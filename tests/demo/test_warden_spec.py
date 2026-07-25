"""The instance spec the warden *requests* of Docker (whitepaper claims 2, 5, 7).

``constants.build_instance_create_kwargs`` is the single place the hardening
flags live, and the authz shim validates every create body against the same
spec — so if a flag silently disappears here, the shim would happily approve the
weakened container. These tests pin each flag the whitepaper cites.

**Scope, stated honestly:** this proves what the warden *asks for*. That dockerd
*applied* it is a different claim, verified against a real daemon by
``docker inspect`` (``deploy/VERIFY.md`` proofs 2, 3, 13). Both halves are
needed: the live check without this one would not catch a flag being dropped
from the spec on a code path CI never exercises.
"""

from __future__ import annotations

import base64
import secrets

import pytest

from demo.warden import constants as C

pytestmark = pytest.mark.unit


@pytest.fixture
def spec() -> dict:
    return C.build_instance_create_kwargs(
        api_key="test-api-key", fernet_key="test-fernet-key",
        created_at=1_700_000_000, instance_id="abc123def456",
    )


# ── Filesystem (claim 2: the instance cannot write to disk) ──────────────────
def test_rootfs_is_read_only(spec):
    assert spec["read_only"] is True


def test_both_declared_volume_paths_are_tmpfs(spec):
    """The image declares ``VOLUME ["/app/configs", "/app/data"]``. Missing
    either one makes Docker create a persistent anonymous *host-disk* volume,
    which would falsify "zero volumes" while every other flag still looked right.
    """
    for path in ("/app/data", "/app/configs"):
        assert path in spec["tmpfs"], f"{path} must be RAM-backed, not a host volume"


def test_tmp_is_tmpfs_for_spooled_uploads(spec):
    """Starlette spools multipart bodies over ~1 MB to /tmp — a pasted config
    must never land on disk there."""
    assert "/tmp" in spec["tmpfs"]


@pytest.mark.parametrize("path", ["/tmp", "/app/data", "/app/configs"])
def test_every_tmpfs_is_noexec_nosuid_and_group_writable(spec, path):
    options = spec["tmpfs"][path]
    assert "noexec" in options
    assert "nosuid" in options
    # A Docker tmpfs shadows the image dir with a fresh ROOT-owned mount, but the
    # image runs as uid 1000 (USER app) and must mkdir /app/data/jobs. Without
    # this the instance exits(3) on a PermissionError — found at Gate-1.
    assert "mode=1777" in options
    assert "size=" in options, "an unbounded tmpfs is a host-memory DoS"


def test_no_bind_mounts_or_volumes_are_requested(spec):
    for forbidden in ("volumes", "binds", "mounts", "volumes_from"):
        assert forbidden not in spec


# ── RAM containment (claim 5: nothing can page or dump to disk) ───────────────
def test_memory_limit_equals_swap_limit(spec):
    """Equal limits mean zero swap allowance even if the host had swap."""
    assert spec["mem_limit"] == spec["memswap_limit"] == C.INSTANCE_MEM_LIMIT


def test_cpu_and_pid_limits_are_set(spec):
    assert spec["nano_cpus"] == C.INSTANCE_NANO_CPUS
    assert spec["pids_limit"] == C.INSTANCE_PIDS_LIMIT


# ── Privilege (the authz-shim's pinned fields) ───────────────────────────────
def test_all_capabilities_are_dropped(spec):
    assert spec["cap_drop"] == ["ALL"]
    assert "cap_add" not in spec
    assert "privileged" not in spec


def test_no_new_privileges_is_the_only_security_opt(spec):
    """The shim requires an exact match, so an appended seccomp=unconfined
    cannot ride along."""
    assert spec["security_opt"] == ["no-new-privileges:true"]


def test_no_uid_override(spec):
    """The image is already non-root (uid 1000 via ``USER app``); forcing a
    different uid breaks tmpfs ownership."""
    assert "user" not in spec


def test_instance_joins_only_the_internal_network(spec):
    assert spec["network"] == C.INSTANCE_NETWORK == "demo-int"


def test_image_is_the_pinned_reference(spec):
    assert spec["image"] == C.INSTANCE_IMAGE


# ── Logging (claim 4: your paste appears in no log, anywhere) ─────────────────
def test_container_log_driver_is_none(spec):
    assert spec["log_config"] == {"type": "none"}


