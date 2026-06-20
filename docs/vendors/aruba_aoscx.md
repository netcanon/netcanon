# Aruba AOS-CX — What works for me?

If you operate modern Aruba (AOS-CX) switches — the 6300 / 6400 /
8320 / 8325 / 8400 class — and want to know what Netcanon does for
you, this is the page.

## TL;DR

- **`aruba_aoscx`** — `show running-config` text **bidirectional**
  (parse AND render).  **Certification: certified.**

AOS-CX is the modern Aruba NOS, **distinct from the legacy
`aruba_aoss`** (ProVision / AOS-Switch) codec — different grammar,
different codec, different `CapabilityMatrix`.  The codec targets the
AOS-CX 10.x surface: L2 switchport + VLAN port membership, `interface
lag N` LAGs, VRFs, `active-gateway` anycast (the VSX / EVPN
distributed gateway), and VXLAN L2VNI bindings.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, VRF binding
- L2 switchport — access / trunk mode, access-VLAN, trunk allowed-VLAN
  list, trunk native VLAN, `lag` membership
- VLANs — ID, name, description, tagged/untagged port lists
- Static routes — default VRF (`ip route`)
- VRFs — name (a bare `vrf <name>` stanza in v1)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- LAGs (`interface lag N`, reconciled with cross-vendor names like
  `Port-channel<N>` / `ae<N>`)
- SNMP v2c community + v3 USM (community, location, contact, v3 users)
- Local users — named AOS-CX `group` (administrators / operators /
  auditors / custom) + `password ciphertext` blob
- VXLAN — VLAN↔VNI binding (`interface vxlan 1 / vni <VNI>` with
  nested `vlan <VLAN>`)

