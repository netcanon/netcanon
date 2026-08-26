# Junos → IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/juniper_junos__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every loss recorded below was additionally re-derived by hand
— `juniper_junos.parse()` → `cisco_iosxr.render()` → `cisco_iosxr.parse()` on
each of the 11 fixtures — so no claim here rests on the drift shape alone.

- Fixture cells: **11**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

The `juniper_junos` corpus on this pair is **mixed by design**: two batfish SP
routers (an L3VPN PE, an EVPN type-5 router), four ksator lab switches (an EX
access switch, QFX 5100 / 5110 / 10K2 leaves), a vSRX MNHA edge firewall, an
ES.net netlab box, a Junos 23.2 EVPN leaf, and the synthetic kitchen sink.
`cisco_iosxr` is a **service-provider edge/core router**: 4-segment interface
names, `Bundle-Ether` LAGs, VRFs whose route-distinguisher is harvested from
`router bgp`, and **no campus L2 model at all**.

So the pair splits cleanly in two:

- the **routed edge and SP surface** — interface identity, addressing, MTU,
  admin state, VRFs, static routes, local users, DNS/NTP/syslog — migrates
  well;
- the **campus L2 and management-services surface** — the VLAN database, SNMP,
  VXLAN, DHCP pools, and Junos' own `groups` / `apply-groups` machinery —
  does not arrive at all.

## The structural finding — and it is the *opposite* of the AOS-CX pair

Anyone arriving here from `aruba_aoscx_to_arista_eos/canonical_surface.md`
should read this before assuming the same shape. There, the interface
inventory shrank 9 → 5, which dragged every `interfaces[].*` sub-field into
`lossy` whether or not the attribute was at fault.

**Here the interface inventory is fully preserved.**

| measurement | value |
|---|---|
| source interface records, all 11 cells | **151** |
| records after parse → render → re-parse | **151** |
| cells where the interface name set differs | **0** |

Junos-native names survive the IOS-XR render verbatim — `ge-0/0/0`,
`et-0/0/48`, `xe-0/0/35`, `ae0`, `irb.100`, `ge-0/0/1.100`, `lo0`, `fxp0`,
`em0`. The render emits `interface ge-0/0/0`, not a translated
`GigabitEthernet0/0/0/0`.

The consequence is the useful one: **every interface loss on this pair is a
genuine per-attribute loss** standing on its own measurement, and every
interface sub-field that survives is recorded `good` rather than being dragged
down by a vanishing parent. Nothing in the interface block is correlated
drift.

Reproduce: `juniper_junos.parse()` → `cisco_iosxr.render()` →
`cisco_iosxr.parse()` over the 11 fixtures, comparing `{i.name for i in
intent.interfaces}` on both sides.

## What *does* vanish wholesale

The structural loss on this pair is not in the interfaces — it is in five
whole canonical surfaces that arrive empty.

| surface | measured | recorded |
|---|---|---|
| `vlans` | 126 source records → 6 re-parsed; **1** of 126 source VLAN ids present after round-trip | `vlans[].id` lossy |
| `snmp` | populated on 6 cells, `None` after round-trip on **6 of 6** | `snmp.*` unsupported |
| `vxlan_vnis` | populated on 3 cells, empty after round-trip on **3 of 3** | `vxlan_vnis[].vni` unsupported |
| `dhcp_servers` | populated on 2 cells, empty after round-trip on **2 of 2** | `dhcp_servers` unsupported |
| `apply_groups` / `group_content` | populated on 6 cells, empty after round-trip on **6 of 6** | both unsupported |

### The VLAN number needs its caveat stated, not implied

126 → 6 is not "6 VLANs survived". The IOS-XR render emits **no VLAN stanza of
any kind** (`grep '^vlan' <render>` returns nothing on all 11 cells). The six
records that re-appear are *synthesised on re-parse* from `encapsulation dot1q
N` on routed sub-interfaces — a different concept wearing the same canonical
field. On `ksator_labmgmt_qfx10k2_junos173` the source carries VLANs
2021–2025 + 2031 and the re-parse yields 10 / 30 / 100: no overlap at all. On
`kitchen_sink` the source carries 10 / 20 / 100 / 200 and the re-parse yields
a single id 100 — recovered from `ge-0/0/1.100`'s dot1q tag, with the VLAN's
name, tagged ports and description gone.

That single coincidental id is the only reason this is recorded `lossy` rather
than `unsupported`: the target codec does declare `/vlans/vlan/id` and
`/vlans/vlan/name` supported (through the sub-interface path), and the drop is
not literally total. **Operationally, treat it as total.** A Junos campus
switch's VLAN database does not migrate to IOS-XR.

