# VyOS — What works for me?

If you operate VyOS routers / firewalls (the open-source Vyatta
successor) and want to know what Netcanon does for you, this is the
page.

## TL;DR

- **`vyos`** — `config.boot` (curly-brace) **bidirectional** (parse
  AND render).  **Certification: certified.**

VyOS is Netcanon's 12th codec and its **first curly-brace parser** (a
brace-stack walker, distinct from the `set`-form `juniper_junos`
codec).  The codec targets VyOS 1.3 / 1.4 / 1.5: interfaces with
`vif` VLAN sub-interfaces and DHCP clients, `system login` users, NTP,
`interfaces bonding` LAGs, `service snmp`, VRFs, and `interfaces
vxlan` netdevs.  Routing-protocol + firewall stanzas (`protocols bgp`
/ `protocols ospf` / `firewall`) are surfaced on the migrate banner
via `dropped_tier3_sections`, **not** translated.

> **Input forms.**  Both `config.boot` (curly-brace) and `show
> configuration commands` (set-form) are accepted — set-form is
> converted to curly-brace up front so the brace-stack walker is
> reused.  The probe disambiguates VyOS set-form from the Junos
> set-form that the `juniper_junos` codec owns.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, `dhcp` / `dhcpv6` client, per-interface VRF binding.
  802.1Q VLANs are `vif <vid>` sub-interfaces, modelled as
  `ethN.<vid>` interfaces (there is **no** top-level VLAN database).
- Static routes — default VRF (with administrative `distance`)
- NTP servers (`system ntp` / `service ntp`, bare + block form)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- Local users — `system login user` (name + role +
  `encrypted-password` hash)
- LAGs — `interfaces bonding bondN` (members + `lag-member-of`
  back-link)
- SNMP — `service snmp` v1/v2c community + v3 USM (community,
  location, contact, v3 users)
- VRFs — `vrf name <X>` instances + the per-interface binding
  (`interfaces ethernet ethN { vrf X }`)
- VXLAN — `interfaces vxlan vxlanN` netdevs (one VNI per netdev:
  VNI, source, multicast group / flood list, UDP port)

