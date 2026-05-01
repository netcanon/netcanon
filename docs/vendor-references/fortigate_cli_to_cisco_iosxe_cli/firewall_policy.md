# Firewall policies: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/firewall_policy.md`](../cisco_iosxe_cli_to_fortigate_cli/firewall_policy.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Firewall / Policies](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Source: [Fortinet FortiOS Cookbook — Firewall and security policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-04-30

FortiGate firewall policies are the **primary product surface**:

```
config firewall policy
    edit 1
        set name "WAN-to-DMZ-Web"
        set srcintf "wan1"
        set dstintf "dmz"
        set srcaddr "all"
        set dstaddr "Web-Servers"
        set action accept
        set service "HTTPS" "HTTP"
        set ssl-ssh-profile "certificate-inspection"
        set av-profile "default"
        set ips-sensor "default"
        set nat enable
    next
end
config firewall vip
    edit "Web-VIP"
        set extip 198.51.100.10
        set mappedip "10.0.0.10"
        set extintf "wan1"
        set portforward enable
        set extport 443
        set mappedport 443
    next
end
config firewall address
    edit "Web-Servers"
        set subnet 10.0.0.0 255.255.255.0
    next
end
```

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — IOS Zone-Based
Firewall and ACL chapters.

```
ip access-list extended INBOUND
 permit tcp any host 10.0.0.10 eq 443
 permit tcp any host 10.0.0.10 eq 80
 deny ip any any log
!
interface GigabitEthernet0/0/0
 ip access-group INBOUND in
!
ip nat inside source list 10 interface GigabitEthernet0/0/0 overload
ip nat inside source static 10.0.0.10 198.51.100.10
```

## Cross-vendor mapping (FortiGate -> Cisco)

The canonical schema **does not model** firewall policies, NAT
rules, address objects, VIPs, or UTM profiles.  See the FortiGate
codec's capability matrix:

```python
UnsupportedPath(
    path="/filter/rule",
    reason=(
        "FortiGate policy rules (config firewall policy) are "
        "Tier 3 — policy semantics differ fundamentally from "
        "other vendors (session-based, zone-aware, UTM-enabled)."
    ),
),
UnsupportedPath(
    path="/nat/rule",
    reason=(
        "FortiGate NAT lives inside firewall policy and "
        "address/VIP objects — not auto-translatable."
    ),
),
```

Cross-vendor migration of FortiGate firewall intent to Cisco is
**out of scope**.  Operators migrating a FortiGate edge to a Cisco
ZBF (or to plain ACLs on a Cat 9000) should manually reconstruct
the policy intent on the target, treating the FortiGate firewall
policy / VIP / address-object / UTM profile config as documentation
rather than as a translatable artefact.

The reverse-direction observation: where Cisco -> FortiGate had
nothing to translate (Cisco-side ACL/ZBF/NAT was a small surface
relative to FortiGate's policy product), FortiGate -> Cisco loses
**most of FortiGate's value-add** — UTM profiles, application
control, SSL inspection, schedules, all have no Cisco analogue
even with manual reconstruction.

Disposition: **unsupported** in both directions.
