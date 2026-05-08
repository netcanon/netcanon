# Migration codecs — authorship guide

A **codec** translates between a vendor's native config format and the
shared `CanonicalIntent` tree.  Every new vendor parser/renderer lives
here as a subpackage.

This README is the codec-writing cookbook.  If you're fixing a bug in
an existing codec, start by reading that codec's `codec.py` + the
matching `tests/unit/migration/test_<vendor>.py`.

---

## Shape of a codec

Eight codecs have shipped: `cisco_iosxe`, `cisco_iosxe_cli`,
`aruba_aoss`, `opnsense`, `mikrotik_routeros`, `fortigate_cli`,
`arista_eos`, `juniper_junos` (plus `_mock`).  The first one you
should copy is whichever vendor is closest in structure to yours:

| Wire format | Reference codec |
|---|---|
| Line-oriented indented CLI with `!` delimiters (Cisco-family) | `cisco_iosxe_cli`, `arista_eos` |
| Line-oriented CLI with section headers like `/ip address` | `mikrotik_routeros` |
| Nested `config/edit/set/next/end` CLI | `fortigate_cli` |
| XML (config.xml dialect) | `opnsense` |
| NETCONF XML | `cisco_iosxe` |
| Banner + positional port lists | `aruba_aoss` |
| Flat `set`-form command text (Junos) | `juniper_junos` |

For Cisco-family dialects (EOS, NX-OS, IOS-XR), start from
`arista_eos` rather than `cisco_iosxe_cli` — the Arista codec is
lighter-weight (no Cat9k CPP grammar, no type-9 password variants)
and the shape is closer to what you'll need for other
IOS-dialect vendors.

Each codec subpackage contains at minimum:

```
netcanon/migration/codecs/<vendor>/
├── __init__.py         # exports the codec class; usually one line
└── codec.py            # parse + render + probe + metadata
```

Larger codecs additionally split out pure helpers into sibling
modules — this is an established repo-wide convention, not optional
flair.  The `codec.py` stays focused on I/O orchestration; the
helpers stay easy to unit-test in isolation:

```
netcanon/migration/codecs/<vendor>/
├── codec.py            # orchestration — class, probe, delegation
├── parse.py            # (fortigate_cli) block tokeniser + per-stanza
│                       # dispatchers; thin codec.parse() delegates here
├── render.py           # (fortigate_cli) canonical tree → vendor text;
│                       # thin codec.render() delegates here
├── port_names.py       # pure classify_port_name + format_port_identity
│                       # (ALL four CLI codecs have this — mandatory
│                       # when the codec participates in the Tier-3
│                       # rename orchestrator; see cross-vendor mesh
│                       # in netcanon/migration/canonical/port_names.py)
├── vlan_heuristics.py  # (fortigate_cli) shared parse/render helpers
│                       # for VLAN iface-name detection
└── _svi_absorption.py  # (aruba_aoss) documents the 3-codepath rule
                        # that absorbs SVI L3 into VLAN stanzas
```

**`parse.py` / `render.py` split** is an optional codec-level
refactor applied when `codec.py` grows past the ~800-1000 LOC band
and the god-file effect starts hurting contributor clarity.
Pattern: `codec.py` keeps the codec class (metadata + probe +
capability matrix + port-name delegates); `codec.parse()` is a
one-line `return parse_intent(raw)` delegator to a module-level
function in `parse.py`, and `codec.render()` is the mirror
delegator to `render.py`.  Shared utilities (IP-mask helpers,
vendor-specific mode tables) live in `parse.py` and get re-imported
into `render.py` — one directional edge, no circular risk.