> **Management-plane caveat.**  When VyOS is the **target**, the codec
> renders no `system domain-name` / `system name-server` / `system
> syslog` / DHCP-server / `radius-server` / `time-zone` config — those
> surfaces are declared `unsupported` (the live validation report
> flags the loss rather than reporting `severity: ok`).  **NTP is the
> exception** — it IS translated.  See
> [What we don't do](#what-we-dont-do).

## Lossy paths

- **`/routing/static-route/description`** — render emits destination +
  next-hop + distance only; the static-route name / description drops.
- **`/lags/lag/mode`** — bonding `mode 802.3ad` (LACP) maps to
  `active`; the non-LACP modes (`active-backup` / `balance-rr` /
  `balance-xor` / …) collapse to `static` (the specific balancing
  algorithm drops — re-select it on the target).
- **`/routing-instances/instance/table`** — VyOS requires a numeric
  `table <id>` on every `vrf name <X>`; the canonical model carries no
  table number, so the codec synthesises a deterministic id
  (`100 + sort-index`) on render.  The original table id is not
  preserved.
- **`/vxlan-vnis/source-interface`** — the VTEP source is
  `source-address <ip>` (or `source-interface <if>`); a cross-vendor
  source (e.g. `Loopback0`) is re-emitted verbatim and may need an
  operator port-rename.
- **`/vxlan-vnis/vlan-id`** — VyOS models one VNI per `vxlan vxlanN`
  netdev with no on-device VLAN (the L2 binding lives on a separate
  `bridge`); the canonical `vlan_id` is synthesised from the VNI and
  the netdev name regenerated `vxlan<index>` on render (deterministic;
  same-vendor round-trip stable, cross-vendor advisory).
- **`/local-users/user/privilege-level`** — VyOS login users have no
  numeric privilege in the common case; the codec maps every login
  user to privilege 15 / role `admin`.  The `encrypted-password` hash
  round-trips verbatim same-vendor; cross-vendor requires re-keying.
- **SNMPv3 `auth-passphrase` / `engine-id`** — v3 USM keys are opaque
  `encrypted-password` blobs (re-key cross-vendor); VyOS declares a
  single config-wide `engineid`, which the codec maps onto every v3
  user.
- **`/interfaces/interface/config/type`** — inferred from the name
  shape (`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback,
  `bondN` → ieee8023adLag); best-effort.

## What we don't do

**Surfaces VyOS render drops** (declared `unsupported` so the loss is
visible, not silent):

- **L2 switchport** — VyOS has no access/trunk model (L2 via
  `bridge` / `vif`); switchport mode / access-VLAN / trunk
  allowed-list / native VLAN / voice-VLAN all drop on render
- **Management plane** — `domain`, `timezone`, DNS / syslog servers,
  DHCP server pools, RADIUS servers (host + secret).  *(NTP IS
  supported.)*
- **Top-level VLAN database** — VyOS has none; 802.1Q VLANs are `vif`
  sub-interfaces (which ARE supported)
- **Per-VRF static routes** — the `vrf name <X>` instances + the
  per-interface binding are supported, but `vrf name <X> { protocols
  static route … }` is deferred past the Phase-3 VRF wire-up
- **VXLAN control plane** — per-VNI EVPN RD/RT and symmetric-IRB
  **L3VNI**; the L2 VLAN↔VNI binding itself IS supported

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `protocols bgp` / `protocols ospf`
  (surfaced on the `dropped_tier3_sections` banner; not auto-rendered)
- **Firewall** — `firewall` rule-sets (auto-translating firewall
  policy across vendors risks subtly-permissive rules)
- **NAT** — `nat source` / `nat destination`
- **Policy** — `policy` route-maps / prefix-lists

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Ten real `config.boot` files from **four sources**, spanning three
VyOS majors (1.3 / 1.4 / 1.5):

- **`cisagov/prescup-challenges`** (6 configs, MIT (SEI), VyOS
  1.4-rolling) — round-1 IPv4 / OSPF border + core (`pc5-round1-*`)
  and round-3b IPv6 / BGP routers (`pc5-round3b-*`, AS65001-65005;
  the `routere` capture is a dense 8-interface / 8-neighbor box)
- **`zhouleyan/wcni-kind`** (2 configs, Apache-2.0, VyOS 1.4-rolling)
  — `wcni-kind-gw0/gw1`, the two ends of one `vni 10` VXLAN tunnel
- **`scottlaird/vyos-parser`** (Apache-2.0, VyOS **1.5**) —
  `service snmp` (`community public`); 5 block-form NTP
- **`rapid7/metasploit-framework`** (BSD-3, VyOS **1.3**) — `service
  snmp` (`community ro` / `write`)

The round-tripping surface is interfaces + hostname + local-users +
NTP (bare + block form) + `interfaces vxlan` + `service snmp`;
OSPF / BGP / firewall are Tier-3.  **Honest scope:** only **VRF**
round-trip remains validated by the synthetic kitchen-sink alone — a
2026-06 hunt found no permissive + curly-brace real capture carrying
`vrf name` (only GPL `vyos-1x` smoketests or unlicensed configs), so
VRF stays synthetic-validated.  A permissive real `vrf name` (and a
real set-form) capture are welcomed via
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## Common gotchas

- **VLANs are `vif` sub-interfaces.**  There is no VLAN database — a
  tagged VLAN is `interfaces ethernet ethN vif <vid>`, modelled as an
  `ethN.<vid>` interface.  A switch-source's per-port VLAN membership
  drops (declared `unsupported`).
- **`protocols bgp` / `protocols ospf` are SHARED with Junos.**  Both
  VyOS and Junos use `set protocols …` — the probe disambiguates by
  config shape, not by that keyword alone.  Pick the right vendor in
  the target dropdown if detection is ambiguous.
- **Curly-brace vs set-form.**  Either input works — `config.boot`
  (curly-brace) is the native form; `show configuration commands`
  (set-form) is converted up front.  Distinct from the `juniper_junos`
  codec, which owns the Junos set-form.
- **VRF table ids are synthesised.**  Render emits a deterministic
  `table <id>` per VRF (`100 + sort-index`); the source table id is
  not preserved.

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
