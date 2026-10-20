# Netcanon Capabilities + Known Limitations

Netcanon is a multi-vendor network device configuration translator
with two co-hosted concerns:

1. **Backup** — pull `running-config` (or vendor equivalent) from
   devices over SSH / NETCONF / REST and store in
   `configs/<host>.<ext>`.
2. **Migration** — translate a stored backup from one vendor's native
   config grammar into another, via a shared canonical intent tree.

This document is the operator-facing source of truth for **what the
program does and does not do**.  Internal architecture lives in
[`../ARCHITECTURE.md`](../ARCHITECTURE.md); contributor rules live in
[`../AGENTS.md`](../AGENTS.md).  Per-codec live certification status
lives in [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md).

---

## Supported vendors

The migration codecs listed below ship today, plus a `_mock` adapter
used in tests.  Backup-side device definitions are listed under
[`../netcanon/definitions/library/`](../netcanon/definitions/library/) (one YAML per vendor/OS family).

**Platform fit.**  The canonical model covers the shared network-function
layer.  On a switch or router that is most of the device's configuration;
on a firewall appliance it is a minority of it.  The policy table, NAT, VPN
and UTM profiles are Tier 3 and are out of scope **in either direction** —
when a firewall is the *source* they are detected and listed by name; when a
firewall is the *target*, nothing is emitted for them at all and the migrate
page raises a **scope advisory** saying so (see § Scope advisories below).
If your migration's centre of gravity is policy, Netcanon is the wrong tool —
see [`COMPARISON.md`](COMPARISON.md).

A codec's **primary device class** — the `Primary class` column below, and
the first entry in its `device_classes` — is the authoritative scope
declaration for that platform: `firewall`-primary codecs are translated at
the L2/L3 layer only.  The two-clause test for setting it lives in
[`../AGENTS.md`](../AGENTS.md) § Hard Rules; the term is defined in
[`glossary.md`](glossary.md); the boundary is guarded by
[`../tests/unit/migration/test_scope_boundary.py`](../tests/unit/migration/test_scope_boundary.py).

| Codec | Vendor | Primary class | Wire format | Direction | Certainty |
|---|---|---|---|---|---|
| `cisco_iosxe_cli` | Cisco IOS-XE | router | `show running-config` text | bidirectional | certified |
| `cisco_iosxe`     | Cisco IOS-XE | router | NETCONF / OpenConfig XML  | bidirectional | best_effort (Phase 0.5 stub render) |
| `cisco_nxos`      | Cisco NX-OS  | switch | `show running-config` text | bidirectional | certified (all 4 phases — L1/L3 + L2 switchport/LAG + SNMP/users + HSRP + VRF RD/RT + per-VRF static + VXLAN-EVPN/L3VNI + IPv4 Distributed Anycast Gateway; round-trip-validated against a 6-config `batfish/lab-validation` corpus across 4 NX-OS 9.x scenarios; IPv6 anycast, plus a documented set of Tier-2/Tier-3 surfaces, remain unsupported — see the live matrix / §A) |
| `cisco_iosxr`     | Cisco IOS-XR | router | `show running-config` text | bidirectional | certified (all 4 phases — interfaces (4-segment) + VRF + RT + RD-from-`router bgp` + per-iface VRF + Bundle-Ether LAGs + local users + per-VRF static + dot1q→VLAN; SP-routing/route-policy/MPLS/IS-IS surfaced via the Tier-3 banner; round-trip-validated against a 10-config corpus from two sources — `batfish/lab-validation` + `ios-xr/xrd-tools` SR/SRv6/IS-IS) |
| `arista_eos`      | Arista EOS    | switch | EOS CLI text              | bidirectional | certified |
| `aruba_aoss`      | Aruba AOS-S   | switch | AOS-S CLI banner + positional port lists | bidirectional | certified |
| `aruba_aoscx`     | Aruba AOS-CX  | switch | `show running-config` text | bidirectional | certified (all 4 phases — hostname + interfaces (multi-token names `interface vlan 11` / `lag 1` / `1/1/1`; L3 + L2 switchport `no routing` / `vlan access` / `vlan trunk`) + VLANs (id/name/description + port projection) + LAGs (`interface lag` + `lacp mode`) + local users + SNMP (community / system-location / system-contact / v3 USM) + `active-gateway` anycast (VSX/EVPN distributed gateway) + top-level `vrf` + default-VRF static + VXLAN L2 VLAN↔VNI binding (`interface vxlan` / `vni` / `vlan`); round-trip-validated against a 4-config `aruba/aoscx-ansible-dcn-workflows` corpus (VXLAN leaves + active-gateway cores) on AOS-CX 10.04 / 10.13; per-VLAN L2VNI RD/RT + symmetric-IRB L3VNI + VSX + VRRP remain unsupported) |
| `juniper_junos`   | Juniper Junos | switch | `set`-form CLI            | bidirectional | certified |
| `fortigate_cli`   | Fortinet FortiGate | firewall | nested `config / edit / set / next / end` CLI | bidirectional | certified |
| `mikrotik_routeros` | MikroTik RouterOS | router | `/path` slash-prefixed CLI export | bidirectional | certified |
| `opnsense`        | OPNsense      | firewall | `config.xml`              | bidirectional | certified |
| `vyos`            | VyOS          | router | `config.boot` curly-brace **or** `set`-form text | bidirectional | certified (Phases 1-6 — `system host-name` + ethernet / loopback / dummy interfaces (address IPv4+IPv6 CIDR / `dhcp` / description / `disable` / mtu) + `vif` VLAN sub-interfaces (`ethN.<vid>`) + `protocols static` routes + `system login` local users + `system`/`service` ntp servers (bare + 1.4 block form) + `bonding` LAGs (`mode 802.3ad` LACP + both member forms) + `service snmp` (v1/v2c community / location / contact + v3 USM users) + VRF (`vrf name` routing-instances + per-interface `vrf` binding) + `interfaces vxlan` netdevs (one VNI each — vni / source / mcast or remote / port); round-trip-validated against a 10-config real corpus from 4 sources spanning VyOS 1.3/1.4/1.5 (`cisagov/prescup-challenges` MIT IPv4/OSPF + IPv6/BGP, `zhouleyan/wcni-kind` Apache-2.0 VXLAN pair, `scottlaird/vyos-parser` + `rapid7/metasploit-framework` for `service snmp`); accepts BOTH the native curly-brace `config.boot` AND `set`-form input (`show configuration commands`, converted to curly-brace up front; the probe disambiguates VyOS set-form from the `set`-form `juniper_junos` codec); per-VRF static routes + symmetric-IRB L3VNI remain later phases) |
| `dell_os10`       | Dell SmartFabric OS10 | switch | `show running-configuration` text | bidirectional | best_effort (all 4 phases wired — hostname + interfaces (three-segment `ethernet1/1/1` naming + `ethernet1/1/10:1` breakout subports; L3 CIDR + `ip vrf forwarding` + L2 switchport/`channel-group`) + SVI-derived VLANs (OS10 has no top-level `vlan <id>` stanza) + `port-channel` LAGs + local users (real numeric `priv-lvl`) + SNMP v2c/v3 USM with the per-line `localized` marker + real VRRP; validated against 14 real OS10 captures that all parse cleanly and round-trip canonical-stable, plus a committed synthetic kitchen sink and full mesh coverage.  `best_effort` rather than `certified` because those captures carry live password hashes and are held out-of-tree, so no REAL corpus is committed; VXLAN/EVPN (`virtual-network`), VLT and QoS/DCB remain unsupported) |

Backup-side device-definition YAMLs ship for every codec family above
(plus per-OS-version overlays).  Cisco and Aruba each span two NOSes with
separate definitions — `Cisco` (IOS-XE) + `CiscoNXOS` + `CiscoIOSXR`, and
`Aruba` (AOS-S) + `ArubaCX` (AOS-CX) — keyed distinctly because `type_key`
must be unique.  **`CiscoNXOS`, `CiscoIOSXR`, and `ArubaCX` are
provisional**: their backup wiring is verified in code and against sample
`show version` output, but has not yet been run against a live device —
the `/definitions` Notes column flags each with a "NOT YET VALIDATED"
warning.  (`VyOS` was provisional too until it was live-validated against a
real VyOS rolling instance — backup run end-to-end — and graduated.)  See
[`../netcanon/definitions/library/README.md`](../netcanon/definitions/library/README.md) for the
authoring guide and the live `/definitions` page in the running app
for the per-vendor inventory.  RESULTS.md is the source of truth for
current certification — this table summarises but does not gate.

> **Certified ≠ deploy-ready.**  The `certainty` label rates *round-trip
> fidelity* (how reliably a config survives parse → render), not deploy
> automation.  Netcanon has no deploy path today — rendered output is for
> manual review and apply; the deploy endpoints remain on the roadmap.

---

## Translation tiers

The canonical intent model classifies every field by semantic
stability across vendors.  This drives both the validation report and
the UI's notification banners.

### Tier 1 — auto-translatable (cross-vendor stable)

