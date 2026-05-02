# SNMP — parse-side wire-up gap (v1/v2c + v3)

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Junos SNMP overview](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html)
Retrieved: 2026-05-01

Source: [Junos SNMPv3 configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

## What OpenConfig models

The `openconfig-system` model has an `snmp` augment that carries
community strings, location, contact, trap hosts, and v3 USM users
(via `openconfig-snmp`).  Cisco's vendor model
`Cisco-IOS-XE-snmp.yang` is sharply richer (per-VRF SNMP server
config, view definitions, SNMP-server-engine-id management) but
the cross-codec canonical surface is the OpenConfig common one.

## What the cisco_iosxe parser actually reads

Nothing.  The parser walks `<interfaces>` only.  `intent.snmp` is
None after parse, regardless of source XML content.

This is a parse-side wire-up gap.  The codec's CapabilityMatrix
declares `/snmp/community`, `/snmp/location`, `/snmp/contact`, and
`/snmp/trap-host` as `supported` aspirationally.  v3 (`/snmp/v3-user`)
is declared `unsupported` explicitly with reason "The NETCONF/
OpenConfig codec is a stub (Phase 0.5 experimental) — SNMPv3 USM
wire-up requires the Cisco-IOS-XE-snmp native YANG module, not
covered today."

## What the Junos target render does with empty input

Nothing.  The render walks `intent.snmp` and bails when the value
is None — no `set snmp` lines emit.

The juniper_junos codec is rich on the SNMP render side:
`/snmp/community`, `/snmp/location`, `/snmp/contact`, and
`/snmp/v3-user` are all declared `supported`.  Junos's SNMPv3 USM
renders the canonical user list with `set snmp v3 usm local-engine
user X authentication-{md5|sha} authentication-key "<key>"` and
`set snmp v3 vacm security-to-group security-model usm
security-name X group <group>`.  All of this is dead code on this
direction because there's no source SNMP data.

## What WOULD survive a hypothetical wire-up

If the cisco_iosxe parser were extended to walk `<snmp>` (likely
via Cisco-IOS-XE-snmp native YANG bridging since OpenConfig SNMP
coverage on Catalyst trains is incomplete), the dispositions would
flip:

| Field | Today | After hypothetical wire-up |
|---|---|---|
| `snmp.community` | not_applicable | good |
| `snmp.location` | not_applicable | good |
| `snmp.contact` | not_applicable | good |
| `snmp.trap_hosts` | not_applicable | good |
| `snmp.v3_users` | not_applicable | lossy (passphrase re-key required cross-vendor) |

The v3 hash-format lossy classification: Cisco encrypts USM
auth/priv passphrases with engineID-derived constants; Junos uses
`$9$...` reversible-encrypted blobs.  Cross-vendor migration
requires the operator to re-key v3 users on the target after
migration — no automatic decrypt path.

## Disposition

| Field | Today |
|---|---|
| `snmp` (top-level) | not_applicable |
| `snmp.community` | not_applicable |
| `snmp.location` | not_applicable |
| `snmp.contact` | not_applicable |
| `snmp.trap_hosts` | not_applicable |
| `snmp.v3_users` | not_applicable |

The v3 user surface is doubly-blocked: parser-side gap PLUS the
explicit `/snmp/v3-user` `unsupported` declaration in the codec
matrix (which would persist after hypothetical v1/v2c wire-up
because v3 needs native-YANG bridging).
