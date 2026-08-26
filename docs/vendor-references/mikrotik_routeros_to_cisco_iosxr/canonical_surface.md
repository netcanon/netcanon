# MikroTik RouterOS → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus a
hand-run parse → render → re-parse of all five cells (see
[Reproducing](#reproducing)). Per-key dispositions were resolved through the
audit's own `actual_disposition()` and the reconciler's `STRUCTURAL_ONLY`
collapse rather than inferred from the drift shape, so this file and the
ratchet agree by construction.

- Fixture cells: **5** (4 real `.rsc` exports + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Interface records round-tripped: **46**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured round-trip. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`mikrotik_routeros` in this corpus is a **SOHO / small-ISP edge router or
CRS-class switch-router** — `ether1..ether8`, a `bridge`, VLAN interfaces, a
DHCP server, a local user table. `cisco_iosxr` is a **service-provider edge /
core router**: 4-segment port names, RD-from-`router bgp`, a heavy VRF surface,
and deliberately **no campus L2**.

The realistic migration is a MikroTik edge box being replaced by an ASR/NCS at
the same demarcation point. The shared surface is therefore the **routed
edge** — interface addressing, MTU, admin state, static routes, LAG bundles,
local accounts — and *not* the L2 / services surface RouterOS carries as a
matter of course.

## The structural finding

This pair does **not** behave like the AOS-CX → EOS pair. There, the loss was
the interface inventory shrinking, which dragged every `interfaces[].*`
sub-field into a loss. Here the opposite holds, and it is worth stating
plainly because it inverts the usual reading:

**The interface inventory is preserved 1:1 on every cell** — 2→2, 9→9, 7→7,
16→16, 12→12, i.e. 46 of 46 records — and **interface names survive
verbatim**. `ether1`, `bridge1`, `bond1`, `vlan100`, `sfp-sfpplus1` all come
back out of the IOS-XR render under exactly those names. The codec does *not*
rewrite them into `GigabitEthernet0/0/0/1` shape, so the 4-segment-port and
`/interfaces/interface/4th-port-segment` machinery that dominates IOS-XR's own
fixtures never engages on a RouterOS source.

Measured across all 46 records, with zero mismatches on any of them:

| interface sub-field | equal, with data | mismatched | equal, both empty |
|---|---|---|---|
| `description` | 24 | **0** | 22 |
| `enabled` | 46 | **0** | 0 |
| `mtu` | 17 | **0** | 29 |
| `ipv4_addresses` | 13 | **0** | 33 |
| `ipv6_addresses` | 3 | **0** | 43 |

The dominant loss on this pair is instead **whole-subsystem drops**. Four
canonical subsystems that RouterOS populates arrive at the IOS-XR render and
produce *no output line at all*:

| subsystem | source records | after round-trip | cells affected |
|---|---|---|---|
| `vlans` | 9 | **0** | 3 |
| `dhcp_servers` | 5 | **0** | 3 |
| `snmp` | populated object | **`None`** | 3 |
| `radius_servers` | 2 | **0** | 1 |

Grepping the rendered IOS-XR config for the kitchen-sink cell returns **zero**
`dhcp`, `snmp` and `radius` lines. These are vanished records, not degraded
ones, so per netcanon #436 they are recorded `unsupported` — which blocks —
rather than `lossy`, which warns and stays compatible and would understate
them badly.

## Per-field measurement (5 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 2 | 3 | 0 |
| dns_servers | 1 | 0 | 4 |
| ntp_servers | 3 | 0 | 2 |
| interfaces[].name / description / enabled / mtu / ipv4 / ipv6 | 5 | 0 | 0 |
| interfaces[].interface_type | 0 | 5 | 0 |
| interfaces[].lag_member_of | 0 | 1 | 4 |
| vlans[].* | 0 | 3 | 2 |
| static_routes | 0 | 1 | 4 |
| dhcp_servers | 0 | 3 | 2 |
| snmp.community / location / contact / trap_hosts | 2 | 1 | 2 |
| snmp.v3_users | 0 | 3 | 2 |
| lags | 0 | 1 | 4 |
| local_users[].name / role | 1 | 0 | 4 |
| radius_servers | 0 | 1 | 4 |

Fields trivially empty on all 5 cells: `domain`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`,
`local_users[].hashed_password`, `vxlan_vnis[].*`, `evpn_type5_routes`,
`routing_instances[].*`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## The VLAN drop, and why only `vlans[].id` declares it

All 9 `CanonicalVLAN` records across 3 cells are dropped. IOS-XR has no campus
L2 model — the target matrix declares `switchport-mode`, `access-vlan`,
`trunk-allowed-vlans`, `trunk-native-vlan` and `voice-vlan` all unsupported,
and VLANs on XR are dot1q sub-interfaces rather than a VLAN table.

What survives is the *L3 interface*, not the VLAN. On the kitchen-sink cell
the render emits `interface vlan100` with ` description Users VLAN` — the
`CanonicalInterface` named `vlan100` round-trips intact — while the
`CanonicalVLAN(id=100, name='vlan100', description='Users VLAN')` record has no
counterpart at all. A reader who checks only for the string "Users VLAN" in
the output will wrongly conclude the VLAN survived.

Because the whole list vanishes, **every** `vlans[].*` key measures as drifted
for that one reason. The reconciler handles this with its `STRUCTURAL_ONLY`
collapse (`tools/run_phase4_reconciliation.py`, the `structural_parent_claimed`
map): iterating `per_field_expectation` **in file order**, the first sub-field
of a parent list keeps its real class and every later sibling whose drift is
purely the wholesale list-length signal is reclassified to `STRUCTURAL_ONLY`
so one structural signal does not multiply across N keys.

The operational consequence for this file:

- `vlans[].id` is written first and declares the loss (`unsupported`). It owns
  the structural signal for the parent list.
- `vlans[].name`, `.ipv4_addresses`, `.untagged_ports`, `.tagged_ports` and
  `.description` are written after it and declare **`good`**. A loss declared
  on any of them could never be evidenced by any cell — it would be collapsed
  before it reached the ratchet — so it would fail the per-pair unevidenced
  ratchet by construction. This is the exact defect that broke six
  declarations across four pairs on the previous wave (see `CHANGELOG.md`);
  all six were correct as `good`.

Read those five `good`s narrowly: they assert that **when a VLAN record
survives, the value survives with it**. On this corpus no VLAN record
survives. The loss is real, and it is declared once, at `vlans[].id`.

**Key order in the YAML is therefore load-bearing, not cosmetic.** Reordering
`vlans[].id` below its siblings would move the structural claim to whichever
key now sorts first and invalidate the rest.

## Two findings worth carrying forward

**1. `interfaces[].interface_type` is a clean, total, 46-of-46 loss.** Both
matrices already declare `/interfaces/interface/config/type` lossy, and the
mechanism is visible in the target's own declared reason: the IOS-XR CLI
parser infers type from the **name prefix** (`GigabitEthernet` →
`ethernetCsmacd`, `Loopback` → `softwareLoopback`, `Bundle-Ether` →
`ieee8023adLag`, `MgmtEth`, `tunnel-*`). RouterOS names match none of those,
so everything lands on `ianaift:other`:

| source type | target type | records |
|---|---|---|
| `ianaift:ethernetCsmacd` | `ianaift:other` | 27 |
| `ianaift:l3ipvlan` | `ianaift:other` | 9 |
| `ianaift:bridge` | `ianaift:other` | 5 |
| `ianaift:ieee8023adLag` | `ianaift:other` | 2 |
| *(empty)* | `ianaift:other` | 2 |
| `ianaift:bridge` | `ianaift:softwareLoopback` | 1 |

The last row is the one to watch: a RouterOS bridge named `loopback` is
**re-typed**, not merely downgraded. The name-prefix heuristic reads the
operator's chosen name and asserts a type the source never said. It happens to
match intent here; it is still a mutation, and a bridge named `tunnel-x` would
mutate the same way with less luck.

**2. `lags` is the naming artifact here — the opposite of the AOS-CX pair.**
The evidence dossier flags a standing trap: renderers key off
`CanonicalInterface.lag_member_of`, not `CanonicalLAG.members`, so a bare
`lags` drift is usually a cross-vendor rename rather than a real loss, and
must be probed before being declared. Probed:

```
src lags  = [('bond1', ['ether3','ether4'], 'active'),
             ('bond2', ['ether5','ether6'], 'static')]
tgt lags  = [('Bundle-Ether1', ['ether3','ether4'], 'active'),
             ('Bundle-Ether2', ['ether5','ether6'], 'static')]
src lag_member_of = {ether3: bond1, ether4: bond1, ether5: bond2, ether6: bond2}
tgt lag_member_of = {ether3: Bundle-Ether1, ..., ether6: Bundle-Ether2}
```

Both bundles survive, **both member sets survive, both modes survive**. Only
the operator-chosen name is rewritten to IOS-XR `Bundle-Ether<N>` form. That
is `lossy` — warns, stays compatible — and emphatically **not** `unsupported`.
`interfaces[].lag_member_of` drifts on the same 4 records for the same single
reason; the two keys are one finding, not two, and neither corroborates the
other.

## `hostname` fails in two different directions

Three of five cells drift, by two distinct mechanisms, and only one of them is
a loss in the ordinary sense:

- **Materialisation** (2 cells: `ntc_ip_address_export`,
  `taqavi_initial_provisioning`): source `''` → target `'Router'`. Neither
  RouterOS export sets `/system identity`, so the canonical hostname is empty;
  the IOS-XR render emits a default `hostname Router` and the re-parse reads it
  back. The migration invents a hostname that was never in the source.
- **Truncation** (1 cell: `routeros_diff_verbose_export`): source
  `'Quinta Router'` → target `'Quinta'`. RouterOS identities may contain
  spaces; an IOS-XR `hostname` line is a single token, so everything after the
  first word is lost on re-parse.

Both matrices declare `hostname` supported, and both are right — a hostname is
always carried. The value is what degrades, so this is `lossy`, not
`unsupported`. Check the identity on any RouterOS box whose name contains a
space before cutover.

## `static_routes`: records survive, labels do not

All 4 routes on the one cell that populates them round-trip with destination
and next-hop intact. Two things change:

- **Descriptions are dropped on all 4** (`'Default route to ISP'` → `''`).
  The target declares `/routing/static-route/description` lossy with the
  reason "render emits destination + next-hop only". On a RouterOS box the
  route comment is frequently the only record of *why* a route exists.
- **One route re-slots fields rather than losing them**: `192.168.99.0/24`
  arrives with `gateway='bridge1'` and `interface=''` and leaves with
  `gateway=''` and `interface='bridge1'`. RouterOS puts an interface name in
  the `gateway` field; IOS-XR renders it as an interface next-hop and the
  re-parse files it under `interface`. Semantically preserved, mechanically
  drifted — it is *not* independent evidence of route loss.

## Source-side gaps vs target-side drops vs symmetric gaps

Three different situations produce three different dispositions, and the
distinction is what tells a reader whether re-authoring on the target helps.

**Source-side gaps → `not_applicable`.** `mikrotik_routeros` declares these
unsupported at the exact path, so as a *source* it never emits them:
`/system/domain`, `/system/syslog-server`, `/routing-instances/instance`,
`/routing-instances/instance/instance-type`. Nothing reaches IOS-XR to be
lost. For `syslog_servers` this is worth acting on — **IOS-XR declares it
supported**, so re-authoring logging hosts on the target will stick.

`routing_instances` is the sharpest instance of this, and the pair's main
irony. IOS-XR carries the richest VRF surface in the mesh (it declares
`/routing-instances/instance` lossy only over the `route_distinguisher`
derivation, and renders `vrf <name>` + address-family + route-targets
cleanly). None of it engages: the source declares the whole instance subtree
unsupported, no committed cell populates it, and 0 of 46 interface records
carry a `vrf`. This pair does not exercise IOS-XR's VRF capability at all.

**Target-side drops → `unsupported`.** `dhcp_servers`, `radius_servers`, the
five `snmp.*` keys, `vlans[].id` and `interfaces[].vrrp_groups`. The source
emits them (or, for VRRP, declares only lossy paths and so *can* emit them);
IOS-XR declares them unsupported and renders nothing. Re-author on the target
only where the target actually has the feature — for SNMP, RADIUS and DHCP the
IOS-XR codec declares them out of v1 scope, so a hand-written stanza will not
survive a future round-trip either.

**Symmetric gaps → `unsupported`.** `timezone`, `vxlan_vnis[].*` and
`anycast_gateway_mac` are declared unsupported by **both** codecs. Neither side
can hold them; nothing about the pairing is at fault.

### One disagreement, resolved by probing

The vanish-classifier calls `snmp` `partial -> lossy`, while the IOS-XR
capability matrix declares `/snmp/community` and four `/snmp/v3-user/*` paths
unsupported ("SNMP parse + render is out of the v1 XR scope"). They disagree,
so it was settled by round-trip rather than by argument: on all three cells
that populate SNMP, `source_intent.snmp` is a populated `CanonicalSNMP` and
`round_tripped.snmp` is `None`, and the rendered config contains zero `snmp`
lines. The matrix is right; the classifier's "partial" reflects only that
`snmp` is a single object rather than a list, so its record-vanishing
heuristic does not fire. All five `snmp.*` keys are recorded `unsupported`.

## Credential material

Two credential-bearing surfaces cross this pair, and neither value is
reproduced here or in the YAML — per `AGENTS.md`, secrets are
operator-traceable even when encrypted, and a document that quotes the value it
describes defeats its own redaction.

- **RADIUS shared secrets** are dropped with the whole `radius_servers` list
  (2 records → 0). The target declares `/radius-servers/server/key`
  unsupported: "the RADIUS shared secret is dropped on migration". The
  fixture's secrets are short synthetic strings, not vendor ciphertext.
- **`local_users[].hashed_password` is empty on all 5 cells, on both sides.**
  A RouterOS `/user` export does not carry the password hash at all, so there
  is no secret to migrate and no hash-format incompatibility to describe. That
  is a source-side gap (`not_applicable`), not a successful migration: accounts
  arrive on IOS-XR without credentials and must have passwords set before
  cutover.

## Two observations with no expectation key

Recorded here rather than declared, because the audit's key list has no key
for either. Neither is claimed as evidence for any disposition in the YAML.

- **`CanonicalLocalUser.privilege_level` collapses to 1.** On the one cell
  with local users, `admin` (15), `operator` (10) and `auditor` (1) all
  re-parse as `1`, while `local_users[].name` and `.role` are preserved
  exactly (`admin`/`admin`, `operator`/`operator`, `auditor`/`operator`). The
  direction is fail-closed — accounts lose privilege rather than gain it — but
  an operator reading only `role` would not see it. Neither codec declares a
  `/local-users/*` privilege path.
- **`CanonicalInterface.default_name` is dropped on 27 of 46 records.**
  RouterOS carries the factory port label (`ether1`, `sfp-sfpplus1`) alongside
  the operator name; IOS-XR emits no equivalent, so it re-parses empty. The
  audited `interfaces[].name` key covers `CanonicalInterface.name` only, which
  is preserved on all 46.

## Reproducing

Every number above comes from this round-trip, run from the repo root:

```python
from netcanon.migration.codecs import mikrotik_routeros, cisco_iosxr  # noqa
from netcanon.migration.codecs.registry import get_codec

src, tgt = get_codec("mikrotik_routeros"), get_codec("cisco_iosxr")
source_intent = src.parse(open(cell).read())
rendered = tgt.render(source_intent)
round_tripped = tgt.parse(rendered)
```

over the five committed cells:

```
tests/fixtures/real/mikrotik/ntc_ip_address_export.rsc
tests/fixtures/real/mikrotik/routeros_diff_verbose_export.rsc
tests/fixtures/real/mikrotik/taqavi_initial_provisioning.rsc
tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc
tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc
```

Interface sub-field counts are aggregated by joining source and round-tripped
interfaces on `name` (a valid join here precisely because names are preserved
1:1) and comparing each sub-field per record — never by sampling one record.
