# SNMP, RADIUS, and local users — Cisco NETCONF source to AOS-S CLI target

Source: [openconfig-system YANG schema docs (AAA augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 Management and Configuration Guide — SNMP](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

Source: [Aruba ArubaOS-Switch 16.11 Access Security Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-05-01

## SNMP

The cisco_iosxe parser does NOT walk SNMP XML — neither OpenConfig's
`/snmp/*` nor the Cisco-IOS-XE-snmp native YANG.  `intent.snmp` is
None after parse.

The aruba_aoss target accepts `/snmp/community`, `/snmp/location`,
`/snmp/contact`, `/snmp/trap-host`, and `/snmp/v3-user` — but with
no source data, the render emits nothing.

For SNMPv3 specifically: the cisco_iosxe matrix declares
`/snmp/v3-user` under `unsupported` ("Phase 0.5 stub — SNMPv3 USM
wire-up requires the Cisco-IOS-XE-snmp native YANG module, not
covered today").  Even if the parser were extended to read v1/v2c
SNMP, v3 users would remain unsupported until the native YANG
module is wired through.

## RADIUS

Same story — parser doesn't walk `<system><aaa><server-groups>`.
`intent.radius_servers` is empty after parse.  AOS-S target
accepts the canonical surface but has nothing to render.

## Local users

Same again — parser doesn't walk `<system><aaa><authentication><users>`.
`intent.local_users` is empty after parse.

If the parser were extended, local users would round-trip through
the canonical `name / privilege_level / hashed_password / role`
tuple — but hash format incompatibility would force re-keying:

* Cisco: type-5 MD5 (`$1$...`), type-8 PBKDF2 (`$8$...`),
  type-9 scrypt (`$9$...`)
* AOS-S: SHA-1 (`<40 hex chars>`), bcrypt (`$2y$...`),
  plaintext (rare, deprecated)

No format overlap — operators must re-set passwords on the AOS-S
target.  Same lossy classification as the cisco_iosxe_cli direction.

## Disposition

| Field | Today | Notes |
|---|---|---|
| `snmp` | not_applicable | source parser gap |
| `snmp.community` | not_applicable | source parser gap |
| `snmp.location` | not_applicable | source parser gap |
| `snmp.contact` | not_applicable | source parser gap |
| `snmp.trap_hosts` | not_applicable | source parser gap |
| `snmp.v3_users` | not_applicable | source parser gap + matrix `unsupported` |
| `radius_servers` | not_applicable | source parser gap |
| `local_users` | not_applicable | source parser gap; would be lossy on hash |
