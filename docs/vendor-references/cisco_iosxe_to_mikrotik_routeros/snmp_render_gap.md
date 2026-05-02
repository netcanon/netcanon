# SNMP render gap — cisco_iosxe NETCONF source to RouterOS target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)
Retrieved: 2026-05-01

## OpenConfig SNMP scope

OpenConfig models SNMP through `openconfig-system`'s `<snmp>` subtree
(community strings, location, contact, trap-targets, USM users).  The
cisco_iosxe codec's `CapabilityMatrix` declares the v1/v2c surface
under `supported`:

```
"/snmp/community",
"/snmp/location",
"/snmp/contact",
"/snmp/trap-host",
```

and the v3 surface under `unsupported`:

```
UnsupportedPath(
    path="/snmp/v3-user",
    reason=(
        "The NETCONF/OpenConfig codec is a stub (Phase 0.5 "
        "experimental) — SNMPv3 USM wire-up requires the "
        "Cisco-IOS-XE-snmp native YANG module, not covered "
        "today.  The ``cisco_iosxe_cli`` sibling codec "
        "parses v3 users from ``show running-config`` "
        "output instead."
    ),
),
```

The v1/v2c declaration is aspirational.  The codec's `parse()`
method walks `<interfaces>` only — no `<snmp>` element is read,
no `<system><snmp>` subtree is read.  The canonical
`intent.snmp` field is always `None` after a cisco_iosxe NETCONF
parse.

## RouterOS render

RouterOS overloads `/snmp community` for both v1/v2c and v3 USM
identities:

```
/snmp
set enabled=yes contact=ops@example.com location="DC1 / Rack 7"
/snmp community
add name=public addresses=10.0.0.0/8 read-access=yes
add name=v3user authentication-protocol=SHA1 \
    authentication-password="..." encryption-protocol=AES \
    encryption-password="..."
```

If the canonical `intent.snmp` field were populated, the MikroTik
codec would emit the corresponding section.  But because the source
side never populates it, the cross-pair render is empty — RouterOS
output carries no `/snmp` section at all.

## Disposition

`snmp`: `not_applicable` — source codec produces no SNMP intent on
parse.  `snmp.community` / `snmp.location` / `snmp.contact` /
`snmp.trap_hosts` / `snmp.v3_users`: same.

The classification is `not_applicable` rather than `unsupported`
because the structural absence is on the SOURCE side — there is no
data being dropped, just no data arriving.  Compare with the
sibling `cisco_iosxe_cli__mikrotik_routeros` pair where the source
DOES populate `intent.snmp` and the cross-pair classification is
`lossy` (with documented v3 algorithm-set divergence).

## When this changes

Three independent unblockers would flip this to `lossy`:

1. The cisco_iosxe codec wires up `<system><snmp>` parse — the v1/
   v2c surface lands in `intent.snmp`.
2. The cisco_iosxe codec wires up the Cisco-IOS-XE-snmp native YANG
   module to extract v3 USM users — `intent.snmp.v3_users`
   populates.
3. Either of the above prompts a re-pass of this YAML.

Until then, `not_applicable` is the honest classification and any
v1/v2c or v3 SNMP content in the source XML must be migrated by
re-keying on the target RouterOS device manually.
