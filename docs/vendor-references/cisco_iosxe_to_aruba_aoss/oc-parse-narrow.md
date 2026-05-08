# What the cisco_iosxe NETCONF parser actually populates

Source: `netcanon.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec.parse`
(authoritative in-tree source for "what the parser walks")
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

## The parser's actual code path

The cisco_iosxe codec's `parse(raw)` method does this:

1. Parse the XML (handle malformed-XML errors).
2. Walk down to the `<interfaces>` element (handle NETCONF envelope
   variants).
3. For each `<interface>` child: extract `name`, `config/description`,
   `config/enabled` (strict YANG boolean), `config/type`, and walk
   `<subinterfaces>/<subinterface>` for IPv4 + IPv6 addresses.
4. Build a `CanonicalIntent` with `interfaces=[...]` and nothing else.

That's it.  `intent.hostname`, `intent.snmp`, `intent.vlans`, etc.
are NEVER populated by this codec, regardless of what the device's
NETCONF reply carries.  Even `intent.source_version` stays empty
(no version-hint extraction).

## What the canonical tree looks like

After `cisco_iosxe.parse()` of the synthetic kitchen-sink XML at
`tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml`, the
resulting `CanonicalIntent` has:

```
hostname = ""                  # never set
domain = ""                    # never set
dns_servers = []               # never set
ntp_servers = []               # never set
timezone = ""                  # never set
syslog_servers = []            # never set
interfaces = [10 records]      # PARSED
vlans = []                     # never set
static_routes = []             # never set
dhcp_servers = []              # never set
snmp = None                    # never set
lags = []                      # never set
local_users = []               # never set
radius_servers = []            # never set
vxlan_vnis = []                # never set (matrix unsupported)
evpn_type5_routes = []         # never set
routing_instances = []         # never set
```

For each interface record, populated fields are: `name`,
`description`, `enabled`, `interface_type`, `mtu` (NOT — see below),
`ipv4_addresses`, `ipv6_addresses` (scope=global hard-coded).

The parser DOES read `<mtu>` from the source XML into the
intermediate dict, but the bridge function
`_iface_dict_to_canonical()` does NOT carry it through to the
`CanonicalInterface.mtu` field.  This is a wire-up gap on the
parse side, declared `lossy` in the matrix.

## Wire-up gaps explicitly declared

The codec's CapabilityMatrix declares many paths under `supported`:

* `/system/hostname`, `/system/dns-server`, `/system/ntp-server`
* `/vlans/vlan/id`, `/vlans/vlan/name`
* `/routing/static-route`
* `/snmp/community`, `/snmp/location`, `/snmp/contact`,
  `/snmp/trap-host`

These declarations are aspirational — they exist so that cross-codec
mesh translations don't classify these paths as `unsupported` on the
target side.  But the parser does not actually read XML for any of
them.

Concretely, this means: the AOS-S target render running on a
canonical tree produced by cisco_iosxe parse will see empty
`intent.hostname`, empty `intent.snmp`, empty `intent.vlans`, etc.
The render emits nothing for those categories — there's no source
data.

## Disposition implication

Every canonical field NOT populated by the parser shows up as
`not_applicable` on this direction's expectation YAML.  This is
materially honest about the codec's current state.  When parser-side
wire-up lands, the YAML would need substantial revision to flip
`not_applicable` to `good` / `lossy` for the canonical-modelled
fields.
