# SNMP (v1/v2c communities, v3 USM, trap hosts)

How SNMP communities, trap hosts, and v3 USM users are configured on
each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-snmp (retrieved 2026-05-01)

Citation ids: `junos-snmp-overview`, `junos-snmpv3-cg`, `arista-snmp`.

## Junos form

```
set snmp location "rack-7-leaf-1"
set snmp contact "noc@example.net"
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp trap-group network-mgmt categories link
set snmp trap-group network-mgmt categories chassis
set snmp trap-group network-mgmt targets 10.0.5.10
set snmp trap-group network-mgmt targets 10.0.5.11

set snmp v3 usm local-engine user alice authentication-sha authentication-key "$9$..."
set snmp v3 usm local-engine user alice privacy-aes128 privacy-key "$9$..."
set snmp v3 vacm security-to-group security-model usm security-name alice group readonly-group
```

Junos models trap targets under named **trap-groups** with explicit
categories (link, chassis, configuration, etc).

## Arista form

```
snmp-server location "rack-7-leaf-1"
snmp-server contact noc@example.net
snmp-server community public ro
snmp-server community private rw
snmp-server host 10.0.5.10 version 2c public
snmp-server host 10.0.5.11 version 2c public

snmp-server user alice readonly-group v3 auth sha <hex> priv aes128 <hex>
snmp-server group readonly-group v3 priv read SystemView
```

Arista uses flat `snmp-server host` declarations with per-host
version + community arguments.

## Mapping notes

- **Community (v1/v2c).** Junos's `set snmp community X authorization
  read-only` -> Arista's `snmp-server community X ro`.  Direct
  semantic mapping (`read-only` <-> `ro`, `read-write` <-> `rw`).
- **Location / contact.** Direct one-to-one scalar mapping.
- **Trap targets.** Junos's named trap-groups flatten to Arista's
  per-host lines.  The trap-group name and per-group categories
  drop on canonical layer (`CanonicalSnmpTrapHost` carries host +
  community + version, not group / category).  Lossy.
- **v3 USM.** Both vendors support SHA-1 / SHA-256 authentication
  and AES-128 / AES-256 / 3DES privacy.
  - **Auth protocol.** Junos `authentication-sha` (SHA-1) -> Arista
    `auth sha`; Junos `authentication-sha256` -> Arista `auth
    sha256`.
  - **Priv protocol.** Junos `privacy-aes128` -> Arista `priv
    aes128`; Junos `privacy-aes192` / `aes256` map to Arista
    `aes192` / `aes256` if the target image supports them
    (Arista has historically lagged on AES-256; older images
    collapse to `aes128`).
  - **Authentication / privacy keys.** Junos stores the key as
    `$9$...` reversibly-encrypted form; Arista stores as a hex
    digest.  These are NOT cross-compatible — operator must re-key
    v3 users on the target.  Lossy by hash incompatibility.
- **Group / view (VACM).** Junos's `set snmp v3 vacm
  security-to-group` + `set snmp v3 vacm access` -> Arista's
  `snmp-server group <name> v3 ...`.  Canonical model carries
  group name; per-group view bindings drop (codec-side wire-up
  gap).
