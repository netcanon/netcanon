# SNMP: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
snmp-server community "public" Operator
snmp-server location "Synthetic-Lab Rack 7"
snmp-server contact "netops@example.invalid"
snmp-server host 10.0.10.200
snmp-server host 10.0.10.201

snmpv3 user "monitor-usr" auth sha "$1$fakeAJ$auth1abcdef0123456789" \
                          priv aes "$1$fakeAJ$priv1abcdef0123456789"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

Notable AOS-S specifics:

- **Community access keyword.**  AOS-S uses `Operator` (read-only)
  and `Manager` (read-write) instead of Cisco's `RO`/`RW` or
  FortiGate's per-host permissions.  The canonical model stores
  only the bare community string (single scalar) so multi-
  community AOS-S configs (e.g. one Operator + one Manager) lose
  all but the first.
- **v3 USM grammar.**  Two-line form: `snmpv3 user <name> auth
  {md5|sha} <pass> priv {aes|des} <pass>` plus `snmpv3 group
  <group> user <name> sec-model ver3` for VACM mapping.  Aruba
  carries hashes in a `$1$<aoss-salt>$<hash>` format that is
  AOS-S-specific (NOT cross-compatible with FortiGate or
  Cisco-IOS).

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

Notable FortiOS specifics:

- **Indexed community table.**  Each community lives in a numbered
  edit; trap hosts nest inside via `config hosts`.
- **`security-level` derives from auth/priv presence.**  Three
  values: `no-auth-no-priv`, `auth-no-priv`, `auth-priv`.
- **Auth/priv protocol enums.**  Auth: `md5 | sha | sha224 |
  sha256 | sha384 | sha512`.  Priv: `aes | aes256 |
  aes256cisco | des`.
- **`ENC` prefix on hashes.**  FortiOS encrypts secrets with an
  internal key; the FortiGate codec preserves the `ENC` prefix
  verbatim.  NOT cross-compatible with Aruba's `$1$<aoss-salt>$
  <hash>`.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

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

- **community / location / contact** — `good`.  Direct preservation
  (Aruba `snmp-server location "X"` -> FortiOS `set location "X"`
  under `config system snmp sysinfo`).
- **trap_hosts** — `good`.  Aruba `snmp-server host` list maps to
  FortiOS `config hosts` nested table inside the community edit.
- **v3_users[].name / group** — `good`.  FortiGate render uses the
  canonical name as the edit ID.
- **v3_users[].auth_protocol / priv_protocol** — `good`.  Aruba's
  enum (`md5`/`sha`, `aes`/`des`) maps cleanly to FortiOS
  (`md5`/`sha`/`sha256`/..., `aes`/`aes256`/`des`).
- **v3_users[].auth_passphrase / priv_passphrase** — `lossy`.
  USM keys are salted with vendor-specific engineID-derived
  constants; Aruba-derived passphrases (`$1$<aoss-salt>$<hash>`)
  will fail on FortiGate after migration.  Operator must re-key
  v3 users on the target.
- **v3_users[].engine_id** — `lossy`.  Field exists in canonical
  but neither codec wires it through.

Disposition for v1/v2c surface: **good** (with caveat that Aruba's
multi-community Operator/Manager pattern collapses to single).

Disposition for v3 USM passphrases: **lossy** (vendor-specific
engineID salting; re-keying required post-migration).
