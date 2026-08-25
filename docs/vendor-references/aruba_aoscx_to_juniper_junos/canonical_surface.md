# AOS-CX → Juniper Junos: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__juniper_junos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus a
direct `juniper_junos.parse(juniper_junos.render(aruba_aoscx.parse(raw)))`
round-trip of all seven fixture cells run while authoring this file. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured round-trip. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## The seven cells

| cell | source interfaces → target |
|---|---|
| `tests/fixtures/real/aruba_aoscx/aoscx_dcn_arch3_ebgp_leaf1a.cfg` | 9 → 7 |
| `tests/fixtures/real/aruba_aoscx/aoscx_dcn_arch3_ibgp_leaf1a.cfg` | 9 → 7 |
| `tests/fixtures/real/aruba_aoscx/aoscx_dcn_arch4_core1_1.cfg` | 18 → 11 |
| `tests/fixtures/real/aruba_aoscx/aoscx_dcn_arch4_core1_2.cfg` | 42 → 35 |
| `tests/fixtures/real/aruba_aoscx/canu_csm17_spine001_ipv6_vrf.cfg` | 22 → 15 |
| `tests/fixtures/real/aruba_aoscx/netutils_aoscx_snmpv3_glcx1009.cfg` | 44 → 25 |
| `tests/fixtures/synthetic/aruba_aoscx/kitchen_sink.cfg` | 13 → 9 |
| **total** | **157 → 109** |

## Device-class framing

`aruba_aoscx` in this corpus is a **campus / small-DC aggregation** switch —
CANU spine, 8320/8325-class core pairs, an access closet. `juniper_junos` is
the general-purpose Junos codec, and the realistic migration is an AOS-CX
switch replaced by an EX/QFX carrying the same VLANs, SVI addressing, LACP
uplinks and VRFs.

This pair is **markedly better than the AOS-CX → EOS pair on the L3 edge and
markedly worse on interface identity**, and the two facts have different
causes. Read both sections below before planning a cutover — the summary
"AOS-CX migrates cleanly to Junos" is true of addressing and false of the
interface inventory.

## The structural finding: interface names are tokenised away

The dominant loss on this pair is **not** per-attribute and **not** a pruning
of unconfigured ports. It is a name-tokenisation collapse.

AOS-CX names its logical interfaces with an embedded space — `lag 1`,
`loopback 0`, `vlan 101`, and the out-of-band port `mgmt`. The Junos render
places that canonical name verbatim in the `set interfaces <name> …` position,
so the emitted config contains lines shaped like:

```
set interfaces lag 1 description "Server-LAG"
set interfaces loopback 0 unit 0 family inet address 10.255.0.1/32
set interfaces loopback 1 description "Router-ID"
set interfaces vlan 10 unit 0 family inet address 10.10.10.1/24
set interfaces vlan 20 unit 0 family inet6 address 2001:db8:20::1/64
```

On re-parse the Junos codec reads the interface name as the first token, so
every `lag <n>` collapses into one record named `lag`, every `loopback <n>`
into one named `loopback`, and every `vlan <n>` into one named `vlan`.
Measured across the seven cells:

- **Physical `1/1/x` ports survive one-for-one on every cell** — all 90
  name-matched records in the corpus are physical ports plus the two `mgmt`
  records that survive.
- **19 collapsed placeholder records** (`lag` / `loopback` / `vlan`) stand in
  for 67 source logical interfaces.
- `mgmt` survives on **2 of 7** cells — and on exactly the two where it is
  administratively down, which is what gives the render something to emit
  (`set interfaces mgmt disable` on the CANU spine, an `interface-range`
  member entry on the netutils capture). On the other five the AOS-CX
  out-of-band port carries no state beyond being up, the render emits no
  `mgmt` line at all, and the record vanishes.

Consequence, and the reason it is worth stating loudly: **every
`interfaces[].*` key measures as drifted on all 7 cells**, because a record
that changes identity takes all of its attributes with it. Declaring any of
them `good` would manufacture a false `CODEC_BUG`.

