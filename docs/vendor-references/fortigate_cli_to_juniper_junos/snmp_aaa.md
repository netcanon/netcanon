# SNMP + AAA / RADIUS: FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: FortiOS CLI Reference — `config system snmp sysinfo / community / user`.
Source: [FortiGate / FortiOS Administration Guide — User authentication / config user radius](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-05-01.

FortiOS models SNMP and RADIUS as edit-table sections.  SNMP:

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

RADIUS:

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

- **SNMP communities**: edit-table can carry multiple community
  strings; FortiGate codec parses only the first into the canonical
  scalar (multi-community configs lose all but one).
- **SNMPv3 security-level**: `no-auth-no-priv` / `auth-no-priv` /
  `auth-priv` — derived from protocol presence on Junos render.
- **Auth/priv protocols**: `md5` / `sha` / `sha224` / `sha256` /
  `sha384` / `sha512` (auth); `des` / `aes` / `aes128` / `aes192` /
  `aes256` / `aes256cisco` (priv).
- **Hash form**: `ENC <opaque-base64>` — FortiOS-proprietary
  encryption; not cross-vendor portable.
- **RADIUS shared secret**: same `ENC <opaque-base64>` form.
- **Acct-port**: FortiOS has no separate `acct-port` field; canonical
  defaults to 1813.
- **`set radius-port 0`** placeholder normalises to default 1812 at
  parse-time.

## Juniper Junos

Source: [Junos SNMP overview](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html).
Source: [Junos SNMPv3 configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html).
Source: [Junos `radius-server` statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html).
Retrieved: 2026-05-01.

Junos SNMP:

```
set snmp community public authorization read-only
set snmp location "Synthetic Lab Rack 7"
set snmp contact "noc@example.net"
set snmp trap-group monitoring targets 10.0.0.250
set snmp trap-group monitoring targets 10.0.0.251
#
set snmp v3 usm local-engine user monitor authentication-sha256 authentication-key "$9$fakeKey$1"
set snmp v3 usm local-engine user monitor privacy-aes256 privacy-key "$9$fakeKey$2"
set snmp v3 vacm security-to-group security-model usm security-name monitor group netadmin
```

Junos RADIUS:

```
set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
set system radius-server 10.0.0.201 port 1812 secret "$9$fakeRadiusSecret$2"
```

Notable Junos specifics:

- **Communities**: `set snmp community <X> authorization
  {read-only|read-write}`.  Multiple communities allowed (Junos
  source can populate richer than the canonical scalar carries).
- **Trap groups**: named groups with multiple targets per group.
  Flatten to a single canonical `trap_hosts: list[str]`.
- **SNMPv3 auth protocols**: `authentication-md5` /
  `authentication-sha` / `authentication-sha224` /
  `authentication-sha256` (Junos exposes a richer set in 17.4+ but
  lacks `sha384`-direct in older releases).
- **Privacy ciphers**: `privacy-des` / `privacy-aes128` /
  `privacy-aes192` / `privacy-aes256` (no `aes256cisco` analogue).
- **VACM access plumbing**: `security-to-group`, `access`, `view` —
  flattens to a default-group on cross-vendor render.
- **Hash form**: `$9$...` reversible-encrypted blobs.  Not
  cross-vendor portable (vendor-specific salt).
- **RADIUS**: keyed by IP address (no operator-friendly name).
- **Accounting port**: `set system radius-server X accounting-port N`.

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surfaces:

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
    auth_protocol: str = ""     # "md5" | "sha" | "sha224" | "sha256" | "sha384" | "sha512"
    auth_passphrase: str = ""
    priv_protocol: str = ""     # "des" | "3des" | "aes" | "aes128" | "aes192" | "aes256"
    priv_passphrase: str = ""
    engine_id: str = ""

class CanonicalRADIUSServer(BaseModel):
    host: str
    key: str = ""
    auth_port: int = 1812
    acct_port: int = 1813
```

- **snmp.community** — `lossy`.  FortiOS multi-community drops to
  scalar.
- **snmp.location / contact** — `good`.  Direct map.
- **snmp.trap_hosts** — `good`.  FortiOS nested host edit-table
  (mask dropped) flattens to canonical list; Junos emits one
  `trap-group <name> targets X` per address.
- **snmp.v3_users** — `lossy`.  Auth/priv passphrases NOT
  cross-decryptable (FortiOS `ENC` vs Junos `$9$...`).  Operator
  re-keying required.
- **radius_servers** — `lossy`.  Shared-secret incompatible (FortiOS
  `ENC` vs Junos `$9$...`).  Acct-port: FortiGate has no field;
  canonical defaults to 1813.

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/snmp_aaa.md`):

- **snmp.community** — `good`.  Junos source community string fits
  the canonical scalar.
- **snmp.trap_hosts** — `good`.  Junos `trap-group X targets ...`
  flattens; FortiGate render emits one `edit N` per target under
  `config system snmp community / config hosts`.  Trap-group
  versioning drops; FortiGate defaults to v2c.
- **snmp.v3_users** — `lossy`.  Junos VACM access plumbing flattens
  to a default-group on FortiGate render.  Hash incompatible.
- **radius_servers** — `lossy`.  Junos IP-keyed -> FortiGate render
  synthesises a name (`radius-<sequence>`).  Junos `accounting-port`
  field has no FortiGate analogue.