Codecs with the split applied: **fortigate_cli** (first; Phase 1
god-file cleanup), **opnsense** (XML wire-format reference),
**aruba_aoss** (banner + positional port-list reference),
**arista_eos** (Cisco-dialect parallel reference),
**mikrotik_routeros** (slash-prefixed CLI reference),
**cisco_iosxe_cli** (largest render path; ``_walk_canonical`` kept
at module level in ``codec.py`` to preserve the cross-codec import
surface every other codec's ``iter_xpaths`` reuses), and
**juniper_junos** (two-pass groups-then-top-level dispatch +
block-form-to-set-form conversion both kept cohesive in
``parse.py``).  All shipped CLI/XML codecs now follow the split
EXCEPT `cisco_iosxe` (NETCONF), whose `codec.py` keeps the parse +
render paths inline because its XML-tree traversal differs enough
from the CLI-text codecs that the split offered no clarity win;
the pattern generalises cleanly to future CLI/XML codecs.  Tests that pin internal symbols
(``_parse_blocks``, ``_prefix_to_mask``, ``_trim_xml_envelope``,
``_format_port_list``, ``_parse_port_list``) should import via
re-export in `codec.py` so the split doesn't break them — see
fortigate_cli/codec.py's, opnsense/codec.py's, and
aruba_aoss/codec.py's `__all__` for the shape.

**`port_names.py` is mandatory** for any codec that participates in
the rename-modal flow.  The cross-vendor orchestrator at
`netcanon/migration/canonical/port_names.py` imports each codec's
pair of pure functions directly — a codec that inlines them inside
`codec.py` blocks on circular imports.  The four CLI codecs
(`cisco_iosxe_cli`, `aruba_aoss`, `mikrotik_routeros`,
`fortigate_cli`) all follow the split; copy the closest one.

**`_svi_absorption.py`-style doc modules** are encouraged when a
codec has a cross-cutting invariant spanning 3+ code paths.  The
Aruba example documents why three different methods need to agree
on a constant — a future contributor changing one without the
others would silently break round-trip.  See
`netcanon/migration/codecs/aruba_aoss/_svi_absorption.py` for the
shape.

---

## Minimum contract

```python
from typing import Any, ClassVar, Iterable

from ....models.migration import CapabilityMatrix, DeviceClass
from ...canonical.intent import CanonicalIntent
from ..base import CodecBase, ParseError, RenderError
from ..registry import register


@register
class MyVendorCodec(CodecBase):
    name: ClassVar[str] = "myvendor_cli"
    version_hint: ClassVar[str | None] = "1.0+"
    input_format: ClassVar[str] = "cli-myvendor"     # see base.INPUT_FORMATS
    direction: ClassVar[str] = "bidirectional"       # or "parse_only" / "render_only"
    certainty: ClassVar[str] = "experimental"        # see below
    canonical_model: ClassVar[str] = "openconfig-lite"

    # UI metadata
    description: ClassVar[str] = "MyVendor XYZ123 CLI config parser."
    sample_input: ClassVar[str] = "hostname myvendor-01\n...\n"
    output_extension: ClassVar[str] = "cfg"

    # Per-pane round-trip gaps.  List any category the Tier-3 rename
    # modal exposes that this codec's parse+render doesn't yet wire
    # (ports / vlans / local_users / snmp / snmpv3; NTP/DNS/syslog/
    # RADIUS + SNMP trap-hosts are planned follow-ups).  The UI shows
    # an amber compatibility banner on the affected pane so operators
    # see up-front that overrides won't reach rendered output.  Remove
    # entries as the codec gains each category's round-trip coverage.
    unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset()

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        vendor_id="myvendor",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported_paths=[
            "/system/hostname",
            "/interfaces/interface/config/name",
            # ... one xpath per CanonicalIntent field your codec wires
        ],
        # Plus lossy_paths / unsupported_paths as needed.
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    def parse(self, raw: str) -> CanonicalIntent:
        # Raise ParseError on malformed input.
        # Return a CanonicalIntent; empty fields OK.
        ...

    def render(self, tree: Any) -> str:
        # Raise RenderError if tree shape is wrong for this vendor.
        # Return a config string the vendor can ingest.
        ...

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        # Yield canonical xpaths present in `tree`.  Used by capability
        # validation.  The cisco_iosxe_cli codec exports a shared
        # `_walk_canonical` helper most other codecs reuse.
        ...

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        # Auto-detection.  Return (confidence_0_to_100, reason_str)
        # when raw_prefix looks like this vendor; return None otherwise.
        # See cisco_iosxe_cli.probe() for a reference implementation.
        ...
```

`@register` auto-enrols the class in the global codec registry; as long
as the module is importable under `netcanon/migration/codecs/`, the
pkgutil-based auto-discovery in `netcanon/migration/__init__.py` picks
it up at import time — **no manual registration step**.

---

## Certainty levels

Declared via the `certainty` ClassVar.  The UI shows each codec's
certainty as a chip; migration output to a non-`certified` target
surfaces a warning banner.

| Level | Meaning | Graduation path |
|---|---|---|
| `experimental` | Tested only against synthetic hand-crafted fixtures | → `best_effort` after real-capture fixtures pass |
| `best_effort` | Round-trip tested against ≥1 real fixture, but <3 captures OR <2 OS versions | → `certified` after ≥3 real captures from ≥2 OS versions round-trip clean |
| `certified` | Round-trip stable across ≥3 real captures from ≥2 OS versions; deploy-ready | — |

Promotion is a human call — update the ClassVar in a commit that also
updates the corresponding assertion in
`tests/unit/migration/test_<vendor>.py` (see the MikroTik commit `4dc7a8e`
for the reference pattern).

---

## Adding a codec — checklist

1. **Copy the closest reference codec** from the table above into a
   new `netcanon/migration/codecs/<vendor>/` directory.
2. **Write `parse()`** against synthetic fixtures in `tests/unit/migration/test_<vendor>.py`.
   Start from the canonical fields your vendor actually has; don't try
   to model everything.
3. **Write `render()`** against the same synthetic fixtures, driving
   toward round-trip stability (`parse(render(parse(raw))) == parse(raw)`
   at the canonical level).
4. **Write `probe()`** using 2-3 discriminating structural markers
   unique to your vendor's wire format.
5. **Fill in `capabilities._CAPS`** listing every canonical xpath your
   parse/render actually handles (not aspirational — just what works).
6. **Add real fixtures** under `tests/fixtures/real/<vendor>/` with
   provenance in `tests/fixtures/real/NOTICE.md`.  The harness at
   `tests/unit/migration/test_real_captures.py` picks them up automatically.
7. **Fix what the harness surfaces** — real captures reliably expose
   grammar you didn't anticipate.  See the "Bugs surfaced" column in
   `tests/fixtures/real/RESULTS.md` for historical examples (every
   codec surfaced 0-2 bugs on first real-capture contact).
8. **Cross-codec smoke test** — add your codec to the parametrised
   matrix in `tests/unit/migration/test_cross_codec_matrix.py`.  This
   catches canonical-representation drift between codecs.

---

## Canonical fields — adding new ones

Each field on `CanonicalIntent` / `CanonicalInterface` /
`CanonicalVlan` etc. needs per-codec parse + render wire-through.  See
`docs/adding-a-canonical-field.md` at the repo root for the MTU
wire-through as a worked example.

Rule of thumb: one feature, one commit touching every bidirectional
codec (8 currently shipped: `cisco_iosxe_cli`, `cisco_iosxe`,
`aruba_aoss`, `opnsense`, `mikrotik_routeros`, `fortigate_cli`,
`arista_eos`, `juniper_junos`).  The Tier 2 wire-throughs (SNMP
v1/v2c + v3 USM, LAGs, local_users, DHCP, RADIUS, MTU) each landed as
a single commit per feature with regression tests in a dedicated
`test_<feature>_wire_through.py` file.

---

## Cross-codec shared utilities

Codecs are NOT siloed.  Some concerns are vendor-agnostic and live
in shared sibling modules at the migration-package root.  When
authoring a new codec, import from these instead of re-implementing
the policy locally:

* **`netcanon/migration/_user_secrets.py`** — cross-vendor
  hash-portability policy.  Public API: `classify_hash(hashed)`,
  `is_migratable(hashed, target_vendor)`, `format_review_comment(
  user_name, algorithm, comment_syntax, target_label)`.  Each
  target codec calls `is_migratable()` before emitting a password
  line; on miss, emit a `format_review_comment(...)` line in the
  appropriate per-codec syntax (`hash` / `semicolon` / `slash` /
  `xml` / `exclamation`) and skip the password command.  NEVER fall
  back to plaintext (would leak the hash literal as the password).
  Per-target accepted-algorithm sets live in
  `_TARGET_ACCEPTS[<vendor>]`.

* **`netcanon/migration/_tier3_detection.py`** — Tier-3 stanza-header
  detection.  Public API: `detect_tier3_sections_iosxe_cli(raw)`,
  `detect_tier3_sections_fortios(raw)`, `detect_tier3_sections_junos(raw)`,
  `detect_tier3_sections_routeros(raw)`,
  `detect_tier3_sections_opnsense(raw)`,
  `detect_tier3_sections_iosxe_xml(raw)` (currently no-op).  Each codec's
  `parse()` calls the matching detector and stamps the result onto
  `CanonicalIntent.dropped_tier3_sections` so the migrate page can
  surface the silent-drop in a "Detected in source but not translated"
  banner.  Output is NOTIFICATION-ONLY — never read by render or any
  transform.  Patterns target stanzas the canonical schema doesn't
  model (firewall, NAT, QoS, route-maps, crypto/IPsec, OPNsense filter
  / NAT / VPN XML); supported stanzas are deliberately excluded so the
  banner doesn't lie about what was dropped.

* **`netcanon/migration/_naming.py`** — naming-value sanitisation.
  Public API: `sanitise_hostname(name, separator="_")`.  Some target
  CLI parsers (Arista EOS, Cisco IOS-XE) reject whitespace in
  hostname / domain / VRF-name tokens; the renderer collapses
  whitespace runs to `_` so the wire form round-trips.  Source state
  is preserved on the canonical model — sanitisation happens only at
  the wire boundary.

* **`netcanon/migration/canonical/transforms.py::project_switchport_to_vlan`**
  — projects per-iface switchport state (`switchport_mode`,
  `access_vlan`, `trunk_allowed_vlans`) back into VLAN-centric
  `vlan.tagged_ports` / `vlan.untagged_ports` lists.  Codecs whose
  parse loop populates per-iface VLAN membership but not the
  symmetric per-VLAN port lists call this as a parse post-pass for
  round-trip stability.  Currently called by `arista_eos`,
  `aruba_aoss`, `cisco_iosxe_cli`, `juniper_junos`.  Helper
  internally guards the Junos `vlan members all` sentinel
  (`range(1,4095)`) to avoid synthesising 4094 phantom CanonicalVlans.

* **`netcanon/migration/canonical/transforms.py::project_vlan_to_switchport`**
  — the symmetric direction.  Materialises port-centric switchport
  state from VLAN-centric membership lists.  Cisco IOS-XE CLI and
  Junos render paths call this so cross-vendor renders from codecs
  that emit no per-port stanzas (Aruba's `vlan N / untagged 1/1-1/47`
  form, OPNsense's `<vlans>`-only) still produce L2 config on the
  target side.

* **`netcanon/migration/canonical/transforms.py::project_svi_to_vlan`**
  — synthesises `CanonicalVlan` records from L3 SVI interfaces
  (`Vlan100`, `irb.100`, etc.) when the source-side parser
  populates the iface but not the corresponding VLAN.  Added in
  Wave 7c (commit `ce9725d`) as a shared helper after the same
  pattern emerged independently in multiple CLI codecs; currently
  called by `arista_eos` (and propagation to other CLI codecs is
  ongoing).  The `cisco_iosxe` NETCONF codec retains its own
  private SVI-absorption helper because its XML-shaped traversal
  doesn't match the shared CLI-oriented signature; aligning the
  two is a separate follow-up.

* **`netcanon/migration/canonical/transforms.py::_natural_port_sort_key`**
  — natural-sort key for port-name strings (`1/1, 1/2, 1/10` rather
  than lex `1/1, 1/10, 1/2`).  Used by `project_switchport_to_vlan`
  and the Junos parser's port-list materialisation to guarantee
  cross-vendor list-order parity in `vlan.tagged_ports` /
  `vlan.untagged_ports`.  Wave 7c (commit `87b2248`) added this as
  the systemic fix for cross-vendor lexical-order drift.

* **LAG-name canonicalisation helpers** — `_canonical_lag_name`
  (Wave 10γ-3) and `_normalise_lag_name_to_arista` (Wave 7c) live
  in `netcanon/migration/canonical/transforms.py` (or the
  per-codec port-name modules that re-export them) and normalise
  vendor LAG forms (`Port-Channel1`, `Bundle-Ether10`, `ae0`,
  `lag1`, `Trk1`) onto a single canonical handle so cross-codec
  renders find each other through the rename mesh.  When adding a
  new codec that emits a LAG container, route through these helpers
  rather than coining a private normaliser — the cross-mesh tests
  in `tests/unit/migration/test_cross_codec_matrix.py` rely on the
  shared canonical form.

When you find yourself wanting per-codec versions of "is this hash
re-emittable?", "is this name CLI-safe?", or "what does VLAN N's
tagged-port set look like?", add to one of the helpers above
instead of duplicating logic in your codec.

---

## Gotchas

### `parse()` must not lose information on round-trip

A `parse → render → parse` cycle should produce canonically-equal
trees.  If it doesn't, one of these is wrong:

* Your `parse()` is dropping data silently.
* Your `render()` is synthesizing names/defaults the parser can't
  reconstruct.  Example: MikroTik's VLAN render used to emit
  `name=vlan<N>` instead of preserving the original iface name
  (`gn-mgmt`), so the second parse couldn't match.
* A parent-codec invariant moved (e.g. `CanonicalVlan.name` semantics
  changed).  Check `tests/fixtures/real/RESULTS.md` for historical
  bugs of this shape.

Real-capture tests check this via
`test_real_capture_round_trips_stable`.  If your codec needs a
round-trip carve-out for a known gap, use
`_KNOWN_ROUNDTRIP_GAPS` in `tests/unit/migration/test_real_captures.py`
with an explanatory string pointing at the Fidelity Polish roadmap entry.

### Hash and credential handling

Codecs must carry **hashed** passwords verbatim, never plaintext.  When
parsing, preserve vendor-specific algorithm tags (`sha1:`, `bcrypt:`,
`fortios:ENC`, Cisco type-digit prefixes like `5 `, `7 `, `9 `) so
renderers can route correctly.  See `test_local_users_wire_through.py`
for the reference pattern.  **Never commit real credential hashes to
test fixtures** (CLAUDE.md hard rule).

### Test fixtures, not real credentials

Synthetic hashes in test input should LOOK like real hashes but be
obviously fake (e.g. `$9$fake$hash`, `ENC fakeEncodedHash==`).  Real
captures from upstream-published repos are OK since they're already
public.

### `iter_xpaths` must match `capabilities.supported_paths`

The cross-codec matrix validates that every xpath a codec yields via
`iter_xpaths(tree)` is declared in its `capabilities`.  A mismatch is
a test failure.  Use the shared `_walk_canonical` from
`cisco_iosxe_cli/codec.py` when possible — it's the canonical walker
every canonical-bridged codec reuses.

---

## See also

- [`../canonical/README.md`](../canonical/README.md) — canonical intent model (Layer 3 sibling — every codec parses INTO and renders FROM these types)
- [`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md) — four-layer design and where codecs sit in the migration pipeline
- [`../../../tests/fixtures/real/RESULTS.md`](../../../tests/fixtures/real/RESULTS.md) — per-codec certification state and real-capture coverage matrix
- [`../../../docs/adding-a-canonical-field.md`](../../../docs/adding-a-canonical-field.md) — worked example of wiring a new field through every codec
- [`../../../docs/glossary.md`](../../../docs/glossary.md) — project-jargon reference
