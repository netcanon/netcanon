# Migration codecs — authorship guide

A **codec** translates between a vendor's native config format and the
shared `CanonicalIntent` tree.  Every new vendor parser/renderer lives
here as a subpackage.

This README is the codec-writing cookbook.  If you're fixing a bug in
an existing codec, start by reading that codec's `codec.py` + the
matching `tests/unit/migration/test_<vendor>.py`.

---

## Shape of a codec

Twelve codecs have shipped (see `RESULTS.md` for the authoritative
roster): the Cisco family `cisco_iosxe_cli` / `cisco_iosxe` /
`cisco_nxos` / `cisco_iosxr`, `arista_eos`, `aruba_aoss` / `aruba_aoscx`,
`juniper_junos`, `vyos`, `opnsense`, `mikrotik_routeros`, and
`fortigate_cli` (plus `_mock`).  The first one you should copy is
whichever vendor is closest in structure to yours:

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
│                       # (+ the model naming rule, physical_port_name,
│                       # where a device-model family names its ports)
│                       # (ALL four CLI codecs have this — mandatory
│                       # when the codec participates in the Tier-3
│                       # rename orchestrator; see cross-vendor mesh
│                       # in netcanon/migration/canonical/port_names.py)
├── deployment_detect.py  # (aruba_aoss) reads the lines of a config that
│                       # state its own hardware; see
│                       # netcanon/migration/deployment_detect.py
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
**cisco_iosxe_cli** (largest render path; ``_walk_canonical`` is
re-exported at module level in ``codec.py`` for back-compat, though the
walker's real home is ``canonical/xpath_walker.py`` and codecs now inherit
``iter_xpaths`` from ``CodecBase``), and
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
`codec.py` blocks on circular imports.  Every codec that joins the
rename-mode mesh ships this split; copy the closest one.

**Two codecs may SHARE one bridge when they are the same platform in
different wire formats.**  `cisco_iosxe` (NETCONF / OpenConfig)
delegates both methods to `cisco_iosxe_cli.port_names` rather than
carrying its own copy: an OpenConfig `<name>GigabitEthernet0/0/0</name>`
and a CLI `interface GigabitEthernet0/0/0` name the same port under the
same grammar, so duplicating it would only create a way for the two to
disagree.  Delegate (don't subclass) — parse and render stay
independent.

⚠️ **Omitting the bridge is not a soft degradation.**  The `CodecBase`
defaults are `classify_port_name` → `kind="unknown"` and
`format_port_identity` → `None`, and `strip_unmappable` defaults to
True — so "no native representation" DELETES the name and the interface
with it, rather than leaving it verbatim as the base docstring claims.
`cisco_iosxe` shipped without a bridge and lost 96% of interfaces as a
target before #482. A codec that cannot translate port names should not
be offered as a target.

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

    # Can a name that differs from an interface's only in letter case
    # be ANOTHER interface on this platform?  True where an operator
    # chooses interface names as free text and case keeps them apart
    # (FortiOS, RouterOS).  False where the device reads two spellings
    # as one (IOS, EOS, AOS-S) -- and also where every interface name
    # is the system's and is lower-case (Junos, VyOS, OPNsense), since
    # another case is then a misspelling of the same port.
    # Model-to-model port mapping compares final names by this rule.
    # The port translator reads it on every translation as well.  The
    # SOURCE's: to count source names when it reports two of them on
    # one target, and to let a rename-map key in another letter case
    # reach its port.  The TARGET's: to decide whether two final names
    # are one place.
    # There is no safe default: False where case tells two interfaces
    # apart merges an operator's interface into a port in a job that
    # reports success; True where it does not lets a misspelling pass
    # beside the port.  State it in every codec's class body --
    # `test_the_codecs_say_which_they_are` fails for a public codec
    # that inherits it.
    port_names_case_sensitive: ClassVar[bool] = False

    # Does the platform find a port by a factory name kept beside the
    # name an operator gave it (RouterOS `set [ find
    # default-name=ether1 ] name=WAN`)?  Leave it out unless your
    # parser fills `CanonicalInterface.default_name`: then set it to
    # True, and model-to-model port mapping will set that field to
    # the port of the declared target each placed port is on -- and
    # then parse your renderer's OUTPUT again to see that each port
    # has a line of its own that looks it up, so your parser must
    # read that lookup back from your own output.
    # `test_the_flag_is_what_the_captures_show`
    # (tests/unit/migration/test_port_name_universe.py) reads the
    # flag off your committed captures.
    # ports_keep_a_factory_name: ClassVar[bool] = True

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        vendor_id="myvendor",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/interfaces/interface/name",
            # ... one xpath per CanonicalIntent field your codec wires.
            # Use the exact strings the shared `_walk_canonical` emits —
            # `classify` is exact-string match, so a path the walker never
            # yields is a dead declaration (the registry honesty test
            # `test_declared_supported_is_walkable` fails on it).
        ],
        # Plus lossy / unsupported as needed.
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

    # iter_xpaths is INHERITED from CodecBase: it walks a CanonicalIntent
    # via the shared `canonical/xpath_walker.py` walker (and handles the flat
    # mock dict).  A canonical-bridged codec needs NO override.  Override only
    # if your tree has a genuinely different shape (e.g. the NETCONF
    # cisco_iosxe codec's nested XML dict).

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
   to model everything.  **If the platform has trunks, a parser that
   makes one states its allowed list.**  The canonical tree has no
   value for "not stated": on a trunk `trunk_allowed_vlans == []` is NO
   VLAN.  Find what the platform's trunk carries when its config has
   no allowed list, in the vendor's own documentation; add the codec's
   row to `TRUNK_THAT_STATES_NO_LIST` (`_helpers.py`, below) and the
   vendor's sentence to the table in
   `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md`;
   and hand what each interface states to a `TrunksByName("<codec>")`
   (below), which gives every record its list when the config has
   been read.  Do not resolve "no allowed line" a stanza: a stanza
   can be met twice, and the list is the interface's.  And tell it
   only what the config STATES — `says_trunk` for a port that says it
   is a trunk, not for one the parser takes for a trunk from another
   line: the platform's default is not given to a guess.
   Read the platform's own words for all and none as what they say
   (`all` is `vlan_id_run(1, 4094)`).
