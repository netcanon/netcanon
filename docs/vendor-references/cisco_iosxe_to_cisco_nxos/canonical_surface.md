# Cisco IOS-XE (NETCONF/OpenConfig) -> Cisco NX-OS: measured canonical surface

Source of truth for this note is the repository itself, not a vendor page:
`netcanon/migration/codecs/cisco_iosxe/codec.py` and
`netcanon/migration/codecs/cisco_nxos/codec.py` (`CapabilityMatrix`), joined
against a full in-process `tools/run_full_mesh.py` pass over the committed
corpus.

Retrieved: 2026-08-20

## Corpus shape

The pair has exactly **one** fixture cell:
`tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml`. The real captures
under `tests/fixtures/real/cisco_iosxe/` are `show running-config` TEXT and
map to the sibling `cisco_iosxe_cli` codec; the `cisco_iosxe` codec parses
NETCONF/OpenConfig XML, and the kitchen sink is the only committed XML
capture. Every count below is therefore over a single cell, and the
sub-field counts are over the 10 interface records inside it.

**render_status = ok, roundtrip_parse_status = ok** (0 render errors,
0 re-parse errors).

The source codec is a Phase-0.5 stub. Its own fixture header states the
scope plainly: it parses ONLY the `/openconfig-interfaces/` subtree into
`CanonicalIntent`, and `intent.vlans` is then synthesised from `Vlan<N>`
SVI interfaces by `_synthesize_vlans_from_svis`. Every other canonical
family arrives at the NX-OS renderer empty. That is why most rows below
read `trivially empty` rather than `preserved` or `drifted`, and why the
matching YAML dispositions are `not_applicable` (loss upstream of the
codec pair) rather than `unsupported` (target declines to emit declared
data).

## Per-field measurement (1 cell, 21 audited fields)

| field | preserved | drifted | trivially empty | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 0 | 1 | 0 | `''` -> `'switch'` (render fallback) |
| `interfaces` | 0 | 1 | 0 | `interface_type` only |
| `lags` | 0 | 1 | 0 | whole record: 0 source -> 1 target |
| `vlans` | 1 | 0 | 0 | — |
| `domain` | 0 | 0 | 1 | — |
| `dns_servers` | 0 | 0 | 1 | — |
| `ntp_servers` | 0 | 0 | 1 | — |
| `timezone` | 0 | 0 | 1 | — |
| `syslog_servers` | 0 | 0 | 1 | — |
| `static_routes` | 0 | 0 | 1 | — |
| `dhcp_servers` | 0 | 0 | 1 | — |
| `snmp` | 0 | 0 | 1 | — |
| `local_users` | 0 | 0 | 1 | — |
| `radius_servers` | 0 | 0 | 1 | — |
| `vxlan_vnis` | 0 | 0 | 1 | — |
| `evpn_type5_routes` | 0 | 0 | 1 | — |
| `routing_instances` | 0 | 0 | 1 | — |
| `raw_sections` | 0 | 0 | 1 | — |
| `apply_groups` | 0 | 0 | 1 | — |
| `group_content` | 0 | 0 | 1 | — |
| `anycast_gateway_mac` | 0 | 0 | 1 | — |

Three fields drift. Eighteen are untested by the corpus.

## Sub-field drift (authoritative — the aggregate, not one sample)

Only the sub-fields listed here drift. Every other sub-field of the same
parent is preserved on every record, so declaring it `good` is safe;
declaring one of THESE `good` would manufacture a false `CODEC_BUG`.

* **`interfaces[].interface_type`** — drifts on 6 of the 10 interface
  records, in two distinct ways:
  * `GigabitEthernet0/0/0` … `GigabitEthernet0/0/4` (5 records):
    `ianaift:ethernetCsmacd` -> `ianaift:other`. NX-OS infers the IANA
    ifType from the NAME PREFIX (its matrix says so explicitly:
    `Ethernet -> ethernetCsmacd, loopback -> softwareLoopback,
    Vlan -> l3ipvlan, port-channel -> ieee8023adLag, nve -> tunnel,
    mgmt -> …`). `GigabitEthernet` is not a Nexus prefix, so the
    re-parse falls through to `other`.
  * `Vlan10` (1 record): `ianaift:l2vlan` -> `ianaift:l3ipvlan`. A
    semantic reclassification rather than a shed — NX-OS
    `interface Vlan10` is always a routed SVI.
  * Preserved: `Loopback0`, `Loopback1` (`softwareLoopback`),
    `Tunnel100` (`tunnel`), `Port-channel1` (`ieee8023adLag`).
* **`hostname`** — whole record. Source `''`; target `'switch'`.
* **`lags`** — whole record. Source count 0, target count 1:
  `{name: "port-channel1", members: [], mode: "active"}`.

Sub-fields of `interfaces` that carry data on the corpus and are preserved
on every record: `name`, `description`, `enabled`, `ipv4_addresses`,
`ipv6_addresses`, `dhcp_client`. Sub-fields of `vlans` that carry data and
are preserved: `id`, `name`, `ipv4_addresses`.

