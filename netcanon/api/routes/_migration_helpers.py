"""
Helpers extracted from :mod:`netcanon.api.routes.migration` for the
``refactor/god-file-cleanup`` branch.

Public surface:

* :func:`resolve_adapter_or_422` — translate adapter-name lookup
  errors into 422s with side-aware ``source`` / ``target`` framing.
* :func:`resolve_input_text` — return the raw config text referenced
  by a request body that names its config one of the two ways
  (:class:`HasInputText`: a plan request, a detect-deployment
  request), enforcing the ``raw_text`` XOR ``source_filename``
  invariant and translating storage misses into 404s.
* :func:`get_target_profiles` — pull the target-profile registry
  from ``request.app.state``; returns an empty dict when the
  attribute is absent (some unit-test fixtures don't run the full
  lifespan).
* :func:`build_codec_info_list` — shape the registered codec list
  into :class:`CodecInfo` records for ``GET /adapters``, joining
  each codec's :class:`CapabilityMatrix` with the corresponding
  vendor's ``display_name``.
* :func:`request_has_overrides_or_profile` — boolean predicate that
  decides whether ``POST /plan`` should route through the
  rename-aware :func:`run_plan_with_overrides` (any per-category
  map present, or a target profile selected).
* :func:`get_model_families` — pull the device-model registry from
  ``request.app.state``.
* :func:`compile_declared_device` — turn one side's declaration (a
  deployment, or a flat target-profile key) into a port inventory,
  translating every way it can be wrong into a 422.
* :func:`resolve_port_inventories` — both sides of a request, or
  ``None`` when the request does not declare its source device.
* :func:`a_device_is_described` — whether an operator can declare a
  device of a codec's vendor: a model family or a target profile.
* :func:`run_translation` — the one place every job-running handler
  dispatches from: model-aware when the request declares both
  devices, the rename-aware pipeline and its check of the finished
  run otherwise, with the body's own port map either way.  It opens
  the server's scope for the request, and so takes the request's turn
  where the limits say how many work at once.
* :func:`request_limits` — the name of the limits this server is set
  to; every handler that hands config text to a parser opens
  :func:`~netcanon.migration.limits.server_scope` with it.
* :class:`AnswerSent` and :func:`request_answer` — the middleware
  that keeps an :class:`~netcanon.migration.limits.Answer` for every
  request and says when the answer has gone out, and the way a
  handler finds its request's.  A request's turn is held until then.
  Where the limits say how many requests work at once, it also
  counts a request that would read config text
  (:func:`reads_config_text`, :data:`READS_CONFIG_TEXT`) when its
  headers arrive -- one that finds every place taken is answered
  503 with its body unread -- and at the request's deadline it
  abandons an answer that has not gone out.
* :func:`job_answer` and :func:`json_pieces` — a job as its answer,
  written to JSON a piece at a time.  Every job-running handler
  returns it.
* :func:`listening_sockets` — what a launcher starts the server on:
  under those limits, a socket on which the system itself ends a
  connection whose client takes nothing.
* :func:`refusal_as_http` — a refusal as the answer of a handler
  that returns no job: 413 for a config past a limit, 503 with
  ``Retry-After`` for a request that did not get a turn, or got
  it too late to finish.

Routes orchestrate; these helpers compute.  None of these touch the
frozen pipeline-stage signatures in
:mod:`netcanon.services.migration_pipeline` — they live one layer
above the pipeline, on the request-shaping / response-shaping side.

Why a separate module?  The route file used to mix request
validation, capability-matrix shaping, target-profile resolution,
and pipeline dispatch in one ~750-LOC file.  Lifting these helpers
into a sibling keeps ``migration.py`` focussed on FastAPI route
declarations + thin glue, and lets each helper acquire focussed
unit-test coverage in :mod:`tests.unit.api.test_migration_helpers`
without spinning up a TestClient.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Iterator
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, TypeAdapter

from ...migration.codecs.base import CodecBase
from ...migration.codecs.registry import get_codec, list_public_codecs
from ...migration.device_models import (
    Deployment,
    DeploymentError,
    DeploymentSpec,
    DeviceModelRegistry,
    Inventory,
    compile_deployment,
    inventory_from_profile,
)
from ...migration.limits import (
    AT_ONCE,
    Answer,
    LimitExceeded,
    Limits,
    body_late,
    resolve,
    server_scope,
)
from ...migration.target_profiles import TargetProfile
from ...models.migration import (
    CodecInfo,
    MigrationJob,
    MigrationJobStatus,
    MigrationPlanRequest,
    Refusal,
)
from ...services.migration_pipeline import (
    run_plan_with_checked_names,
    run_plan_with_models,
)
from ...storage.base import BaseConfigStore

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: The paths whose ``POST`` hands config text to a parser: the seven
#: that return a job, the two that read a vendor or a device out of
#: a paste, and the sanitiser.  Where the limits say how many
#: requests work at once, a request to one of these is COUNTED when
#: its headers arrive (:class:`AnswerSent`).  A handler that takes
#: config text and is not here is not counted, and its body is read
#: before anything limits it:
#: ``tests/integration/test_config_limits_api.py`` finds the
#: handlers by what they take, sends each a request, and fails for
#: one that is not counted -- and for a path here that no such
#: handler answers.
READS_CONFIG_TEXT = frozenset({
    "/api/v1/migration/plan",
    "/api/v1/migration/plan/ports",
    "/api/v1/migration/plan/vlans",
    "/api/v1/migration/plan/local_users",
    "/api/v1/migration/plan/snmp",
    "/api/v1/migration/plan/snmpv3",
    "/api/v1/migration/render",
    "/api/v1/migration/detect",
    "/api/v1/migration/detect-deployment",
    "/api/v1/sanitize",
})

#: The most bytes of an answer that are handed to the server at a
#: time, for a request that holds a place (:class:`_InItsTime`).  It
#: is the size at which a server stops taking more until the client
#: has read.
WRITE = 65_536

#: The seconds a client that was told "busy" is asked to leave before
#: it sends the request again (``Retry-After``).  The work in front of
#: it is a few seconds at most under the limits that make a request
#: wait; this is long enough not to arrive in the same line again.
BUSY_RETRY_AFTER = 5

#: The entries of a long list that are written to JSON at a time
#: (:func:`json_pieces`).
LIST_RUN = 2_000

#: An answer of more bytes than this is sent piece by piece, and one
#: of fewer as one body: every ordinary job is one body, as ever.
WHOLE_ANSWER = 1_000_000

_FIELD_WRITERS: dict[tuple[type[BaseModel], str], tuple[bytes, TypeAdapter[Any]]] = {}

#: Where a request's :class:`Answer` is kept, in its ASGI scope.
_ANSWER_KEY = "netcanon.answer"


class AnswerSent:
    """ASGI middleware: keeps an :class:`Answer` for every HTTP
    request, and tells it when the answer has gone out.

    A handler that reads config text opens the server's scope with
    its request's ``Answer`` (:func:`request_answer`).  Where the
    limits say how many requests work at once, the request's turn
    then stays taken after the handler returns -- while the answer
    is made into bytes and written to the client -- and comes back
    here, when the application has finished with the request: sent,
    failed, or abandoned by its client.

    Under such limits it does three more things, for a request that
    would read config text (:func:`reads_config_text`) and for no
    other:

    * **It counts the request when its headers arrive, before its
      body is read** (:meth:`Answer.arrived`).  A body is memory, and
      it used to be read before the request could ask for a turn, so
      requests that arrived together added up however few of them
      were let work.  There are as many places as may work and wait.
      A request that finds them taken is answered here, at once --
      503 with ``Retry-After`` and the sentence a busy server gives
      -- and its body is never asked for.
    * **It holds the request to one deadline, counted from then**
      (:class:`_InItsTime`): the body has that long to arrive, and
      the answer to be read.
    * **At that deadline it abandons an answer that has not gone
      out**: nothing more of it is sent, what was held for it is let
      go, the connection is closed, and the log says so in counts.
      A turn that was lent to the answer comes back with it.

    Under any other limits, and for every other request (a ``GET``,
    ``/health``, the pages), it passes everything through.

    It has to be the OUTERMOST middleware.  The others pass an
    answer's bytes on; only when the call below returns have they
    left the process.  ``create_app`` adds it last, which is what
    makes it so.

    Args:
        app: The application inside.
        limits: The limits this server is set to: a
            :class:`~netcanon.migration.limits.Limits`, the name of
            a profile, or ``None`` for the standard ones.  A name is
            looked up for every request.
    """

    def __init__(self, app: Any, limits: Limits | str | None = None) -> None:
        self.app = app
        self.limits = limits

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        answer = scope[_ANSWER_KEY] = Answer()
        try:
            if not reads_config_text(scope):
                await self.app(scope, receive, send)
                return
            try:
                answer.arrived(self.limits)
            except LimitExceeded as exc:
                # Every place is taken.  Answered now, in words, and the
                # body is not asked for: the server discards it as it
                # comes in.
                await _answer_in_words(send, 503, exc, [(b"retry-after", str(BUSY_RETRY_AFTER).encode())])
                return
            if answer.deadline is None:
                await self.app(scope, receive, send)
                return
            await _InItsTime(self.app, scope, receive, send, answer, resolve(self.limits)).run()
        finally:
            answer.sent()


def reads_config_text(scope: Any) -> bool:
    """Whether the request of *scope* is one that would read config
    text: a ``POST`` to one of :data:`READS_CONFIG_TEXT`.

    Decided from the method and the path alone, because it is asked
    when only the headers have arrived.
    """
    if scope.get("method") != "POST":
        return False
    path, root = scope.get("path", ""), scope.get("root_path", "")
    if root and path.startswith(root) and path[len(root):].startswith("/"):
        # A server that was told it is mounted under a prefix hands the
        # whole path over; routes are matched without the prefix.
        path = path[len(root):]
    return path in READS_CONFIG_TEXT


async def _answer_in_words(
    send: Any, status: int, exc: LimitExceeded, headers: list[tuple[bytes, bytes]],
) -> None:
    """A refusal, sent from the middleware itself: the body a handler's
    ``HTTPException`` has (``{"detail": "Refused: ..."}``)."""
    body = json.dumps(
        {"detail": f"Refused: {exc}"}, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    await send({
        "type": "http.response.start", "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"x-content-type-options", b"nosniff"),
            *headers,
        ],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _no_longer_than(
    awaited: Awaitable[_T], seconds: float | None, also: asyncio.Future[None] | None = None,
) -> tuple[bool, _T | None]:
    """*awaited*, for at most *seconds* (``None``: as long as it
    takes) or until *also* is done, whichever is first.

    Returns:
        ``(True, its result)``, or ``(False, None)`` when it was not
        finished in time: it is then cancelled, and nothing of it is
        left running.  With zero seconds it gets one chance to finish
        without waiting for anything.
    """
    task = asyncio.ensure_future(awaited)
    try:
        await asyncio.wait(
            {task} if also is None else {task, also},
            timeout=None if seconds is None else max(0.0, seconds),
            return_when=asyncio.FIRST_COMPLETED,
        )
        finished = task.done()
    finally:
        # Not finished in time, or this wait was itself cancelled.
        if not task.done():
            task.cancel()
    return (True, task.result()) if finished else (False, None)


class _InItsTime:
    """One request that holds a place, between the server and the
    application: what it may wait for the client for, and until when.

    The application inside waits for the client in two places.  It
    waits for the BODY (``receive``), and it waits for the client to
    READ (``send``: a server lets ``send`` return only when what was
    written before has left its buffer).  Neither wait has an end of
    its own, and each holds memory: a place and whatever of the body
    has come in, or an answer that can be tens of megabytes and the
    turn that was lent to it.  A client that sends nothing more, or
    reads nothing, would hold them for as long as it kept its
    connection.

    So both waits end at the request's deadline
    (:attr:`Answer.deadline`).  What the application is then told is
    what it is told when a client leaves -- ``receive`` says
    ``http.disconnect``, and ``send`` takes what it is given and
    drops it -- which every part of it already knows how to handle,
    and which lets a streamed answer run to its end and let go of
    its pieces as it does.  When the application has returned:

    * a request whose body had not arrived is answered 408, in
      words, and its connection closed;
    * an answer that had not gone out is left unfinished, which
      makes the server close the connection.

    Only WAITING is bounded.  An answer that is made after the
    deadline -- the refusal of a request that stood in the line for
    its whole time, or was out of time in a parser -- is sent, as far
    as it goes without waiting for the client: a refusal is a few
    hundred bytes, and goes.  And a client that reads, however
    slowly, is not cut inside the deadline.

    An answer is handed to the server at most :data:`WRITE` bytes at
    a time.  A server takes whatever it is handed into its buffer at
    once; handed a body whole, it would hold megabytes that this
    cannot let go of, and "gone out" would mean no more than "in the
    buffer".
    """

    def __init__(
        self, app: Any, scope: Any, receive: Any, send: Any, answer: Answer, limits: Limits,
    ) -> None:
        self.app, self.scope, self.answer, self.limits = app, scope, answer, limits
        self._receive, self._send = receive, send
        #: Why the request was ended at its deadline: ``body`` (it had
        #: not arrived), ``answer`` (it had not gone out); ``""`` while
        #: it has not been.
        self.ended = ""
        self._at_end: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.body_in = False
        self.body_bytes = 0
        self.started = False
        self.declared: int | None = None
        self.handed = 0

    def _end(self, why: str) -> None:
        if not self.ended:
            self.ended = why
            self._at_end.set_result(None)

    async def receive(self) -> Any:
        if self.ended:
            return {"type": "http.disconnect"}
        # Until the body is in, the wait is for the body and ends at the
        # deadline.  After that the application is listening for the
        # client to leave, which can take as long as the answer does.
        left = None if self.body_in else self.answer.left()
        came, message = await _no_longer_than(self._receive(), left, self._at_end)
        if not came:
            self._end("body")
            return {"type": "http.disconnect"}
        if message["type"] == "http.request":
            self.body_bytes += len(message.get("body") or b"")
            self.body_in = not message.get("more_body", False)
        return message

    async def _hand(self, message: Any) -> bool:
        """Hand *message* to the server, waiting for the client no
        longer than the request's deadline; whether it went."""
        went, _ = await _no_longer_than(self._send(message), self.answer.left(), self._at_end)
        if not went:
            self._end("answer")
        return went

    async def send(self, message: Any) -> None:
        if self.ended:
            return
        if message["type"] != "http.response.body":
            if await self._hand(message) and message["type"] == "http.response.start":
                self.started = True
                for name, value in message.get("headers") or ():
                    if name.lower() == b"content-length" and value.isdigit():
                        self.declared = int(value)
            return
        body = message.get("body") or b""
        if len(body) <= WRITE:
            if await self._hand(message):
                self.handed += len(body)
            return
        last, view = not message.get("more_body", False), memoryview(body)
        for start in range(0, len(view), WRITE):
            piece = bytes(view[start:start + WRITE])
            more = not (last and start + WRITE >= len(view))
            if not await self._hand({"type": "http.response.body", "body": piece, "more_body": more}):
                return
            self.handed += len(piece)

    async def run(self) -> None:
        fault = ""
        try:
            await self.app(self.scope, self.receive, self.send)
        except LimitExceeded:
            # A refusal is every handler's to answer, and none lets one
            # out; one that did is not made to vanish here.
            raise
        except Exception as exc:
            if not self.ended:
                raise
            # What the application made of being told its client had
            # gone.  The request is over either way; the log names it.
            fault = f"; the application then raised {type(exc).__name__}"
        if not self.ended:
            return
        path, seconds = self.scope.get("path", ""), self.limits.seconds or 0
        # Counts, a path of the application and the name of the limits:
        # nothing of what the request carried.
        if self.ended == "body" and not self.started:
            logger.warning(
                "the body of a request to %s had not arrived when its %g seconds "
                "(%s limits) were up: %d bytes of it had; answered 408, and its "
                "place given back%s",
                path, seconds, self.limits.name, self.body_bytes, fault,
            )
            refusal = body_late(self.limits, seconds - (self.answer.left() or 0.0))
            # With nothing waited for: the client has stopped sending, and
            # may have stopped reading.
            await _no_longer_than(
                _answer_in_words(self._send, 408, refusal, [(b"connection", b"close")]), 0.0,
            )
            return
        logger.warning(
            "an answer from %s had not gone out when its request's %g seconds "
            "(%s limits) were up, and was abandoned: %d of %s bytes had been "
            "handed to the client; the rest was let go and the connection "
            "closed%s",
            path, seconds, self.limits.name, self.handed,
            "an undeclared number of" if self.declared is None else f"{self.declared:,}",
            fault,
        )


