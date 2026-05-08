# Adding a canonical field — worked example (MTU)

Use this as the template when extending `CanonicalIntent` with a new
field.  The worked example is the per-interface MTU wire-through that
landed as commit `e3b48b4`; every step below maps to a concrete change
you can `git show` for reference.

**Two shapes of this commit:**

1. **Wire-through (this doc's main pattern):** schema + every codec's
   parse + every codec's render + tests, all in one commit.  Best when
   the feature is cross-cutting and you know exactly how each codec
   emits it.  MTU was this shape.
2. **Ship-before-wire:** schema + `Unsupported` entries on the
   capability matrices of every relevant codec, no parse/render wiring
   yet.  Best when the feature is DC-class or niche and codec wire-up
   will land incrementally as demand arrives.  `CanonicalVxlan` +
   `CanonicalEvpnType5Route` are the reference case — see commit for
   GAP 1 in the translator-plans roadmap.  Each later codec-wiring
   commit demotes the `Unsupported` entry to `supported`/`lossy`.

---

## The shape of the work

Adding a canonical field is one logical feature that touches
**all 5 codecs + the canonical model + tests** in a single commit.
The pattern is rehearsed: the Tier 2 wire-throughs (SNMP, LAGs,
local_users, DHCP pools, RADIUS servers) all shipped in this shape
and so did MTU.

Budget: 30-60 minutes of focused work for a simple field like MTU;
2-3 hours for something with cross-field semantics (like LAGs which
have a per-interface `lag_member_of` backref).

---

## Step-by-step

### 1. Declare the field on the canonical model

If it's a per-interface attribute, add to `CanonicalInterface` in
`netcanon/migration/canonical/intent.py`:

```python
class CanonicalInterface(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    interface_type: str = ""
    mtu: int | None = None                   # ← already there
    ipv4_addresses: list[CanonicalIPv4Address] = Field(default_factory=list)
    # ...
```

`None` as the default is the convention — codecs distinguish "field
absent in source config" from "field present with value N" and
render accordingly.  For collection fields use `Field(default_factory=list)`.

Top-level features (an entire new canonical object like `CanonicalDHCPPool`)
get their own class in the same file plus a new field on `CanonicalIntent`:

```python
class CanonicalIntent(BaseModel):
    # ...
    dhcp_servers: list[CanonicalDHCPPool] = Field(default_factory=list)
```

### 2. Wire each codec's `parse()` to populate the field

For MTU, the interesting cases:

**Cisco IOS-XE CLI** (`netcanon/migration/codecs/cisco_iosxe_cli/codec.py`):
add a regex at module scope, match inside the interface-stanza loop,
forward into the intermediate dict, and set on the built
`CanonicalInterface`:

```python
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)

# In the interface-body loop:
mm = _MTU_RE.match(line)
if mm:
    try:
        current["mtu"] = int(mm.group(1))
    except ValueError:
        pass
    continue

# In _build_canonical_interface:
return CanonicalInterface(
    # ... existing fields ...
    mtu=raw.get("mtu"),
)
```

**OPNsense** (XML-based): add an `<mtu>` element parse in
`_parse_interface_zone_canonical`:

```python
mtu_el = el.find("mtu")
if mtu_el is not None and mtu_el.text:
    try:
        iface.mtu = int(mtu_el.text.strip())
    except ValueError:
        pass
```

**MikroTik** (key=value): inside `_parse_interface_ethernet`:

```python
if "mtu" in kv:
    try:
        iface.mtu = int(kv["mtu"])
    except ValueError:
        pass
```

**FortiGate** (`config/edit/set` block parser): inside the `edit` loop
of `_apply_system_interface`:

```python
mtu_tokens = edit.settings.get("mtu")
if mtu_tokens:
    try:
        iface.mtu = int(mtu_tokens[0])
    except ValueError:
        pass
```

**Aruba AOS-S**: skipped intentionally — AOS-S has no per-port MTU
(only a global `jumbo` flag).  When a vendor genuinely can't carry
your field, don't fake it — document the gap in the commit message
and in `tests/fixtures/real/RESULTS.md`.

### 3. Wire each codec's `render()` to emit the field

Render side mirrors parse.  Render only when the field is non-default
to avoid emitting noise:

**Cisco** (parse-only — no render side for this codec).

**OPNsense**:
```python
if iface.mtu is not None:
    ET.SubElement(zone_el, "mtu").text = str(iface.mtu)
```

**MikroTik**:
```python
if iface.mtu is not None:
    parts.append(f"mtu={iface.mtu}")
```

**FortiGate** (needs an extra `mtu-override enable` per FortiOS
semantics — be aware of vendor quirks):
```python
if iface.mtu is not None:
    out.append("        set mtu-override enable")
    out.append(f"        set mtu {iface.mtu}")
```

### 4. Regression test file

Create `tests/unit/migration/test_<feature>_wire_through.py` with one
class per codec — parse assertions, render assertions, round-trip,
and ideally one cross-codec flow.  Template from
`test_mtu_wire_through.py`:

```python
class TestCiscoMTUParse:
    def test_simple_mtu(self):
        raw = "interface GigabitEthernet1/0/1\n mtu 9000\n!\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].mtu == 9000

    def test_mtu_absent_stays_none(self):
        # Critical — distinguishes "parsed and saw no mtu" from
        # "parsed and field defaulted".
        ...

class TestOPNsenseMTUParseRender:
    def test_round_trip(self):
        c = OPNsenseCodec()
        raw = "<opnsense>...<mtu>1492</mtu>...</opnsense>"
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].mtu == second.interfaces[0].mtu == 1492

# ... per codec ...

class TestCiscoToOPNsenseMTU:
    """Cross-vendor flow proves the canonical bridge works end-to-end."""
    def test_cisco_mtu_reaches_opnsense_output(self):
        raw = "interface Gi1/0/1\n mtu 9000\n!\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        out = OPNsenseCodec().render(intent)
        assert "<mtu>9000</mtu>" in out
```

Target ~15-25 tests for a simple field; the MTU wire-through shipped
with 14.

### 5. Verify against the real-capture corpus

Run `pytest tests/unit/migration/test_real_captures.py -v -s` — the
coverage summary lines will show the new field being populated from
real fixtures (or not, which is also useful signal).  For MTU:

```
[real-capture] ntc_carrier_interfaces.txt
    interfaces=6 mtu_present=2   # 9096 and 1546
[real-capture] routeros_diff_verbose_export.rsc
    interfaces=9 mtu_present=9   # 1500 across the board
```

If a round-trip test fails on the real corpus, you've likely found a
real bug — fix it in the same commit and add a regression test.  Do
NOT add to `_KNOWN_ROUNDTRIP_GAPS` unless the fix is genuinely a
separate session.

### 6. Capability matrix declaration

Each codec's `_CAPS` needs a new entry in `supported_paths` (or
`lossy_paths` / `unsupported_paths` as appropriate):

