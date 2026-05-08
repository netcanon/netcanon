# Cisco IOS-XE — What works for me?

If you operate Cisco IOS-XE devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

Two codecs ship for the IOS-XE family:

- **`cisco_iosxe_cli`** — `show running-config` text parse + render.
  **Certification: certified.**  Recommended for cross-vendor
  translation.
- **`cisco_iosxe`** — NETCONF / OpenConfig XML.  **Certification:
  best_effort** (Phase 0.5 stub render — parses richly, renders the
  subset Netcanon's NETCONF stub knows how to emit).  Use only when
  you specifically need NETCONF output.

For 95% of operators wanting to translate IOS-XE configs to other
vendors (or vice versa), use `cisco_iosxe_cli`.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`, `domain`, DNS / NTP / syslog servers, `timezone`
- Interfaces — name, description, enabled state, IPv4 + IPv6
  addresses, MTU, VRF binding, `kind` override
- VLANs — ID, name, tagged/untagged port lists, SVI L3 (via
  VLAN-centric projection from the `switchport` per-interface form)
- Static routes
- LAGs (`Port-channel<N>` reconciled with cross-vendor names like
  `ae<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- SNMP v1 / v2c / v3 USM (community, contact, location, trap-hosts;
  v3 with auth + priv per user)
- RADIUS servers
- DHCP server pools (per-pool network, gateway, range, options)
- Local users with hashed passwords — `$5$` / `$6$` / `$8$` / `$9$`
  form-preserving cross-vendor migration

## Lossy paths

- **`/routing-instances/instance`** — VRFs translate, but per-VRF
  static routes don't carry a VRF discriminator (route-table
  membership drops on round-trip).  `address-family ipv6` and EVPN
  sub-stanzas inside `vrf definition` are parse-and-ignore in v1.
  See the codec's `CapabilityMatrix.lossy` declarations.

## What we don't do

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall ACLs** — zone-based firewall, CBAC, reflexive ACLs
- **NAT rules** — `ip nat inside source list` etc.
- **IPsec VPN** — crypto maps, IKEv2 profiles, tunnel-protection
- **QoS** — `class-map` / `policy-map` / `service-policy`
- **Routing protocols** — BGP / OSPF / EIGRP stanzas (informational
  only; not auto-rendered to other vendors)
- **PKI / crypto** material — trustpoints, certificate chains, keys

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **Batfish public corpus** — AAA, interfaces, IP routes, logging,
  SNMP grammar kitchen-sinks (Apache-2.0)
- **`racc_csr1_iosxe173_umbrella_sig.txt`** — CSR1000v on IOS-XE 17.3
  with Cisco Umbrella SIG anycast routing
- **`racc_csr1000v_iosxe169_bgp_ospf.txt`** — CSR1000v on IOS-XE 16.9
  LTS (oldest LTS we validate against)
- **`racc_cat8000v_iosxe179_netconf.txt`** — Cat8000V on IOS-XE 17.9
  with NETCONF / RESTCONF + type-9 hash form
- **`user_contrib_cat9300_iosxe1712.txt`** — operator-contributed
  physical Cat 9300-24UX on IOS-XE 17.12 (47 interfaces, 3 LAGs,
  full Cat9k CPP grammar)
- **`cml_saumur_iosxe1712_pvrstp.txt`** — CML lab on IOS-XE 17.12
  exercising `spanning-tree pathcost method long` etc.
- **`cml_basic_forwarding_iosv_r1_ospf.txt`** — IOSv 15.x with OSPF
  + dot1Q sub-interfaces

## Common gotchas

- **No `terminal length 0`.**  Netcanon uses `--More--`
  space-injection for paging.  This is a hard rule (see
  [`../../CLAUDE.md`](../../CLAUDE.md)) — don't try to bypass.
- **Mgmt-vrf interface** (`GigabitEthernet0/0` with
  `vrf forwarding Mgmt-vrf`) gets `kind=mgmt` override automatically
  by the parser, so cross-vendor rename can cascade to Aruba `oobm`
  / Junos management VRF.
- **Type-7 hashes** are Cisco-proprietary and **migration-blocked**
  when targeting non-Cisco vendors — Netcanon emits a review-comment
  in the rendered output rather than translating to plaintext.
  Type-9 hashes round-trip cleanly within Cisco; type-5/6 hashes
  translate via the cross-vendor crypt-form mapping.
- **Backup-side**: `cisco_more_paging: true` in the device-definition
  YAML — see [`../../definitions/cisco/`](../../definitions/cisco/)
  for the canonical examples.

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
