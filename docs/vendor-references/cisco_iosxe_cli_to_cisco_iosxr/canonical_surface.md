# IOS-XE CLI → IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` and
then replayed through the reconciler's `STRUCTURAL_ONLY` collapse, so this file
and the ratchet agree by construction rather than by hope.

- Fixture cells: **15**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand-run round-trips whose exact
> commands are given in the sections that claim them. Where a disposition rests
> on a declaration rather than an observed round-trip, the YAML says so.

## Device-class framing

`cisco_iosxe_cli` in this corpus is a **campus / branch** box — Catalyst 9300
access switches, CSR/Cat8000v branch routers, an EVPN leaf, plus the synthetic
kitchen sink. `cisco_iosxr` is a **service-provider edge/core router**: 4-segment
port names, VRF-heavy, RD derived from `router bgp`, and — the fact that governs
this whole pair — **no campus L2 model at all**.

The realistic migration is therefore a *branch or PE-facing IOS-XE router* being
re-homed onto ASR9k/NCS-class XR. Anything that only makes sense on a campus
switch does not survive, and does not survive *partially* — it is simply gone.

## The structural finding, and how it differs from other pairs

On most audited pairs the dominant loss is the **interface inventory shrinking**,
which drags every `interfaces[].*` sub-field into drift for one reason.

**That does not happen here.** Across all 15 cells, **144 interface records go in
and 144 come out** — not one vanishes. Reproduced with:

```
py <scratchpad>/yz_sweep.py     # parse with cisco_iosxe_cli, render with
                                # cisco_iosxr, re-parse, diff every record
# → interface sub-field drifts across all 15 cells
#   (name/description/enabled/mtu/ipv4_addresses/ipv6_addresses): 0
```

Zero drift on those six sub-fields over 144 records. They are declared `good`
because they *are* good, not because the matrices say so.

The structural collapse on this pair lands somewhere else entirely: on
**`vlans`**, where the whole list is dropped, and on **`vxlan_vnis`**, likewise.
Those two parents are why the YAML has `vlans[].id` and `vxlan_vnis[].vni`
declared first among their siblings — the reconciler's `STRUCTURAL_ONLY` rule
awards the parent's record-level signal to whichever sub-field key appears
**first in YAML insertion order**
(`tools/run_phase4_reconciliation.py`, `structural_parent_claimed`). The
remaining sub-fields of those two lists are `good`: they describe what happens
to the value when a record survives, and no VLAN or VNI record ever survives to
contradict them.

## Per-key measurement (15 cells)

`d` = drifted, `p` = preserved, `t` = trivially empty (both sides had no data,
so the cell could not test the claim).

| key | d | p | t | disposition |
|---|---|---|---|---|
| hostname | 1 | 14 | 0 | lossy |
| domain | 0 | 3 | 12 | good |
| dns_servers | 0 | 1 | 14 | good |
| ntp_servers | 0 | 1 | 14 | good |
| timezone | 0 | 0 | 15 | unsupported |
| syslog_servers | 0 | 3 | 12 | good |
| interfaces[].name | 0 | 11 | 4 | good |
| interfaces[].description | 0 | 8 | 7 | good |
| interfaces[].enabled | 0 | 11 | 4 | good |
| interfaces[].mtu | 0 | 4 | 11 | good |
| interfaces[].ipv6_addresses | 0 | 3 | 12 | good |
| interfaces[].ipv4_addresses | 0 | 9 | 6 | good |
| interfaces[].interface_type | 6 | 5 | 4 | lossy |
| interfaces[].lag_member_of | 3 | 0 | 12 | lossy |
| interfaces[].vrrp_groups | 1 | 0 | 14 | unsupported |
| vlans[].id | 5 | 0 | 10 | unsupported (structural owner) |
| vlans[].name / ipv4_addresses / untagged_ports / tagged_ports / description | 5 | 0 | 10 | good (structural-only) |
| static_routes | 2 | 5 | 8 | lossy |
| dhcp_servers | 1 | 0 | 14 | unsupported |
| snmp.community / location / contact / trap_hosts | 2 | 0 | 13 | unsupported |
| snmp.v3_users | 1 | 1 | 13 | unsupported |
| lags | 3 | 0 | 12 | lossy |
| local_users[].name / role / hashed_password | 0 | 7 | 8 | good |
| radius_servers | 1 | 0 | 14 | unsupported |
| vxlan_vnis[].vni | 1 | 0 | 14 | unsupported (structural owner) |
| vxlan_vnis[].vlan_id / mcast_group | 1 | 0 | 14 | good (structural-only) |
| evpn_type5_routes | 0 | 0 | 15 | unsupported |
| routing_instances[].name | 0 | 3 | 12 | good |
| routing_instances[].description | 0 | 1 | 14 | good |
| raw_sections / apply_groups / group_content | 0 | 0 | 15 | not_applicable |
| anycast_gateway_mac | 0 | 0 | 15 | unsupported |

## Where the campus surface goes: VLANs vanish outright

Four of the five VLAN-bearing cells lose the **entire** list, and the render
contains no `vlan` line at all:

| fixture | source VLANs | after round-trip |
|---|---|---|
| `batfish_cisco_interface.txt` | 9 | 0 |
| `ciscolive_brkops1104_evpn_leaf_iosxe1715.txt` | 3 | 0 |
| `user_contrib_cat9300_iosxe1712.txt` | 6 | 0 |
| `kitchen_sink.txt` | 4 | 0 |

The `cisco_iosxr` matrix is consistent with this on the interface side — it
declares `/interfaces/interface/switchport-mode`, `access-vlan`,
`trunk-allowed-vlans`, `trunk-native-vlan` and `voice-vlan` all **unsupported**,
with the reason *"IOS-XR is SP-routing with no L2 switchport model (L2VPN is
Tier-3)"*. What the matrix does **not** say is that the top-level `vlans` list
goes with them: it declares two `/vlans/vlan/...` paths *supported*. The
measurement is the authority here, and it says the list is emptied.

### The fifth cell is a phantom, not a survivor

`ntc_carrier_interfaces.txt` drifts on `vlans` in the **opposite** direction:
source `0` VLANs, round-trip `1`.

```
py <scratchpad>/yz_detail.py
# src vlans: []   rt vlans: [(2234, '', '')]
```

The source is a carrier box of dot1q sub-interfaces. The XR render writes
`encapsulation dot1q 2234` under each sub-interface; re-parsing that line
materialises a VLAN record that the source never had. It is a fabricated
record, not a rescued one — which is why `vlans[].id` is `unsupported` (records
vanish) rather than `lossy` (records degrade). Per netcanon #436, `lossy` warns
and stays compatible; that would badly understate a switch losing its whole
VLAN database.

## `hostname`: a placeholder, not a dropped value

The single `hostname` drift is the same fixture, and it is a **fail-open
default**:

```
py <scratchpad>/yz_detail.py
# src hostname=''  rt hostname='Router'
# hostname lines in render: ['hostname Router']
```

The mechanism is one line of the renderer —
`netcanon/migration/codecs/cisco_iosxr/render.py:93`:

```python
hostname = tree.hostname or "Router"
```

A source with no hostname yields a config that claims to be a box called
`Router`. Nothing was lost; something was **invented**. It is recorded `lossy`
rather than `unsupported` because the field round-trips perfectly on the other
14 cells and the target plainly supports it — the failure is a substitution,
and an operator diffing the two configs needs to see it flagged.

## `static_routes`: the vanish heuristic was wrong, and here is the proof

The mechanical vanish classifier reports `static_routes TOTAL -> unsupported`
for this pair. It is wrong, and the disagreement was resolved by round-tripping
rather than by preferring one table over the other.

```
py -c "... parse cisco_iosxe_cli, render cisco_iosxr, re-parse, set-compare ..."
# batfish_cisco_ip_route.txt        16 routes -> 16 routes
#   route identity sets equal (ignoring description): True
#   descriptions src: ['bippety', 'boppety']   descriptions rt: []
# racc_csr1_iosxe173_umbrella_sig.txt  22 -> 22
#   0.0.0.0/0 | description 'UMBRELLA_SIG' -> ''
```

Every route survives with destination, gateway, egress interface, metric and
VRF intact. **Only `description` is dropped** — 3 route records across the 2
drifting cells. Both matrices already declare `/routing/static-route/description`
lossy, with the XR reason *"Render emits destination + next-hop only; the
static-route name / description is dropped"*. That is a textbook `lossy`, and
declaring it `unsupported` would have blocked a migration that in fact carries
the entire forwarding table across.

Why the heuristic missed it: it flags a sub-field whose target side is empty,
and `'' `is empty. It cannot see that the *record* survived. Worth remembering
the next time the two tables disagree — the heuristic is a fast screen, not a
verdict.

## SNMP is not degraded; it is absent

The opposite correction, in the opposite direction. The vanish heuristic reports
`snmp partial-> lossy`; the round-trip says otherwise. Rendering
`batfish_cisco_snmp.txt` — a fixture whose whole point is SNMP — produces this
config in its entirety:

```
!! IOS XR Configuration 6.6.2
!
hostname cisco_snmp
!
end
```

Five lines. Community, location (`UC Santa Cruz 4900M`), contact
(`CENIC Core Engineering`) and five trap hosts all gone; `kitchen_sink.txt`
additionally loses 2 SNMPv3 users. The `cisco_iosxr` matrix agrees and is blunt
about why: `/snmp/community` is declared **unsupported**, reason *"SNMP parse +
render is out of the v1 XR scope."*

All five `snmp.*` keys are therefore `unsupported`, and — trap #1 — they are
**one finding, not five**. They share a single cause: the SNMP block is never
emitted. None of them corroborates another.

One artefact worth stating so nobody re-derives it as a contradiction:
`snmp.v3_users` measures `preserved` on one cell. That is
`batfish_cisco_snmp.txt`, whose source has an empty v3-user list; an empty list
"survives" a wholesale drop trivially. The cell that actually carries v3 users
loses both.

