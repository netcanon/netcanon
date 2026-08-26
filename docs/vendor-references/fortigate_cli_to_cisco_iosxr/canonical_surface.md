# FortiGate CLI → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/fortigate_cli__cisco_iosxr.yaml`.

**Source of every number here:** the committed `tools/run_full_mesh.py` run
(`tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`), plus a
hand-run parse → render → re-parse of all four cells through the public codec
API. Per-key dispositions were resolved through the audit's own
`actual_disposition()` and the reconciler's structural-collapse rule rather
than inferred from the drift shape, so this file and the ratchet agree by
construction.

- Fixture cells: **4**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the committed fixtures, the measured mesh run, and round-trips
> the author ran personally. Where a disposition rests on a declaration rather
> than an observed round-trip, the YAML says so in that key's own words.

## Reproducing every number below

```python
from netcanon.migration.codecs.registry import get_codec
import netcanon.migration.codecs  # registers the codecs

src, tgt = get_codec("fortigate_cli"), get_codec("cisco_iosxr")
c0 = src.parse(open(FIXTURE, encoding="utf-8", errors="replace").read())
rendered = tgt.render(c0)
c1 = tgt.parse(rendered)          # compare c0 vs c1 field by field
```

The four cells:

| fixture | interfaces | vlans | lags | dhcp pools | radius | snmp | users |
|---|---|---|---|---|---|---|---|
| `tests/fixtures/real/fortigate/kevinguenay_fgt_70g_branch.conf` | 21 | 2 | 2 | 1 | 0 | – | 1 |
| `tests/fixtures/real/fortigate/kevinguenay_fgt_vm_hub.conf` | 19 | 0 | 1 | 1 | 0 | – | 1 |
| `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf` | 34 | 5 | 2 | 6 | 1 | yes | 3 |
| `tests/fixtures/synthetic/fortigate_cli/kitchen_sink.conf` | 12 | 3 | 2 | 2 | 2 | yes | 3 |

## Device-class framing

`fortigate_cli` in this corpus is a **branch / hub NGFW** — a FortiGate 70G
branch box, a FortiGate-VM hub, a FortiGate 100E, and the synthetic
kitchen-sink. `cisco_iosxr` is a **service-provider edge/core router**: four-
segment port names, a heavy VRF surface, route-distinguishers read from
`router bgp`, and no campus L2 model at all.

The pair is therefore asymmetric in an unusual way. The shared surface is
narrow but *clean* — hostname, DNS, NTP, interface addressing, static routes,
local-user identity all round-trip intact. What does not survive is
everything that makes the FortiGate a firewall rather than a router: DHCP
service, SNMP, RADIUS, VLAN tags, and most LAG membership. And the target's
own strength — VRFs — receives nothing, because the source models no routing
instances at all.

## The structural finding: interfaces survive, VLANs do not

Unlike the campus-to-DC pairs in this audit, **the interface inventory does
not shrink**: 21 → 21, 19 → 19, 34 → 34, 12 → 12. All 86 source interface
records reach the render. `description`, `enabled`, `mtu`, `ipv4_addresses`
and `ipv6_addresses` drift on **zero** of them. Those keys are `good` on
measurement, not on optimism.

The record that vanishes is the **VLAN**: 2 → 0, 5 → 0, 3 → 0 on the three
cells that carry VLANs. The rendered IOS-XR config contains no `vlan`
construct of any kind.

The mechanism is a two-sided declaration mismatch, and it is worth stating
precisely because both matrices are individually truthful:

