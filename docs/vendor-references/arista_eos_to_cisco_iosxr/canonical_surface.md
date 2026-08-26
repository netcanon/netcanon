# Arista EOS → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/arista_eos__cisco_iosxr.yaml`.

**Source of every number here:** the committed cross-mesh run
(`tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`), with each
per-key disposition resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every claim that is not a cell count was additionally
re-derived by hand: parse the fixture with `arista_eos`, render with
`cisco_iosxr`, re-parse the render, compare.

- Fixture cells: **6**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration or on a hand-built config rather than a committed cell, the YAML
> says so explicitly and names which.

## Device-class framing

`arista_eos` in this corpus is a **DC leaf/spine** — EVPN/VXLAN fabric, VLANs,
SVIs, MLAG port-channels, anycast gateway. `cisco_iosxr` is a
**service-provider edge/core router**: 4-segment port names, a heavy VRF
surface, and no campus L2 model at all.

The pair is asymmetric, and the asymmetry runs cleanly along one seam. The
**L3 routed surface crosses almost intact**; the **L2 / fabric surface does not
cross at all**. There is very little in between, which is why this pair's
dispositions cluster hard at `good` and `unsupported` with only five `lossy`
keys.

## The structural finding — and it is the *inverse* of the campus pairs

On the campus-to-DC pairs the dominant loss is the interface inventory
shrinking, which forces every `interfaces[].*` sub-field to measure as drifted.
**That does not happen here.** The interface count is preserved on every cell:

| cell | source interfaces | re-parsed interfaces |
|---|---|---|
| `batfish_duplicateprivate_eos4211` | 17 | 17 |
| `batfish_eos_evpn_vlan_based_leaf` | 30 | 30 |
| `batfish_labval_dc1_leaf2a_eos4230` | 39 | 39 |
| `karneliuk_a_eos1_eos4260` | 4 | 4 |
| `ksator_dcs_7150s64_eos4224` | (interfaces preserved) | — |
| `kitchen_sink` (synthetic) | 13 | 13 |

Because no interface record vanishes, `interfaces[].name`, `.description`,
`.enabled`, `.mtu` and `.ipv6_addresses` are honestly `good` — they are
preserved on every populated cell, not merely "intact on the survivors". The
interface losses on this pair are **per-attribute**, and each one is declared
on its own measured merits.

The structural drops on this pair happen one level up, at whole **top-level
lists**:

| list | source → re-parsed | cells |
|---|---|---|
| `vlans` | 5→0, 8→0, 15→0, 1→0 | 4 |
| `vxlan_vnis` | 3→0, 6→0, 9→0, 1→0 | 4 |
| `dhcp_servers` | 2→0 | 1 |
| `snmp` | whole object → `None` | 2 |
| `anycast_gateway_mac` | MAC → `''` | 2 |

The IOS-XR render emits **no `vlan` line, no `nve`/VXLAN stanza, no `snmp`
line and no DHCP pool** for any of these. These are total drops, so they are
recorded `unsupported` (which blocks) rather than `lossy` (which warns and
stays compatible) — netcanon #436.

## Per-field measurement (6 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 6 | 0 | 0 |
| domain | 2 | 0 | 4 |
| dns_servers | 4 | 0 | 2 |
| ntp_servers | 4 | 0 | 2 |
| syslog_servers | 1 | 0 | 5 |
| interfaces[].name / .enabled | 6 | 0 | 0 |
| interfaces[].description | 4 | 0 | 2 |
| interfaces[].mtu | 1 | 0 | 5 |
| interfaces[].ipv6_addresses | 2 | 0 | 4 |
| interfaces[].ipv4_addresses | 4 | 2 | 0 |
| interfaces[].interface_type | 0 | 6 | 0 |
| interfaces[].lag_member_of | 0 | 3 | 3 |
| vlans[].* | 0 | 4 | 2 |
| static_routes | 5 | 0 | 1 |
| dhcp_servers | 0 | 1 | 5 |
| snmp.community | 0 | 2 | 4 |
| snmp.location / .contact / .trap_hosts / .v3_users | 1 | 1 | 4 |
| lags | 0 | 3 | 3 |
| local_users[].name / .hashed_password | 6 | 0 | 0 |
| local_users[].role | 4 | 2 | 0 |
| vxlan_vnis[].* | 0 | 4 | 2 |
| routing_instances[].name | 4 | 0 | 2 |
| anycast_gateway_mac | 0 | 2 | 4 |

Trivially empty on all 6 cells: `timezone`, `interfaces[].vrrp_groups`,
`radius_servers`, `evpn_type5_routes`, `routing_instances[].description`,
`raw_sections`, `apply_groups`, `group_content`.

## The `vlans[]` sub-field rule, and why five of them are `good`

Every VLAN record disappears, so the mesh measures **all six** `vlans[].*`
keys as drifted on the same 4 cells. That is one signal, not six: the sub-fields
drift for the single reason that the parent list changed length.

