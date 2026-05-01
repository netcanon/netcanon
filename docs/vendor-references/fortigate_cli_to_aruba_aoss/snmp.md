# SNMP: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/snmp.md`](../aruba_aoss_to_fortigate_cli/snmp.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS CLI Reference — `config system snmp`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/).
Retrieved: 2026-04-30

```
config system snmp sysinfo
    set status enable
    set location "data-center-rack-7"
    set contact-info "noc@example.org"
end
config system snmp community
    edit 1
        set name "public-ro"
        config hosts
            edit 1
                set ip "10.50.0.10 255.255.255.255"
            next
            edit 2
                set ip "10.50.0.11 255.255.255.255"
            next
        end
    next
end
config system snmp user
    edit "monitor-readonly"
        set security-level auth-priv
        set auth-proto sha256
        set auth-pwd ENC fakeAuthHashAAAAAAAAAAAAAA==
        set priv-proto aes256
        set priv-pwd ENC fakePrivHashBBBBBBBBBBBBBB==
    next
end
```

See [`../aruba_aoss_to_fortigate_cli/snmp.md`](../aruba_aoss_to_fortigate_cli/snmp.md)
for full FortiOS specifics.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
snmp-server community "public-ro" Operator
snmp-server location "data-center-rack-7"
snmp-server contact "noc@example.org"
snmp-server host 10.50.0.10
snmp-server host 10.50.0.11

snmpv3 user "monitor-readonly" auth sha "$1$<aoss-salt>$<hash>" \
                                priv aes "$1$<aoss-salt>$<hash>"
snmpv3 group "auth-priv-grp" user "monitor-readonly" sec-model ver3
```

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface (same as forward):

```
class CanonicalSNMP(BaseModel):
    community: str = ""
    location: str = ""
    contact: str = ""
    trap_hosts: list[str]
    v3_users: list[CanonicalSNMPv3User]

class CanonicalSNMPv3User(BaseModel):
    name: str
    group: str = ""
    auth_protocol: str = ""
    auth_passphrase: str = ""
    priv_protocol: str = ""
    priv_passphrase: str = ""
    engine_id: str = ""
```

- **community** — `lossy`.  FortiGate's edit-table can carry
  multiple community strings; the FortiGate codec parses only the
  first into the canonical scalar.  Multi-community FortiOS
  configs lose all but one.  Aruba render maps the surviving
  community to AOS-S's bare `snmp-server community "X" Operator`
  form (defaulting to Operator/RO since canonical does not carry
  a permission field).
- **location / contact** — `good`.  Direct preservation.
- **trap_hosts** — `good`.  FortiOS's nested `config hosts` table
  lands in the canonical list; Aruba renders `snmp-server host
  <addr>` lines.
- **v3_users[].name / group** — `good`.  Direct preservation.
- **v3_users[].auth_protocol / priv_protocol** — `lossy`.
  FortiOS supports a wider auth enum (`sha224` / `sha256` /
  `sha384` / `sha512`) than AOS-S (`md5` / `sha` only).  Cross-
  vendor render coerces FortiOS `sha224`+ to Aruba `sha`.
  Priv enum (FortiOS `aes` / `aes256` / `aes256cisco` / `des`)
  collapses to AOS-S `aes` / `des`.
- **v3_users[].auth_passphrase / priv_passphrase** — `lossy`.
  USM keys are salted with vendor-specific engineID-derived
  constants; FortiOS-derived `ENC <opaque-base64>` will fail on
  Aruba after migration.  Operator must re-key v3 users on the
  target.
- **v3_users[].engine_id** — `lossy`.  Canonical field exists but
  not wired through.

Disposition for v1/v2c surface: **good** (with caveat that FortiOS
multi-community pattern collapses to single canonical scalar).

Disposition for v3 USM passphrases: **lossy** (vendor-specific
engineID salting; re-keying required post-migration).  Auth
protocol coercion is mechanical but loses precision when FortiOS
source uses sha224+.
