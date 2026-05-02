# EVPN-VXLAN, MAC-VRF, L3-VRF: Arista EOS versus FortiGate FortiOS

## Arista EOS — VXLAN + EVPN + VRF surface

Source: [Arista EOS User Manual — VXLAN Configuration (4.36.0F)](https://www.arista.com/en/um-eos/eos-vxlan-configuration)
Source: [Arista EOS User Manual — Configuring EVPN (4.35.2F)](https://www.arista.com/en/um-eos/eos-configuring-evpn)
Source: [Arista EOS User Manual — VRF (4.35.2F)](https://www.arista.com/en/um-eos/eos-vrf)
Retrieved: 2026-05-01

```
vrf instance TENANT_A
!
ip routing vrf TENANT_A
!
interface Vlan100
   vrf TENANT_A
   ip address 10.100.0.1/24
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
   vxlan vlan 20 vni 10020
   vxlan vlan 100 vni 10100
   vxlan vrf TENANT_A vni 50100
!
router bgp 65001
   router-id 10.255.0.1
   neighbor 10.0.0.0 remote-as 65000
   !
   vlan 100
      rd 10.255.0.1:100
      route-target both 65000:100
      redistribute learned
   !
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
      route-target export evpn 65000:50100
   !
   address-family evpn
      neighbor 10.0.0.0 activate
   !
```

Notable Arista specifics:

- **VRF declaration via `vrf instance <name>`** at the top level (the
  modern form; legacy `vrf definition` also accepted on EOS 4.x).
- **Per-interface VRF binding** via `vrf <name>` inside the
  interface stanza (no `vrf forwarding` keyword on Arista, just
  bare `vrf`).
- **VLAN-to-VNI mapping** under `interface Vxlan1`:
  - `vxlan vlan N vni X` for L2 segment binding.
  - `vxlan vrf X vni Y` for L3 VNI (Type-5 IRB symmetric routing).
- **VTEP source interface** via `vxlan source-interface Loopback0`.
- **MAC-VRF / EVPN address-family** under `router bgp / vlan N` —
  the codec parses RD + RT communities and emits
  `instance_type="mac-vrf"` `CanonicalRoutingInstance` records.
- **L3 VRF EVPN** under `router bgp / vrf <name>` with `route-target
  import evpn` / `export evpn`.
- **EVPN data plane** activated via `router bgp / address-family
  evpn / neighbor X activate`.

## FortiGate FortiOS — none of the above

Source: [Fortinet Document Library — VRF support (FortiOS 7.x Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

FortiGate FortiOS is a session-based stateful firewall + UTM
platform.  As a routing/security appliance:

- **No VXLAN data plane.**  FortiGate's VXLAN tunnels (`config system
  vxlan`) exist for SD-WAN overlay scenarios and do not interoperate
  with EVPN-VXLAN fabrics.  The FortiGate codec lists every
  `/vxlan-vnis/*` xpath under `unsupported` with rationale
  "VXLAN not modelled — FortiGate is a firewall codec".
- **No EVPN / MP-BGP support** for fabric data-plane signalling.
  FortiGate's BGP is a vanilla unicast BGP without the EVPN address-
  family.  The codec parses-and-ignores BGP (Tier 3).
- **No MAC-VRF / L2VPN.**  No L2VPN service models on FortiGate.
- **VDOMs** are FortiGate's multi-tenancy primitive but they are
  HEAVYWEIGHT — each VDOM carries an independent firewall policy
  table, address-object database, admin sessions, and routing
  table.  VDOMs do not map 1:1 to Cisco-style named-VRFs.
- **FortiOS 7.x per-interface integer VRF** (`set vrf <id>`) is
  closer in spirit to Cisco VRF-Lite — a single global firewall
  context with multiple routing tables — but the FortiGate codec
  does NOT parse `set vrf` into `CanonicalRoutingInstance` records
  in v1.

## Cross-vendor mapping (Arista -> FortiGate)

Canonical surface (Arista populates; FortiGate codec is parse-and-
ignore for all of these):

```
vxlan_vnis: list[CanonicalVxlan]
evpn_type5_routes: list[CanonicalEvpnType5Route]
routing_instances: list[CanonicalRoutingInstance]
interfaces[].vrf: str   (per-interface VRF membership)
```

- **vxlan_vnis** — `unsupported`.  Arista parses fully; FortiGate
  codec capability matrix lists `/vxlan-vnis/vni`,
  `/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` all
  under `unsupported`.  Records drop silently on FortiGate render
  (operator review-required banner).  The Arista synthetic kitchen-
  sink (`ks-leaf-01`) carries five VNI records (10010, 10020,
  10100, plus L3-VNI 50100 on TENANT_A) — all drop.
- **evpn_type5_routes** — `unsupported`.  Both codecs list per-
  prefix records as parse-and-ignore.  FortiGate has no EVPN data
  plane.
- **routing_instances** — `unsupported`.  Arista populates with
  `instance_type="vrf"` for `vrf instance` blocks and
  `instance_type="mac-vrf"` for `router bgp / vlan N` MAC-VRFs.
  FortiGate codec does not parse any VRF representation in v1; the
  closest analogue would be FortiOS 7.x per-interface integer VRF
  (still not wired in v1) or VDOMs (heavyweight, structurally
  different).  All routing-instance records drop on render.
- **interfaces[].vrf** — `unsupported`.  Arista's `vrf TENANT_A`
  inside an interface stanza populates the canonical `vrf` field;
  FortiGate has no per-interface VRF render path in v1, so the
  field drops silently.  This is the per-interface companion to
  `routing_instances` — both must be wired together.

## Cross-vendor mapping — VLAN-to-VNI L2 binding (`vxlan_vnis[]`)

Sub-fields all `unsupported` on this direction:

- `vxlan_vnis[].vlan_id` — drops with the parent record.
- `vxlan_vnis[].vni` — drops.
- `vxlan_vnis[].mcast_group` — drops.
- `vxlan_vnis[].flood_list` — drops.
- `vxlan_vnis[].source_interface` — drops (FortiGate has no VTEP).
- `vxlan_vnis[].udp_port` — drops.

## Cross-vendor mapping — VRF (`routing_instances[]`)

Sub-fields all `unsupported` on this direction:

- `routing_instances[].name` — drops.
- `routing_instances[].instance_type` — drops.
- `routing_instances[].route_distinguisher` — drops.
- `routing_instances[].rt_imports` / `.rt_exports` — drop.
- `routing_instances[].description` — drops.
- `routing_instances[].l3_vni` — drops (no FortiGate Type-5 IRB).

Disposition summary: **unsupported across the whole surface**.
Arista's DC-class fabric stance has no FortiGate target on this
cross-pair.  Operators decommissioning an Arista leaf to a
FortiGate edge must accept that the EVPN-VXLAN tenant separation
collapses to FortiGate's VDOM / per-interface-integer-VRF model
manually, with the firewall product taking over the role of
inter-tenant boundary.
