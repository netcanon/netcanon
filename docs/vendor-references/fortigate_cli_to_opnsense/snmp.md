# SNMP: FortiGate FortiOS versus OPNsense

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 CLI Reference — `config system snmp
community` / `config system snmp user`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Retrieved: 2026-05-01

```
config system snmp sysinfo
    set status enable
    set description "Synthetic-Lab Rack 7"
    set contact-info "netops@example.invalid"
end
config system snmp community
    edit 1
        set name "public"
        config hosts
            edit 1
                set ip "10.0.10.200 255.255.255.255"
            next
        end
        set query-v1-status enable
        set query-v2c-status enable
        set trap-v1-status enable
        set trap-v2c-status enable
    next
end
config system snmp user
    edit "monitor-usr"
        set security-level auth-priv
        set auth-proto sha256
        set auth-pwd ENC fakeEncodedAuthHash==
        set priv-proto aes128
        set priv-pwd ENC fakeEncodedPrivHash==
    next
end
```

Notes:

- `config system snmp sysinfo` carries `description` (location-ish
  text but FortiOS labels it description) and `contact-info`.  The
  canonical `location` field maps from `description` here.
- `config system snmp community` is an edit-table; each community
  has its own `<hosts>` sub-table (also edit-tables) that carry the
  trap receivers.  Multiple communities are supported but canonical
  holds only ONE community string (the first parsed wins).
- v3 USM users live under `config system snmp user`.  Auth/priv
  passphrases are stored as `ENC <opaque-base64>` with FortiOS's
  internal-key encryption.
- Auth/priv protocols enumerate {`md5`, `sha1`, `sha224`, `sha256`,
  `sha384`, `sha512`} for auth and {`des`, `3des`, `aes128`, `aes192`,
  `aes256`} for priv.

## OPNsense

Source: [OPNsense Net-SNMP plugin
reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <snmpd>
    <syslocation>Synthetic-Lab Rack 7</syslocation>
    <syscontact>netops@example.invalid</syscontact>
    <rocommunity>public</rocommunity>
    <traphost>10.0.10.200</traphost>
  </snmpd>
</opnsense>
```

Notes:

- `<rocommunity>` is the read-only community.  Read-write
  (`<rwcommunity>`) is supported but rare in production.
- `<traphost>` carries the trap receiver.  Some plugin versions
  support multiple `<traphost>` elements; the codec emits one per
  canonical trap_hosts entry.
- SNMPv3 USM is NOT in `config.xml`.  OPNsense's SNMPv3 user store
  lives in the bsnmpd / net-snmp plugin's own
  `/usr/local/etc/snmpd.conf` createUser lines, outside the
  canonical surface.  The OPNsense codec capability matrix lists
  `/snmp/v3-user` as `unsupported` with this rationale.
- The OPNsense codec's `unsupported_rename_categories` frozenset
  declares `"snmpv3"` so the rename-pane shows the unsupported-
  category banner when OPNsense is the target.

## Cross-vendor mapping

Canonical fields covered (`CanonicalSNMP`):

```
community, location, contact, trap_hosts, v3_users, engine_id
```

FortiGate -> OPNsense:

- `snmp.community`: **good** — FortiGate `set name "public"`
  (community edit) ↔ OPNsense `<rocommunity>public</rocommunity>`.
  Multi-community FortiOS configs collapse to the first community
  on canonical.
- `snmp.location`: **good** — FortiGate `set description "..."`
  (sysinfo) ↔ OPNsense `<syslocation>...</syslocation>`.  Note the
  FortiOS field name is `description` while OPNsense uses
  `syslocation`; the canonical field is `location`.
- `snmp.contact`: **good** — FortiGate `set contact-info "..."`
  (sysinfo) ↔ OPNsense `<syscontact>...</syscontact>`.
- `snmp.trap_hosts`: **good** — FortiGate `<hosts>` edit-table host
  IPs ↔ OPNsense `<traphost>` elements.  FortiGate's per-host
  `query-v1-status` / `trap-v2c-status` toggles drop on canonical.
- `snmp.v3_users`: **unsupported** — OPNsense's v3 store lives in
  snmpd.conf, outside the canonical surface.  FortiGate-source
  v3 USM users drop on the cross-pair; the rename-pane shows the
  `snmpv3` unsupported-category banner declared on the OPNsense
  codec's `unsupported_rename_categories` frozenset.  Operators must
  re-declare v3 users on the OPNsense plugin's snmpd.conf
  manually after migration.
- `snmp.engine_id`: not currently wired through either codec.
