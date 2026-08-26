# IOS-XE (OpenConfig XML) → IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, with
every per-key disposition resolved through the audit's own
`actual_disposition()` rather than inferred from the drift shape — so this file
and the ratchet agree by construction. Every drifting key was then
**re-derived by hand** with the round-trip in [Reproduction](#reproduction).

- Fixture cells: **1**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below comes from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and a hand-run parse → render → re-parse
> of the one fixture cell. Where a disposition rests on a *declaration* rather
> than an observed round-trip, the YAML says so in the entry itself.

## Read the cell count first

This pair has **one** cell, and that matters more than usual.

`cisco_iosxe` is not the `show running-config` codec — that is its
`cisco_iosxe_cli` sibling. `cisco_iosxe` is the **NETCONF / OpenConfig XML**
codec, and it is an explicit Phase-0.5 stub that parses only the
`/openconfig-interfaces/` subtree. Consequently:

- `tests/fixtures/real/cisco_iosxe/` maps to `cisco_iosxe_cli`, not to this
  codec (`netcanon/migration/fixture_dirs.py::DIR_TO_CODEC_NAME`), so this
  codec has **no real captures at all**;
- its only fixture is the synthetic kitchen sink
  `tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml`.

Only **three** of the twenty-one audited top-level fields carry any observation
at all — `hostname`, `interfaces` and `vlans`. The remaining **eighteen** are
*trivially empty on the source side*: not "preserved", not "lost", simply never
populated. Their YAML keys are decided by the two capability matrices, and each
such entry says in its own text that it rests on a declaration rather than on a
round-trip.

## Device-class framing

`cisco_iosxe` here is a **branch / campus-edge router** described through
OpenConfig — the kitchen sink carries a WAN uplink, a LAN downlink, a routed
port with a dot1q trunk, two loopbacks, a GRE tunnel, an SVI and a
port-channel. `cisco_iosxr` is a **service-provider edge/core router**:
4-segment port names (rack/slot/instance/port), VRFs with the RD derived from
`router bgp`, and *no campus L2 model whatsoever* — IOS-XR expresses a VLAN
only as `encapsulation dot1q <id>` on a sub-interface.

The pair is asymmetric in exactly the way that framing predicts: the routed L3
surface migrates cleanly and the campus L2 surface does not survive at all.

## The three measured drifts

Only three of the twenty-one audited fields drift on the one cell. Each was
reproduced by hand.

### 1. `hostname` — a *synthesised* value, not a lost one

The source intent's hostname is the empty string: the `cisco_iosxe` matrix
declares both `/system/hostname` and the blunt whole-field `/hostname`
unsupported, and the OpenConfig stub never parses one.

The IOS-XR renderer then substitutes a literal default —
`netcanon/migration/codecs/cisco_iosxr/render.py:93` is
`hostname = tree.hostname or "Router"` — and the re-parse reads back
`'Router'`.

So the drift direction is `'' → 'Router'`: the target **gains** a value the
source never carried. Recorded `lossy` rather than `unsupported` because
nothing vanished (#436: a vanished record is not lossy, and the converse holds
too — `lossy` warns and stays compatible, which is the right severity for a
default that silently fills a blank). Operationally it is worth a warning of
its own: migrate several IOS-XE devices through this pair and every one of them
arrives named `Router`.

### 2. `interfaces[].interface_type` — 3 of 10 records fall back to `other`

The interface **inventory is intact** — 10 records in, 10 records out, every
name verbatim. What degrades is the type discriminator, on exactly the records
whose IOS-XE name prefix has no IOS-XR equivalent:

| interface | source type | after round-trip |
|---|---|---|
| `Port-channel1` | `ianaift:ieee8023adLag` | `ianaift:other` |
| `Tunnel100` | `ianaift:tunnel` | `ianaift:other` |
| `Vlan10` | `ianaift:l2vlan` | `ianaift:other` |

The other seven (`GigabitEthernet0/0/0`–`0/0/4`, `Loopback0`, `Loopback1`)
keep their type.

The mechanism is declared, not accidental: `cisco_iosxr` lists
`/interfaces/interface/config/type` **lossy** precisely because its parser
re-infers the type from the name prefix.
`netcanon/migration/codecs/cisco_iosxr/parse.py::_TYPE_HINTS` recognises
`bundle-ether`, `loopback`, `mgmteth`, `tunnel-ip`, `tunnel-te` and the
`*gige`/`*ethernet` family; `_infer_type()` returns `ianaift:other` for
anything else. IOS-XE spells those same three concepts `Port-channel`,
`Tunnel` and `Vlan`, none of which is an IOS-XR prefix.

> The evidence dossier reports this as "drifts on 3 cell(s)" against a
> one-cell pair. The hand round-trip locates it precisely: **3 of 10 interface
> records on the single cell**. Use the record count, not the dossier's label.

### 3. `vlans` — a total drop, and the reason is structural

The source parse yields one `CanonicalVLAN` (`id=10`, `name='User VLAN 10 SVI'`,
`10.10.10.1/24`), synthesised from the `Vlan10` SVI interface. The re-parse
yields **zero**. The rendered IOS-XR config contains no `encapsulation dot1q`
line and no VLAN stanza of any kind.

That is not a renderer oversight in isolation — it is the device-class gap. A
control probe on `tests/fixtures/synthetic/cisco_iosxr/kitchen_sink.cfg`
confirms `cisco_iosxr` *does* round-trip a VLAN cleanly (1 → 1) when it arrives
as a sub-interface carrying `encapsulation dot1q 100`. IOS-XR has that one
carrier and no other. A VLAN record that arrives as an SVI, with no dot1q-tagged
sub-interface and no member ports, has nowhere to land.

Recorded `unsupported` on `vlans[].id`, not `lossy`: the record vanishes
entirely, and per #436 `lossy` (warn + `compatible=True`) would understate a
total drop that should block.

**Do not read the VLAN drop as losing the SVI's addressing.** `10.10.10.1/24`
and `2001:db8:10::1/64` both survive — on the `Vlan10` *interface* record,
which round-trips intact. What is lost is the VLAN *record*: its ID, its name,
and the L2 identity. This is why the five sibling `vlans[].*` keys are `good`
and not lossy (see below).

## Why five `vlans[].*` keys are `good` despite measuring as drifted

`vlans[].name`, `vlans[].ipv4_addresses`, `vlans[].untagged_ports`,
`vlans[].tagged_ports` and `vlans[].description` each show drift on this cell.
All of it is one signal: the parent list going 1 → 0. The reconciler's
STRUCTURAL_ONLY collapse assigns that record-level loss to the **first**
sibling, `vlans[].id`, which claims it as `unsupported`.

A loss declared on any of the other five could **never** be evidenced by any
cell, because there is no residual per-record signal left for it to point at —
it would fail the per-pair ratchet by construction. These keys ask a different
question: *when a VLAN record survives, does this value survive with it?* On
this pair no VLAN record survives at all, so the answer is vacuous rather than
negative, and the honest disposition is `good` with the vacuity stated.

This is a rule the project learned the expensive way: on the previous wave six
declarations were written as losses on exactly this shape, all six failed the
gate, and all six were correct as `good`.

Correlated drift is not independent evidence. None of these five corroborates
any other, and none corroborates `vlans[].id`.

## Per-field measurement (1 cell)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 0 | 1 | 0 |
| interfaces (record inventory) | 1 | 0 | 0 |
| interfaces[].name / description / enabled | 1 | 0 | 0 |
| interfaces[].ipv4_addresses / ipv6_addresses | 1 | 0 | 0 |
| interfaces[].interface_type | 0 | 1 | 0 |
| vlans (all sub-fields) | 0 | 1 | 0 |
| everything else | 0 | 0 | 1 |

Trivially empty on the source side: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `interfaces[].mtu`,
`interfaces[].lag_member_of`, `interfaces[].vrrp_groups`, `static_routes`,
`dhcp_servers`, all five `snmp.*`, `lags`, all three `local_users[].*`,
`radius_servers`, all three `vxlan_vnis[].*`, `evpn_type5_routes`, both
`routing_instances[].*`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

Interface detail preserved verbatim across the round-trip: 10 of 10 names,
10 of 10 descriptions (including the deliberately empty one on
`GigabitEthernet0/0/4`), 10 of 10 admin states (`GigabitEthernet0/0/2`'s
`enabled=False` survives as `shutdown` and re-parses `False`), 10 IPv4
addresses across 7 records — multi-address ports included, `GigabitEthernet0/0/1`
carries three — and 5 IPv6 addresses across 4 records, all with
`scope='global'` intact on both sides.

## Source-side gaps vs symmetric gaps

The distinction drives whether the YAML says `not_applicable` or
`unsupported`, and it is operational: it tells a reader whether re-authoring on
the target is worth doing.

**Source-side gap → `not_applicable`, and the target WILL hold it if you
re-author.** `cisco_iosxe` declares these unsupported (or, for MTU, lossy)
while `cisco_iosxr` declares them supported:

| canonical field | source declares | target declares |
|---|---|---|
| `dns_servers` | `/system/dns-server` unsupported | `/system/dns-server` supported |
| `ntp_servers` | `/system/ntp-server` unsupported | `/system/ntp-server` supported |
| `syslog_servers` | `/system/syslog-server` unsupported | `/system/syslog-server` supported |
| `interfaces[].mtu` | `/interfaces/interface/config/mtu` **lossy** | `/interfaces/interface/config/mtu` supported |
| `interfaces[].lag_member_of` | `/lags` unsupported (whole-field) | `/lags/lag/members` supported |
| `static_routes` | `/routing/static-route` unsupported | `/routing/static-route` + `/vrf` supported |
| `lags` | `/lags` unsupported (whole-field) | `/lags/lag/{name,members,mode}` supported |
| `local_users[].{name,role,hashed_password}` | `/local_users` unsupported (whole-field) | `/local-users/user/{name,role,hashed-password}` supported |
| `routing_instances[].{name,description}` | `/routing-instances/instance` unsupported | `/routing-instances/instance` **lossy** |

The MTU row is worth reading twice. The source declares MTU *lossy*, not
unsupported — "parsed into the intermediate dict but not carried through to
`CanonicalInterface`". The effect is identical to a gap: the kitchen sink sets
`<mtu>1500</mtu>` on `GigabitEthernet0/0/0` and the parsed intent shows
`mtu=None` on all ten records. Nothing reaches the target to be lost.

The routing-instances row is the one where re-authoring is most worth the
effort *and* most worth checking afterwards: IOS-XR is the heavy-VRF codec of
the mesh, but it declares `/routing-instances/instance` **lossy**, not
supported — `vrf <name>` and per-interface membership round-trip while the
route-distinguisher does not.

**Source-side gap with no target declaration → `not_applicable`, but
re-authoring will NOT round-trip either.** `domain` (`/system/domain`
unsupported on the source, undeclared on the target) and
`snmp.{location,contact,trap_hosts}` (declared unsupported on the source,
undeclared on the target). The target's own reason for `/snmp/community` reads
"SNMP parse + render is out of the v1 XR scope", so the absence of a
declaration for location/contact/trap-host is a matrix gap, not latent
capability. The YAML says this plainly rather than implying the target can hold
them.

**Symmetric gap → `unsupported`.** Both matrices declare these unsupported at
the same path, so neither side of the pair can carry the concept:

`/system/timezone` · `/dhcp-servers/pool` · `/radius-servers/server/{host,key}` ·
`/snmp/community` · `/snmp/v3-user/{auth-protocol,priv-protocol,priv-passphrase,group}` ·
`/vxlan-vnis/{vni,source-interface,udp-port}` · `/evpn-type5-routes/route` ·
`/anycast-gateway-mac` · the whole
`/interfaces/interface/vrrp-groups/group/*` subtree (8 paths on each side)

`vxlan_vnis[].vlan_id` and `vxlan_vnis[].mcast_group` have no declared path of
their own on either side. They are recorded `unsupported` because their
identity leaf `/vxlan-vnis/vni` is symmetrically unsupported: no VNI record can
exist on either side of this pair, so the sub-fields have no carrier at all.

## Credential material

Nothing to redact on this pair. The `cisco_iosxe` matrix declares the
whole-field `/local_users` unsupported and the parsed intent carries
`local_users == []`, so no password hash, no vendor ciphertext blob and no
SNMPv3 passphrase ever enters the canonical intent from this source. The
hash-format question that dominates most pairs in this mesh simply does not
arise here — which is a property of the stub source, not evidence that IOS-XR
handles credentials well.

## One caveat the fidelity harness cannot see

The harness scores **preservation**, not target-syntax **validity** (the same
distinction recorded for the demo `run_plan` path). Both are worth knowing
before a cutover, and only the first is measured here.

The IOS-XR render for this cell emits `interface Vlan10`, `interface
Port-channel1` and `interface Tunnel100` — names carried straight over from the
source. Those are not IOS-XR spellings. The repo's own declarations say so
without needing a vendor manual: `cisco_iosxr`'s `_TYPE_HINTS` table names
`bundle-ether` and `tunnel-ip` / `tunnel-te` as the prefixes it recognises for
LAGs and tunnels, and the target's reason for
`/interfaces/interface/access-vlan` states outright that "IOS-XR has no
per-port access-VLAN; VLANs are dot1q sub-interfaces". Because the names
round-trip verbatim, `interfaces[].name` measures as fully preserved and is
correctly `good` — the canonical data survives. A human still has to rename
those three interfaces before the config will load on a real XR box.

This is stated as an observation from the render below, not filed as a codec
defect; it is the same three interfaces that already drive the
`interfaces[].interface_type` loss, and it is downstream of the same
device-class gap.

## Reproduction

Run from the repo root. Requires no fixture regeneration and writes nothing.

```python
import sys; sys.path.insert(0, ".")          # run from the repo root
from netcanon.migration.codecs import cisco_iosxe, cisco_iosxr  # noqa: F401
from netcanon.migration.codecs.registry import get_codec

src, tgt = get_codec("cisco_iosxe"), get_codec("cisco_iosxr")
a = src.parse(open(
    "tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml", encoding="utf-8").read())
b = tgt.parse(tgt.render(a))

print("hostname  ", repr(a.hostname), "->", repr(b.hostname))
print("interfaces", len(a.interfaces), "->", len(b.interfaces))
print("vlans     ", len(a.vlans), "->", len(b.vlans))
bt = {i.name: i.interface_type for i in b.interfaces}
for i in a.interfaces:
    if bt.get(i.name) != i.interface_type:
        print("  type drift", i.name, i.interface_type, "->", bt.get(i.name))
```

Output:

```
hostname   '' -> 'Router'
interfaces 10 -> 10
vlans      1 -> 0
  type drift Tunnel100 ianaift:tunnel -> ianaift:other
  type drift Vlan10 ianaift:l2vlan -> ianaift:other
  type drift Port-channel1 ianaift:ieee8023adLag -> ianaift:other
```

The VLAN control probe — swap the source for
`tests/fixtures/synthetic/cisco_iosxr/kitchen_sink.cfg` parsed and rendered by
`cisco_iosxr` alone — prints `vlans 1 -> 1`, which is what establishes that the
drop above is the SVI-shaped VLAN having no IOS-XR carrier rather than a broken
VLAN round-trip in the target codec.