- `cisco_iosxr` declares `/vlans/vlan/id` and `/vlans/vlan/name` **supported**
  — but its own supported-path comment scopes that to VLANs *synthesised from
  `encapsulation dot1q <tag>` on a routed sub-interface* ("no port
  membership; name always empty").
- `fortigate_cli` declares `/interfaces/interface/dot1q-vlan` **unsupported**,
  and sets `dot1q_vlan` on **none** of the 86 source interface records.

FortiOS carries the tag on the VLAN record itself (`set type vlan` +
`set vlanid 100` under `config system interface`). The only path by which
IOS-XR can re-emit a VLAN is the interface tag the source never populates, so
the render emits no `encapsulation dot1q` line and every VLAN record drops.
Reasoning from either matrix alone gets this wrong in both directions.

## The other structural finding: single-token grammar slots

Two unrelated-looking losses share one root cause — **a FortiGate value
containing a space meeting an IOS-XR grammar slot that is a single token**:

1. `interface lacp trunk` renders verbatim and re-parses as `lacp`. One
   record of 86 (`user_contrib_fg100e_fos7213.conf`).
2. `secret 0 fortios:ENC <ciphertext>` re-parses as the bare marker
   `fortios:ENC`. The parse regex is `secret\s+(\d+)\s+(\S+)` — it stops at
   the space, and everything after it is discarded.

Rename any FortiGate interface whose name contains whitespace before cutover;
the password case is covered under *Credential material* below.

## Per-field measurement (4 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 4 | 0 | 0 |
| domain | 1 | 0 | 3 |
| dns_servers | 4 | 0 | 0 |
| ntp_servers | 1 | 0 | 3 |
| interfaces[].description / enabled / mtu / ipv4 / ipv6 | see below | 0 | – |
| interfaces[].name | – | 1 record of 86 | – |
| interfaces[].interface_type | 1 record | 84 records | – |
| interfaces[].lag_member_of | – | 12 records | – |
| vlans[].* | 0 | 3 (whole record) | 1 |
| static_routes | 3 | 0 | 1 |
| dhcp_servers | 0 | 4 (whole record) | 0 |
| snmp.* | 0 | 2 (whole object) | 2 |
| lags | 0 | 4 | 0 |
| local_users[].name / role | 4 | 0 | 0 |
| local_users[].hashed_password | 0 | 4 (6 of the 8 user records) | 0 |
| radius_servers | 0 | 2 (whole record) | 2 |

Fields trivially empty on all 4 cells: `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, `vxlan_vnis[].*`, `evpn_type5_routes`,
`routing_instances[].*`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

Interface sub-field drift, counted over all 86 records (author-run
aggregate, not a single sample): `interface_type` 84 · `lag_member_of` 12 ·
`name` 1 · `description` 0 · `enabled` 0 · `mtu` 0 · `ipv4_addresses` 0 ·
`ipv6_addresses` 0. The `interface_type` collapse is uniform —
68 `ethernetCsmacd`, 10 `l3ipvlan` and 6 `ieee8023adLag` all land on
`ianaift:other`; only `loopback0` keeps `softwareLoopback`, because the XR
parser infers type from a name prefix and FortiGate names (`port1`, `dmz`,
`wan1`, `agg1`, `VL_200`) match none of them.

## Source-side gaps vs target-side drops

`fortigate_cli` declares these unsupported at the exact path, so as a
*source* it never emits them:

`/system/timezone` · `/system/syslog-server` · `/routing-instances/instance`
· `/vlans/vlan/tagged-ports` · `/vlans/vlan/untagged-ports` ·
`/interfaces/interface/dot1q-vlan`

Two of those are worth separating from the rest, because the device config
*does* carry the data and the codec drops it at parse time — verified by
grepping the fixtures:

- `set timezone "Europe/Amsterdam"` (branch, hub) and `set timezone 04`
  (fg100e) exist in the source text; `intent.timezone` is `""` on all four
  cells. `cisco_iosxr` also declares `/system/timezone` unsupported, so this
  is a **symmetric** gap → `unsupported`.
- `config log syslogd setting` blocks exist in three fixtures;
  `intent.syslog_servers` is `[]` on all four cells. Here `cisco_iosxr`
  declares syslog **supported**, so re-authoring `logging <host>` on the
  target will stick → `not_applicable`, a source-side gap.

Target-side drops — the source populates them and `cisco_iosxr` declares them
unsupported, so they vanish on render: `/dhcp-servers/pool` ·
`/radius-servers/server/host` + `/key` · `/snmp/community` (and the v3-user
children) · `/interfaces/interface/vrrp-groups/group`.

## Where the drift-shape probe and the matrix disagreed

The wave's vanish heuristic classified `snmp` as a *partial* degradation.
It is not: the whole object drops. The heuristic looks for an "all N …
dropped" phrasing, and the SNMP drift is recorded as
`snmp: {…} → None`, which it reads as a value change.

Settled by round-trip rather than by argument: on both cells that populate
SNMP, `c1.snmp is None` and the rendered config contains **zero** lines
matching `snmp`. That agrees with the `cisco_iosxr` declaration ("SNMP parse
+ render is out of the v1 XR scope") and disagrees with the heuristic, so the
YAML records `unsupported` for all five `snmp.*` keys.

The same cross-check ran the other way for `vlans`: there the *matrix* looked
permissive (two supported paths) and the round-trip proved a total drop. Both
disagreements were resolved by inspecting output, not by preferring one
source of truth.

## One finding worth carrying forward: `lags` is conditional

`lags` is the only key on this pair whose outcome depends on the *source
name*, and it is `lossy` rather than `unsupported` for that reason:

- `agg1` / `agg2` (kitchen-sink) **survive**. Members re-emit
  ` bundle id 1 mode active`, and the re-parse reconstructs `Bundle-Ether1`
  with `['port2', 'port3']` intact. A vendor-correct rename.
- `fortilink`, `LAG_INTERNAL`, `lacp trunk` (all three real fixtures)
  **vanish**: 2 → 0, 1 → 0, 2 → 0. No `bundle` line is emitted at all.

The render helper emits membership only when `re.search(r"(\d+)\s*$", …)`
matches the LAG name — a trailing-digit requirement FortiGate's default
`fortilink` and operator-chosen names do not meet.

Two consequences for how this file's numbers should be read:

1. `interfaces[].lag_member_of` drifts from **the same mechanism**. It is a
   second key, not a second piece of evidence, and the YAML says so.
2. The audit canonicalises `agg<N>` → `LAG<N>` but has no `Bundle-Ether<N>`
   shape in `_LAG_NAME_RE`, so the surviving case still scores as drift. That
   is a scoring artifact on the surviving cell; the operative loss is the
   non-digit case.

Separately, and left for a codec change rather than fixed here:
`fortigate_cli` declares **nothing** for `/lags/lag` — neither supported,
lossy nor unsupported — while its parser plainly produces LAG records (2, 1,
2 and 2 across the corpus). A source-side matrix under-declaration.

## Credential material

`local_users[].hashed_password` drifts on all 6 populated records (of 8 user
records; the fg100e cell's two RADIUS-backed accounts carry no local secret).

FortiOS stores the admin secret as a `fortios:ENC`-prefixed ciphertext blob.
The XR render places it in the `secret 0` slot — the type-0, plaintext-marker
form, per the codec's own docstring — and the re-parse recovers only the bare
`fortios:ENC` marker: a 226-character source value re-parses as 11
characters.

Two separable consequences:

- **Every migrated account arrives without a usable credential.** Set
  passwords on the target before cutover, or the accounts are unusable.
- **The intermediate render carries the ciphertext in a plaintext-marked
  slot.** Treat the rendered config as sensitive material, not as a
  safe-to-circulate artefact.

The ciphertext values are deliberately not reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes
defeats its own redaction. The same applies to the two SNMPv3 users on the
kitchen-sink cell, whose auth and privacy passphrases are described by shape
only.

## Drift outside the audited key set

Two fields drift on this pair that the 43-key audit list does not name.
Recording them here so they are not rediscovered as surprises:

- `local_users[].privilege_level` collapses `15 → 1` on every admin record
  (4 records). IOS-XR carries no numeric privilege level; the role *string*
  survives in `group <role>`, the numeric privilege does not. This is why
  `local_users[].role` being `good` should not be read as "authorisation
  migrated" — the render emits the FortiGate profile name verbatim as an XR
  task-group name, so a label survives that the target may have no group for.
- `interfaces[].dhcp_client_v6` drops `dhcp6 → ""` on 2 records (`wan1`,
  `wan2` on the branch cell). An interface that took its IPv6 address from
  DHCPv6 arrives with neither the address nor the client.

## Certainty

`medium`. Every non-trivial disposition on this pair was verified by a
personally-run round-trip on the fixture cited in its `reason`. The
`unsupported` calls on `interfaces[].vrrp_groups`, `vxlan_vnis[].*` and
`anycast_gateway_mac` rest on the two capability matrices agreeing, with no
cell exercising them — each of those keys says so in its own text rather than
implying a measurement.
