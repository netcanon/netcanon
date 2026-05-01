# Firewall policies: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — IOS Zone-Based
Firewall and ACL chapters.

Cisco IOS-XE has two distinct surfaces for firewalling:

- **Standard / extended ACLs** — per-interface stateless filtering:
  ```
  ip access-list extended INBOUND
   permit tcp any host 10.0.0.10 eq 443
   permit tcp any host 10.0.0.10 eq 80
   deny ip any any log
  !
  interface GigabitEthernet0/0/0
   ip access-group INBOUND in
  ```
- **Zone-Based Firewall (ZBF)** — stateful policy via class-maps,
  policy-maps, and zone-pairs.  More complex; rarely deployed on
  pure-routing IOS-XE platforms (Cat 9000 series).

NAT is configured separately:

```
ip nat inside source list 10 interface GigabitEthernet0/0/0 overload
ip nat inside source static 10.0.0.10 198.51.100.10
```

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Firewall / Policies](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config firewall policy`.
Source: [Fortinet FortiOS Cookbook — Firewall and security policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-04-30

FortiGate firewall policies are the **primary product surface** —
they are session-based, zone-aware, and integrate UTM (antivirus,
IPS, web-filter) profiles.  A representative snippet:

```
config firewall policy
    edit 1
        set name "WAN-to-DMZ-Web"
        set srcintf "wan1"
        set dstintf "dmz"
        set srcaddr "all"
        set dstaddr "Web-Servers"
        set action accept
        set schedule "always"
        set service "HTTPS" "HTTP"
        set inspection-mode flow
        set ssl-ssh-profile "certificate-inspection"
        set av-profile "default"
        set ips-sensor "default"
        set logtraffic all
        set nat enable
    next
end
```

NAT lives **inside** firewall policies (`set nat enable` + per-policy
ippool / dstaddr-VIP) and via address objects:

```
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
```

Notable FortiOS specifics:

- **Session-based stateful inspection** — every policy implies state
  table tracking (no notion of stateless ACL).
- **Zone-aware** — `srcintf` and `dstintf` are required.  No
  per-direction-on-interface ACL like Cisco's `ip access-group X
  {in|out}`.
- **Address objects** — IPs and subnets are first-class named objects
  (`config firewall address`); policies reference them by name.  No
  Cisco-style inline `permit ip 10.0.0.0 0.0.0.255 any`.
- **UTM integration** — antivirus, IPS, web-filter, application-
  control, DLP profiles attach per-policy.  No Cisco analogue.

## Cross-vendor mapping

The canonical schema **does not model** firewall policies.  See
`CanonicalIntent` in `netconfig/migration/canonical/intent.py` —
the field set is hostname / domain / DNS / NTP / interfaces / VLANs
/ static-routes / DHCP / SNMP / LAGs / local-users / RADIUS plus
the Tier-2 EVPN-VXLAN extensions.  No `firewall_policies` /
`acls` / `nat_rules` field exists.

The FortiGate codec's capability matrix lists:

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

The Cisco IOS-XE codec similarly does not parse ACLs / ZBF / NAT
rules — those land in `raw_sections` (Tier 3) for display-only
carry-through.

Cross-vendor migration of firewall intent is therefore **out of
scope**.  Operators migrating between platforms should manually
recreate policies on the target, treating the source's firewall
config as documentation rather than as a translatable artefact.

Disposition: **unsupported** in both directions.
Reason: canonical schema gap; firewall semantics differ
fundamentally between a stateless-ACL/ZBF router and a session-
based UTM firewall.
