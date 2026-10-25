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

**What the pair is not asked.**  The orchestrator puts a name to
`classify_port_name` and `format_port_identity` only across vendors.
In a job from a codec to itself a name nobody mapped stands as
written, so the pair need not give a codec's own names back (several
do not: `format(classify(name))` loses a Junos management prefix, a
FortiOS role name, an OS10 breakout lane; the test named below
keeps the list of the codecs it is true of).  And an interface named
`<port>.<unit>` goes where its port goes, with its unit, whatever
the classifier makes of the dotted name: a `PortIdentity` has no
place for a unit, so a classifier that reads one can only read it as
the port (Junos, VyOS) — which, left to itself, put two interfaces on
one name.  What a classifier still decides is a dotted name that is
no interface of the tree, such as a Junos reference to unit 0
(`ge-0/0/1.0`): read it as the port.  It also still decides a unit
of a management port, of a loopback and of a port it does not
know, and an interface numbered 0: none of those is sent after its
port across vendors.  Nor is a name that ends in more than ten
digits: a renderer that makes a number of the unit in a name
(FortiOS, VyOS) is not handed one longer than that from another
vendor's config by the orchestrator.  A parser that knows a port's
role from
context sets `CanonicalInterface.kind` (the IOS-XE `Mgmt-vrf` port
is `mgmt`), and the orchestrator reads that ahead of the name.  A
parser that reads no 802.1Q tag for a sub-interface (AOS-CX, OS10)
leaves each such unit to be written without one on every target.
The orchestrator reports that across vendors; in a job from such a
codec to itself the tag is lost the same way and nothing reports
it.  A VLAN interface a platform
NAMES after its parent (`ether1.55` on RouterOS) is classified
`svi`, and keeps its own form on every target.  See
`translate_port_names` and
`tests/unit/migration/test_units_follow_their_port.py`, which runs
every public codec's captures, and a sub-interface from each grammar
that names one onto every codec.

**Where a name depends on the other names, the target places them
together.**  `format_port_identity` is given one name at a time, and
a target whose name for a loopback depends on the config's other
loopbacks cannot be right that way: Junos has one loopback
interface, `lo0`, whose unit 0 is the global table's loopback and of
which each routing instance takes a unit of its own.  Such a codec
overrides `CodecBase.place_loopbacks`, which the orchestrator calls
once, across vendors, with every loopback no entry decides (its
name, its number and its routing instance) and the names the entries
give; it answers the name of each it places and, for each that has
no place, the reason, which the job reports as it drops the name.
Every other codec keeps the default (`None`: each loopback is
formatted alone).  See `tests/unit/migration/test_a_loopback_is_a_unit_of_lo0.py`.