## Capability matrices (in-repo ground truth)

Both matrices, per audited family. `supported=N` is the count of supported
xpaths; the named paths are the declared `LossyPath` / unsupported entries.

| family | cisco_iosxe (source) | cisco_nxos (target) |
|---|---|---|
| `hostname` | unsupported `/system/hostname` | supported (1) |
| `domain` | unsupported `/system/domain` | supported (1) |
| `dns_servers` | unsupported `/system/dns-server` | supported (1) |
| `ntp_servers` | unsupported `/system/ntp-server` | supported (1) |
| `timezone` | unsupported `/system/timezone` | **unsupported** `/system/timezone` |
| `syslog_servers` | unsupported `/system/syslog-server` | supported (1) |
| `interfaces` | supported (8); lossy `ipv6/address/scope`, `tunnel-type`, `config/mtu`; unsupported switchport / VLAN / VRRP / anycast family | supported (15); lossy VRRP-as-HSRP family, `ipv4/address/virtual-gateway-address`, `tunnel-type`, `config/type`; unsupported `voice-vlan`, `ipv6/address/virtual-gateway-address` |
| `vlans` | unsupported `/vlans/vlan/id`, `/name`, and the L3-on-VLAN family | supported (4); lossy `ipv4/address/ip` + companions, `description` |
| `static_routes` | unsupported `/routing/static-route` family | supported (2); lossy `description` |
| `dhcp_servers` | **unsupported** `/dhcp-servers/pool` | **unsupported** `/dhcp-servers/pool` |
| `snmp` | unsupported whole `/snmp` family | supported (5); lossy `v3-user/auth-passphrase`, `/priv-passphrase`, `/engine-id` |
| `lags` | no declared paths | supported (3) |
| `local_users` | no declared paths | supported (3); lossy `privilege-level` |
| `radius_servers` | **unsupported** `/radius-servers/server/host`, `/key` | **unsupported** `/radius-servers/server/host`, `/key` |
| `vxlan_vnis` | unsupported `/vxlan-vnis/*` | supported (3); lossy `udp-port`, `vni` sub-flags |
| `evpn_type5_routes` | unsupported `/evpn-type5-routes/route` | lossy `/evpn-type5-routes/route` (modelled as a VRF property) |
| `routing_instances` | unsupported `/routing-instances/instance` | supported (4); lossy `instance-type`, `route-distinguisher`, `rt-imports` |
| `raw_sections` | no declared paths | lossy `/system/raw-sections/vdc`, `/features` |
| `anycast_gateway_mac` | unsupported `/anycast-gateway-mac` | supported (1) |

## Notes grounding the dispositions

* **`hostname` is a substitution, not a drop.** The canonical tree reaches
  the NX-OS renderer with `hostname == ""`, and
  `netcanon/migration/codecs/cisco_nxos/render.py` has no omit path — it
  falls back to the literal `switch`. The emitted config carries
  `hostname switch` AND a synthesised `vdc switch id 1`, and the re-parse
  reads the device back as `switch`. Deploying the render renames the
  device.
* **`lags` is the pair's most operator-significant loss.** The source
  never populates `intent.lags` or `interfaces[].lag_member_of` (no
  `openconfig-if-aggregate` parse), but the bundle exists as an ordinary
  `CanonicalInterface` named `Port-channel1`, so the render emits
  `interface Port-channel1` with its `ip address 10.20.30.1/30` and the
  NX-OS parser re-derives a memberless `CanonicalLAG` from that stanza.
  Because the NX-OS renderer derives its feature gates from `tree.lags`
  (empty), the render also omits `feature lacp`. Net effect on the wire:
  an addressed port-channel with zero members and no LACP feature gate.
* **Multiple IPv4 addresses round-trip but not as secondaries.** The
  OpenConfig source marks none of them `is_secondary`, so
  `GigabitEthernet0/0/1` renders three bare `ip address A/24` lines. The
  audit scores PRESERVATION, and all three are preserved through the
  re-parse — but on a real Nexus a bare second `ip address` replaces the
  first rather than adding a secondary. This is a target-syntax caveat on
  a `good` field, not a fidelity loss.
* **`Tunnel100` loses its encapsulation upstream of the pair.** The source
  never populates `tunnel_type` (declared lossy on the cisco_iosxe side),
  so the render emits `feature tunnel` and `interface Tunnel100` with no
  `tunnel mode gre ip`, no source and no destination.
* **`timezone`, `dhcp_servers`, `radius_servers` are target-side gaps.**
  Both matrices declare them unsupported, so wiring the source parse would
  NOT move these rows — the NX-OS renderer emits no clock stanza, no DHCP
  pool and no AAA radius-server config regardless of what the canonical
  tree carries. Every other empty family on this pair is a source-side
  parse gap that WOULD move once the OpenConfig parser walks `<system>`,
  `<vlans>`, `<network-instances>` and `<snmp>`.
