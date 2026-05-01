# SNMP: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/snmp.md`](../cisco_iosxe_cli_to_fortigate_cli/snmp.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS CLI Reference — system snmp community / user / sysinfo](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/).
Retrieved: 2026-04-30

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
    next
end
```

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — SNMP.

```
snmp-server community READONLY ro
snmp-server location "DC1 Rack 4"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.50 version 2c READONLY
snmp-server user noc-mon NOC-GROUP v3 auth sha CISCO-AUTH-PASS priv aes 128 CISCO-PRIV-PASS
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

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
  carry multiple community strings; the FortiGate codec parses
  the first community into the canonical scalar.  Multi-community
  FortiOS configs lose all but one on canonical-side; Cisco render
  is therefore single-community even where the source had several.
- **snmp.location / contact** — `good`.
- **snmp.trap_hosts** — `good`.  The FortiOS host list flattens to
  the canonical list and Cisco emits one `snmp-server host` per
  entry.
- **snmp.v3_users[].name / group** — `good`.  Direct preservation.
- **snmp.v3_users[].auth_protocol** — `lossy`.  FortiOS's
  `sha224 / sha384 / sha512` map to Cisco's `sha` (Cisco IOS-XE
  CLI accepts only `md5` and `sha` historically; modern releases
  add `sha-2` family but the canonical-to-Cisco render path
  collapses to `sha`).  Surface preservation is good; semantic
  fidelity drops on advanced auth algorithms.
- **snmp.v3_users[].priv_protocol** — `lossy`.  FortiOS
  `aes256cisco` (a Cisco-compatibility AES-256 variant) and
  `aes256` (FortiOS-default AES-256) both flatten to canonical
  `aes256`; Cisco render emits `priv aes 256`.  Cisco's
  proprietary `3des` cipher is not commonly emitted by FortiGate.
- **snmp.v3_users[].auth_passphrase / priv_passphrase** — `lossy`.
  Hashes are not cross-compatible (engineID-salted on both sides);
  cross-vendor re-keying is required.  Both codecs preserve the
  opaque hash verbatim with vendor tags.
- **snmp.v3_users[].engine_id** — `lossy`.  Canonical field exists
  but neither parse path wires it through.

Disposition for v1/v2c surface: **good** (with caveat that multi-
community FortiOS configs collapse to single).

Disposition for v3 USM surface: **lossy** (engineID-salted
passphrases plus auth/priv-protocol enum coercion).