```python
_CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
    supported_paths=[
        # ...
        "/interfaces/interface/config/mtu",
    ],
)
```

### 7. Update the roadmap

Mark the field SHIPPED in `translator-plans.txt` (Fidelity Polish
section for single fields, Tier 2 Remaining section for bigger
features).  Include the regression-test count and which real
fixtures now surface the data.

### 8. Add a HUMAN_TESTING.md entry

A one-line paste-this-and-check prompt for manual validation in
the UI:

```markdown
- [ ] **MTU** (Cisco -> OPNsense): paste `interface Gi1/0/1 / mtu 9000`;
      target should emit `<mtu>9000</mtu>` in the interface zone.
```

---

## Commit shape

One commit per canonical field, touching:

- `netcanon/migration/canonical/intent.py` (model)
- 4-5 codec files (parse + render per codec)
- `tests/unit/migration/test_<feature>_wire_through.py` (NEW)
- Possibly `translator-plans.txt` + `HUMAN_TESTING.md`

Commit message format — see `git show e3b48b4` (MTU wire-through) or
`git show e495a0b` (local_users) for the reference pattern.  Key
points to include:

- One-line summary with the feature name
- What got wired per codec, including deliberate skips
- Test count and where they live
- Real-capture coverage impact (which fixtures now surface the field)
- Total test count before / after

---

## Gotchas

### Default values matter

