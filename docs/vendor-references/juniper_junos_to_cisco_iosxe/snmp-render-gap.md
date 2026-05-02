# SNMP — render-side wire-up gap (v1/v2c + v3)

Source: [Junos SNMP overview](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html)
Retrieved: 2026-05-01

Source: [Junos SNMPv3 configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html)
Retrieved: 2026-05-01

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

## What the Junos source produces

The juniper_junos codec walks `set snmp community X authorization
{read-only|read-write}`, `set snmp location X`, `set snmp contact
X`, `set snmp trap-group <name> targets X`, and the v3 USM surface:

* `set snmp v3 usm local-engine user X authentication-{md5|sha|sha224|
  sha256} authentication-key "$9$..."`
* `set snmp v3 usm local-engine user X privacy-{des|aes128|aes192|
  aes256} privacy-key "$9$..."`
* `set snmp v3 vacm security-to-group security-model usm
  security-name X group <group>`

`intent.snmp` is populated with `CanonicalSNMP` carrying community,
location, contact, trap_hosts, and a list of `CanonicalSNMPv3User`
records on parse.

## What the cisco_iosxe render emits

Nothing.  The render walks `intent.interfaces` only.  `intent.snmp`
is silently dropped.

The codec's CapabilityMatrix declares `/snmp/community`,
`/snmp/location`, `/snmp/contact`, `/snmp/trap-host` as `supported`
aspirationally.  v3 (`/snmp/v3-user`) is declared `unsupported`
explicitly with reason "The NETCONF/OpenConfig codec is a stub
(Phase 0.5 experimental) — SNMPv3 USM wire-up requires the
Cisco-IOS-XE-snmp native YANG module, not covered today."

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `snmp` (top-level) | unsupported | render-side gap |
| `snmp.community` | unsupported | render-side gap |
| `snmp.location` | unsupported | render-side gap |
| `snmp.contact` | unsupported | render-side gap |
| `snmp.trap_hosts` | unsupported | render-side gap |
| `snmp.v3_users` | unsupported | doubly-blocked: render-side gap PLUS matrix-unsupported declaration on `/snmp/v3-user` |

## Repair path

Two distinct gaps:

1. **v1/v2c.** The cisco_iosxe `_render_canonical` would need to
   emit `<system><snmp><communities>` and `<contact>` / `<location>`
   leaves under `<system><config>`.  Mechanical extension; both
   sides of the canonical surface are stable.
2. **v3 USM.** The cisco_iosxe codec would need to bridge the
   Cisco-IOS-XE-snmp native YANG module to emit
   `<usm><user>` records with auth/priv key references.  Heavier;
   requires native-YANG bridging that this Phase-0.5 stub doesn't
   carry.  Even after v1/v2c wire-up, v3 stays unsupported until
   the native-YANG bridging lands.

## Hash format on cross-vendor

Even when the cisco_iosxe codec eventually wires v3 render, the
v3 USM passphrase round-trip is lossy: Junos uses `$9$...`
reversible-encrypted blobs (Junos's symmetric encryption with a
device-specific key); Cisco uses engineID-derived hashes that
require the source engineID for re-derivation.  Cross-vendor
migration requires the operator to re-key v3 users on the target
device after migration — no automatic decrypt path.  This is a
canonical-model property that survives any render-side wire-up.
