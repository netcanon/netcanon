# Phase 4d — fix-task spawn drafts

This file holds self-contained prompt drafts for the top-6 leverage
fixes identified in
[`PHASE4_RECONCILIATION.md`](PHASE4_RECONCILIATION.md).  Each entry
is intended to be passed to `mcp__ccd_session__spawn_task` by an
orchestrator: the spawned session has no memory of the Phase 4
conversation, so each prompt must stand on its own with file paths,
diff context, expected behaviour, and the test that should pass
after the fix.

The drafts deliberately keep the per-vendor markdown links so the
spawned agent can read the full bug-by-bug attribution before
deciding how to slice the fix.  Title length is kept under 60
characters for the chip label.

---

## Draft 1 — Widen aruba_aoss parse iface regex for cross-vendor names

**Title:** `Widen aruba_aoss parse iface regex for cross-vendor names`

**Tldr:** The Aruba AOS-S parser's interface-header regex rejects
hyphenated, dotted, and multi-slash port names (`ge-0/0/1`,
`GigabitEthernet0/0/0`, `irb.100`, `Port-channel1`) on re-parse,
even though the renderer emits them verbatim.  Widening the regex
clears roughly 66 CODEC_BUG cells, the largest single fix in the
backlog.

**Prompt:**

```
You are fixing the highest-leverage codec defect in the Phase 4
backlog.  Read the per-vendor findings in
`tests/fixtures/real/phase4_findings_juniper_junos.md` (Finding 1,
~40 cells) and `tests/fixtures/real/phase4_findings_cisco_iosxe.md`
(Finding 1, ~4 cells), plus
`tests/fixtures/real/phase4_findings_cisco_iosxe_cli.md` (Pattern G
on Aruba parser hyphens) and the broader synthesis in
`tests/fixtures/real/PHASE4_RECONCILIATION.md` (rank 1 in the top-6
table) before editing.

Fix locus: `netconfig/migration/codecs/aruba_aoss/parse.py:174-176`.
The current regex is:

    _IFACE_HEADER_RE = re.compile(
        r'^interface\s+("?[A-Za-z]*\d+(?:/\d+)?"?)\s*$',
        re.IGNORECASE,
    )

It demands `[A-Za-z]*\d+(?:/\d+)?` — i.e. at most one slash segment,
mandatory trailing digit, no hyphen, no dot.  This rejects:

* `ge-0/0/1`, `xe-0/0/0`, `et-0/0/0` (Junos: hyphen + double slash)
* `ge-0/0/1.100` (Junos sub-unit: extra `.unit` segment)
* `irb`, `irb.100` (Junos pseudo-interface, no leading digit OR dot)
* `GigabitEthernet0/0/0`, `TenGigabitEthernet1/0/1` (Cisco: triple-
  segment slash count)
* `Port-channel1`, `Port-Channel10` (LAG name hyphens — also affects
  `_parse_port_list`'s sub-tokeniser, see Pattern G in the
  cisco_iosxe_cli markdown for the parallel fix needed there)

Recommended widening (per the juniper_junos findings markdown):

    _IFACE_HEADER_RE = re.compile(
        r'^interface\s+("?[A-Za-z][\w./\-]*"?)\s*$',
        re.IGNORECASE,
    )

This accepts any leading alpha followed by word-chars / dots /
slashes / hyphens.  Verify that legitimate AOS-S forms (`A1`, `1`,
`1/A1`, `Trk1`, `25`) all still match — the leading alpha
requirement breaks `1` and `25`, so the alternation needs to allow a
bare-numeric form too.  The shipped form must accept both bare
numerics and Cisco-shaped names.  Re-test against
`tests/fixtures/real/aruba_aoss/*.cfg` to ensure no regression on
real captures.

Companion concerns documented in the per-vendor markdowns:

* The render path at `aruba_aoss/render.py:329-332` emits
  `interface {iface.name}` literally without any port-rename mesh.
  Widening parse alone is the cheap fix; an architecturally cleaner
  alternative is to apply a port-rename mesh on render so cross-
  vendor names land on AOS-S native forms (`1/A1`, etc.).  The
  Phase 3 expectation YAMLs presume the rename mesh exists; until
  it's wired, parse-side widening is the pragmatic shortcut.
* `_parse_port_list` (line 250 + `_expand_port_range` at line 265)
  splits any token containing `-` as a range, shredding
  `Port-channel1` into `["Port", "channel1"]`.  Document this as a
  follow-up bug if the regex fix doesn't already address it; the
  cisco_iosxe_cli findings markdown (Pattern G) has the diagnosis.

Test that should pass after fix:

    # tests/unit/migration/codecs/aruba_aoss/test_parse_iface_header.py
    from netconfig.migration.codecs.aruba_aoss.parse import _IFACE_HEADER_RE

    def test_iface_header_accepts_cross_vendor_names():
        assert _IFACE_HEADER_RE.match("interface ge-0/0/1")
        assert _IFACE_HEADER_RE.match("interface ge-0/0/1.100")
        assert _IFACE_HEADER_RE.match("interface irb")
        assert _IFACE_HEADER_RE.match("interface irb.100")
        assert _IFACE_HEADER_RE.match("interface GigabitEthernet0/0/0")
        assert _IFACE_HEADER_RE.match("interface TenGigabitEthernet1/0/1")
        assert _IFACE_HEADER_RE.match("interface Port-channel1")
        # Native AOS-S forms must still match.
        assert _IFACE_HEADER_RE.match("interface 1")
        assert _IFACE_HEADER_RE.match("interface 25")
        assert _IFACE_HEADER_RE.match("interface A1")
        assert _IFACE_HEADER_RE.match("interface Trk1")
        assert _IFACE_HEADER_RE.match("interface 1/A1")

After the fix, re-running `tools/run_full_mesh.py` and
`tools/run_phase4_reconciliation.py` should show approximately 66
CODEC_BUG cells transitioning to ALIGNED across:
`juniper_junos → aruba_aoss` (40), `cisco_iosxe → aruba_aoss` (4),
`cisco_iosxe_cli → aruba_aoss` (2 partial), and ~18 cells in the
opnsense → aruba_aoss interface-count cascade.

Do not modify the per-vendor findings markdowns — they are committed
authoritative references.  Update `tests/fixtures/real/RESULTS.md`
if the fix flips any per-codec certification disposition.
```

---

## Draft 2 — Loosen mikrotik_routeros render ethernet filter

**Title:** `Loosen mikrotik render filter for non-ether iface names`

**Tldr:** The RouterOS renderer only emits `/interface ethernet`
rows for `ether*`-named or `default_name`-bearing interfaces, so
cross-vendor names like `wan`/`lan` (opnsense), `ge-0/0/X` (Junos),
`Loopback0`/`Tunnel100` (cisco) silently drop their description /
mtu / enabled / dhcp_client state.  Loosening the filter clears
about 58 CODEC_BUG cells.

**Prompt:**

```
You are fixing the second-highest-leverage codec defect in the
Phase 4 backlog.  Read the per-vendor findings in
`tests/fixtures/real/phase4_findings_juniper_junos.md` (Finding 2,
~28 cells), `tests/fixtures/real/phase4_findings_opnsense.md` (B1,
~30 cells), and `tests/fixtures/real/phase4_findings_cisco_iosxe.md`
(Finding 1 mikrotik branch) before editing.  The cross-cutting
synthesis is in `tests/fixtures/real/PHASE4_RECONCILIATION.md`
(rank 2 of the top-6).

Fix locus: `netconfig/migration/codecs/mikrotik_routeros/render.py`
lines 85-110, where `ethernet_ifaces` is filtered through
`_is_ethernet_name(i.name) or _is_ethernet_name(i.default_name) or
(i.interface_type == "ianaift:ethernetCsmacd" and i.default_name)`.
`_is_ethernet_name` (parse.py:832-834) is the literal regex
`^ether\d`.

The defect: cross-vendor sources name interfaces `wan`, `lan`,
`opt1`, `lo0` (opnsense), `ge-0/0/0`, `xe-0/0/1`, `irb` (Junos),
`GigabitEthernet0/0/0`, `Loopback0`, `Tunnel100` (cisco).  None of
those match `^ether\d`, and cross-vendor codecs don't populate
`default_name` (it's a RouterOS-internal field).  Result: the
`/interface ethernet` block emits zero rows for those interfaces;
their description / mtu / enabled / dhcp_client state never reaches
the wire.  Their IP addresses do reach the wire via `/ip address`
rows (which iterate every `(iface, addr)` pair), so the iface
re-materialises on reparse but with default attribute values.
IP-less interfaces (e.g. opnsense `wan` zone in DHCP-client mode)
disappear entirely.

Recommended fix (per the per-vendor markdowns):

    # Inside the ethernet_ifaces selection logic:
    ethernet_ifaces = [
        i for i in tree.interfaces
        if not _looks_like_vlan_iface(i.name)
        and not _looks_like_bridge_iface(i.name)
        and not _looks_like_lag_iface(i.name)
    ]

The find-key already falls back to canonical name when default_name
is empty (`find_key = iface.default_name or iface.name`), so a
`set [ find name=wan ] disabled=no` row is harmless even on a real
RouterOS device that doesn't have a port called `wan` (the operator
will see the rename intent in the deploy artifact).

Companion concerns:

* `/interface vlan` (render.py:147-192) emits one row per
  `tree.vlans` entry that doesn't already have a matching VLAN
  interface, and parse re-materialises a fresh `CanonicalInterface`
  per VLAN.  The opnsense findings markdown (B1) documents the
  resulting over-emit on opnsense → mikrotik (5 synthetic VLAN
  ifaces appearing in the round-tripped tree).  The cleaner fix is
  to ensure the round-trip doesn't invent interfaces that didn't
  exist in the source — either annotate the rendered VLAN row with
  metadata that makes the parser skip materialising it as a
  separate CanonicalInterface, or filter at parse time.
* The juniper_junos markdown also names a Loopback / Tunnel
  emission gap on the cisco_iosxe → mikrotik pair (Finding 1
  mikrotik branch).  Once the ethernet filter is loosened, those
  iface types still need a render path — RouterOS expresses
  loopback as a /interface bridge (or /interface ovpn-server, or
  /interface gre — depends on platform).  Pick a sensible default
  and document it in the codec README.

Test that should pass after fix:

    # tests/unit/migration/codecs/mikrotik_routeros/test_render_non_default_name.py
    def test_render_non_ether_iface_preserves_attrs():
        intent = CanonicalIntent(interfaces=[
            CanonicalInterface(name="ge-0/0/1", description="trunk",
                               mtu=9216, enabled=False),
            CanonicalInterface(name="wan", enabled=True,
                               ipv4_addresses=[]),
            CanonicalInterface(name="lan", enabled=True,
                               ipv4_addresses=[CanonicalIPv4Address(...)]),
        ])
        out = render_intent(intent)
        # All three ifaces emit some `/interface ethernet` line.
        assert "/interface ethernet" in out
        for name in ("ge-0/0/1", "wan", "lan"):
            assert name in out
        # Round-trip preserves description / mtu / enabled.
        roundtrip = parse_intent(out)
        by_name = {i.name: i for i in roundtrip.interfaces}
        assert by_name["ge-0/0/1"].description == "trunk"
        assert by_name["ge-0/0/1"].mtu == 9216
        assert by_name["ge-0/0/1"].enabled is False
        assert "wan" in by_name and "lan" in by_name

After the fix, expect roughly 58 CODEC_BUG cells transitioning to
ALIGNED: `juniper_junos → mikrotik_routeros` (28),
`opnsense → mikrotik_routeros` (30), with smaller wins on
cisco_iosxe / cisco_iosxe_cli / fortigate_cli sources.

Do not modify the per-vendor findings markdowns.  If the fix lands
new tests, update `tests/README.md` if the markers used change.
```

---

## Draft 3 — Emit `<if>` child for opnsense interface zones

**Title:** `Emit <if> child for opnsense interface zones on render`

**Tldr:** The OPNsense renderer skips the `<if>` child element when
a zone has no other content, so the parser drops the entire zone via
its "empty stub" rule, and case-mangled zone tags lose original
port-name identity.  Real OPNsense always carries `<if>igb0</if>`;
emitting it makes the round-trip invertible and clears about 23
cells.

**Prompt:**

```
You are fixing the third-highest-leverage codec defect in the
Phase 4 backlog.  Read
`tests/fixtures/real/phase4_findings_aruba_aoss.md` (O1+O2, 8 cells),
`tests/fixtures/real/phase4_findings_arista_eos.md` (OP-1, 5 cells),
`tests/fixtures/real/phase4_findings_cisco_iosxe_cli.md` (Pattern D,
5 cells), and
`tests/fixtures/real/phase4_findings_fortigate_cli.md` (C, 10 cells)
for the bug-by-bug detail.  Top-level synthesis is in
`tests/fixtures/real/PHASE4_RECONCILIATION.md` (rank 3 of the top-6).

Fix locus: `netconfig/migration/codecs/opnsense/render.py:126-144`
(per-iface zone emit), with a companion change in
`netconfig/migration/codecs/opnsense/parse.py:354-360`
(`_parse_interface_zone_canonical`).

Two cooperating defects:

1. **Empty-zone drop.**  Render emits per-iface XML element
   `<zone_tag>...</zone_tag>` but only populates child elements
   (`<descr>`, `<enable>`, `<ipaddr>`, etc.) when the canonical
   field is non-empty.  An interface with `enabled=False`, no
   description, no MTU, no IPs produces a self-closing `<zone_el/>`.
   Parse then drops it via "no `<if>` AND zero children → return
   None" (line 360).  Sparse OPNsense exports lose entire zones.
2. **Zone-tag mangling is non-invertible.**  `_zone_tag_for(iface.name)`
   (line 279) lowercases and replaces non-alphanumeric chars with
   `_`, prepending `if_` when the first char is a digit.  So
   `Ethernet0` becomes `<ethernet0>`, `1/A1` becomes `<if_1_a1>`,
   `A1` becomes `<a1>`, etc.  The original port-name identity is
   destroyed because the renderer never carries it forward.  Two
   distinct port names can collide on the same XML tag, dropping
   one (verified in the aruba_central_5memberstack fixture: 48
   ifaces → 46 round-tripped).

Recommended fix (per the per-vendor markdowns, identical
recommendation in three of them): always emit `<if>` carrying the
original canonical name as the first child of every zone element.

    # opnsense/render.py:128 (top of per-iface emission loop)
    if_el = ET.SubElement(zone_el, "if")
    if_el.text = iface.name
    # ... existing conditional <descr>, <enable>, etc. emissions

Then update the parser to prefer the `<if>` text when present:

    # opnsense/parse.py:354-360 (_parse_interface_zone_canonical)
    if_el = el.find("if")
    if if_el is not None and if_el.text:
        iface_name = if_el.text.strip()
    else:
        iface_name = el.tag  # legacy fallback
    iface = CanonicalInterface(name=iface_name)

Drop the "empty zone → return None" rule; named-but-empty interfaces
should round-trip.

Companion concerns:

* If two distinct canonical iface names sanitise to the same zone
  tag (collision), `_zone_tag_for` should append a disambiguator
  (`_2`, `_3`).  This is the tertiary fix called out in the
  aruba_aoss markdown (O1) — only matters once the `<if>`-recovery
  fix is in place, since the colliding tag would otherwise just
  drop a record.
* The ipv6 link-local-vs-global single-slot defect (OP-2 in arista
  markdown, D in mikrotik markdown) is independent and should be
  filed separately — that one needs `<virtualip>` extension or YAML
  reclassification.

Test that should pass after fix:

    # tests/unit/migration/codecs/opnsense/test_iface_name_roundtrip.py
    def test_zone_round_trip_preserves_name_and_count():
        intent = CanonicalIntent(interfaces=[
            CanonicalInterface(name="Ethernet0", enabled=True),
            CanonicalInterface(name="A1", enabled=True),
            CanonicalInterface(name="1/A1", enabled=True),
            CanonicalInterface(name="GigabitEthernet0/0/0", enabled=True),
            CanonicalInterface(name="port15", enabled=False),  # sparse
        ])
        out_xml = render_intent(intent)
        roundtrip = parse_intent(out_xml)
        names = sorted(i.name for i in roundtrip.interfaces)
        assert names == sorted(i.name for i in intent.interfaces)

After the fix, expect roughly 23 CODEC_BUG cells transitioning to
ALIGNED: aruba_aoss → opnsense (8), arista_eos → opnsense (5),
cisco_iosxe_cli → opnsense (5), fortigate_cli → opnsense (~5 of
the 10 interface-count cells), with smaller wins elsewhere.
```

---

## Draft 4 — Add Junos L2 / LAG / SVI render paths

**Title:** `Add Junos L2 ethernet-switching, ae<N>, and irb render`

**Tldr:** The Junos render is L3-only — no `family
ethernet-switching` for switchport state, no `ae<N>` for LAGs, no
synthetic `irb.<vid>` SVI for VLAN L3 addresses.  Adding the three
emit paths clears about 22 cells across multiple source vendors.

**Prompt:**

```
You are wiring up the L2 surface of the Junos render path.  Read
`tests/fixtures/real/phase4_findings_arista_eos.md` (JU-4 LAG +
contributions to JU-1 count cascade),
`tests/fixtures/real/phase4_findings_aruba_aoss.md` (J1 L2 / J2
SVI / J3 LAG, 17 cells), and
`tests/fixtures/real/phase4_findings_cisco_iosxe_cli.md` (Patterns A
and B, ~22 cells).  Top-level synthesis is in
`tests/fixtures/real/PHASE4_RECONCILIATION.md` (rank 4 of the
top-6).

Fix locus: `netconfig/migration/codecs/juniper_junos/render.py` —
three additions:

1. **`family ethernet-switching` per-iface block.**  For each
   `CanonicalInterface` carrying `switchport_mode`, `access_vlan`,
   or `trunk_allowed_vlans`, emit:

       set interfaces <name> unit 0 family ethernet-switching interface-mode <access|trunk>
       set interfaces <name> unit 0 family ethernet-switching vlan members <vlan-name>  # repeated for trunks
       set interfaces <name> native-vlan-id <native>  # if trunk_native_vlan

   Use a `vlan_name_by_id` lookup over `tree.vlans`; Junos
   references VLANs by name, not VID.  Mirror
   `arista_eos/render.py:159-171` for the per-iface logic and call
   `project_vlan_to_switchport(tree)` at the top of `render_intent`
   if the source codec didn't already populate the per-iface
   fields (see the cross-cutting projection-call gap noted in
   PHASE4_RECONCILIATION.md).

2. **`ae<N>` aggregated-ether-options for LAGs.**  For each
   `CanonicalLAG` in `tree.lags`, emit:

       set chassis aggregated-devices ethernet device-count <max-ae+1>  # once
       set interfaces ae<N> aggregated-ether-options lacp <active|passive>
       set interfaces <member> ether-options 802.3ad ae<N>  # per member

   Map `Port-Channel<N>` / `trk<N>` / `Port-channel<N>` canonical
   LAG names to `ae<N>` by stripping leading non-digits and reusing
   the trailing integer (fall back to enumeration if no digits).
   Verify the existing Junos parser at
   `juniper_junos/parse.py` already handles `aggregated-ether-options
   lacp` and `ether-options 802.3ad ae<N>`; if not, the parse side
   needs symmetric work.

3. **`irb.<vid>` SVI L3 emit.**  When a `CanonicalVlan` has a
   non-empty `ipv4_addresses` list, emit:

       set interfaces irb unit <vlan.id> family inet address <ip>/<prefix>  # per address
       set interfaces irb unit <vlan.id> vlan-id <vlan.id>
       set vlans <vlan-name> l3-interface irb.<vlan.id>

Companion concerns documented in the per-vendor markdowns:

* **MAC-VRF binding gap** (juniper_junos findings Finding 6, arista
  source) is independent — Junos `instance-type mac-vrf` emits a
  routing-instance the Arista renderer can't resolve back to a vlan
  binding.  Out of scope for this draft.
* **Routing-instance `.0` suffix** (rank 5 fix) is being addressed
  by Draft 5; if both fixes ship in the same branch, ensure the
  test run picks up the combined improvement.

Test that should pass after fix:

    # tests/integration/migration/test_juniper_junos_codec.py
    def test_l2_switchports_round_trip_to_junos():
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=10, name="USERS",
                                 ipv4_addresses=[CanonicalIPv4Address(...)])],
            interfaces=[CanonicalInterface(
                name="ge-0/0/1",
                switchport_mode="access",
                access_vlan=10,
            )],
        )
        out = render_intent(intent)
        assert "family ethernet-switching" in out
        assert "interface-mode access" in out
        assert "vlan members USERS" in out
        # SVI L3:
        assert "interfaces irb unit 10 family inet address" in out
        assert "vlans USERS l3-interface irb.10" in out

    def test_lag_round_trip_to_junos():
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/1", lag_member_of="Port-Channel10"),
                CanonicalInterface(name="ge-0/0/2", lag_member_of="Port-Channel10"),
            ],
            lags=[CanonicalLAG(name="Port-Channel10",
                               members=["ge-0/0/1","ge-0/0/2"], mode="active")],
        )
        out = render_intent(intent)
        assert "set interfaces ae10 aggregated-ether-options lacp active" in out
        assert "set interfaces ge-0/0/1 ether-options 802.3ad ae10" in out
        # Round-trip:
        roundtrip = parse_intent(out)
        assert len(roundtrip.lags) == 1
        assert roundtrip.lags[0].name == "Port-Channel10"

After the fix, expect roughly 22 CODEC_BUG cells transitioning to
ALIGNED across cisco_iosxe_cli → juniper_junos (~22),
aruba_aoss → juniper_junos (~15), and arista_eos → juniper_junos (~5
of the LAG-related cells; the rest are parse-side suffix issues
addressed by Draft 5).
```

---

## Draft 5 — Strip `.0` suffix in Junos parse routing-instance lookup

**Title:** `Strip .0 suffix in Junos routing-instance iface lookup`

**Tldr:** The Junos render appends `.0` to interface names inside
routing-instance bindings, but the parser's `iface_by_name` lookup
doesn't strip the suffix before falling back to stub-creation —
every iface bound into a VRF spawns a duplicate stub, exploding
interface counts.  Two-line parse fix clears 18 cells.

**Prompt:**

```
You are fixing a small but high-leverage parse-side asymmetry in the
Junos codec.  Read
`tests/fixtures/real/phase4_findings_arista_eos.md` (Bug JU-1,
documented as cross-cutting CC-1; collapses 18 of 27 Junos
findings) before editing.  Top-level synthesis is in
`tests/fixtures/real/PHASE4_RECONCILIATION.md` (rank 5 of the
top-6).

Fix locus: `netconfig/migration/codecs/juniper_junos/parse.py`
lines 319-332 — the routing-instance binding handler that calls
`iface_by_name.get(iface_name)`.  The render side at
`juniper_junos/render.py:397-405` always appends `.0` to the iface
name (Junos routing-instances reference UNITs, and the canonical
stores the parent name without a unit suffix), so reparse sees
`Loopback0.0` and can't find a matching iface in `iface_by_name`
(which only has `Loopback0`).  The current code falls through to
stub-creation, materialising a duplicate `CanonicalInterface(name=
"Loopback0.0", vrf=...)`.

Recommended fix (option (2) in the arista markdown — preserves
Junos-faithful render output):

    iface = iface_by_name.get(iface_name)
    if iface is None and iface_name.endswith(".0"):
        iface = iface_by_name.get(iface_name[:-2])
    if iface is None:
        # ... existing stub creation path ...

This way the renderer continues to emit `Loopback0.0` (which is
correct Junos syntax) and the parser successfully resolves it back
to the parent `Loopback0`.

Test that should pass after fix:

    # tests/unit/migration/codecs/test_juniper_junos_parse.py
    def test_routing_instance_dot_zero_iface_resolves():
        cfg = (
            "set interfaces Loopback0 unit 0 family inet address 1.1.1.1/32\n"
            "set routing-instances TENANT_A interface Loopback0.0\n"
            "set routing-instances TENANT_A instance-type vrf\n"
        )
        intent = parse_intent(cfg)
        # Single interface, not a duplicate.
        assert len(intent.interfaces) == 1
        assert intent.interfaces[0].name == "Loopback0"
        assert intent.interfaces[0].vrf == "TENANT_A"

After the fix, expect roughly 18 CODEC_BUG cells transitioning to
ALIGNED on the arista_eos → juniper_junos cell alone (every
`interfaces[].<subfield>` count drift on the
`batfish_labval_dc1_leaf2a_eos4230.txt` and `kitchen_sink.txt`
fixtures collapses onto this single fix), with smaller wins on
cisco_iosxe_cli → juniper_junos.

Do not change the render side — Junos's `.0` syntax is correct
operator output and changing it would surprise reviewers reading
the migrated config.
```

---

## Draft 6 — Add cisco_iosxe_cli top-level resolver / NTP / VRF parsers

**Title:** `Add cisco_iosxe_cli top-level resolver / NTP / VRF parsers`

**Tldr:** The cisco_iosxe_cli renderer correctly emits `ip
name-server`, `ip domain name`, `ntp server`, and `vrf definition`
blocks, but the parser only handles indented forms inside `ip dhcp
pool` stanzas.  Round-trip drops `intent.dns_servers`,
`intent.domain`, `intent.ntp_servers`, and `intent.routing_instances`
to empty.  About 12 cells cleared.

**Prompt:**

```
You are wiring up the missing top-level parsers in the cisco_iosxe_cli
codec.  The renderer is correct; the parser has gaps.  Read
`tests/fixtures/real/phase4_findings_arista_eos.md` (Bugs CI-1, CI-2,
CI-3 — 8 cells), `tests/fixtures/real/phase4_findings_juniper_junos.md`
(Finding 5 — 4 cells), `tests/fixtures/real/phase4_findings_opnsense.md`
(B2 — 5 cells), `tests/fixtures/real/phase4_findings_aruba_aoss.md`
(C1 — 3 cells), `tests/fixtures/real/phase4_findings_fortigate_cli.md`
(A — 4 cells), and `tests/fixtures/real/phase4_findings_mikrotik_routeros.md`
(B — 2 cells) for the cell-by-cell attribution.  Top-level
synthesis is in `tests/fixtures/real/PHASE4_RECONCILIATION.md`
(rank 6 of the top-6).

Fix locus: `netconfig/migration/codecs/cisco_iosxe_cli/parse.py`,
specifically the top-level scope around lines 219-249 where
`_extract_hostname` and `_parse_static_routes` already live.

Three additions:

1. **`ip name-server`** — currently only handled inside DHCP pools
   (lines 760-768).  Add a top-level regex matching
   `^ip\s+name-server\s+(?:vrf\s+\S+\s+)?(.+)$` (multi-line);
   Cisco accepts multiple servers space-separated on one line, so
   split on whitespace and extend `intent.dns_servers`.  Mirror
   `arista_eos/parse.py:54-60` (same vendor family, same wire
   syntax, prior art).

2. **`ip domain name`** — match `^ip\s+domain\s+name\s+(\S+)$`,
   assign to `intent.domain`.  Also accept the legacy `ip
   domain-name` (hyphen) form for parity with how Cisco IOS
   historically wrote it.

3. **`ntp server`** — match `^ntp\s+server\s+(?:vrf\s+\S+\s+)?(\S+)`,
   append to `intent.ntp_servers`.  Same arista_eos prior art.

4. **`vrf definition`** (separate, larger addition).  Currently no
   parser awareness of `vrf definition <name>` block — the renderer
   emits a full `vrf definition / description / rd / route-target /
   address-family / exit-address-family` block (render.py:140-155)
   and reparse drops it entirely.  Add a `_parse_routing_instances(raw)
   -> list[CanonicalRoutingInstance]` helper modelled on the
   existing block-walker pattern (`_parse_dhcp_pools` /
   `_parse_radius_servers`).  Anchor on `^vrf definition (\S+)`,
   absorb the indented sub-stanza, build a
   `CanonicalRoutingInstance` per block.  Per-interface
   `vrf forwarding <name>` is already emitted by render but the
   matching parse-side line in `_parse_interfaces` may not set
   `iface.vrf` — audit both halves.

Recommend factoring (1)-(3) into a single `_parse_globals(raw,
intent)` helper and (4) into its own helper, both called from
`parse_intent` after `_extract_hostname`.

Test that should pass after fix:

    # tests/unit/migration/codecs/test_cisco_iosxe_cli_parse.py
    def test_top_level_resolver_and_ntp_parse():
        cfg = (
            "hostname r1\n"
            "ip domain name example.com\n"
            "ip name-server 1.1.1.1\n"
            "ip name-server 8.8.8.8 9.9.9.9\n"
            "ntp server 10.0.0.1\n"
            "ntp server 10.0.0.2\n"
        )
        intent = parse_intent(cfg)
        assert intent.domain == "example.com"
        assert intent.dns_servers == ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
        assert intent.ntp_servers == ["10.0.0.1", "10.0.0.2"]

    def test_vrf_definition_parses():
        cfg = (
            "vrf definition TENANT_A\n"
            " description tenant a\n"
            " rd 65000:1\n"
            " route-target both 65000:1\n"
            " address-family ipv4\n"
            " exit-address-family\n"
        )
        intent = parse_intent(cfg)
        assert len(intent.routing_instances) == 1
        ri = intent.routing_instances[0]
        assert ri.name == "TENANT_A"
        assert ri.route_distinguisher == "65000:1"

After the fix, expect roughly 12 CODEC_BUG cells transitioning to
ALIGNED across every source vendor whose target is cisco_iosxe_cli
and whose source carries top-level resolver / NTP / VRF data.

The render side already works — do not modify any render path.  Do
not modify the per-vendor findings markdowns.
```

---

## See also

* [`PHASE4_RECONCILIATION.md`](PHASE4_RECONCILIATION.md) — top-level
  reconciliation narrative this file backs
* `tests/fixtures/real/phase4_findings_*.md` — per-source-vendor
  bug-by-bug attribution, the source of truth for "estimated bugs
  cleared" claims in each draft above
* `tools/run_phase4_reconciliation.py` — re-running this script
  after each fix lands shows the residual CODEC_BUG count
