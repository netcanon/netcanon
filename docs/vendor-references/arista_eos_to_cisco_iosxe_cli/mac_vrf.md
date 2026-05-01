# EVPN MAC-VRF: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [Arista EOS Central — EVPN VXLAN L2 Configuration Example (per-VLAN MAC-VRF)](https://eos.arista.com/evpn-configuration-vxlan-l2-vlan-aware-bundles/)
Retrieved: 2026-04-30

Arista expresses the per-VLAN MAC-VRF binding inside `router bgp` via
a `vlan <N>` sub-stanza, not as a top-level construct:

```
router bgp 65001
 vlan 100
  rd 65001:100
  route-target both 65001:100
  redistribute learned
```

Each `vlan <N>` block under `router bgp` represents an L2 EVPN
instance for VLAN N.  The RD + RT define the per-VLAN MAC-VRF
identity.  This pattern is documented in the Arista EVPN VXLAN L2
configuration guide — it is the canonical Arista EOS way to express
"announce MAC/IP routes for VLAN N over BGP-EVPN".

The Arista codec parses these into `CanonicalRoutingInstance` records
with `instance_type = "mac-vrf"` (see
`netconfig/migration/codecs/arista_eos/parse.py`
`_parse_router_bgp_vrf_routing_instances` and the GAP-EVPN-1
discussion in that function's docstring).

## Cisco IOS-XE

Source: [Cisco IOS XE 17 BGP Configuration Guide — L2VPN EVPN](https://www.cisco.com/c/en/us/td/docs/routers/asr920/configuration/guide/mpls/16-12-1/b-mpls-l2vpn-xe-16-12-asr920/m-bgp-evpn-vpls.html)
Source: [Cisco IOS XE Cisco Catalyst 9500 Series Switches — EVPN VXLAN Layer 2 Overlay Network](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-7/configuration_guide/vxlan/b_177_bgp_evpn_vxlan_9500_cg/configuring_evpn_vxlan_layer_2_overlay_network.html)
Retrieved: 2026-04-30

Cisco IOS-XE expresses MAC-VRFs through different constructs depending
on platform:

* **Catalyst 9500 / NX-OS lineage**: `vlan configuration <N>` plus
  `member evpn-instance <N> vni <X>` declares the EVPN instance for
  that VLAN; RD + RT live under `l2vpn evpn instance <N> vlan-based`.
* **ASR 920 / older IOS-XE**: `l2vpn evpn instance <N> vlan-based`
  carries the per-instance RD + RT; the VLAN is bound via `service
  instance` under the physical interface.

Neither form is a clean direct translation of Arista's
`router bgp / vlan <N>` per-VLAN sub-stanza.  Cisco IOS-XE's L2VPN-EVPN
configuration model is a separate top-level surface (`l2vpn evpn
instance ...` and / or `vlan configuration ...`), not an inline
sub-stanza of `router bgp`.

## Cross-vendor mapping

The Arista codec populates `CanonicalRoutingInstance` records with
`instance_type = "mac-vrf"` for each per-VLAN binding.  The Cisco
IOS-XE render path **does not** emit MAC-VRF records:
`netconfig/migration/codecs/cisco_iosxe_cli/render.py` walks
`tree.routing_instances` and emits `vrf definition` blocks (the L3
form), making no special handling for `instance_type == "mac-vrf"`.

Concretely: an Arista source with per-VLAN MAC-VRF bindings parses
correctly into the canonical tree, but the Cisco IOS-XE render output
emits these as plain `vrf definition <name>` blocks — a **type
mismatch** with the original L2 EVPN intent.  The operator targeting
IOS-XE must hand-author the equivalent `l2vpn evpn instance ...` or
`vlan configuration ... / member evpn-instance ...` lines.

Disposition: **lossy**.  Reason: Arista's per-VLAN MAC-VRF binding
under `router bgp / vlan <N>` has no corresponding emission path in
the Cisco IOS-XE renderer; canonical `instance_type = "mac-vrf"`
records get emitted as plain `vrf definition` blocks, which is
semantically wrong (L2 vs L3).  Operator review required.