## `lags`: a real drift, but the loss is the name — and the audit's own gap

`lags` and `interfaces[].lag_member_of` drift on all 3 LAG-bearing cells. The
bundle itself is **completely intact**:

```
# user_contrib_cat9300_iosxe1712.txt
src lags: Port-channel1 ['Te1/0/1','Te1/0/2','Te1/0/3','Te1/0/4']
          Port-channel2 ['Te1/0/21','Te1/0/22']
          Port-channel3 ['Te1/0/19','Te1/0/20']
rt  lags: Bundle-Ether1 [same 4 members]
          Bundle-Ether2 [same 2 members]
          Bundle-Ether3 [same 2 members]
```

Membership, count and grouping all survive. `Port-channel<N>` → `Bundle-Ether<N>`
is the correct IOS-XR name for the same bundle.

So why does it score as drift? Because the audit's LAG-name canonicaliser does
not know the XR name:

```
py -c "import ...; print(_canonical_lag_name('Port-channel1'), _canonical_lag_name('Bundle-Ether1'))"
# LAG1 None
```

`_LAG_NAME_RE` in `tools/run_phase4_reconciliation.py` accepts
`ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond` — every LAG shape the mesh
has met **except** IOS-XR's `Bundle-Ether<N>`. An unmatched name falls through
to raw string equality, so the rename surfaces as drift on both
`_LAG_NAME_FIELDS` keys.

Both keys are declared `lossy`, and the reason says which loss it is: the
operator-facing name, not the aggregation. **This is a gap in the reconciler's
canonicaliser, not a codec defect** — extending `_LAG_NAME_RE` to cover
`Bundle-Ether<N>` is the real fix, and it belongs in a tool change, not in this
pair's expectation file. Recorded here so the next author does not re-derive it
or, worse, "fix" a codec that is behaving correctly.

## Credential and privilege material

`local_users[].hashed_password` **round-trips byte-identical** on all 7
populated cells — verified by equality, not by eyeball. The XR render re-emits
the IOS secret form under an XR `username` block:

```
username <name>
 group <role>
 secret <type> <hash>          # types 5, 8 and 9 all present in the corpus
```

Hash values are deliberately not reproduced in this file or in the YAML. Per
`AGENTS.md`, crypt-style secrets are operator-traceable material and a document
that quotes the value it describes defeats its own redaction. The *shape* is all
that is needed: an IOS type marker followed by a `$`-prefixed crypt hash.

**One adjacent finding that is not a declared key.** `local_users[].role`
survives (`admin` → XR task group `admin`), but `privilege_level` does **not**:
it reads `15` on the source and `1` after the round-trip, on 11 user records
across 4 cells. XR expresses authorisation as a task group, so the numeric IOS
privilege has nowhere to land and re-parses at the default. The direction is
fail-*closed* (a privilege-15 account arrives as level 1), so it will not silently
grant access — but it will break automation that keys off privilege level. It is
outside the audited key set and so cannot be declared in the YAML; it is recorded
here instead of being silently dropped.

## Source-side reach vs target-side blocks

Three scalars deserve their `good` despite the source matrix declaring nothing
for them: `domain` (3 cells), `dns_servers` (1 cell), `ntp_servers` (1 cell).
The `cisco_iosxe_cli` matrix lists `supported=0` for each, yet the parser emits
them and the XR render carries them through unchanged. The matrices are an
under-declaration here; the measurement is what the YAML follows.

Four keys are trivially empty on all 15 cells, so the **matrices decide**:

- `timezone` — **both** codecs declare `/system/timezone` unsupported. A
  symmetric gap: `unsupported`.
- `anycast_gateway_mac` — source declares it supported, target declares
  `/anycast-gateway-mac` unsupported (*"IOS-XR has no VARP /
  distributed-anycast-gateway grammar"*). A target-side block: `unsupported`.
- `evpn_type5_routes` — source declares the path lossy, target declares it
  unsupported (*"IOS-XR EVPN runs under top-level `l2vpn` + `evpn` + `bridge
  group` … No canonical mapping in v1"*). Target-side block: `unsupported`.
- `raw_sections`, `apply_groups`, `group_content` — neither codec declares
  anything and no cell populates them. `not_applicable`.

None of these four rests on an observed round-trip, and the YAML says so on each
one rather than implying a measurement that was never taken.

## VRFs: the surface XR is actually built for

`routing_instances[].name` and `[].description` are preserved on every populated
cell — the one part of an SP-relevant config that crosses cleanly. Two caveats
that are *not* in the declared key set and so live here:

- The XR matrix declares `/routing-instances/instance` **lossy** because
  `route_distinguisher` is re-derived rather than carried. RD is not an audited
  key on this pair.
- `l3_vni` drops (`100200` → `null`) on `ciscolive_brkops1104_evpn_leaf_iosxe1715.txt`
  — the EVPN L3VNI binding, consistent with the VXLAN list being dropped
  wholesale. Also not an audited key.

Neither affects the two declared keys, both of which are honestly `good`.