That is the trap. On the 90 surviving name-matched records the attributes are
*perfect*:

| sub-field, surviving records only | identical | differing |
|---|---|---|
| `description` | 90 | 0 |
| `enabled` | 90 | 0 |
| `mtu` | 90 | 0 |
| `ipv4_addresses` (13 records carry data) | 13 | 0 |

Both matrices are right about description, enabled and MTU. The records still
lose their identity.

## Sub-fields with an independent cause

These are the `interfaces[].*` keys that do **not** merely inherit the
structural drift. Each was measured separately on the surviving records, so
none of them is being used to corroborate another (a correlated record-count
change is a single fact, not nine).

**`interface_type` — an independent, total attribute drop.** On all 90
surviving name-matched records the canonical type changes from
`ianaift:ethernetCsmacd` to the empty string. Nothing about the record
collapse is involved: these are records that survive intact in every other
respect. `aruba_aoscx` independently declares
`/interfaces/interface/config/type` lossy in its own matrix.

**`lag_member_of` — a rename, not a membership loss.** 44 of the 90 surviving
records differ, and every one of them is the same shape: `lag 1` → `ae1`,
`lag 256` → `ae256`. The aggregate index is identical on both sides in all 44
cases; no member changes aggregate and none is orphaned. This is a
vendor-correct rename that the audit does not neutralise — see the
methodology note at the end.

**`ipv6_addresses` — measured on the two records that have data.** Exactly two
source records in the whole corpus carry an IPv6 address: `vlan 6` on the CANU
spine and `vlan 20` in the kitchen sink. Both are `vlan <n>` records, i.e.
exactly the class that collapses, and in both cells the re-parsed target has
**zero** interfaces carrying IPv6. So the IPv6 loss is observed, not assumed —
but it is observed on the same structural cause, not a separate one.

**`vrrp_groups` — no data anywhere.** Zero source records in any of the seven
cells populate `vrrp_groups`. `aruba_aoscx` declares the whole
`/interfaces/interface/vrrp-groups/group/*` subtree unsupported (AOS-CX
expresses first-hop redundancy as VSX active-gateway), so as a *source* it
cannot emit one. The key measures drifted only because the record set changes.
Worth knowing for the cutover: `juniper_junos` as a **target** does model
VRRP — it declares only `/interfaces/interface/vrrp-groups/group/mode` lossy —
so VRRP re-authored on the Junos side will stick.

## LAGs mostly survive — the opposite of the EOS pair

On the AOS-CX → EOS pair, LAGs vanish outright. Here they do not. Round-tripped
on all seven cells, comparing on the canonicalised aggregate index:

- **6 of 7 cells round-trip the entire LAG set** — same count, same member
  lists, same LACP mode. `netutils_aoscx_snmpv3_glcx1009.cfg` carries 16 LAGs
  and all 16 arrive with their members intact; the CANU spine's 4 and the
  arch4 core pair's 5 likewise.
- **1 cell loses one record**: the kitchen sink's `lag 2` (mode `static`, **no
  members**) is dropped, 2 → 1. The renderer builds the aggregate from
  `CanonicalInterface.lag_member_of`, so a LAG with no member ports has nothing
  to render — the rendered config contains no `ae2` line at all, and re-parse
  therefore yields no `ae2`.

So the operational rule is narrow and checkable: **a configured-but-empty LAG
will not appear on the target.** Everything else about aggregation migrates.

## VLAN membership: physical ports survive, LAG ports do not

`vlans[].untagged_ports` drifts on all 7 cells and `vlans[].tagged_ports` on 4
of the 5 that populate it. The mechanism is the tokenisation collapse again,
seen from the VLAN side: membership entries naming a physical port survive,
membership entries naming a LAG do not, because the port name `lag 101` is
destroyed by the same first-token read.

Two cells make this unambiguous:

- `aoscx_dcn_arch4_core1_2.cfg` VLAN 1 carries 24 physical ports plus 5 LAG
  entries untagged. All 24 physical ports arrive; all 5 LAG entries are gone.
