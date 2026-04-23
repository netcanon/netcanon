# Migration codecs — authorship guide

A **codec** translates between a vendor's native config format and the
shared `CanonicalIntent` tree.  Every new vendor parser/renderer lives
here as a subpackage.

This README is the codec-writing cookbook.  If you're fixing a bug in
an existing codec, start by reading that codec's `codec.py` + the
matching `tests/unit/migration/test_<vendor>.py`.

---

## Shape of a codec

Six codecs have shipped: `cisco_iosxe`, `cisco_iosxe_cli`, `aruba_aoss`,
`opnsense`, `mikrotik_routeros`, `fortigate_cli` (plus `_mock`).  The
first one you should copy is whichever vendor is closest in structure
to yours:

| Wire format | Reference codec |
|---|---|
| Line-oriented indented CLI with `!` delimiters | `cisco_iosxe_cli` |
| Line-oriented CLI with section headers like `/ip address` | `mikrotik_routeros` |
| Nested `config/edit/set/next/end` CLI | `fortigate_cli` |
| XML (config.xml dialect) | `opnsense` |
| NETCONF XML | `cisco_iosxe` |
| Banner + positional port lists | `aruba_aoss` |

Each codec subpackage contains at minimum:

```
netconfig/migration/codecs/<vendor>/
├── __init__.py         # exports the codec class; usually one line
└── codec.py            # parse + render + probe + metadata
```

Larger codecs additionally split out pure helpers into sibling
modules — this is an established repo-wide convention, not optional
flair.  The `codec.py` stays focused on I/O orchestration; the
helpers stay easy to unit-test in isolation:

```
netconfig/migration/codecs/<vendor>/
├── codec.py            # orchestration — parse, render, probe
├── port_names.py       # pure classify_port_name + format_port_identity
│                       # (ALL four CLI codecs have this — mandatory
│                       # when the codec participates in the Tier-3
│                       # rename orchestrator; see cross-vendor mesh
│                       # in netconfig/migration/canonical/port_names.py)
├── vlan_heuristics.py  # (fortigate_cli) shared parse/render helpers
│                       # for VLAN iface-name detection
└── _svi_absorption.py  # (aruba_aoss) documents the 3-codepath rule
                        # that absorbs SVI L3 into VLAN stanzas
```

**`port_names.py` is mandatory** for any codec that participates in
the rename-modal flow.  The cross-vendor orchestrator at
`netconfig/migration/canonical/port_names.py` imports each codec's
pair of pure functions directly — a codec that inlines them inside
`codec.py` blocks on circular imports.  The four CLI codecs
(`cisco_iosxe_cli`, `aruba_aoss`, `mikrotik_routeros`,
`fortigate_cli`) all follow the split; copy the closest one.

**`_svi_absorption.py`-style doc modules** are encouraged when a
codec has a cross-cutting invariant spanning 3+ code paths.  The
Aruba example documents why three different methods need to agree
on a constant — a future contributor changing one without the
others would silently break round-trip.  See
`netconfig/migration/codecs/aruba_aoss/_svi_absorption.py` for the
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
as the module is importable under `netconfig/migration/codecs/`, the
pkgutil-based auto-discovery in `netconfig/migration/__init__.py` picks
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
   new `netconfig/migration/codecs/<vendor>/` directory.
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

Rule of thumb: one feature, one commit touching all 5 codecs.  The
Tier 2 wire-throughs (SNMP, LAGs, local_users, DHCP, RADIUS, MTU)
each landed as a single commit per feature with regression tests in
a dedicated `test_<feature>_wire_through.py` file.

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
