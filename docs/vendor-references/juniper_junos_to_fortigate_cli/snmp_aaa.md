# SNMP + AAA / RADIUS: Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos SNMP overview](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html).
Source: [Junos SNMPv3 configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html).
Source: [Junos `radius-server` statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html).
Retrieved: 2026-05-01.

Junos SNMP:

```
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp location "Synthetic Lab Rack 7"
set snmp contact "noc@example.net"
set snmp trap-group monitoring targets 10.0.0.250
set snmp trap-group monitoring targets 10.0.0.251
#
set snmp v3 usm local-engine user monitor authentication-md5 authentication-key "$9$fakeMd5AuthKey$1"
set snmp v3 usm local-engine user monitor privacy-des privacy-key "$9$fakeDesPrivKey$1"
set snmp v3 vacm security-to-group security-model usm security-name monitor group netadmin
#
set snmp v3 usm local-engine user readonly_v3 authentication-sha256 authentication-key "$9$fakeSha256AuthKey$2"
set snmp v3 usm local-engine user readonly_v3 privacy-aes256 privacy-key "$9$fakeAes256PrivKey$2"
set snmp v3 vacm security-to-group security-model usm security-name readonly_v3 group readonly
```

Junos RADIUS:

```
set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
set system radius-server 10.0.0.201 port 1812 accounting-port 1813 secret "$9$fakeRadiusSecret$2"
```

Notable Junos specifics:

- **Communities**: multiple allowed; canonical scalar holds first
  parsed (Junos codec captures `community` as scalar).
- **Trap groups** with multiple targets per group.
- **SNMPv3** richly modelled: USM users with auth/priv protocols
  + VACM access plumbing (security-to-group, access, view).
- **Auth protocols**: `authentication-md5` / `authentication-sha`
  (= SHA-1) / `authentication-sha224` / `authentication-sha256`.
  Older releases lack `sha384` / `sha512` direct.
- **Privacy ciphers**: `privacy-des` / `privacy-aes128` /
  `privacy-aes192` / `privacy-aes256`.
- **Hash form**: `$9$...` reversible-encrypted blobs.
- **RADIUS keyed by IP** (no operator-friendly name); separate
  `accounting-port` field.

## FortiGate FortiOS

Source: FortiOS CLI Reference — `config system snmp sysinfo / community / user`.
Source: [FortiGate / FortiOS Administration Guide — User authentication / config user radius](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiGate SNMP:

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

FortiGate RADIUS:

```
config user radius
    edit "primary-radius"
        set server "10.50.0.20"
        set secret ENC fakeRadiusSecret11111111==
        set auth-type auto
        set radius-port 1812
    next
end
```

Notable FortiOS specifics:

- **Communities**: edit-table can hold multiple but FortiGate codec
  captures only the first into canonical scalar.
- **SNMPv3 security-level**: `auth-priv` / `auth-no-priv` /
  `no-auth-no-priv`.
- **Auth protocols**: `md5` / `sha` / `sha224` / `sha256` / `sha384`
  / `sha512`.
- **Hash form**: `ENC <opaque-base64>` — FortiOS-proprietary.
- **No accounting-port field**; canonical defaults to 1813.
- **Trap hosts** nested under `config system snmp community / config
  hosts` with mask (mask drops on parse).

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surfaces (`CanonicalSNMP`, `CanonicalSNMPv3User`,
`CanonicalRADIUSServer`).

- **snmp.community** — `good`.  Junos source -> FortiGate edit-table.
- **snmp.location / contact** — `good`.
- **snmp.trap_hosts** — `good`.  Junos trap-group `targets` flatten
  to canonical list; FortiGate emits one host per address.  Trap-
  group versioning drops; FortiGate defaults to v2c.
- **snmp.v3_users** — `lossy`.  Auth/priv passphrases NOT
  cross-decryptable (Junos `$9$...` vs FortiOS `ENC <...>`).  Junos
  VACM access plumbing flattens to a default-group on FortiGate
  render.
- **radius_servers** — `lossy`.  IP-keyed Junos -> name-required
  FortiGate (render synthesises `radius-<sequence>`).  Shared-secret
  incompatible (`$9$` vs `ENC`).  Acct-port: Junos has separate
  field; FortiGate has no separate field (canonical defaults to
  1813), so non-default Junos source values drop.

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/snmp_aaa.md`):

- **snmp.community** — `lossy`.  FortiOS multi-community drops to
  scalar.
- **snmp.v3_users** — `lossy`.  Operator re-keying required.