def listening_sockets(config: Any, limits: Limits | str | None) -> list[socket.socket] | None:
    """What a launcher starts the server of *config* on, under
    *limits*: a socket bound here, on which the system ends a
    connection whose client takes nothing -- or ``None``, for a
    server that binds its own as it always has.

    An answer nobody reads is abandoned at its request's deadline
    (:class:`AnswerSent`), and the server then closes the
    connection.  But a server closes a connection when what it has
    already written has been taken, and a client that takes nothing
    keeps it: measured in a 256 MiB container, three megabytes of
    socket buffer a connection, charged to the server, and
    twenty-one such connections were the whole of its memory.
    Nothing in the application can end such a connection.  The
    system can: ``TCP_USER_TIMEOUT`` on a listening socket is given
    to every connection accepted from it, and ends one whose peer
    has taken nothing (or acknowledged nothing) for that long.  It
    is set to the seconds a request may take.  A client that reads,
    however slowly, is not affected: the time starts again whenever
    it takes something.

    Only under limits that say how many requests work at once, and
    only where the system has the option (Linux).  Everywhere else
    nothing is bound and nothing changes.

    Args:
        config: The server's ``uvicorn.Config``; its
            ``bind_socket()`` binds the address it names.
        limits: The limits the server is set to.

    Returns:
        ``[the bound socket]`` to hand to ``Server.run(sockets=...)``,
        or ``None``.
    """
    resolved = resolve(limits)
    option = getattr(socket, "TCP_USER_TIMEOUT", None)
    if resolved.at_once is None or resolved.seconds is None or option is None:
        return None
    bound = config.bind_socket()
    try:
        bound.setsockopt(socket.IPPROTO_TCP, option, int(resolved.seconds * 1000))
    except OSError as exc:
        # A system that names the option and does not take it: the
        # server still starts, on the socket that is bound.
        logger.warning(
            "the listening socket did not take TCP_USER_TIMEOUT (%s): a connection whose "
            "client reads nothing is kept until the client lets go", type(exc).__name__,
        )
    return [bound]