The reconciler collapses exactly this case. When a list sub-field's drift is a
wholesale list-length change with no per-record slice, the **first** such key in
the canonical key order keeps its real class and the rest are reclassified
`STRUCTURAL_ONLY`, which the unevidenced ratchet does not accept as evidence.

So `vlans[].id` carries the record-level loss for the whole list and is
`unsupported`; `vlans[].name`, `.ipv4_addresses`, `.untagged_ports`,
`.tagged_ports` and `.description` are `good`. This is **not** a claim that
those values survive — no VLAN record survives on any cell of this pair. It is
the statement that the record vanishing belongs to `vlans[].id`, and that a
loss declared on a sibling could never be evidenced by any cell. The identical
rule applies to `vxlan_vnis[]`: `.vni` is `unsupported`, `.vlan_id` and
`.mcast_group` are `good`.

Counting those five VLAN keys as five independent losses would be the
correlated-drift error, and the ratchet is built to reject it.

## Three findings worth carrying forward

### 1. `interface_type` collapses to `ianaift:other` on 100% of records

152 interface records across all 6 cells, without exception:
`ianaift:ethernetCsmacd` → `ianaift:other`, `ianaift:ieee8023adLag` →
`ianaift:other`.

The mechanism is verifiable rather than mysterious. The IOS-XR render keeps the
Arista interface names verbatim — it emits `interface Ethernet1` and
`interface Port-Channel10`. The IOS-XR parser infers interface type from an
**XR** name prefix (`GigabitEthernet`, `Loopback`, `Bundle-Ether`, `MgmtEth`,
`tunnel-*`), which is exactly what its own `CapabilityMatrix` says it does.
`Ethernet1` matches none of those prefixes, so the type degrades to
`ianaift:other`. Both codecs already declare
`/interfaces/interface/config/type` lossy, so the declaration and the
measurement agree.

Nothing forwarding-related breaks — the addresses, descriptions and admin state
on those same records all survive — but any downstream consumer that filters on
`interface_type` will see an undifferentiated pile of `other`.

### 2. `lags` drift here is a **name-form** change, not a membership loss

The bundle survives completely. Verified on
`batfish_eos_evpn_vlan_based_leaf.txt`:

```
src lags: [('Port-Channel3', ['Ethernet3','Ethernet4']), ('Port-Channel5', ['Ethernet5']), ...]
rt  lags: [('Bundle-Ether3', ['Ethernet3','Ethernet4']), ('Bundle-Ether5', ['Ethernet5']), ...]
```

Members identical, bundle numbers identical, and the render emits
`bundle id 3 mode active` on each member interface. Only the operator-facing
name changes, `Port-Channel<N>` → `Bundle-Ether<N>`, which is the correct
IOS-XR spelling.

The reason it registers as drift at all is a gap in the audit's own alias list.
`_canonical_lag_name()` in `tools/run_phase4_reconciliation.py` maps documented
LAG spellings to a stable `LAG<N>` token so vendor renames do not fire
CODEC_BUG, and its regex is
`^(?:ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond)(\d+)$`. Confirmed
directly:

```
_canonical_lag_name('Port-Channel3') = 'LAG3'
_canonical_lag_name('Bundle-Ether3') = None
```

`Bundle-Ether<N>` is not in the list, so the canonicalisation falls through to
raw equality and the rename surfaces. `lags` and `interfaces[].lag_member_of`
are therefore recorded `lossy` — the canonical name genuinely does not
round-trip as a value — with the reason stating plainly that the aggregation
itself is intact. They are **not** `unsupported`: nothing vanishes.

Adding `Bundle-Ether` to `_LAG_NAME_RE` would retire both declarations. That is
a tool change and is deliberately left outside this pair's files.

### 3. `local_users[].role` is *materialised*, not dropped

IOS-XR renders the canonical role as `group <role>`. When the source user has
**no** role, the IOS-XR codec derives one from `privilege_level`. Reproduced
with a hand-built config (see "Commands that reproduce this" below):

```
src: [('noRole','',15), ('hasRole','network-admin',15), ('lowPriv','',1)]
rt : [('noRole','root-lr',15), ('hasRole','network-admin',1), ('lowPriv','operator',1)]

XR render:  username noRole / group root-lr
            username hasRole / group network-admin
            username lowPriv / group operator
```

This is what the two drifting cells show: `karneliuk_a_eos1_eos4260` (`aaa`,
role `''` → `root-lr`) and `ksator_dcs_7150s64_eos4224` (three privilege-15
users with no role → `root-lr`, one privilege-1 user → `operator`).

Read this precisely. It is **not** a privilege escalation — an EOS
`username X privilege 15` already carries full authority, and `root-lr` is the
faithful IOS-XR spelling of it. What changes is that an implicit authority
becomes an **explicit named grant written into the target config**, which is a
material difference at review time. Roles that were explicitly set survive as
group names.

One adjacent observation, recorded because it is on the same records: the
`privilege_level` re-derived from a surviving group name can move
(`network-admin` 15 → 1). `privilege_level` has no expectation key in the
schema's field list, so it is documented here rather than declared.

