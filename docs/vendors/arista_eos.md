# Arista EOS — What works for me?

If you operate Arista EOS devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

- **`arista_eos`** — EOS CLI parse + render.  **Certification:
  certified.**  Bidirectional.

The codec covers EOS 4.21 through 4.26 across DCS-7150S, DC1-LEAF
(vEOS EVPN/MLAG), and DuplicatePrivate-style fixtures.  The
underlying CLI grammar is stable from EOS 4.20+; newer LTS releases
parse / render cleanly but aren't covered by a fixture in the
corpus yet — operator captures from EOS 4.27+ are welcome (see
[`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)).

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname`, `domain`, DNS / NTP / `syslog_servers` (`logging host
  <ip>` harvest + render, promotion #11).  `timezone` is declared
  **unsupported** on this codec — see the capability matrix; it does
  not round-trip.
- Interfaces — `Ethernet<N>` and QSFP-breakout `Ethernet<N>/<M>`,
  Loopback, Management1; descriptions, IPv4 + IPv6, VRF binding
- VLANs — ID, name, tagged/untagged member lists
- Static routes
- LAGs (`Port-Channel<N>` reconciled with cross-vendor `ae<N>` /
  `Po<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 — community, contact, location, traps; v3 USM
  with auth + priv per user
- RADIUS — `radius-server host`
- Local users with hashed passwords — `secret sha512 $6$` and
  `secret 5 $1$` form-preserving cross-vendor migration
- MLAG — peer link + per-Port-Channel `mlag <id>` mapping
- VRF definitions (`vrf instance ...`)
- VXLAN — `interface Vxlan1` + `vxlan vlan <id> vni <vni>` mappings
  (ship-before-wire path stabilised)
- Routing instances (`/routing-instances/instance` declared
  supported on Arista — VRF + EVPN paths translate cleanly)

## L3 redundancy: VRRP + VARP anycast-gateway

**New in v0.2.0** (Waves B + C — VRRP and anycast-gateway wire-up).

### Classic VRRP

Multi-line per-group grammar inside an SVI / routed-port stanza.  The
codec accepts both the modern `ipv4` keyword (EOS 4.21+) and the
legacy `ip` form on parse; render always emits the modern `ipv4` form.

```text
interface Vlan30
   ip address 10.0.30.1/24
   vrrp 10 ipv4 10.0.30.254
   vrrp 10 priority 110
   no vrrp 10 preempt
   vrrp 10 track Ethernet1
   vrrp 10 description primary HA pair
   vrrp 10 timers advertise 3
!
```

Sub-commands handled: `ipv4` / `ip` (legacy) / `ipv6` (VRRPv3),
`priority`, `preempt` (+ `no` form), `description`, `track <iface>`
(decrement value lossy), `timers advertise <S>`, `mac-address`
(per-group override), `authentication text` / `authentication md5
key-string`.  Multiple `vrrp <gid> ...` lines on the same interface
converge onto one `CanonicalVRRPGroup` keyed by VRID; multiple VRIDs
on the same SVI surface as multiple records.

### VARP (Virtual ARP) anycast-gateway

DC-fabric anycast — every leaf SVI carries the same virtual IP, no
per-leaf primary on the wire.  Two surfaces:

```text
interface Vlan110
   ip address virtual 10.1.10.1/24
   ip address virtual 10.1.100.1/24 secondary
   ipv6 address virtual fd20:1::1/64
!
ip virtual-router mac-address 00:1c:73:00:dc:01
```

Canonical mapping:

- `ip address virtual X/Y [secondary]` lands on
  `CanonicalIPv4Address` with `ip=""` (no per-leaf primary) and
  `virtual_gateway_address="X"`; the `secondary` trailer round-trips
  via `is_secondary=True`.
- `ipv6 address virtual X/Y` (EOS 4.30+) mirrors the IPv4 path onto
  `CanonicalIPv6Address.virtual_gateway_address`.
- Top-level `ip virtual-router mac-address <MAC>` lands on
  `CanonicalIntent.anycast_gateway_mac` (system-wide; one MAC per
  device, cascades to every VARP IP).
- `ip address virtual source-nat vrf <V> address <Z>` is a DISTINCT
  feature (VARP source-NAT for VRF-leaked traffic, Tier 3) and is
  parse-and-ignored — does NOT pollute the VARP anycast surface.

### Known limitations

- **Per-IP virtual MAC is lossy.** EOS only supports a system-wide
  `ip virtual-router mac-address`; per-address MAC overrides (Junos
  `virtual-gateway-v4-mac` / `-v6-mac`) have no Arista equivalent.
  Cross-vendor renders from Junos sources surface a review banner on
  the migrate page.
- **VARP has no group_id on the wire.**  Discrimination is purely
  structural — `virtual_gateway_address != ""` on the address record
  IS the anycast intent.
- VARP source-NAT (`ip address virtual source-nat ...`) is Tier-3 and
  not modelled.
- **An interface's own address beside a shared gateway is two
  lines.**  From a source that has both on one interface (a Junos
  `virtual-gateway-address`, an AOS-CX `active-gateway`, an NX-OS
  anycast SVI) the output has `ip address virtual <gateway>` and
  then `ip address <own>`.  This codec reads those two lines back
  as two address records, and nothing here establishes that an
  EOS interface holds the two together: check on the device after
  loading that it has both.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model design rationale (`CanonicalVRRPGroup` +
  `mode="vrrp"` discriminator).
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (per-IP companion fields + system-wide
  MAC; § "Arista EOS (VARP)" covers the no-primary edge case).

## Lossy paths

- See per-codec `CapabilityMatrix.lossy` declarations.  Most fields
  parse + render cleanly within the documented surface; lossy paths
  surface only when translating to vendors with sub-field drift
  (e.g. per-IP virtual-MAC overrides collapsing onto EOS's single
  chassis-wide virtual-router MAC).

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall ACLs**
- **NAT**
- **IPsec VPN**
- **QoS**
- **Routing protocols** — `router bgp`, `router ospf`, EVPN
  redistribution policies (`address-family evpn`, route-map in/out
  filters) are parse-tolerant but not auto-rendered to other
  vendors
- **`management api http-commands`** / `daemon TerminAttr` —
  parse-tolerant
- **PKI / crypto material**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`ksator_dcs_7150s64_eos4224.txt`** — DCS-7150S-64-CL on
  EOS 4.22.4M-2GB (256 lines; first Arista fixture); 5 local users
  mixing `nopassword` / `secret sha512 $6$` / `secret 5 $1$`;
  spanning-tree mstp, parse-and-ignore `router bgp` / `daemon
  TerminAttr` / `transceiver qsfp default-mode 4x10G`
- **`batfish_labval_dc1_leaf2a_eos4230.txt`** — vEOS DC1-LEAF2A
  EVPN leaf on EOS 4.23.0.1F (429 lines); MLAG peer link + 5
  Port-Channels, VXLAN1 overlay, 15 tenant VLANs, router bgp 65102,
  VRF definitions, Vlan3009 with VARP virtual-router MAC
- **`batfish_duplicateprivate_eos4211.txt`** — vEOS DuplicatePrivate
  on EOS 4.21.1.1F; private-ASN scenario (router bgp 65001 +
  neighbor remote-as 65001)
- **`karneliuk_a_eos1_eos4260.txt`** — vEOS on EOS-4.26.0.1F; full
  EVPN/VXLAN kitchen-sink (route-maps, BGP EVPN address-family,
  VLAN VNI mappings)
- **`batfish_eos_evpn_vlan_based_leaf.txt`** — Batfish public
  corpus VLAN-based EVPN leaf reference (Apache-2.0).  6 SVIs
  including a VARP secondary on Vlan110 + system-wide MAC.  Wave-C
  reference for Arista VARP wire-up

Spans 4 distinct EOS majors (4.21 + 4.22 + 4.23 + 4.26).

## Common gotchas

- **A trunk's allowed list means what it says.**  A trunk with no
  `switchport trunk allowed vlan` line is read as a trunk of EVERY
  VLAN — the EOS default, which EOS states by the absence of the
  line — and reaches another vendor as that.  `switchport trunk
  allowed vlan none`, and a list emptied by `remove` or `except`, is
  a trunk of NO VLAN.  `add` and `remove` on an interface's first
  allowed line start from every VLAN.  As a target: every VLAN is
  written as
  a trunk with no allowed line (never the ids, which are one line of
  some 19,000 characters); no VLAN is `switchport trunk allowed vlan
  none`; any other list is written as it stands.  Release 0.7.7 and
  earlier had one value, an empty list, for a trunk that allows no
  VLAN and for one that states no list: a `none` trunk came out here
  as a trunk of every VLAN, and a trunk with no list reached Junos,
  OS10 and AOS-S carrying none — check trunks translated that way.
  A port with a `switchport trunk` line and no `switchport mode
  trunk` line is read as a trunk — even after `switchport mode
  access` — though an EOS port is an access port until it is told
  otherwise and keeps a trunk line without acting on it.  That is an
  older fault of the parser.  Such a port is given nothing from the
  default: it is a trunk of the VLANs its lines name, or of NO VLAN
  (`switchport trunk native vlan 999` alone comes back with
  `switchport trunk allowed vlan none`), never of every VLAN.  The
  vendors' own sentences are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunk-that-states-no-allowed-list-platform-by-platform).
- **MLAG is NOT translated** — corrected 2026-09-24; this entry
  previously claimed the parser "round-trips the peer-link mapping",
  which was wrong in both halves.  There is no MLAG or peer record on
  the canonical tree and no codec models one, so neither the
  `mlag configuration` block (domain-id / peer-address / peer-link) nor
  the per-bundle `mlag <N>` marker reaches the canonical tree or the
  rendered output.  What *does* round-trip is the Port-Channel itself —
  its name, members and description, via `CanonicalLAG` — and
  cross-vendor renaming of that name works.  That is a LAG surviving,
  not an MLAG surviving: a bundle that was dual-homed across the peer
  pair becomes an ordinary single-chassis Port-Channel on the target.
  Both halves are now reported in the Tier-3 banner (with the bundle id,
  so you can see which Port-Channels changed meaning) rather than
  dropped silently.  The same defect, and the same fix, applies to Dell
  OS10's VLT — see [`dell_os10.md`](dell_os10.md).
- **`channel-group` emission on member Ethernets** — render-side
  bug fixed early in the codec history (`channel-group N mode
  <mode>` on member Ethernet interfaces was missing); regression
  test pinned in `tests/unit/migration/test_arista_eos.py`.
- **EVPN/VXLAN ship-before-wire** — schema shipped early; render
  + parse for `interface Vxlan1` and per-VLAN VNI mappings stabilised
  in Wave 10β-B.
- **`service routing protocols model multi-agent`** — preserved as
  raw section; not in canonical model.
- **Renaming or dropping `Vlan<N>` in the rename modal is not shown
  by the output.**  A translation from EOS to EOS lists each VLAN
  interface under *Other names in the config*.  EOS output writes
  `interface Vlan<id>` from the VLAN itself: renamed, the interface
  is written under the new name and the old one again; dropped, it
  comes back.  And a loopback that is the VXLAN source can be
  renamed there, but dropped it is still named by `vxlan
  source-interface`.  The job records each entry and says nothing.
  Renumber or drop the VLAN on the VLANs pane, which takes its
  interface with it.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