def resolve_adapter_or_422(name: str, side: str):
    """Return the named adapter or raise a 422 with a helpful message.

    Uses 422 not 404 because the adapter name is REQUEST-PAYLOAD data;
    callers should fix their body, not their URL.
    """
    try:
        return get_codec(name)
    except LookupError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unknown {side} adapter: {exc}",
        ) from exc


class HasInputText(Protocol):
    """A request body that names its config one of the two ways."""

    raw_text: str | None
    source_filename: str | None


def resolve_input_text(
    body: HasInputText, storage: BaseConfigStore
) -> str:
    """Return the raw config text referenced by *body*.

    Exactly one of ``raw_text`` / ``source_filename`` MUST be set.
    Raises:
        HTTPException 422: If both are set or neither is set.
        HTTPException 404: If ``source_filename`` refers to a file
            that doesn't exist.
    """
    has_text = body.raw_text is not None
    has_file = body.source_filename is not None
    if has_text == has_file:
        raise HTTPException(
            status_code=422,
            detail=(
                "Exactly one of `raw_text` or `source_filename` is required."
            ),
        )
    if has_text:
        return body.raw_text or ""
    try:
        return storage.get_content(body.source_filename or "")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"source_filename not found: {body.source_filename!r}",
        ) from exc


def get_target_profiles(request: Request) -> dict[str, TargetProfile]:
    """Pull the target-profile registry from ``request.app.state``.

    Profiles are loaded once at app startup (see ``main.py`` lifespan)
    and exposed through ``app.state.target_profiles``.  ``getattr`` with
    a default makes this safe under the bare-app fixtures used by some
    unit tests, which don't populate the full lifespan-loaded state —
    those tests get an empty dict and the route returns an empty list
    rather than raising AttributeError.

    Args:
        request: The current request; only its ``app.state`` is consulted.

    Returns:
        Mapping of ``"<vendor>/<model>"`` keys to ``TargetProfile``
        instances.  Empty when no profiles are loaded.
    """
    return getattr(request.app.state, "target_profiles", {})