Modelled and wired across the shipped bidirectional codecs.  Most leaves
round-trip cleanly on every codec; a few carry documented per-codec
exceptions (e.g. `tunnel_type` is **lossy** on FortiGate — FortiOS expresses
tunnels in separate top-level sections, not as an encap discriminator on a
tunnel interface; `mtu` is unsupported on Aruba AOS-S, which has no per-port
MTU concept).  The per-codec tables under
[§A](#a-capability-matrix-unsupported--lossy-panels) are the source of
truth for which leaves are lossy/unsupported on which codec; this list
names the canonical surface, not a blanket guarantee.

* `hostname`, `domain`
* `interfaces` — `name`, `description`, `enabled`, IPv4 + IPv6
  addresses, `vrf` binding, `kind` (physical / mgmt / loopback /
  uplink), `mtu`, `lag_member_of`, `dhcp_client_v6` (IPv6 DHCPv6 /
  SLAAC mode discriminator), `tunnel_type` (GRE / EoIP / IPIP /
  IPSEC / VXLAN encap discriminator)
* `vlans` — `id`, `name`, `tagged_ports`, `untagged_ports`, SVI L3
  (via VLAN-centric projection)
* `static_routes` — `destination`, `gateway`, `interface`, `metric`,
  `description`; plus per-VRF `vrf` discriminator (v0.2.0 Wave A —
  see Tier 2 ship-before-wire note below)
* `dns_servers`, `ntp_servers` — wired on most codecs (the two Cisco
  SP/DC codecs cisco_nxos and cisco_iosxr, which historically render-
  dropped the management plane, now wire it — promotions #4/#13); plus
  `syslog_servers` and `timezone`, which are wired on only a **subset**
  of codecs: `timezone` on none as of this release; `syslog_servers` on
  juniper_junos, cisco_iosxe_cli, arista_eos (`logging host <ip>`,
  promotions #1/#11), cisco_nxos (`logging server <ip>`, #4) and
  cisco_iosxr (bare `logging <ip>`, #13).  These are
  Tier-1 by data shape but NOT yet a cross-vendor guarantee — the §A
  per-codec panels are authoritative.  An unwired field is dropped on
  parse and surfaces the cross-vendor banner where the codec declares it
  unsupported; for `syslog_servers` and `timezone` every codec declares
  the path (`syslog_servers` 5 supported + 7 unsupported, `timezone`
  unsupported on all 12), so those drops are always bannered, never silent.
* `interfaces[].vrrp_groups` (v0.2.0 Wave B — classic FHRP
  redundancy, mode discriminator `vrrp` / `hsrp` / `carp`) — wired
  across the bidirectional codecs.  See
  [`v0.2.0-planning/01-vrrp-canonical/`](v0.2.0-planning/01-vrrp-canonical/)
  for the design rationale and the
  [Cross-vendor L3-redundancy grammar reference](#cross-vendor-l3-redundancy-grammar-reference)
  section below for the per-vendor mapping table.

### Tier 2 — translatable with caveats

Modelled and wired across most codecs; cross-vendor mappings can be
lossy where vendors disagree on representation.

* `snmp` — community, contact, location, trap-host, plus SNMPv3 USM
  users (auth/priv/group/engine — see per-codec notes below)
* `lags` — name, mode (LACP / static), members; vendor-native names
  reconciled via the LAG name-equivalence helper (`Po1` /
  `Port-channel1` / `ae1` / `trk1` are recognised as the same bundle)
* `local_users` — name, privilege, role, hashed_password.  Hashes
  that the target's CLI cannot consume surface as comment-form
  review lines (see "Hash-portability policy" below) — **never** as
  a plaintext fallback
* `radius_servers`
* `dhcp_servers` (per-pool — network, gateway, range, options)
* `vxlan_vnis`, `evpn_type5_routes` (shipped schema-first; `vxlan_vnis`
  is now wired `supported` on `arista_eos`, `cisco_nxos`,
  `aruba_aoscx`, `vyos`, `cisco_iosxe_cli` — the per-codec §A tables
  are authoritative; `evpn_type5_routes` stays lossy-by-default on
  every codec)
* `routing_instances` + per-interface `vrf` (cross-vendor VRF
  primitive — schema-first, now wired on multiple codecs; see the
  per-codec §A tables)
* `static_routes[].vrf` (v0.2.0 Wave A — per-VRF route
  discriminator; wired `supported` on `juniper_junos`, `arista_eos`,
  `cisco_iosxe_cli`, `cisco_nxos`, `cisco_iosxr`)
* `interfaces[].ipv4_addresses[].virtual_gateway_address` /
  `virtual_gateway_mac` / `is_secondary` and the matching IPv6
  fields (v0.2.0 Wave C — anycast-gateway companion to the primary
  IP).  Distinct from VRRP: anycast is an IP-address property, not
  a router-group election.  Wired as `supported` on Junos
  (`virtual-gateway-address`), Arista EOS (VARP `ip address
  virtual`), and Cisco IOS-XE CLI (SD-Access `fabric forwarding
  mode anycast-gateway`, IPv4 only).  IPv6 anycast on IOS-XE
  remains `unsupported` (parses-and-ignores; no fixture coverage
  today).  See
  [`v0.2.0-planning/02-anycast-gateway/`](v0.2.0-planning/02-anycast-gateway/)
* `anycast_gateway_mac` (v0.2.0 Wave C — chassis-wide system MAC
  for Arista `ip virtual-router mac-address`, Cisco SD-Access
  `fabric forwarding anycast-gateway-mac`).  Junos `unsupported`
  by design (per-IRB-unit MAC overrides flow through the per-
  address `virtual_gateway_mac` field instead).
* `apply_groups` + `group_content` (Junos-specific; preserved
  byte-for-byte through round-trip)

### Tier 3 — opaque carry / not auto-rendered

These are present in source devices but **never auto-translated**.
The codec parsers deliberately drop them; the
[`_tier3_detection.py`](../netcanon/migration/_tier3_detection.py)
heuristic surfaces what was dropped via the migrate page banner so
operators see the gap.

* `firewall_rules` — vendor-specific stateful policy; cross-vendor
  semantics don't translate cleanly (zone-pair vs interface ACL vs
  table-driven rule sets)
* `nat_rules` — tightly coupled to interface zone designations
* `vpn` — IPsec / SSL-VPN / WireGuard / OpenVPN; key material and
  peer-specific knobs aren't safely auto-portable
* `routing_protocols` — BGP / OSPF / EIGRP / IS-IS;
  protocol-internal state belongs to the operator, not the
  translator
* QoS — class-maps / policy-maps / shapers / queues
* PKI / crypto — certificate chains, IKE policies, key blobs
* Route-maps / policy-statements / prefix-lists

This is an architectural decision, not a backlog item.  See the
"Architectural decision (Cluster E.X deferred)" entry in
[`../CHANGELOG.md`](../CHANGELOG.md) for the rationale.

---

## Notification mechanisms operators see

The UI surfaces every place the translator can't faithfully cross
the vendor boundary.  Each surface is named so operators can grep
the rendered output or screen-grab the panel.

### A. Capability matrix "Unsupported" / "Lossy" panels

The migrate page renders three lists under **Validation details**:
Supported / Lossy / Unsupported.  Each codec declares its own matrix
in `netcanon/migration/codecs/<vendor>/codec.py`.

> **Authoritative source:** the live capability matrices in
> `netcanon/migration/codecs/<vendor>/codec.py` (surfaced verbatim by the
> `/api/v1/definitions` endpoint and the migrate page's Validation panel)
> are the single source of truth.  The per-codec tables below are a
> hand-maintained **illustrative digest** of the most operator-relevant
> lossy / unsupported paths with their rationale — they are NOT a complete
> enumeration and may lag the code between releases.  When a table and the
> live matrix disagree, the live matrix wins.

#### `cisco_iosxe_cli` (Cisco IOS-XE CLI, bidirectional)

A banner, and every other text written between two delimiters (`aaa
authentication banner`, a `menu` title, a `busy-message`, a line's
`vacant-message` and a web authentication banner at any indentation),
and a `macro name`, is text and is not read as configuration: a banner
ends at the next occurrence of its delimiter anywhere, a macro at a
line that is `@`.  One with no end, a line of one that ends in a form
feed or the like, and a `^C` left outside every banner because a
banner's own text held it are refused; a text that holds `^C` and then
opens another banner is not seen (see
[`vendors/cisco_iosxe.md`](vendors/cisco_iosxe.md) § "A banner is
text").

| Path | Class | Reason summary |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Supported (Wave B) | Parses the `vrrp <vrid> ip|ipv6|priority|preempt|description|authentication|track|timers` family inside `interface` stanzas; renders the classic single-line per-attribute form (broadest IOS-XE compatibility, 15.x onward). |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Lossy (Wave C) | SD-Access anycast-gateway (`virtual_gateway_address == the interface primary IP`) round-trips via `fabric forwarding mode anycast-gateway`, but a SEPARATE cross-vendor VARP virtual IP (the Arista/Junos shape, `virtual_gateway_address != the interface IP`) has no IOS-XE equivalent and drops on render (review comment only).  Demoted from supported to **lossy** so the separate-VIP loss surfaces instead of reporting `severity:ok` (silent-loss guard). |
| `/anycast-gateway-mac` | Supported (Wave C) | Top-level `fabric forwarding anycast-gateway-mac <MAC>` round-trips between Cisco dotted-triplet wire form (`0001.c73a.0000`) and canonical colon-hex. |
| `/interfaces/interface/vrrp-groups/group/address-family` | Lossy (Wave B) | IOS-XE 17.12+ modern multi-line `vrrp <VRID> address-family ipv4` nested block is detected (so lossiness is visible) but not deep-populated; render always emits the classic single-line form (accepted by every IOS-XE 15.x+).  A config that uses ONLY the modern AF form round-trips as an empty group shell — the lossiness is intentional and operator-visible. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | IPv6 SD-Access anycast parses-and-ignores in v1.  Corpus has zero fixtures exercising it; wire-up deferred until demand arrives.  IPv4 SD-Access anycast IS supported (row above). |
| `/routing/static-route/vrf` | Supported (v0.2.0) | Per-VRF static routes: `ip route vrf <NAME> <dest> <mask> <gw>` round-trips through parse + render onto `CanonicalStaticRoute.vrf`.  Administrative-distance is harvested onto `metric` (and re-emitted) and a trailing `name <X>` onto `description`; only the `global` route-leak / `tag` / `track` tokens are not modelled and parse-and-ignore. |
| `/interfaces/interface/config/type` | Lossy | CLI parser infers IANA type from name prefix (GigabitEthernet → ethernetCsmacd, Loopback → softwareLoopback) but cannot detect all IANA types. |
| `/evpn-type5-routes/route` | Lossy | Per-prefix EVPN Type-5 records are a VRF property; no codec populates them today (lossy-by-default extension point). |
| `/interfaces/interface/subinterfaces/subinterface/ipv6` | Unsupported | Phase 0.5 scope — IPv4 only. |
| `/vxlan-vnis/{vni,source-interface,mcast-group}` | Supported (#351) | IOS-XE VXLAN-EVPN L2 VNI: `interface nve1` VTEP + `member vni <V>` + `vlan configuration` VLAN↔VNI binding round-trips through parse + render; `/routing-instances/instance/l3-vni` is supported too. |
| `/vxlan-vnis/{udp-port,flood-list}` | Lossy | The nve1 render keeps the VNI identity but normalizes the UDP port and drops head-end static ingress-replication flood peers (no IOS-XE grammar in v1). |
| `/routing-instances/instance` | Lossy | VRF declarations parse and render bidirectionally (`parse._parse_routing_instances` → `vrf definition` emit loop; cross-vendor confirmed via Wave 10β-B / commit `40de39c`).  Lossy because `address-family ipv6` / EVPN `l2vpn evpn` sub-stanzas inside `vrf definition` are parse-and-ignore in v1.  (Per-VRF static-route membership now round-trips via the supported `/routing/static-route/vrf` surface above.) |
| `/access-list/{extended,standard,ipv6}` | Unsupported | Tier 3 — auto-translating ACL semantics across vendors risks shipping subtly-permissive rules. |
| `/snmp/v3-user/auth-passphrase` | Lossy | `snmp-server user <n> <grp> v3 auth <proto> <value>` takes the operator's passphrase and IOS-XE derives the localised USM key from it, so a value that is already another agent's key cannot be re-derived: the render refuses it (review comment, no `snmp-server user` line) rather than deriving a key from a key.  A source passphrase is portable and is emitted unchanged.  The optional `encrypted` keyword (`v3 encrypted auth …`, per the Cisco command reference) IS parsed: it marks the value as the stored, already-derived key, and it is re-emitted behind the same keyword so the device does not re-derive it. |
| `/snmp/v3-user/priv-passphrase` | Lossy | Same as the auth key — refused with the user unless it is a portable passphrase or came from IOS-XE itself. |
| `/firewall` | Unsupported | Zone-based firewall (zone-pair / policy-map type inspect) is Tier 3. |
| `/nat` | Unsupported | NAT is Tier 3 — semantics are tightly coupled to interface zone designations. |

#### `cisco_iosxe` (NETCONF / OpenConfig, bidirectional Phase 0.5 stub)

This codec is an experimental stub — its `_render_canonical()`
emits **only the `openconfig-interfaces` subtree**.  Every other
canonical surface is declared `unsupported` so the cross-mesh audit
matrix flags the gap honestly rather than masquerading as drift.

| Path (granular) | Class |
|---|---|
| `/interfaces/interface/config/mtu` | Lossy (YANG MTU drops platform-specific IP-vs-link distinction) |
| `/system/{hostname,dns-server,ntp-server}` | Unsupported |
| `/vlans/vlan/{id,name}` | Unsupported |
| `/routing/static-route` | Unsupported |
| `/routing/static-route/vrf` | Unsupported (ship-before-wire v0.2.0; schema present but stub renders interfaces only) |
| `/snmp/{community,location,contact,trap-host,v3-user}` | Unsupported |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported |
| `/routing-instances/instance` | Unsupported |
| `/evpn-type5-routes/route` | Unsupported |
| `/interfaces/interface/vrrp-groups/group` | Unsupported (ship-before-wire v0.2.0 Wave B; stub renders interfaces only) |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Unsupported (ship-before-wire v0.2.0 Wave C) |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported (ship-before-wire v0.2.0 Wave C) |
| `/anycast-gateway-mac` | Unsupported (ship-before-wire v0.2.0 Wave C) |
| `/access-list`, `/firewall` | Unsupported (Tier 3) |

Top-level field markers (`/hostname`, `/domain`, `/dns_servers`,
`/ntp_servers`, `/timezone`, `/syslog_servers`, `/vlans`,
`/static_routes`, `/snmp`, `/lags`, `/local_users`, `/radius_servers`,
`/dhcp_servers`, `/routing_instances`, `/vxlan_vnis`,
`/evpn_type5_routes`) are also declared unsupported so the cross-mesh
audit's `f"/{field}"` shape match flips correctly.  Operators
selecting this codec as a target should expect interfaces-only
output.

#### `arista_eos` (bidirectional)

A text with no indentation is REFUSED in words rather than
mis-parsed: the parser reads a stanza by its indentation, and reading
such a text as the switch is inferred to (by the mode each command
leaves open) would need every mode's words, which no Arista page
lists.  A banner, and every other body that Arista's tools end at an
`EOF` line (a `comment`, RCF code, a multi-line `action bash`, a
certificate and its key), is text and is never read as
configuration; a body with no `EOF`, or with a line that ends in a
form feed or the like, is refused.  `router bgp` is read
by relative depth, so tabs and other widths read as EOS's own (see
[`vendors/arista_eos.md`](vendors/arista_eos.md) § "Common
gotchas").

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Supported (Wave B) | Classic VRRP parses `vrrp <N> ipv4 <VIP>` + multi-line modern `vrrp <N> { ip address, priority, preempt, advertisement-interval }` and renders the multi-line modern form. |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Supported (Wave C) | VARP: `ip address virtual X/M` populates the address record's `virtual_gateway_address`; secondary trailer preserved via `is_secondary` flag. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Supported (Wave C) | IPv6 VARP: `ipv6 address virtual` parses to the IPv6 address record. |
| `/anycast-gateway-mac` | Supported (Wave C) | Chassis-wide `ip virtual-router mac-address <MAC>` round-trips to `CanonicalIntent.anycast_gateway_mac`. |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | Lossy (Wave C) | EOS only supports one chassis-wide virtual-router MAC; per-IP MAC overrides (Junos `virtual-gateway-v4-mac`) drop on render — cross-vendor sources carrying per-IP MACs surface a review banner so the operator can either consolidate to a single system-wide MAC or pick a vendor target that preserves per-IP overrides. |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | Lossy (Wave C) | Mirror of the IPv4 case — EOS shares one system-wide MAC across IPv4 and IPv6 anycast. |
| `/routing/static-route/vrf` | Supported (#340) | Per-VRF static routes (`ip route vrf <NAME> …`) round-trip onto `CanonicalStaticRoute.vrf`; interface-nexthop (`… <iface>`, e.g. `Null0`) is supported too (#342). |
| `/interfaces/interface/config/type` | Lossy | EOS interface names don't encode speed; parser defaults `Ethernet<N>` to a `gig` speed-hint and target codecs that care about speed (e.g. Cisco's GigabitEthernet vs TenGigabitEthernet distinction) may emit less-specific prefixes. |
| `/evpn-type5-routes/route` | Lossy | Per-prefix records are a lossy-by-default extension point — no codec populates them today (would require route-map / policy-statement parsing). |
| `/snmp/v3-user/auth-passphrase` | Lossy | `snmp-server user … auth <proto> <value>` takes the operator's PASSPHRASE and EOS derives the localised key from it at commit, so a value that is already another agent's key cannot be re-derived: the render refuses it (review comment, no `snmp-server user` line) rather than feeding a digest through key derivation.  A source passphrase is portable and is emitted unchanged.  EOS's own ENGINE clause (`v3 localized <engineID> auth …`) IS parsed: the key is recorded as already-localised and re-emitted behind the same clause, since writing it into the bare passphrase slot would make EOS derive a key from a key.  Grammar per the EOS command reference; no committed fixture carries the clause. |
| `/snmp/v3-user/priv-passphrase` | Lossy | Same as the auth key — the privacy value is refused with the user unless it is a portable passphrase or came from EOS itself; re-key the v3 user on the target. |
| `/routing/bgp` | Unsupported | BGP neighbour tables / redistribution / address-families parse-and-ignore in v1. |
| `/routing/ospf` | Unsupported | OSPF areas / redistribution / per-interface cost tuning parse-and-ignore in v1. |
| `/access-list/{extended,standard,ipv6}` | Unsupported | Tier 3 — auto-translating ACL semantics across vendors risks shipping subtly-permissive rules. |

#### `aruba_aoss` (bidirectional)

A banner -- printed as a double-quoted string across lines, ended by
the first quote no backslash escapes -- is text and is not read as
configuration, by the parser or the deployment detector.  One with no
end, with text after its closing quote, or with a line that ends in a
form feed or the like is refused, and so is a later line with an odd
number of quotes (the quote a banner's own text held ended it early);
a text whose quotes leave no such line is not seen (see
[`vendors/aruba_aoss.md`](vendors/aruba_aoss.md) § "A banner is
text").

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Supported (Wave B) | Parses + renders a global `router vrrp` enable + `vrrp vrid <N> / owner\|priority / virtual-ip-address <Y> / preempt / enable` inside `vlan N` stanzas (AOS-S binds VRRP to the SVI's VLAN, not the L3 interface). The `vrrp vrid` header carries **no** `ip` prefix per the AOS-S 16.10 CLI reference; the legacy `ip vrrp vrid` form is still accepted on parse. `owner` maps to the canonical priority 255 (the RFC 5798 address-owner value — the full 0-255 range is now representable, and render inverts 255 back to `owner`). |
| `/interfaces/interface/vrrp-groups/group/virtual-ips` | Lossy (Wave B) | AOS-S `virtual-ip-address` accepts only ONE address per vrid; cross-vendor migration from Cisco IOS-XE secondaries or Junos `virtual-address [ list ]` drops the tail with a review comment. |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Unsupported | AOS-S has no anycast-gateway grammar (campus L2/L3 codec). |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | Same as IPv4 — no native anycast grammar. |
| `/anycast-gateway-mac` | Unsupported | AOS-S has no chassis-wide anycast MAC concept. |
| `/routing/static-route/vrf` | Unsupported | Per-VRF static-route binding parses-and-ignores in v1. |
| `/interfaces/interface/config/type` | Lossy | AOS-S does not declare IANA `ifType`; codec infers type from interface-name shape (bare number → ethernet, `Trk` → port-channel, `Vlan` → l3ipvlan). |
| `/filter/rule` | Unsupported | AOS-S access-lists are Tier 3 (informational) and not yet auto-rendered. |
| `/snmp/v3-user/auth-passphrase` | Lossy | `snmpv3 user "<n>" auth <proto> "<value>"` takes the operator's passphrase and AOS-S derives the localised USM key from it, so a value that is already another agent's key cannot be re-derived: the render refuses it (review comment, no `snmpv3 user` line, and the `snmpv3 group` binding drops with it) rather than deriving a key from a key.  A source passphrase is portable and is emitted unchanged. |
| `/snmp/v3-user/priv-passphrase` | Lossy | Same as the auth key — refused with the user unless it is a portable passphrase or came from AOS-S itself; re-key the v3 user on the target. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | VXLAN not modelled — AOS-S is a campus L2/L3 codec. |

#### `juniper_junos` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Supported (Wave B) | Parses + renders `set interfaces irb unit N family inet address X vrrp-group <N> { virtual-address Y, priority, preempt }`.  Both classic IPv4 and IPv6 (`vrrp-inet6-group`) wire-up landed. |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Supported (Wave C) | One-line `set interfaces irb unit N family inet address X virtual-gateway-address Y` stores both pieces on the same `CanonicalIPv4Address` record. |
| `/interfaces/interface/ipv4/address/virtual-gateway-mac` | Supported (Wave C) | Per-IRB-unit `virtual-gateway-v4-mac M` populates the per-address MAC override. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Supported (Wave C) | IPv6 form: `family inet6 address X virtual-gateway-address Y`. |
| `/interfaces/interface/ipv6/address/virtual-gateway-mac` | Supported (Wave C) | `virtual-gateway-v6-mac M`. |
| `/routing/static-route/vrf` | Supported (v0.2.0) | `set routing-instances <NAME> routing-options static route <dest> next-hop <gw>` harvests onto `CanonicalStaticRoute.vrf` and renders back out (the routing-instances dispatcher now descends into `routing-options static`).  Top-level `set routing-options static route` lines round-trip with `vrf=""`.  next-hop form only — `discard` / `reject` blackhole routes and the explicit `rib <name>` form (e.g. IPv6 `inet6.0`) are not modelled, same as the global table; a VRF implied solely by a static route does not materialise an empty routing-instance. |
| `/anycast-gateway-mac` | Unsupported | Junos has no chassis-wide anycast-gateway MAC; per-IRB-unit overrides live on `CanonicalIPv4Address.virtual_gateway_mac` (the `virtual-gateway-v4-mac` / `-v6-mac` grammar) and round-trip through the supported per-address surface instead.  Cross-vendor migration from a source carrying a system-wide MAC (Arista, NX-OS) must distribute the value across every IRB unit's per-address MAC on the receiving Junos side. |
| `/interfaces/interface/subinterfaces/subinterface` | Lossy | Unit 0 collapses into the parent; units 1+ materialise as distinct `<parent>.<unit>` interfaces, and per-unit 802.1Q tagging (`unit N vlan-id`) is captured on `/interfaces/interface/dot1q-vlan` (GAP 7 — round-trips). Per-unit subinterface attributes beyond the address + 802.1Q tag remain unmodelled. |
| `/groups` | Lossy | Apply-groups inheritance is wired for the dispatch surface (system / login / interfaces / protocols / SNMP / routing-options / routing-instances / vlans); group bodies for unsupported surfaces (policy-options, firewall filters, RADIUS server options) parse-and-ignore. |
| `/evpn-type5-routes/route` | Lossy | Per-prefix records lossy-by-default — VRF-property model uses `CanonicalRoutingInstance.l3_vni`; explicit per-prefix lists not populated by any codec today. |
| `/snmp/v3-user/auth-passphrase` | Lossy | `authentication-key` holds the value Junos itself stored for one of its own keys, so a key produced by another agent cannot be written there: the render refuses it (review comment, and the user's VACM `security-to-group` binding is dropped with it) rather than emitting a key that authenticates nobody.  A source PASSPHRASE is portable and is routed through `authentication-password`, from which Junos derives the key on commit, and the parser reads that leaf back.  The parser also records WHICH leaf carried the value, so a Junos config that stores a passphrase in `authentication-password` now classifies as portable and migrates, instead of failing closed because the kind was inferred per-codec. |
| `/snmp/v3-user/priv-passphrase` | Lossy | Same as the auth key — a foreign privacy key is refused with the user, and a portable passphrase is routed through `privacy-password` instead of `privacy-key`. |
| `/routing/bgp` | Unsupported | BGP / IS-IS / OSPF / MPLS stanzas parse-and-ignore in v1; Junos routing-options grammar warrants a dedicated follow-up. |
| `/firewall/filter` | Unsupported | Junos firewall filters (family / term / from / then) are Tier 3 — distinct from ACL models in other codecs. |

#### `fortigate_cli` (bidirectional) — L2/L3 layer only (firewall policy is Tier 3, never translated)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Supported (Wave B) | Nested-edit form: `config system interface / edit X / config vrrp / edit <N> / set vrip Y / set priority / set preempt enable / set vrdst <iface>`. |
| `/interfaces/interface/vrrp-groups/group/virtual-ips` | Lossy (Wave B) | FortiOS `config vrrp / edit N` accepts a single `set vrip` per group.  Multi-IP canonical groups (IOS-XE repeated `vrrp N ip X`, Junos `virtual-address [ X Y Z ]`) emit the first VIP and drop the tail with a `# review:` line — operator must split into multiple groups manually. |
| `/interfaces/interface/vrrp-groups/group/virtual-mac` | Lossy (Wave B) | FortiOS uses `set vrrp-virtual-mac enable/disable` as an interface-wide toggle (defaults to disable, meaning FortiOS uses its own NPU MAC instead of `00:00:5E:00:01:VRID`).  The canonical `virtual_mac` per-group override has no FortiOS equivalent and is silently dropped — cross-vendor renders into FortiGate cannot pin a custom VRID MAC at the group level. |
| `/interfaces/interface/vrrp-groups/group/track-interfaces` | Lossy (Wave B) | FortiOS `set vrdst <iface>` accepts a single destination-tracking entry per group.  Multi-track canonical groups (IOS-XE `track` objects, Arista `vrrp N track Ethernet1 decrement 10`) emit the first and drop the rest.  The decrement value is also lossy — FortiOS vrdst is a binary up/down trigger, not a priority-decrement scheme. |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Unsupported | FortiGate is an edge firewall with no native anycast surface (HA is delivered via VRRP groups, not anycast-MAC fabrics).  **Cross-vendor consequence:** Junos→FortiGate anycast translation DROPS the data with a review banner. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | Same as IPv4 — FortiGate has no anycast grammar. |
| `/anycast-gateway-mac` | Unsupported | No chassis-wide anycast MAC concept. |
| `/routing/static-route/vrf` | Unsupported | Per-VRF static-route binding parses-and-ignores in v1. |
| `/interfaces/interface/config/description` | Lossy | FortiOS limits the interface alias to 25 characters; longer descriptions from other vendors are truncated. |
| `/interfaces/interface/config/type` | Lossy | FortiOS has no IANA `ifType`; inferred from `type vlan` sub-setting or name shape. |
| `/filter/rule` | Unsupported | `config firewall policy` is Tier 3 — session-based, zone-aware, UTM-enabled semantics don't translate cleanly. |
| `/snmp/v3-user/auth-passphrase` | Lossy | `set auth-pwd "ENC <v>"` claims the value is encrypted under this FortiGate's key, true only of a value this device produced, so a key belonging to another agent is refused (review comment, no `edit` block).  A source passphrase is portable and is emitted WITHOUT the `ENC` prefix, which is how an operator types one and FortiOS encrypts it on save. |
| `/snmp/v3-user/priv-passphrase` | Lossy | Same as the auth key — a foreign privacy key is refused with the user; a portable passphrase is emitted without the prefix. |
| `/nat/rule` | Unsupported | FortiGate NAT lives inside firewall policy and address / VIP objects — not auto-translatable. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | VXLAN not modelled — FortiGate is a firewall codec. |

#### `mikrotik_routeros` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Supported (Wave B) | Top-level section dispatcher: `/interface vrrp add interface=ether1 vrid=10 priority=110 v3-protocol=ipv4` + `/ip address add address=Y/24 interface=vrrp10`.  Cross-vendor tracking and authentication surfaces emit review comments rather than dropping silently. |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Unsupported | RouterOS has no anycast-gateway grammar. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | Same as IPv4 — no native anycast grammar. |
| `/anycast-gateway-mac` | Unsupported | No chassis-wide anycast MAC concept. |
| `/routing/static-route/vrf` | Unsupported | Per-VRF static-route binding parses-and-ignores in v1. |
| `/interfaces/interface/config/type` | Lossy | RouterOS does not expose IANA `ifType`; codec infers it from interface-name prefix (`etherN` → ethernetCsmacd, `vlanN` → l3ipvlan). |
| `/vlans/vlan/name` | Lossy | MikroTik stores a VLAN's name as the L3 interface name (e.g. `vlan10`), not a separate descriptive name field; cross-vendor rendering may conflate the two. |
| `/vlans/vlan/description` | Lossy | RouterOS exposes a single per-VLAN `comment` field, which the parser maps to the VLAN name; a separate description collides with it on render. |
| `/filter/rule` | Unsupported | Firewall filter rules are Tier 3 (informational) and not auto-rendered. |
| `/snmp/v3-user/auth-passphrase` | Lossy | `authentication-password=` takes the operator's passphrase and RouterOS derives the localised USM key from it, so a value that is already another agent's key cannot be re-derived: the render refuses it (review comment, no `add name=` line).  A source passphrase is portable and is emitted unchanged. |
| `/snmp/v3-user/priv-passphrase` | Lossy | Same as the auth key — refused with the user unless it is a portable passphrase or came from RouterOS itself. |
| `/nat/rule` | Unsupported | NAT rules are Tier 3 — informational only. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | RouterOS VXLAN exists but is rare in canonical scope and not modelled in v1. |

#### `opnsense` (bidirectional) — L2/L3 layer only (firewall policy is Tier 3, never translated)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/vrrp-groups/group` | Lossy (Wave B, CARP variant) | Hosts CARP-only HA groups via `<virtualip><vip><mode>carp</mode><vhid>N</vhid>…</vip></virtualip>` with a `mode="carp"` discriminator on the canonical record.  Lossy because `CanonicalVRRPGroup` records with `mode="vrrp"` or `mode="hsrp"` are SKIPPED on render — OPNsense has no native HSRP wire protocol, and its pure-VRRP mode under `<virtualip>` is rarely deployed and not yet emitted; only `mode="carp"` round-trips.  Additionally, the `advskew`↔`priority` mapping (`priority = 254 - advskew`) preserves relative HA-pair ordering but not exact election timing. |
| `/interfaces/interface/ipv4/address/virtual-gateway-address` | Unsupported | OPNsense uses CARP for HA (distinct semantics); no anycast-gateway grammar. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | Same as IPv4 — no native anycast grammar. |
| `/anycast-gateway-mac` | Unsupported | No chassis-wide anycast MAC concept. |
| `/routing/static-route` (and `gateway` / `metric` / `description` / `interface`) | Unsupported | The parser harvests routes from `<gateways>` + `<staticroutes>`, so OPNsense-as-**source** translates outward fine — but the `config.xml` renderer emits neither block, so a route translated **into** OPNsense does not survive at all.  A record that vanishes is unsupported, not lossy: validation reports `block`, and an X→OPNsense plan tells the operator to re-create routing on the target rather than warning them past it. |
| `/routing/static-route/vrf` | Unsupported | Separate rationale from the render gap above: OPNsense's `config.xml` has no VRF model at all, so a per-VRF binding parses-and-ignores and stays unsupported even once `<staticroutes>` rendering lands. |
| `/interfaces/interface/config/description` | Lossy | OPNsense imposes no length limit on description text; other vendors (Cisco 240 chars, Juniper 900) may truncate on render. |
| `/dhcp-servers/pool` | Lossy | A pool is keyed by the zone of its interface.  A pool whose interface is no interface of the output serves nothing there (an EOS pool, whose own name is where its interface goes, is written under a zone of that name, `<users>`); one that names no interface (a pool from IOS-XE or RouterOS, a Junos pool whose server group binds no interface) is written under `<lan>`, a zone the output has only if an interface is called that.  Read back, such a pool is left out.  The report lists this path for every pool written onto OPNsense, a bound one included.  As a **source**, a pool is on the device its zone is assigned to, and a pool whose zone `<interfaces>` does not have is left out and listed. |
| `/filter/rule` | Unsupported | `<filter>` is Tier 3. |
| `/nat/outbound` | Unsupported | `<nat>` is Tier 3. |
| `/snmp/v3-user` | Unsupported | OPNsense's SNMPv3 lives in raw `snmpd.conf` — Tier 3. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | VXLAN not modelled — OPNsense is a firewall codec. |

#### `cisco_nxos` (Cisco NX-OS, bidirectional, certified)

Broad supported surface (L1/L3 + L2 switchport/LAG + SNMP/local-users +
HSRP + VRF RD/RT + per-VRF static + VXLAN-EVPN/L3VNI + IPv4 Distributed
Anycast Gateway).  A banner, ended at the next occurrence of its
delimiter anywhere, and a `scheduler job`'s commands, ended by a line
`end-job`, are text and are not read as configuration; one with no
end, or with a line that ends in a form feed or the like, is refused
(see [`vendors/cisco_nxos.md`](vendors/cisco_nxos.md) § "A banner is
text").  The lossy / unsupported exceptions:

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | Interface-type inferred from the name prefix (Ethernet → ethernetCsmacd, loopback → softwareLoopback, Vlan → l3ipvlan, port-channel → ieee8023adLag, nve → tunnel, mgmt → ethernetCsmacd).  Best-effort; may not catch every IANA type. |
| `/system/raw-sections/vdc` | Lossy | `vdc <name> id N / limit-resource …` (N7K virtualisation) has no canonical primitive; the source block is discarded and a default single-VDC `vdc <hostname> id 1` wrapper is synthesised on render. |
| `/system/raw-sections/features` | Lossy | `feature <name>` lines are derived on render from the canonical-tree shape (any SVI → `feature interface-vlan`, etc).  Source features not motivated by a canonical surface (`feature scp-server`, `feature telnet`) are dropped; re-authorise on the target. |
| `/local-users/user/privilege-level` | Lossy | NX-OS uses a named `role` (network-admin / network-operator / custom), not a numeric privilege.  network-admin / vdc-admin → 15, everything else → 1.  The named role round-trips losslessly same-vendor. |
| `/snmp/v3-user/auth-passphrase` | Lossy | The trailing `localizedkey` keyword is a CLAIM that the digest is already localised against this agent's engine ID, so it is both read and re-emitted per line: a key from another agent is refused (review comment, no `snmp-server user` line), a genuine passphrase renders WITHOUT the keyword and the Nexus localises it on commit, and a localised digest keeps its keyword.  NX-OS 10.x `localizedV2key` is normalised to the older `localizedkey` form on render.  Re-key SNMPv3 users on the target across OS-version boundaries. |
| `/snmp/v3-user/engine-id` | Lossy | engineID emitted colon-decimal (`128:0:0:9:…`); cross-vendor sources typically use hex.  Preserved verbatim same-vendor; cross-vendor render may need re-keying. |
| `/interfaces/interface/vrrp-groups/group` | Lossy | FHRP is expressed as HSRP (`interface VlanN / hsrp N / ip <vip> / priority / preempt`).  EVERY `CanonicalVRRPGroup` renders as an `hsrp` block regardless of source `mode` — the virtual-IP redundancy intent survives but the wire protocol changes.  Same-vendor HSRP round-trips losslessly; sub-second timers / virtual-MAC / track objects are not modelled. |
| `/routing-instances/instance/route-distinguisher` | Lossy | `rd auto` tells the device to derive the RD itself (`<BGP router-id>:<internal VRF ID>` for an IP-VRF) — a value that exists only at runtime and cannot be recovered from a config file. Netcanon preserves the keyword for same-vendor round-trips and, on targets whose grammar has no `auto` form (Junos, IOS-XE CLI), drops it with a review comment rather than inventing a value. An explicit `rd <asn>:<nn>` round-trips losslessly. |
| `/routing-instances/instance/rt-imports` | Lossy | `route-target both <rt> evpn` advertises in both IPv4-unicast and L2VPN-EVPN; the `evpn` address-family scope does not round-trip cross-vendor (RT value preserved, scope reverts to IPv4 unicast).  Same-vendor round-trips. |
| `/vxlan-vnis/vni` | Lossy | `interface nve1 / member vni N` per-VNI sub-flags (`suppress-arp`, alternate ingress-replication) do not round-trip — render always emits the modern BGP-EVPN head-end shape (`host-reachability protocol bgp`).  The VLAN↔VNI binding round-trips via `vlan N / vn-segment`. |
| `/evpn-type5-routes/route` | Lossy | EVPN Type-5 is modelled as a VRF property via `CanonicalRoutingInstance.l3_vni` (`vrf context X / vni N` + `member vni N associate-vrf`), not per-prefix records; no route-map / prefix-filter parsing in v1. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | IPv4 Distributed Anycast Gateway IS supported; the IPv6 companion parses-and-ignores in v1 (no fixture coverage; parity with the IOS-XE IPv6-anycast deferral). |
| `/routing-protocols/bgp` | Unsupported | `router bgp <asn>` is Tier-3 — captured for the dropped-Tier-3 banner, never auto-rendered cross-vendor. |
| `/routing-protocols/ospf` | Unsupported | Tier-3. |
| `/routing-protocols/eigrp` | Unsupported | Tier-3. |
| `/routing-protocols/isis` | Unsupported | Tier-3. |
| `/access-list/{extended,standard,ipv6}` | Unsupported | ACLs are Tier-3 — auto-translating ACL semantics across vendors risks subtly-permissive rules.  Operator authors firewall policy manually (mirrors cisco_iosxe_cli). |
| `/firewall` | Unsupported | NX-OS hosts no stateful firewall; declared unsupported for cross-vendor surface consistency. |
| `/nat` | Unsupported | NX-OS hosts no typical edge NAT. |
| `/qos` | Unsupported | `class-map / policy-map type qos / service-policy` is Tier-3 — DC-grade QoS is too platform-specific to auto-translate. |

#### `cisco_iosxr` (Cisco IOS-XR, bidirectional, certified)

Broad supported surface (Tier-1 + VRF + RT + per-interface VRF + LAG +
local users + per-VRF static + dot1q sub-interfaces).  A text with no
indentation, and the `show running-config formal` form of a whole
config (a setting on its `interface` lines), are REFUSED in words
rather than mis-parsed: a text with no indentation because IOS XR
places a line by its indentation when it loads a file, the formal
form because the parser reads only the form `show running-config`
prints.  A formal excerpt with no `interface` line is not recognised,
and is read as almost nothing (see
[`vendors/cisco_iosxr.md`](vendors/cisco_iosxr.md) § "Common
gotchas").  A banner (`banner <type>`, `aaa banner login`) is text and
is not read as configuration: it ends at the next occurrence of the one
character after its type, anywhere, and each kind is a row of the
sections not translated with its count of lines.  One with no end, a
`banner` line IOS XR does not print, a `^` alone in a banner printed
with `^C`, and a line of one that ends in a form feed or the like are
refused; a banner set through NETCONF that is printed with no end runs
on to its first character's next occurrence, and the lines between are
not read (see [`vendors/cisco_iosxr.md`](vendors/cisco_iosxr.md) § "A
banner is text").  The lossy / unsupported exceptions:

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | Type inferred from the name prefix (GigabitEthernet → ethernetCsmacd, Loopback → softwareLoopback, Bundle-Ether → ieee8023adLag, MgmtEth → ethernetCsmacd, tunnel-ip/te → tunnel); sub-interfaces with vendor-specific encapsulation classify as `other`. |
| `/interfaces/interface/4th-port-segment` | Lossy | IOS-XR port names use 4 segments (rack/slot/module/port); the cross-vendor `PortIdentity` supports 3.  Slot, module and port are carried; the rack round-trips same-vendor via `PortIdentity.meta['iosxr_rack']` and is not carried cross-vendor (it is 0 on every non-clustered system) — verify via the rename modal. |
| `/routing-instances/instance` | Lossy | `vrf <name>` + `address-family ipv4 unicast` / `import\|export route-target` + per-interface `vrf <name>` membership round-trip, but `route_distinguisher` must be read from / rendered to the BGP block (`router bgp <asn> / vrf <name> / rd <rd>`).  A minimal BGP-RD carrier is synthesised on render with ASN derived from the RD administrator field; a config whose BGP ASN differs re-emits the normalised ASN (cosmetic — the RD round-trips).  No `router bgp` ⇒ `route_distinguisher=''`.  `l3_vni` (EVPN Type-5) is not modelled. |
| `/snmp/community` | Unsupported | SNMP parse + render is out of the v1 XR scope. |
| `/routing/bgp` | Unsupported | `router bgp <asn>` is Tier-3 (a minimal per-VRF RD harvest aside); full BGP modelling stays unsupported. |
| `/routing/ospf` | Unsupported | `router ospf <pid>` parse-and-ignore (Tier-3). |
| `/routing/isis` | Unsupported | `router isis <name>` parse-and-ignore (Tier-3). |
| `/mpls` | Unsupported | `mpls ldp` / `mpls traffic-eng` / `mpls oam` are SP-platform fundamentals with no canonical model; Tier-3 banner notes the dropped surface. |
| `/policy/{route-policy,prefix-set,community-set,as-path-set}` | Unsupported | The IOS-XR RPL `… end-policy` / `… end-set` set-form DSL is structurally distinct from IOS-XE `route-map` sequence form; Tier-3 by design (parity with Junos `policy-options`). |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | IOS-XR VXLAN (NCS 5500 / 540 `nve`) is rare in the SP corpus; no canonical demand surfaced.  Parse-and-ignore in v1. |
| `/evpn-type5-routes/route` | Unsupported | IOS-XR EVPN runs under top-level `l2vpn` + `evpn` + `bridge group` — grammatically distant from the IOS-XE / Arista / NX-OS model.  No canonical mapping in v1. |
| `/access-list/{extended,ipv6}` | Unsupported | `ipv4 access-list NAME / N permit …` is Tier-3 — auto-translating ACL semantics risks subtly-permissive rules (parity with IOS-XE). |
| `/firewall` | Unsupported | IOS-XR firewall features are Tier-3 stateful surfaces (parity with IOS-XE). |
| `/nat` | Unsupported | IOS-XR NAT (`nat64` / `cgnat`) is Tier-3. |

#### `aruba_aoscx` (Aruba AOS-CX, bidirectional, certified)

Broad supported surface (Tier-1 + L2 switchport/LAG + local users + SNMP
v2c/v3 + IPv4 active-gateway anycast + VXLAN L2VNI VLAN↔VNI binding).
Distinct from the campus `aruba_aoss` (AOS-S) codec.  A banner, ended
at the first later line that ENDS with its one delimiter (one with
text after it is the banner's text), is text and is not read as
configuration; one with no end, more than one character after its
type, or a line that ends in a form feed or the like is refused.  A
banner whose text holds the delimiter at the end of a line ends there,
undetected (see [`vendors/aruba_aoscx.md`](vendors/aruba_aoscx.md) §
"A banner is text").  The lossy / unsupported exceptions:

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | No IANA ifType is declared; inferred from the name shape (`1/1/1` → ethernetCsmacd, `vlan N` → l3ipvlan, `lag N` → ieee8023adLag, `loopback N` → softwareLoopback, `mgmt` → ethernetCsmacd, `vxlan N` → tunnel).  Best-effort. |
| `/system/raw-sections/version-banner` | Lossy | The `!Version ArubaOS-CX <release>` banner + service footer lines (`ssh server`, `https-server`, `clock`, `ntp`, `spanning-tree`, `system interface-group`) are discarded on parse and a synthesised banner is emitted on render; re-apply management-plane services on the target. |
| `/local-users/user/privilege-level` | Lossy | Named `group` (administrators / operators / auditors / custom), not numeric: administrators → 15, everything else → 1.  The `password ciphertext` blob is AES-encrypted with the device key (portable same-device only); cross-vendor migration requires re-keying. |
| `/snmp/v3-user/auth-passphrase` | Lossy | Two distinct losses.  (1) AOS-CX renders SHA-1 auth / AES-128 priv only, so a stronger source algorithm is DOWNGRADED — a crypto change, not a re-key.  (2) `auth-pass ciphertext <blob>` claims the value is encrypted under this device's key, true only of a key this switch produced, so a key belonging to another agent is refused (review comment, no `snmpv3 user` line).  A source passphrase is portable and renders through `auth-pass plaintext`, which the switch encrypts itself; the parser already accepts both keywords, so the recovered form round-trips. |
| `/vxlan-vnis/source-interface` | Lossy | AOS-CX states the VTEP source as an IPv4 *address* (`interface vxlan 1 / source ip <X>`), not an interface name (NX-OS / Arista `source-interface loopbackN`).  Stored verbatim in the opaque `source_interface` field; a cross-vendor source carrying an interface *name* has no `source ip` form so the line is omitted on render (VLAN↔VNI bindings still emit).  Set the loopback→IP mapping on the target manually. |
| `/snmp/trap-host` | Unsupported | The `snmp-server host … trap …` trap-receiver grammar is deferred; v2c community + system-location / system-contact + v3 USM users are supported. |
| `/routing-instances/instance/{description,route-distinguisher,rt-imports,rt-exports}` | Unsupported | The `vrf <name>` stanza is a bare name in v1; descriptions / RD / route-targets live under the deferred `evpn` / `router bgp` blocks. |
| `/routing/static-route/vrf` | Unsupported | Per-VRF static-route binding parses-and-ignores in Phase 1; only default-VRF `ip route` is wired. |
| `/interfaces/interface/vrrp-groups/group` | Unsupported | AOS-CX VRRP (`vrrp <vrid> address-family` under an SVI) is a later phase; the `active-gateway` distributed-gateway anycast surface IS supported. |
| `/interfaces/interface/ipv6/address/virtual-gateway-address` | Unsupported | IPv4 active-gateway is supported; the IPv6 anycast companion parses-and-ignores in v1 (parity with NX-OS / IOS-XE). |
| `/vxlan-vnis/l2vni-route-target` | Unsupported | The per-VLAN L2VNI RD/RT (`evpn / vlan N / rd auto / route-target …`) is almost always `auto`-derived and has no cross-vendor canonical home; the VLAN↔VNI binding IS translated, the RD/RT is re-derived on the target. |
| `/routing-instances/instance/l3-vni` | Unsupported | EVPN symmetric-IRB L3VNI (`vni N / vrf <name>` under the VTEP + `router bgp / vrf`) is a later phase; the L2VNI binding IS supported. |
| `/routing-protocols/bgp` | Unsupported | `router bgp <asn>` (incl. the EVPN address-family) is Tier-3 — captured for the dropped-Tier-3 banner, never auto-rendered cross-vendor. |
| `/routing-protocols/ospf` | Unsupported | Tier-3. |
| `/access-list/{extended,standard}` | Unsupported | ACLs are Tier-3 — auto-translating risks subtly-permissive rules (mirrors cisco_nxos). |
| `/qos` | Unsupported | QoS (`class` / `policy` / `apply qos`) is Tier-3 — too platform-specific to auto-translate. |
| `/nat` | Unsupported | AOS-CX hosts no typical edge NAT. |

#### `vyos` (VyOS, bidirectional, certified)

Broad supported surface (curly-brace `config.boot` **and** set-form
`show configuration commands` input; Tier-1 + local users + NTP +
bonding LAGs + SNMP + VRF + VXLAN L2VNI).  Render always emits the
curly-brace form.  The lossy / unsupported exceptions:

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | No IANA ifType; inferred from the name shape (`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback, `bondN` → ieee8023adLag).  Best-effort. |
| `/system/raw-sections/version-banner` | Lossy | The `// vyos-config-version` trailer + not-yet-modelled `service` / `system` management blocks (SSH / syslog / DNS) are discarded on parse and a synthesised trailer is emitted on render; re-apply those services on the target. |
| `/local-users/user/privilege-level` | Lossy | `system login user` accounts have no numeric privilege in the common case; every login user maps to privilege 15 / role `admin`.  The `encrypted-password` hash round-trips verbatim same-vendor; cross-vendor migration requires re-keying. |
| `/lags/lag/mode` | Lossy | Bonding `mode 802.3ad` (LACP) → `active`; the non-LACP modes (`active-backup` / `balance-rr` / `balance-xor` / …) collapse to `static` (the balancing algorithm is dropped — re-select on the target). |
| `/snmp/v3-user/auth-passphrase` | Lossy | v3 USM auth/privacy keys carry one of two leaves under both `auth` and `privacy`: `encrypted-password` (localised against VyOS's own engine ID) or `plaintext-password` (VyOS hashes it on commit).  Both are parsed — `plaintext-password` was previously dropped on the floor, building the user with an empty key — and each is re-emitted through the leaf matching its recorded kind, so a passphrase is never relabelled as this agent's own localised key.  Round-trips verbatim same-vendor; cross-vendor migration requires re-keying (vendor-specific salts), and a foreign key is never accepted INTO VyOS. |
| `/snmp/v3-user/engine-id` | Lossy | VyOS declares a single config-wide `engineid` for the whole agent; the canonical model carries it per-user, so the one value maps onto every v3 user (and a single `engineid` is emitted when the users share one). |
| `/routing-instances/instance/table` | Lossy | VyOS requires a numeric `table <id>` on every `vrf name <X>`; the canonical RoutingInstance carries no table number, so a deterministic id (`100 + sort-index`) is synthesised on render.  The original table id is not preserved. |
| `/vxlan-vnis/source-interface` | Lossy | The VTEP source is `source-address <ip>` (or `source-interface <if>`) on the vxlan netdev; the opaque string round-trips same-vendor but a cross-vendor source (e.g. `Loopback0`) is re-emitted verbatim and may need an operator port-rename. |
| `/vxlan-vnis/vlan-id` | Lossy | VyOS models ONE VNI per `vxlan vxlanN` netdev with no on-device VLAN (the L2 binding lives on a separate `bridge`); the required canonical `vlan_id` is synthesised from the VNI and the netdev name regenerated `vxlan<index>` on render — both deterministic (stable same-vendor, advisory cross-vendor). |
| `/vlans/vlan/id` | Unsupported | VyOS has no top-level VLAN database; 802.1Q VLANs are `vif <vid>` sub-interfaces (rendered as `ethN.<vid>` interfaces), which ARE supported. |
| `/routing/static-route/vrf` | Unsupported | Per-VRF static routes (`vrf name <X> { protocols static route … }`) are deferred past the Phase-3 VRF wire-up; the `vrf name` instances + per-interface binding ARE supported. |
| `/vxlan-vnis/l2vni-route-target` | Unsupported | EVPN per-VNI RD/RT lives under `protocols bgp … address-family l2vpn-evpn` (Tier-3, dropped); the L2 VLAN↔VNI binding is supported but the control-plane RD/RT is not auto-translated. |
| `/routing-instances/instance/l3-vni` | Unsupported | Symmetric-IRB L3VNI (a VNI bound to a VRF for inter-subnet routing) is out of scope for the Phase-5 per-netdev L2-VNI model. |
| `/routing-protocols/bgp` | Unsupported | `protocols bgp` is Tier-3 — captured for the dropped-Tier-3 banner, never auto-rendered cross-vendor. |
| `/routing-protocols/ospf` | Unsupported | Tier-3. |
| `/nat` | Unsupported | `nat source` / `nat destination` is Tier-3 — too platform-specific to auto-translate. |
| `/firewall` | Unsupported | `firewall` rule-sets are Tier-3 — auto-translating risks subtly-permissive rules. |
| `/access-list/extended` | Unsupported | VyOS `policy` route-maps / prefix-lists are Tier-3. |

#### `dell_os10` (Dell SmartFabric OS10, bidirectional, best_effort)

Broad supported surface (Tier-1 + L2 switchport/LAG + SVI-derived VLANs
+ local users + SNMP v2c/v3 + real VRRP + VRF + per-VRF static).
Distinct from Dell's older Force10 **OS9 / FTOS** grammar, which this
codec REFUSES rather than mis-parse.  A banner, ended by a line that
is its delimiter alone, is text and is not read as configuration; one
with no end, with more than its delimiter after its type, or with a
line that ends in a form feed or the like is refused, and so is a
line of its delimiter alone left outside every banner because a
banner's own text held one (see
[`vendors/dell_os10.md`](vendors/dell_os10.md) § "A banner is
text").  The lossy / unsupported exceptions:

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | No IANA ifType is declared; inferred from the name shape (`ethernet` → ethernetCsmacd, `vlan` → l3ipvlan, `port-channel` → ieee8023adLag, `loopback` → softwareLoopback, `mgmt` → ethernetCsmacd).  Best-effort. |
| `/interfaces/interface/dhcp-client` | Lossy | OS10 spells this `ip address dhcp`, which v1 neither parses nor renders; the interface renders, the DHCP-client flag drops. |
| `/interfaces/interface/dhcp-client-v6` | Lossy | OS10 spells this `ipv6 address autoconfig` / `dhcp`; the marker is consumed but has no canonical value, so it drops on render. |
| `/interfaces/interface/ipv6/address/secondary-ip` | Lossy | The IPv4 render re-emits the `secondary` keyword and reads it back, but OS10's `ipv6 address` form has no such keyword, so an IPv6 secondary flag is lost while the address survives. |
| `/interfaces/interface/tunnel-type` | Lossy | v1 models no OS10 tunnel encapsulation; the port renders as a plain `interface <name>` stanza while its encapsulation type drops. |
| `/interfaces/interface/{ipv4,ipv6}/address/virtual-gateway-address` | Lossy | OS10 has **no VARP / distributed-anycast-gateway concept** — first-hop redundancy is real VRRP (`vrrp-group` + `virtual-address`).  The interface address renders; the anycast virtual IP does not.  Re-author it as a VRRP group on the target. |
| `/interfaces/interface/{ipv4,ipv6}/address/virtual-gateway-mac` | Lossy | Drops with the anycast virtual-gateway IP above. |
| `/vlans/vlan/description` | Lossy | OS10 carries exactly ONE human label for a VLAN — the SVI's `description` — and the render spends it on `CanonicalVlan.name`.  A separate canonical description has no second place to go. |
| `/vlans/vlan/ipv4/address/{virtual-gateway-address,virtual-gateway-mac}` | Lossy | The VLAN's address renders (an `interface vlan<N>` SVI is synthesised for a VLAN that carries one), but the anycast virtual gateway has no OS10 form. |
| `/routing-instances/instance/instance-type` | Lossy | Renders as `ip vrf <name>`, which has no mac-vrf form, so the mac-vrf vs vrf discriminator downgrades to `vrf`.  The instance itself round-trips. |
| `/routing-instances/instance/{description,route-distinguisher,rt-imports,rt-exports,l3-vni}` | Lossy | The `ip vrf <name>` stanza carries the name and nothing else — RD, route-targets and the L3VNI binding all live under Tier-3 `router bgp` / the deferred `virtual-network` indirection. |
| `/routing/static-route/description` | Lossy | Render emits destination + next-hop + administrative distance only; a route name / description drops. |
| `/snmp/v3-user/{auth-passphrase,priv-passphrase}` | Lossy | A USM key is localised against the agent's OWN engine ID, and Dell states such keys cannot be copied between switches (10.5.2 User Guide L8942).  A key from another agent is REFUSED (review comment, no `snmp-server user` line) rather than emitted behind `localized`, which would claim the digest was already this switch's.  A source PASSPHRASE is portable and is emitted WITHOUT that keyword so OS10 localises it on commit.  Migrating cross-vendor means re-keying SNMPv3 users. |
| `/snmp/v3-user/auth-protocol` | Lossy | OS10 offers only `auth md5` / `auth sha`, so every SHA-2 variant (sha224/256/384/512) collapses to `sha` — a real crypto downgrade, not a faithful round-trip. |
| `/snmp/v3-user/priv-protocol` | Lossy | OS10 offers only `priv des` / `priv aes`, so AES-192 and AES-256 collapse to `aes` and 3DES to `des`. |
| `/snmp/v3-user/engine-id` | Lossy | OS10 states the engine ID on its own `snmp-server engineID local` line rather than on the user, so a per-user engine ID from a cross-vendor source drops while the user renders. |
| `/interfaces/interface/vrrp-groups/group/mode` | Lossy | OS10 renders **real VRRP**, so a cross-family source mode (HSRP / CARP) is reinterpreted as VRRP: the operator's redundancy intent for the virtual IP survives but the wire protocol changes.  Same-vendor VRRP round-trips losslessly. |
| `/interfaces/interface/vrrp-groups/group/{advertisement-interval,authentication,virtual-mac,track-interfaces,description}` | Lossy | Not modelled in the v1 VRRP surface; the group renders (id / priority / preempt / virtual addresses) without them.  OS10 tracks a track-OBJECT id, not an interface name, so a canonical track-interface list has no faithful form. |
| `/interfaces/interface/vrrp-groups/group/virtual-ipv6s` | Lossy | OS10 expresses IPv6 VRRP through a SEPARATE `vrrp-ipv6-group` stanza that v1 does not render, so IPv6 virtual addresses drop while the IPv4 group survives. |
| `/vxlan-vnis/{vni,vlan-id,source-interface,mcast-group,flood-list,udp-port}` | Unsupported | OS10 reaches an overlay through a `virtual-network <vnid>` indirection deferred past v1; no VXLAN is rendered. |
| `/evpn-type5-routes/route` | Unsupported | No EVPN is rendered; BGP / EVPN is Tier-3 on OS10. |
| `/anycast-gateway-mac` | Unsupported | No distributed-anycast-gateway concept (see the virtual-gateway rows above). |
| `/system/{domain,dns-server,ntp-server,syslog-server,timezone}` | Unsupported | v1 parses no `ip domain-name` / `ip name-server` / `ntp server` / `logging server` / clock stanza.  Re-apply the management plane on the target. |
| `/dhcp-servers/pool` + `/dhcp-servers/pool/{gateway,dns-servers,domain-name,lease-time}` | Unsupported | v1 parses no DHCP server pool. |
| `/radius-servers/server/{host,key}` | Unsupported | v1 parses no AAA `radius-server` config. |
| `/interfaces/interface/dot1q-vlan` | Unsupported | Per-port dot1q sub-interface VLAN tagging is not modelled. |
| `/interfaces/interface/voice-vlan` | Unsupported | Per-port voice VLAN is not modelled. |
| `/routing-protocols/{bgp,ospf,eigrp,isis}` | Unsupported | Tier-3 — captured for the dropped-Tier-3 banner, never auto-rendered cross-vendor. |
| `/access-list/{extended,standard,ipv6}` | Unsupported | ACLs are Tier-3 — auto-translating risks subtly-permissive rules. |
| `/firewall` | Unsupported | Tier-3. |
| `/nat` | Unsupported | OS10 does not host typical edge NAT. |
| `/qos` | Unsupported | QoS / DCB is Tier-3 — too platform-specific to auto-translate. |


### B. Tier-3 sections detected banner

When a source codec parses a config that contains stanzas it
deliberately drops (firewall, NAT, QoS, route-maps, IPsec, etc.),
the parser's per-vendor heuristic detector populates
`CanonicalIntent.dropped_tier3_sections` with the matching
stanza headers.  The migrate page renders these as a warning banner:

> ⚠ Tier-3 sections detected in source — The source config contains
> N section(s) this tool does not translate (firewall rules, NAT,
> QoS, route-maps, IPsec, etc.).  These will NOT appear in the
> rendered output.  Operator must apply them manually on the target
> device.

One kind of row is not a section to apply by hand.  A Junos
statement the source had **deactivated** (`deactivate <path>` in
set-form, `inactive:` in the hierarchical form) is not in force on
the device, so it is left out of the translation and listed here as
`inactive: <path>`; a statement under a load file's `delete:` is
listed as `delete: <path>`; and an IOS XR `interface preconfigure
<name>` stanza, which is configuration the router holds for an
interface it does not have until the line card is put in, is listed
as `preconfigure: interface <name>`.  No interface is made of such
a stanza, neither one called `preconfigure` nor the port it names,
and nothing in it is read.  The banner counts only the sections,
says in a sentence of its own what the other rows are, and is
headed "Statements the source held and did not run" when it holds
nothing else.  A same-vendor Junos job does not write the statement
back as inactive: it is gone from the output, and the row is the
record.

Such a row names the statement and never a secret.  Its path is cut
after the first word that names one (a word with `community`,
`password`, `secret`, `key`, `psk` or `authentication` in it) and
the cut is marked: `inactive: snmp community ...`.  A deactivated
leaf is named by its first word, without its value.  A row for a
section is the stanza header as the config has it.

A job whose only rows are of this kind, and which recognised
nothing else, is `partial`: a statement is named whether or not
anything under it would have been read, so the row is not a sign
that the text was a config.  The rows of this kind are bounded:
past the bound, one last row counts the statements not listed.

Rows a parser adds itself are sections, counted with the others
and true of the same sentence — they are not in the output:

* **`interface range ...`** (IOS-XE, IOS XR) — the header of a
  stanza that configures several ports at once.  It names no
  interface, so no interface is made of it and nothing in it is
  read.  Configure the ports it covers on the target by hand.
* **`interface breakout <port> map <profile>`** (IOS-XE, IOS XR)
  — OS10's line for splitting a port into lanes, in a text read as
  one of those two.  It names no interface either: one row a line,
  and nothing of it in the output.
* **`<dhcpd><zone>: no <zone> in <interfaces>, so its DHCP pool has
  no interface`** (OPNsense) — a DHCP pool keyed by a zone no
  device is assigned to.  It has no interface to be on, and is
  left out.

Per-vendor detection patterns
([`netcanon/migration/_tier3_detection.py`](../netcanon/migration/_tier3_detection.py)):

| Source codec | Patterns matched (excerpt) |
|---|---|
| `cisco_iosxe_cli` / `arista_eos` / `aruba_aoss` (IOS-style CLI heuristic) | `ip access-list extended/standard <name>`, `ipv6 access-list <name>`, numbered `access-list N permit/deny`, `ip nat inside/outside/pool`, `class-map`, `policy-map`, `route-map <name>`, `crypto isakmp/ipsec/map/pki`, `zone-pair security` |
| `juniper_junos` (set form, and the hierarchical form as it is read: converted to set form first) | `set firewall [family X] filter <name>`, `set security {policies\|nat\|ike\|ipsec\|zones\|address-book\|flow\|screen\|alg\|utm\|application-tracking\|forwarding-options}`, `set policy-options {policy-statement\|prefix-list\|community} <name>`, `set class-of-service` |
| `fortigate_cli` | `config firewall {policy\|policy6\|vip\|vip6\|central-snat-map\|address\|addrgrp\|service\|shaper}`, `config vpn {ipsec\|ssl}`, `config {webfilter\|antivirus\|ips\|dlp\|application}`, `config router {policy\|route-map}` |
| `mikrotik_routeros` | `/ip firewall {filter\|nat\|mangle\|raw\|address-list}`, `/ipv6 firewall …`, `/queue`, `/ip ipsec`, `/routing {filter\|bgp\|ospf}` |
| `opnsense` | XML elements: `<filter>`, `<nat>`, `<ipsec>`, `<openvpn>`, `<wireguard>`, `<shaper>`, `<load_balancer>`, `<captiveportal>` |
| `cisco_iosxe` (NETCONF) | No-op (NETCONF input rarely carries Tier-3 stanzas — retained for codec-hook symmetry) |

Detection is intentionally heuristic on stanza headers — not a
parse.  False positives are preferred to false negatives.  The
output is **notification-only**: it never feeds the renderer or any
transform.

### C. Render-time review comments

When a render path can't faithfully emit a piece of canonical
state, it emits a comment in the target's native syntax instead of
guessing or silently dropping.  Operators searching for `review:`
in rendered output find every such site.

* **Hash-portability policy**
  ([`netcanon/migration/_user_secrets.py`](../netcanon/migration/_user_secrets.py)).
  Every render path that emits a local user (all eleven) calls
  `is_migratable(hash, target_vendor)` first; on a miss, they emit a
  vendor-correct comment of the form:

      password manager user-name "X" -- review: <alg> hash from
      source vendor cannot be re-used on <target>; reset this user
      password manually

  Comment delimiter varies by vendor: Aruba AOS-S uses `;`, Cisco
  IOS-XE CLI / NX-OS / IOS-XR, Arista EOS and ArubaOS-CX use `!`,
  VyOS uses `/* … */`, Junos / FortiGate / MikroTik use `#`,
  OPNsense uses `<!-- … -->` (with `--` collapsed to `-` per XML
  1.0).  Per-target accepted-algorithm sets live in
  `_TARGET_ACCEPTS`.  A foreign hash NEVER falls
  back to plaintext (that would leak the hash literal as the password —
  a severe security bug).

  Two caveats, both measured rather than asserted:

  1. The policy only binds secrets it can *recognise*.  Until the
     `_STRUCTURED_PREFIXES` table existed, a bare crypt string carrying
     no algorithm tag — the form VyOS stores natively — classified as
     `plaintext`, so the "never falls back" rule did not engage and the
     digest was emitted under the target's cleartext marker on 14 of 14
     VyOS records.  Bare crypt forms and vendor ciphertext blobs are now
     classified by prefix, and an unmodelled `$id$` shape fails closed.
  2. Until #461, **`aruba_aoscx`, `cisco_iosxr`, `cisco_nxos` and `vyos`
     emitted local users WITHOUT calling the gate**, so as targets they
     accepted any hash.  Measured on the corpus before that change: 61
     source secrets rendered behind NX-OS `password 0` and 61 behind IOS-XR
     `secret 0` — both cleartext markers — plus 116 VyOS and 93 AOS-CX
     values written into hash slots that could not authenticate.  All four
     now gate; a consumable secret is re-tagged into the target's native
     form (IOS-XR `secret 10` for SHA-512 crypt, a bare crypt string in
     VyOS `encrypted-password`) and genuine plaintext goes to the leaf that
     means plaintext.  NX-OS type 5 is now classified by its payload: NX-OS
     writes every crypt form under `password 5` and defaults to `$5$`, which
     had been mis-tagged MD5 crypt and passed the EOS / IOS-XE gates.
     `test_every_user_rendering_codec_refuses_an_unmodelled_secret` fails
     for any codec — current or future — that renders users without the
     gate.
  3. A tag names an algorithm only when it can be trusted.  `junos:` is a
     vendor envelope and OPNsense's `bcrypt:` is applied unconditionally, so
     since #462 both defer to the crypt(3) id inside the payload (`$9$`
     excepted, being both Juniper-reversible and Cisco type-9).  OPNsense
     accepts bcrypt and SHA-512 crypt.

* **SNMPv3 USM key portability**
  ([`vyos/render.py`](../netcanon/migration/codecs/vyos/render.py)).  A v3 auth
  or privacy key is localised against the agent's engine ID, so it does not
  port between devices even when both sides model USM.  Since #463 the vyos
  render emits a key only when it produced it (`source_vendor == "vyos"`);
  any other key is refused and the whole `user` entry is skipped, with a
  `review:` comment naming it.  There is no recovery path here — unlike a
  local-user password, the target accepts no plaintext USM form.  Other
  targets still carry foreign USM keys verbatim; their pair expectations
  declare that loss.

  Since #464 the policy is shared
  ([`_usm_keys.py`](../netcanon/migration/_usm_keys.py)) and NX-OS uses it too.
  NX-OS differs from VyOS in having a portable form: a passphrase renders
  without `localizedkey` and the agent localises it on commit, so passphrase
  sources migrate correctly rather than being refused.  The kind is inferred
  from the source codec's grammar, never from the value's shape.  Three
  grammars mark the kind on the line itself (NX-OS `localizedkey`, AOS-CX
  `ciphertext`/`plaintext`, Junos `authentication-key` vs
  `authentication-password`) and their parsers now RECORD which marker they
  read, onto `CanonicalSNMPv3User.auth_kind` / `priv_kind`; a line carrying no
  marker falls back to the per-codec default.  That is still kind-from-grammar,
  at per-line rather than per-codec resolution — it is not licence to read the
  value, and three committed NX-OS captures prove why: they carry
  `localizedkey` over a value sanitisation left word-like, so the marker
  survived where the shape did not.  Recording it also fixed a SAME-VENDOR
  corruption: NX-OS had been re-emitting a passphrase line with `localizedkey`
  appended, telling the agent a passphrase was already localised against its
  own engine ID.

  Since #465 `arista_eos` and `juniper_junos` are gated too, and they show the
  two shapes this defect takes.  EOS's slot takes a PASSPHRASE and derives the
  key from it, so handing it a digest re-derives a key from a key; Junos's
  `authentication-key` holds a value Junos already processed, so handing it a
  passphrase stores the passphrase as a key.  Junos carries a portable key
  through `authentication-password` (a different LEAF, where NX-OS used the
  same leaf without a keyword) and the parser was taught to read that leaf in
  the same change — a leaf the render emits but the parser ignores is a silent
  loss.  A Junos refusal drops the user's VACM `security-to-group` binding as
  well, since a security-name with no usable key is a half-configured account.

  Since #466 `aruba_aoscx` gates too, and it is the NX-OS shape in a different
  grammar: `auth-pass ciphertext <blob>` claims the value is encrypted under
  this device's key, so a foreign key is refused and a portable passphrase
  renders through `auth-pass plaintext` for the switch to encrypt.  Its parser
  already accepted both keywords, so that recovery needed no parse change —
  and the parser now also RECORDS which keyword it saw, so an AOS-CX *source*
  whose key really is a passphrase migrates instead of failing closed.  Each
  token carries its own keyword, so auth and priv are resolved independently.

  Since #467 `aruba_aoss` gates too, in the Arista shape: its `snmpv3 user`
  slot takes a passphrase and derives the key, so a foreign key is refused and
  passphrase sources are untouched.  A refused AOS-S user also loses its
  `snmpv3 group … user …` binding, which would otherwise name a user that was
  never created.

  Since #468 the series is complete: `cisco_iosxe_cli` and
  `mikrotik_routeros` gate in the Arista shape, and `fortigate_cli` in the
  AOS-CX shape — `set auth-pwd "ENC <v>"` claims FortiOS encryption, so a
  foreign key is refused and a portable passphrase is emitted WITHOUT the
  prefix for FortiOS to encrypt on save.  **All nine codecs that render
  SNMPv3 USM users now gate.**  FortiGate was missing from the earlier
  "remaining targets" lists in #464-#467; it renders v3 users and was never
  gated, so it is included here.

  Two parsers stamp a FAMILY name rather than the codec name
  (`fortigate_cli` → `fortigate`, `cisco_iosxe_cli` → `cisco_iosxe`).
  `_usm_keys._VENDOR_ALIASES` treats those as same-vendor, without which a
  FortiGate re-render of its own config would refuse its own key — FortiOS
  values classify `encrypted`, which no target accepts from a foreign source.

* **Aruba AOS-S DHCP comment block**
  ([`aruba_aoss/render.py`](../netcanon/migration/codecs/aruba_aoss/render.py)).
  AOS-S is a DHCP-relay platform on most SKUs — it doesn't run a
  DHCP server.  When canonical carries DHCP pools, the renderer
  emits a header comment block:

      ; DHCP pools from source codec are not supported
      ; by AOS-S (AOS-S is a DHCP relay platform, not a
      ; DHCP server).  Reconfigure on a sibling server.

  …followed by one summary comment line per pool.

* **Aruba AOS-S OOBM IPv6**.  AOS-S has documented `oobm` IPv4
  syntax but unverified IPv6 syntax; the renderer emits the IPv6
  address as a comment-form review line rather than guessing.

* **MikroTik IPsec tunnel placeholders**.  When the canonical
  carries an IPsec peer with an empty/placeholder address, the
  renderer emits the line plus `comment="review: tunnel endpoint
  placeholder -- set local-address/remote-address"`.

* **Junos `apply-groups` round-trip**.  Group bodies are emitted
  verbatim before their `apply-groups` reference so the operator
  can audit; cross-vendor renderers do not include them.

* **Foreign port names** (Cisco IOS-XE CLI render path).  When the
  port-rename mesh hands a foreign port name to a target whose
  `classify_port_name` can't place it, the renderer emits
  `! interface <name> -- review: foreign port` rather than
  emitting an interface stanza for an unknown chassis position.

### D. Validation severity (`ok` / `warn` / `block`)

Every `MigrationJob` carries a validation severity computed from the
target's capability matrix vs. the canonical tree's actually-populated
fields.  The migrate page reflects this in the status banner and
`POST /api/v1/migration/plan` returns it on `job.validation`:

* `ok` — every populated canonical leaf maps to a `supported` xpath
  on the target.
* `warn` — at least one leaf hits a `lossy` xpath; render proceeds.
* `block` — at least one leaf hits an `unsupported` xpath; the job's
  status flips to `partial` (rendered output exists but should be
  reviewed before deploy).

Job status reaches `failed` only when a stage actually raises;
validation alone never fails the job.

A job can be `partial` with a clean validation report: for its port
names.  Section D1 says when, for a request that declares no devices;
section G, for one that declares both.

### D1. Port names that are not settled (`fused_ports` / `unresolved_ports` / `untranslated_ports`)

A warning is not a status.  Unless you declare both devices (section
G), every port name is translated by the shape of the name, and
three things that translation can do to a name are a loss the
capability matrix has no path for:

* **Two source names end on one name of the output**, so the config
  of two interfaces is written as one.  Aruba AOS-S `1/1` and the
  uplink-module port `1/A1` are both `Ethernet1` on EOS; VyOS `eth0`
  and `eth1` are both `port1` on FortiOS, which numbers from 1; Junos
  `ae0` and `ae1` are both `Port-channel1` on IOS-XE; a Junos
  per-instance loopback `lo0.2` is put on `Loopback0` beside `lo0`.
  Any two names count — a LAG or a loopback as much as a port —
  and they are compared as each platform tells interfaces apart
  (`Trk1` and `trk1` are one port on AOS-S; `DMZ` and `dmz` are two
  interfaces on FortiOS).
* **A name is dropped** because the target has no name for it.  A
  hardware port — a management port onto a platform with no form
  for one, a breakout lane, a port whose shape the target's names
  cannot take — and a logical name just the same: a loopback or a
  tunnel the target has no form for, a FortiGate hardware switch
  (`internal`) that holds the LAN address.  What was configured on
  it is not in the output.  A sub-interface that went with its port
  is listed with it.
* **A name is left as the source config has it**, because the
  translator could not read it as any kind of port (`could not
  classify port name ...; left verbatim`).  Whatever the output has
  of it is under a name of the source vendor: an IOS
  `GigabitEthernet1` (the one-number ports of a virtual router) in a
  Junos config, an OPNsense `igc0`, a RouterOS interface an operator
  named, the `VlanN` interface an AOS-S VLAN's address is carried
  on where the target calls that interface something else.  Nobody
  chose that name for the target.  A name the translator left that
  is no foreign name on the target is not listed — see "What is
  not counted" below.

Such a job is `partial`, not `completed`.  `job.error` says "Port
names are not settled: ..." — after the sentence it already had,
if the validation report made it `partial` as well — and the names
are on the job as data:

* **`fused_ports`** — each shared name of the output, with the
  source names that ended on it;
* **`unresolved_ports`** — the names that were dropped and that no
  entry of your `port_rename_map` names (`source_ports` says which
  of them are hardware ports);
* **`untranslated_ports`** — the names left as the source has them
  that are a foreign name on the target and that no entry names.

Nothing else about the job moves: the output is the one it always
rendered, and the warning lines (`port_rename: multiple source ports
map to ...`, `... target OOBM model differs ...`, `... could not
classify port name ...`) are the ones it always carried.

**To settle it**, decide each name with an entry of `port_rename_map`
(the Ports pane of the rename modal, or the API):

* two names on one name — give all but one of them a name of its
  own, or `null` to drop it;
* a dropped name — a target name, or `null`, which is you saying
  it is to go.  An entry that drops a port decides its
  sub-interfaces with it;
* a name left as it was — the name it is to have on the target, or
  `null` to drop it.  Where the name is right on the target as it
  stands (a RouterOS interface you named `WAN`, onto FortiOS, where
  a name is yours to choose), give it ITSELF: `{"WAN": "WAN"}` is
  you saying so.

A value is a name or `null`.  A blank one — `""`, only white
space, or only characters that draw nothing (control and format
characters: a zero-width space, a NUL, a byte-order mark) — is
refused with a 422 on every plan endpoint: it is not a way to
drop, and taken as a name it wrote an interface with no name
anyone can see.
Two entries of your own that point at one name are reported like any
other two.

**Declaring both devices settles the hardware ports among these
names, and no others.**  Ports are then paired by position, each
with a port of its own, and the job reports through
`port_mapping_plan` (section G) — the job's three fields are empty
on such a job, so that one fact has one account.  A pair of devices
decides nothing about two loopbacks on one loopback, a tunnel that
was dropped or a VLAN interface left under its source name: with
both devices declared the output has them the same, and the job is
not held for them.  So the job's sentence offers the devices only
where a hardware port is among what it lists, and says so where
they would decide only some of it.  (The sentence does not know
which vendors have a device described: it makes the offer for an
NX-OS source too, for which none ships.  The rename modal does
know, and does not.)

The same body gives the same status and the same fields on `/plan`
and on every per-pane endpoint, and every one of them applies the
body's `port_rename_map`.  (`/plan/vlans`, `/plan/local_users`,
`/plan/snmp` and `/plan/snmpv3` used to set a posted port map aside
unless devices were declared.)

**In the browser** the status banner of the migrate page shows the
sentence.  The rename modal says above its table how many names
share one, how many were dropped and how many were left under their
source name.  Rows the job wrote as one interface carry the
collision mark (⛔); a dropped row and a row left under its source
name carry the mark of a row that needs a decision (?), counted on
their section.

* Two rows written as one: give one of them another target, or drop
  it.
* A dropped row: **drop** beside *keep verbatim* is the decision
  that it is to go, and **Accept the drops** records it for all of
  them; with a target device chosen the row's list has a *Drop*
  entry.
* A row left under its source name says so where its auto name
  would be, and has the name field, **keep this name** — the entry
  that names it with itself — and **drop**; with a target device
  chosen its list has *Keep this name*.  No one button does this
  for several rows: whether a name is right on the target is said
  of one name at a time.

The strip sends you to the device pickers only for what they
settle.  With nothing chosen it offers both devices where a
hardware port is among the names and each vendor has a device to
choose.  With one device chosen and no hardware port among the
names, it says that choosing the other pairs hardware ports by
position and settles none of the names above — it used to end
"Choose the target device to pair ports by position" whatever
was listed.  Where the target vendor has no device described, it
says so and does not tell you to choose one.

Then Apply.  Apply is held for rows the job lists as written as one
interface, and for two rows you give one name in the fields before
Apply — nothing has judged those yet.  Two rows that show one auto
name and that the job does not list (a Junos `lo0.0` beside `lo0`)
are one interface, and hold nothing.

What is not counted:

* A Junos reference to unit 0 of an interface (`lo0.0` where the
  interface is `lo0`) is that interface, and no second one.  A config
  that gives unit 0 a stanza of its own beside its port (a VyOS `vif
  0`) has written two interfaces, and they are counted.
* A VLAN interface on a target that writes it from its VLAN (AOS-S)
  keeps its name by design: it is neither dropped nor left for want
  of a name, and shares it with nothing.
* Between two configs of one vendor nothing is listed unless an
  entry of yours caused it: no name is classified there, and each
  stands.
* **A name the translator left that is no foreign name where it
  lands.**  Between two codecs of one platform — IOS-XE as CLI
  text and over NETCONF — a name the CLI classifier does not read
  (`GigabitEthernet1`) is still a name of IOS-XE, and none is
  listed.  Across platforms a name is not listed where the target
  itself writes exactly that name for the kind of thing the source
  config says it is.  The kinds are the logical ones a parser reads
  from the config around a name: a VLAN's interface, a loopback, an
  aggregate, a tunnel.  The case that occurs: the `Vlan<id>`
  interface an AOS-S VLAN's address is carried on is `interface
  Vlan10` on EOS, IOS-XE and NX-OS, and such a job is not held for
  it.  The rule is narrow on purpose:
  - never a hardware port — which port of another device a port
    is, is what a declared device answers (an IOS `Ethernet0` is
    listed onto EOS, though EOS reads the name);
  - never onto FortiOS or RouterOS, where any string is a name
    and a port under a foreign one is a port no line finds; and
    never from them, where a name is whatever was typed (a
    RouterOS interface called `vlan100` may carry VLAN 20);
  - never a name that says which port it is on (`agg1.100`);
  - only the spelling the target writes itself: OS10 reads
    `Vlan10` and prints `vlan10`, so an AOS-S VLAN's interface is
    still listed there.

  The translator's `could not classify port name ...; left
  verbatim` warning names every name it left, listed or not.

What still says `completed`, and is yours to check:

* **A name the config only refers to.**  A name in a static route, a
  DHCP pool, a tracking entry or a VXLAN source that the translator
  cannot read is left as it is, with the same `could not classify`
  warning, and holds no job: what those places hold is not always
  an interface (a route to `Null0`, the keyword `dhcp` of an IOS-XE
  route, an EOS DHCP pool's own name, a source address).  `ip route
  10.50.0.0 255.255.0.0 Null0` onto
  RouterOS is `gateway=Null0`, in a job that can be `completed`.
  Read a finished job's warnings for that line.
* **A LAG member the config has no interface for.**  The members
  of an OPNsense lagg are as a rule NICs assigned to nothing, and a
  FortiGate aggregate can name a member that has no `edit` stanza.
  Those two parsers make no interface record for such a member, and
  a target that writes a LAG on each member's own stanza — EOS,
  AOS-CX, IOS-XE CLI, IOS-XR, NX-OS, OS10, Junos — writes the LAG
  with no member, in a job that can be `completed`.  (AOS-S, FortiOS,
  RouterOS and OPNsense write the member list.  So does VyOS for a
  LAG it writes as `bond<N>`; one left under a name it does not read
  as a LAG — a FortiGate `agg1` — comes out an `ethernet` interface
  with no member, in a `partial` job that lists it.)  Compare each
  LAG's members in the output with the source.  An AOS-S port that
  a config names only in a VLAN's list or on a `trunk` line was such
  a port too, VLAN membership included, in release 0.7.7 and
  earlier; its parser now gives it a record
  (see [`vendors/aruba_aoss.md`](vendors/aruba_aoss.md)).
* **A port on AOS-CX under a name AOS-CX cannot read as a port.**
  That renderer writes a port's VLANs only where the port's name
  reads as a port or a LAG.  A port left under its source name, or
  given a name of your own in the port map (`{"3": "uplink-x"}`),
  has its stanza and no `vlan access` / `vlan trunk` line in it.
  A name that was left is listed (`untranslated_ports`); a name you
  chose is not, and that job can be `completed`.
* **A Junos next hop that names a unit keeps the old name across
  vendors.**  `next-hop ge-0/0/0.0` onto EOS is `ip route
  10.9.0.0/16 ge-0/0/0.0`, beside a `ge-0/0/0` that became
  `Ethernet0` (so too onto AOS-CX, IOS-XE CLI, IOS-XR, NX-OS, OS10,
  RouterOS and VyOS).  With devices declared the plan lists the
  route (`stale_next_hops`); without, nothing does.
* **Two spellings the target reads as one name.**  IOS-XE onto Junos
  with `{"GigabitEthernet1/0/2": "ge-1/0/1.0"}` puts both addresses
  under `ge-1/0/1 unit 0`, which Junos reads as one interface; an
  EOS entry `"Ethernet 1"` beside `Ethernet1` likewise.  Names are
  compared by letter case and surrounding space, not as the device
  would expand them.
* **One AOS-S port written in two letter cases, sent apart.**
  `interface 1/A1` and `untagged 1/a1` with an entry for `1/A1`
  only: one port's config on two targets.  The warning says the two
  "do not end together"; give every spelling the same entry.
* **RouterOS as the target.**  With no devices declared, an entry
  that names a port `bridge1`, `vlan5` or a word of your own
  (`WAN`) can leave the port found by no line, or by the new name
  (`set [ find name=WAN ]`), in a job that can be `completed`.
  Section G: only a declared target device can say which hardware a
  RouterOS port is.
* **With both devices chosen in the modal**, the strip no longer
  says which names were not settled, and the job Apply then makes
  holds only for hardware ports (section G): a VLAN interface left
  under its source name is in the output the same, in a job that
  can be `completed`.  Decide such names before you pair.
* **A name the output has no line for.**  A name left as the source
  has it is listed whether or not the target's renderer wrote
  anything for it (a Junos `irb` that has only a description, onto
  RouterOS): keeping it then keeps nothing.  Look for the name in
  the output before you keep it.

### D2. Scope advisories (target-platform notices)

Separate from the severity ladder above, and deliberately so: that ladder
grades **per-xpath** loss for fields the source actually carried, whereas a
scope advisory reports something about the **target platform** that no field
can express — the absence of a whole configuration plane.

`job.scope_advisories` is populated by `run_plan` when the target's *primary
device class* is `firewall` and the source's is not (see § Platform fit).  It
is a notice, never a gate: `job.status` and `job.validation.severity` are
untouched, the render proceeds, and the operator may ignore it.

It exists because that direction was otherwise unreported.  The Tier-3 banner
reads the **source** config, so it says nothing when the source is a switch;
and `/filter/rule` / `/nat/rule` are declared `unsupported` but no canonical
field walks to them, so `validate_against` — which is a *loss* detector, not
an *absence* detector — cannot fire on them either.  Building a canonical
firewall surface would not change that: with `firewall_rules == []` the walker
still yields nothing.  So the notice is stated where it can be stated at all.

Firewall→firewall pairs deliberately raise no advisory: there the source
codec's Tier-3 detector already names the lost policy stanzas.

Rendered on the migrate page as `migrate-scope-advisory-banner`, beneath the
Tier-3 banner.

### E. Compatibility-banner per rename pane

The rename modal (Tier-3 rename) shows an amber banner on a pane
when the active target codec declares that pane's category in
`unsupported_rename_categories`.  Today only the
`cisco_iosxe` (NETCONF) and `opnsense` codecs declare anything —
both list `"snmpv3"` (their SNMPv3 render paths are unsupported), and
`cisco_iosxe` additionally lists `"ports"` (its port-name translation
is an inherited no-op stub, so a port-rename pane against it warns
up-front rather than emitting N per-port warnings).  The banner
prevents the ghost-success
bug where rename overrides apply to canonical but vanish from
rendered output.

### F. Target-profile provenance notice

When you pick a target model in the rename modal, the port names in
its dropdowns come from a target profile, and a name you pick is
written into the generated config exactly as shown.  A line under the
fit-check banner (`migrate-rename-profile-notice`) says what those
names are worth:

* **Port names describe: …** — the one deployment state the profile
  covers.  A port's name depends on how the device is deployed, not
  only on its model: an Aruba 2930F port is `24` standalone and `1/24`
  as a VSF member; a 3810M says `1/24` with stacking enabled and `24`
  without; a Juniper QFX5120-48Y port is `xe-` at its default 10G and
  `et-` at 25G.  If your device is in a different state, the listed
  names are not yours.
* **How the names were established** — *checked against a real capture
  of this model* (re-proven by the test suite on every run), *from
  published documentation* (the vendor's guides, sometimes public
  real-device output; nothing re-checks it), or **not verified for
  this target**, which turns the notice amber.
* **A caveat**, where there is something that would make the names
  wrong on your device — an uplink module that may not be fitted, a
  breakout mode, a stacking prerequisite.

A profile nobody has graded says **Port names not yet graded**.  That
is not a clean bill of health: check the names against your device.
The grade covers port names and counts only — not the profile's
capacity figures (LAG and VLAN ceilings), which are sourced
separately and, for some vendors, not at all.

Known limitation: choosing a profile does **not** change the
auto-translated names.  The translator derives each target name from
the *shape* of the source name — Cisco `GigabitEthernet1/0/1` becomes
Aruba AOS-S `1/1` — whatever model you select, so with a standalone
2930F profile the *Auto target* column shows `1/1` while the profile,
correctly, offers `1`.  Each such row is marked amber with "not on
profile" counted on its section header; left alone, it renders a port
name the selected device does not have.  Pick the right port from the
row's dropdown, or set them all at once through the API's
`port_rename_map` — or declare both devices, which is what section G
is for.

Two things that translation by shape does not do:

* Between two configs of the **same vendor** it changes no port
  name.  A name you did not map stays as it is written — a job from
  a vendor to itself with no entries returns the config's own
  interface names.  Map a port in the Ports pane or with
  `port_rename_map`; to move between two models of one vendor,
  declare both devices (section G).
* A **sub-interface** is not named from the shape of its own name.
  `<port>.<unit>` goes where its port goes, with its unit: a Junos
  `ge-0/0/1.54` onto EOS is `Ethernet1.54` with its `encapsulation
  dot1q`, an IOS-XE `GigabitEthernet0/0/1.54` onto Junos is `unit 54`
  of `ge-0/0/1` with its `vlan-id`.  It is dropped with a port that
  is dropped (listed in `port_drops`, with a warning), and follows a
  `port_rename_map` entry that moves or drops its port.  Its 802.1Q
  tag is not part of its name: where none was read for it from the
  source, the unit is written without one and a warning says so
  (`... went with its port to 'Ethernet1.54' with no 802.1Q tag
  ...`).  Section G lists what is not followed.

Neither held up to 0.7.7 — a same-vendor job renamed and dropped
ports nobody had mapped, and a sub-interface was written onto its
parent port or left under its source name — in jobs that said
`completed`.  Translate again a config that was translated with it;
[`../CHANGELOG.md`](../CHANGELOG.md) says what to look for.

And three things it does do are said in the job's status, not only
in its warnings: it can put two names on one name, it drops a name
the target has none for, and it leaves a name it cannot read as the
source config has it.  Each makes the job `partial` until you decide
the names — section D1.

**Every name has a row.**  The Ports pane has one row for each name
the config uses where a port name goes.  A name the translation
renamed or warned about is under its kind (link aggregations, VLAN
SVIs, loopbacks, ...), and so is every hardware port; every other
name that is no port — a LAG, a VLAN interface, a loopback or a
tunnel the job left as it was — is under *Other names in the
config*, the last section.  A translation from a vendor to itself
renames none of them and warns about none, so that section is
where you rename or drop one.  On the API the two lists are
`source_ports` and
`source_other_names` of every plan response, with or without
devices declared: together they are the names the config uses where
a port name goes.  A `port_rename_map` key outside both has an
effect in two cases: a port the config names only through a
sub-interface of it (an entry for `GigabitEthernet0/0/1` moves or
drops `GigabitEthernet0/0/1.54` where the config has no stanza for
the port), and, where the source platform's names have no letter
case, another spelling of a name in the lists.
`source_other_names` also holds what
a config writes where an interface name goes without naming one —
a route to `Null0`, a VTEP source given as an address.

**A rename or a drop entered on a row of *Other names in the
config* is recorded, and the output does not always show it.**  The
job lists the entry in `port_renames` or `port_drops` and warns
about nothing.  Whether the output shows it depends on whether the
target writes that interface by that name, and for these it does
not:

* a **VLAN interface on AOS-S** (`Vlan10`).  AOS-S writes a VLAN's
  address in the `vlan` stanza, by the VLAN's id: renamed or
  dropped, the output is the same to the byte;
* a **VLAN interface on OS10, EOS and RouterOS** (`vlan100`,
  `Vlan100`), and some on IOS-XE (CLI).  The target writes one for a
  VLAN from the VLAN itself: renamed, the output has an interface of
  the new name and the old one again; dropped, the old one is still
  written.  On RouterOS the renamed one also takes its VLAN id from
  its new name (`vlan100` renamed `vlan97` is written
  `vlan-id=97`), and one with a name of its own (`clustervlan100`)
  can come back as `vlan<id>`;
* a **loopback that is a VXLAN source** (EOS, NX-OS).  A rename is
  shown.  Dropped, its stanza goes and the VXLAN source line
  still names it;
* **Junos `irb`**, the bare name a config lists beside its
  `irb.<unit>` interfaces: neither is shown, and the units stay
  under `irb`.

Over the committed inputs, each onto its own vendor, every other
row of that section did what it said: a LAG, a tunnel, a loopback
that is no VXLAN source, a VLAN interface on AOS-CX, NX-OS, Junos
(`irb.<unit>`) and OPNsense.  The API has always answered the same
request the same way; what is new is that the page offers it.  After such
an entry, read the output: where the old name is still in it, take
the entry back.  A VLAN interface is written from its VLAN, so
renumber or drop the VLAN instead (the VLANs pane,
`vlan_rename_map`) — on EOS, IOS-XE and AOS-S that moves the
interface with it — and make any other such change in the output by
hand.

### G. Model-to-model port mapping

Tell netcanon which device the config came from and which one it is
going to, and it pairs the ports by **position** instead of guessing
from the shape of their names: the third access port of the source
with the third access port of the target, the first uplink with the
first uplink.  That is what makes a standalone Aruba 2930F-48G land
correctly on a 2930M-48G with an SFP+ module in a one-member stack —
`1`..`48` become `1/1`..`1/48`, and the built-in uplinks `49`..`52`
become the module's `1/A1`..`1/A4`.

**In the browser:** translate, open **Interface rename**, and on the
Ports pane choose the *Source device* and the *Target device*.

* A device is a model from a model family — then you also choose its
  deployment mode, the module in each bay and, for a stack, its
  members — or a profile, where no family describes the device yet.
* A stack has one row of controls per member (**+ stack member** adds
  one).  Two stacks pair row by row — the first source member with
  the first target member — whatever numbers the members carry; where
  the numbers differ the strip above the table says which member went
  to which, and each port's row says its member.
* The source device is filled in from the config where the config
  states it; open "Read from the config" under it to see the lines.
  It is a proposal: a `member` or `flexible-module` line shows what a
  device is provisioned for, not what is fitted.  Change it if it is
  wrong.  The line turns amber where the proposal does not stand on
  its own: the config uses port names the device does not have (it
  says how many, and the first few), or the config names no port, so
  nothing could be checked against it.  Where no device could be
  read, the line says why.  While the config is being read the line
  says so; a server that has not answered in twenty seconds is given
  up on, the line says that, and the config is asked about again the
  next time the modal opens.
* The line under the source device, and under a target chosen from a
  model family, says what you declared, how many ports that is and
  the first and last name, and how well the names are established.  A
  bay you did not state is counted as empty, and the line says so in
  amber.  A target chosen from a flat profile keeps the profile notice
  it always had (deployment state, grade, caveat), which states no
  port count.  A source device you chose or edited yourself is said
  not to have been checked against the port names the config uses.
* A declaration the server refuses — a member number the mode does
  not have — turns the line red and says why, in the server's words.
  It is still sent with Apply, which the server then refuses: the
  output is left as it was, and the footer of the modal says *Not
  applied* with the server's reason until you change something in
  the modal or the footer has its next thing to say (the footer's
  line is about the last thing done: an edit clears it, looking at
  another pane does not).  A line that
  says the device *could not be checked* is not a refusal: the preview
  did not arrive, and Apply sends the device for the server to compile
  itself.
* Before Apply the table lists the ports the config uses, in the
  declared source device's port order (undeclared: in the order of
  the config's interface stanzas; an AOS-S port that has no stanza
  comes after those that have one, in port order).
* **Apply** pairs the ports.  The table then shows, per source port,
  the target port and the position that decided it ("uplink 1"), and
  a row for every name with no place on the target.
* The strip above the table counts **what happened**: ports that
  stand where they were paired; paired ports your own entries dropped
  or sent elsewhere; ports with no place; ports you gave a place; PoE
  or speed lost.  Green means the job needs nothing from you, amber
  that a name needs a decision or a route still names a port that
  moved, red that the job is held (a target port was given two
  sources, or a RouterOS port is not found by its hardware).  If
  the source device you chose is not the one the config is of,
  nothing can be paired: the strip is headed **No port was paired
  by position**, in amber, whatever is accepted afterwards.  After
  Apply the footer says what the strip says; "Applied." by itself
  is for a job the strip has nothing to say against.
* **Accept as shown** records the outcome on screen as your decision
  for each undecided name (a dropped port stays dropped, a kept one
  stays where it landed), and Apply confirms it.  It is a decision
  about the pairing on screen: with other devices declared it is
  forgotten at the next Apply, and it is not kept across a page load.
* **If Apply is greyed out it says why**, beside the button.  Two rows
  that end on one target name hold it.  With both devices declared
  and not yet applied, only a collision between entries of your own
  does: two ports the name-shape translation put on one name are what
  the pairing by position mends.
* A target chosen with no source device works as before: its port
  list fills the choices in the table, and nothing is paired.  Where
  that leaves port names in the output the target does not have -- a
  switch that stands alone translated for a stack keeps `1`, `2`, `3`
  where the stack's ports are `1/1`, `1/2`, `1/3` -- the strip says
  so in amber, with the count, and Apply's footer says the ports
  were not paired.  Choose the source device and apply again.  A
  target device belongs to the target codec it was chosen for.
* The modal does not block the page: translate again behind it and it
  is redrawn from the new job; an Apply still out for the old one is
  given up.  An Apply the server does not answer in two minutes is
  given up too, and says so.
* Where a vendor has model families, the target model list has the
  family models first and the vendor's flat profiles after them,
  under "Profiles — one fixed port list": a switch can be in both,
  under the same words.
* The modal can be worked from the keyboard.  Tab stops at every
  control it shows, a row's "drop" included, and Esc closes it and
  gives the focus back to the button that opened it.  On a closed
  list of target ports, typing a port's name chooses that port.
* Your own entries — in the ports pane and in the VLAN, user and
  SNMP panes — are kept in the browser by source codec, target
  codec and the config's host name, and put back when the modal
  opens on such a config again; the footer says so.  Two configs can
  share a host name: an entry kept for a name the config on the page
  has no row for is left out, the footer says how many were, and
  they stay kept for the config that has the name.  In
  the VLAN pane a number that is no VLAN id (1 to 4094) is not an
  entry: nothing is sent for that VLAN while the field holds it,
  and the field has a red edge.

**Through the API** the same steps are:

1. `GET /api/v1/migration/model-families` lists the device families
   netcanon models, with each one's models, modes and modules.
2. `POST /api/v1/migration/detect-deployment` reads the source device
   out of the config itself, where the config states it (below).
3. `POST /api/v1/migration/inventory` shows the ports a declared
   device has, by their real names, before you translate anything.
4. `POST /api/v1/migration/plan` with `source_deployment` and
   `target_deployment` does the translation.

```json
{
  "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": "...",
  "source_deployment": {"mode": "standalone",
                        "members": [{"model": "JL260A"}]},
  "target_deployment": {"mode": "stacked",
                        "members": [{"model": "JL322A",
                                     "modules": {"A": "JL083A"}}]}
}
```

A model is named by its key or by its part number.  `mode` says how
the device is deployed, which decides its port names; leave it out (or
send it empty) and the family's default is used, and the response
tells you which that was.  `modules` says what is fitted in each bay; a
bay you do not mention is treated as empty, and reported back as *not
stated*.

**A stack on both sides.**  Each `members` list can hold more than
one switch:

```json
{
  "source_deployment": {"mode": "vsf",
                        "members": [{"model": "JL260A", "id": 1},
                                    {"model": "JL260A", "id": 3}]},
  "target_deployment": {"mode": "stacked",
                        "members": [{"model": "JL322A", "id": 1,
                                     "modules": {"A": "JL083A"}},
                                    {"model": "JL322A", "id": 2,
                                     "modules": {"A": "JL083A"}}]}
}
```

`id` is the member's number — the one the device prints in front of
each of its port names (`3/5`).  Leave it out and the members are
numbered in the order listed, from the lowest number the mode allows
that no other member states (1, 2, 3 ...);
`port_mapping_plan.source.members[].member_id` says what each got.
The numbers must be the config's own: a config that names `3/5`
against members numbered 1 and 2 comes back with every `3/...` name in
`off_inventory`.  (The response calls the number `member_id`; in a
request it is `id`.)

Two stacks are paired member by member **in the order the two lists
give them**: the first member you list for the source with the first
you list for the target, whatever their member numbers are.  The
fabric above, numbered 1 and 3, lands on the stack numbered 1 and 2
with `3/5` as `2/5`, and the plan says in a line which member went to
which — between two declared deployments, for a member the config
uses and whose ports you did not decide one by one.  The order of
each list is therefore yours to choose: list the members in the order
you want them paired.  If that puts a member beside a member of its
own number instead of on it — for instance the same two members
listed 2, 1 on one side and 1, 2 on the other — the plan says so in a
line of its own (`... paired with a member of ANOTHER number while
one of the two numbers is declared on both sides ...`): a
**crossing**, which is what a list typed in another order looks like.
The job is still `completed`, because the order is yours to choose.

Within a member the ports pair as they do on one switch — a 2930F
member's built-in uplinks become the module ports of the 2930M member
in the same position.  A port never changes member to find a place.
Where a source member has more access ports than the target member in
its position, the extra ones are unplaced even if another target
member has ports to spare; and a source member beyond the target's
last has no place at all (`reason: "no-member"` on each of its
`unplaced` entries) — its used ports are dropped and listed, like any
other unplaced port.  A target member the source has no member for is
listed in `unused_target` and left alone — unless the config names
ports of a member you did not declare: those names are off-inventory
and stay as they are, which can be on that member.

Two things are yours to do.  A target VSF fabric of more than one
member needs at least one port of each member for its links, and the
pairing does not know
which: it can give configuration to every port.  Send the source
ports that land on the links elsewhere, or drop them, in
`port_rename_map`.  And what makes the switches a stack is not
translated: see *The stack's own configuration* under Known
limitations.

**An AOS-S config usually states its source device.**  An AOS-S `show
running-config` states its own hardware: the chassis part number, the
modules it is provisioned for, and whether it is stacked.
`POST /api/v1/migration/detect-deployment` with `{"source": "<codec>",
"raw_text": "..."}` reads those lines and returns a `deployment` you
can send straight back as `source_deployment`.  It is a proposal to
confirm, never applied by itself, and it tells you how far to trust it:

* `evidence` — the hardware lines it was read from, each as far as its
  part number (a member line's MAC address comes after that and is not
  read).  They are fragments to confirm against, not whole config
  lines;
* `notes` — what those lines cannot show, and what the reading left
  out or had to choose.  A stack member or a module line states what
  the switch is *provisioned* for; a member can be configured before it
  is connected, and a bay can be provisioned for a module that is not
  fitted.  A member, module or `module 1` line that could not be read,
  a member or a bay stated two ways, a banner and a `module 1` line
  that disagree, a second banner or stanza, a banner or `module 1`
  line of one switch beside a stanza are each said here.  A note names
  a few member numbers and counts the rest, and says when `evidence`
  or the notes themselves were cut short;
* `missing_ports` / `consistent` — the check against the config itself:
  port names the config uses that the proposed device does not have.
  One cause is a module the config does not state; another is a partial
  paste.  `missing_ports` holds the first few hundred and
  `missing_port_count` the whole number; a name longer than 128
  characters is cut to that, ending `…`.  `consistent` is `true` when
  none is missing, `false` when some are, and `null` when there was
  nothing to check: nothing was proposed, the text could not be
  parsed, or it names no port (only its top was pasted).  `null` is
  not a pass.

`deployment` is `null` unless every device the config names is a model
of one family, in a mode that is not in doubt, and the result compiles.
So it is `null` when the config does not state its device (only part of
it was pasted, say); when no model family describes a part number it
states (`unknown_parts`); when the members it names belong to different
families; when what it states does not compile — a module the bay does
not take, a member number outside the mode's range, more members than
the mode allows; and when the vendor has no detector yet.  The first
of `notes` says which.  None of these is an error: the answer is a 200
either way.
Detection reads Aruba AOS-S configs today; no other vendor has a
detector yet.

A proposal lists a stack's members by member number, lowest first,
whatever order the config states them in.  Two stacks are paired in the
order their declarations list the members, so that is the order to
check before sending it back.

**Both devices must be declared.**  A source without a target, or a
`target_deployment` without a source, is a 422.  The response carries
`port_mapping_plan` when both devices were declared and the job
rendered, and its `applied` says whether a pairing was made.  If the
plan is `null`, nothing was paired — check the spelling of the field
names, because the plan request ignores top-level fields it does not
know (a misspelt `source_deployment` beside a `target_profile` is
simply not seen).  Whatever was declared, the response lists the
names the source config uses where a port name goes:
`source_ports`, its hardware ports, and `source_other_names`,
every other one — a LAG, a VLAN interface, a loopback.  A
`port_rename_map` entry is keyed by a name from either.

What you get back, on the job's `port_mapping_plan`:

* **`applied`** — `false` when no pairing could be made at all: one
  side is a profile that lists no ports or lists a name twice, or a
  RouterOS config gives a port the name another port of the source
  device still has, or looks two interfaces up by one factory name.
* **`pairings`** — every source port and the target port the pairing
  chose for it, flagged (`slower`, `poe_lost`) where a faster port
  lands on a slower one or a PoE port on a port without PoE.  This is
  the pairing *before* your own `port_rename_map` was applied: a port
  listed in **`overridden`** went where you sent it, and
  `port_renames` / `port_drops` on the job say where every port ended
  up (on a RouterOS target, `target_hardware` as well: a port can be
  on a port of the device under a name of its own).
* **`overridden`** — source ports whose pairing your `port_rename_map`
  replaced.
* **`unplaced`** — source ports with no place on the target: a 48-port
  config on a 24-port switch, or uplinks with no uplink ports to go
  to.  An access or uplink port is **dropped from the output** and
  listed in `port_drops`: it is never moved onto a spare port of
  another kind, and never left in the output under its old name.  Each
  entry's `dropped` says what happened to that port, and `landed` the
  name it ended under if it was kept.

  A management port with no management port in the target model is
  treated differently.  It is handed to the ordinary port translation
  — the *name-shape translator*, which derives a target name from the
  shape of the source name and knows what each target does with
  out-of-band management (on AOS-S it becomes the `oobm` block).  If
  that kept it, the entry says `dropped: false` and where it `landed`;
  if the target has no form for a management port at all, the
  translator drops it and the entry says `dropped: true`.  Either way
  it needs your decision: netcanon does not know whether the target
  device has a management interface (an Aruba 2930F has none).
* **`off_inventory`** — names in the config that are not ports of the
  source device you declared.  They are handed to the name-shape
  translator, which may rename them or drop them.  Usually this means
  the source model, its mode, its modules or — for a stack — its
  members' numbers were declared wrongly: check them.
* **`labelled_ports`** — source ports the config knows by a name of
  its own, each with the port's name in the device model.  RouterOS
  only: it keeps a port's factory name (`ether2`) beside the name you
  gave it (`core-a`), and every other line of the config uses yours.
  Such a port is paired by its factory name and goes by YOUR name
  everywhere else — in `pairings`, in the job's lists, and as the key
  of a `port_rename_map` entry.  An entry keyed by the port's factory
  name is taken for it.
* **`sub_interfaces`** — sub-interface names (`ge-0/0/0.54`) that
  followed their parent port, with the name each was given — the
  parent's name on the target with the unit after it — or `null`
  when the parent was dropped and the sub-interface with it.  Between
  two configs of the same codec and across vendors alike.  Where the
  target's capability matrix lists the 802.1Q tag of a routed
  sub-interface as unsupported, the interface is still written under
  that name, without the tag: the job is `partial` and the validation
  details list the tag.
* **`untagged_units`** — sub-interface names that went with their
  parent port across vendors although no 802.1Q tag was read for
  them from the source, each with the name it has in the output.
  The tag is not in the name, so the output has an interface of
  that name and no VLAN for it — and no tag for the validation
  details to list.  Such a unit is not in `sub_interfaces`: it stays
  in `off_inventory` and in `unresolved_ports`, so the job is
  `partial` until your `port_rename_map` names it.  A unit gets
  here from a source platform whose parser reads no tag for a
  sub-interface (AOS-CX, OS10), from a stanza whose tag line the
  parser did not read (an IOS-XE CLI, NX-OS, AOS-CX or OS10 config
  pasted without its indentation; an IOS XR or EOS one is refused),
  and from a config that states none.
* **`unvouched_units`** — sub-interface names that went where their
  port went, tag and all, and that the plan does not count as having
  followed, each with the name it has in the output.  The plan takes
  a name for a unit of a port only where the name spells the port as
  the config does, so two kinds are here: a unit typed in another
  letter case than its port (`gigabitethernet1/0/1.54` under
  `GigabitEthernet1/0/1`, where names have no letter case) and a
  unit of a unit (`ge-0/0/1.54.2`).  Each stays in `off_inventory`
  and in `unresolved_ports`, so the job is `partial` until your
  `port_rename_map` names it; a line of the plan says which, and
  where each went.
* **`displaced`** — names nobody decided that the name-shape
  translator would have put on a name another interface ends on, or
  on a port of the target: a name from either group above, or a
  logical interface such as an aggregate.  Rather than merge two
  interfaces into one, netcanon **drops** such a name and says so.
  Where every name in a clash was undecided, one keeps the name — a
  port of the declared source if there is one, otherwise a hardware
  port, otherwise the first — and only the others are dropped.
* **`fused`** — target ports that received more than one source name.
  The pairing never does this and an undecided name is displaced
  before it can, so an entry here means your own `port_rename_map`
  points two ports at one name.  Names are compared as the platform
  tells interfaces apart: on AOS-S or IOS `1/a1` is the port `1/A1`;
  on FortiOS and RouterOS, where you choose interface names, `DMZ`
  and `dmz` are two interfaces; and on a platform that names every
  interface itself in lower case (Junos, OPNsense) `GE-0/0/2`
  is `ge-0/0/2` misspelt, and is that port.  On RouterOS two ports on
  one piece of hardware under two names are fused as well.
* **`off_target`** — names your `port_rename_map` put a port on that
  the declared target device does not list for its ports.  Allowed,
  and reported.  **Only case and surrounding space are understood.**
  An abbreviation the device accepts (`Gi1/0/1` for
  `GigabitEthernet1/0/1`) is not recognised as that port: it is
  listed here, the job can still be `completed`, and the port it
  names can end up with two source ports on it without appearing in
  `fused`.  Use the names `POST /inventory` prints.  Between two
  configs of one codec a unit of a listed port (`ge-0/0/7.54`) is not
  off-target; across vendors it is not for an entry whose SOURCE
  name is a sub-interface (`GigabitEthernet1/0/1.54` given
  `Ethernet1.54`), which is where netcanon itself puts a unit.  On a
  RouterOS target a NAME you give a port is not
  listed here while the port's hardware has a place, or while the
  port is in `unbound_ports`; the plan says in a line of its own what
  became of the entry.
* **`target_hardware`** — RouterOS targets only: source names whose
  port is on a target port that is not the name they have in the
  output, each with that port.  RouterOS finds a port by its factory
  name, so every port the mapping places that the config has an
  interface for — from any source vendor —
  is looked up by the port of the target it is on.  A port you had
  named in a RouterOS config keeps the name, and an entry whose
  target is not a port of the declared target NAMES the port; in both
  cases the hardware is where the mapping put it
  (`set [ find default-name=sfp-sfpplus2 ] name=core-a`).
  `port_renames` records names, so it has no entry for such a move;
  this field does, and `fused` and `unused_target` count the port
  where its hardware is.  A port nobody placed that you kept under a
  name is still looked up by the factory name it had: it is listed
  here if the target has a port of that name, and in
  `source_hardware` if it has not — or in `unbound_ports`, if the
  name you kept it under reads as another kind of interface, since no
  line is then written for it.
* **`source_hardware`** — between two RouterOS configs only: ports
  nobody placed that the output still looks up by the factory name
  they had on the source device, which the declared target does not
  have — one you kept by NAMING it, or one the config names that is
  not a port of the declared source.  Give the port a port of the
  target, or drop it.
* **`unbound_ports`** — RouterOS targets only: ports that no line of
  their own in the output looks up by their hardware, each with that
  hardware.  The finished output is read back to find them, and each
  port is judged by its own line.  Three ways.  The port's name reads
  as another kind of interface: RouterOS output has no Ethernet line
  for a name shaped like a VLAN, a bridge, a LAG or a loopback
  (`bond1`, `bridge-uplink`, `vlan-trunk`, `uplink.10`, `lo0`),
  whoever chose the name — and between two RouterOS configs that
  holds for a port nobody placed as well, which is then listed with
  the factory name it had.  Or the mapping placed a port the config
  has no interface for — it names it only as a LAG member or in a
  route — and your entry gave it a name that is no port of the
  target, which the output then uses (`slaves=`, `gateway=`) and
  nothing defines.  Or you gave two ports of another vendor one name:
  the output finds the first by it, and the second is listed.  The
  entry for such a port is not listed in `off_target` as well.  The
  job is `partial` while this is not empty: name the port with a port
  of the target (that moves it there), or — where the config has an
  interface for it — with a name of its own that does not read that
  way.
* **`landed_off_target`** — logical names nobody decided (a VLAN
  interface, an aggregate) that the name-shape translator gave a
  port-shaped name the declared target does not list — a data port's
  or a management port's (`em1`, `oobm`) — each with that
  name.  Nothing shares the name, so it is not dropped — but its
  config is on a port the device does not have, so it is in
  `unresolved_ports` until you map or drop it.
* **`stale_next_hops`** — destinations of static routes whose next
  hop still names an interface that has another name in the output,
  or is not in it: a
  RouterOS list of gateways (`gateway=ether1,ether2`), a routing-table
  suffix (`ether3@main`), or — across vendors — a Junos unit
  (`next-hop et-0/0/24.0`).  A next hop that is exactly an
  interface's name follows it and is not listed; nor is a list whose
  members only changed places among themselves.  A next hop naming a
  port of the declared source that the config has no interface
  record for is listed.  The job is `partial` while this is not
  empty.  No entry rewrites the route: correct it in the output, or
  keep the names it uses — on a RouterOS target an entry that gives
  each such port its old name (`{"ether3": "ether3"}`) leaves the
  route right, since a name does not decide a port's hardware there.
* **`ignored_overrides`** — entries of a `port_rename_map` whose
  target was blank (empty, white space, or only characters that
  draw nothing), for a name the config uses.  A blank target
  decides nothing.  Through the HTTP API you will not see one: a
  blank target is refused with a 422 before any job is run (send
  `null` to drop).  A caller of the pipeline in Python that passes
  one has it set aside and listed here.
* **`emptied_lags`**, **`shrunk_lags`**, **`lost_routes`**,
  **`lost_dhcp_pools`**, **`lost_tracking`**, **`lost_vtep_sources`**
  — what a dropped port took with it.  A LAG loses a dropped member;
  a static route or a DHCP pool that names a dropped port is removed
  whole, even if the route also has a next-hop address; an interface
  that stays loses a VRRP track entry that named the port
  (`lost_tracking` lists the interface); and a VXLAN source
  interface that was dropped leaves the VTEP without the source it
  was bound to.
* **`unused_target`** — target ports nothing ended on.  Between two
  stacks that includes every port of a target member the source has
  no member for.
* **`rename_map`** — the pairing as a rename map, before your own
  entries: what the server handed to the translator for the ports it
  decided.
* **`evidence`**, **`caveats`** — the weaker of the two devices'
  grades for their port names, and what is unverified about either.
* **`warnings`** — the same outcome in sentences.  They are also
  among the job's `warnings`.
* **`unresolved_ports`** — the used source names that still need a
  decision from you.
* **`source` / `target`** — what each declaration resolved to: the
  model, the mode, each member's id and modules, and how well the port
  names are established.  That grade is about the names at each end;
  it does not mean the pairing itself was observed.

The job is `partial` rather than `completed` while `unresolved_ports`
is not empty: a used port that was dropped for want of a place, a
management port with no management port in the target model, a name
that was off-inventory or was displaced — and that you have not
decided yourself.  An entry for that port in `port_rename_map` — a
target name, or `null` to drop it — is you deciding it.  It always
wins over the pairing, on `/plan` and on every per-pane endpoint.  A
target is read as the target device spells it (`1/a1` is `1/A1`)
where another letter case cannot be another interface — the platform
has no case, or names every interface itself in lower case; on
FortiOS and RouterOS it is stripped and taken as typed.  A blank
target is ignored.  The
job is also `partial` while `fused`, `stale_next_hops` or
`unbound_ports` is not empty, whatever you acknowledged, and when no
pairing could be made at all.  `unresolved_ports` also holds every
name in `landed_off_target`.  A port the mapping PLACED that no line
of its own looks up (`unbound_ports`) holds the job.  A port with no
place that you keep under a name is your decision: it is reported in
a line (and in `source_hardware` between two RouterOS configs) and
does not hold the job — with one exception.  Between two RouterOS
configs, a name that reads as another kind of interface (`bridge-x`,
`bond7`, `lo0`) leaves such a port with no line at all, and it is
listed in `unbound_ports` like a placed one, with the factory name it
had.

**Devices no family describes yet** can be declared by the key of a
target profile instead (`source_profile` / `source_module`,
`target_profile` / `target_module`).  The profile is read as one
device in the one state it documents, with its ports in the order the
profile lists them; the plan warns that this order has not been
checked against the faceplate.  For a profile with modules, leave the
module out to take the profile's default, send `""` to say none is
fitted, or name one (in any case); a module the profile does not list
is a 422.  `target_profile` *without* a source declaration changes
nothing, as before.

**Known limitations**

* Model families ship for a first set of Aruba AOS-S switches only;
  `GET /model-families` is the current list.  Everything else goes
  through target profiles, and a device with neither a family nor a
  profile cannot be declared yet.
* **Only port names are translated.**  An AOS-S config that removes
  ports from VLAN 1 with `no untagged` gets that line back for the
  ports the output tags in some VLAN and lists untagged in none; a
  port another VLAN lists untagged leaves VLAN 1 by that line.  A port
  the source removes and puts in no other VLAN gets no line, and stays
  in VLAN 1 on a factory-default target.  Check VLAN 1 on the result.
* A Catalyst config lists the interfaces of every network module the
  chassis could take, whichever one is fitted, plus an
  application-hosting port.  Declared with one module, the other
  modules' interface names come back as off-inventory, and one that
  would land on a paired port is displaced.  The job is `partial`
  although the model is right, because netcanon cannot yet tell these
  names from a wrongly declared model.
* What is "a port the config uses" depends on how well the source
  codec tells a port from a logical interface.  Loopbacks, tunnels,
  SVIs and LAGs are left out, and so is a name only a route or a DHCP
  pool mentions unless the codec recognises it as a port (`Null0` is
  not one).  Some firewall pseudo-interfaces the codec does not
  classify are still reported as off-inventory.  So is an
  `interface Null0` stanza (a common hardening stanza on IOS), and a
  VRRP `track <object number>` is read as a port name and can be
  reported as displaced.  Neither means the source model is wrong.
* A source config that spells a port another way than the device
  prints it (`gigabitethernet1/0/1`, `Gi1/0/1`) is not matched to the
  model: every such name is off-inventory.  A real `show
  running-config` prints the full name; a config built from a
  template may not.
* **RouterOS: a name and a move.**  A port you had named is paired
  by its factory name and, between two RouterOS configs, keeps your
  name while its hardware moves; onto any other vendor it takes the
  name of the port it was paired with.  An entry of
  `port_rename_map` is keyed by the name the CONFIG uses for the
  port — yours, where you gave one.  With devices declared an entry
  keyed by the factory name of such a port is taken for it; without,
  it matches nothing and is ignored with a warning.  Whether an
  entry's target is a move or a name is decided from the declared
  target's port list and from nothing else: `sfp1` names the port on
  a device that has no `sfp1`, and the plan says in a line that it
  was taken as a name.  A name you gave a port that is itself a port
  of the target is not kept — there it could only be that port — and
  the port takes its paired port's name.  If the config calls one
  port by the name another port of the source device still has, or
  looks two interfaces up by one factory name, no pairing is made at
  all.  **Without devices declared an entry never moves a port**: it
  names it.  The output then finds the port by the factory name it
  had where the config states one (a `set [ find default-name= ]`
  line, or a name of the form `etherN`); a port the export mentions
  only elsewhere has none recorded, and naming it renders a lookup by
  the new name (`set [ find name=WAN ]`), which matches no port —
  declare both devices, or add the port's `/interface ethernet` line.
* A RouterOS port named so that it reads as another port (a bridge
  called `SFP-SFPPLUS1`) is translated by that reading, as it is
  without devices declared, and is displaced if that puts it on a
  port of the target.  And a port named so that it reads as a LAG, a
  VLAN, a bridge or a loopback is paired as the port it is, but the
  RouterOS renderer goes by the shape of the name: for `bond1` or
  `bridge1` it writes no line for the port, and for `vlan10` a VLAN
  interface on another port — with or without devices declared.  With
  devices declared the plan lists such a port (`unbound_ports`) and
  the job is `partial`; give the port another name in
  `port_rename_map`.
* A port the mapping placed that the config names only as a LAG
  member or in a route has no line of its own in RouterOS output.
  Naming it in `port_rename_map` writes the name where the port is
  referenced and nowhere else; the plan lists it (`unbound_ports`)
  and the job is `partial`.  Give such a port a port of the target,
  not a name.  A port with NO place that you keep under a name is
  written the same way — into `slaves=` or `gateway=`, defined by
  nothing — and that is said in a line of the plan, not in
  `unbound_ports`: the job is `completed`, because keeping it was
  your decision.
* RouterOS output writes a LAG's members and a route's next hop
  unquoted, so a name with white space or a comma in it breaks the
  line it is written into, whether or not the port has an interface.
  A placed port with no interface is still reported under such a
  name in the ordinary cases (`my port`, `a,b`).  It is not where the
  name begins with a comma, `@` or `%`, holds `@` or `%` ahead of the
  white space or comma, is wrapped in double quotes, or has a line
  break in it: the entry is then listed in `off_target` only.
* **A next hop that is not exactly an interface's name is not
  followed** when the interface moves: a RouterOS route with several
  gateways or a routing-table suffix, and — across vendors — a Junos
  unit next hop.  The plan lists the route (`stale_next_hops`) and the
  job is `partial`.
* **A non-zero unit of a Junos management port** (`me0 unit 5`)
  follows its port under a name Junos does not accept
  (`set interfaces me0.5 unit 0 ...`).  Map it by hand.
* A FortiGate VLAN interface the codec reads as a physical port
  (`DMZ` beside a port `dmz`) or as a management port (`MGMT`), and
  its stock `fortilink` aggregate,
  are given port-shaped names by the name-shape translator.  They are
  displaced where that name is a port of the target and listed in
  `landed_off_target` where it is not; either way the job is
  `partial` until you decide them.
* A **sub-interface** follows its parent port, with its unit, and
  is dropped with a port that is dropped — between two configs of
  the same codec and across vendors (`GigabitEthernet1/0/1.100` onto
  Junos is `unit 100` of the port its own port was paired with).
  What the target makes of `<its port>.<unit>` is the target's: a
  platform with no routed sub-interface still gets an interface of
  that name, without the tag (a Junos unit onto AOS-S is `1.54`,
  which is no name of an AOS-S port — there a tagged routed
  interface is a VLAN), in a job that is `partial` because the
  validation details list the tag.  Map such a unit by hand.  Two
  cases to look for.  A unit with **no tag read from the source** (a
  platform whose parser reads none — AOS-CX, OS10 — a line the
  parser did not read, or a config
  that states none) leaves the validation nothing to list, on any
  target: the unit is written under `<port>.<unit>` with no VLAN.
  It is recorded in `untagged_units`, the job is `partial` until
  you name it, and a line of the plan says which units; without
  devices declared a warning says the same of each, and the job's
  status does not move for it (section D1 says what it moves for
  there).  Between two configs of ONE
  vendor none of that is said — and a tag the parser does not read
  (AOS-CX, OS10) is lost there as well, as it is on every path,
  with nothing in the job to report it.
  And **VyOS and FortiOS take the VLAN id from the number in the
  name** (`vif <unit>`, `set vlanid <unit>`): a source unit whose
  number is not its tag — IOS `GigabitEthernet0/0/1.54` with
  `encapsulation dot1Q 300` — comes out tagged 54, in a `partial`
  job.  Check the VLAN id of every sub-interface on those two.

  Not followed across vendors: a unit of a **loopback** or of a
  **management port** (a Junos `lo0.5` is put on the target's
  loopback beside `lo0`, and the job warns that two names share
  it) — a management port by its name (EOS `Management1.5`) or by
  what its config says of it (the Catalyst port in `Mgmt-vrf`,
  whose name reads as any other port's); a unit of a port the
  source codec's classifier does not know
  (a channelized Junos `xe-0/0/6:2.10`), which stays under its
  source name; a reference to Junos unit 0 (`ge-0/0/1.0`), which is
  the port itself on every other platform, and an interface
  numbered 0 (a hand-written `interface Gi0/0/1.0`, or `.00`), which
  stays under its source name; a name that ends in more than ten
  digits, which no platform numbers a sub-interface with and which
  stays under its source name too; and a VLAN
  interface that
  is only NAMED like a unit (FortiOS `port1.55`, RouterOS
  `ether1.55`), which is a name of its own.  Between two configs of
  one codec each of these keeps its name, and a unit of a LAG or a
  loopback (`ae0.100`, `lo0.5`) follows an entry for its LAG or
  loopback.  Where names have no letter case a unit typed in
  another case than its port (`gigabitethernet0/0/1.54`) is still
  that port's unit.  With devices declared that one is not counted
  as having followed, and neither is a unit of a unit
  (`ge-0/0/1.54.2`): each is listed as a name the declared device
  does not have, and asks for a decision.  The plan says of each
  that it moved with its port, where to, and why it does not vouch
  for it (`unvouched_units`, a line of the plan, and the unit's row
  in the rename modal).  Name the unit in the port map, or drop it.
* netcanon does not know whether a model has an out-of-band
  management port.  A source management port with no management port
  in the target model is therefore always left for you to decide,
  even where the translation kept it.
* On an AOS-S module with HPE Smart Rate ports (JL081A), whether a
  port supplies PoE depends on the chassis.  The inventory lists those
  ports without PoE and says so; a PoE warning about one of them is
  not reliable.
* A dropped port can leave a LAG with no members.  The plan names the
  LAG (`emptied_lags`); the VLANs that refer to it are not cleaned up.
  A static route that names a dropped port is removed whole rather
  than kept with its next hop alone; the plan lists it
  (`lost_routes`).
* Not modelled: modular chassis, breakout lanes, and ports a stack
  uses as its links (which carry no configuration on the real device).
* The pairing is a starting point.  Two switches of the same shape
  pair exactly; a switch onto a firewall, or onto a device with a
  different mix of port types, needs a human look.
* **The stack's own configuration** (`stacking`, `vsf`, member
  provisioning, and the `oobm` block, per-member addresses included)
  is not translated.  Only the port names are made right.  The job
  has no warning for it; with a 2930F fabric or a 2930M stack
  declared from a model family, the plan's `caveats` say so.
* An AOS-S config defines a LAG as `trk1` and lists it in a VLAN as
  `Trk1`.  That is one LAG and one name, `trk1`, as a key of a rename
  map — a key in another letter case (`Trk1`) reaches it too, with
  or without devices declared — in `source_other_names`, and in the
  rename modal, where it has one row.  Onto another vendor it has
  its one entry in `port_renames` too.  Between two AOS-S configs
  the LAG is not renamed, so it has none there, and its row is
  under *Other names in the config*.
  A HARDWARE port typed in two letter cases (`A1` in one
  VLAN, `a1` in another, which no device prints) is still two names:
  an entry for one leaves the other as it was, and the job says so
  (`... are one name on aruba_aoss, written in more than one letter
  case, and do not end together`).  Give both the same entry —
  through the API.  The rename modal shows the two spellings as two
  rows; onto another vendor, with no target device chosen, it
  counts two rows on one target as a collision and will not apply.
  That holds for a name typed in two letter cases on any platform
  without letter case (an IOS-XE route that names `loopback0`
  beside `interface Loopback0`).
* A key of a rename map is the name the config uses for the port.
  Where the source platform's names have no letter case — every
  vendor but FortiOS and RouterOS — a key in another letter case is
  taken for that name, when the config writes the name one way and
  that spelling has no entry of its own.  A TARGET written in another
  letter case is the same port on a target without letter case: two
  source ports sent to `Trk1` and `trk1` on AOS-S are on one LAG, and
  the job says so.

### H. Config size limits (a job that says `refused:`)

A few characters of a config can stand for a great deal: `2-4000` is
thousands of VLAN ids, `all` is every one, and every trunk that allows
every VLAN is a member of every VLAN.  So Netcanon counts what a
config makes, and refuses past a limit rather than spend the memory.
It also gives each request a time limit.

**What you see.**  The job is `failed`, its error begins `refused:`,
and the sentence names what was large, how large, and the limit:

> refused: reading the config as aruba_aoss would make 9,009 or more
> different ports named by port ranges; the limit is 8,192 (counted
> over 9 ranges; the last one read: 8009-9009).  This server runs with
> the 'standard' config size limit.  To allow more, set
> NETCANON_CONFIG_LIMITS=large (or unlimited) in its environment and
> restart it; in the desktop application, choose Preferences... ->
> Config size limit.

The migrate page shows it in the red banner; the sanitise page shows
it under the form (the API answers 413); `detect-deployment` still
proposes the device, and says in a note why it could not check the
proposal against the port names; the command line prints it and exits
2.  The job also carries it as data (`refusal`: the limit, how many
were asked for, the limit's number), for a client that must tell "too
large for this server" from "could not be read".  "or more" means the
count stopped at the limit: the whole number is larger.

**One other refusal is not about size.**  A server set to `small` works
on one request that reads config text at a time (below).  A request that
waited its whole time behind another is refused too, and says so:

> refused: the server works on one config at a time, and was busy with
> another for the 20 seconds this request may take; this request was not
> started and its config was not read.  Send it again.  This server runs
> with the 'small' config size limit, the one the public demo uses.  A
> Netcanon you run yourself does not make one request wait for another
> by default.

Nothing is wrong with the config: send it again.  The job's `refusal`
has `at_once` as its limit; the sanitiser and `detect` answer **503**
with `Retry-After` (not 413, which is "too large" and would be the same
answer the next time); `detect-deployment` proposes nothing and gives
the sentence as its note.

A request that got its turn after a wait, and then ran out of time, is
busy too.  It is not told that it was slow; it says how long it waited:

> refused: the server works on one config at a time, and this request
> waited 17.5 seconds for its turn; what was left of the 20 seconds it
> may take was not enough, and it was stopped before reading the config
> as cisco_iosxe_cli began.  Send it again.  This server runs with the
> 'small' config size limit, the one the public demo uses.  A Netcanon
> you run yourself does not make one request wait for another by
> default.

It is answered as the one above is: `at_once` in a job's `refusal`, 503
with `Retry-After` from the sanitiser and `detect`.  (A request that did
not wait and ran out of time is refused for its time: `seconds` in a
job's `refusal`, 413 from the sanitiser.)

Two answers come from the server before any handler runs, and are the
same on every endpoint that reads config text -- the seven that return
a job too, since there is no job to make of a request nobody read:

* **503 with `Retry-After`**, at once, to a request that arrives while
  as many are in flight as may work and wait.  Its body is not read.
  The detail is the busy sentence: "... and 2 more were already
  waiting their turn; this request was not started and its config was
  not read.  Send it again. ..."
* **408**, to a request whose body has not arrived inside the time a
  request may take: "... the request passed the 20 seconds it may take
  while its body was still arriving, and was stopped ..."  The
  connection is closed.

**The limits.**  One setting chooses a column by name.

| Limit | What is counted | `small` | `standard` | `large` |
|---|---|---:|---:|---:|
| `vlan_ids` | VLAN ids that lists and ranges name (`2-4000`, `all`, `except 7`); the 4,094 of a trunk that states no allowed list, where that is every VLAN (IOS-XE, NX-OS, EOS, AOS-CX); on AOS-S, one for each VLAN a port is tagged in (never more than the `memberships` those lines are) | 1,048,576 | 16,777,216 | 67,108,864 |
| `memberships` | one port in one VLAN's port list, or in one LAG | 50,000 | 1,000,000 | 4,000,000 |
| `ports` | different ports that port ranges name; ports that only a VLAN's or a LAG's list names | 2,048 | 8,192 | 32,768 |
| `interfaces` | interface records, wherever one is made | 2,500 | 50,000 | 200,000 |
| `copies` | entries a Junos `interface-range` copies onto its members | 10,000 | 100,000 | 400,000 |
| `words` | words of set commands written out from block-form Junos | 250,000 | 4,000,000 | 16,000,000 |
| `text` | characters of an output; of the nested blocks VyOS set lines are written out as | 8,000,000 | 64,000,000 | 256,000,000 |
| `seconds` | the time one request may take | 20 | 120 | 600 |

`unlimited` is no limit and no time limit.

**Requests at once.**  Every limit in the table is for one request.
Under `small` the server also works on 1 request that reads config
text at a time: a second waits its turn (inside its own 20 seconds), at
most 2 wait, and one more is refused at once as busy.  A request is
counted when its headers arrive, so that one more is refused before
its body is read; and its 20 seconds run from then, for all of it --
the body to arrive, the turn, the work, and the answer to be read.
**Under `small` an answer has the request's seconds to be read in**:
one that has not gone out by then is abandoned and its connection
closed, however much of it was left (a client that reads, however
slowly, is not cut before that).  A server started with `netcanon
serve` on Linux also has the system end the connection of a client
that has taken nothing for that long.  `standard`,
`large` and `unlimited` limit no requests at once.  Pages, `/health`
and endpoints that read no config text never wait; neither does the
command line.

| Platform | Default | How it is set |
|---|---|---|
| Web, Docker, pip | `standard` | `NETCANON_CONFIG_LIMITS=small\|standard\|large\|unlimited` in the environment or `.env`; restart.  A value that is none of the four stops the server at startup |
| Desktop | `standard` | **Preferences... -> Config size limit** (Standard / Large / Unlimited); restart |
| Command line | `standard` | `netcanon sanitize --limits <name>`, else `NETCANON_CONFIG_LIMITS` |
| Public demo | `small` | Not yours to set: the sentence says so, and says what a Netcanon you run yourself allows.  One request at a time |

**Where the `standard` numbers come from.**  `vlan_ids`: 4,096 ports
that each allow every VLAN.  `memberships`: about three times the most
(port, VLAN) pairs a vendor verifies on one device.  `ports`: about
three times the most ports one system has.  `interfaces`: room for a
router with tens of thousands of sub-interfaces.  `seconds`: the
slowest honest request the other limits admit takes seconds on half a
CPU, not minutes.  Every real capture this project holds is far under
the `small` limits.

**What is refused that is real**, so that nobody finds it later:

* Under `standard`: more than 4,096 ports that each state `all`; more
  than a million kept memberships; and an output of more than 64
  million characters — which a few thousand ports that each allow
  every VLAN are when the target writes every id (IOS-XE, EOS: about 19
  KB a port; Junos, NX-OS, AOS-CX and Dell OS10 write a range).  Use
  `large`, or `unlimited` for a config you know.
* Block-form Junos is counted in the words of the set commands it is
  converted to.  The same config pasted as `show configuration |
  display set` is not converted, and is not counted in words.
* Under `small` (the demo): a switch with more than 256 ports that each
  state `all`, or more than 50,000 memberships.
* **A trunk with no allowed line counts as one that states `all`** on
  IOS-XE, NX-OS, EOS and AOS-CX, where such a trunk carries every VLAN
  (on AOS-CX: a `vlan trunk native` line and no `vlan trunk allowed`).
  A chassis whose every port is a trunk with no list is counted port by
  port like one that writes `all` on each, and the sentence names the
  last such trunk: "... the last one read: a trunk with no allowed list,
  which is every VLAN: GigabitEthernet1/0/257".  On Dell OS10 and Junos
  such a trunk carries no VLAN and counts as nothing.

**What the limits do not bound** — requests in flight under every set
but `small`, how many connections a client opens and leaves open, the
size of an answer, a renderer that runs long, and records no limit
counts (static routes, addresses) — is in
[`SECURITY.md`](../SECURITY.md) "Input Validation — Config Text".

---

## Backup-side limitations

The backup concern is architecturally simpler — connection happens
via SSH (Netmiko) / NETCONF / REST with vendor-specific paging
controls.  Operator-visible failure modes:

* **`422 Unknown type_key(s)`** — `POST /api/v1/backups` validates
  every device's `type_key` against the loaded definitions; unknown
  keys reject with a 422 listing both the offenders and the loaded
  set.
* **`type_key` filename grammar** — definition load-time validator
  in [`netcanon/definitions/schema.py`](../netcanon/definitions/schema.py)
  rejects any `type_key` containing `_` or `.`.  The file-store
  filename grammar is `{type_key}_{safe_host}_{timestamp}.{ext}`
  and underscores or dots inside `type_key` make round-trip
  parsing ambiguous.
* **Connection failures** — surfaced on the per-device row of the
  backup-job result with the exception class name and message.
  Mocking is at one factory: `get_collector` (AGENTS.md hard rule).
* **Probe non-match** — backup-side code does not auto-detect
  vendors; the operator declares `type_key` per device.  Migration
  has its own auto-detect probe (see
  [`migration_detect.py`](../netcanon/services/migration_detect.py)).
* **Cisco paging** — Cisco devices use SPACE-injection via
  `connection.cisco_more_paging: true` in the YAML definition.
  AGENTS.md hard rule: never replace this with `terminal length 0`.

---

## Round-trip vs. cross-vendor

Two distinct fidelity surfaces, often confused:

* **Round-trip** — `parse(render(parse(raw))) == parse(raw)` for the
  **same** vendor codec.  The cert harness's primary invariant.
  Per-codec status in
  [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md).
* **Cross-vendor / cross-mesh** — every-source by every-target pass
  through the canonical bridge.  The audit matrix lives at
  [`../tests/fixtures/real/CROSS_MESH_RESULTS.md`](../tests/fixtures/real/CROSS_MESH_RESULTS.md)
  (Phase 1: mechanical drift) and
  [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  (Phase 4: classified into ALIGNED / CODEC_BUG /
  EXPECTED_LOSSY / EXPECTED_UNSUPPORTED / METHODOLOGY_ISSUE_under /
  METHODOLOGY_ISSUE_over / STRUCTURAL_ONLY / TRIVIAL_EMPTY).

A codec can be round-trip clean and still drop fields cross-vendor
(`/snmp/v3-user` is valid SNMPv3 on Cisco CLI source, but the
NETCONF target codec doesn't implement render).  Both numbers
matter; the matrix is honest about both.

---

## Cross-paradigm exceptions

* **`cisco_iosxe` (NETCONF) is a Phase 0.5 stub.**  The render path
  emits ONLY `openconfig-interfaces`.  Its capability matrix
  declares the gap — every non-interface canonical surface is
  `unsupported`.  Operators who need full NETCONF output should use
  the CLI sibling (`cisco_iosxe_cli`) which renders complete config
  text.
* **OPNsense SNMPv3 is Tier 3.**  OPNsense stores SNMPv3 in raw
  `snmpd.conf` snippets, not its config.xml schema; the codec
  declares `/snmp/v3-user` unsupported and lists `"snmpv3"` in
  `unsupported_rename_categories`.
* **MikroTik does not accept foreign hashes.**  RouterOS rehashes
  the supplied password itself, so `_user_secrets._TARGET_ACCEPTS`
  permits only `plaintext` for `mikrotik_routeros`.  Cross-vendor
  hashes always trigger a review comment.
* **Aruba AOS-S as DHCP target.**  AOS-S is a DHCP relay platform
  (`ip helper-address`) — it is not a DHCP server.  Source DHCP
  pools surface as a comment block, not as `dhcp-server pool`
  syntax.
* **A trunk's allowed list means what it says.**  On a trunk an
  empty list is NO VLAN, a list of every id (1-4094) is EVERY VLAN,
  and any other list is the list.  A trunk that states no allowed
  list is read as what its platform does with one: every VLAN on
  `cisco_iosxe_cli`, `cisco_nxos`, `arista_eos` and `aruba_aoscx`;
  no VLAN on `dell_os10` and `juniper_junos`.  Each target writes
  its own form: `switchport trunk allowed vlan none` and, for every
  VLAN, a trunk with no allowed line on IOS-XE, NX-OS and EOS;
  `vlan trunk allowed all` on AOS-CX; `vlan members all`, or no
  members, on Junos; no allowed line for no VLAN on OS10; the VLANs
  that tag the port on AOS-S.  Release 0.7.7 and earlier had one
  value, an empty list, for all three statements, and a trunk that
  allowed no VLAN came out allowing every VLAN on four targets:
  check any trunk translated then whose list is empty or absent on
  either side.  These limits remain, each written in the output or
  here:
  * **AOS-CX cannot be told "no VLAN".**  A trunk with no allowed
    VLAN carries every VLAN there.  For a source trunk that allows
    none, neither `vlan trunk` line is written and a `! review:`
    line in the stanza says what the source said.  The job does not
    report it: list the VLANs the port is to carry, or shut it down.
    What is written is a switched port with no `vlan` line, taken
    here to be an access port in VLAN 1 by the switch's default;
    that default is not established here from a vendor's page.
  * **OS10 cannot be told "every VLAN".**  It has no word for it,
    its VLAN ids end at 4093, and a VLAN must exist before a port
    is put in it.  A trunk of every VLAN is written `switchport
    trunk allowed vlan 1-4094` under a `! review:` line: replace
    the range with the VLANs the switch has.  A list that is not
    every VLAN is written as it stands with no such line, though it
    can name an id past 4093 (`2-4094`) or a VLAN the output does
    not declare.
  * **AOS-S cannot be told "and any VLAN made later".**  A trunk of
    every VLAN is tagged in each VLAN the output declares, and
    nothing in the output marks that more was meant.
  * **`none` on a port that is not `switchport mode trunk` is
    dropped.**  On such a port an empty list and no list are one
    value, and no line is written for it, same vendor included.  An
    IOS-XE port in a dynamic mode that states `switchport trunk
    allowed vlan none` comes back with no allowed line, and carries
    every VLAN if it negotiates a trunk.  A VLAN drop that empties
    the list kept on such a port gives no line and no warning.
  * **A trunk line with no `switchport mode trunk` line is read as a
    trunk** by `cisco_nxos` and `arista_eos`, though a port of
    either platform is an access port until it is told otherwise.
    Such a port is a trunk of the VLANs its lines name, or of no
    VLAN — never of every VLAN: the platform's defaults are a
    trunk's, and are given only to a port that says it is one.
    That holds for the default native VLAN as well: VLAN 1 on such
    a port's list is a tagged VLAN of it, and no output states
    VLAN 1 untagged for it.  The EOS parser reads an allowed line
    below an access line as making the port a trunk, and drops
    its access VLAN, even under `switchport mode access`; the NX-OS
    parser takes the first of the two lines.  (What the switches
    do is not stated here: this is how the two parsers read it.)  Look for such ports in the source: take the
    trunk lines off an access port, or add `switchport mode trunk`
    to a trunk.
  * **A trunk whose list is stated where the parser does not read it
    is a trunk of every VLAN:** a port-channel member that states
    the mode and leaves the list to its port-channel, and a port
    that takes its list from `inherit port-profile` (NX-OS) or
    `source template` (IOS-XE).  Check `vlan members all`, OS10's
    `1-4094` and AOS-S tags on such a port.
  * **A stanza met twice is one interface for its allowed list
    only.**  Its allowed lines are applied to one list, in order;
    each stanza is still written, with the mode it states.
* **A trunk's allowed list holds its native VLAN.**  The list is
  what the trunk carries, the native VLAN among them, and a native
  VLAN the list leaves out is stated and not carried.  The platforms
  do not all write it that way: `cisco_iosxe_cli`, `cisco_nxos`,
  `arista_eos`, `aruba_aoscx` and `juniper_junos` have a native line
  of its own beside an allowed list that may name the VLAN or leave
  it out; on `dell_os10` the untagged VLAN is the trunk's access
  VLAN, beside an allowed line of tagged VLANs; `aruba_aoss` lists a
  VLAN's `untagged` ports apart from its `tagged` ones.  So an AOS-S
  port that is untagged in one VLAN and tagged in others, and an OS10
  trunk with an access VLAN, are written for the first five with
  that VLAN on the allowed line beside the native line
  (`switchport trunk native vlan 10`, `switchport trunk allowed vlan
  10,20,30`).  **Release 0.7.7 and earlier left it off the allowed
  line**, in jobs that said `completed`: where the list decides what
  a trunk carries, that is a port with no untagged VLAN.  Check the
  allowed list of every trunk with a native line that was migrated
  then from AOS-S or OS10, and add the native VLAN to it.  The other
  way, a trunk whose own list leaves its native VLAN out is written
  as it stands on those five; on AOS-S it gets no `untagged` line
  (it was written `untagged` in that VLAN) and a `; review:` line in
  that VLAN's stanza that says so, and on OS10 `no switchport access
  vlan` under a `! review:` line (it was written that VLAN as its
  access VLAN).  Neither line calls the VLAN the source's: its id
  is the output's.  The AOS-S line has three forms.  Of a name the
  output tags in some VLAN, which VLAN 1's `no untagged` line takes
  out of the default VLAN, it says so.  Of a port no line takes out
  it says what HPE's guide says of one (it is in the default VLAN,
  and remains there until it is removed); of a trunk group
  (`Trk<n>`), and of a port the same output puts on a `trunk` line,
  it gives HPE's sentences for a trunk group (a new one is placed in
  the default VLAN; a static one, which is what is written, is
  configured for VLAN membership as a port is).  A VLAN map
  that would bring such a native VLAN INTO its port's list does not
  make it carried, and there are two cases.  Where the map has made
  it one VLAN with a VLAN that the list names (a VLAN of the config,
  or any id of a short allowed list) -- it is given that VLAN's id,
  or the other way -- the native VLAN is
  cleared, so that the merged VLAN stays tagged on every target.
  Where a longer list only covered the new id as a number of a range
  (`native vlan 1000` beside `allowed vlan 2-999,1001-4094`, and
  1000 renumbered to 900) nothing was merged: the new id is taken
  out of the list and the native VLAN is kept, so that the trunk
  carries it on no target.  Each has a `vlan_rename:` warning of
  its own, and both are done whatever the port's mode
  ([`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) § "A trunk's allowed
  list is not what I wrote").  What a switch does with a native
  VLAN outside its list is the vendor's to say: HPE says it of
  AOS-CX (untagged frames dropped); Cisco says it of IOS-XE and
  NX-OS for VLAN 1, and for another VLAN it is an inference from
  Cisco's rule; Juniper states it as a requirement to receive, for
  the ELS grammar this codec writes; for EOS it is not established.
  The sentences are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
  These limits remain:
  * **A port that carries no VLAN untagged, on IOS-XE and NX-OS
    beside one that does.**  A trunk that states no native VLAN has
    its platform's own: VLAN 1 on IOS-XE, NX-OS, EOS and AOS-CX,
    none on Junos.  On the way IN that is read, for a port that
    says it is a trunk (`switchport mode trunk`; on AOS-CX a `vlan
    trunk` line): such a trunk of the four has native VLAN 1 where
    its allowed list holds VLAN 1 -- unless its text says the
    native VLAN is sent tagged (`vlan dot1q tag native`, with
    `exclude control` or without; `switchport trunk native vlan
    tag`; AOS-CX `vlan trunk native <N> tag`), and then it carries
    no VLAN untagged.  On the way OUT a port with no untagged VLAN
    and VLAN 1 on its list -- a Junos trunk with no
    `native-vlan-id`, an AOS-S port that is only `tagged`, a trunk
    whose native VLAN is sent tagged, or that the VLAN pane's map
    cleared -- is written each of the four targets' form for that:
    AOS-CX `vlan trunk native 1 tag`; EOS `switchport trunk native
    vlan tag` (what it then sends for VLAN 1 is not on Arista's
    page); IOS-XE and NX-OS `vlan dot1q tag native`, which tags the
    native VLAN of EVERY trunk of the switch.  So on those two it is
    written only where no port the check reads blocks it: it reads
    the ports written in trunk mode, the ports with trunk lines and
    no mode, and the ports in a mode no mode line is written for
    (dynamic, private-vlan, dot1q-tunnel, fex-fabric and the like),
    and none may carry a VLAN untagged, be in such a mode, or hold
    trunk lines in no mode.  A port written with no mode and no
    trunk line is not counted: on a Catalyst such a port is in
    dynamic auto by default, and should it become a trunk the line
    tags its native VLAN as well.  Otherwise the port is written
    no native line under a `! review:` line, and carries VLAN 1
    untagged by the switch's own default
    ([`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) § "A trunk's
    allowed list is not what I wrote").  The per-port `tag` of the
    Catalyst 9500 High Performance models is not written.  On
    NX-OS, what the line does with an untagged frame it receives
    is a point on which Cisco's pages disagree.  A trunk that sends
    a native VLAN other than 1 tagged comes back with the form for
    VLAN 1 where its list holds VLAN 1 (on IOS-XE and NX-OS, the line
    for every trunk where no port blocks it, and otherwise a review
    line), and with no native line where its list leaves VLAN 1 out:
    the id is not kept.
  * **`vlan members all` beside `native-vlan-id` on Junos.**  A
    trunk of every VLAN that carries a VLAN untagged is written
    `vlan members all` and `native-vlan-id <N>`.  Juniper's page
    asks for the logical interface to be a member of the native
    VLAN, and its procedure names that VLAN on `vlan members`;
    whether `all` takes the native VLAN in is not established.
    Check on the switch that such a trunk receives untagged frames
    into its native VLAN, or name the VLAN on `vlan members`.
  * **A VLAN map that merges a trunk's untagged VLAN with a VLAN
    it carries tagged puts the port on both lines of an AOS-S
    VLAN.**  The six targets that write the port's own lines carry
    the merged VLAN untagged.  AOS-S is written from the VLANs'
    member lists, which the map joins: the merged VLAN's stanza has
    `untagged <port>` and `tagged <port>`, in a job that says only
    `multiple source VLANs mapped to <N> — tagged/untagged port
    lists merged`.  What a switch makes of the two lines is not
    established: take the port off the one that is not meant.
  * **The default of OS10 and of AOS-S is not read as a source.**
    An OS10 trunk's native VLAN is the default VLAN of its switch
    when it states no access VLAN, by Dell's page ("By default,
    native VLAN of a port is the default VLAN ID of the switch.");
    which id that is is a setting (`default vlan-id`) that no Dell
    example and no capture prints as configuration, so it is not
    read, and such a trunk is read as carrying no VLAN untagged.  On
    AOS-S a port is in the default VLAN, VLAN 1, until it is removed
    from it; a port that is on no line of `vlan 1` -- which no full
    config printed in HPE's 16.09-16.11 guides has, but a fragment or
    a template can -- is read as carrying no VLAN untagged.  As
    targets, both are written a form for a trunk that carries none
    (Fixed in the CHANGELOG): OS10 `no switchport access vlan` under a
    `! review:` line, and AOS-S `no untagged` in VLAN 1 for every name
    the output tags somewhere, lists untagged nowhere and names on no
    line of VLAN 1.  An AOS-S trunk that carries
    nothing at all is left as it is: AOS-S has no form for a port in
    no VLAN, and such a trunk stays in the default VLAN.  And an OS10
    trunk with no access VLAN whose allowed line holds VLAN 1 -- the
    AOS-CX LAGs of `vlan trunk native 1 tag`, a Junos trunk of `vlan
    members all` -- has no Dell example, and Dell says "An interface
    cannot be an access and trunk member of the same VLAN.": check on
    the switch whether it takes such a trunk's allowed line, and what
    the trunk then carries untagged; its review line says so.
  * **`no switchport access vlan` on an OS10 trunk is not settled.**
    Dell's page for the command says it resets the access VLAN
    membership (to VLAN 1); Dell's VLAN-stacking notes describe the
    trunk it leaves as "pure trunk ports without any access VLAN
    membership", which "drop any untagged" traffic.  The line is
    written under a `! review:` line that says so -- for a native
    VLAN the list leaves out, and for a trunk with no native VLAN
    unless another record of the interface states its untagged VLAN
    (a native VLAN, or an access VLAN): check what the port carries
    untagged.  It is read back as no
    untagged VLAN, which is what the tree has for a trunk with no
    such line as well: an OS10 trunk with neither line comes back
    onto OS10 with it.
  * **`fortigate_cli`, `mikrotik_routeros` and `opnsense` write the
    untagged VLAN as a tagged VLAN device**, like any other VLAN.
    That includes VLAN 1 of a Cisco, Arista or AOS-CX trunk that
    states no native VLAN: it is such a trunk's untagged VLAN by
    its platform's default, and reaches these three as a tagged
    VLAN 1 device.
    Their matrices declare the native VLAN unsupported; nothing in
    the output marks which device was untagged at the source.  On
    `mikrotik_routeros` every VLAN device of an output is on ONE
    parent -- the config's one port with an address or an allowed
    list, or `bridge1` where there is not exactly one -- whether or
    not that port carries the VLAN.
  * **A Junos output is ELS grammar** (`interface-mode trunk`,
    `native-vlan-id` on the physical interface, the native VLAN among
    the `vlan members`).  On a switch that takes the older grammar
    (`port-mode trunk`) the native VLAN belongs off the members --
    Juniper's knowledge base has it sent tagged there when it is a
    member -- so the output is not for such a switch as it stands.
    As a source, a trunk in the older grammar loses its native VLAN:
    `native-vlan-id` under the unit is not read.
  * **`vlan dot1q tag native exclude control` comes back, where the
    line comes back at all, as the line without its last two
    words.**  It is read as the line for every trunk, which is
    written again where a trunk under it holds VLAN 1 and no port
    blocks it (above); the tree keeps no word for the control
    traffic.
* **A VLAN known only to an "allow-everything" trunk is not
  translated.**  On the six port-centric codecs (`cisco_iosxe_cli`,
  `arista_eos`, `cisco_nxos`, `juniper_junos`, `aruba_aoscx`,
  `dell_os10`) Netcanon reconstructs the VLAN database from the
  config text.  A VID counts as real if it has a `vlan <N>` stanza
  or an SVI, if a port binds it as an access or native VLAN, or if a
  *specific* `switchport trunk allowed vlan` list names it.  A VID
  whose only appearance is a wide range — `1-4094`, `2-4094`,
  `100-3000` — is not translated: such a line means "carry whatever
  exists", so expanding it would fabricate thousands of VLANs the
  operator never wrote.  `switchport trunk allowed vlan 701-710`
  therefore yields ten VLANs on the target; `1-4094` yields none
  from that line alone.  This is a parse-time reconstruction rule,
  not a `CapabilityMatrix` declaration, which is why it appears here
  rather than in a per-codec panel.  See
  [`docs/TROUBLESHOOTING.md`](TROUBLESHOOTING.md) § "My VLANs
  disappeared".

---

## Cross-vendor L3-redundancy grammar reference

Classic FHRP and anycast-gateway are sibling surfaces in canonical —
operators searching for "where does my vendor's X land?" use this
table to find the corresponding canonical field.  Full per-vendor
grammar deep-dive lives in
[`v0.2.0-planning/01-vrrp-canonical/02-per-vendor-grammar.md`](v0.2.0-planning/01-vrrp-canonical/02-per-vendor-grammar.md)
and
[`v0.2.0-planning/02-anycast-gateway/02-per-vendor-grammar.md`](v0.2.0-planning/02-anycast-gateway/02-per-vendor-grammar.md).

### Classic FHRP (VRRP / HSRP / CARP) — `CanonicalVRRPGroup`

Wire-protocol discriminator lives in `CanonicalVRRPGroup.mode`
(`"vrrp"` default, `"hsrp"`, `"carp"`).  Same canonical record;
different bytes on the wire.

| Vendor | Native grammar (canonical mapping) | Canonical `mode` |
|---|---|---|
| Cisco IOS-XE | `interface X / vrrp 10 ip 192.168.1.254 / vrrp 10 priority 110 / vrrp 10 preempt` | `vrrp` (HSRP via `standby` grammar parses but renders as VRRP) |
| Arista EOS | `interface VlanN / vrrp 10 ipv4 192.168.1.254 / vrrp 10 priority 110` (modern multi-line) | `vrrp` |
| Juniper Junos | `set interfaces irb unit N family inet address X vrrp-group 10 virtual-address Y / priority 110 / preempt` | `vrrp` (IPv6 via `vrrp-inet6-group`) |
| Aruba AOS-S | `router vrrp` + `vlan N / vrrp vrid 10 / virtual-ip-address Y / priority 110 / preempt / enable` | `vrrp` |
| FortiGate | `config system interface / edit X / config vrrp / edit 10 / set vrip Y / set priority 110 / set preempt enable / next / end` | `vrrp` |
| MikroTik RouterOS | `/interface vrrp add interface=ether1 vrid=10 priority=110 v3-protocol=ipv4` | `vrrp` |
| OPNsense (BSD CARP) | `<virtualip><vip><mode>carp</mode><vhid>10</vhid><advskew>0</advskew><password>…</password><subnet>Y</subnet></vip></virtualip>` | `carp` (priority ↔ `254 − advskew`) |

### Anycast-gateway — IP-address property, not a group election

Lives on `CanonicalIPv4Address.virtual_gateway_address` /
`virtual_gateway_mac` (and the IPv6 mirror).  Chassis-wide MAC lives
on `CanonicalIntent.anycast_gateway_mac`.

| Vendor | Per-SVI virtual IP grammar | System-wide MAC grammar | Per-SVI MAC override |
|---|---|---|---|
| Arista EOS (VARP) | `interface VlanN / ip address virtual X/M` (`secondary` trailer permitted) | `ip virtual-router mac-address MAC` | none (chassis-wide only) |
| Juniper Junos | `set interfaces irb unit N family inet address X virtual-gateway-address Y` | none (per-unit only) | `set interfaces irb unit N virtual-gateway-v4-mac M` / `-v6-mac M` |
| Cisco IOS-XE SD-Access | `interface VlanN / fabric forwarding mode anycast-gateway` (binds the SVI's primary IP) | `fabric forwarding anycast-gateway-mac MAC` | none |
| Aruba AOS-S / FortiGate / MikroTik / OPNsense | **none native** (declare `unsupported`) | — | — |

### Cross-vendor migration consequences

The cross-vendor story is asymmetric.  Some examples operators run
into routinely:

* **Junos → Arista anycast.**  Translates cleanly: Junos
  `virtual-gateway-address` populates the canonical record, Arista
  renders `ip address virtual`.  Junos per-unit
  `virtual-gateway-v4-mac` collapses to Arista's chassis-wide
  `ip virtual-router mac-address` (review banner if multiple
  distinct per-unit MACs appear in the source).  A unit that has
  an address of its own beside the gateway is written as two
  lines, `ip address virtual <gateway>` and then
  `ip address <own>`; nothing here establishes that an EOS
  interface holds the two together, so check on the device after
  loading that it has both (the same two lines are written from an
  AOS-CX `active-gateway` and an NX-OS anycast SVI).
* **Junos → FortiGate anycast.**  DROPS the data with a review
  banner.  FortiGate has no anycast grammar; the canonical
  `virtual_gateway_address` field is declared `unsupported` on
  `fortigate_cli`, so the migrate-page Unsupported panel fires for
  every IRB unit carrying a virtual gateway address.  Operator must
  rebuild HA via VRRP on the FortiGate side.
* **Arista VARP → IOS-XE.**  IPv4 translates via SD-Access
  (`fabric forwarding mode anycast-gateway`); IPv6 VARP DROPS
  because `/interfaces/interface/ipv6/address/virtual-gateway-address`
  is `unsupported` on `cisco_iosxe_cli` (no fixture coverage today).
* **IOS-XE HSRP → any non-Cisco target.**  The IOS-XE parser folds
  HSRP grammar into the canonical record; targets render VRRP.
  Election timing is operator-equivalent but the wire protocol
  flips — operator must verify both ends agree on VRID / virtual-IP
  on a per-VLAN basis before deploy.
* **OPNsense CARP ↔ VRRP devices.**  The `mode="carp"`
  discriminator carries through.  OPNsense as target renders only
  `mode="carp"` records (`mode="vrrp"` / `"hsrp"` records are
  SKIPPED with a review banner).  Cross-vendor migration *toward*
  OPNsense from VRRP devices currently requires the operator to
  flip `mode` manually, or accept the silent skip.

---

## What is auto-tested

The cross-mesh fidelity audit harness
([`tools/run_full_mesh.py`](../tools/run_full_mesh.py),
[`tools/run_phase4_reconciliation.py`](../tools/run_phase4_reconciliation.py))
runs every `(source codec, target codec, fixture)` triple and
classifies per-canonical-field drift.  Outputs commit as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.  Per-vendor
investigation reports (`phase4_findings_<vendor>.md`) carry the
triage decisions.

The unit-tier real-capture harness
([`tests/unit/migration/test_real_captures.py`](../tests/unit/migration/test_real_captures.py))
asserts three invariants per fixture: parse doesn't crash, parse
populates at least one canonical field, and (for bidirectional
codecs) `canonical(parse(render(parse(raw))))` matches
`canonical(parse(raw))`.

For the live numbers on either matrix, consult the markdown files
named above.  This document deliberately omits hard-coded counts
(per AGENTS.md hard rule on prose-rot).

---

## What this document is NOT

* It is **not** a roadmap.  See
  [`../translator-plans.txt`](../translator-plans.txt).
* It is **not** a contributor guide.  See
  [`../AGENTS.md`](../AGENTS.md).
* It is **not** a security model.  See
  [`../SECURITY.md`](../SECURITY.md).
* It is **not** a per-fixture certification matrix.  See
  [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md).

---

## Reporting issues / feature requests

Bugs and feature requests welcome via the project's issue tracker.
For codec authoring, start at
[`../netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md).

When reporting a translation bug, include:

1. Source codec + target codec.
2. The shortest source snippet that reproduces.
3. Expected vs. actual rendered output.
4. Any review comments / Tier-3 banner contents the UI showed.

---

## See also

- [`../README.md`](../README.md) — quickstart
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — internal four-layer design
- [`../AGENTS.md`](../AGENTS.md) — contributor directives
- [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md) — per-codec certification state (live)
- [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md) — cross-mesh audit matrix (live)
- [`./glossary.md`](./glossary.md) — project vocabulary (Tier 1/2/3, TRIVIAL_EMPTY, ship-before-wire, etc.)
- [`./v0.2.0-planning/01-vrrp-canonical/`](./v0.2.0-planning/01-vrrp-canonical/) — VRRP / HSRP / CARP canonical-model design (Wave B)
- [`./v0.2.0-planning/02-anycast-gateway/`](./v0.2.0-planning/02-anycast-gateway/) — anycast-gateway canonical-surface design (Wave C)
