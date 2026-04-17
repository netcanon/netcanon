"""
Pydantic models for the translator / migration engine.

Phase 0 scope: types used by the adapter contract, capability matrix,
validation report, and the ``MigrationJob`` lifecycle.  No I/O; no
schema work (libyang comes in Phase 0.5).

All severity fields use the same three-step convention introduced by
``CompatibilityReport`` in ``netconfig.models.diff``:

    ok    — safe to proceed, no user action needed
    warn  — proceed with awareness (lossy or partial)
    block — stop unless the caller explicitly overrides (force=True)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# DeviceClass — coarse category of the target network function
# ---------------------------------------------------------------------------


class DeviceClass(str, Enum):
    """Coarse-grained device category an adapter targets.

    Used by ``check_class_compat`` to block obviously-nonsensical
    migrations (e.g. trying to render a Layer-2 switch config through
    a WAN router adapter).

    Taxonomy is deliberately flat — matrix-style "a device can fulfil
    multiple roles" captures the real world (L3 switches route AND
    switch; UTM appliances firewall AND do WAF).  Each adapter
    declares zero or more classes; compatibility is a non-empty
    intersection.  An adapter that declares no classes is "uncommitted"
    and the pipeline flags it as a ``warn`` rather than a block, so
    experimental adapters can be developed without immediately
    wiring up class declarations.

    Add new values sparingly; every value should represent a category
    where the *primary* feature surface is meaningfully different from
    every other category — not a vendor distinction.
    """

    #: L2 forwarding plane: VLANs, spanning-tree, MAC learning.
    #: Includes dumb switches and smart-but-L2-only devices.
    switch = "switch"

    #: L3 routing: OSPF, BGP, VRFs, MPLS, static routes.
    #: L3 switches declare BOTH ``switch`` and ``router``.
    router = "router"

    #: Stateful policy enforcement: rules, NAT, IPS/IDS.
    firewall = "firewall"

    #: Traffic distribution: F5, NetScaler, HAProxy appliances.
    load_balancer = "load_balancer"

    #: Wireless LAN controller (Aruba, Cisco WLC, Meraki MX).
    wireless_controller = "wireless_controller"

    #: Lightweight access points — usually controller-managed.
    access_point = "access_point"

    #: Web application firewall — distinct enough from a L3/4
    #: firewall that mapping between them is almost always lossy.
    waf = "waf"


# ---------------------------------------------------------------------------
# Capability-matrix leaf types
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Vendor declaration
# ---------------------------------------------------------------------------


class VendorInfo(BaseModel):
    """Declarative vendor identity loaded from YAML at startup.

    A vendor is NOT code — it's a small struct that groups codecs,
    provides UX labels, and carries defaults for device-class
    declarations.  Codecs link to their vendor via
    ``CapabilityMatrix.vendor_id``.

    Attributes:
        id: Unique identifier matching ``CapabilityMatrix.vendor_id``
            on each codec.  Stable across releases.  Lowercase,
            underscored (e.g. ``cisco_iosxe``).
        display_name: Human-readable label for the UI (e.g.
            ``"Cisco IOS-XE"``).
        device_classes: Default device classes for codecs that inherit
            from this vendor.  Individual codecs can override.
        default_timeout: SSH/transport timeout in seconds.
            Informational for Phase R7 (transports); carried here
            so vendor YAML is the single source of truth.
        notes: Free-text for the definitions page / tooltip.
    """

    id: str
    display_name: str
    device_classes: list[DeviceClass] = Field(default_factory=list)
    default_timeout: int = 30
    notes: str = ""


class LossyPath(BaseModel):
    """A YANG path the target adapter can partially represent.

    A lossy conversion is permitted but surfaces a warning in the
    ``ValidationReport`` so the caller can decide whether the fidelity
    loss is acceptable.

    Attributes:
        path: YANG xpath expression (adapter-scoped interpretation — see
            ``CapabilityMatrix.classify``).
        reason: Human-readable explanation of what's lost.
        severity: ``warn`` (default) lets the migration proceed; ``error``
            escalates to a block unless ``force=True``.
    """

    path: str
    reason: str
    severity: Literal["warn", "error"] = "warn"


class UnsupportedPath(BaseModel):
    """A YANG path the target adapter cannot emit at all.

    Presence of any unsupported path in a tree forces the
    ``ValidationReport`` severity to ``block``.  The caller may still
    override with ``force=True``; in that case ``strip_unsupported`` is
    the natural transform to apply before render.
    """

    path: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# CapabilityMatrix
# ---------------------------------------------------------------------------


class CapabilityMatrix(BaseModel):
    """Declarative statement of what an adapter can round-trip.

    Loaded at adapter registration time from the adapter's
    ``capabilities.yaml`` (Phase 1+) or hand-constructed in code
    (Phase 0).  The pipeline's validate stage walks a tree's xpaths
    and classifies each against this matrix.

    Attributes:
        adapter: Adapter name (matches ``CodecBase.name``).
        version_range: PEP 440 / SemVer range this matrix applies to.
        supported: xpath patterns the adapter round-trips cleanly.
        lossy: xpath patterns that survive with known caveats.
        unsupported: xpath patterns the adapter cannot emit.

    See ``classify`` for the resolution rules when a path is present in
    more than one list (which would be a configuration bug — this code
    treats ``unsupported`` as the strictest rule and uses it to decide).
    """

    adapter: str  # codec name (kept as "adapter" in JSON for back-compat)
    vendor_id: str = ""  # e.g. "cisco_iosxe", "opnsense" — links to vendor YAML (R2)
    version_range: str = "*"
    #: Device categories this codec targets.  Used for cross-class
    #: guard — see ``netconfig.services.migration_validate.check_class_compat``.
    #: Declaring zero classes means "uncommitted" and produces a warn-
    #: level banner rather than a block.
    device_classes: list[DeviceClass] = Field(default_factory=list)
    supported: list[str] = Field(default_factory=list)
    lossy: list[LossyPath] = Field(default_factory=list)
    unsupported: list[UnsupportedPath] = Field(default_factory=list)

    def classify(
        self, xpath: str
    ) -> Literal["supported", "lossy", "unsupported"]:
        """Classify a single xpath against this matrix.

        Resolution order (strictest wins so contributors can't
        accidentally mark a dangerous path as supported):

            1. ``unsupported`` wins if the path is listed there.
            2. ``lossy`` wins next.
            3. ``supported`` — either explicit or implicit (any path
               not otherwise classified is assumed supported for
               adapters that choose to declare only the exceptions).

        The Phase 0 implementation uses simple string equality; Phase 1
        adds glob/prefix matching (e.g. a pattern ending in ``/**``).
        """
        for up in self.unsupported:
            if up.path == xpath:
                return "unsupported"
        for lp in self.lossy:
            if lp.path == xpath:
                return "lossy"
        # Explicit supported list OR implicit default.
        return "supported"


# ---------------------------------------------------------------------------
# Validation + diff report types
# ---------------------------------------------------------------------------


class XPathDelta(BaseModel):
    """A single semantic difference between two YANG trees.

    Phase 0 ships this shape but the tree-diff engine that populates
    it lands in Phase 1 alongside the first non-mock adapter.

    Attributes:
        xpath: The path that changed.
        kind: ``added`` — present in target, absent in source;
              ``removed`` — present in source, absent in target;
              ``changed`` — present in both but the value differs.
        severity: Informational by default; adapters may raise
            severity for risky structural changes like ACL reordering.
        detail: Free-text explanation.
    """

    xpath: str
    kind: Literal["added", "removed", "changed"]
    severity: Literal["info", "warn", "error"] = "info"
    detail: str | None = None


class ValidationReport(BaseModel):
    """Result of validating a source tree against a target's capabilities.

    Shape mirrors ``CompatibilityReport`` in ``netconfig.models.diff``
    (``compatible`` bool + ``severity`` + ``reasons``) so UI code can
    render both with the same banner component.

    Attributes:
        compatible: ``True`` iff ``severity != "block"``.
        severity: Aggregate severity across all classified xpaths.
        supported_paths: xpaths that round-trip cleanly.
        lossy_paths: xpaths that survive with warnings.
        unsupported_paths: xpaths the target cannot emit.
        reasons: High-level one-liners for the UI banner.
    """

    compatible: bool
    severity: Literal["ok", "warn", "block"]
    supported_paths: list[str] = Field(default_factory=list)
    lossy_paths: list[LossyPath] = Field(default_factory=list)
    unsupported_paths: list[UnsupportedPath] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Transforms + migration job lifecycle
# ---------------------------------------------------------------------------


class TransformSpec(BaseModel):
    """A single transform to run between parse and validate.

    Transforms are declarative — name + args — so they can serialise
    into a ``MigrationJob`` and be persisted alongside it.  The
    ``netconfig.migration.transforms`` registry resolves ``name`` to a
    callable at run time.

    Attributes:
        name: Registered transform name (e.g. ``rename_interfaces``).
        args: Keyword arguments passed to the transform.
    """

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class MigrationJobStatus(str, Enum):
    """Lifecycle states of a ``MigrationJob``.

    Stages map 1:1 onto the pipeline (see ``translator-plans.txt`` §7).
    Terminal states follow the same three-way convention adopted for
    ``BackupJob`` — ``completed`` / ``partial`` / ``failed``.  The
    ``awaiting_approval`` pause exists so a user can review the
    validation report + render output before deploy commits anything.
    """

    pending = "pending"
    parsing = "parsing"
    transforming = "transforming"
    validating = "validating"
    rendering = "rendering"
    diffing = "diffing"
    awaiting_approval = "awaiting_approval"
    snapshotting = "snapshotting"
    deploying = "deploying"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class MigrationJob(BaseModel):
    """An in-progress or completed migration.

    Phase 0 exposes the shape but the orchestration that advances a
    job through its stages lands in Phase 2 alongside the API routes.
    For now jobs are transient objects produced by the pipeline
    service's ``run_plan`` helper.

    Attributes:
        id: UUID4 string, generated at creation.
        status: Current lifecycle state.
        source_codec: Name of the adapter used to parse input.
        target_codec: Name of the adapter used to render output.
        transforms: Ordered list of transforms applied between
            parse and validate.
        created_at: UTC time of creation.
        completed_at: UTC time of terminal state; ``None`` while running.
        validation: Populated after the validate stage completes.
        rendered: Populated after the render stage completes.
        error: Human-readable error summary on terminal-fail states.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: MigrationJobStatus = MigrationJobStatus.pending
    source_codec: str
    target_codec: str
    transforms: list[TransformSpec] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    validation: ValidationReport | None = None
    rendered: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Adapter info (for list/GET endpoints)
# ---------------------------------------------------------------------------


class MigrationPlanRequest(BaseModel):
    """Request body for ``POST /api/v1/migration/plan`` and ``/render``.

    Callers supply the input config text one of two ways:

    * ``raw_text`` — inline content.  Use for ad-hoc experimentation
      (``curl``-able).
    * ``source_filename`` — name of an existing stored config, loaded
      by the route from ``FileConfigStore``.  Use when the input is
      already the output of a backup job.

    Exactly one of the two MUST be set — the endpoint returns 422 if
    both or neither are provided.

    Attributes:
        source: Registered name of the adapter that parses input
            (e.g. ``"cisco_iosxe"``).
        target: Registered name of the adapter that renders output.
        raw_text: Inline config text.  Mutually exclusive with
            ``source_filename``.
        source_filename: Name of a stored config to load.
        force: Skip the device-class guard.  Default ``False``.
    """

    source: str
    target: str
    raw_text: str | None = None
    source_filename: str | None = None
    force: bool = False


class CodecInfo(BaseModel):
    """Summary surfaced by ``GET /api/v1/migration/adapters``.

    Lightweight on purpose — the full ``CapabilityMatrix`` lives at
    ``GET /api/v1/migration/adapters/{name}/capabilities``.  Exposes
    ``device_classes`` so UIs can filter the target-picker to
    compatible adapters before the user commits (same idea as the
    config-diff Compare picker's same-``type_key`` filter), and
    ``input_format`` so the /migrate UI can set a matching
    placeholder + compatible stored-config list.

    Attributes:
        input_format: Short catalogue tag from
            :data:`netconfig.migration.codecs.base.INPUT_FORMATS`
            describing what the adapter's ``parse()`` expects.
    """

    name: str
    vendor_id: str = ""
    vendor_display_name: str = ""
    version_range: str
    device_classes: list[DeviceClass] = Field(default_factory=list)
    input_format: str = "unknown"
    direction: str = "bidirectional"
    certainty: str = "experimental"
    canonical_model: str = "openconfig-lite"
    supported_count: int
    lossy_count: int
    unsupported_count: int
