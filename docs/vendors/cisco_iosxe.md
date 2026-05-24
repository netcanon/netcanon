# Cisco IOS-XE — What works for me?

If you operate Cisco IOS-XE devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

Two codecs ship for the IOS-XE family:

- **`cisco_iosxe_cli`** — `show running-config` text **bidirectional**
  (parse AND render).  Cisco IOS-XE CLI is used as both a translation
  *source* and a *target* throughout the walkthrough corpus and
  `tools/demo.py`.  **Certification: certified.**
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

## L3 redundancy: VRRP + SD-Access anycast-gateway

**New in v0.2.0** (Waves B + C — VRRP and SD-Access anycast-gateway
wire-up).  `cisco_iosxe_cli` only — the NETCONF codec leaves these
paths `unsupported` (matrix-only declaration; matches the existing
`/snmp/v3-user` / `/vxlan-vnis/vni` Phase-0.5 stub pattern).

### Classic VRRP

Single-line per-attribute form, the broadly-supported surface across
every IOS-XE release from 15.x onward.  This is the form real
captures emit (see `tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt`).

```text
interface GigabitEthernet0/2
 ip address 192.168.1.1 255.255.255.0
 vrrp 12 ip 192.168.1.254
 vrrp 12 priority 110
 vrrp 12 preempt
 vrrp 12 description Edge VRRP
 vrrp 12 timers advertise 3
 vrrp 12 authentication md5 key-string SECRET
 vrrp 12 track 100 decrement 20
!
```

Sub-commands handled: `vrrp N ip X` / `vrrp N ipv6 X` (VRRPv3),
`priority`, `preempt` (+ `no` form), `description`, `timers advertise
<S>`, `authentication text <key>` (→ `plain:<key>`),
`authentication md5 key-string <key>` (→ `md5:<key>`), `track <obj>
decrement <D>` (the object name surfaces; decrement is lossy).
Multiple VRIDs on the same interface produce multiple records.

### SD-Access anycast-gateway

Catalyst 9000 fabric-mode anycast: per-SVI marker plus a chassis-wide
MAC declaration.

```text
fabric forwarding anycast-gateway-mac 0001.c73a.0000
!
interface Vlan100
 ip address 10.1.100.1 255.255.255.0
 fabric forwarding mode anycast-gateway
!
```

Canonical mapping:

- Top-level `fabric forwarding anycast-gateway-mac AABB.CCDD.EEFF`
  lands on `CanonicalIntent.anycast_gateway_mac` (converted from
  Cisco's dotted-triplet to canonical colon-hex; renders back to
  dotted-triplet).
- Per-SVI `fabric forwarding mode anycast-gateway` mirrors the
  primary IP as the anycast: `virtual_gateway_address = ip` on every
  IPv4 address record.  Order-independent (works whether the marker
  precedes or follows `ip address`).
- The discriminator gate is structural — a plain SVI with no
  `fabric forwarding mode anycast-gateway` line parses with
  `virtual_gateway_address=""`.

### Known limitations

- **Modern address-family VRRP form is lossy.**  IOS-XE 17.12+ adds
  the nested `vrrp N address-family ipv4` block with indented
  `address` / `priority` / `preempt` sub-commands.  The parser
  detects the surface (so the lossiness is visible) but does NOT
  deep-populate the nested attributes; render always emits the
  classic single-line per-attribute form.  A config that uses ONLY
  the modern AF form round-trips as an empty group shell —
  intentional and operator-visible.
- **Track decrement value drops.**  `vrrp N track 100 decrement 20`
  preserves only the track-object name on the canonical
  `track_interfaces` field; the priority-decrement value is lossy
  across every codec that supports it.
- **IPv6 SD-Access anycast is unsupported.**  IPv4 SD-Access anycast
  is fully wired; IPv6 (`fabric forwarding ipv6 mode
  anycast-gateway`) is rare in production captures and stays
  declared `unsupported` until demand arrives.
- **Cross-vendor `virtual_gateway_address` divergent from primary.**
  When a Junos / Arista VARP source carries a virtual IP DIFFERENT
  from the SVI's primary IP, IOS-XE SD-Access has no equivalent
  expression — render emits a `! review:` comment line rather than
  silently dropping the discrepancy, and suppresses the SD-Access
  marker.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model + the modern-AF lossy rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway canonical model; see `01-canonical-model.md`
  § "NX-OS shape" for the IP-mirror semantic shared with SD-Access.

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
- **`batfish_iosxe_basic_vrrp.txt`** — Batfish public corpus VRRP
  basic grammar (Apache-2.0).  Two-router HA pair with VRRP
  groups on GigabitEthernet — exercises the classic single-line
  VRRP form used by Wave-B VRRP wire-up
- **`ntc_carrier_interfaces.txt`** — Network To Code public corpus
  (Apache-2.0).  Carrier IOS grammar: VRFs, dot1Q Q-in-Q
  subinterfaces, QoS, ACL groups, uRPF.  Validates parse-tolerance
  for grammar outside the Cat9k campus surface

## Common gotchas

- **No `terminal length 0`.**  Netcanon uses `--More--`
  space-injection for paging.  This is a hard rule (see
  [`../../AGENTS.md`](../../AGENTS.md)) — don't try to bypass.
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
