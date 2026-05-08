"""
Helpers extracted from :mod:`netcanon.api.routes.migration` for the
``refactor/god-file-cleanup`` branch.

Public surface:

* :func:`resolve_adapter_or_422` — translate adapter-name lookup
  errors into 422s with side-aware ``source`` / ``target`` framing.
* :func:`resolve_input_text` — return the raw config text referenced
  by a :class:`MigrationPlanRequest` body, enforcing the
  ``raw_text`` XOR ``source_filename`` invariant and translating
  storage misses into 404s.
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

from fastapi import HTTPException, Request

from ...migration.codecs.registry import get_codec, list_codecs
from ...migration.target_profiles import TargetProfile
from ...models.migration import CodecInfo, MigrationPlanRequest
from ...storage.base import BaseConfigStore


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
        )


def resolve_input_text(
    body: MigrationPlanRequest, storage: BaseConfigStore
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
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"source_filename not found: {body.source_filename!r}",
        )


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
    for name in list_codecs():
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

    Legacy callers that supply none of these get the plain
    :func:`run_plan` path unchanged.
    """
    return (
        body.port_rename_map is not None
        or body.vlan_rename_map is not None
        or body.local_user_rename_map is not None
        or body.snmp_community_rename_map is not None
        or body.snmpv3_user_rename_map is not None
        or body.target_profile is not None
    )