### SNMP is the one place the drift heuristic and the matrix disagreed

The mechanical vanish-classifier reads the `snmp` drift string as a partial
degradation and suggests `lossy`; the target `CapabilityMatrix` declares
`/snmp/community` plus four `/snmp/v3-user/*` paths **unsupported** with the
reason "SNMP parse + render is out of the v1 XR scope". The matrix is right,
and it was checked rather than trusted: on all six cells that populate SNMP,
the render contains no line beginning `snmp` and the re-parsed intent has
`snmp is None`. All five `snmp.*` keys are therefore `unsupported`, not
`lossy` — a vanished record is not lossy (#436), and `lossy`'s
`compatible=True` would understate a surface that is simply absent.

## Per-field measurement (11 cells)

Counts are cells, resolved per YAML key through `actual_disposition()`.

| key | preserved | drifted | trivially empty |
|---|---|---|---|
| `hostname` | 10 | 1 | 0 |
| `domain` | 2 | 0 | 9 |
| `dns_servers` / `ntp_servers` / `syslog_servers` | 6 | 0 | 5 |
| `interfaces[].name` / `.enabled` | 11 | 0 | 0 |
| `interfaces[].description` | 9 | 0 | 2 |
| `interfaces[].mtu` | 5 | 0 | 6 |
| `interfaces[].ipv4_addresses` | 8 | 2 | 1 |
| `interfaces[].ipv6_addresses` | 5 | 1 | 5 |
| `interfaces[].interface_type` | 0 | 11 | 0 |
| `interfaces[].lag_member_of` | 0 | 5 | 6 |
| `vlans[].*` | 0 | 8 | 3 |
| `static_routes` | 9 | 0 | 2 |
| `dhcp_servers` | 0 | 2 | 9 |
| `snmp.community` | 1 | 5 | 5 |
| `snmp.location` / `snmp.v3_users` | 4 | 2 | 5 |
| `snmp.contact` / `snmp.trap_hosts` | 5 | 1 | 5 |
| `lags` | 0 | 5 | 6 |
| `local_users[].name` / `.role` / `.hashed_password` | 8 | 0 | 3 |
| `vxlan_vnis[].*` | 0 | 3 | 8 |
| `routing_instances[].name` | 6 | 0 | 5 |
| `routing_instances[].description` | 2 | 0 | 9 |
| `apply_groups` / `group_content` | 0 | 6 | 5 |

Trivially empty on all 11 cells: `timezone`, `interfaces[].vrrp_groups`,
`radius_servers`, `evpn_type5_routes`, `raw_sections`,
`anycast_gateway_mac`. Verified directly — every one of the 11 parsed source
intents has zero records / an empty string for each.

## Source-side gaps, symmetric gaps and target-side drops

The three cases are recorded differently because they mean different things to
whoever runs the cutover.

**Symmetric gaps — `unsupported`.** Both matrices declare the path
unsupported, so this is a property of the pair, not an IOS-XR limitation:
`/system/timezone`, `/radius-servers/server/host` + `/key`,
`/anycast-gateway-mac`. Nothing carries them and re-authoring on the target
will not help.

**Target-side drops — `unsupported`.** The source models it and IOS-XR
declares it away: the whole `/interfaces/interface/vrrp-groups/group/*`
subtree (eight paths, "out of the v1 IOS-XR scope"),
`/evpn-type5-routes/route`, `/dhcp-servers/pool`, `/snmp/*`,
`/vxlan-vnis/*`. Re-author by hand on the target, or accept the loss.

**Undeclared drops.** `apply_groups` and `group_content` are dropped on all
six cells that populate them and **neither codec declares any path for
either** — not supported, not lossy, not unsupported. The drop is measured,
not declared. That is a target-side matrix under-declaration rather than a
pair-specific fact; it is recorded here and left for a codec change rather
than papered over in the YAML.

**Source-side gap — `not_applicable`.** Only `raw_sections`, which no
committed Junos fixture populates and neither codec declares.

## Findings worth carrying forward

### 1. `lags` is the `Bundle-Ether` rename, not membership loss

The bundle survives completely. Across the five populated cells:

| measurement | value |
|---|---|
| source LAG records | **18** |
| LAG records after round-trip | **18** |
| `ae<N>` → `Bundle-Ether<N>` matches | **18** |
| of those, member list byte-identical | **18** |

`ae1` → `Bundle-Ether1`, `ae101` → `Bundle-Ether101`, members unchanged. This
is the vendor-correct IOS-XR name, and `interfaces[].lag_member_of` drifts on
exactly the same 25 records for exactly the same reason — **one signal, not
two.** Neither may be cited as corroborating the other.

Why it surfaces as drift at all: `_LAG_NAME_RE` in
`tools/run_phase4_reconciliation.py` canonicalises `ae` / `Po` /
`Port-channel` / `Port-Channel` / `trk` / `Trk` / `agg` / `bond` to a stable
`LAG<N>` token so exactly this class of rename collapses to "preserved". It
does **not** know `Bundle-Ether<N>`, so the IOS-XR-native shape falls through
to raw equality. A tooling observation, not a pair fact; left for a tooling
change.

One thing here *is* worth an operator's attention. The render emits the
bundle's L3 configuration under `interface ae0` while the member ports carry
`bundle id 0 mode active`. The re-parse therefore recovers the bundle as
`Bundle-Ether0` **and** keeps a separate `ae0` interface record carrying the
addressing — the same bundle under two names in one config.

### 2. `interfaces[].interface_type` drifts on 100% of records

151 of 151, on every cell. The mechanism is the direct consequence of the
structural finding above: because the render preserves Junos-native interface
names, and the IOS-XR parser infers interface type **from the name prefix**
(`GigabitEthernet` → `ethernetCsmacd`, `Loopback` → `softwareLoopback`,
`Bundle-Ether` → `ieee8023adLag`, `MgmtEth` → `ethernetCsmacd`), a name like
`ge-0/0/0` matches no prefix and re-parses as `ianaift:other`. The target
declares `/interfaces/interface/config/type` lossy for exactly this reason.

Name fidelity and type fidelity are traded against each other on this pair.
The corpus keeps the name.

### 3. `hostname` fails *open*, on one cell

`tsg8139_evpn_leaf_dhcpv6_junos232` parses with an empty hostname, and the
IOS-XR render emits `hostname Router` — a placeholder, not a translation. The
other ten cells preserve the hostname exactly, and both matrices declare
`/system/hostname` supported. This is the whole of the `hostname` loss on this
pair: not a mangled name, a manufactured one. Anything downstream that keys
off hostname will key off `Router`.

### 4. Anycast virtual-gateway addressing is stripped from both families

The addresses themselves survive; the anycast gateway they carry does not.

- IPv4: `virtual_gateway_address` cleared on **10** records
  (`batfish_evpntype5_router1_junos2541` alone accounts for four —
  `irb.100`/`.200`/`.300`/`.400`), `ip` and `prefix_length` intact.
- IPv6: `virtual_gateway_address` **and** `virtual_gateway_mac` cleared on
  **6** records (all on `ksator_labmgmt_qfx10k2_junos173`), `ip` and
  `prefix_length` intact, including the link-local addresses on the same
  interfaces, which have no gateway attribute to lose.

IOS-XR declares both `/interfaces/interface/ipv{4,6}/address/
virtual-gateway-address` unsupported — it has no VARP / anycast-gateway
grammar. This is the field most likely to break first-hop reachability on
cutover: the SVI arrives addressed, without the shared gateway.

### 5. The two keys that carry a whole list's loss

`vlans[].id` and `vxlan_vnis[].vni` are the only members of their lists that
record a loss. Their siblings — `vlans[].name`, `.ipv4_addresses`,
`.untagged_ports`, `.tagged_ports`, `.description`, and
`vxlan_vnis[].vlan_id`, `.mcast_group` — are recorded `good` **not** because
nothing happens to them, but because the mesh records this pair's list-level
loss exactly once and the first key claims it. No per-record sub-field drift
exists for any of them on any cell, so a loss declared on a sibling could
never be evidenced and would fail the per-pair ratchet by construction.

Read those `good`s together with the key that carries the loss. They do not
mean "the VLAN name migrates".

## Credential material

`local_users[].hashed_password` is **preserved on all 8 populated cells** —
verified as string equality between the source intent and the re-parsed
intent, not inferred. So are `local_users[].name` and `.role`.

Two caveats an operator needs, neither of which changes the `good`:

1. The render emits the Junos secret behind IOS-XR's `secret 0` marker. In
   Cisco syntax `0` means *plaintext follows*, so the emitted line's type
   marker does not describe the material it carries. The canonical value
   round-trips exactly; the marker on the rendered line is what is wrong.
2. `local_users[].role` is preserved as a string while the numeric
   `privilege_level` collapses **15 → 1** on 10 records. `privilege_level` is
   not a key in the expectation YAML, so it does not affect any disposition —
   but "role preserved" is not "authority preserved". Check effective
   privilege on every migrated account.

No secret value — Junos-encrypted, crypt-style or otherwise — is reproduced in
this file or in the expectation YAML. Per `AGENTS.md`, secrets are
operator-traceable even when encrypted, and a document that quotes the value
it describes defeats its own redaction.
