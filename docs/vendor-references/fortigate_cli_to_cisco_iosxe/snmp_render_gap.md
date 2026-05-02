# SNMP render gap — `fortigate_cli` source to `cisco_iosxe` target

Source: [Fortinet FortiGate CLI Reference 7.4 — `config system snmp community` / `config system snmp user`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/)
Retrieved: 2026-05-01

Source: [openconfig-system YANG schema docs (SNMP augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

## FortiGate SNMP source

FortiGate models SNMP across two stanzas:

```
config system snmp sysinfo
    set status enable
    set description "edge SNMP"
    set contact-info "noc@example.com"
    set location "DC1"
end

config system snmp community
    edit 1
        set name "public"
        config hosts
            edit 1
                set ip 10.0.0.5 255.255.255.255
            next
        end
    next
end

config system snmp user
    edit "noc-monitor"
        set security-level auth-priv
        set auth-proto sha
        set auth-pwd ENC <opaque-base64>
        set priv-proto aes
        set priv-pwd ENC <opaque-base64>
    next
end
```

The FortiGate parser populates the full `CanonicalSNMP` record:

* `intent.snmp.community` from the first `community` edit's `set name`
* `intent.snmp.location` / `intent.snmp.contact` from sysinfo
* `intent.snmp.trap_hosts` from per-community `config hosts` records
* `intent.snmp.v3_users[]` from `config system snmp user` blocks

## What the cisco_iosxe target render does

Nothing.  `_render_canonical()` walks `intent.interfaces` only —
no SNMP XML emission regardless of canonical content.

The cisco_iosxe codec's CapabilityMatrix declares
`/snmp/community`, `/snmp/location`, `/snmp/contact`, and
`/snmp/trap-host` under `supported` aspirationally.  The
`/snmp/v3-user` path is declared `unsupported` explicitly:

> "The NETCONF/OpenConfig codec is a stub (Phase 0.5
> experimental) — SNMPv3 USM wire-up requires the
> Cisco-IOS-XE-snmp native YANG module, not covered today.  The
> cisco_iosxe_cli sibling codec parses v3 users from
> `show running-config` output instead."

So v3 is doubly unsupported: render-side gap PLUS matrix
declaration.

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `snmp` (top-level) | unsupported | cisco_iosxe render doesn't emit SNMP XML |
| `snmp.community` | unsupported | Same render-side gap |
| `snmp.location` | unsupported | Same render-side gap |
| `snmp.contact` | unsupported | Same render-side gap |
| `snmp.trap_hosts` | unsupported | Same render-side gap |
| `snmp.v3_users` | unsupported | Doubly unsupported: render-side gap + matrix `/snmp/v3-user` declaration |

`unsupported` (render-side gap) rather than `not_applicable`
because the FortiGate source populates `intent.snmp` and the
canonical layer carries the data — the loss happens at
cisco_iosxe render.
