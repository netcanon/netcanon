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
* :func:`run_translation` — the one place every job-running handler
  dispatches from: model-aware when the request declares both
  devices, the ordinary rename-aware pipeline otherwise.

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

from typing import Any, Protocol

from fastapi import HTTPException, Request

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
from ...migration.target_profiles import TargetProfile
from ...models.migration import CodecInfo, MigrationJob, MigrationPlanRequest
from ...services.migration_pipeline import (
    run_plan_with_models,
    run_plan_with_overrides,
)
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
    port names.  *overrides* are that handler's own
    ``run_plan_with_overrides`` keyword arguments (its category maps
    and ``force``), passed through unchanged when the request does
    not declare its devices.

    When it does, they go to
    :func:`~netcanon.services.migration_pipeline.run_plan_with_models`
    instead, with one substitution: ``port_rename_map`` is taken from
    the BODY, whatever the handler passed.  Four of the per-pane
    handlers pass ``{}`` there ("translate by name shape, and ignore
    a port map posted to this pane"), which is right for a guess and
    wrong for a pairing: the pairing is itself a port map, so the
    operator's edits to it — the drops they have acknowledged
    included — must not depend on which URL the body is posted to.
    """
    inventories = resolve_port_inventories(request, body, source, target)
    if inventories is None:
        return run_plan_with_overrides(source, target, raw_text, **overrides)
    source_inventory, target_inventory = inventories
    overrides["port_rename_map"] = dict(body.port_rename_map or {})
    return run_plan_with_models(
        source, target, raw_text, source_inventory, target_inventory,
        **overrides,
    )
