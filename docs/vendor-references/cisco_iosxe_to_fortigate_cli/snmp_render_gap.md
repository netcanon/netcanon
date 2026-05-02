# SNMP — `cisco_iosxe` source to `fortigate_cli` target

Source: [openconfig-system YANG schema docs (SNMP augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate CLI Reference 7.4 — `config system snmp community` / `config system snmp user`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Retrieved: 2026-05-01

## OpenConfig SNMP coverage

OpenConfig models SNMP under `<snmp>` with `<community>` /
`<contact>` / `<location>` / `<trap-host>` for v1/v2c, and
`<engine>` + `<view>` + `<vacm>` + `<usm>` for v3.  The
Cisco-IOS-XE-snmp native YANG module (Cisco vendor extension)
adds Cisco-specific paths like `community-config` /
`v3-user-config`.

Real-world Catalyst 9K devices typically respond to the OpenConfig
namespace with a sparse `<snmp>` element bridged from the native
YANG.  The data is on the wire when an operator reads
`<get-config>` from a configured device.

## What the `cisco_iosxe` parser does

Nothing.  The codec's `parse()` walks `<interfaces>` only — there
is no `_parse_snmp()` helper, no walk of `<snmp>` or
`<system><snmp>` subtrees.  After parse, `intent.snmp` is `None`.

The `cisco_iosxe` codec's CapabilityMatrix declares
`/snmp/community`, `/snmp/location`, `/snmp/contact`, and
`/snmp/trap-host` under `supported`, but those declarations are
aspirational (cross-codec mesh friendliness) — they exist so that
translations *into* the cisco_iosxe codec from other sources
don't classify the paths as `unsupported` on the target side, but
the actual parser never populates `intent.snmp`.

The matrix declares `/snmp/v3-user` explicitly under `unsupported`
with rationale:

> "The NETCONF/OpenConfig codec is a stub (Phase 0.5
> experimental) — SNMPv3 USM wire-up requires the
> Cisco-IOS-XE-snmp native YANG module, not covered today.  The
> cisco_iosxe_cli sibling codec parses v3 users from
> `show running-config` output instead."

So v3 is doubly unsupported: parse gap PLUS matrix declaration.

## What the FortiGate target would do

The FortiGate codec (`fortigate_cli`) accepts the full SNMP
canonical surface:

* `intent.snmp.community` -> `config system snmp community / edit
  N / set name "<community>"`
* `intent.snmp.location` / `intent.snmp.contact` -> `config system
  snmp sysinfo / set location / set contact`
* `intent.snmp.trap_hosts` -> per-host `config hosts` records
  inside the community or under sysinfo
* `intent.snmp.v3_users[]` -> `config system snmp user / edit
  "<name>" / set security-level auth-priv / set auth-proto sha /
  set auth-pwd ENC <hash> / set priv-proto aes / set priv-pwd
  ENC <hash>`

When `intent.snmp` is `None` (the cisco_iosxe-source case), the
FortiGate render emits no SNMP stanzas regardless.  The
information would be lost without ever reaching the render — the
codec parser never had it.

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `snmp` (top-level) | not_applicable | NETCONF parser doesn't read `<snmp>` |
| `snmp.community` | not_applicable | Same parse-side gap |
| `snmp.location` | not_applicable | Same parse-side gap |
| `snmp.contact` | not_applicable | Same parse-side gap |
| `snmp.trap_hosts` | not_applicable | Same parse-side gap |
| `snmp.v3_users` | not_applicable | Doubly missing: parse-side gap + matrix `/snmp/v3-user` `unsupported` |

Promotes to `lossy` (vendor-specific salt incompatibility on v3
passphrases; multi-community collapse) when the cisco_iosxe parser
wires `<snmp>` reading.
