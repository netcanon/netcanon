# VXLAN VTEP / VNI mappings: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [Arista EOS Central — VXLAN Configuration Example](https://eos.arista.com/vxlan-configuration-example/)
Source: [EOS 4.36.0F — VXLAN](https://www.arista.com/en/um-eos/eos-vxlan)
Retrieved: 2026-04-30

Arista models the VTEP as `interface Vxlan1` with all per-VLAN +
per-VRF VNI mappings inside:

```
interface Vxlan1
 vxlan source-interface Loopback0
 vxlan udp-port 4789
 vxlan vlan 100 vni 10100
 vxlan vlan 200 vni 10200
 vxlan vrf TENANT_A vni 50000
```

The Arista codec parses these into `CanonicalVxlan` records (per VLAN
mapping) and `CanonicalRoutingInstance.l3_vni` (per VRF / Type-5
mapping).  See `netcanon/migration/codecs/arista_eos/parse.py`
GAP-EVPN-2 and GAP-EVPN-3 commentary.

## Cisco IOS-XE

Source: [Cisco IOS XE Catalyst 9500 — Configuring VXLAN BGP EVPN](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-7/configuration_guide/vxlan/b_177_bgp_evpn_vxlan_9500_cg.html)
Source: [Cisco IOS XE Catalyst 9500 — Network Virtualization Endpoint (NVE)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-7/configuration_guide/vxlan/b_177_bgp_evpn_vxlan_9500_cg/configuring_vxlan_bgp_evpn_layer_3_overlay_network.html)
Retrieved: 2026-04-30

Cisco IOS-XE's VXLAN/EVPN model uses `interface NVE1` (Network
Virtualization Endpoint) on platforms that support it (Catalyst 9300/
9500/9600 in NX-OS-like configuration mode, ASR 1000 with appropriate
licensing).  Standard IOS-XE on routers / older Catalyst platforms
does not expose `interface NVE` at all.

```
interface nve1
 source-interface Loopback0
 host-reachability protocol bgp
 member vni 10100 mcast-group 239.1.1.1
 member vni 50000 vrf TENANT_A
```

Per-VLAN VNI binding lives under `vlan configuration <N>`:

```
vlan configuration 100
 member evpn-instance 100 vni 10100
```

## Cross-vendor mapping

The canonical model is `CanonicalVxlan` plus the
`CanonicalRoutingInstance.l3_vni` field for L3 / Type-5 VNI.

The Cisco IOS-XE render path **does not** emit VXLAN/NVE
configuration: `netcanon/migration/codecs/cisco_iosxe_cli/render.py`
has no NVE / VLAN-configuration / l2vpn-evpn render block.  The Cisco
IOS-XE codec capability matrix at
`netcanon/migration/codecs/cisco_iosxe_cli/codec.py` lists all
VXLAN-related xpaths under `unsupported`:

```
/vxlan-vnis/vni
/vxlan-vnis/source-interface
/vxlan-vnis/udp-port
```

with explicit rationale ("IOS-XE VXLAN mappings (`interface nve1 /
member vni <N> associate vrf <name>`) parse-and-ignore in v1.
CanonicalVxlan schema exists; wire-up deferred until demand arrives
for Catalyst-to-Arista migrations.").

Practically: an Arista source with `interface Vxlan1` and full VNI
mapping table parses correctly into the canonical tree, but the Cisco
IOS-XE render output emits **nothing** for the VXLAN surface.  The
operator targeting IOS-XE must hand-author the equivalent
`interface nve1` and `vlan configuration ...` blocks.

Disposition: **unsupported**.  Reason: Cisco IOS-XE codec does not
render NVE / VXLAN; canonical `CanonicalVxlan` records and
`CanonicalRoutingInstance.l3_vni` values silently drop on render.
Wire-up deferred to GAP-VXLAN-IOSXE follow-up.