- `kitchen_sink.cfg` VLAN 10 keeps untagged `1/1/2` and tagged `1/1/4`
  unchanged, while VLAN 20's untagged `lag 2` goes to empty.

This is the same root cause as `interfaces[].name`, not independent
corroboration of it.

## The L3 edge is the good news

`vlans[].ipv4_addresses` is **`good` on this pair** — preserved on all 5 cells
that populate it — and that is the sharpest single contrast with AOS-CX → EOS,
where the same key drifts on all 5. The SVI address *and* its
`virtual_gateway_address` companion both survive: `10.12.101.2/24` with
virtual gateway `10.12.101.1` round-trips byte-for-byte, because Junos mounts
the SVI as an `irb` unit that carries the virtual-gateway address natively.

The caveat that belongs next to it: `juniper_junos` declares
`/vlans/vlan/ipv4/address/secondary-ip` lossy — Junos treats every
`family inet address` on an `irb` unit as co-equal, so a primary/secondary
distinction would flatten. No committed cell carries a secondary SVI address,
so that is a declaration, not an observation.

`static_routes`, `routing_instances[].name` and the VXLAN VNI bindings all
carry: VRF names `CSM` / `keepalive` / `test` / `RED` / `BLUE` survive, and
VNI-to-VLAN bindings survive on all 3 cells that populate them.

## The anycast inversion

`anycast_gateway_mac` is a **total drop**, measured on all 5 cells that
populate it — the MAC goes to the empty string, and `juniper_junos` declares
`/anycast-gateway-mac` unsupported with the explanation that Junos has no
system-wide anycast-gateway MAC (per-IRB overrides live on
`CanonicalIPv4Address.virtual_gateway_mac` instead).

This is the exact inverse of the EOS pair, where the fabric-wide MAC survives
and the per-SVI gateway address does not. Here **the per-SVI gateway address
survives and the fabric-wide MAC does not.** For a cutover that means
first-hop redundancy is closer to working than on the EOS pair, but the shared
MAC has to be re-expressed per IRB unit on the Junos side rather than declared
once.

## Static routes: destination and next-hop carry, preference does not

Measured on the one cell that exercises it: `10.99.0.0/16 via 203.0.113.254`
arrives with destination and next-hop intact and its **metric flattened from
200 to 0**. The CANU default route (metric 0 on both sides) round-trips
unchanged. `juniper_junos` declares `/routing/static-route/metric` and
`/routing/static-route/description` lossy and
`/routing/static-route/interface` unsupported.

Operationally: a floating / backup static route loses the preference that made
it floating and arrives equal-cost with the primary. Re-apply route preference
on the target before the routes are activated.

## SNMP

Preserved on all 4 cells that carry an SNMP record — community, location and
contact all round-trip exactly where they have data (`location` and `contact`
on the arch4 core pair, `community` on the kitchen sink).

Of those 4 cells, **2 carry an SNMPv3 USM user**. `snmp.v3_users` drifts on
exactly **1** of them, and the drift is a single token: the privacy protocol
`aes` is renormalised to `aes128`. The other user (`md5` / `des`) round-trips
identically. On both cells the USM user name, group, auth protocol and **both
passphrases** carry across unchanged.

Two consequences worth writing into a cutover plan:

1. The SNMPv3 user is not lost — it is renamed at the protocol-token level.
   Confirm `aes128` is what you meant before committing the render.
2. Because the auth and privacy keys *are* carried into the rendered Junos
   config (`set snmp v3 usm local-engine user … authentication-key …`), the
   render output is secret-bearing. Handle it accordingly.

`snmp.trap_hosts` measures `good`, but on empty data: **no committed cell
carries a trap host at all**, and `aruba_aoscx` declares `/snmp/trap-host`
**unsupported** as a source. A real AOS-CX config with trap receivers would
therefore not emit them. That is a source-matrix / corpus gap, not a
demonstrated success — see the methodology note.

## Credential material