## Credential material

`local_users[].hashed_password` is **preserved on all 6 cells** — the stored
secret survives byte-identical, and Arista and IOS-XR both declare
`/local-users/user/hashed-password` supported. This is the good outcome and it
is unusual across the mesh; most pairs lose it.

Hash values are deliberately not reproduced in this file or in the expectation
YAML. Per `AGENTS.md`, stored secrets are operator-traceable even when hashed,
and a document that quotes the value it describes defeats its own redaction.
Only the shape was inspected (length and leading marker).

## Matrix declarations that disagree with measured behaviour

Recorded here because they are codec-level facts, not pair-specific ones, and
belong in a codec change rather than in an expectation file.

- **`cisco_iosxr` declares `/vlans/vlan/id` and `/vlans/vlan/name`
  SUPPORTED** while dropping every VLAN in the corpus — 5→0, 8→0, 15→0, 1→0,
  with no `vlan` line emitted at all. A target-side under-declaration. The
  YAML follows the measurement, not the matrix.
- **`arista_eos` declares nothing at all under `/lags/lag`** (neither
  supported, lossy nor unsupported) although it parses and renders
  port-channels.
- **`arista_eos` declares nothing for `/system/domain`**, and neither does
  `cisco_iosxr`, yet the field round-trips cleanly on both cells that populate
  it (`dns domain lab.local` → intact). A symmetric under-declaration with a
  benign outcome.
- **`arista_eos` declares nothing under `/radius-servers/*`** although
  `parse.py` demonstrably populates `radius_servers` from
  `radius-server host <ip> ... key ...`. This matters: it means the pair's
  `radius_servers` disposition cannot be read off the source matrix as a
  source-side gap. It is a genuine target-side drop.

## Dispositions resting on a hand-built round-trip, not a committed cell

Three keys are trivially empty on all 6 cells. Guessing was declined; a minimal
config was built and round-tripped instead, and the YAML names this in each
`reason` / `note`.

| key | hand-built result | disposition |
|---|---|---|
| `radius_servers` | 1 parsed server → 0 after render; no `radius` line emitted | `unsupported` |
| `interfaces[].vrrp_groups` | 1 parsed group → 0 after render; no `vrrp` line emitted | `unsupported` |
| `routing_instances[].description` | `'Tenant X production VRF'` survives intact inside the rendered `vrf` block | `not_applicable` |

`routing_instances[].description` is left `not_applicable` rather than promoted
to `good`: no committed cell populates it, `arista_eos` declares its own
`/routing-instances/instance/description` path lossy, and one hand-built shape
is not grounds for overriding the source codec's deliberate declaration. Stated
rather than guessed at.

## How to reproduce every claim above

No scratch tooling is needed — the whole measurement is three lines run from
the repo root, read-only, writing no baseline:

```python
import netcanon.migration.codecs                       # registers the codecs
from netcanon.migration.codecs.registry import get_codec

raw      = open(FIXTURE, encoding="utf-8", errors="replace").read()
c0       = get_codec("arista_eos").parse(raw)          # source intent
rendered = get_codec("cisco_iosxr").render(c0)         # target config text
c1       = get_codec("cisco_iosxr").parse(rendered)    # re-parsed intent
```

Then compare `c0` against `c1` for the field in question. The six fixtures of
this pair are:

```
tests/fixtures/real/arista_eos/batfish_duplicateprivate_eos4211.txt
tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt
tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt
tests/fixtures/real/arista_eos/karneliuk_a_eos1_eos4260.txt
tests/fixtures/real/arista_eos/ksator_dcs_7150s64_eos4224.txt
tests/fixtures/synthetic/arista_eos/kitchen_sink.txt
```

Specific checks used above:

- **VLAN / VXLAN / DHCP / SNMP / anycast total drops** — compare `len(c0.vlans)`
  against `len(c1.vlans)` (and the same for `vxlan_vnis`, `dhcp_servers`), and
  check `c1.snmp is None`; then grep `rendered` for `vlan`, `nve`, `snmp`.
- **LAG rename** — compare `[(l.name, l.members) for l in c0.lags]` against the
  same on `c1`, then grep `rendered` for `bundle id`.
- **LAG alias gap** — import `_canonical_lag_name` from
  `tools/run_phase4_reconciliation.py` and call it on `'Port-Channel3'` and
  `'Bundle-Ether3'`.
- **User role materialisation, RADIUS and VRRP** — none of these is populated
  by a committed cell, so build a minimal EOS config containing
  `username X privilege 15 nopassword`, `radius-server host <ip> ... key ...`
  and a `vrrp <n>` stanza, and run the same three lines over it.
- **Per-cell disposition** — `actual_disposition(cell["field_disposition"], key)`
  from `tools/run_phase4_reconciliation.py`, against the cells in
  `tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`. Importing that
  helper is read-only; running the reconciliation pass itself is not, and was
  not done.
