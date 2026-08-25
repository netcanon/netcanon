# AOS-CX → Cisco IOS-XE CLI: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__cisco_iosxe_cli.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every claim about *mechanism* (as opposed to counts) was
re-derived by round-tripping the fixture named beside it —
`cisco_iosxe_cli.parse(cisco_iosxe_cli.render(aruba_aoscx.parse(raw)))` — rather
than reasoned from grammar.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and round-trips run against committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`aruba_aoscx` in this corpus is a **campus access/aggregation** switch;
`cisco_iosxe_cli` is the **IOS-XE `show running-config` text** codec — a
Catalyst-class campus switch or a branch router. This is the most *symmetric*
device-class pairing AOS-CX has in the mesh: both sides model VLANs, SVIs,
access/trunk ports, port-channels, local users, SNMP and static routes at the
same altitude, and the measured result reflects that. Fourteen of 43 keys are
`good`, including every VLAN identity field and both VXLAN binding fields.

## The structural finding

The dominant loss is **not** per-attribute and **not** a shrinking inventory —
it is that the fidelity mesh renders **bare**. `tools/run_full_mesh.py` calls
`target_codec.render(canonical_source)` directly, which does not engage the
cross-vendor port-name bridge
(`netcanon/migration/canonical/port_names.py::translate_port_names`). So the
IOS-XE render carries AOS-CX port names through **verbatim**:

```
interface lag 1          interface vlan 101         interface 1/1/49
interface loopback 0     interface Vlan101   ← synthesized SVI, ip only
```

Those are not IOS-XE interface names. On re-parse the IOS-XE line scanner
truncates each at the first space, so `lag 1` / `lag 2` / `lag 101` all collapse
to one record named `lag`, `loopback 0` and `loopback 1` both become
`loopback`, and `vlan 101` / `vlan 102` / `vlan 4000` all become `vlan`.
Meanwhile `synthesize_svis_from_vlan_l3` adds `Vlan101` / `Vlan102` /
`Vlan4000` records **alongside** the passthrough `vlan 101` stanzas, so the same
SVI is emitted twice under two names — once with description + `shutdown`, once
with only an IP and no shutdown.

Net effect on record count, all 7 cells:

| cell | source ifaces | target ifaces |
|---|---|---|
| aoscx_dcn_arch3_ebgp_leaf1a | 9 | 8 |
| aoscx_dcn_arch3_ibgp_leaf1a | 9 | 8 |
| aoscx_dcn_arch4_core1_1 | 18 | 20 |
| aoscx_dcn_arch4_core1_2 | 42 | 44 |
| canu_csm17_spine001_ipv6_vrf | 22 | 27 |
| netutils_aoscx_snmpv3_glcx1009 | 44 | 49 |
| kitchen_sink (synthetic) | 13 | 14 |

It shrinks on the two leaf cells (the AOS-CX `mgmt` OOB port is never emitted)
and grows on the other five (duplicate SVIs outnumber the collapsed names).
Either way the record sets do not align, the comparator emits **one** drift —
`count drift: N → M (interfaces)` — and **every `interfaces[].*` sub-field is
measured as drifted on all 7 cells for that single reason.**

That is why all nine of them carry a loss in the YAML even though a
name-preserving record keeps its description, admin state, MTU and IPv4 address
intact. Declaring any of them `good` would manufacture a false `CODEC_BUG`.
It is also why none of them corroborates another: they are one observation
counted nine times.

## The control run

The same fixtures were re-rendered with the port-name bridge engaged
(`translate_port_names(intent, aruba_aoscx, cisco_iosxe_cli, {})` before
`render`). Measured, not assumed:

| cell | bare | with bridge |
|---|---|---|
| aoscx_dcn_arch3_ebgp_leaf1a | 9 → 8 | 8 → 8 |
| aoscx_dcn_arch4_core1_1 | 18 → 20 | 17 → 17 |

The bridge rewrites `1/1/49` → `GigabitEthernet1/1/49`, `lag 1` →
`Port-channel1`, `loopback 0` → `Loopback0`, `vlan 101` → `Vlan101` (which then
merges with the synthesized SVI instead of duplicating it). With it engaged,
`aoscx_dcn_arch4_core1_1` round-trips **every** interface attribute — including
`interface_type`, which degrades to `ianaift:other` on the bare path because the
IOS-XE parser infers type from a name prefix that an AOS-CX name does not have.
The only residual interface divergence is the SVI virtual-gateway address (see
below), and the only dropped record is `mgmt`, which the bridge drops with an
explicit warning: *"aruba_aoscx mgmt interface 'mgmt' → target OOBM model
differs; review target mgmt config."*

**This does not change a single disposition.** The ratchet measures the bare
path, so the bare path is what the YAML records. It changes the *advice*: the
port-name mapping is the first thing to fix in a real AOS-CX → IOS-XE cutover,
and it is not a codec-model gap.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces (all sub-fields) | 0 | 7 | 0 |
| vlans[].id | 7 | 0 | 0 |
| vlans[].name | 7 | 0 | 0 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].untagged_ports | 0 | 7 | 0 |
| vlans[].tagged_ports | 1 | 4 | 2 |
| vlans[].description | 0 | 4 | 3 |
| static_routes | 2 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 2 | 2 | 3 |
| lags | 0 | 7 | 0 |
| local_users[].name | 6 | 0 | 1 |
| local_users[].role | 0 | 6 | 1 |
| local_users[].hashed_password | 6 | 0 | 1 |
| vxlan_vnis[].vni / vlan_id | 3 | 0 | 4 |
| routing_instances[].name | 3 | 0 | 4 |
| anycast_gateway_mac | 5 | 0 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`vxlan_vnis[].mcast_group`, `routing_instances[].description`.
`interfaces[].vrrp_groups` is *not* in that list — no cell populates a VRRP
group, but the key still measures as drifted because it rides the shared
interface record drift.