**A `virtual` identity is its own vendor's.**  The kind is for an
interface only one vendor has (an IOS-XE `VirtualPortGroup`, a
RouterOS bridge), and the classifier marks whose it is in `meta`
(`cisco_virtual_port_group`, `mikrotik_bridge`).  A formatter writes
a name for one only where it reads its own mark, and otherwise
returns `None`: no "closest analogue".  A RouterOS bridge written
as a loopback carried the LAN's gateway onto an interface with no
port.  See
`tests/unit/migration/test_a_virtual_interface_is_its_vendors_own.py`.

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
   (`all` is `vlan_id_run(1, 4094)`, counted first: step 4).
   **And say where the platform's text states a trunk's untagged
   VLAN.**  In the tree a trunk's list is what it carries, its native
   VLAN among them.  If the platform writes the native VLAN on a line
   of its own and its allowed line may name it or leave it out, the
   row in `NATIVE_VLAN_AND_THE_LIST` (`_helpers.py`, below) is
   `LIST_DECIDES` and the parser puts the list as the text has it.
   If it states the untagged VLAN BESIDE a list of tagged VLANs, the
   row is `BESIDE_THE_LIST` and the parser adds it
   (`trunk_list_read`).  Add the vendor's sentence for what a
   native VLAN outside the list does -- or "not established" -- to
   the second table of that vendor-reference page.
   **And say what a trunk has for a native VLAN when it states
   none.**  An unset `trunk_native_vlan` means no untagged VLAN, so
   a platform's default is the parser's to put, like the list.  Add
   the codec's row to `TRUNK_THAT_STATES_NO_NATIVE` (`_helpers.py`,
   below) -- the id, or that there is none, or that the text does
   not give it -- with the vendor's sentence in the table "And when
   the config states no untagged VLAN at all" of the same page; tell
   `TrunksByName` each native line an interface states
   (`native_line`; a parser that keeps one record a name has the
   native VLAN on the record and need not), when a port SAYS it is
   a trunk (`says_trunk` / `mode_line`), and the platform's words
   for a native VLAN that is sent tagged (`native_is_tagged`, with
   `tagged=False` for a port's own word that it is not): `settle()`
   then gives a trunk that says it is one and states no native VLAN
   the default, where its list holds it, and gives a trunk whose
   native VLAN is sent tagged none at all.  The default is a trunk's: a
   port the parser takes for a trunk from a trunk line alone gets
   none.  A test fails for a codec that is in one of the three
   tables and not in all of them.
   **And say what the platform's interface `mtu` counts.**  The
   tree's MTU is the payload, the largest IP packet; a platform whose
   number counts a header, a tag or a whole frame converts it at its
   edge.  Add the codec's row to `MTU_BEYOND_THE_PAYLOAD`
   (`_helpers.py`, below), with the vendor's sentence in
   `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/mtu.md`,
   read a stated `mtu` through `mtu_read` and write one through
   `mtu_written` for the interfaces whose number is an Ethernet one
   -- the codec's own classifier says which.  A platform with no
   interface MTU is named, with its reason, in `NO_INTERFACE_MTU` in
   `tests/unit/migration/test_an_mtu_counts_the_payload.py`, which
   fails for a public codec that is in neither.  And say what it
   does with an IP MTU of its own (`ip_mtu`): read and write its
   statement, write it as the one `mtu` (`one_mtu_written`), or
   name the codec in `_SAID_LOST` in
   `tests/unit/migration/test_an_ip_mtu_of_its_own.py`, with the
   matrix saying so; that test fails for a public codec that is
   in none of them.
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
   nearest thing in silence.  A `BESIDE_THE_LIST` renderer writes its
   allowed line WITHOUT the native VLAN (`trunk_list_written`), and writes
   the untagged VLAN only where the list holds it
   (`trunk_untagged_vlan`): a native VLAN outside the list is, in
   the tree, stated and not carried.  A renderer whose platform has
   a default native VLAN writes its form for a trunk that carries
   none where the tree gives a trunk no native VLAN and its list
   holds the default (`wants_no_untagged_vlan`): written no native
   line, it would carry the default untagged.  Where the form is a
   line for the whole switch, decide it over every port
   (`every_native_vlan_tagged`), and say what is not written in a
   `! review:` line.  Where the default has no id the list can be
   asked about, ask of every trunk with no native VLAN: OS10 writes
   each one `no switchport access vlan` under a review line, unless
   another record of the interface states its untagged VLAN (a native
   VLAN, or an access VLAN), which the line would take back.  AOS-S,
   told VLAN by VLAN, asks of the output's member lists: a name tagged
   somewhere, untagged nowhere and on no line of VLAN 1 is taken out
   of VLAN 1 with `no untagged`.
   `tests/unit/migration/test_a_trunk_says_none_nothing_or_all.py`
   fails for a public codec that is neither in the table nor named,
   with its reason, in that module's `NO_ALLOWED_LIST`; and a codec
   that starts to write a trunk's VLANs fails
   `test_a_vlan_left_out_stays_out.py` until it is listed there, and
   then the first module until it has a reader for the new target's
   text.  `test_the_list_holds_the_native_vlan.py` fails for a codec
   that is in one of the two trunk tables and not the other, and
   wants a reader of its own for the new grammar and a row in its
   hand-written table.
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

   And what a text EXPANDS to is counted, which is the codec's to do in
   two places (`netcanon/migration/limits.py`; the Hard Rule in
   `AGENTS.md` has the reasons).  **An expander charges before it
   makes**: where a token becomes many entries — a range of VLAN ids
   or of ports, a keyword for "every", a list copied onto every member
   — count what is about to be made on the line before it is, with what
   the config wrote, which a refusal quotes:
   `charge("vlan_ids", high - low + 1, token)`.  **A loop over lines
   looks at the deadline**: `for line in ticked(raw.splitlines()):`,
   and `tick()` as the first statement of a `while` that walks by
   index.  Nothing else is the codec's: the meter is opened round its
   `parse` and `render` by `CodecBase`, an interface is counted by the
   model, and the finished tree and the output are counted at the
   boundary.  The tests that fail if either is forgotten, all in
   `tests/unit/migration/test_limits.py`:
   `test_every_loop_over_lines_is_ticked`
   (reads the source of every module here);
   `test_a_parse_past_its_deadline_is_stopped` (runs over
   every public codec, and needs the synthetic capture under
   `tests/fixtures/synthetic/<codec>/`);
   `test_every_run_of_entries_has_its_answer`
   (a new `range(...)`, slice of `VLAN_IDS` or `vlan_id_run(...)` goes
   in its table, as `charged` or with what bounds it); and, for a
   reader of VLAN id lists, add its stanza to `WIDE` there — a parser
   whose expander does not count is refused only when its tree is
   finished, and that test tells the difference.  A broad `except` in a
   parser names `LimitExceeded` before it
   (`test_no_broad_handler_swallows_a_refusal`).
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
  `_TARGET_ACCEPTS[<vendor>]`, and a typed password (`plaintext`) is
  in a target's set only where the target has a line that takes one:
  a new user-rendering codec goes in `_TYPED_FORM` in
  `tests/unit/migration/test_a_typed_password_is_not_a_hash.py`.

* **`netcanon/migration/_comments.py`** — a value written into a
  comment stays in it.  Public API: `comment(text, syntax)` (the
  comment with its delimiters) and `comment_text(text, syntax)` (the
  text alone, e.g. for an `ET.Comment`).  A comment that ends at a
  terminator (`slash` `/* */`, `xml` `<!-- -->`) is ended by a value
  that holds it, and what follows is configuration; the helper breaks
  the terminator where it stands.  Build every comment that carries a
  value of the tree through it (both `format_review_comment` helpers
  do); a new codec goes in `_COMMENT_FORMS` in
  `tests/unit/migration/test_a_value_stays_in_its_comment.py`, which
  also reads the source for a block comment built anywhere else.

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

* **`netcanon/migration/_one_value.py`** — a credential or an
  account's name is written as ONE value of the place it goes, or not
  at all.  Public API: `splits(value)` (not one word of a
  word-at-a-time CLI: white space or a `"`), `breaks_its_quotes(value)`
  (cannot stand between quotes on a grammar with no escape, AOS-S),
  `left_out(what, target_label)` (the review line's text; `what` must
  not hold a secret).  A renderer writing a password, community,
  SNMPv3 user or FHRP key asks before it writes, and leaves the record
  out (never alters it) where the value would not be one value; where
  its target quotes, it escapes as the platform documents.  A new
  line-grammar codec is judged by
  `tests/unit/migration/test_a_secret_is_one_value.py` with no entry
  of its own (it walks `list_public_codecs()`); a target that quotes
  goes in that module's `_QUOTES` with the escape it documents.
  For what is not a secret: `one_value_tree(tree, target_label, names=,
  addresses=, unread_text=, no_escape=, test=)`, called once at the top
  of `render_intent`, before the first line, with the fields the
  renderer writes as one word; it returns the tree to write and the
  review lines, which the renderer puts at the top of its output in
  its own comment form.  `one_word(name)` is the one word a name is
  written as.  A new line-grammar codec is judged by
  `tests/unit/migration/test_a_name_is_one_word.py` with no entry of its
  own; a place of its grammar that reads to the end of the line goes in
  that module's `_REST_OF_LINE`, from a vendor page or a committed
  capture that prints such a line, and a target that
  quotes in some places only, in `_QUOTED_PLACES`.

* **`netcanon/migration/_tier3_detection.py`** — Tier-3 stanza-header
  detection.  One `detect_tier3_sections_<vendor>(raw)` per source codec
  (`iosxe_cli`, `iosxe_xml` [no-op], `fortios`, `junos`, `routeros`,
  `opnsense`, `nxos`, `iosxr`, `aoscx`, `vyos`) — see the module for the
  authoritative set.  Each codec's
  `parse()` calls the matching detector and stamps the result onto
  `CanonicalIntent.dropped_tier3_sections` so the migrate page can
  surface the silent-drop in a "Detected in source but not translated"
  banner.  (Junos: the detector is given the set-form the parser
  read, not the text as it came; and `left_out_rows` makes the rows
  for statements the parser read and left out, which
  `is_left_out_row` tells from a section.  The IOS-XE CLI, IOS XR and
  OPNsense parsers add rows of their own: a left-out row for an IOS
  XR `interface preconfigure` stanza, which the router holds and
  does not run, and a section row for an `interface range` header
  and for a `<dhcpd>` zone that has no device, whose pool is left
  out.)  Output is NOTIFICATION-ONLY — never read by render or any
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

* **`netcanon/migration/_one_line.py`** — a value is written on one
  line.  Public API: `one_line_each(tree)` (the pipeline's, after the
  transforms: each run of line breaks as one space, in place, and the
  places it did so, for the job's warnings), `first_line_break(tree)`
  (the check `CodecBase.render` makes: a tree that still holds a break
  is a `RenderError`), `LINE_BREAKS`.  A renderer needs to do nothing:
  it is never handed a value of more than one line, whatever the field,
  so it may put any value into its line as it stands.  A parser that
  reads a value of several lines (FortiOS between its quotes, the XML
  parsers) keeps it as it is; the layout is lost on the way out, and
  the job says where.  The same module keeps every control character
  out (`CONTROL_CHARACTERS`: Unicode's `Cc` but a tab and the
  breaks): `text_only_each(tree)` and `first_control_character(tree)`
  are the same two halves, and a parser that decodes an escape
  (RouterOS `\1B`) reads it as the character and leaves the rest to
  the pipeline.  A secret (`SECRETS`) that holds a break or a control
  character is left out before either mend (`secrets_left_out`): a
  renderer is never handed one with a space in its place.

* **`netcanon/migration/_vlan_labels.py`** — a VLAN's label as its
  name.  Public API: `vlan_labels_as_names(tree)`,
  `label_is_its_name(vlan, interface_names)`, `vlan_labels(tree)`,
  `NAMES_A_VLAN_AFTER_ITS_INTERFACE`.  A renderer whose VLAN is an
  interface (RouterOS, FortiOS) asks `vlan_labels` for each VLAN's
  label and writes it as the interface's where the interface states
  no description; a parser that names every VLAN after its interface
  is in the set, which a test holds equal to the parsers that do so
  on the committed captures.  A codec whose VLAN has
  only a name sets `vlans_have_only_a_name = True` in its class body
  and calls nothing: `run_plan` and `CodecBase.render` apply the rule
  (a VLAN named after an interface of the config, or not named, is
  written with its description as its name).  A public codec that
  leaves the flag `False` is named, with its reason, in
  `NOT_NAME_ONLY` in
  `tests/unit/migration/test_a_vlan_label_is_its_name.py`, which fails
  for one that is in neither.

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
  — the symmetric direction.  Fills port-centric switchport state
  from VLAN-centric membership lists.  The AOS-S parser calls it at
  the end of `parse()`, once every port its lists name has a record
  (`synthesise_missing=False`).  The Arista EOS, Cisco IOS-XE CLI and
  Junos render paths call it too, with the default: for a tree that
  holds a port in a VLAN's list and has no record for it, it makes
  one.  **Do not rely on that from a parser.**  Every other render
  path writes a port — its VLANs and its LAG — from the port's own
  record alone, and the record the projection makes has no interface
  type.  **A parser gives a record to every
  port one of its lists names** (a VLAN's `tagged_ports` /
  `untagged_ports`, a LAG's `members`), and it is the record its own
  empty stanza makes, so that a config and its own rendering parse
  alike.  AOS-S is the worked example
  (`aruba_aoss/parse.py::_a_record_for_every_port_named`): its device
  prints an `interface` stanza only for a port with a setting of its
  own, so most ports of a real capture are named by the lists alone.
  `tests/unit/migration/test_vlan_members_reach_the_output.py` holds
  every public parser to it on the committed captures, and looks for
  each port's VLANs in the output of every target.

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

* **`netcanon/migration/canonical/transforms.py::synthesize_svis_from_vlan_l3`**
  — the other direction: an interface for each VLAN that holds an
  address on its record and has no interface of its own in the tree
  (the Junos parser folds an `irb` unit's address onto the VLAN it
  binds, and keeps no interface for the unit).  Called by the four
  renderers that state a VLAN's address only on a VLAN interface:
  `arista_eos`, `cisco_iosxe_cli`, `cisco_nxos` and `aruba_aoscx`,
  each naming the interface its own way.  An interface of the VLAN is
  recognised in any spelling (`Vlan10`, `vlan10`, `vlan 10`), so a
  tree another codec parsed gets no second one, and the addresses
  after the first are marked `is_secondary`.
  `tests/unit/migration/test_a_vlan_records_address_is_written.py`
  reads each of the four outputs as text and with its parser.

* **`netcanon/migration/canonical/transforms.py::_natural_port_sort_key`**
  — natural-sort key for port-name strings (`1/1, 1/2, 1/10` rather
  than lex `1/1, 1/10, 1/2`).  Used by `project_switchport_to_vlan`
  and the Junos parser's port-list materialisation to guarantee
  cross-vendor list-order parity in `vlan.tagged_ports` /
  `vlan.untagged_ports`; by the AOS-S renderer for the names of its
  VLAN 1 lines (`_out_of_vlan_1`, `_tagged_in_vlan_1`); by the AOS-S
  parser for the order of the interface records it makes from the
  VLAN lists; and by the IOS-XE CLI renderer for the order of its
  interface stanzas.  Wave 7c (commit `87b2248`) added this as
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
  **`sole_vlan_id(text)`** answers "does this list name exactly one id,
  and which" without making the list: a second pass over a line that
  another pass expands asks this, because a line expanded twice is
  counted twice (NX-OS did, for `vlan <range>`).

* **`netcanon/migration/limits.py`** — what one request may make, and
  for how long.  `charge(kind, n, where)` before an expander makes its
  entries; `distinct(kind, names, where)` where the same names made
  again are not more of the kind (the ports `1-48` tagged in 400 VLANs
  are 48 ports); `ticked(iterable)` / `tick()` in a loop over lines.
  `_helpers.charge_id_lines(...)` is for a renderer that writes every
  id of a port's allowed list (IOS-XE, EOS): it adds up the lines as
  the renderer will write them — nothing for a trunk of every VLAN,
  which is no line; the word for a trunk of none; else the ids, and
  `joined_ids_length` says how long a list is written out, without
  writing it — and charges before the first character.
  Callers: `grep -rn "limits import" netcanon/migration`.  See
  `ARCHITECTURE.md` "Config limits".

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
    line>)`, NOT the name it gives the record: the NX-OS parser reads
    `interface port-channel 1` and `interface port-channel 2` as the
    one name `port-channel` (the IOS-XE parser did, until it read a
    type and its number written apart as one name), and those are two
    interfaces.  A stanza met
    twice is one interface; a trunk that states no list has the
    platform's only where the interface says it is a trunk, and a
    trunk the parser inferred from a trunk line has nothing of it.
    Callers: `grep -rn "TrunksByName(" netcanon/migration/codecs`
    (the five parsers of the table with the `switchport` or `vlan
    trunk` grammar; `juniper_junos` keeps its members by name itself).
  * **`unstated_trunk_list(codec, where)`** — the list of a trunk with
    no allowed line: every id or none, a new list each call.  Asked by
    `TrunksByName` and by the Junos parser.  Every id is 4,094
    entries from a stanza of two lines, so it is charged as `all` is,
    before the list is made (`limits.charge`, below); *where* is the
    interface, for a refusal to name.
  * **`merge_trunk_allowed(existing, remainder, unstated=...)`** — one
    `switchport trunk allowed vlan` line applied to the interface's
    list.  `existing=None` while the interface has stated no line,
    and the platform's list as `unstated`: `add` and `remove` then
    start from it, as they do on the device (the copy is charged).
    `TrunksByName` calls it; a parser does not need to.
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

* **`netcanon/migration/codecs/_helpers.py::vlan_carriers(intent)`**
  — for each VLAN of a tree that something carries, the LAG or the
  port that carries it: a LAG one of whose ports names it, then a
  port that names it, then a trunk of every VLAN.  The parent of a
  VLAN's device on a target that hangs each VLAN on one port
  (`opnsense`, `fortigate_cli`).  Ask it once a render: a walk of the
  ports for each VLAN grows with their product.

* **`netcanon/migration/codecs/_helpers.py::NATIVE_VLAN_AND_THE_LIST`**
  — where a platform's text states the VLAN a trunk carries
  untagged, by codec: `LIST_DECIDES` on `arista_eos`, `aruba_aoscx`,
  `cisco_iosxe_cli`, `cisco_nxos` and `juniper_junos` (a native line
  of its own; the allowed line may name the VLAN or leave it out),
  `BESIDE_THE_LIST` on `dell_os10` (the trunk's access VLAN, beside
  an allowed line of tagged VLANs).  The ONE place it is written,
  with the same codecs as the table above and no other; the vendors'
  sentences are in the same vendor-reference page.  In the tree a
  trunk's list is what the trunk carries, its native VLAN among them,
  and a native VLAN the list does not hold is stated and not carried.
  Its readers:
  * **`canonical/transforms.py::trunk_untagged_vlan(allowed,
    native)`** (also importable from `_helpers`) — the VLAN a trunk
    carries untagged, or `None`.  Every reader of a trunk's untagged
    VLAN asks it: `project_switchport_to_vlan`; the OS10 renderer;
    the AOS-S renderer, for the `; review:` line it writes where a
    trunk's native VLAN is outside its list and no `untagged` line
    is written; and the VLAN rename pass (`canonical/vlan_names.py`),
    which asks it before and after a map: a native VLAN the map
    would bring into its port's list is cleared where the map merged
    it with a VLAN of the config that the list names, and the new id
    is taken out of the list where the list only covered that number
    with a range.  Never read `trunk_native_vlan` alone.
  * **`trunk_list_read(codec, stated, untagged)`** — the list a
    parser puts: for a `BESIDE_THE_LIST` codec the tagged VLANs its
    text lists with the untagged one added, in its place among
    them; for a `LIST_DECIDES` codec the list as stated.
  * **`trunk_list_written(codec, allowed, native)`** — what a
    renderer names on its allowed line: for a `BESIDE_THE_LIST`
    codec the list without the native VLAN; for a `LIST_DECIDES`
    codec the list as it stands.
  Both ask the table by the codec's name, as
  `switchport_trunk_allowed_value` asks its own; a codec that is not
  in it is a `KeyError`.  The `LIST_DECIDES` codecs have nothing to
  convert and do not call them.
  Callers: `grep -rn "trunk_list_read\|trunk_list_written\|trunk_untagged_vlan" netcanon/migration`.
  AOS-S is in neither table: it is told VLAN by VLAN, and its port
  records are made by `project_vlan_to_switchport`, which puts the
  VLAN a port is untagged in into the port's list.

* **`netcanon/migration/codecs/_helpers.py::TRUNK_THAT_STATES_NO_NATIVE`**
  — what a trunk has for a native VLAN when its config states NONE,
  by codec: VLAN 1 on `arista_eos`, `aruba_aoscx`, `cisco_iosxe_cli`
  and `cisco_nxos`; `NATIVE_NONE` on `juniper_junos`;
  `NATIVE_OF_THE_SWITCH` on `dell_os10`, the default VLAN of the
  switch, which is a setting no trunk states and is not filled in
  (as a target, an OS10 trunk with no native VLAN is written `no
  switchport access vlan`, under a review line, unless another
  record of the interface states its untagged VLAN -- a native VLAN,
  or an access VLAN).
  The ONE place it is written, with the same codecs as the two tables
  above and no other; the vendors' sentences are in the same
  vendor-reference page, and so is what is not established.  In a
  tree a parser made, an
  unset `trunk_native_vlan` says the port carries no VLAN untagged,
  as far as the platform's text AND its default go.  Its readers,
  all in `_helpers.py`:
  * **`unstated_native_vlan(codec, allowed)`** — the native VLAN a
    parser puts for a trunk that states none: the platform's
    default where it is an id and the trunk's list holds it, `None`
    otherwise.  `TrunksByName.settle()` asks it for a record that
    is a trunk, of an interface that SAYS it is one (`switchport
    mode trunk`; on AOS-CX a `vlan trunk` line), after the record
    has its list -- a trunk with no allowed line holds the default
    by the platform's list.  A port in another mode that keeps
    trunk lines, and a port the parser took for a trunk from a
    trunk line alone, are given none: the same test `settle()`
    makes before it gives the platform's LIST.  It does not ask
    for an interface that states a native VLAN in any of its
    stanzas (`native_line`), nor for one whose text says the
    native VLAN is sent tagged (`native_is_tagged`;
    `tags_every_native_vlan(raw)`, `tags_its_native_vlan(line)` and
    `untags_its_native_vlan(line)` find the words of the
    `switchport` grammar); a trunk of that interface is given no
    native VLAN at all, a stated one included.  The parser then
    mirrors ports onto the VLANs' member lists as before, so the
    default VLAN has a record and the trunk is its untagged member
    -- and a renderer that writes a `vlan` line for every VLAN of
    the tree writes one for it.
  * **`switchport_trunk_native_value(codec, allowed, native)`** —
    what follows `switchport trunk native vlan`, or `None` for no
    line.  Used by the renderers of `arista_eos`, `cisco_iosxe_cli`
    and `cisco_nxos` for a port they write as a TRUNK: no line for
    the platform's default where the trunk's list holds it (no real
    capture of the three prints one), the line for any other
    native VLAN and for the default itself where the list leaves it
    out.  The IOS-XE renderer also writes the trunk lines of a port
    in another mode, and writes the native line of such a port as
    it stands: the parser puts no default back for it.
    (`aruba_aoscx` writes `vlan trunk native 1`, as its captures
    do; `juniper_junos`, `dell_os10` and `aruba_aoss` write the
    untagged VLAN they are given.)
  * **`wants_no_untagged_vlan(codec, allowed, native)`** -- whether a
    trunk is to be written its target's form for "no VLAN
    untagged": no native VLAN in the tree, and the platform's
    default id on its list.  `aruba_aoscx` writes `vlan trunk native
    1 tag`, `arista_eos` `switchport trunk native vlan tag`.  Asked
    only for a record of an interface no record of which has a
    native VLAN (`native_vlan_stated(interfaces)`).  Not asked by
    `dell_os10`, whose default is no id: it writes `no switchport
    access vlan` for every such trunk, under a review line, and asks
    `native_vlan_stated` the same way -- and of an access record of
    the same name with an access VLAN, which states the trunk's
    untagged VLAN on OS10 as well.  `aruba_aoss` is in no table
    and asks VLAN by VLAN (`_out_of_vlan_1` in its renderer).
  * **`every_native_vlan_tagged(codec, interfaces)`** -- whether an
    IOS-XE or NX-OS output says `vlan dot1q tag native`, a line for
    every trunk: where a trunk wants the form, no trunk carries a
    VLAN untagged, and no port is in a mode no line is written for
    or holds trunk lines in no mode (a port with no mode and no
    trunk line is not counted).  Otherwise each such trunk has a
    `! review:` line.
  Callers: `grep -rn "unstated_native_vlan\|switchport_trunk_native_value\|wants_no_untagged_vlan" netcanon/migration`.

* **`netcanon/migration/codecs/_helpers.py::MTU_BEYOND_THE_PAYLOAD`**
  — what a platform's interface `mtu` counts beyond the payload, by
  codec (`MtuCounts(header, per_tag)`): 14 and 4 a tag on
  `juniper_junos` (the media MTU) and `cisco_iosxr`, 22 on
  `dell_os10` (a frame), nothing on the others.  The ONE place it is
  written; `CanonicalInterface.mtu` is the payload.  Its readers are
  **`mtu_read(codec, stated, tags=)`**, for a parser, and
  **`mtu_written(codec, payload, tags=)`**, for a renderer; which
  interfaces they apply to is the codec's own to say (`irb` and a
  port on Junos, not a loopback).  The vendors' sentences are in
  `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/mtu.md`.
  Callers: `grep -rn "mtu_read\|mtu_written" netcanon/migration`.

* **`netcanon/migration/codecs/_helpers.py::IP_MTU_THAT_IS_NOT_STATED`**
  — the IP MTU of an interface whose config states none, on a
  platform where it is a setting with a default of its own that a
  raised `mtu` does not raise (`aruba_aoscx`: 1500).  Its readers
  are **`ip_mtu_read(codec, stated, payload, ipv4=)`**, for a
  parser (`None` where the stated IP MTU is the payload, the
  default where none is stated under a larger payload), and
  **`ip_mtu_written(codec, iface)`**, for a renderer.  A platform
  with one MTU writes **`one_mtu_written(iface)`**: the IP MTU
  where the tree states no payload.
  Callers: `grep -rn "ip_mtu_read\|ip_mtu_written\|one_mtu_written" netcanon/migration`.

* **`netcanon/migration/codecs/_helpers.py::spaced_port_name`** and
  **`without_keyword_stanzas`** — two readings of a Cisco header
  line that the IOS-XE CLI and IOS XR parsers share.
  `spaced_port_name(first, second)` is the interface name two words
  spell: IOS reads `interface ethernet 1/11` and `ip route 0.0.0.0
  0.0.0.0 loopback 66` as one name, so a type on its own followed
  by a number is joined to it, in the letters the config has.  A
  parser that takes the first word for the name makes an interface
  called `ethernet`.  `without_keyword_stanzas(raw)` takes out every
  stanza whose header begins with a word that is no type
  (`NOT_AN_INTERFACE_TYPE`: `preconfigure`, `range`, `breakout`) and
  returns their header lines; the parser runs it before any reader,
  so that nothing in such a stanza binds anything.
  `keyword_stanza_rows(headers)` makes the rows of
  `dropped_tier3_sections` from them, and the keywords are two
  kinds of row: a `preconfigure` stanza is a statement the device
  holds and does not run (a left-out row, as for a Junos `inactive:`
  statement), a `range` stanza or a `breakout` line is in force and
  not translated (its header, a section).  In a route, a word after
  a type is joined to it only where it can be the type's number: an
  address there is the gateway.  (`cisco_nxos`, `aruba_aoscx` and
  `dell_os10` read their headers themselves.)

* **`netcanon/migration/codecs/_helpers.py::without_unread_tags`**,
  **`second_dot1q_tags`** and **`a_tag`** -- a sub-interface's tag
  statement, read whole or not at all (IOS-XE CLI, IOS XR and EOS;
  Junos reads a unit's statements itself and makes the same row with
  `unread_tags_row`).  `a_tag(word)` is one 802.1Q id (1 to 4094, in
  ASCII digits), never the id a range, a list or a keyword begins
  with; `second_dot1q_tags(statement)` is the `(outer, inner)` of a
  Cisco `encapsulation dot1q N [second-dot1q M]`, or `None`.
  `without_unread_tags(raw, is_tag_statement, tags_of)` takes out
  each `interface` stanza whose own tag statement (at the stanza's
  own depth: a submode's is not the stanza's) the parser's `tags_of`
  cannot read, and returns a row for each; the parser runs it before
  any reader, so that a sub-interface is never written with fewer
  tags than it matches.

* **`netcanon/migration/codecs/_scanner.py::without_text_bodies`** --
  `without_text_bodies(raw, opens, unended, *, codec, command=...)`:
  the text with every line of each body of text in it (a banner, a
  macro, a scheduler job) made empty, each keeping its number, so that
  no reader of the parse takes a banner's words for configuration (a
  banner line `username <name> privilege 15 ...` was an account on the
  target).  The loop is shared: it walks the text a line at a time,
  cut where `str.splitlines` cuts it (so a line's number is the
  parser's), and copies it only when a line is emptied.  Where a body
  opens and ends is the parser's own, from its vendor, handed in as
  `opens(text, number)`, which returns a `Body(ends, ended)` or
  `None`; `ends_anywhere(delimiter)` is the rule "at the next
  occurrence of the delimiter, anywhere in a line".  Refused, each in
  a sentence that names the line and quotes nothing: a body still open
  at the end of the text (the parser's `unended`), a line that opens,
  is in or ends a body and ends in another character than a line feed
  (`LINE_END_MESSAGE`, with `codec` and `command` filled in: a device
  ends a line at a line feed, Python at a form feed too), and whatever
  the parser's callables refuse.  The IOS-XE CLI, NX-OS, AOS-CX, OS10,
  AOS-S and IOS XR parsers each wrap it as `without_banner_bodies(raw)`
  and call it first in `parse_intent` (before the JSON/XML check) and
  again where `codec.parse` reads the Tier-3 rows; the AOS-S
  deployment detector calls it too.  IOS XR also runs it once more, on
  a text that held a banner, to count each banner's lines for its
  Tier-3 row (`banner_rows`).  A new parser of a platform with
  banners does the same, from its vendor's rule.  The EOS parser keeps
  its own loop (`without_bodies`), which refuses the same line ends: a
  certificate there opens its body on a later line than the one that
  names it.

* **`netcanon/migration/codecs/_scanner.py::first_flat_stanza`** --
  `first_flat_stanza(raw, headers, *, any_white_space=False)`: the
  line of the first stanza whose body stands at the left margin of a
  text with no indentation, or `None`.  A parser that reads its
  stanzas by their indentation cannot read such a text, and refuses it
  in words before any reader runs (after `without_banner_bodies`, so
  that a banner's lines are no indentation): IOS XR, EOS, AOS-CX,
  IOS-XE CLI, NX-OS and OS10, each with its own `_STANZA_HEADERS` and
  `FLAT_TEXT_MESSAGE`.  Indentation is what the parser's readers take
  for it: a space or a tab by default, any white space with
  `any_white_space` (the readers of the last four ask `str.isspace`).

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
