# Cisco NX-OS — What works for me?

If you operate Cisco Nexus (NX-OS) data-center switches and want to
know what Netcanon does for you, this is the page.

## TL;DR

- **`cisco_nxos`** — `show running-config` text **bidirectional**
  (parse AND render).  **Certification: certified.**

NX-OS is a distinct grammar from IOS-XE — it gets its own codec, its
own `CapabilityMatrix`, and its own render path.  The codec targets
the NX-OS 9.x+ data-center surface (Nexus 3000/9000-class): L2
switchport + VLAN database, port-channel LAGs, VRFs with RD /
route-target, VXLAN-EVPN (L2VNI + symmetric-IRB L3VNI), HSRP, and the
IPv4 Distributed Anycast Gateway.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, VRF binding
- L2 switchport — access / trunk mode, access-VLAN, trunk allowed-VLAN
  list, trunk native VLAN, port-channel (`channel-group`) membership
- VLANs — ID, name, tagged/untagged port lists (VLAN-centric
  projection from the per-interface `switchport` form)
- Static routes — default VRF **and** per-VRF (`ip route … vrf X`)
- LAGs (`port-channel<N>` reconciled with cross-vendor names like
  `ae<N>` / `Port-channel<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- SNMP v2c community + v3 USM (community, location, contact,
  trap-hosts, v3 users with auth + priv)
- Local users — named NX-OS `role` (network-admin / network-operator
  / custom) + hashed password, form-preserving
- VRFs — name, description, route-distinguisher, route-target
  import/export
- VXLAN-EVPN — VLAN↔VNI binding (`vlan N / vn-segment`), the `nve1`
  VTEP (source-interface, UDP port, multicast group, flood list), and
  the symmetric-IRB **L3VNI** (`vrf context X / vni N`)

> **Management-plane caveat.**  When NX-OS is the **target**, the codec
> now renders `ip domain-name` / `ip name-server` / `ntp server` /
> `logging server` (promotion #4 — domain / DNS / NTP / syslog
> round-trip), but still emits no `ip dhcp` / `radius-server` / `clock
> timezone` config — those surfaces stay declared `unsupported` (the
> live validation report flags the loss rather than reporting
> `severity: ok`).  See [What we don't do](#what-we-dont-do).

## L3 redundancy: HSRP + IPv4 Distributed Anycast Gateway

### HSRP (FHRP)

NX-OS expresses first-hop redundancy as HSRP, nested under the SVI:

```text
interface Vlan10
  hsrp 10
    priority 110
    preempt
    ip 10.1.10.1
```

The canonical model is vendor-neutral (`CanonicalVRRPGroup` with a
`mode in {"vrrp", "hsrp", "carp"}` discriminator).  On render, the
codec emits **every** group as an `hsrp` block regardless of the
source `mode` — so a cross-vendor VRRP / CARP group normalises to
HSRP on NX-OS.  The operator's redundancy intent for the virtual IP
survives; the wire protocol changes (this is declared
[lossy](#lossy-paths)).  Same-vendor HSRP round-trips losslessly.

### IPv4 Distributed Anycast Gateway

Fabric-mode anycast: a chassis-wide MAC plus a per-SVI marker.

```text
fabric forwarding anycast-gateway-mac 0001.c73a.0000
!
interface Vlan100
  ip address 10.1.100.1/24
  fabric forwarding mode anycast-gateway
```

Canonical mapping:

- `fabric forwarding anycast-gateway-mac AABB.CCDD.EEFF` lands on
  `CanonicalIntent.anycast_gateway_mac` (dotted-triplet ↔ canonical
  colon-hex).
- Per-SVI `fabric forwarding mode anycast-gateway` mirrors the
  primary IP as the anycast (`virtual_gateway_address = ip`).  This
  is the same IP-mirror semantic shared with the IOS-XE SD-Access
  codec.

**IPv6 anycast is unsupported** — IPv4 DAG is fully wired; the IPv6
companion parses-and-ignores in v1 (parity with the IOS-XE codec's
identical IPv6-anycast deferral).

## Lossy paths

- **`/interfaces/interface/vrrp-groups/group`** — VRRP / CARP groups
  normalise to HSRP on render (see above); sub-second timers,
  virtual-MAC, and track objects are not modelled in v1.
- **`/routing/static-route/description`** — render emits destination
  + next-hop + metric only; the static-route name/description drops.
- **`/routing-instances/instance/route-distinguisher`** — `rd auto`
  is preserved verbatim as a sentinel; cross-vendor renderers that
  don't recognise it must synthesise an explicit RD.  An explicit RD
  round-trips losslessly.
- **`/routing-instances/instance/rt-imports`** — `route-target both
  <rt> evpn` preserves the RT value but the L2VPN-EVPN address-family
  discriminator reverts to IPv4-unicast cross-vendor.
- **`/vxlan-vnis/vni`** — per-VNI sub-flags (`suppress-arp`,
  alternate ingress-replication) don't round-trip; the codec emits
  the modern BGP-EVPN head-end-replication shape on every render.
  The VLAN↔VNI binding itself round-trips.
- **`/local-users/user/privilege-level`** — NX-OS named roles map to
  numeric privilege (network-admin / vdc-admin → 15, else → 1) for
  cross-vendor targets; the named role round-trips losslessly
  same-vendor.
- **SNMPv3 `auth-passphrase` / `engine-id`** — the 10.x
  `localizedV2key` digest normalises to the older `localizedkey`
  form, and engineIDs are colon-decimal; cross-vendor / cross-version
  migration requires re-keying the v3 user on the target.
- **`/system/raw-sections/vdc`** and **`…/features`** — N7K VDC
  virtualisation grammar is discarded (a default single-VDC wrapper
  is synthesised on render); `feature <name>` lines are derived on
  render from the canonical-tree shape, so source `feature` lines not
  motivated by a canonical surface (e.g. `feature scp-server`) drop.

## What we don't do

**Management-plane Tier-1/2 surfaces NX-OS render drops** (declared
`unsupported` so the loss is visible, not silent):

- `timezone` (`domain`, DNS, NTP and syslog servers now round-trip —
  promotion #4)
- DHCP server pools
- RADIUS servers (host + shared secret)
- IPv6 anycast-gateway

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `router bgp` / `router ospf` / `eigrp` /
  `isis` stanzas (surfaced on the `dropped_tier3_sections` banner;
  not auto-rendered)
- **ACLs** — standard / extended / IPv6 (auto-translating ACL
  semantics across vendors risks shipping subtly-permissive rules)
- **Firewall / NAT** — NX-OS does not host a stateful firewall or
  typical edge NAT
- **QoS** — `class-map type qos` / `policy-map type qos` /
  `service-policy`

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Six `batfish/lab-validation` configs (Apache-2.0), all NX-OS 9.2(3),
spanning four scenarios:

- **`batfish_nxos_hsrp_nxos1.txt`** / **`…nxos2.txt`** — HSRP (FHRP)
  HA pair + port-channel LAG
- **`batfish_nxos_evpn_l3vni_nx1.txt`** / **`…nx2.txt`** —
  VXLAN-EVPN symmetric-IRB **L3VNI** + `nve1` VTEP
- **`batfish_nxos_evpn_l2vni_nx1.txt`** — VXLAN-EVPN **L2VNI**
  (`vn-segment`)
- **`batfish_nxos_bgp_redist_d1.txt`** — BGP redistribute-connected
  + VRF

(The high interface counts in these captures reflect batfish's full
chassis dumps — every Ethernet port appears, most unconfigured.)
Operator captures from a **newer NX-OS major** (10.x) and a second
source are the highest-value contributions — see
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## Common gotchas

- **HSRP is the FHRP, not VRRP.**  Cross-vendor VRRP / CARP groups
  render as `hsrp` blocks; same-vendor HSRP round-trips cleanly.
- **`nve1` is the VTEP, not a routed port.**  The codec intercepts
  `interface nve1` as the VXLAN tunnel-endpoint container (`tunnel`
  kind), not an L3 interface.
- **Some management services don't carry.**  DHCP / RADIUS / timezone
  are render-dropped on an NX-OS target — re-apply them on the device.
  The validation panel flags each.  (DNS / NTP / syslog / domain now
  round-trip — promotion #4.)
- **`feature` lines are regenerated.**  The renderer derives `feature
  interface-vlan` / `feature lacp` / `feature hsrp` etc. from the
  canonical shape; it does not preserve arbitrary source `feature`
  declarations.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — when something
  doesn't translate cleanly
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — diagnostic
  flowchart
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md) — the cross-mesh audit
