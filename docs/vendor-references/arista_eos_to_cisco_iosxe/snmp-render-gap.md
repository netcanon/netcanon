# SNMP — Arista source to OpenConfig NETCONF render gap

Source: [Arista EOS User Security (4.35.2F)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

## Arista source surface

The arista_eos parser populates `intent.snmp` with the v1/v2c
surface (`community`, `location`, `contact`, `trap_hosts`) plus the
v3 USM surface (`v3_users` list with name, group, auth_protocol,
auth_passphrase, priv_protocol, priv_passphrase, engine_id).

Arista source grammar:

```
snmp-server community public ro
snmp-server location "DC1 Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250
snmp-server user monitor netadmin v3 auth sha $9$fakeAuthHash$1 priv aes256 $9$fakePrivHash$1
```

The Arista CapabilityMatrix lists `/snmp/community`, `/snmp/location`,
`/snmp/contact`, `/snmp/trap-host`, `/snmp/v3-user` under `supported`.

## OpenConfig target surface

OpenConfig models SNMP under `openconfig-system`:

* `<snmp><communities>` for v1/v2c
* `<snmp><engine>` for engineID
* `<snmp><users>` for v3 USM users (group binding via VACM)
* `<snmp><targets>` for trap destinations

In practice Cisco IOS-XE devices use the Cisco-IOS-XE-snmp.yang
native module rather than openconfig-system for SNMP — OpenConfig's
SNMP coverage is incomplete and Cisco's NETCONF agent prefers
the native module.

## What the cisco_iosxe codec emits

`_render_canonical()` does not walk `intent.snmp` at all.  No
`<snmp>` element appears in the output XML regardless of source
content.  This applies to both v1/v2c and v3 surfaces.

The capability matrix declares the v1/v2c paths
(`/snmp/community`, `/snmp/location`, `/snmp/contact`,
`/snmp/trap-host`) under `supported` aspirationally; the codec
intends to wire them up via the Cisco-IOS-XE-snmp native YANG
module bridging eventually but hasn't today.

The v3 path `/snmp/v3-user` is declared under `unsupported`
explicitly, with the reason: "The NETCONF/OpenConfig codec is a stub
(Phase 0.5 experimental) — SNMPv3 USM wire-up requires the
Cisco-IOS-XE-snmp native YANG module, not covered today.  The
`cisco_iosxe_cli` sibling codec parses v3 users from `show running-config`
output instead."

The codec also declares
`unsupported_rename_categories = frozenset({"snmpv3"})`, which
surfaces an amber pane-compat banner when operators select this
codec as target — the only codec-level surface today that flags its
v3 wire-up gap to operators.

## v3 hash compatibility

Even with bidirectional wire-up, SNMPv3 passphrase hashes are NOT
cross-vendor portable.  v3 USM hashes are derived from a function
of (passphrase, engineID), and engineID differs between vendors and
between devices.  Concretely:

* Arista source carrying `auth sha $9$fakeAuthHash$1` was salted
  with the source Arista device's engineID.
* Cisco IOS-XE target consuming the same hash would attempt to use
  it salted with its own engineID; SNMP authentication fails.

Operators migrating across vendors must re-key SNMPv3 users on the
target.  This is upstream of the NetConfig codec layer; the
canonical model preserves the opaque hash bytes verbatim per
`CanonicalSNMPv3User.auth_passphrase` schema docs (which call out
the "never plaintext" guarantee but make no compatibility claim).

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `snmp` | unsupported | Render-side wire-up gap: `_render_canonical` does not walk `intent.snmp` |
| `snmp.community` | unsupported | Same render gap |
| `snmp.location` | unsupported | Same |
| `snmp.contact` | unsupported | Same |
| `snmp.trap_hosts` | unsupported | Same |
| `snmp.v3_users` | unsupported | Doubly: render gap PLUS matrix declares `/snmp/v3-user` `unsupported` (Phase-0.5 stub) |

Operator implication: SNMP / SNMPv3 from Arista to a Cisco IOS-XE
device requires routing through `cisco_iosxe_cli` (the certified
CLI codec) for v1/v2c, and post-render re-keying on the device for
v3 regardless of pipeline.
