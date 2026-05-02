# OpenConfig YANG parse scope of the cisco_iosxe codec

Source: `netconfig.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec.parse`
(authoritative in-tree source for "what the parser walks")
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

## What the parser actually walks

The cisco_iosxe codec's `parse(raw)` method does this:

1. Parse the XML (handle malformed-XML errors).
2. Walk down to the `<interfaces>` element (handle NETCONF envelope
   variants: bare fragment, `<rpc-reply>/<data>` wrap).
3. For each `<interface>` child: extract `name`, `config/description`,
   `config/enabled` (strict YANG boolean), `config/type` (IANA ifType
   ident), and walk `<subinterfaces>/<subinterface>` for IPv4 + IPv6
   addresses.
4. Build a `CanonicalIntent` with `interfaces=[...]` and nothing else
   populated (other top-level fields stay at their defaults).

That's the full parse implementation.  `intent.hostname`,
`intent.snmp`, `intent.vlans`, `intent.static_routes`,
`intent.local_users`, `intent.lags`, `intent.routing_instances`
are NEVER populated by this codec, regardless of what the device's
NETCONF reply carries.

## What the matrix declares — the aspirational gap

The codec's `CapabilityMatrix._CAPS` declares these paths as
`supported`:

* `/system/hostname`, `/system/dns-server`, `/system/ntp-server`
* `/vlans/vlan/id`, `/vlans/vlan/name`
* `/routing/static-route`
* `/snmp/community`, `/snmp/location`, `/snmp/contact`,
  `/snmp/trap-host`

These declarations are aspirational: present so cross-codec mesh
translations don't classify these paths as `unsupported` on the
target side.  But the parser does not actually read XML for any of
them.  Operationally, an OPNsense render running on a canonical
tree produced by `cisco_iosxe` parse will see empty `intent.hostname`,
empty `intent.snmp`, empty `intent.vlans`, empty `intent.static_routes`
— so the OPNsense renderer emits nothing for those categories on
this cross-pair.

## Real Cisco NETCONF replies do carry the data

Cisco IOS XE 17.x devices DO return `<native>`, `<system>`, `<vlans>`,
`<network-instances>`, `<snmp>` subtrees from `<get-config>` against
the union YANG datastore.  The data is in the wire bytes — the
parser just doesn't read it.  This is a PARSE-side wire-up gap, not
a vendor-modelling gap.

For the cross-pair YAML's per-field disposition, the schema
README's `not_applicable` definition covers this case: "the field
is structurally absent on the source vendor's wire format" — here
the wire format CARRIES it but the codec doesn't extract.
Operationally identical from the perspective of the canonical tree
the OPNsense render sees.

## Implication for cisco_iosxe -> opnsense

Every canonical field NOT populated by the parser shows up as
`not_applicable` on this direction's expectation YAML.  This is
materially honest about the codec's current state.  When parser-
side wire-up lands (out of scope for this audit), the YAML will
need revision to flip `not_applicable` to `good` / `lossy` /
`unsupported` for the canonical-modelled fields, depending on
OPNsense's modelling boundary for each.
