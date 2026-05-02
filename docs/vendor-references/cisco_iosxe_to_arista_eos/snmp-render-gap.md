# SNMP — OpenConfig NETCONF source to Arista EOS target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

Source: [Arista EOS User Security (4.35.2F)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

## Why this is a parse-side gap, not a render-side gap

Unlike the forward direction (`arista_eos -> cisco_iosxe`) where the
target render silently drops SNMP data, on this reverse direction the
source PARSER never populates SNMP data.  The arista_eos target codec
is fully wired to render `intent.snmp` (community / location / contact
/ trap-host / v3 USM users); it just receives `intent.snmp = None`.

## What the cisco_iosxe parser does NOT extract

The codec walks `<interfaces>` only.  It does not walk:

* `openconfig-system:<snmp>` — community / location / contact /
  v3 USM users.
* Cisco-IOS-XE-snmp native YANG namespaces — Cisco IOS-XE devices
  expose their full SNMP configuration via the native YANG module
  (`Cisco-IOS-XE-snmp.yang`) rather than openconfig-system, because
  OpenConfig's SNMP coverage is incomplete.

The codec capability matrix declares `/snmp/community`,
`/snmp/location`, `/snmp/contact`, `/snmp/trap-host` under
`supported` aspirationally.  `/snmp/v3-user` is declared under
`unsupported` explicitly with the reason: "The NETCONF/OpenConfig
codec is a stub (Phase 0.5 experimental) — SNMPv3 USM wire-up
requires the Cisco-IOS-XE-snmp native YANG module, not covered
today."

## What the arista_eos target render does

The arista_eos codec's render walks `intent.snmp` and emits:

```
snmp-server community <community> ro
snmp-server location "<location>"
snmp-server contact "<contact>"
snmp-server host <addr>
snmp-server user <name> <group> v3 auth <proto> <hash> priv <proto> <hash>
```

When `intent.snmp` is None, the Arista render emits no SNMP
configuration.  The output Arista device has no SNMP enabled
regardless of source content.

## v3 hash compatibility (when wire-up lands)

Even with bidirectional wire-up of the cisco_iosxe SNMP parse path,
SNMPv3 passphrase hashes are NOT cross-vendor portable.  v3 USM
hashes are derived from a function of (passphrase, engineID), and
engineID differs between vendors and between devices.  Operators
migrating from Cisco IOS-XE to Arista must re-key SNMPv3 users on
the target.  This is upstream of the NetConfig codec layer; the
canonical model preserves opaque hash bytes verbatim per
`CanonicalSNMPv3User.auth_passphrase` schema docs.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `snmp` | not_applicable | Parse-side gap: cisco_iosxe parser doesn't walk `<snmp>` |
| `snmp.community` | not_applicable | Same |
| `snmp.location` | not_applicable | Same |
| `snmp.contact` | not_applicable | Same |
| `snmp.trap_hosts` | not_applicable | Same |
| `snmp.v3_users` | not_applicable | Doubly: parser gap PLUS the matrix declares `/snmp/v3-user` `unsupported` (Phase-0.5 stub; SNMPv3 USM requires native YANG bridging) |

## When this flips

Once the cisco_iosxe parser bridges into Cisco-IOS-XE-snmp native
YANG, `snmp.community` / `snmp.location` / `snmp.contact` /
`snmp.trap_hosts` flip to `good` (canonical-stable surface; Arista
syntax is byte-identical for v1/v2c).  `snmp.v3_users` flips to
`lossy` because of the engine-ID-derived hash incompatibility.
