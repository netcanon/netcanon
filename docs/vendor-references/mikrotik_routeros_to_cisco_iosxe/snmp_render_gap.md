# SNMP render gap — RouterOS source to cisco_iosxe NETCONF target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/tree/main/vendor/cisco/xe)
Retrieved: 2026-05-01

## RouterOS SNMP source

RouterOS exposes SNMP configuration in two sections:

```
/snmp
set enabled=yes contact=ops@example.com location="DC1 / Rack 7" \
    trap-target=10.0.0.50 trap-version=2

/snmp community
add name=public addresses=10.0.0.0/8 read-access=yes
add name=v3user authentication-protocol=SHA1 \
    authentication-password="..." encryption-protocol=AES \
    encryption-password="..."
```

RouterOS overloads the `/snmp community` section for both v1/v2c
and v3 USM identities — a community with auth/encryption fields
populated is a v3 user, otherwise it's a v2c community string.
The MikroTik parser populates:

* `intent.snmp.community` — first non-v3 community
* `intent.snmp.location` — from `/snmp set location=`
* `intent.snmp.contact` — from `/snmp set contact=`
* `intent.snmp.trap_hosts[]` — from `/snmp set trap-target=`
  (single-element list since RouterOS supports only one)
* `intent.snmp.v3_users[]` — for each `/snmp community` with auth
  fields.  RouterOS supports only MD5/SHA1 auth and DES/AES
  (= AES-128) priv; the canonical record carries those.

## What the cisco_iosxe target render emits

Nothing for SNMP.  The `_render_canonical()` method walks
`intent.interfaces` only.  No `<system><snmp>` element appears in the
output XML, regardless of canonical content.

The CapabilityMatrix lists:

```
"/snmp/community",
"/snmp/location",
"/snmp/contact",
"/snmp/trap-host",
```

under `supported`.  These are aspirational declarations for cross-
codec mesh translation friendliness, not actual render-time wire-up.

The matrix lists `/snmp/v3-user` under `unsupported` with reason
`"The NETCONF/OpenConfig codec is a stub (Phase 0.5 experimental) —
SNMPv3 USM wire-up requires the Cisco-IOS-XE-snmp native YANG
module, not covered today.  The cisco_iosxe_cli sibling codec parses
v3 users from show running-config output instead."`

This means v3 USM is doubly absent from the target render: the
overall SNMP render is gap-blocked, AND v3 specifically is matrix-
declared `unsupported` even when general SNMP wire-up lands.

## Disposition

* `snmp`: `unsupported` — render-side wire-up gap on every sub-field.
* `snmp.community` / `snmp.location` / `snmp.contact` /
  `snmp.trap_hosts`: `unsupported` (same gap).
* `snmp.v3_users`: `unsupported` — doubly so (render gap + matrix
  declaration).

## When this changes

Three independent unblockers:

1. The cisco_iosxe codec wires up `<system><snmp>` render — the v1/
   v2c surface flips to `good` (RouterOS source -> Cisco target,
   community / location / contact / single trap_host all map
   directly).
2. The cisco_iosxe codec adds Cisco-IOS-XE-snmp native YANG bridging
   — `intent.snmp.v3_users` flips to `lossy` (RouterOS only supports
   MD5/SHA1 + DES/AES-128, all of which Cisco supports cleanly; the
   `lossy` instead of `good` classification reflects that
   passphrases are engineID-salted and re-keying on the target is
   required regardless).
3. Either of the above prompts a re-pass of this YAML.

Until then, `unsupported` is the honest classification and any v1/
v2c SNMP content in the source must be re-applied directly on the
target Cisco device, with v3 users re-keyed.

## Direction-specific note

The contrast with the sibling `mikrotik_routeros__cisco_iosxe_cli`
pair is sharp: that pair classifies SNMP as `lossy` because the
cisco_iosxe_cli render DOES walk `intent.snmp` and emit
`snmp-server community ...` / `snmp-server host ...` / `snmp-server
user ...` lines.  The NETCONF stub's narrow render scope is the
single biggest factor making this pair lossier than its CLI sibling.