3. **Write `render()`** against the same synthetic fixtures, driving
   toward round-trip stability (`parse(render(parse(raw))) == parse(raw)`
   at the canonical level).  **A trunk's list is one of three
   statements, and each gets the target's own form:** no VLAN (an
   empty list), every VLAN (every id, 1-4094: `trunk_list_says` /
   `is_every_vlan`), or the list.  Write no allowed line for the list
   that is the platform's own default for a trunk — that is what the
   device prints, and what makes a default trunk come back as it went
   — and never the platform's word for "everything" for any other
   list.  Where the platform has no form for one of the three, write
   a `! review:` line in the stanza that says so; do not pick the
   nearest thing in silence.
   `tests/unit/migration/test_a_trunk_says_none_nothing_or_all.py`
   fails for a public codec that is neither in the table nor named,
   with its reason, in that module's `NO_ALLOWED_LIST`; and a codec
   that starts to write a trunk's VLANs fails
   `test_a_vlan_left_out_stays_out.py` until it is listed there, and
   then the first module until it has a reader for the new target's
   text.
4. **Write `probe()`** using 2-3 discriminating structural markers
   unique to your vendor's wire format.  A probe — and everything
   `parse` does — reads whatever was pasted, so its cost has to fit the
   text's length.  Five shapes have each shipped and been mended (the
   Hard Rule in `AGENTS.md` has them): under `re.MULTILINE` write
   `^[^\S\n]+keyword`, never `^\s+keyword` (`\s` crosses newlines); a
   value before trailing white space is `(\S(?:.*\S)?)\s*$`, never a
   lazy `(\S.*?)\s*$`; a trailing number is `(?<!\d)(\d+)$`; lines
   gathered into one are joined once, not added to a string line by
   line; and a handler that needs a record an earlier line made finds
   it by key (`GrowingIndex`, below), never by reading the list —
   `next(...)`, `any(...)`, `name in a_list` — once per line.
   `tests/unit/test_untrusted_text_cost.py` builds texts from
   every pattern of the codec and times its `probe` and `parse`, and
   needs a small capture under `tests/fixtures/` that detection gives
   to the new codec.  Then run `python tools/stanza_cost_search.py
   --codec <name>`: it writes every line and block of the codec's
   captures many times over, which no test does.
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
codec (12 currently shipped — see `RESULTS.md` for the live roster).
The Tier 2 wire-throughs (SNMP
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

* **`netcanon/migration/_radius_secrets.py`** — cross-vendor RADIUS
  shared-secret portability.  Public API:
  `classify_radius_secret(value, source_vendor)`,
  `radius_secret_is_migratable(value, source_vendor, target_vendor)`,
  `unwrap_native_secret(value)`, `format_review_comment(host, ...)`.
  Every codec rendering `CanonicalRADIUSServer.key` MUST call the
  gate: only a plaintext secret crosses a vendor boundary, and a
  FortiGate `ENC` blob is encrypted under its own device's key.
  On a refusal, still emit the server record and add a review
  comment — the operator needs to see the half-configured server.
  A new rendering codec goes in `_TARGET_ACCEPTS` here AND in
  `_RENDERING_TARGETS` in
  `tests/unit/migration/test_radius_secret_portability.py`.

* **`netcanon/migration/_tier3_detection.py`** — Tier-3 stanza-header
  detection.  One `detect_tier3_sections_<vendor>(raw)` per source codec
  (`iosxe_cli`, `iosxe_xml` [no-op], `fortios`, `junos`, `routeros`,
  `opnsense`, `nxos`, `iosxr`, `aoscx`, `vyos`) — see the module for the
  authoritative set.  Each codec's
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
  `aruba_aoscx`, `aruba_aoss`, `cisco_iosxe_cli`, `cisco_nxos`,
  `dell_os10`, `juniper_junos`.  Helper
  internally guards the list of every id (`range(1,4095)`: Junos
  `vlan members all`, AOS-CX `vlan trunk allowed all`, a Cisco or
  Arista trunk that states no list) to avoid synthesising 4094 phantom
  CanonicalVlans: such a trunk goes onto the VLANs already declared.
  Left to itself it synthesises a VLAN for every VID a switchport
  mentions, so every caller that prunes hands it the set it keeps:
  `project_switchport_to_vlan(intent, keep=<the set below>)`.  With
  `keep`, no record is made and no port stamped for a trunk-allowed id
  outside the set — a trunk that states `1-4093` used to be 4,093
  records and stamps for the handful that were kept — and an id that is
  not a VLAN id is still handed to the record, so the parse still
  refuses it.  The six codecs that prune pass `keep=`
  (`grep -rn "keep=legitimate_vlan_ids" netcanon/migration/codecs`);
  `aruba_aoss`, which prunes nothing, passes none.

* **`netcanon/migration/canonical/transforms.py::switchport_declared_vlan_ids`**
  — the "legitimate VID" set the phantom-VLAN prune keeps: declared
  `vlan <N>` stanzas, every `access_vlan` / `trunk_native_vlan` (via the
  narrower `access_and_native_vlan_ids`, which is the primitive, not the
  thing to call), and the members of any `trunk_allowed_vlans` list no
  wider than `TRUNK_ALLOWED_SPECIFICITY_BOUND`.  Currently called by
  `arista_eos`, `aruba_aoscx`, `cisco_iosxe_cli`, `cisco_nxos`,
  `dell_os10`, `juniper_junos` — the six port-centric codecs.  The call
  pattern is fixed: snapshot the set BEFORE the projection, hand it
  over (`project_switchport_to_vlan(intent, keep=legitimate_vlan_ids)`),
  and prune `intent.vlans` to it AFTER.
  A narrow trunk list is a specific operator declaration and its
  VLANs are real; only a WIDE one ("allow everything") synthesises
  nothing.  Excluding trunk members outright — the behaviour before
  2026-09 — silently dropped VLANs at parse time, which no render check
  and no cross-mesh cell could detect.  A new port-centric codec MUST
  adopt this; re-deriving a local keep-set is how the rule drifts.

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

* **`netcanon/migration/canonical/port_names.py::rewrite_port_names`**
  — the port-name sweep: every place a canonical tree keeps a port
  name, written through a resolver.  The translator uses it, and so
  does a parser that finds one port under two names (AOS-S, whose
  device writes a LAG `trk1` and `Trk1`): a codec that has to rename
  a port everywhere calls this rather than walking the tree itself,
  so that it cannot be a field short of the translator.  Beside it,
  `key_by_the_configs_spelling` is the one rule for a rename-map key
  in another letter case; the translator and `run_plan_with_models`
  both apply it.

* **`netcanon/migration/codecs/_helpers.py::GrowingIndex`** — find a
  record, by key, in a list that grows while a config is parsed.  A
  handler runs once per line; one that reads through what the earlier
  lines made (`next(r for r in intent.routing_instances if r.name ==
  name)`) costs the square of the lines.  `GrowingIndex(lambda:
  intent.routing_instances, lambda ri: ri.name).get(name)` reads each
  record once, whoever appended it, and answers with the first of a key
  (or the last, `last=True`).  Used by the Arista, AOS-S and Junos
  parsers; make one per parse and hand it to the handlers that need it.

* **`netcanon/migration/codecs/_helpers.py::Uniques`** — append a value
  to a list unless the list has it, without reading the list.  For a
  list of ONE record that a line adds to — the addresses of one
  interface, the members of one LAG, the route targets of one VRF —
  where `if x not in lst: lst.append(x)` costs the square of the lines
  the record is given and `GrowingIndex` has nothing to index.
  `once.add(lst, x)` keeps first-seen order and drops a repeat, as the
  scan did; one `Uniques()` per parse serves any number of lists.  For
  values that cannot be hashed give a key: `once.add(vlan.ipv4_addresses,
  addr, address_key)` (`address_key` is beside it, for IPv4 address
  records).  Do NOT use it on a list that is reassigned or has entries
  taken out between two calls (an AOS-S VLAN's port lists, the lists
  the switchport projection stamps): keep a set or an insertion-ordered
  dict beside such a list instead.  Callers:
  `grep -rn "Uniques()" netcanon/migration/codecs`.  A new
  look-then-append fails
  `TestNoListIsLookedThroughThenAddedTo` in
  `tests/unit/test_untrusted_text_cost.py` until it is mended or listed
  there with the bound that makes it harmless.

* **`netcanon/migration/codecs/_helpers.py::VLAN_IDS`** and
  **`vlan_id_run(low, high)`** — every VLAN id as one shared tuple of
  ints, and a range of them as a list.  A parser that expands
  `2-4000` builds the list from these (`vlan_id_run(2, 4000)`, or
  `out.extend(VLAN_IDS[low:high + 1])`) and not from `range()`: the
  list is equal either way, and holds a pointer an id where it held a
  new int an id as well — a config can state a wide range on every
  port it has.  Used by `_parse_vlan_list` and `merge_trunk_allowed`
  here and by the Arista and Junos parsers' own expanders.

* **`netcanon/migration/codecs/_helpers.py::TRUNK_THAT_STATES_NO_LIST`**
  — what a trunk carries when its config states NO allowed list, by
  codec: every VLAN on `arista_eos`, `aruba_aoscx`, `cisco_iosxe_cli`
  and `cisco_nxos`; none on `dell_os10` and `juniper_junos`.  The ONE
  place a platform's default is written; the vendors' sentences
  behind each row are in
  `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md`.
  On a trunk a list means what it says — `[]` is no VLAN, every id is
  every VLAN — so "not stated" is resolved where the platform is
  known, by the parser, and nowhere else.  Its readers, all in
  `_helpers.py`:
  * **`TrunksByName(codec)`** — what the interfaces of one config
    state about their trunks, kept by the interface's NAME as the
    config writes it: each allowed line (`allowed_line`, or
    `allowed_is` where a line states the list outright), and that the
    port says it is a trunk (`mode_line` / `says_trunk`).  The parser
    hands it every record it makes (`made`) and calls `settle()` when
    the config has been read; each record then has its interface's
    list.  The key a stanza parser gives is `TrunksByName.key(<header
    line>)`, NOT the name it gives the record: two parsers read
    `interface port-channel 1` and `interface port-channel 2` as the
    one name `port-channel`, and those are two interfaces.  A stanza met
    twice is one interface; a trunk that states no list has the
    platform's only where the interface says it is a trunk, and a
    trunk the parser inferred from a trunk line has nothing of it.
    Callers: `grep -rn "TrunksByName(" netcanon/migration/codecs`
    (the five parsers of the table with the `switchport` or `vlan
    trunk` grammar; `juniper_junos` keeps its members by name itself).
  * **`unstated_trunk_list(codec)`** — the list of a trunk with no
    allowed line: every id or none, a new list each call.  Asked by
    `TrunksByName` and by the Junos parser.
  * **`merge_trunk_allowed(existing, remainder, unstated=...)`** — one
    `switchport trunk allowed vlan` line applied to the interface's
    list.  `existing=None` while the interface has stated no line,
    and the platform's list as `unstated`: `add` and `remove` then
    start from it, as they do on the device.  `TrunksByName` calls
    it; a parser does not need to.
  * **`trunk_list_says(allowed)`** — `TRUNK_NONE`, `TRUNK_ALL` or
    `TRUNK_SOME`; it asks
    **`canonical/transforms.py::is_every_vlan(allowed)`**, the one
    reading of "every VLAN" that a renderer or a pass asks: the VLAN
    rename pass, the Junos renderer, and the renderers that choose
    one parent for a VLAN (`opnsense`, `mikrotik_routeros`,
    `fortigate_cli`) use it as well.  (One reader beside it is not
    the same question: `_every_id` in the same module, for
    `project_switchport_to_vlan`, tells TWO lists apart that are not
    expanded into a VLAN record an id — every id, and every id but 1
    — and takes neither for a list that also holds a number that is
    no VLAN id, so that the parse still refuses it.)
  * **`switchport_trunk_allowed_value(codec, allowed, coalesce=...)`**
    — what follows `switchport trunk allowed vlan` on a trunk, or
    `None` for no line.  Used by the renderers of `arista_eos`,
    `cisco_iosxe_cli`, `cisco_nxos` and `dell_os10`, which ask the
    table what "no line" means on their platform.  (`aruba_aoscx` and
    `juniper_junos` have grammars of their own and call
    `trunk_list_says` / `is_every_vlan`.)

* **LAG-name helpers (location note)** — two LAG-name helpers exist
  but are NOT shared cross-codec utilities and do NOT live in
  `netcanon/migration/canonical/transforms.py`: `_canonical_lag_name`
  (`tools/run_phase4_reconciliation.py`) collapses LAG aliases
  (`Port-Channel1`, `Bundle-Ether10`, `ae0`, `lag1`, `Trk1`) for the
  offline cross-mesh reconciliation only, and
  `_normalise_lag_name_to_arista` (`arista_eos/render.py`) is internal
  to the Arista renderer.  Per-codec LAG naming is handled in each
  codec's own `port_names.py` / render path — don't import these two
  as if they were canonical transforms.

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
test fixtures** (AGENTS.md hard rule).

### Test fixtures, not real credentials

Synthetic hashes in test input should LOOK like real hashes but be
obviously fake (e.g. `$9$fake$hash`, `ENC fakeEncodedHash==`).  Real
captures from upstream-published repos are OK since they're already
public.

### `iter_xpaths` must match `capabilities.supported`

The cross-codec matrix validates that every xpath a codec yields via
`iter_xpaths(tree)` is declared in its `capabilities`.  A mismatch is
a test failure.  `CodecBase.iter_xpaths` already walks a `CanonicalIntent`
via the shared walker in `canonical/xpath_walker.py`, so a canonical-bridged
codec inherits the right behaviour and should NOT override it (nor import
`_walk_canonical` through `cisco_iosxe_cli`).  Override only for a genuinely
different tree shape (e.g. the NETCONF codec's nested XML dict).

---

## See also

- [`../canonical/README.md`](../canonical/README.md) — canonical intent model (Layer 3 sibling — every codec parses INTO and renders FROM these types)
- [`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md) — four-layer design and where codecs sit in the migration pipeline
- [`../../../tests/fixtures/real/RESULTS.md`](../../../tests/fixtures/real/RESULTS.md) — per-codec certification state and real-capture coverage matrix
- [`../../../docs/adding-a-canonical-field.md`](../../../docs/adding-a-canonical-field.md) — worked example of wiring a new field through every codec
- [`../../../docs/glossary.md`](../../../docs/glossary.md) — project-jargon reference
