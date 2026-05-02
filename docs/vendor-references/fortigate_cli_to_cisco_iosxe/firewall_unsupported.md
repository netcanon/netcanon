# FortiGate firewall / NAT / UTM — source carries data, canonical is silent

Source: [Fortinet FortiGate Cookbook — Firewall policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

Source: [Cisco IOS-XE Programmability Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

## Reverse-direction framing

This direction is `fortigate_cli` (FortiOS) -> `cisco_iosxe`
(NETCONF/OpenConfig).  FortiGate's primary product surface is
firewall policy + NAT + VIP + UTM — exactly what a real edge
FortiGate's running config carries by volume.  Typical example:

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
`unsupported` in its capability matrix:

> "FortiGate policy rules (config firewall policy) are Tier 3 —
> policy semantics differ fundamentally from other vendors
> (session-based, zone-aware, UTM-enabled)."

> "FortiGate NAT lives inside firewall policy and address/VIP
> objects — not auto-translatable."

These stanzas fall into `raw_sections` if at all — the FortiGate
parser does not produce canonical records for them.

## Canonical schema gap

The v1 canonical model has NO representation for firewall policy /
NAT / VIP / UTM:

* No `CanonicalFirewallPolicy` / `CanonicalSecurityPolicy` record.
* No `CanonicalNATRule` record.
* No `CanonicalAddressObject` / `CanonicalServiceObject` /
  `CanonicalVIP` record.

This is intentional v1 scope — security policy semantics differ
fundamentally between vendors (Cisco ZBF zone-pairs, FortiGate
session-stateful zone-aware, OpenConfig's nascent policy model).
A canonical model that captured the cross-vendor surface would
need vendor-specific extensions for UTM / IPS / app-control / SSL
inspection, none of which are stable cross-vendor.

## Cisco target side

Cisco IOS-XE models security via Zone-Based Firewall (ZBF), ACLs,
and CBAC.  OpenConfig's `acl` model is shipped (`openconfig-acl`)
but Cisco's IOS-XE NETCONF coverage of ACLs is partial in v1.
The cisco_iosxe codec doesn't walk OpenConfig `<acl>` on parse or
emit it on render — `_render_canonical()` is interface-only.

## What this means in practice

Operators standing up a Cisco IOS-XE NETCONF orchestration
target from a FortiGate edge get:

* The interface canonical-core (name / description / enabled /
  IPv4 / IPv6) — the only fields the cisco_iosxe render emits.

They do NOT get:

* FortiGate firewall policies, VIPs, address objects, UTM profiles
  — these never reach the canonical layer in v1.
* Cisco-side ACL / ZBF emission — render-side gap on cisco_iosxe.

Operators consolidating a FortiGate edge into a Cisco IOS-XE box
must manually rearchitect security policy from scratch.  The pair
is appropriate ONLY for the narrow case where the security policy
is being migrated externally (out-of-band / professional services)
and `fortigate_cli -> cisco_iosxe` handles only the interface
addressing sub-step.

## Disposition

The canonical schema does not enumerate firewall / NAT fields, so
there is nothing to mark in the per-field expectation YAML.  The
absence is itself the documentation.  This file exists for the
operator orientation.

Forward direction: see
`../cisco_iosxe_to_fortigate_cli/firewall_unsupported.md` for the
forward framing where the cisco_iosxe parser doesn't even read
the source's ACL / ZBF subtrees, making the question moot
upstream of canonical.