def build_codec_info_list(vendors: dict) -> list[CodecInfo]:
    """Return one :class:`CodecInfo` per registered codec.

    Each entry includes the linked vendor's ``display_name`` (resolved
    from *vendors*, typically ``request.app.state.vendors``) so the UI
    can group codecs by vendor without a second round-trip.

    Args:
        vendors: Mapping of ``vendor_id`` to a vendor record exposing
            a ``display_name`` attribute.  Pass ``{}`` when the vendor
            registry isn't populated; missing entries fall back to an
            empty display name.

    Returns:
        One :class:`CodecInfo` per name in
        :func:`netcanon.migration.codecs.registry.list_codecs`, in
        registry-iteration order.
    """
    result: list[CodecInfo] = []
    for name in list_public_codecs():
        codec = get_codec(name)
        caps = codec.capabilities
        vendor = vendors.get(caps.vendor_id)
        result.append(
            CodecInfo(
                name=caps.adapter,
                vendor_id=caps.vendor_id,
                vendor_display_name=vendor.display_name if vendor else "",
                version_range=caps.version_range,
                device_classes=list(caps.device_classes),
                input_format=getattr(codec, "input_format", "unknown"),
                direction=getattr(codec, "direction", "bidirectional"),
                certainty=getattr(codec, "certainty", "experimental"),
                canonical_model=getattr(codec, "canonical_model", "openconfig-lite"),
                supported_count=len(caps.supported),
                lossy_count=len(caps.lossy),
                unsupported_count=len(caps.unsupported),
                description=getattr(codec, "description", ""),
                sample_input=getattr(codec, "sample_input", ""),
                output_extension=getattr(codec, "output_extension", ""),
                unsupported_rename_categories=sorted(
                    getattr(codec, "unsupported_rename_categories", frozenset())
                ),
            )
        )
    return result


