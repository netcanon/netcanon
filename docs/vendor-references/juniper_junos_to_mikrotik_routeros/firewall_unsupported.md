# Firewall + policy-statements: Juniper Junos versus MikroTik RouterOS (Tier-3 both ways)

How firewall filters / NAT / policy are modelled on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/security-policies/topics/topic-map/security-policies-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/routing-policy/topics/topic-map/policy-overview.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/24805973/Firewall (retrieved 2026-05-01)

Citation ids: `junos-firewall-overview`, `junos-policy-overview`,
`mikrotik-firewall`.

## Junos form

```
set firewall family inet filter PROTECT-RE term allow-bgp from \
    source-address 10.0.0.0/24
set firewall family inet filter PROTECT-RE term allow-bgp from \
    protocol tcp
set firewall family inet filter PROTECT-RE term allow-bgp from \
    destination-port bgp
set firewall family inet filter PROTECT-RE term allow-bgp then accept

set policy-options policy-statement PEER-EXPORT term 1 from \
    route-filter 192.168.0.0/16 orlonger
set policy-options policy-statement PEER-EXPORT term 1 then accept
```

Junos firewall filters are declared per address-family
(`family inet` / `family inet6` / `family bridge` / `family any`)
under top-level `firewall`.  Each filter is a list of named
`term`s with `from` (match) and `then` (action).  Routing policies
(`policy-options policy-statement`) follow the same term-based
grammar but apply to BGP / OSPF route filtering rather than packet
filtering.

The juniper_junos codec lists `/firewall/filter` under `unsupported`
("Tier-3 — the grammar (family / term / from / then) is distinct
from ACL models in other codecs and defers").

## RouterOS form

```
/ip firewall filter
add chain=input action=accept connection-state=established,related
add chain=input action=drop in-interface=ether1
add chain=forward action=accept connection-state=established,related

/ip firewall nat
add chain=srcnat action=masquerade out-interface=ether1

/ip firewall mangle
add chain=prerouting action=mark-connection new-connection-mark=isp1 \
    in-interface=ether1
```

RouterOS firewall + NAT + mangle live under `/ip firewall` (and
`/ipv6 firewall` for v6).  Chains are `input` / `forward` / `output`
(packet filter) and `srcnat` / `dstnat` (NAT).  RouterOS firewall
features are extensive and idiomatic — a meaningful canonical
subset would be a major engineering undertaking.

The mikrotik_routeros codec lists `/filter/rule` and `/nat/rule`
under `unsupported` ("Firewall filter rules are Tier 3
(informational) and not auto-rendered by the canonical bridge.").

## Cross-vendor mapping

Both vendors keep firewall / NAT / policy outside the canonical
auto-render surface.  Junos source's firewall filters land in
`raw_sections` on parse; RouterOS target render emits no firewall
config from canonical (the operator must hand-translate).  Same for
`policy-statement` on Junos source -> RouterOS routing-filter on
target.

Disposition: **unsupported** on Junos source -> RouterOS target
(neither side auto-translates).  Tier-3 by design — operator
hand-translation required.
