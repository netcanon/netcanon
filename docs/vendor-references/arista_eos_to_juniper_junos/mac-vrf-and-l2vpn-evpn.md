# MAC-VRF and L2VPN-EVPN service models

How each platform declares the MAC-VRF (the virtual MAC table per
EVPN instance) and how the EVPN address-family is enabled under BGP.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-configuring-evpn (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)

Citation ids: `arista-evpn-cg`, `junos-evpn-irb-example`.

## Arista EOS form

VLAN-based service (one MAC-VRF per VLAN) — the most common DC pattern:

```
router bgp 65001
   address-family evpn
      neighbor SPINES activate
   vlan 100
      rd 10.255.0.1:100
      route-target both 64500:10100
      redistribute learned
   vlan 200
      rd 10.255.0.1:200
      route-target both 64500:10200
      redistribute learned
```

Per-VLAN `rd` + `route-target both X:Y` lives inside `router bgp` (NOT
under the L2 `vlan N` global stanza).  `redistribute learned` is
required for MAC announcements to flow.

## Junos form

```
set switch-options route-distinguisher 10.255.0.1:1
set switch-options vrf-target target:64500:1
set protocols evpn vni-options vni 10100 vrf-target target:64500:10100
set protocols evpn vni-options vni 10200 vrf-target target:64500:10200
set protocols evpn extended-vni-list all
set protocols evpn encapsulation vxlan
```

Junos defaults to **VLAN-aware service** — one default-switch instance
carries all VNIs, with the global RD/RT under `switch-options` and
per-VNI RT overrides under `protocols evpn vni-options`.  An explicit
per-VNI MAC-VRF model (Junos `instance-type mac-vrf`) is available
but rarely used outside service-provider deployments.

## Mapping notes

- Arista's per-VLAN RD/RT model is the **VLAN-based** EVPN service;
  Junos's default is **VLAN-aware** service.  Both vendors
  interoperate over the same EVPN NLRIs but the canonical model
  doesn't currently expose service-model selection — the rendered
  output picks each vendor's default form, which is correct for the
  common case.
- Per-VLAN RD on Arista (`10.255.0.1:100`) does NOT round-trip
  losslessly to Junos's single-RD form.  Operators using per-VLAN
  RDs for service-provider use cases need to layer
  `instance-type mac-vrf` explicitly on the Junos side; the
  canonical model flags this gap by storing only the global RD on
  the routing-instance.
- BGP / address-family activation is **not modelled canonically**
  in v1 — both codecs list `/routing/bgp` under `unsupported`.  The
  rendered output carries the EVPN-VXLAN data-plane intent but the
  operator must wire the BGP overlay manually.