def request_has_overrides_or_profile(body: MigrationPlanRequest) -> bool:
    """Decide whether ``POST /plan`` should engage the rename-aware pipeline.

    Returns ``True`` when *body* carries ANY per-category override map
    (port / vlan / local-user / SNMP community / SNMPv3 user) OR a
    ``target_profile`` selection.  Target-profile alone means "run
    auto-heuristic + return diagnostics the UI can render," and still
    needs the rename-aware pipeline.

    Requests that supply none of these still get auto port-name
    translation via ``run_plan_with_overrides(port_rename_map={})`` — the
    default ``/plan`` flow (this module imports no bare :func:`run_plan`).
    The ``run_plan`` primitive itself remains unchanged.
    """
    return (
        body.port_rename_map is not None
        or body.vlan_rename_map is not None
        or body.local_user_rename_map is not None
        or body.snmp_community_rename_map is not None
        or body.snmpv3_user_rename_map is not None
        or body.target_profile is not None
    )


def get_model_families(request: Request) -> DeviceModelRegistry:
    """Pull the device-model registry from ``request.app.state``.

    Loaded once at app startup (see ``main.py`` lifespan).  Bare-app
    unit fixtures that skip the lifespan get an empty registry rather
    than an ``AttributeError``.
    """
    registry = getattr(request.app.state, "model_families", None)
    return registry if registry is not None else DeviceModelRegistry()