## Source-side gaps vs target-side drops

AOS-CX declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for IOS-XE to lose:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/{host,key}` ·
`/routing-instances/instance/description`

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational — it tells a reader whether re-authoring on the target would help.
It helps for `syslog_servers`: **cisco_iosxe_cli declares `/system/syslog-server`
SUPPORTED**, so `logging host` re-authored on the target will stick. For
`domain`, `dns_servers`, `ntp_servers`, `dhcp_servers` and `radius_servers` the
target codec declares *nothing* at those paths — neither supported nor
unsupported — so this pair has measured nothing about them in either direction
and the YAML says so rather than implying a capability.

`timezone` is different: **both** matrices declare `/system/timezone`
unsupported (the IOS-XE reason reads *"Render emits no clock/timezone stanza;
intent.timezone is dropped on migration"*), a symmetric gap. That one is
`unsupported`.

## Four findings worth carrying forward

**1. `lags` is `lossy` here, and that is the opposite of the EOS pair.** On 6 of
7 cells the only divergence is the name form — `lag 1` → `Port-channel1` —
with membership intact. Round-tripping `aoscx_dcn_arch4_core1_1` returns all
five port-channels with byte-identical member lists (`Port-channel256` keeps
`1/1/31` + `1/1/32`), and every member port keeps its `lag_member_of` binding
under the renamed LAG. The 7th cell (`kitchen_sink`) loses one record, 2 → 1:
`lag 2` has **no members**, renderers materialise port-channels from
`CanonicalInterface.lag_member_of`, and its passthrough stanza `interface lag 2`
is not recognisable as a port-channel on re-parse. With the port-name bridge
engaged that cell round-trips both LAGs. Nothing here is a vanished surface, so
`lossy` (warns, stays compatible) is the honest severity — where AOS-CX → EOS
emitted no `Port-Channel` line at all and earned `unsupported` (#436).

Worth flagging separately: **cisco_iosxe_cli declares NOTHING for `/lags/lag`** —
no supported, lossy or unsupported entry — while its renderer emits
`channel-group` lines and its parser reconstructs `Port-channelN`. That is a
matrix under-declaration, the same shape as the one recorded on the arista_eos
pair, and it belongs in a codec change rather than in a pair expectation file.

**2. `local_users[].hashed_password` is `good`, and `good` here is a hazard.**
The field round-trips byte-for-byte on all 6 populated cells. It survives
because the IOS-XE render emits it under the **type-0 keyword**
(`username <name> privilege 15 secret 0 <blob>`), and type 0 is IOS-XE's
*plaintext* marker. So what round-trips is the string, not a credential: pasted
onto a real Catalyst, that line would set the user's literal password to the
AOS-CX ciphertext. The fidelity harness scores preservation, not target-syntax
validity. Reset every migrated account before cutover.

**3. `anycast_gateway_mac` is `good` but do not read it as "anycast works".**
The chassis-wide MAC round-trips on all 5 populated cells while the per-SVI
active-gateway address does **not**: `vlans[].ipv4_addresses` drifts on all 5
cells that populate it, always the same way — `virtual_gateway_address` goes
from an address to empty while `ip` and `prefix_length` survive. The target
declares this: `/vlans/vlan/ipv4/address/virtual-gateway-address` is a declared
`LossyPath` whose reason is *"the synthesized `interface Vlan<N>` carries only
ip+prefix_length"*. The render is honest about it in-band — it emits a
`! review:` comment naming the dropped virtual gateway next to the SVI — so
grep the rendered config for `! review:` before cutover, and re-author HSRP,
VRRP or `fabric forwarding mode anycast-gateway` on the target SVIs. This is the
field most likely to break first-hop reachability.

**4. The SNMPv3 divergence runs the *other* way.** On the 2 cells that carry a
v3 user, name, auth protocol, priv protocol and both passphrase fields
round-trip; what changes is that the target **gains** a USM group name
(`v3group`) that the source never carried, because
`snmp-server user <name> <group> v3 …` has no groupless form. It is drift, so
the key is `lossy` — but nothing was lost. Treat the group as a placeholder and
set the real USM group and views on the target. AOS-CX separately declares six
`/snmp/v3-user/*` child paths lossy, so v3 credential material should be
re-created rather than trusted regardless.

## Credential material

Two credential-bearing surfaces appear on this pair, and neither value is
reproduced here or in the expectation YAML.

- **Local-user secrets.** AOS-CX stores them in its own encrypted form — an
  `AQB…`-prefixed ciphertext blob. It is neither a crypt(3) hash (`$1$` /
  `$5$` / `$6$` / `$9$` / `$2y$`) nor anything IOS-XE can validate. Per
  `AGENTS.md`, encrypted secrets are operator-traceable even when encrypted,
  and a document that quotes the value it describes defeats its own redaction.
  Only the *shape* is stated above.
- **SNMP community and v3 passphrases.** Re-emitted verbatim into
  `snmp-server community <community> RO` and the v3 user line. The committed
  fixtures carry sanitized placeholders; the mechanism is what matters, and the
  values are not quoted.
