"""
Target-device profiles — hardware-aware metadata for port-name
translation UI.

A :class:`TargetProfile` describes the physical port inventory of a
specific target device model (Aruba 2930F-48G-PoEP, FortiGate 100E,
Cisco C9300-24UX, MikroTik CRS310, etc.).  Profiles are loaded from
YAML files under ``definitions/target_profiles/`` and used by:

1. **UI dropdown options** — the per-port target-name dropdown in the
   Tier 3 rename modal lists only ports the target device actually
   has.  A 2930F-48 offers ports 1-48 + uplink A1/A2, not a free-form
   number picker.

2. **Collision detection** — the UI validates uniqueness of target
   port assignments against the profile's known port set.

3. **Fit check** — when the source config has more ports than the
   selected target profile, the UI surfaces a summary: "source has 52
   interfaces; target 2930F-48 has 48 + 2 uplinks = 50; 2 interfaces
   can't be mapped."

4. **Speed compatibility warnings** — source port is 10G but target
   port is 1G-only → flag for operator review.

Profiles are OPTIONAL.  Users can skip target-profile selection and
the Tier 3 UI falls back to free-form target-name entry (Tier 2
behaviour).  Selecting a profile upgrades the UX to validated,
bounded dropdowns.

YAML shape (see ``definitions/target_profiles/*.yaml`` for examples)::

    vendor: aruba_aoss
    model: 2930F-48G-PoEP
    display_name: "Aruba 2930F-48G-PoEP (JL256A)"
    device_class: switch
    stacking: vsf-capable
    ports:
      - {id: "1",    kind: physical, speed: gig,   poe: true}
      - {id: "2",    kind: physical, speed: gig,   poe: true}
      # ... ports 1-48
      - {id: "1/A1", kind: uplink,   speed: 10gig}
      - {id: "1/A2", kind: uplink,   speed: 10gig}
    lags:
      max: 24
      prefix: Trk

Module variants (chassis-based platforms with swappable uplink
modules, e.g. Cisco Cat 9300 NM slot, Aruba 3810M expansion slot)::

    vendor: cisco_iosxe
    model: C9300-24UX
    ports:                              # chassis-fixed access ports
      - {range: "GigabitEthernet1/0/1-24", kind: physical, speed: 10gig, poe: true}
      - {id: "GigabitEthernet0/0", kind: mgmt, speed: gig}
    modules:
      NM-8X:
        description: "8x 10G SFP+ uplinks"
        ports:
          - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig, sfp: true}
      NM-2Q:
        description: "2x 40G QSFP+ uplinks"
        ports:
          - {range: "FortyGigabitEthernet1/1/1-2", kind: uplink, speed: 40gig, sfp: true}

Modules are ADDITIVE: selecting a module adds its ports to the base
``ports:`` list.  Profiles with no ``modules:`` key behave exactly as
before (zero modules → UI module dropdown hidden).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from ..models.migration import DeviceClass

logger = logging.getLogger(__name__)


PortKindYaml = Literal[
    "physical",  # user-addressable port (access or routed)
    "uplink",    # fabric uplink (typically SFP / SFP+ / QSFP cage)
    "mgmt",      # out-of-band management
    "console",   # RS-232 / USB console (rarely in running-config)
]


class TargetPort(BaseModel):
    """A single port slot on a target device.

    ``id`` is the vendor-native name the user would see in the
    generated target config (``1``, ``1/A1``, ``port1``, ``ether5``,
    etc.).  Matches what the corresponding codec's
    ``format_port_identity`` would emit.
    """

    id: str
    kind: PortKindYaml = "physical"
    speed: str = ""
    """Maximum supported speed (``gig``, ``2.5gig``, ``5gig``,
    ``10gig``, ``25gig``, ``40gig``, ``100gig``).  Empty = unknown /
    any."""

    poe: bool = False
    """PoE (Power over Ethernet) capability — advisory for the UI."""

    sfp: bool = False
    """True when this is an SFP cage (1G SFP or 10G SFP+).  Used to
    differentiate from RJ45 ports of the same speed."""

    notes: str = ""
    """Free-form advisory (e.g. "multigig", "combo with sfp1")."""


class TargetModule(BaseModel):
    """A swappable uplink module option for a chassis-based profile.

    Models the "which NM card is installed?" dimension independently
    from the chassis.  A ``TargetProfile`` can declare multiple
    module SKUs; the rename-modal UI surfaces them as a third
    dropdown (Vendor → Chassis → Module) and adds the selected
    module's ports to the base ``TargetProfile.ports`` set.

    Module ports are ADDITIVE: the chassis profile's ``ports:``
    lists chassis-fixed access ports, and each module contributes
    its own uplinks.  Effective port inventory for a given operator
    choice = ``profile.ports + profile.modules[sku].ports``.

    ``sku`` is the vendor's part-number-style SKU (``NM-8X``,
    ``NM-2Q``, ``JL084A``, etc.) when one exists; freeform label
    otherwise.  Used as the dict key in
    :attr:`TargetProfile.modules` and as the wire-format value for
    module selection in ``MigrationPlanRequest``.
    """

    sku: str = ""
    """SKU / part-number for the module.  May be empty when set via
    dict-key-only YAML authorship — the loader backfills from the key."""

    description: str = ""
    """Human-readable blurb for the UI dropdown (e.g. ``"8x 10G
    SFP+ uplinks"``)."""

    ports: list[TargetPort] = Field(default_factory=list)
    """Ports this module contributes when selected.  Same shape as
    :attr:`TargetProfile.ports`; expanded through the same range
    shorthand at load time."""


class TargetLAGCaps(BaseModel):
    """LAG capacity of the target device."""

    max: int = Field(ge=0, le=4096)
    """Maximum number of LAGs the target supports."""

    prefix: str = ""
    """Vendor-native LAG name prefix.  Aruba uses ``Trk``, Cisco uses
    ``Port-channel``, MikroTik uses ``bond``, OPNsense uses ``lagg``,
    FortiGate LAGs are user-named (leave empty to indicate free
    user-chosen name).
    """


class TargetProfile(BaseModel):
    """A target device profile — the UI's source of truth for
    valid port assignments.

    Profiles are declarative YAML data; no behaviour lives here.
    Lookups and UI logic operate on parsed :class:`TargetProfile`
    instances via the helper accessors below.
    """

    vendor: str
    """Vendor identifier matching one of the codec vendor IDs
    (``cisco_iosxe``, ``aruba_aoss``, ``mikrotik_routeros``,
    ``opnsense``, ``fortigate``)."""

    model: str
    """Vendor-specific model code, e.g. ``2930F-48G-PoEP`` or ``100E``.
    Combined with ``vendor`` it uniquely identifies this profile."""

    display_name: str = ""
    """Human-readable name for UI display.  Falls back to
    ``vendor model`` if empty."""

    device_class: DeviceClass = DeviceClass.switch

    stacking: str = ""
    """Free-form stacking capability note: ``""`` (no stacking),
    ``vsf-capable`` (Aruba), ``stackwise`` (Cisco Cat9k), ``""`` for
    firewalls/routers with no stacking concept."""

    ports: list[TargetPort] = Field(default_factory=list)
    """Chassis-fixed ports — always present regardless of module choice.
    For legacy profiles (no ``modules:`` declared) this lists every
    port on the device.  For module-variant profiles this holds only
    the chassis-fixed access + mgmt ports; uplink inventory moves
    into per-:class:`TargetModule` entries."""

    modules: dict[str, TargetModule] = Field(default_factory=dict)
    """Swappable uplink module options, keyed by SKU.  Empty dict =
    legacy single-variant profile.  Non-empty = operator must choose
    a module; ``effective_ports(sku)`` returns ``self.ports`` plus
    the chosen module's ports.

    Module selection is additive and orthogonal to the base ``ports:``
    list — no port ever appears in both."""

    lags: TargetLAGCaps | None = None

    max_vlans: int | None = None
    """Maximum number of simultaneously-configured VLANs this device
    supports (vendor-specific — e.g. Aruba 2930F: 2048, Cisco
    Catalyst 9300: 4094, MikroTik CRS: 4094).  Drives the VLAN-
    pane fit-check banner: when source_vlans.length exceeds this
    value, the pane shows a red block banner telling the operator
    they'll need to trim before the migration will fit.  ``None``
    (default) means "no limit known / declared" and hides the
    banner on this pane — same discipline as ports (no profile =
    no fit-check)."""

    max_local_users: int | None = None
    """Maximum number of local user accounts.  Real examples:
    Aruba AOS-S 2930F declares a ``max-users-local`` around 16-64;
    Cisco IOS-XE allows up to 65535 concurrently; OPNsense is
    essentially unbounded.  Same None-default + pane-scoped
    banner semantics as ``max_vlans``."""

    # ------------------------------------------------------------------
    # Helper accessors — keep UI code decoupled from the YAML structure
    # ------------------------------------------------------------------

    @property
    def key(self) -> str:
        """Unique profile identifier for API use: ``<vendor>/<model>``."""
        return f"{self.vendor}/{self.model}"

    @property
    def port_count(self) -> int:
        """Total base ports (excludes per-module uplinks).  For
        module-variant profiles use :meth:`effective_port_count` with
        a specific module SKU to include uplinks."""
        return len(self.ports)

    @property
    def has_modules(self) -> bool:
        """True when at least one module variant is declared.  UI
        uses this to decide whether to surface the third-stage
        module dropdown."""
        return bool(self.modules)

    def module_skus(self) -> list[str]:
        """Ordered SKUs of declared modules (insertion-order stable)."""
        return list(self.modules.keys())

    def default_module_sku(self) -> str | None:
        """Return the SKU the UI should preselect.

        * No modules declared → ``None`` (UI hides the dropdown).
        * ``"default"`` is present → that wins (explicit author intent).
        * Otherwise the first declared SKU (insertion order).
        """
        if not self.modules:
            return None
        if "default" in self.modules:
            return "default"
        return next(iter(self.modules))

    def _resolve_module_sku(
        self, module_sku: str | None
    ) -> str | None:
        """Normalize None → default_module_sku; unknown SKU → None
        (falls back to base ports only, caller's responsibility to
        surface an error / warning if that's not the intent)."""
        if module_sku is None:
            return self.default_module_sku()
        if module_sku in self.modules:
            return module_sku
        return None

    def effective_ports(
        self, module_sku: str | None = None
    ) -> list[TargetPort]:
        """Return the full port set the operator would see for
        *module_sku*.

        Equals ``self.ports + self.modules[sku].ports`` when the
        module exists; falls back to ``self.ports`` otherwise.  Safe
        to call on legacy profiles (no modules) — returns
        ``self.ports`` unchanged.
        """
        resolved = self._resolve_module_sku(module_sku)
        if resolved is None or resolved not in self.modules:
            return list(self.ports)
        return list(self.ports) + list(self.modules[resolved].ports)

    def effective_port_count(
        self, module_sku: str | None = None
    ) -> int:
        """Total port count for the given module choice, including
        chassis-fixed + module uplinks."""
        return len(self.effective_ports(module_sku))

    def port_ids(
        self,
        kind: PortKindYaml | None = None,
        module_sku: str | None = None,
    ) -> list[str]:
        """Return port ids for the given module choice, optionally
        filtered by kind.  When *module_sku* is None the default
        module (if any) is used, so this stays backwards compatible
        with callers that only pass ``kind``."""
        ports = self.effective_ports(module_sku)
        if kind is None:
            return [p.id for p in ports]
        return [p.id for p in ports if p.kind == kind]

    def lookup_port(
        self,
        port_id: str,
        module_sku: str | None = None,
    ) -> TargetPort | None:
        """Return the :class:`TargetPort` matching *port_id* within
        the given module's effective set, or None."""
        for p in self.effective_ports(module_sku):
            if p.id == port_id:
                return p
        return None

    def display(self) -> str:
        return self.display_name or f"{self.vendor} {self.model}"


# ---------------------------------------------------------------------------
# YAML loader — mirrors the device-definitions loader pattern
# ---------------------------------------------------------------------------


class ProfileLoadError(Exception):
    """Raised when a profile YAML file can't be parsed or validated."""


#: Range shorthand regex.  Accepts both "1-48" and "A1-A4" style —
#: the second prefix (between ``-`` and the end number) is optional
#: and when present must match the first prefix.  Also accepts
#: "GigabitEthernet1/0/1-24" (prefix on start only).
_RANGE_RE = re.compile(
    r"^(?P<prefix>.*?)(?P<start>\d+)-(?P<prefix2>.*?)(?P<end>\d+)$"
)


def _expand_range_entries(ports_raw: list[Any]) -> list[dict[str, Any]]:
    """Expand ``range`` shorthand entries into concrete port records.

    Two accepted forms for a ports-list entry:

    * ``{id: "A1", kind: uplink, speed: 10gig, ...}`` — literal,
      passed through unchanged.
    * ``{range: "<prefix><start>-<end>", kind: ..., ...}`` — expanded
      into one entry per integer in ``[start, end]``, with each
      expanded entry's ``id`` set to ``<prefix><n>``.  Every other
      field (kind, speed, poe, sfp, notes) is duplicated across all
      expanded entries.

    Examples::

        {range: "1-48", kind: physical, speed: gig, poe: true}
          → ports 1, 2, ..., 48 all with kind=physical, gig, PoE=true

        {range: "GigabitEthernet1/0/1-24", kind: physical, speed: 10gig}
          → GigabitEthernet1/0/1, ..., GigabitEthernet1/0/24

        {range: "A1-A4", kind: uplink, speed: 10gig, sfp: true}
          → A1, A2, A3, A4 — the regex finds the numeric tail, keeping
            the "A" prefix intact.
    """
    out: list[dict[str, Any]] = []
    for entry in ports_raw:
        if not isinstance(entry, dict):
            # Leave exotic entries to pydantic validation below.
            out.append(entry)
            continue
        if "range" not in entry:
            out.append(entry)
            continue
        range_str = entry["range"]
        m = _RANGE_RE.match(str(range_str).strip())
        if not m:
            raise ProfileLoadError(
                f"invalid range shorthand {range_str!r}; expected "
                f"'<prefix><start>-<end>' (e.g. '1-48', 'A1-A4' or "
                f"'GigabitEthernet1/0/1-24')"
            )
        prefix = m.group("prefix")
        prefix2 = m.group("prefix2")
        if prefix2 and prefix2 != prefix:
            raise ProfileLoadError(
                f"invalid range {range_str!r}: inconsistent prefix "
                f"({prefix!r} vs {prefix2!r}) — both sides must match"
            )
        start = int(m.group("start"))
        end = int(m.group("end"))
        if start > end:
            raise ProfileLoadError(
                f"invalid range {range_str!r}: start {start} > end {end}"
            )
        shared = {k: v for k, v in entry.items() if k != "range"}
        for n in range(start, end + 1):
            out.append({"id": f"{prefix}{n}", **shared})
    return out


def load_profile_file(path: Path) -> TargetProfile:
    """Load and validate a single profile YAML file.

    Supports range-shorthand entries in the ``ports:`` list — see
    :func:`_expand_range_entries` for syntax.  Range entries are
    expanded before pydantic validation so the model only ever sees
    concrete ``{id: ..., kind: ...}`` records.

    Modules (optional): a top-level ``modules:`` mapping keyed by SKU
    gets the same range-expansion treatment on its per-module
    ``ports:`` list, and the dict key is backfilled into each
    module's ``sku`` field when the author omitted it::

        modules:
          NM-8X:            # key → module.sku = "NM-8X"
            description: "8x 10G SFP+"
            ports:
              - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig}
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileLoadError(f"{path}: YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileLoadError(f"{path}: expected a YAML mapping at top level")
    if "ports" in data and isinstance(data["ports"], list):
        try:
            data["ports"] = _expand_range_entries(data["ports"])
        except ProfileLoadError as exc:
            raise ProfileLoadError(f"{path}: {exc}") from exc
    # Expand ranges inside each declared module and backfill sku.
    if "modules" in data and isinstance(data["modules"], dict):
        expanded: dict[str, Any] = {}
        for sku, mod_raw in data["modules"].items():
            if not isinstance(mod_raw, dict):
                raise ProfileLoadError(
                    f"{path}: module {sku!r} must be a mapping, "
                    f"got {type(mod_raw).__name__}"
                )
            mod = dict(mod_raw)  # shallow copy — don't mutate caller YAML
            mod.setdefault("sku", sku)
            if "ports" in mod and isinstance(mod["ports"], list):
                try:
                    mod["ports"] = _expand_range_entries(mod["ports"])
                except ProfileLoadError as exc:
                    raise ProfileLoadError(
                        f"{path}: module {sku!r}: {exc}"
                    ) from exc
            expanded[sku] = mod
        data["modules"] = expanded
    try:
        return TargetProfile(**data)
    except ValidationError as exc:
        raise ProfileLoadError(
            f"{path}: schema validation failed: {exc}"
        ) from exc


def load_profiles_dir(directory: Path) -> dict[str, TargetProfile]:
    """Load every ``*.yaml`` file in *directory* and return a mapping
    from profile key (``vendor/model``) to :class:`TargetProfile`.

    Skips files that fail to load — logs the error and continues.
    The API surfaces whatever succeeded rather than failing the whole
    app on a single bad profile.

    If *directory* does not exist, returns an empty mapping (target
    profiles are an optional feature).
    """
    profiles: dict[str, TargetProfile] = {}
    if not directory.exists():
        logger.info(
            "target_profiles: directory %s not found — no profiles loaded",
            directory,
        )
        return profiles
    for path in sorted(directory.glob("*.yaml")):
        try:
            profile = load_profile_file(path)
        except ProfileLoadError as exc:
            logger.warning("target_profiles: skip %s: %s", path.name, exc)
            continue
        if profile.key in profiles:
            logger.warning(
                "target_profiles: duplicate key %s "
                "(file %s overwrites earlier entry)",
                profile.key, path.name,
            )
        profiles[profile.key] = profile
    logger.info(
        "target_profiles: loaded %d profile(s) from %s",
        len(profiles), directory,
    )
    return profiles
