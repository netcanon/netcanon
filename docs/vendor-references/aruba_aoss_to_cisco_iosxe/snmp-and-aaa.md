# SNMP, RADIUS, and local users — AOS-S source to OpenConfig NETCONF target

Source: [openconfig-system YANG schema docs (AAA augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

## SNMP

AOS-S parser populates the full `CanonicalSNMP` record:

* `community` from `snmp-server community "<name>" Operator|Manager`
* `location` / `contact` / `trap_hosts` from the obvious directives
* `v3_users` from `snmpv3 user "<name>" auth ... priv ...` plus
  `snmpv3 group "<group>" user "<name>" sec-model ver3`

The cisco_iosxe target render does not walk `intent.snmp` at all.

Additionally, the cisco_iosxe codec's CapabilityMatrix declares
`/snmp/v3-user` under `unsupported` explicitly:

> "The NETCONF/OpenConfig codec is a stub (Phase 0.5 experimental) —
> SNMPv3 USM wire-up requires the Cisco-IOS-XE-snmp native YANG
> module, not covered today.  The cisco_iosxe_cli sibling codec
> parses v3 users from show running-config output instead."

So SNMPv3 is doubly unsupported: render gap PLUS matrix declaration.

## RADIUS

AOS-S parser populates `intent.radius_servers` from
`radius-server host <ip>` / `radius-server key "<secret>"`.  The
cisco_iosxe target render emits nothing — `_render_canonical()`
walks interfaces only.

OpenConfig models RADIUS under
`<system><aaa><server-groups><server-group>` in the
openconfig-system AAA augment, but the cisco_iosxe codec does not
yet wire that subtree.

## Local users

AOS-S parser populates `intent.local_users` from `password manager
user-name "<name>" sha1 "<hash>"` and similar.  The cisco_iosxe
target render emits nothing — same render-side gap.

OpenConfig models local users under
`<system><aaa><authentication><users>` but again the codec doesn't
wire the subtree.

Even if wired, hash format incompatibility would force re-keying:
AOS-S uses SHA-1 / bcrypt / plaintext; Cisco uses MD5 / type-8
PBKDF2 / type-9 scrypt.  Same lossy classification as the
aruba_aoss_to_cisco_iosxe_cli direction.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `snmp` | unsupported | target render gap |
| `snmp.community` | unsupported | target render gap |
| `snmp.location` | unsupported | target render gap |
| `snmp.contact` | unsupported | target render gap |
| `snmp.trap_hosts` | unsupported | target render gap |
| `snmp.v3_users` | unsupported | target render gap + matrix `/snmp/v3-user` `unsupported` |
| `radius_servers` | unsupported | target render gap |
| `local_users` | unsupported | target render gap |
