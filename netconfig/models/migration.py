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

    #: Non-fatal advisories from the pipeline.  Populated by
    #: ``run_plan_with_rename`` when the cross-vendor port-name
    #: translator leaves interfaces unmapped or surfaces
    #: complexity-cases (breakout / hw-aggregate / loopback-in-
    #: AOS-S-style scenarios).  Empty on a fully clean run.
    warnings: list[str] = Field(default_factory=list)

    #: Source→target port-name rewrites applied during
    #: :func:`run_plan_with_rename`.  Surfaced in the UI's
    #: "Interface translation" panel so operators can see exactly
    #: which names changed (and, in Tier 3, override them).  Keys
    #: are source names; values are target names.  Unchanged names
    #: are not included.
    port_renames: dict[str, str] = Field(default_factory=dict)

    #: Source names the operator explicitly marked "don't render" via
    #: the Tier 3 rename modal.  Every reference to these names was
    #: stripped from the canonical tree before render; the rendered
    #: output does not contain the corresponding interface stanzas.
    #: Populated by ``run_plan_with_rename`` from entries in
    #: :attr:`MigrationPlanRequest.port_rename_map` whose value was
    #: ``None``.
    port_drops: list[str] = Field(default_factory=list)

    #: Source VLAN ID → target VLAN ID rewrites applied during
    #: :func:`run_plan_with_overrides` when the caller supplied a
    #: ``vlan_rename_map``.  Parallels :attr:`port_renames` for the
    #: VLAN-mapping per-pane override in the Tier-3 modal.  Keys
    #: and values are both integers 1-4094.  Unchanged VLAN IDs are
    #: not included — only actual rewrites.  Empty dict when the
    #: caller didn't pass a ``vlan_rename_map`` at all.
    vlan_renames: dict[int, int] = Field(default_factory=dict)

    #: VLAN IDs the operator explicitly marked "don't render" via
    #: ``None`` values in the rename map.  The canonical tree had
    #: every reference to these IDs stripped before render —
    #: ``CanonicalVlan`` entry removed, ``access_vlan``
    #: detached, ``trunk_allowed_vlans`` entries removed,
    #: ``trunk_native_vlan`` / ``voice_vlan`` cleared on affected
    #: interfaces.
    vlan_drops: list[int] = Field(default_factory=list)

    #: Source-tree VLAN IDs captured post-parse, pre-transform.
    #: Lets the Tier-3 rename modal's VLAN pane enumerate every
    #: VLAN the operator could rewrite or drop — without this field
    #: the UI has no way to surface VLANs that the operator hasn't
    #: already touched.  Populated by
    #: :func:`run_plan_with_overrides` via a capture transform that
    #: runs ahead of any user-supplied overrides; empty on legacy
    #: :func:`run_plan` calls that bypass the overrides engine.
    source_vlans: list[int] = Field(default_factory=list)

    #: Canonical hostname captured post-parse.  Feeds the Tier-3
    #: rename modal's localStorage persistence key so a given
    #: (source_codec, target_codec, hostname) triple has its own
    #: override memory — moving between devices doesn't clobber
    #: saved overrides for the previous one.  Empty when the source
    #: config didn't declare a hostname.
    source_hostname: str = ""


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
    port_rename_map: dict[str, str | None] | None = None
    """Optional per-port target-name override map.  When provided, the
    pipeline runs the Tier 2 port-name translator with these entries
    taking precedence over the auto-heuristic.  Used by the Tier 3 UI
    rename modal.  Backwards-compatible: callers that don't set this
    get the legacy behaviour (no port-name translation at all).

    Entry value semantics:

    * ``str`` — use this name as the target-side port name verbatim
      (user override wins over the auto-heuristic).
    * ``None`` (``null`` in JSON) — DROP the interface from the
      canonical tree before render.  Every reference to the source
      name disappears: the interface stanza, VLAN tagged/untagged
      lists, LAG membership, static-route egress, DHCP pool
      interface.  Used when an operator decides a source interface
      has no target representation and should be stripped rather
      than mapped (e.g. Cisco ``AppGigabitEthernet1/0/1``
      app-hosting bridge, loopbacks that can't be ported, unused
      physical ports).
    * key NOT in map — run the auto-heuristic (classify + format).
    """

    target_profile: str | None = None
    """Optional target-device profile key (``vendor/model`` form, e.g.
    ``aruba_aoss/2930F-48G-PoEP``).  Advisory only — the rename modal
    uses this to drive dropdown options and validate port ids against
    the target device's known port set.  Does not affect rendering."""

    target_module: str | None = None
    """Optional module SKU within :attr:`target_profile` (e.g.
    ``NM-8X``, ``NM-2Q``, ``JL084A``).  Used when the selected profile
    declares module variants (chassis + swappable uplink module) —
    tells the rename modal which of the module's uplink port-ids to
    offer in the target-name dropdown.  Advisory only (mirrors
    ``target_profile`` semantics — does not affect rendering)."""

    vlan_rename_map: dict[int, int | None] | None = None
    """Optional VLAN ID → target VLAN ID override map.  Parallel
    surface to :attr:`port_rename_map` for the VLAN-mapping per-pane
    override in the Tier-3 modal.

    Entry value semantics:

    * ``int`` — rewrite this VLAN's ID to the target ID across the
      canonical tree (the ``CanonicalVlan`` itself + every
      ``access_vlan`` / ``trunk_native_vlan`` / ``voice_vlan`` /
      ``trunk_allowed_vlans`` reference).
    * ``None`` — DROP the VLAN entirely.  Every reference is
      stripped; interfaces whose ``access_vlan`` was this ID get
      detached (``access_vlan = None``, switchport_mode unchanged
      — operator typically wants to re-assign manually afterwards).
    * key NOT in map — VLAN passes through unchanged.

    IDs outside 1-4094 trigger warnings and are skipped (the entry
    is discarded before any tree mutation).  Mapping multiple
    source IDs to the same target ID triggers a merge: port lists
    are unioned, SVI addresses concatenated.  Mapping to an ID
    that already exists in the source tree also merges.

    Backwards-compatible: callers that don't set this get the
    legacy behaviour (VLAN IDs pass through unchanged).  Callers
    that set it to ``{}`` opt into the VLAN-rename pipeline with
    no explicit overrides (useful when the UI wants to surface
    "no VLAN overrides applied" in the response shape)."""


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

    # UI-metadata fields (R5 follow-up — UI Metadata Migration session).
    # These replace the client-side FORMAT_CATALOGUE that previously
    # duplicated codec metadata in migrate.html.  Each codec class is
    # the single source of truth for its own presentation strings.
    description: str = ""
    sample_input: str = ""
    output_extension: str = ""