def compile_declared_device(
    side: str,
    codec: CodecBase,
    deployment: DeploymentSpec | None,
    profile_key: str | None,
    module_sku: str | None,
    profiles: dict[str, TargetProfile],
    families: DeviceModelRegistry,
) -> Inventory:
    """Compile one side's device declaration to a port inventory.

    A declaration is either a deployment (model family, mode,
    members, modules) or the key of a flat target profile.  The
    deployment wins when both are present, which only the target side
    allows: the browser sends ``target_profile`` on every request once
    a profile is picked.

    The vendor is never taken from the request body.  It is the vendor
    of the codec the request already names, so a client cannot declare
    a device of one vendor against a codec of another.

    Args:
        side: ``"source"`` or ``"target"`` — the prefix of the request
            fields being read, so an error names the field at fault
            (``source_deployment``).  ``""`` for a request whose fields
            are plain ``deployment`` / ``profile``.
        codec: That side's codec.
        deployment: The deployment, if one was sent.
        profile_key: ``vendor/model`` of a flat target profile, if sent.
        module_sku: Module choice within that profile, in any case.
            ``None`` selects the profile's default module, ``""``
            states that no module is fitted, and anything else must
            be one of the profile's modules.
        profiles: The loaded target profiles.
        families: The loaded device-model families.

    Raises:
        HTTPException 422: the deployment does not compile (unknown
            model, mode, bay, module or member id — the detail says
            what was wrong and, for a mode, bay, module or member id,
            what is allowed); the profile key is unknown; the profile
            belongs to another vendor than the codec; or the profile
            has no module of that name.  On the advisory path an
            unknown module selects none
            (:meth:`TargetProfile.effective_ports`); here the choice
            decides which ports exist, so a typo is refused rather
            than compiled as a chassis with its uplinks missing.
    """
    vendor = codec.capabilities.vendor_id
    prefix = f"{side}_" if side else ""
    if deployment is not None:
        try:
            return compile_deployment(
                Deployment(vendor=vendor, **deployment.model_dump()), families,
            )
        except DeploymentError as exc:
            raise HTTPException(
                status_code=422, detail=f"{prefix}deployment: {exc}",
            ) from exc
    profile = profiles.get(profile_key or "")
    if profile is None:
        raise HTTPException(
            status_code=422,
            detail=f"{prefix}profile: unknown target profile {profile_key!r}",
        )
    if profile.vendor != vendor:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{prefix}profile: {profile.key} is a {profile.vendor} "
                f"profile, but the codec {codec.name!r} is {vendor}"
            ),
        )
    if module_sku:
        wanted = module_sku.strip().lower()
        match = next((s for s in profile.modules if s.lower() == wanted), None)
        if match is None:
            have = ", ".join(profile.modules) or "none"
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{prefix}module: {profile.key} has no module "
                    f"{module_sku!r} (modules: {have})"
                ),
            )
        module_sku = match
    return inventory_from_profile(profile, module_sku)


def resolve_port_inventories(
    request: Request,
    body: MigrationPlanRequest,
    source: CodecBase,
    target: CodecBase,
) -> tuple[Inventory, Inventory] | None:
    """The source and target inventories *body* declares, if it declares both.

    Positional port mapping engages only when the request says which
    device the config came FROM.  A ``target_profile`` on its own never
    does: the browser sends that field on every Apply once a profile is
    picked, and a request that changes nothing today must not start
    re-pairing ports.

    Returns:
        ``(source_inventory, target_inventory)``, or ``None`` when the
        request does not declare a source device.

    Raises:
        HTTPException 422: the source is declared twice
            (``source_deployment`` and ``source_profile``);
            ``source_module`` is sent without ``source_profile``; a
            source device is declared without a target device; a
            ``target_deployment`` is sent without a source device;
            or either declaration is invalid (see
            :func:`compile_declared_device`).

    The combination checks are made here, as short string details,
    and not by a validator on the request model: a pydantic error
    raised at the body level echoes the whole body — the pasted
    config included — back in the 422.
    """
    if body.source_deployment is not None and body.source_profile is not None:
        raise HTTPException(
            status_code=422,
            detail="send source_deployment or source_profile, not both",
        )
    if body.source_module and body.source_profile is None:
        raise HTTPException(
            status_code=422, detail="source_module needs source_profile",
        )
    if not body.declares_source_device:
        if body.target_deployment is not None:
            # Unlike a bare target_profile -- which the browser sends on
            # every Apply and which must stay advisory -- no older client
            # sends a target deployment, and one without a source can
            # only be half a declaration.  Refusing it beats a completed
            # job that silently paired nothing.
            raise HTTPException(
                status_code=422,
                detail=(
                    "a target device was declared without a source "
                    "device: send source_deployment or source_profile "
                    "as well"
                ),
            )
        return None
    if not body.declares_target_device:
        raise HTTPException(
            status_code=422,
            detail=(
                "a source device was declared without a target device: "
                "send target_deployment or target_profile as well"
            ),
        )
    profiles = get_target_profiles(request)
    families = get_model_families(request)
    return (
        compile_declared_device(
            "source", source, body.source_deployment, body.source_profile,
            body.source_module, profiles, families,
        ),
        compile_declared_device(
            "target", target, body.target_deployment, body.target_profile,
            body.target_module, profiles, families,
        ),
    )


def a_device_is_described(request: Request, codec: CodecBase) -> bool:
    """Whether a device of *codec*'s vendor can be declared: a model
    family of that vendor, or a target profile.  The migrate page
    asks the same of the same registries (``_modelsKnown``).

    A job's sentence offers "declare both devices" only where this
    holds for both sides: for a vendor nobody has described a
    device of (NX-OS, IOS XR, OS10, VyOS as shipped) the offer was
    advice nobody could take.
    """
    vendor = codec.capabilities.vendor_id
    if get_model_families(request).model_keys(vendor):
        return True
    return any(
        profile.vendor == vendor
        for profile in get_target_profiles(request).values()
    )


