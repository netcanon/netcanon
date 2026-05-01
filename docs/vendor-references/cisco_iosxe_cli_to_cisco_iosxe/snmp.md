# SNMP — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [SNMP Configuration Guide, Cisco IOS XE 17 — Configuring SNMP
Support](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-17-x/snmp-xe-17-book/nm-snmp-cfg-snmp-support.html)
(retrieved 2026-04-30).

v1 / v2c surface:

```
snmp-server community public RO
snmp-server community private RW
snmp-server location "Building 7 Floor 3"
snmp-server contact noc@example.com
snmp-server host 10.0.0.5 version 2c public
```

v3 USM:

```
snmp-server group READONLY v3 priv read all-items
snmp-server user opsuser READONLY v3 auth sha AUTHP4SS priv aes 128 PR1VP4SS
```

The `snmp-server user` lines are NOT echoed in `show running-config`
for security reasons; collectors reconstruct them from `show snmp
user`.  The `cisco_iosxe_cli` codec parses both forms.

## OpenConfig / Cisco-IOS-XE-snmp NETCONF form

OpenConfig has historically not had a fully-baked SNMP model — the
`openconfig-snmp` module is shorter and less complete than the
interface and routing models.  Cisco's NETCONF agent on IOS-XE 17.x
exposes SNMP primarily via the **native** model
(`Cisco-IOS-XE-snmp.yang`), which mirrors the CLI grammar.

Source: [Cisco-IOS-XE-snmp.yang vendor model — YangModels GitHub](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
(retrieved 2026-04-30).

Native YANG snippet (illustrative — exact tag names vary by IOS-XE
version):

```xml
<snmp-server xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-snmp">
  <community>
    <name>public</name>
    <RO/>
  </community>
  <location>
    <text>Building 7 Floor 3</text>
  </location>
</snmp-server>
```

## Cross-format mapping in this repository

The OpenConfig NETCONF codec in this repository declares the
`/snmp/community`, `/snmp/location`, `/snmp/contact`, `/snmp/trap-host`
paths as `supported` in its capability matrix and explicitly lists
`/snmp/v3-user` as `unsupported`.  However, like the VLAN paths
above, the codec's parse/render do not actually emit any SNMP XML —
the codec is a Phase-0.5 stub that only walks `<interfaces>`.

The CLI codec parses all five SNMP paths (including v3 users from
either `snmp-server user` lines or recovered `show snmp user` output).

| Canonical field | CLI -> NETCONF | NETCONF -> CLI |
|---|---|---|
| `snmp.community` | unsupported (NETCONF render emits no SNMP XML) | not_applicable |
| `snmp.location` | unsupported | not_applicable |
| `snmp.contact` | unsupported | not_applicable |
| `snmp.trap_hosts` | unsupported | not_applicable |
| `snmp.v3_users` | unsupported (capability matrix declares it explicitly) | not_applicable |

The codec's `unsupported_rename_categories = frozenset({"snmpv3"})`
declaration in `cisco_iosxe/codec.py` exists precisely to surface
this gap to operators in the per-pane override UI:

> "The NETCONF/OpenConfig codec is a stub (Phase 0.5 experimental) —
> SNMPv3 USM wire-up requires the Cisco-IOS-XE-snmp native YANG
> module, not covered today.  The `cisco_iosxe_cli` sibling codec
> parses v3 users from `show running-config` output instead."

Once SNMP is wired (and the codec bridges native or
`openconfig-snmp` for community + v3), the disposition flips:

* v1/v2c surface (community / location / contact / trap_hosts) ->
  `good` in both directions (same vendor, same engine, same
  underlying database).
* v3 USM passphrases -> `good` for same-vendor (cross-format on the
  same engine the device-derived engineID stays constant, so the
  hashes round-trip).  This is materially different from the
  cross-vendor v3 case where engineID divergence forces re-keying.