def test_log_level_excludes_parsed_fragments(spec):
    """Bodies are never logged at any level; ``warning`` also excludes the
    parsed fragments that ``debug`` would emit."""
    assert spec["environment"]["NETCANON_LOG_LEVEL"] == "warning"


# ── Labels (the backstop's only handle on a container) ───────────────────────
def test_labels_carry_creation_time_and_instance_id_but_never_the_token(spec):
    labels = spec["labels"]
    assert labels[C.LABEL_CREATED_AT] == "1700000000"
    assert labels[C.LABEL_INSTANCE] == "abc123def456"
    # The routing token does not exist at create time and labels are immutable.
    assert len(labels) == 2


# ── Environment / keys (claim 7: the Fernet key is never written to disk) ─────
def test_instance_env_is_exactly_the_expected_keys(spec):
    assert set(spec["environment"]) == {
        "NETCANON_API_KEY",
        "NETCANON_HOST",
        "NETCANON_PORT",
        "NETCANON_LOG_LEVEL",
        "NETCANON_FERNET_KEY",
    }


def test_instance_binds_all_interfaces_on_the_internal_net_only(spec):
    assert spec["environment"]["NETCANON_HOST"] == "0.0.0.0"
    assert spec["environment"]["NETCANON_PORT"] == str(C.INSTANCE_PORT) == "8000"


def test_api_key_is_injected_so_the_non_loopback_bind_is_gated(spec):
    assert spec["environment"]["NETCANON_API_KEY"] == "test-api-key"


async def test_generated_fernet_key_is_valid_and_per_instance(warden):
    """Injecting a valid Tier-1 key is what stops netcanon ever reaching its
    file fallback at ``data/.fernet_key`` — so no key file is created at all."""
    from cryptography.fernet import Fernet

    await warden.fill_pool()
    keys = [
        call["environment"]["NETCANON_FERNET_KEY"]
        for call in warden.docker.create_calls
    ]
    assert len(keys) >= 2

    for key in keys:
        assert len(base64.urlsafe_b64decode(key)) == 32, "must be a 256-bit key"
        Fernet(key)  # raises if netcanon could not actually use it

    assert len(set(keys)) == len(keys), "keys must be per-instance, never shared"


async def test_api_keys_are_per_instance(warden):
    await warden.fill_pool()
    api_keys = [c["environment"]["NETCANON_API_KEY"] for c in warden.docker.create_calls]
    assert len(set(api_keys)) == len(api_keys)


# ── Token entropy (claim 1: a routing token is a bearer credential) ──────────
def test_routing_token_is_128_bits():
    assert C.TOKEN_NBYTES == 16


def test_token_generator_is_unique_and_url_safe():
    """Pins the generator configuration the warden mints with. (The mint loop
    itself is covered in ``test_warden_lifecycle.py``.)"""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    tokens = {secrets.token_urlsafe(C.TOKEN_NBYTES) for _ in range(10_000)}

    assert len(tokens) == 10_000, "token collision in 10k draws"
    for token in tokens:
        assert set(token) <= allowed
        assert len(token) >= 22


# ── Lifecycle constants must stay mutually consistent ────────────────────────
def test_pool_recycle_age_keeps_assignments_under_pool_max_age():
    assert C.POOL_RECYCLE_AGE == C.POOL_MAX_AGE - C.REAPER_PERIOD
    assert C.POOL_RECYCLE_AGE < C.POOL_MAX_AGE


def test_idle_ttl_is_shorter_than_the_hard_ceiling():
    assert C.IDLE_TTL_TIGHT < C.IDLE_TTL < C.HARD_TTL


def test_occupancy_thresholds_leave_a_dead_band():
    assert C.OCCUPANCY_LOOSEN < C.OCCUPANCY_TIGHTEN, "hysteresis needs a gap"


def test_hidden_stale_window_is_more_forgiving_than_visible():
    """Background tabs get throttled timers; reaping them on the visible
    threshold would kill sessions mid-demo."""
    assert C.HB_STALE_HIDDEN > C.HB_STALE_VISIBLE > C.HB_INTERVAL


def test_pool_fits_inside_the_global_cap():
    assert C.POOL_SIZE < C.MAX_ACTIVE
