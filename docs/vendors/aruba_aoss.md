# Aruba AOS-S — What works for me?

If you operate Aruba AOS-S (formerly ProCurve) switches and want to
know what Netcanon does for you, this is the page.

## TL;DR

- **`aruba_aoss`** — AOS-S CLI parse + render.  **Certification:
  certified.**  Bidirectional.

The codec covers AOS-S WB / WC / KB software branches across the
major AOS-S generations represented in the corpus: 2920 / 2930F /
2930M stack / 5400R modular chassis.  The CLI grammar is stable
across the AOS-S product line, so other generations (2530, the YA
branch, etc.) parse and render through the same pipeline — they
just aren't pinned by a fixture yet (operator captures welcome —
see [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)).

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname`, `domain`, DNS / NTP / syslog servers, `timezone`
  + DST rule
- Interfaces — slot-port and letter-slot-port (`A1-A24`, `B1-B24`
  on modular 5400R) port-id ranges, descriptions, IPv4 SVI L3
- VLANs — ID, name, tagged/untagged port lists with comma-separated
  range expansion (`A2-A6,A8-A10,A12-A24`), `primary-vlan`
- Static routes (incl. `ip default-gateway` form)
- LAGs (`trk<N>` reconciled with cross-vendor `Port-channel<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 — `snmpv3 user` + `snmpv3 group` mappings; engine
  ID; trap-host with `trap-level` filtering
- RADIUS — `radius-server host <ip> key <secret>`
- DHCP server pools (`dhcp-server pool` grammar with default-router
  + dns-server + network + range)
- Local users — `password manager sha1` hash (and other AOS-S hash
  forms) form-preserving migration

Parse-tolerant (parsed but not currently rendered cross-vendor —
intra-AOS-S round-trip preserves them; cross-vendor render path is
future work):

- `dhcp-snooping` — `authorized-server` lists, VLAN scope, trust-port
- `web-management ssl`, `ip authorized-managers` management-plane
  ACLs

## L3 redundancy: VRRP (no anycast)

**New in v0.2.0** (Wave B — classic VRRP wire-up).

AOS-S nests VRRP groups inside the per-VLAN stanza — the VLAN IS the
SVI on AOS-S, so the redundancy group lives next to the VLAN's IP
address rather than on a separate routed interface.  Canonical
attaches the group to the synthesised `Vlan<N>` interface (see the
codec's `_svi_absorption.py` pattern).

### Grammar

```text
router vrrp
;
vlan 100
   name "Mgmt"
   ip address 10.0.100.1/24
   ip vrrp vrid 10
      virtual-ip-address 10.0.100.254
      priority 110
      preempt
      enable
      authentication mode plaintext-password "SECRET"
      exit
   exit
```

Sub-commands handled: `virtual-ip-address`, `priority`, `preempt` (+
absence ⇒ `preempt=False`), `enable` (mandatory marker; consumed
without a canonical field — render re-emits it), `authentication mode
plaintext-password "<key>"` (→ `plain:<key>`).  The top-level `router
vrrp` enabler line is mandatory and gets re-emitted any time there
are groups in the canonical tree.

Multiple `ip vrrp vrid` blocks in the same `vlan N` stanza produce
multiple `CanonicalVRRPGroup` records on the SVI.

### Known limitations

- **Single virtual-ip-address per vrid.**  AOS-S `virtual-ip-address`
  accepts ONE address per group.  Cross-vendor migration from
  multi-VIP sources (Cisco IOS-XE `vrrp 10 ip X secondary`, Junos
  `virtual-address [ X Y Z ]`) emits the first VIP and drops the tail
  with a `; review:` comment — operator must split into multiple
  groups manually if redundancy is needed on every address.
- **No anycast-gateway grammar.**  AOS-S is a campus L2/L3 codec
  with no equivalent of Arista VARP / Junos virtual-gateway-address /
  Cisco SD-Access fabric forwarding.  All anycast canonical paths
  are declared `unsupported` and parse-and-ignore.
- **No CARP, no HSRP.**  Only IETF VRRP.
- **AOS-S vendor default is `preempt=False`**, opposite to most
  other vendors — the parser overrides the canonical default (True)
  when the `preempt` token is absent from the source.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model design (`CanonicalVRRPGroup`); see
  `02-per-vendor-grammar.md` § "Aruba AOS-S" for the single-VIP
  constraint rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (no AOS-S participation; declared
  unsupported across all three anycast canonical paths).

## Lossy paths

See per-codec `CapabilityMatrix.lossy` declarations in the codec
source — most fields parse + render cleanly within the documented
surface.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Aruba-specific firewall** features (`access-list extended`
  beyond simple ACL parse-tolerance)
- **NAT**
- **IPsec VPN**
- **QoS** policies
- **Routing protocols** (OSPF / RIP / static routes parse, but
  protocol stanzas informational)
- **PoE policy detail** beyond per-port `power-over-ethernet enable`

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`aruba_central_5memberstack_rendered.cfg`** — rendered from
  Aruba Central's bulk-config 5-member-stack template (BSD-2-Clause
  upstream)
- **`hpe_community_2930f_wc1607_intervlan.cfg`** — 2930F on
  WC.16.07.0002 with 12 VLANs, inter-VLAN L3, `ip helper-address`
  on 10 VLANs (HPE Community forum-share)
- **`hpe_community_2920_wb1608_dhcp_snooping.cfg`** — 2920 on
  WB.16.08.0001 — different OS family (WB vs WC) and major version
  from the other captures.  `dhcp-snooping` with 13
  `authorized-server` entries, NTP iburst, ACLs
- **`hpe_community_2930f_wc1610_dhcp_server.cfg`** — 2930F on
  WC.16.10.0005 with `dhcp-server pool` grammar exercised across
  3 pools and 4 VLANs
- **`user_contrib_2930m_wc1611.cfg`** — 2930M stack on WC.16.11.0025
  (most-current WC LTS), JL323A chassis + JL083A flexible-module
  uplinks, `stacking` stanza, `oobm` per-member IP, SNMPv3 engineid,
  `password manager sha1` hash, slot-port + slot-letter-port range
  expansion
- **`hpe_community_5406rzl2_kb1515.cfg`** — 5406Rzl2 (J9850A)
  modular-chassis on KB.15.15.0008 (first KB-branch and first
  modular-chassis fixture); `module A type j9534a` + `module B
  type j9537a` line-card declarations

Spans WB / WC / KB software branches and 2920 / 2930F / 2930M /
5400R hardware classes (the body above hedges "other generations
including 2530 / YA branch parse + render through the same
pipeline — they just aren't pinned by a fixture yet").

## Common gotchas

- **`include-credentials` mode** affects how hashes appear in
  running-config — Netcanon parses + preserves both forms.
- **Banner format + positional port lists** — the codec correctly
  parses the AOS-S banner / "Configuration Editor" prelude and the
  position-sensitive port-list forms (`untagged 1,3,5-10` etc.).
- **Stacking-aware port IDs** — 2930M stacks use `1/1-1/47`,
  `1/A1-1/A4` forms which expand correctly in cross-vendor port
  rename.
- **Hash portability** — `sha1` hashes don't translate to all
  targets cleanly; review-comment surfaces in the rendered output
  when targeting incompatible vendors.
- **Backup-side**: definition YAML lives at
  [`../../definitions/aruba/aos-s/16.x.yaml`](../../definitions/aruba/aos-s/16.x.yaml).

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
