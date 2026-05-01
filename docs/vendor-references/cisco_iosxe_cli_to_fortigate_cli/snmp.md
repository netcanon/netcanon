# SNMP: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — SNMP
support.

```
snmp-server community READONLY ro
snmp-server location "DC1 Rack 4"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.50 version 2c READONLY
snmp-server user noc-mon NOC-GROUP v3 auth sha CISCO-AUTH-PASS priv aes 128 CISCO-PRIV-PASS
```

v3 user form: `snmp-server user <name> <group> v3 auth {md5|sha}
<pass> priv {des|aes {128|192|256} | 3des} <pass>`.

Cisco-side hash handling: passphrases entered as plaintext are stored
in the running-config as plaintext UNTIL the operator runs
`snmp-server engineID local <eid>` and re-enters them, at which
point IOS-XE stores them as `localized-key <hex>`.  Cross-vendor
migration of localized keys is not portable.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS CLI Reference — system snmp community](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — `config system snmp community`.
Source: [Fortinet FortiGate / FortiOS CLI Reference — system snmp user](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — `config system snmp user`.
Retrieved: 2026-04-30

FortiOS splits SNMP into three configs:

```
config system snmp sysinfo
    set status enable
    set location "DC1 Rack 4"
    set contact-info "noc@example.com"
end
config system snmp community
    edit 1
        set name "READONLY"
        config hosts
            edit 1
                set ip "10.0.0.50 255.255.255.255"
            next
        end
    next
end
config system snmp user
    edit "noc-mon"
        set security-level auth-priv
        set auth-proto sha
        set auth-pwd ENC <opaque-hash>
        set priv-proto aes
        set priv-pwd ENC <opaque-hash>
        set notify-hosts "10.0.0.50"
    next
end
```

Notable FortiOS specifics:

- **Indexed community table.**  Each community string lives in a
  numbered edit (1, 2, 3, ...) rather than a single global directive.
  The trap host list is nested under the community via
  `config hosts`.
- **`security-level` derives from auth/priv presence.**  The three
  accepted values are `no-auth-no-priv`, `auth-no-priv`, `auth-priv`.
- **Auth / priv protocol enums.**  FortiOS accepts `md5 | sha |
  sha224 | sha256 | sha384 | sha512` for auth and `aes | aes256 |
  aes256cisco | des` for priv.  Cisco's `aes 128 | aes 192 | aes 256`
  collapses to FortiOS `aes` (= AES-128) by default.
- **`ENC` prefix on hashes.**  FortiOS encrypts secrets with an
  internal key; the `ENC` prefix denotes this.  The FortiGate codec
  preserves the prefix verbatim under the canonical opaque hash.

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalSNMP(BaseModel):
    community: str = ""
    location: str = ""
    contact: str = ""
    trap_hosts: list[str] = Field(default_factory=list)
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

- **snmp.community** — `lossy`.  FortiGate's edit-table model can
  carry multiple community strings, but the canonical model holds a
  single `community` scalar.  Cross-vendor migration of Cisco-side
  multiple-community configs (rare) drops all but one.
- **snmp.location** — `good`.  Direct map to `set location`.
- **snmp.contact** — `good`.  Direct map to `set contact-info`.
- **snmp.trap_hosts** — `good`.  Cisco's `snmp-server host` list maps
  to FortiOS's `config hosts` nested table.  Both vendors round-trip
  the host list cleanly.
- **snmp.v3_users[].name / group** — `good`.  Direct preservation;
  FortiGate uses the edit ID as the username.
- **snmp.v3_users[].auth_protocol / priv_protocol** — `good`.  The
  canonical-to-FortiGate enum mapping is documented in
  `render._CAN_TO_FG_AUTH` / `_CAN_TO_FG_PRIV`.
- **snmp.v3_users[].auth_passphrase / priv_passphrase** — `lossy`.
  USM keys are salted with vendor-specific engineID constants;
  Cisco-derived passphrases will fail on FortiGate after migration
  unless the operator sets `engine_id` to match the source.  Hashes
  pass through verbatim with the `ENC` prefix; cross-vendor re-keying
  is required in practice.  Documented in CanonicalSNMPv3User
  docstring.
- **snmp.v3_users[].engine_id** — `lossy`.  The canonical field
  exists; FortiGate parse / render does not currently wire it
  through.

Disposition for v1/v2c surface (community / location / contact /
trap_hosts): **good** (with caveat that multi-community configs
collapse to single).

Disposition for v3 USM passphrases: **lossy** (vendor-specific
engineID salting; re-keying required post-migration).
