# OpenConfig YANG vs Cisco-IOS-XE-native YANG on IOS-XE 17.x

## Background

Cisco IOS-XE platforms (Catalyst 9K, ISR, ASR1K, Cat8000V, CSR1Kv) run a
single configuration database that is exposed through three independent
schemas:

* **CLI** — the operator-facing `running-config` text format, line-
  oriented and indentation-significant.
* **Cisco-IOS-XE-native YANG** — Cisco-defined YANG modules whose tree
  shape mirrors the CLI grammar one-for-one (`Cisco-IOS-XE-native`,
  `Cisco-IOS-XE-interfaces`, `Cisco-IOS-XE-vrf`, `Cisco-IOS-XE-snmp`,
  `Cisco-IOS-XE-spanning-tree`, `Cisco-IOS-XE-ip` and dozens of
  feature-specific submodules).
* **OpenConfig YANG** — vendor-neutral models (`openconfig-interfaces`,
  `openconfig-vlan`, `openconfig-network-instance`, `openconfig-system`)
  that Cisco supports via translation to / from the native models.

Source: [Native, IETF, OpenConfig... Why so many YANG models? — Cisco
Blogs](https://blogs.cisco.com/developer/which-yang-model-to-use)
(retrieved 2026-04-30):

> "Native models are specific to Cisco devices and platforms, while
> open models are designed to be independent of the underlying platform
> implementation, with their intent to normalize per-vendor
> configuration of network devices. […] Cisco models are typically a
> superset of what OpenConfig offers, and requests for an OpenConfig
> data element are converted to the corresponding native data element."

## Implications for this codec pair

The `cisco_iosxe` codec in this repository is the OpenConfig-flavoured
NETCONF/XML codec.  Its tree shape (see `codec.py` namespace constants
`http://openconfig.net/yang/interfaces` +
`http://openconfig.net/yang/interfaces/ip`) is **OpenConfig only** —
it does not bridge into `Cisco-IOS-XE-native`.  This is a deliberate
Phase-0.5 scoping decision (see the codec docstring); it keeps the
codec portable across non-Cisco YANG-speaking platforms but caps the
covered surface at what OpenConfig models.

That cap matters for cross-format translation:

* **OpenConfig covers** interfaces (name, description, enabled, MTU,
  type, IPv4 / IPv6 addresses), VLANs (id, name, switched-vlan
  interface-mode + access/trunk lists), network-instance (VRF
  metadata), system (hostname, DNS, NTP, timezone), some SNMP, some
  routing.  These fields round-trip cleanly through the canonical
  intent tree.
* **Cisco-IOS-XE-native covers everything else** — banner motd, EXEC
  banners, `service timestamps`, line vty / console settings, AAA
  policy, route-maps, ACLs, crypto, QoS, and dozens of feature areas
  whose CLI text is preserved on the device but has no OpenConfig
  representation.  When a CLI source has these stanzas, an
  OpenConfig-only render strips them.

For the bidirectional `cisco_iosxe_cli` codec (see its capability
matrix), the same cap applies on the destination side: any field this
repository's OpenConfig codec doesn't model is `unsupported` or
`lossy` on the CLI -> NETCONF cross-pair.

## Quote-grade reference for the CLI ↔ NETCONF correspondence

Cisco IOS-XE 17.7+ ships a built-in introspection command:

> "Starting with Cisco IOS XE Cupertino 17.7.1 and later releases, you
> can automatically translate IOS commands into relevant NETCONF-YANG
> XML or RESTCONF-JSON request messages […]   Execute the
> `show running-config | format netconf-xml` command […]  to translate
> IOS commands."

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x —
NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
(retrieved 2026-04-30).

This output is the device's own ground truth for the CLI->YANG
bridge — but it emits the **native** model, not OpenConfig.  Any
OpenConfig codec consuming the same device's `<get-config>` reply
sees a different (smaller) tree shape, because the OpenConfig layer is
a translation overlay on top of native.

## Cross-pair disposition baseline

For the canonical fields this repository models, both wire formats
target the same operational state — so within the OpenConfig surface
the cross-pair should be `good` in both directions.  Drift surfaces
in three places:

1. **CLI-only fields** (banner, `service timestamps`, EXEC commands,
   `!` comments, line ordering, route-maps, ACLs, AAA policy) —
   OpenConfig has no slot for them, so CLI -> NETCONF is `unsupported`
   on these.  NETCONF -> CLI is `not_applicable` (the source never had
   them to begin with).
2. **CanonicalIntent fields the NETCONF codec doesn't wire** (SNMPv3,
   VRF declarations, VXLAN, LAGs, local users, RADIUS, DHCP server) —
   the NETCONF codec lists these `unsupported` in its capability
   matrix, so cross-translation drops them on render.  CLI source is
   richer than the NETCONF target can express.
3. **OpenConfig-richer-than-native edge cases** — IPv6 link-local
   scope, switched-vlan interface-mode discrimination, MTU layer
   ambiguity (IP MTU vs link MTU).  OpenConfig models these as
   discriminated leaves; CLI text often elides the discriminator.
   NETCONF -> CLI loses the precision; CLI -> NETCONF defaults the
   discriminator.

Confidence: **high** for the framing; **medium** for per-field
disposition because the OpenConfig codec in this repo is a Phase-0.5
stub that under-implements its declared capability matrix.
