# Firewall + NAT + scripts + hotspot: MikroTik RouterOS versus Juniper Junos (Tier-3 both ways)

How firewall / NAT / scripts / hotspot / queues / wireless are
modelled on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/24805973/Firewall (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8323241/Scripting (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/24805384/Hotspot (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/security-policies/topics/topic-map/security-policies-overview.html (retrieved 2026-05-01)

Citation ids: `mikrotik-firewall`, `mikrotik-scripting`,
`mikrotik-hotspot`, `junos-firewall-overview`.

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

/interface wireguard
add listen-port=51820 name=wg0 private-key="fake-private-key"

/ip hotspot
add interface=bridge1 name=hs-guest

/system script
add name=daily-backup source="/system backup save name=daily"
```

RouterOS firewall + NAT + mangle live under `/ip firewall` (and
`/ipv6 firewall` for v6).  RouterOS additionally has `/interface
wireguard` (WireGuard VPN), `/interface ovpn-server` (OpenVPN),
`/ip hotspot` (captive-portal), `/system script` (operator scripts),
`/queue` (QoS / traffic shaping), `/interface wireless` (wireless
AP).  All of these are RouterOS-rich plumbing without canonical
analogues.

The mikrotik_routeros codec lists `/filter/rule` and `/nat/rule`
under `unsupported` ("Firewall filter rules are Tier 3
(informational) and not auto-rendered by the canonical bridge.").

## Junos form

```
set firewall family inet filter PROTECT-RE term allow-bgp from \
    source-address 10.0.0.0/24
set firewall family inet filter PROTECT-RE term allow-bgp then accept

set security policies from-zone trust to-zone untrust policy ALLOW-OUT \
    match source-address any destination-address any application any
set security policies from-zone trust to-zone untrust policy ALLOW-OUT \
    then permit
```

Junos firewall filters are declared per address-family (`family inet`
/ `family inet6` / `family bridge` / `family any`) under top-level
`firewall`.  SRX devices additionally have a `security policies`
hierarchy for stateful zone-based firewall.

The juniper_junos codec lists `/firewall/filter` under `unsupported`
("Tier-3 — the grammar (family / term / from / then) is distinct
from ACL models in other codecs and defers").

## Cross-vendor mapping

Both vendors keep firewall / NAT / policy outside the canonical
auto-render surface.  RouterOS source's `/ip firewall` rules land in
`raw_sections` on parse; Junos target render emits no firewall
config from canonical (operator hand-translates).  RouterOS-only
plumbing (hotspot, scripts, queues, wireless, WireGuard, OVPN) has
no Junos canonical analogue at all.

Disposition: **unsupported** on RouterOS source -> Junos target
(neither side auto-translates).  Tier-3 by design — operator hand-
translation required.  RouterOS-rich plumbing (hotspot, scripts,
queues, WireGuard, wireless AP, OVPN-server) is structurally absent
in the Junos target's auto-render surface and remains in
raw_sections for review.
