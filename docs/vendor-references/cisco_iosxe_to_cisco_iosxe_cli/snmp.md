# SNMP — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, OpenConfig partial coverage,
Cisco-IOS-XE-snmp native model) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/snmp.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec does not parse SNMP XML.  Its parse
path walks `<interfaces>` only.  The codec's capability matrix
explicitly declares `/snmp/v3-user` as `unsupported` and the v1/v2c
paths under `supported` are aspirational (no parse logic emits them).

| Canonical field | NETCONF -> CLI |
|---|---|
| `snmp.community` | not_applicable — parser never populates |
| `snmp.location` | not_applicable |
| `snmp.contact` | not_applicable |
| `snmp.trap_hosts` | not_applicable |
| `snmp.v3_users` | not_applicable |

Once the NETCONF codec wires SNMP parsing (likely via
Cisco-IOS-XE-snmp native YANG since OpenConfig has thin SNMP
coverage), the cross-pair flips to:

* v1/v2c surface -> `good` (community / location / contact /
  trap_hosts; same vendor, same database).
* v3 USM users -> `good` for same-vendor, same-engine.  The
  passphrase hashes are salted with the device's engineID; round-
  tripping NETCONF -> CLI on the **same device** preserves the
  engineID, so the hashes round-trip cleanly.  This is materially
  different from the cross-vendor v3 case (`cisco_iosxe_cli ->
  arista_eos`) where engineID divergence forces re-keying.

The codec's `unsupported_rename_categories = frozenset({"snmpv3"})`
declaration in `cisco_iosxe/codec.py` exists to flag the
v3-rename pane as inert when the NETCONF codec is selected as
target — the NETCONF wire-up gap means SNMPv3 user renames have
nowhere to land.  This will need to be reconsidered when SNMP
wire-up arrives.
