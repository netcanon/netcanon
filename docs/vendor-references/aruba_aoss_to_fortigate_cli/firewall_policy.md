# Firewall policies: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has a Tier-3 ACL surface (named extended access-lists,
applied per-port or per-VLAN) but **no stateful firewall, no NAT,
no VPN, no UTM**.  Typical example:

```
ip access-list extended ALLOW_MGMT
    10 permit tcp 10.0.0.0/24 any eq 22
    20 permit tcp 10.0.0.0/24 any eq 443
    30 deny ip any any
    exit

interface 1
    ip access-group ALLOW_MGMT in
    exit
```

The aruba_aoss codec lists `/filter/rule` under unsupported in its
capability matrix ("AOS-S access-lists are Tier 3
(informational) and not yet auto-rendered").  ACL stanzas fall
into `raw_sections` if at all.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate Cookbook — Firewall policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-04-30

FortiGate's firewall policy is its **primary product surface**:

```
config firewall policy
    edit 1
        set name "outbound-allow"
        set srcintf "internal"
        set dstintf "wan1"
        set srcaddr "all"
        set dstaddr "all"
        set service "ALL"
        set action accept
        set nat enable
        set logtraffic all
    next
end
config firewall vip
    edit "web-server-vip"
        set extip 198.51.100.10
        set extintf "wan1"
        set mappedip "10.0.0.50"
    next
end
config firewall address
    edit "internal-network"
        set subnet 10.0.0.0 255.255.0.0
    next
end
```

The FortiGate codec lists `/filter/rule` and `/nat/rule` under
unsupported in its capability matrix ("FortiGate policy rules
(config firewall policy) are Tier 3 — policy semantics differ
fundamentally from other vendors (session-based, zone-aware,
UTM-enabled)" and "FortiGate NAT lives inside firewall policy and
address/VIP objects — not auto-translatable").

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface: **none**.  v1 canonical model has no
representation for firewall policy / NAT / VPN / UTM.  Aruba ACLs
and FortiGate policy live in `raw_sections` if at all.

Disposition: **not_applicable** for this cross-pair (no canonical
field exists).  Aruba ACLs do not have a sensible target on
FortiGate (the policy semantics differ fundamentally — ACL is
stateless first-match, FortiGate policy is stateful zone-aware
session-based).  Operators consolidating an AOS-S edge into a
FortiGate must manually rearchitect the security policy from
scratch.
