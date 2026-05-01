# Routing protocols (BGP / OSPF / static): Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S supports a limited set of dynamic routing protocols on
higher-end models (3810 / 5400R class):

- **OSPFv2**: `router ospf` global block.  Per-area `area <id>`
  with optional `nssa` / `stub`.
- **RIP**: `router rip` global block.  Limited modern usage.
- **No BGP, no EIGRP, no IS-IS** in any AOS-S firmware.

Lower-end AOS-S models (2930F / 2930M) support only static routes
+ per-VLAN basic routing; OSPF is a 3810 / 5400R licensed feature.

The aruba_aoss codec does **not** parse any of the dynamic-routing
stanzas in v1; they fall into `raw_sections` for display only.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Dynamic routing](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiOS 7.x uses an FRR-based routing daemon with rich BGP / OSPF
/ RIP / IS-IS support:

```
config router bgp
    set as 65001
    set router-id 10.255.255.1
    config neighbor
        edit "192.0.2.1"
            set remote-as 65002
        next
    end
end
config router ospf
    set router-id 10.255.255.1
    config area
        edit 0.0.0.0
        next
    end
end
```

The FortiGate codec does not currently parse `config router bgp` /
`config router ospf` / etc. into canonical records in v1; they
fall into `raw_sections` for display only.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface: **none**.  v1 canonical model has no
representation for dynamic routing protocols beyond static routes
(`CanonicalStaticRoute`).  Both codecs parse-and-ignore the
relevant stanzas.

Disposition: **not_applicable** for this cross-pair (no canonical
field exists).  Operators migrating between vendors with dynamic
routing must manually translate the source's protocol config to
the target.

Static routes (`ip route` / `config router static`) are the only
routing primitive that round-trips on this cross-pair; see
`static_routes.md`.
