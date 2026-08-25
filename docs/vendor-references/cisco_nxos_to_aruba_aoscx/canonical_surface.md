# NX-OS → ArubaOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_nxos__aruba_aoscx.yaml`.

**Source of every number here:** the committed `tools/run_full_mesh.py` pass
(`tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`), reconciled
with `tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved
through the audit's own `actual_disposition()` rather than inferred from the
drift shape, so this file and the ratchet agree by construction. Every claim
below that a record "survives" or "vanishes" was additionally re-derived by
parsing the fixture with `cisco_nxos` and rendering with `aruba_aoscx`
directly.

- Fixture cells: **13**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and direct parse → render → re-parse
> probes. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

Both codecs declare `device_classes=[switch, router]`
(`netcanon/migration/codecs/cisco_nxos/codec.py:118`,
`netcanon/migration/codecs/aruba_aoscx/codec.py:124`). This pair is therefore
**not** device-class-asymmetric the way `aruba_aoscx → arista_eos` is: an
NX-OS leaf and an AOS-CX 8xxx/6xxx both claim the switch-plus-router surface.
Everything lost below is a *codec-surface* loss, not a "the target is a
different kind of box" loss — which matters, because most of it is
recoverable rather than fundamental.

## The structural finding: the interface list does NOT shrink

Worth stating first because it is the opposite of the `aruba_aoscx →
arista_eos` pair, and because assuming otherwise would corrupt every
`interfaces[].*` disposition:

| cell | source interfaces | re-parsed interfaces |
|---|---|---|
| akarneliuk_evpn_vxlan_mcast_leaf_c1l1 | 19 | 19 |
| batfish_nxos_bgp_redist_d1 | 129 | 129 |
| batfish_nxos_evpn_l2vni_nx1 | 131 | 131 |
| batfish_nxos_evpn_l3vni_nx1 / nx2 | 132 | 132 |
| batfish_nxos_hsrp_nxos1 / nxos2 | 134 | 134 |
| batfish_nxos_n9kv_ebgp_r1 | 66 | 66 |
| busterswt_spine_leaf_xk32_1 | 72 | 72 |
| nautobot_gc_nxos_snmp_spine01 | 67 | 67 |
| networklessons_clab_dag_symmetric_irb_leaf1 | 70 | 70 |
| networklessons_clab_vxlan_mcast_leaf2 | 4 | 4 |
| kitchen_sink | 12 | 12 |

Record count is preserved on **13 of 13 cells**. `interfaces[].name`,
`description`, `enabled`, `mtu`, `ipv4_addresses` and `ipv6_addresses` are all
`good`, and they are good *on their own merits* — no record drop is
propagating into them.

## The real root cause: untranslated port names

Five separate keys drift, and **they drift for one shared reason**. This is
stated explicitly because correlated drift is not independent evidence: none
of the five corroborates any other, and the YAML entries say so rather than
citing each other.

`aruba_aoscx/render.py:_render_interface` gates the entire L2 block on the
port name classifying as a real AOS-CX port:

```python
kind = _port_names.classify_port_name(iface.name).kind
is_l2 = (
    kind in ("physical", "lag")
    and iface.switchport_mode in ("access", "trunk")
)
```

`classify_port_name` expects the AOS-CX `<stack>/<module>/<port>` shape.
Fed NX-OS names it returns `kind='unknown'`:

| name | classified kind |
|---|---|
| `1/1/3` | `physical` |
| `lag 1` | `lag` |
| `vlan 10` | `svi` |
| `Ethernet1/3` | **`unknown`** |
| `port-channel1` | **`unknown`** |
| `Vlan10` | **`unknown`** |
| `loopback0` | **`unknown`** |

The mesh audit renders straight from the parsed intent with no port-rename
pass (the bare `run_plan` path — see
`feedback_demo_bare_run_plan_no_port_xlate`), so every physical port arrives
at the renderer as `unknown` and the `no routing` / `vlan access` / `vlan
trunk` / `lacp mode` block is skipped for all of them.

Consequences, all five from that one gate:

1. `vlans[].untagged_ports` and `vlans[].tagged_ports` render empty.
2. `interfaces[].interface_type` degrades to `ianaift:other`.
3. `lags[].mode` re-parses as `static` because `lacp mode` is emitted only on
   a stanza named `lag <N>`.
4. `interfaces[].lag_member_of` changes token (see below).

**Proven recoverable.** Running `translate_port_names(intent, cisco_nxos,
aruba_aoscx, rename_map={})` before the render — the `_with_rename` /
`run_plan_with_overrides` path — restores all of it on `kitchen_sink.cfg`:

```
applied: Ethernet1/3 -> 1/1/3, port-channel1 -> lag 1, Vlan10 -> vlan 10,
         loopback0 -> loopback 0, mgmt0 -> mgmt