`local_users[].name` and `local_users[].role` both round-trip on all 6
populated cells (`admin` / `administrators`, `netops` / `operators`).

`local_users[].hashed_password` drifts on all 6. What was measured: the AOS-CX
secret is an opaque `AQB`-prefixed ciphertext blob — an ArubaOS-CX-native
encrypted form, the longest observed running to 184 characters — and **not** a
crypt(3) string; none of the observed values carries a `$1$` / `$5$` / `$6$` /
`$9$` / `$2y$` prefix. (One fixture is a sanitised capture and carries a short
placeholder in that position instead of a real blob.) The Junos render emits
the value verbatim into
`set system login user <name> authentication encrypted-password "…"`, and the
Junos re-parse returns it tagged with a `junos:` marker prefix — every value
measured comes back exactly six characters longer than it went in.

So this is not a vanished field; it is worse in a way the drift shape alone
does not convey: what lands on the target is **AOS-CX-format key material
sitting in a Junos `encrypted-password` slot**. Set passwords on the Junos side
before cutover; do not assume the migrated value is a usable credential.

Separately, `local_users[].privilege_level` — a canonical sub-field outside the
audited key list — degrades from 15 to 1 on all 6 populated cells, and
`aruba_aoscx` declares `/local-users/user/privilege-level` lossy. An operator
reading "role survives" should not infer that the privilege level does.

## Source-side gaps vs symmetric gaps

`aruba_aoscx` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for Junos to lose. All are
recorded `not_applicable`, and the operational half of the distinction is what
the target declares:

| field | target declaration | what to do |
|---|---|---|
| `syslog_servers` | **supported** | re-author `set system syslog host …` — it will stick |
| `dhcp_servers` | **supported** | re-author the DHCP pool on the target |
| `domain` | no declaration | re-author by hand; the target has no stated support either |
| `dns_servers` | no declaration | re-author by hand; the target has no stated support either |
| `ntp_servers` | no declaration | re-author by hand; the target has no stated support either |
| `routing_instances[].description` | no declaration | VRF descriptions do not migrate |

Two fields are **symmetric gaps** — both matrices declare them unsupported —
and are recorded `unsupported` rather than `not_applicable`:

- `timezone` — `juniper_junos` states plainly that its render emits no
  clock/timezone stanza.
- `radius_servers` — both codecs declare `/radius-servers/server/host` and
  `/radius-servers/server/key` unsupported; the Junos render emits no AAA
  radius-server config, so the shared secret is dropped on migration.

`apply_groups` and `group_content` deserve a note because the target here *is*
Junos, so unlike every other pair the surface is meaningful on the target side.
It is still `not_applicable`: `aruba_aoscx` has no apply-groups concept, so the
canonical field is never populated from this source and no cell exercises it.

## Methodology notes worth carrying forward

**1. The audit's LAG-name canonicaliser does not cover the AOS-CX form.**
`tools/run_phase4_reconciliation.py` canonicalises `lags[].name` and
`interfaces[].lag_member_of` before comparing, so a vendor-correct rename
collapses to "preserved". Its pattern accepts `ae<n>`, `Po<n>`,
`Port-channel<n>`, `trk<n>`, `agg<n>`, `bond<n>` — all space-free. The AOS-CX
native form `lag 1` matches none of them, so it canonicalises to `None` while
the Junos side canonicalises to `LAG1`, and the pair compares unequal. Verified
on all 44 differing records: 0 canonicalise-equal. The rename is therefore
counted as drift on this pair even though the aggregate index is identical on
both sides. That is a tooling gap, not a pair-specific fact, and is left for a
codec/tooling change rather than papered over here.

**2. `aruba_aoscx` declares `/snmp/trap-host` unsupported while the mesh
measures `snmp.trap_hosts` preserved.** The two do not actually conflict — the
measurement is empty-to-empty on all four populated cells — but it means the
`good` disposition on that key rests on the absence of data, not on a
demonstrated round-trip. A fixture carrying trap receivers would settle it.
Recorded here rather than resolved.