> **Management-plane caveat.**  When AOS-CX is the **target**, the
> codec renders no `ip domain-name` / `ip dns` / `ntp server` /
> `logging` / `dhcp-server` / `radius-server` config — those surfaces
> are declared `unsupported` (the live validation report flags the
> loss rather than reporting `severity: ok`).  See
> [What we don't do](#what-we-dont-do).

## L3 redundancy: active-gateway anycast

AOS-CX models the VSX / EVPN distributed gateway as `active-gateway`
under the SVI — an Arista-VARP-style anycast (a stable IP present on
every switch, no group ID):

```text
interface vlan 100
    ip address 10.1.100.2/24
    active-gateway ip mac 12:01:00:00:01:00
    active-gateway ip 10.1.100.1
```

Canonical mapping:

- `active-gateway ip <vip>` mirrors into
  `CanonicalIPv4Address.virtual_gateway_address`.
- `active-gateway ip mac <mac>` lands on
  `CanonicalIntent.anycast_gateway_mac`.

This co-exists with — and is the inverse of — classic FHRP: **VRRP**
(`vrrp <vrid> address-family` under an SVI) is a later phase and stays
`unsupported`; the `active-gateway` anycast surface IS the supported
distributed-gateway path.  **IPv6 active-gateway** parses-and-ignores
in v1 (parity with the NX-OS / IOS-XE IPv6-anycast deferral).

## Lossy paths

- **`/routing/static-route/description`** — render emits destination +
  next-hop only; the static-route name / description drops.
- **`/interfaces/interface/config/type`** — AOS-CX declares no IANA
  ifType; the codec infers it from the name shape (`1/1/1` →
  ethernetCsmacd, `vlan N` → l3ipvlan, `lag N` → ieee8023adLag,
  `loopback N` → softwareLoopback, `vxlan N` → tunnel).
- **`/local-users/user/privilege-level`** — the named `group` maps to
  numeric privilege (administrators → 15, else → 1) for cross-vendor
  targets; the named group round-trips losslessly same-vendor.  The
  `password ciphertext` blob is AES-encrypted with the device key
  (portable same-device only) — cross-vendor migration requires
  re-keying.
- **`/snmp/v3-user/auth-passphrase`** — SNMPv3 auth/priv keys are
  device-key `ciphertext` blobs; emitted verbatim cross-vendor but the
  operator must re-key on the target.
- **`/vxlan-vnis/source-interface`** — AOS-CX states the VTEP source
  as an IPv4 *address* (`interface vxlan 1 / source ip <X>`), not an
  interface name like NX-OS / Arista.  A cross-vendor source carrying
  an interface *name* has no AOS-CX `source ip` form, so the `source
  ip` line is omitted on render (the VLAN↔VNI bindings still emit).
- **`/system/raw-sections/version-banner`** — the `!Version
  ArubaOS-CX <release>` banner + management-plane service footer
  (`ssh server`, `https-server`, `clock`, `ntp`, `spanning-tree`) is
  discarded on parse; a synthesised banner is emitted on render.

## What we don't do

**Surfaces AOS-CX render drops** (declared `unsupported` so the loss
is visible, not silent):

- **Management plane** — `domain`, `timezone`, DNS / NTP / syslog
  servers, DHCP server pools, RADIUS servers (host + secret), SNMP
  trap-hosts (`snmp-server host`)
- **VRF detail** — VRF description, route-distinguisher, route-target,
  and per-VRF static routes (these live under the deferred `evpn` /
  `router bgp` blocks; only the bare `vrf <name>` + default-VRF `ip
  route` are wired)
- **VRRP** (FHRP) and **IPv6 active-gateway**
- **VXLAN control plane** — per-VLAN L2VNI RD/RT (almost always
  `auto`-derived) and symmetric-IRB **L3VNI** (`vni N / vrf <name>`);
  the L2 VLAN↔VNI binding itself IS supported

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `router bgp` (incl. the EVPN
  address-family) / `router ospf` (surfaced on the
  `dropped_tier3_sections` banner; not auto-rendered)
- **ACLs** — standard / extended
- **QoS** — `class` / `policy` / `apply qos`
- **NAT** — AOS-CX does not host typical edge NAT

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Four configs from Aruba's published `aruba/aoscx-ansible-dcn-workflows`
reference fabric (Apache-2.0), spanning two grammar families and two
AOS-CX majors:

- **`aoscx_dcn_arch3_ibgp_leaf1a.cfg`** / **`…ebgp_leaf1a.cfg`** —
  EVPN-VXLAN leaves (iBGP + eBGP), `interface vxlan` L2VNI, `rd auto`
  vs explicit `route-target 1:11` (GL.10.04.0020)
- **`aoscx_dcn_arch4_core1_1.cfg`** / **`…core1_2.cfg`** — L3-agg
  cores with real `active-gateway` SVIs + multi-chassis LAGs; the
  arch4 cores are the first **real** `active-gateway` capture (the
  anycast surface was synthetic-only through Phase 3) — the
  `core1_2` VSX-secondary peer has a dense 42-interface table
  (GL.10.13.1000)

The corpus is single-source; an operator capture from a different
source, plus configs exercising symmetric-IRB **L3VNI**, **VSX**, and
**VRRP**, are welcomed via
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## Common gotchas

- **AOS-CX is L3-by-default; `no routing` opts into L2.**  This is the
  **inverse** of NX-OS (where ports are L2 by default).  A physical
  port with no `no routing` is a routed interface; the switchport L2
  model engages only when the port opts out of routing.
- **`active-gateway` is the anycast, not VRRP.**  The supported
  distributed-gateway surface is `active-gateway ip` / `active-gateway
  ip mac`; classic VRRP (`vrrp <vrid>`) is a later phase and drops.
- **Distinct from `aruba_aoss`.**  AOS-CX (10.x) and AOS-Switch /
  ProVision (16.x, the `aruba_aoss` codec) are different NOSes — the
  `!Version ArubaOS-CX` banner is the probe discriminator.  Pick the
  right vendor in the target dropdown.
- **Management services don't carry.**  DNS / NTP / syslog / DHCP /
  RADIUS / domain / timezone are render-dropped on an AOS-CX target —
  the validation panel flags each; re-apply them on the device.

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
