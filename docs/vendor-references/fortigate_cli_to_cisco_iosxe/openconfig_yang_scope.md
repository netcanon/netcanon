# OpenConfig YANG render scope — what `cisco_iosxe` actually emits

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

Source: [Native, IETF, OpenConfig... Why so many YANG models? (Cisco Blogs)](https://blogs.cisco.com/developer/which-yang-model-to-use)
Retrieved: 2026-05-01

## What the FortiGate source produces

The `fortigate_cli` codec's `parse_intent()` populates the full
canonical surface from a FortiOS configuration export:

* `intent.hostname` from `config system global / set hostname "..."`
* `intent.dns_servers` from `config system dns / set primary / set
  secondary` (and the hidden `set tertiary`)
* `intent.ntp_servers` from `config system ntp / config ntpserver /
  edit N / set server <addr>`
* `intent.interfaces` from `config system interface` (with
  description / enabled / IPv4 / IPv6 / VLAN child detection / LAG
  member detection)
* `intent.vlans` synthesised from VLAN child interfaces (parent
  + vlanid pairs) plus SVI-style addressing
* `intent.static_routes` from `config router static / edit N`
* `intent.snmp.community` from `config system snmp community / edit
  N / set name`
* `intent.snmp.location` / `intent.snmp.contact` from `config system
  snmp sysinfo`
* `intent.snmp.trap_hosts` from per-community `config hosts` records
* `intent.snmp.v3_users[]` from `config system snmp user / edit
  "<name>"` with auth-proto / priv-proto / auth-pwd / priv-pwd
* `intent.local_users` from `config system admin / edit "<name>"`
  (super_admin -> privilege 15; other accprofiles -> privilege 1
  with profile name preserved in `role`)
* `intent.radius_servers` from `config user radius / edit "<name>"`
* `intent.lags` from `config system interface` records with `set
  type aggregate`
* `intent.dhcp_servers` from `config system dhcp server / edit N`
  (interface-bound model)

Effectively the entire canonical surface a Tier-1 / Tier-2 v1
codec covers.

## What the cisco_iosxe target render emits

Looking at the renderer entry point in
`netcanon/migration/codecs/cisco_iosxe/codec.py:_render_canonical()`:

```python
def _render_canonical(self, intent) -> str:
    root = ET.Element(f"{{{_NS_IF}}}interfaces")
    for iface in intent.interfaces:
        # ... emits <interface><name>, <config>{description, enabled, type},
        # ... emits <subinterfaces><subinterface> with <ipv4> + <ipv6>
    return ...
```

That is the entire body.  The renderer walks `intent.interfaces`
and emits exactly that subtree.  No `<system>`, no `<network-
instances>`, no `<snmp>`, no `<aaa>`, no DHCP-related XML.

## Implications for the FortiGate source

Every canonical field the FortiGate parser populates besides the
`intent.interfaces` core is dropped silently on cisco_iosxe render.
The canonical layer carries the data; the wire-out boundary
discards it.

This is a **render-side wire-up gap** — different from the forward
direction's parser-side gap.  Disposition is `unsupported` with
reason citing the render gap (matrix declarations as `supported`
for `/system/hostname`, `/system/dns-server`, `/system/ntp-server`,
`/snmp/community`, `/snmp/location`, `/snmp/contact`,
`/snmp/trap-host`, `/vlans/vlan/id`, `/vlans/vlan/name`, and
`/routing/static-route` are aspirational — they exist for
cross-codec mesh friendliness so translations *into* this codec
don't classify those paths as unsupported, but the actual emit
path is narrow).

Honest classification beats matrix-deference (per the schema
README's per-field disposition rule).

## Disposition

| Source field after FortiGate parse | Disposition on cisco_iosxe render | Rationale |
|---|---|---|
| `intent.interfaces` populated | varied (see `interface_fields.md`) | The only canonical surface emitted |
| Everything else populated | `unsupported` | cisco_iosxe render walks `intent.interfaces` only |

When the cisco_iosxe codec wires `<system>`, `<network-instances>`,
`<snmp>`, `<aaa>`, etc. on render, these flip to `good` / `lossy`
as cross-vendor render machinery applies.