def request_limits(request: Request) -> str | None:
    """The name of the limits this server is set to
    (``Settings.config_limits``), for :func:`~netcanon.migration.
    limits.server_scope`.

    ``None`` — which that function reads as the standard limits —
    under a bare-app fixture that skips the lifespan.
    """
    settings = getattr(request.app.state, "settings", None)
    return getattr(settings, "config_limits", None)


def request_answer(request: Request) -> Answer | None:
    """The :class:`Answer` the application keeps for *request*, for
    :func:`~netcanon.migration.limits.server_scope`.

    ``None`` when nothing keeps one -- an application assembled
    without :class:`AnswerSent`, a request made up by a test.  The
    scope then gives its turn back when the handler's block ends,
    since nobody would say that the answer went out.
    """
    scope = getattr(request, "scope", None)
    answer = scope.get(_ANSWER_KEY) if isinstance(scope, dict) else None
    return answer if isinstance(answer, Answer) else None


def _is_written_field_by_field(cls: type[BaseModel]) -> bool:
    """Whether a model's JSON is its fields' JSON, one after another:
    no serializer of its own, no computed field, nothing in its
    configuration that changes how a value is written."""
    decorators = cls.__pydantic_decorators__
    return not (
        decorators.field_serializers or decorators.model_serializers
        or decorators.computed_fields
        or any(key.startswith(("ser_", "json_")) or key == "use_enum_values" for key in cls.model_config)
    )


def _field_writer(cls: type[BaseModel], name: str) -> tuple[bytes, TypeAdapter[Any]]:
    """The JSON key of a field, with its colon, and what writes its
    value.  Made once a field: building a writer is not free."""
    made = _FIELD_WRITERS.get((cls, name))
    if made is None:
        field = cls.model_fields[name]
        key = json.dumps(field.serialization_alias or field.alias or name).encode("utf-8") + b":"
        made = _FIELD_WRITERS[cls, name] = (key, TypeAdapter(field.annotation))
    return made


def json_pieces(model: BaseModel) -> Iterator[bytes]:
    """*model* as JSON, a piece at a time: joined, the pieces are byte
    for byte what the framework sends for a handler that returns the
    model (``tests/integration/test_job_answer.py`` compares the two,
    job by job).

    A piece is one field, or -- of a list longer than
    :data:`LIST_RUN` -- one run of its entries, so no piece is much
    larger than what it was written from.  Written whole, the largest
    job the ``small`` limits admit is 38 MB of JSON that takes twice
    that while it is written, and a nested model costs the same again
    in the framework's own passes.
    """
    cls = type(model)
    if not _is_written_field_by_field(cls):
        yield cls.__pydantic_serializer__.to_json(model, by_alias=True)
        return
    opening = b"{"
    for name, field in cls.model_fields.items():
        if field.exclude:
            continue
        key, writer = _field_writer(cls, name)
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            yield opening + key
            yield from json_pieces(value)
        elif type(value) is list and len(value) > LIST_RUN:
            yield opening + key + b"["
            for start in range(0, len(value), LIST_RUN):
                run = writer.dump_json(value[start:start + LIST_RUN], by_alias=True)
                yield (b"," if start else b"") + run[1:-1]
            yield b"]"
        else:
            yield opening + key + writer.dump_json(value, by_alias=True)
        opening = b","
    yield b"}" if opening == b"," else b"{}"


async def _sent_and_let_go(pieces: deque[bytes]) -> AsyncIterator[bytes]:
    """The pieces in order, each let go of as it is handed over --
    and all that are left, if the sending stops before the end (the
    client left, or the answer was abandoned at its deadline)."""
    try:
        while pieces:
            yield pieces.popleft()
    finally:
        pieces.clear()


def job_answer(job: MigrationJob, response: Response) -> Response:
    """*job* as its answer, written a piece at a time.

    A handler that returns a model leaves the framework to make the
    answer: the model to a dict, the dict validated into a second
    model, that model to JSON-ready values, those to a string, the
    string to bytes.  A job's validation report has a path for every
    membership, so the answer to the largest job the ``small`` limits
    admit is 38 MB, and making it that way took more memory than the
    translation did -- on a 256 MiB instance, the difference between
    an instance that survives requests at once and one that does not.

    Here the job is written straight to JSON (:func:`json_pieces`).
    The bytes are the ones the framework would have sent, with the
    same ``Content-Length``.  A small answer goes as one body; a large
    one goes piece by piece, and each piece is freed as it is sent.

    Args:
        job: What the pipeline returned.
        response: The response the framework handed the handler.
            What the handler set on it (``X-Netcanon-Job-Status``) is
            carried over, as the framework does for a returned
            model and does not for a returned response.
    """
    pieces = deque(json_pieces(job))
    size = sum(map(len, pieces))
    answer: Response
    if size <= WHOLE_ANSWER:
        answer = Response(content=b"".join(pieces), media_type="application/json")
    else:
        answer = StreamingResponse(
            _sent_and_let_go(pieces), media_type="application/json",
            headers={"content-length": str(size)},
        )
    answer.headers.raw.extend(response.headers.raw)
    return answer