render:  no routing / vlan access 10 / vlan trunk native 1 /
         vlan trunk allowed 10,20,30 / lacp mode active
re-parse: vlan 10 untagged=['1/1/3'] tagged=['1/1/4','lag 1']
          1/1/3 access=10 · 1/1/4 trunk=[10,20,30] native=1
          lag 1 mode='active'
          1/1/1 ianaift:ethernetCsmacd · lag 1 ianaift:ieee8023adLag ·
          loopback 0 ianaift:softwareLoopback · vlan 10 ianaift:l3ipvlan
```

The dispositions in the YAML record what the **audited** path measures, which
is the honest thing for a ratchet to gate on. The operator instruction in each
of those entries is the same: run the migration with port translation
engaged.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 0 | 2 | 11 |
| ntp_servers | 0 | 1 | 12 |
| syslog_servers | 0 | 1 | 12 |
| interfaces[].name / description / enabled / mtu / ipv4 / ipv6 | 3–13 | 0 | 0–10 |
| interfaces[].interface_type | 0 | 13 | 0 |
| interfaces[].lag_member_of | 0 | 5 | 8 |
| interfaces[].vrrp_groups | 0 | 4 | 9 |
| vlans[].id | 13 | 0 | 0 |
| vlans[].name | 5 | 0 | 8 |
| vlans[].ipv4_addresses | 0 | 6 | 7 |
| vlans[].untagged_ports | 0 | 8 | 5 |
| vlans[].tagged_ports | 0 | 4 | 9 |
| static_routes | 4 | 4 | 5 |
| snmp.community / location / contact | 11 | 0 | 2 |
| snmp.trap_hosts | 9 | 2 | 2 |
| snmp.v3_users | 0 | 11 | 2 |
| lags | 0 | 5 | 8 |
| local_users[].name / role | 9 | 0 | 4 |
| local_users[].hashed_password | 0 | 9 | 4 |
| vxlan_vnis[].vni / vlan_id | 8 | 0 | 5 |
| vxlan_vnis[].mcast_group | 0 | 2 | 11 |
| routing_instances[].name | 12 | 0 | 1 |
| routing_instances[].description | 0 | 1 | 12 |
| anycast_gateway_mac | 4 | 3 | 6 |

Fields trivially empty on all 13 cells: `dns_servers`, `timezone`,
`dhcp_servers`, `radius_servers`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `vlans[].description`.

## Source-side gaps vs target-side drops

The NX-OS source is the *rich* side on the system scalars. `cisco_nxos`
declares `/system/domain`, `/system/dns-server`, `/system/ntp-server` and
`/system/syslog-server` **supported**; `aruba_aoscx` declares all four
**unsupported** with matching reasons ("Render emits no name-server config",
"Render emits no logging/syslog config", …). These are target-side drops, so
they are recorded `unsupported`, not `not_applicable` — re-authoring on the
target will not help until the AOS-CX render side is wired.

`timezone`, `dhcp_servers` and `radius_servers` are **symmetric** declared
gaps: both matrices declare `/system/timezone`, `/dhcp-servers/pool` and both
`/radius-servers/server/*` leaves unsupported. Also `unsupported`, and
flagged in the YAML as declaration-only — no cell populates them, so no
round-trip was observed.

`vlans[].description` is the one true **source-side** gap on this pair:
`aruba_aoscx` declares `/vlans/vlan/description` **supported**, while the
NX-OS parser never populates it (0 descriptions across all 13 cells — NX-OS
carries a VLAN `name`, not a separate description line, and `cisco_nxos`
declares the path lossy on its own render side for that reason). Recorded
`not_applicable`.

## Findings worth carrying forward

**1. `anycast_gateway_mac` is conditional, and the matrices do not say so.**
Both codecs declare `/anycast-gateway-mac` **supported**, yet the value blanks
on 3 of the 7 cells that populate it (`batfish_nxos_evpn_l2vni_nx1`,
`batfish_nxos_evpn_l3vni_nx1`, `batfish_nxos_evpn_l3vni_nx2`) and survives on
the other 4. Probing shows why: `aruba_aoscx` has no standalone chassis-wide
anycast-MAC directive — the MAC is emitted only as `active-gateway ip mac
<mac>` *inside* an SVI stanza that also carries `active-gateway ip <vip>`. On
`kitchen_sink.cfg`, `Vlan20` carries a `virtual_gateway_address`, both lines
render, and the MAC round-trips. On the three batfish EVPN cells no SVI
carries an address at all, so no `active-gateway` line is emitted anywhere and
the global MAC has nowhere to land.

That is a **matrix under-declaration** — a supported-at-the-exact-path
declaration that is really "supported *if* at least one SVI carries an anycast
VIP". It belongs in a codec change, not in this pair file, and is left as a
finding rather than patched here.

The heuristic total-drop classifier calls this row `TOTAL → unsupported`. It
is wrong here for a mechanical reason: `anycast_gateway_mac` is a **scalar**,
so it can only ever drop wholly, and the classifier reads that as a vanished
record. It is not one — the value survives intact on 4 of 7 cells. Recorded
`lossy`.

**2. `vlans[].ipv4_addresses` is a re-mount, not a loss.** The heuristic
classifier calls the `vlans` parent `TOTAL → unsupported`; the `aruba_aoscx`
matrix declares `/vlans/vlan/ipv4/address/ip` **lossy**. The probe settles it.
On `kitchen_sink.cfg` the source carries the SVI address on *both* canonical
mounts, and after the round-trip:

```
src vlan 10 ipv4=[('10.10.10.1', 24, '')]   → tgt vlan 10 ipv4=[]
src Vlan10  ipv4=[('10.10.10.1', 24, '')]   → tgt Vlan10  ipv4=[('10.10.10.1', 24, '')]
src Vlan20  ipv4=[('10.20.20.1', 24, '10.20.20.1')]
                                            → tgt Vlan20  ipv4=[('10.20.20.1', 24, '10.20.20.1')]
```

The address, its prefix length and its anycast virtual-gateway companion all
survive — on the `interfaces[]` mount. Only the VLAN-record copy is emptied,
because `aruba_aoscx` renders SVI L3 from the sibling `interface vlan N`
stanza and never re-projects it back onto the VLAN record on re-parse. The
rendered config is complete. `lossy`, and the YAML says plainly that
`interfaces[].ipv4_addresses` is `good` for exactly this reason.

**3. Every static route that vanishes is VRF-bound.** Four cells drift; the
cause is identical on all four and matches the target's declaration that
`/routing/static-route/vrf` is unsupported ("only default-VRF `ip route` is
wired"):

| cell | source routes | survives |
|---|---|---|
| kitchen_sink | `0.0.0.0/0` vrf `''`, `10.100.0.0/16` vrf `''`, `10.50.0.0/16` vrf `TENANT-A` | first two |
| busterswt_spine_leaf_xk32_1 | `0.0.0.0/0` vrf `''`, `0.0.0.0/0` vrf `management` | first |
| akarneliuk_evpn_vxlan_mcast_leaf_c1l1 | `0.0.0.0/0` + `::/0`, both vrf `management` | **none** |
| batfish_nxos_n9kv_ebgp_r1 | `0.0.0.0/0` + `0::/0`, both vrf `management` | **none** |

Default-VRF routes survive verbatim on every cell that has them. The two
"all N dropped" cells are cells whose *entire* route table was
management-VRF-bound — those devices render with an empty routing table.
Recorded `lossy` rather than `unsupported`: the target declares
`/routing/static-route` supported at the exact path and demonstrably emits
`ip route` lines, so `validate_against` warning is the correct signal; the
`unsupported` precedent (#436) applies to a target that renders no routes at
all, which is not this pair.

**4. `interfaces[].lag_member_of` drift is a rename the canonicaliser misses.**
The audit canonicalises LAG names before comparing (`_LAG_NAME_FIELDS` →
`_canonical_lag_name`) precisely so a vendor-correct rename does not fire a
CODEC_BUG. Its regex is
`^(?:ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond)(\d+)$` — anchored, and
case-sensitive. NX-OS emits lowercase `port-channel1`; AOS-CX emits
`lag 1` with a space. **Neither matches**, so both sides fall through to raw
equality and the rename registers as drift on all 5 populated cells.

The aggregation itself is intact — `Ethernet1/5` and `Ethernet1/6` both leave
`port-channel1` and both arrive in `lag 1`, and the LAG record keeps its
member list. Read this row as "the bundle token changed", not "membership was
lost". The `lags` row below is the one that carries a real semantic loss, and
it was proven separately.

**5. `lags` loses LACP, not membership.** Members survive
(`['Ethernet1/5','Ethernet1/6']` on both sides); `mode` goes
`active` → `static`. The bare render emits `interface port-channel1` with a
description and nothing else, and puts `lag 1` on each member — so on
re-parse the bundle is a static trunk. With port translation engaged the same
fixture renders `interface lag 1 … lacp mode active` and re-parses as
`active`. **Operationally this is the most dangerous row on the pair**: a
static bundle facing an LACP peer does not negotiate, and depending on the
peer's failure mode either black-holes or forms a loop.

**6. SNMP splits cleanly by version.** `community`, `location` and `contact`
are preserved on all 11 populated cells. `trap_hosts` drifts on exactly the 2
cells that actually carry a receiver (`nautobot_gc_nxos_snmp_spine01`:
`10.1.1.1` → dropped; `kitchen_sink`: `192.0.2.50` → dropped) and the target
declares `/snmp/trap-host` unsupported — "the `snmp-server host <ip> trap
version … community …` trap-receiver grammar is deferred". The record vanishes
entirely, so that row is `unsupported`. `v3_users` drifts on all 11: the USM
user record survives with its name and auth protocol, while the VACM `group`
binding is blanked on every cell that had one, the per-user `engine_id` is
blanked on all 4 cells that carry one, the privacy passphrase is dropped on 7
cells, and `aes128` normalises to `aes`. Six `/snmp/v3-user/*` child
paths are declared lossy on the target for exactly these reasons. The record
survives, so that row is `lossy`.

## Credential material

`local_users[].hashed_password` drifts on all 9 populated cells while
`local_users[].name` and `local_users[].role` are preserved on all 9.

The NX-OS source stores the user secret as a type marker followed by a
crypt(3) SHA-256 hash (the `$5$…` family). After the round-trip the canonical
field retains only the leading numeric type marker — a single character — and
the digest is gone. `privilege_level` also collapses (15 → 1), which the
target declares lossy: AOS-CX uses a named group rather than a numeric
privilege and the codec maps administrators → 15 and everything else → 1.

Every migrated account therefore arrives **without a usable credential**. Set
passwords on the target before cutover and re-check role assignment, or the
accounts are unusable and the privileged one is no longer privileged.

No secret value — NX-OS crypt hash, AOS-CX `AQ…`-prefixed ciphertext blob, or
SNMPv3 passphrase — is reproduced in this file or in the expectation YAML. Per
`AGENTS.md`, encrypted secrets are operator-traceable even when encrypted, and
a document that quotes the value it describes defeats its own redaction. Only
shapes and lengths are given.
