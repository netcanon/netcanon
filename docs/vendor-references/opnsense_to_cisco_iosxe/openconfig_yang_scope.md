# OpenConfig YANG render scope of the cisco_iosxe codec

Source: `netcanon.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec.render`
and `_render_canonical` (authoritative in-tree source for "what the
renderer emits")
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

## What the renderer actually emits

The cisco_iosxe codec's `_render_canonical(intent)` method does this:

1. Build a root `<interfaces>` element with the openconfig-interfaces
   namespace.
2. For each `CanonicalInterface` in `intent.interfaces`: emit
   `<interface><name>`, `<config><name>/<description>/<enabled>/<type>`,
   and a `<subinterfaces><subinterface><index>0</index>...</subinterface>`
   block carrying any IPv4 + IPv6 addresses.
3. Pretty-print and return.

That's the full render implementation.  The renderer NEVER emits
`<system>`, `<vlans>`, `<network-instances>`, `<snmp>`, `<routing>`,
`<aaa>`, `<dhcp>`, regardless of what the canonical tree carries
in `intent.hostname`, `intent.snmp`, `intent.vlans`, etc.

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
target side.  But the renderer does not actually emit XML for any
of them.  Operationally, an OPNsense source's hostname / SNMP /
VLAN / RADIUS / local-users records reach a `cisco_iosxe` render
and emerge as a bare `<interfaces>` document — everything else
silently dropped.

## Schema-README labelling: unsupported, not not_applicable

The schema README defines:

- `unsupported` — "the target vendor doesn't model the concept at
  all (in the auto-render canonical-portable form), so the renderer
  emits a comment / TODO marker / nothing.  reason REQUIRED."
- `not_applicable` — "the field is structurally absent on the
  source vendor's wire format."

For this direction, the OPNsense source CAN populate hostname /
domain / SNMP / local-users / RADIUS / VLANs / DHCP — and DOES for
several of those.  The render-side emit gap is therefore
`unsupported` rather than `not_applicable` for those fields.
Fields where the OPNsense parser ALSO doesn't populate (DNS / NTP
/ syslog / timezone / static-routes / IPv6 link-local) compound
the loss but the render gap is still the dominant failure mode.

## Implication for opnsense -> cisco_iosxe

Every canonical field NOT emitted by the renderer shows up as
`unsupported` on this direction's expectation YAML.  This is
materially honest about the codec's current state.  When render-
side wire-up lands (out of scope for this audit), the YAML will
need revision to flip `unsupported` to `good` / `lossy` for the
canonical-modelled fields, depending on Cisco's modelling boundary
for each.

A few fields stay `unsupported` even after render wire-up — VXLAN,
EVPN, VRF — because the cisco_iosxe codec's matrix declares
`/vxlan-vnis/*` and friends as unsupported regardless ("Phase 0.5
stub; native YANG bridging not covered").