`mtu: int | None = None` means the codec explicitly distinguishes
"not set in source" from "set to 0".  If the canonical default were
`1500`, you couldn't tell those apart — bad for round-trip fidelity.
Use `None` for optional scalars, `Field(default_factory=list)` for
collections.

### Don't break existing round-trips

After wiring the field, run the full real-capture harness
(`pytest tests/unit/migration/test_real_captures.py`).  New parse
logic can accidentally pick up lines that used to be ignored,
changing the canonical tree for existing fixtures — which breaks
round-trip stability with the existing render logic.

### Cross-feature interactions

Some fields have cross-feature semantics — e.g. adding `lag_member_of`
on `CanonicalInterface` also needs a shared transform
(`project_switchport_to_vlan` for Cisco, similar for others) or the
canonical tree will be incomplete.  If your field is part of a bigger
structural shift, create `netcanon/migration/canonical/transforms.py`
helpers and wire them in each codec's `parse()` after the per-line
extraction.

### Per-vendor quirks go in codec code, not canonical

The canonical model should stay cross-vendor-clean.  Vendor-specific
rules (FortiGate needs `mtu-override enable`; AOS-S has no per-port
MTU at all) belong in the codec's render path, not on the canonical
field definition.  Document the quirk in a render-side comment.

### Switch-level globals stamped onto every record

Some fields are conceptually switch-level (one per device) but the
canonical type they belong on is record-shaped (one per VLAN, one per
VRF, etc.).  The pattern: store the same value on every record at
parse-time, render reads the first non-empty record and emits once.
`CanonicalVxlan.source_interface` + `CanonicalVxlan.udp_port`
(GAP-EVPN-2) are the reference case — Arista emits both inside the
single `interface Vxlan1` stanza alongside per-VNI mappings, while
Junos emits them under `set switch-options ...` as siblings of the
per-vlan mappings.  The canonical model unifies them as record-level
fields so a tree built from N VNIs carries N copies of the value (each
identical).  Render-side: walk the records, take the first non-default,
emit once.  Parse-side: capture into a scratch local during the walk,
back-patch every record at end-of-stanza (operators sometimes emit the
global AFTER the per-VNI mappings).  This avoids inventing a per-tree
"VTEP profile" type whose only consumer is render — keeps the
canonical surface small.

---

## IPv6 address wire-through (GAP-EVPN-3)

A second worked example: `CanonicalIPv6Address` + per-interface
`ipv6_addresses`, wired through every bidirectional codec in a single
commit.  Followed the MTU pattern verbatim with two extras worth
calling out:

1. **Scope discriminator.**  IPv6 has a global / link-local
   address-class distinction that's keyword-tagged on Cisco / Arista
   (`ipv6 address X link-local`) but prefix-inferred on Junos /
   MikroTik / OPNsense / FortiGate.  The canonical model carries
   `scope: str = "global"` as a normalised enum; codecs that
   keyword-tag round-trip the keyword, codecs that don't infer scope
   from the `fe80::/10` prefix at parse time.

2. **Vendor-placeholder filtering.**  FortiGate's `set ip6-address
   ::/0`, OPNsense's `<ipaddrv6>dhcp6</ipaddrv6>` / `idassoc6`, and
   AOS-S's `ipv6 address dhcp full` are vendor-default /
   DHCPv6-keyword markers that don't represent static addresses.
   Codecs filter them on parse so the canonical tree stays clean —
   without the filter, every FortiGate fixture in the corpus would
   produce 40+ spurious `::/0` records.  The pattern: parse-side
   gates the canonical-record append behind a syntactic check (e.g.
   "address contains a colon" for OPNsense's keyword vs colon-hex
   discriminator); render-side emits without re-introducing the
   placeholder.

## See also

- [`../netcanon/migration/canonical/README.md`](../netcanon/migration/canonical/README.md) — canonical intent model overview and Tier 1 / 2 / 3 promotion rules
- [`../netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md) — codec authorship guide (every codec touched by a wire-through lives here)
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — four-layer design and where canonical sits in the migration pipeline
- [`glossary.md`](glossary.md) — project-jargon reference (canonical, codec, wire-through, ship-before-wire)
