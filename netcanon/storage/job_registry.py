"""
LRU-bounded in-memory cache of ``BackupJob`` objects.

Disk (via :class:`FileJobStore`) is the source of truth — every job is
persisted to ``jobs/{id}.json``.  The in-memory registry caches the
most-recent N jobs for fast API access; older jobs transparently
lazy-load from disk on get-by-id.

Pre-R8 the in-memory cache was an unbounded ``dict``: every job ever
created stayed in memory forever, so a server that handled 100,000
jobs over its lifetime held ~500 MB of ``BackupJob`` objects.  This
class caps memory usage at ``max_memory_jobs`` (default 1000) without
losing historical visibility — older jobs are still queryable by ID
via the disk fallback.

The registry intentionally mirrors the ``dict``-like surface the route
handlers already use (``__setitem__`` / ``__getitem__`` / ``__contains__``
/ ``__len__`` / ``values()`` / ``get()``) so swapping ``app.state.jobs``
to a registry instance requires no route-handler changes.

Semantic notes:

* ``__len__`` returns the **memory-resident** count, NOT the total disk
  count.  Use :meth:`total_disk_count` for the operator-meaningful
  "jobs ever recorded" number.  The :func:`get_jobs` dependency is
  used for the list endpoint (which wants memory-resident only) and
  the health probe (which wants responsiveness over historical
  accounting), so a fast in-memory ``len()`` is the right default.
* ``values()`` returns memory-resident jobs only.  Old jobs (evicted)
  do NOT appear in ``values()`` — they require a get-by-id lookup,
  which lazy-loads from disk.  The Jobs UI page shows recent jobs
  first and operators rarely scroll past the most-recent 50, so the
  cap is practically invisible at default settings.
* ``__getitem__`` lazy-loads from disk on a memory miss.  The loaded
  job is promoted into the cache (potentially evicting an even-older
  job to make room) so repeated reads of the same historical job stay
  fast.  ``KeyError`` is raised only if the job doesn't exist on disk
  either.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Iterator, ValuesView

from ..models.backup import BackupJob
from .job_store import FileJobStore

logger = logging.getLogger(__name__)


# Default cap on memory-resident jobs.  Sized for the typical Netcanon
# deployment (tens-to-hundreds of devices, schedules running hourly to
# daily, ~10k jobs/year).  At ~5 KB per BackupJob this caps memory at
# ~5 MB.  Override via the ``NETCANON_MAX_MEMORY_JOBS`` env var (read
# in main.py).
DEFAULT_MAX_MEMORY_JOBS = 1000


class BackupJobRegistry:
    """LRU-bounded in-memory cache of ``BackupJob`` objects.

    Disk-backed: every memory miss falls through to
    :meth:`FileJobStore.load_one`.  Insertions over the cap evict the
    least-recently-used entry from memory (but NOT from disk —
    persistence is independent of this cache).

    Args:
        job_store: The :class:`FileJobStore` whose data this registry
            caches.  Disk is the source of truth.
        max_memory_jobs: Cap on memory-resident jobs.  Default 1000
            (~5 MB).  Setting this to 0 disables caching entirely
            (every read hits disk).
        warm_cache: When True (default), the constructor preloads the
            ``max_memory_jobs`` most-recent jobs from disk so the API
            is fast on the common case (recent jobs) post-restart.
            When False, the cache starts empty and warms lazily.
            Disable for tests that want deterministic starting state.
    """

    def __init__(
        self,
        job_store: FileJobStore,
        max_memory_jobs: int = DEFAULT_MAX_MEMORY_JOBS,
        warm_cache: bool = True,
    ) -> None:
        if max_memory_jobs < 0:
            raise ValueError(
                "max_memory_jobs must be >= 0, got {!r}".format(max_memory_jobs)
            )
        self._store = job_store
        self._max = max_memory_jobs
        self._cache: OrderedDict[str, BackupJob] = OrderedDict()
        if warm_cache and max_memory_jobs > 0:
            self._warm_from_disk()

    def _warm_from_disk(self) -> None:
        """Preload up to ``max_memory_jobs`` most-recent jobs at startup.

        Uses the disk's full ``load_all()`` then trims — for installs
        with <10k jobs this is fast.  For installs that have run the
        server long enough to accumulate 100k+ jobs, startup will take
        proportional time (one JSON parse per job); the v0.2.0
        optimisation path is to stat-sort by mtime and parse only the
        newest N.
        """
        all_jobs = self._store.load_all()
        # Sort newest-first by created_at, take the most-recent N.
        sorted_jobs = sorted(
            all_jobs.values(),
            key=lambda j: j.created_at,
            reverse=True,
        )[: self._max]
        # Insert oldest-first so the newest end up at the OrderedDict
        # tail (the LRU "most recent" position).
        for job in reversed(sorted_jobs):
            self._cache[job.id] = job
        logger.info(
            "BackupJobRegistry warmed: %d job(s) in memory "
            "(disk has %d, cap=%d)",
            len(self._cache),
            len(all_jobs),
            self._max,
        )

    # ── Dict-like surface used by the route handlers ─────────────────

    def __setitem__(self, job_id: str, job: BackupJob) -> None:
        """Insert or update a job in the cache.

        Existing entries move to the MRU position (end of OrderedDict);
        new entries are appended and trigger LRU eviction if the cache
        would exceed ``max_memory_jobs``.  Eviction is memory-only —
        the evicted job remains on disk and is still retrievable via
        :meth:`__getitem__`.
        """
        if self._max == 0:
            # Caching disabled — drop on the floor; disk persistence
            # is the responsibility of the caller (job_store.save).
            return
        if job_id in self._cache:
            # Existing entry: move to MRU + replace.
            self._cache.move_to_end(job_id)
            self._cache[job_id] = job
            return
        self._cache[job_id] = job
        if len(self._cache) > self._max:
            # Pop the LRU entry (the oldest insertion still in cache).
            evicted_id, _ = self._cache.popitem(last=False)
            logger.debug(
                "BackupJobRegistry evicted %s (cache at cap %d)",
                evicted_id,
                self._max,
            )

    def __getitem__(self, job_id: str) -> BackupJob:
        """Return the job with this ID.

        Memory hit → O(1) return + LRU position refresh.
        Memory miss → disk read via ``load_one``.  If found, the job
        is promoted into the cache (which may evict an even-older
        entry).  If absent from disk, ``KeyError`` is raised — same
        semantics as a plain ``dict``.
        """
        if job_id in self._cache:
            self._cache.move_to_end(job_id)
            return self._cache[job_id]
        # Lazy-load from disk.
        job = self._store.load_one(job_id)
        if job is None:
            raise KeyError(job_id)
        # Promote to cache (may evict).
        self[job_id] = job
        return job

    def __contains__(self, job_id: object) -> bool:
        """``job_id in registry`` — checks memory then disk.

        Disk check is a cheap ``path.exists()`` (no JSON parse).
        Returns False for non-string keys (mirrors dict semantics
        but defensive against ``in`` checks with arbitrary types).
        """
        if not isinstance(job_id, str):
            return False
        if job_id in self._cache:
            return True
        return (self._store._dir / f"{job_id}.json").exists()

    def __len__(self) -> int:
        """Number of MEMORY-resident jobs.

        Intentionally fast — used by the health probe + UI counters.
        Use :meth:`total_disk_count` for the full disk total.
        """
        return len(self._cache)

    def __iter__(self) -> Iterator[str]:
        """Iterate memory-resident job IDs in insertion (LRU) order."""
        return iter(self._cache)

    def values(self) -> ValuesView[BackupJob]:
        """Memory-resident jobs.  Order is LRU (oldest first)."""
        return self._cache.values()

    def keys(self):
        """Memory-resident job IDs.  Order is LRU."""
        return self._cache.keys()

    def get(
        self, job_id: str, default: BackupJob | None = None,
    ) -> BackupJob | None:
        """Dict-style ``get`` with default.

        Triggers a disk lazy-load on memory miss.  Returns ``default``
        only when the job isn't on disk either.
        """
        try:
            return self[job_id]
        except KeyError:
            return default

    # ── Registry-specific surface ───────────────────────────────────

    def total_disk_count(self) -> int:
        """Total number of jobs persisted to disk.

        O(n) directory scan but does NOT parse the JSON files.  Use
        sparingly — appropriate for diagnostic / health endpoints
        but not for hot paths.
        """
        return len(self._store.list_job_ids())

    @property
    def max_memory_jobs(self) -> int:
        """The memory cap this registry was configured with."""
        return self._max