def refusal_as_http(exc: LimitExceeded) -> HTTPException:
    """A refusal, as the answer of a handler that returns no job (the
    sanitiser, codec detection).

    * **413** for a config past a limit, or a request out of time:
      the status an upload over the byte cap gets, for the same
      reason -- more than this server is set to take.  Sending the
      same thing again gets the same answer.
    * **503** with ``Retry-After`` for a request the server was too
      busy for (``at_once``): one that did not get a turn, and
      nothing of it was read; or one that got its turn after a
      wait and ran out of time, which is refused as busy too and
      says how long it waited.  Sending the same thing again is
      what to do.  A client that retries on 503 does the right
      thing by itself; one that read 413 here would give up on a
      config nothing is wrong with.

    Either way the detail is ``Refused:`` and the sentence.
    """
    if exc.kind == AT_ONCE:
        return HTTPException(
            status_code=503, detail=f"Refused: {exc}",
            headers={"Retry-After": str(BUSY_RETRY_AFTER)},
        )
    return HTTPException(status_code=413, detail=f"Refused: {exc}")


def _refused_before_work(
    source: CodecBase, target: CodecBase, exc: LimitExceeded,
) -> MigrationJob:
    """The job of a request that was refused before any stage ran:
    ``failed``, with ``refusal`` set and an ``error`` that begins
    ``refused:`` -- what ``run_plan`` makes of a refusal inside a
    stage, so that a client reads one shape."""
    job = MigrationJob(source_codec=source.name, target_codec=target.name)
    job.status = MigrationJobStatus.failed
    job.error = f"refused: {exc}"
    job.refusal = Refusal(**exc.as_dict())
    job.completed_at = datetime.now(UTC)
    # Counts and names of limits only, as for every refusal.
    logger.warning(
        "run_translation %s: refused %s -> %s before any stage: %s limit "
        "of the %s limits (asked %s, limit %s)",
        job.id[:8], source.name, target.name, exc.kind, exc.profile,
        exc.asked, exc.cap,
    )
    return job


def run_translation(
    request: Request,
    body: MigrationPlanRequest,
    source: CodecBase,
    target: CodecBase,
    raw_text: str,
    **overrides: Any,
) -> MigrationJob:
    """Run the pipeline for *body* — model-aware when it declares both devices.

    Every job-running handler dispatches through here, so the same
    body posted to ``/plan`` or to a per-pane endpoint renders the same
    port names and comes back with the same status.  *overrides* are
    that handler's own category maps and ``force``, passed through
    unchanged.

    The port map is not a handler's to pass: it is taken from the
    BODY, on every endpoint, and an absent one is read as ``{}``
    (translate every name by its shape).  A job's status depends on
    what was decided about its ports.  With both devices declared
    the positional pairing is itself a port map the operator edits;
    with none declared a port the translator dropped, or two names
    it put on one, hold the job ``partial`` until an entry decides
    them.  A decision -- an acknowledged drop included -- must not be
    lost to the URL the body is posted to.  The four category panes
    used to pass ``{}`` and set a posted port map aside; that left a
    job on those panes with no way to be settled.

    A request that declares both devices goes to
    :func:`~netcanon.services.migration_pipeline.run_plan_with_models`,
    which pairs ports by position and checks its own finished run.
    One that declares none goes to
    :func:`~netcanon.services.migration_pipeline.run_plan_with_checked_names`:
    the rename-aware pipeline, and then the same question asked of
    a run made by name shape.

    Either way the work runs inside ONE scope of the server's: the
    limits this server is set to, and one deadline for every parse and
    render the request makes (with both devices declared the source is
    parsed two or three times and the output is read back).  A config
    past a limit comes back as a ``failed`` job with ``refusal`` set;
    nothing is asked about the port names of a job that did not
    render.

    Where the limits say how many requests work at once, the request
    waits for its turn here, inside that deadline, and holds it until
    the job has been sent to the client (:class:`AnswerSent`): a job
    can be tens of megabytes.  One that is still waiting when its
    deadline passes comes back as the same kind of job: ``failed``,
    ``refusal.limit`` ``at_once``, and words that say the server was
    busy and to send it again.  So does one that got its turn after
    a wait and then ran out of time, from inside the pipeline: its
    words say how long it waited.  (A request that found every place
    taken when it arrived never reaches a handler: the middleware
    answers it 503, its body unread.)
    """
    inventories = resolve_port_inventories(request, body, source, target)
    overrides["port_rename_map"] = dict(body.port_rename_map or {})
    try:
        with server_scope(request_limits(request), answer=request_answer(request)):
            if inventories is None:
                return run_plan_with_checked_names(
                    source, target, raw_text, **overrides,
                    devices_known=(
                        a_device_is_described(request, source)
                        and a_device_is_described(request, target)
                    ),
                )
            source_inventory, target_inventory = inventories
            return run_plan_with_models(
                source, target, raw_text, source_inventory, target_inventory,
                **overrides,
            )
    except LimitExceeded as exc:
        # The pipeline answers a refusal inside a stage itself.  What
        # reaches here was raised where the scope is opened -- the
        # request did not get a turn -- and is a result all the same.
        return _refused_before_work(source, target, exc)
