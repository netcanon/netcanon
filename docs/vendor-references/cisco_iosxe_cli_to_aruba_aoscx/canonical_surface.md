# Cisco IOS-XE CLI → Aruba AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__aruba_aoscx.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus (run `20260825T024200Z`), reconciled with
`tools/run_phase4_reconciliation.py`. Per-key dispositions were resolved through
the audit's own `actual_disposition()` rather than inferred from the drift
shape, so this file and the ratchet agree by construction. Every *mechanism*
claimed below was additionally re-derived in a standalone read-only probe:
parse the fixture with `cisco_iosxe_cli`, render with `aruba_aoscx`, re-parse
the render, and look at the output.

- Fixture cells: **15**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and round-trip probes against the
> committed fixtures. Where a disposition rests on a declaration rather than an
> observed round-trip, the YAML says so explicitly.

## Device-class framing

The two sides of this pair are not the same kind of box, and the source side is
not even internally consistent. The `cisco_iosxe_cli` corpus spans **campus
Catalyst switches** (`user_contrib_cat9300_iosxe1712`,
`cml_saumur_iosxe1712_pvrstp`), **routers** (`racc_csr1000v_iosxe169_bgp_ospf`,
`racc_cat8000v_iosxe179_netconf`, `racc_csr1_iosxe173_umbrella_sig`), a
**carrier sub-interface aggregation** config (`ntc_carrier_interfaces`) and an
**EVPN leaf** (`ciscolive_brkops1104_evpn_leaf_iosxe1715`). `aruba_aoscx` is a
campus access/aggregation switch.

The realistic migration is therefore the Catalyst subset: a campus closet or
small-aggregation Catalyst replaced by an AOS-CX switch carrying the same VLAN
database, SVI addressing, uplink LAGs, local users and SNMP. The router-only
surface has no AOS-CX home at all and shows up as declared drops:
`/interfaces/interface/tunnel-type` (GRE / IPsec) is declared **lossy** by
`aruba_aoscx`, `/interfaces/interface/dot1q-vlan` (routed
`GigabitEthernet2/0/4.223415`-style sub-interfaces) is declared **unsupported**,
and both were measured drifting. Neither is a YAML key on this pair, but a
planner migrating an ISR/CSR rather than a Catalyst should read them as a
warning that this is the wrong pair for that box.

## The structural finding: one root cause, four symptoms

**The interface inventory does NOT shrink on this pair.** 144 interface records
in, 144 out, every `name` intact across all 15 cells. That is the opposite of
the AOS-CX→EOS pair, and it means `interfaces[].name`, `.description`,
`.enabled`, `.mtu`, `.ipv4_addresses` and `.ipv6_addresses` are all genuinely
`good` — declaring a loss on any of them would be an unevidenced over-claim.

What *does* happen is a single mechanism with four separate measured symptoms.
`aruba_aoscx` classifies an interface by the **shape of its name**
(`netcanon/migration/codecs/aruba_aoscx/port_names.py`): `1/1/1` → physical,
`vlan N` → SVI, `lag N` → LAG, `loopback N` → loopback, `mgmt` → mgmt.
**Every Cisco-shaped name classifies as `unknown`** — verified directly:
`TenGigabitEthernet1/0/1`, `GigabitEthernet0/0/1`, `Port-channel1`, `Vlan10`
and `Loopback0` all return `kind="unknown"`.

Four render gates key off that classification, and all four fail closed:

| symptom | gate | measured across 15 cells |
|---|---|---|
| `interfaces[].interface_type` → `ianaift:other` | AOS-CX declares no IANA ifType; it is inferred from the name shape | **144 of 144** records |
| `switchport_mode` / `access_vlan` / `trunk_*` dropped | `render.py` emits the L2 block only when `kind in ("physical", "lag")` | **40 L2 ports in, 0 out** |
| `vlans[].untagged_ports` / `tagged_ports` emptied | membership is rebuilt from the interface stanzas that were never emitted | **95 port-to-VLAN bindings in, 0 out** |
| `lags[].mode` → `static` | `lacp mode` is emitted only on a `kind == "lag"` stanza | **6 LACP bundles in, 0 out** |

These four are **one loss reported four times**, not four independent findings.
`vlans[].untagged_ports` drifting is not corroboration that `interface_type` is
broken, and vice versa — they share a cause. The YAML says so on each key.

### The recovery, measured

The loss is an artefact of a **bare render with no port-name translation**, and
it is fully recoverable. Re-running `kitchen_sink.txt` through
`netcanon.migration.canonical.port_names.translate_port_names()` before the
`aruba_aoscx` render translated 14 of the 15 interface names to AOS-CX shape
(`TenGigabitEthernet1/0/1` → `1/1/1`, `Port-channel1` → `lag 1`, `Vlan10` →
`vlan 10`, `Loopback0` → `loopback 0`) and recovered, exactly:

- `interface_type` on all 14 renamed records (`ethernetCsmacd`,
  `ieee8023adLag`, `l3ipvlan`, `softwareLoopback` all round-trip);
- `switchport_mode`, `access_vlan`, `trunk_allowed_vlans`,
  `trunk_native_vlan` on every L2 port;
- all four VLANs' untagged/tagged member lists;
- `lacp mode active` / `passive` on both LAGs.

The one interface that stayed Cisco-named — `GigabitEthernet0`, the OOB
management port — kept `ianaift:other`.

**Operator consequence:** do not plan this cutover off a bare `run_plan`. Use
the path that engages `translate_port_names` (the default `/plan` route does,
via `run_plan_with_overrides(port_rename_map={})`) and hand-map anything the
auto-classifier leaves behind. The dispositions in the YAML describe the bare
render, because that is what the mesh measures and what the ratchet scores.

## Per-field measurement (15 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 14 | 1 | 0 |
| interfaces[].name / .description / .enabled / .mtu / .ipv4_addresses / .ipv6_addresses | 3–11 | 0 | 4–12 |
| interfaces[].interface_type | 0 | 11 | 4 |
| interfaces[].lag_member_of | 0 | 3 | 12 |
| interfaces[].vrrp_groups | 0 | 1 | 14 |
| vlans[].id | 4 | 0 | 11 |
| vlans[].name | 2 | 0 | 13 |
| vlans[].ipv4_addresses | 0 | 3 | 12 |
| vlans[].untagged_ports | 0 | 4 | 11 |
| vlans[].tagged_ports | 0 | 2 | 13 |
| static_routes | 4 | 3 | 8 |
| snmp.community / .location / .contact | 2 | 0 | 13 |
| snmp.trap_hosts | 0 | 2 | 13 |
| snmp.v3_users | 1 | 1 | 13 |
| lags | 0 | 3 | 12 |
| local_users[].name / .role | 7 | 0 | 8 |
| local_users[].hashed_password | 1 | 6 | 8 |
| vxlan_vnis[].vni / .vlan_id | 1 | 0 | 14 |
| vxlan_vnis[].mcast_group | 0 | 1 | 14 |
| routing_instances[].name | 3 | 0 | 12 |
| routing_instances[].description | 0 | 1 | 14 |
| domain | 0 | 3 | 12 |
| syslog_servers | 0 | 3 | 12 |
| dns_servers / ntp_servers / dhcp_servers / radius_servers | 0 | 1 | 14 |

Fields trivially empty on all 15 cells: `timezone`, `vlans[].description`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

The interface sub-field row is a range because the audit's TRIVIAL_EMPTY
cascade fires per sub-field: `name` and `enabled` are populated on 11 cells,
`description` on 8, `ipv4_addresses` on 9, `mtu` on 4, `ipv6_addresses` on 3.
None of them drift on any cell.

## Target-side drops vs symmetric gaps

`aruba_aoscx` declares these **unsupported at the exact path**, and each was
measured as a clean total drop — source populated, target empty:

| path | measured |
|---|---|
| `/system/domain` | 3 cells, e.g. a domain string → `''` |
| `/system/dns-server` | 1 cell, all 3 servers dropped |
| `/system/ntp-server` | 1 cell, all 2 servers dropped |
| `/system/syslog-server` | 3 cells, up to 6 servers dropped at once |
| `/dhcp-servers/pool` | 1 cell, both pools dropped |
| `/radius-servers/server/host` + `/key` | 1 cell, both servers dropped |
| `/snmp/trap-host` | 2 cells, 2 and 5 trap receivers → `[]` |
| `/interfaces/interface/vrrp-groups/group` (whole subtree) | 1 cell, the VRRP group → `[]` |
| `/routing-instances/instance/description` | 1 cell, both VRF descriptions → `''` |
| `/routing/static-route/vrf` | the VRF-bound route is the one that vanishes |

These are recorded `unsupported`, not `lossy`: the record is gone, not
degraded, and per netcanon #436 `lossy` (warn + `compatible=True`) would
understate a vanished record.

`timezone` is different: **both** matrices declare `/system/timezone`
unsupported and no cell populates it. That is a symmetric gap, and it is
`unsupported` on that basis rather than on a measurement.

`vlans[].description` is different again, and in the other direction. The
`cisco_iosxe_cli` parser builds `CanonicalVlan(id=…, name=…)` and nothing else
— the IOS-XE `vlan <id>` stanza has no description keyword — so this is a
**source-side structural gap**, recorded `not_applicable`.

## Four findings worth carrying forward

**1. `vlans[].ipv4_addresses` is a representation change, not a reachability
loss.** It drifts to `[]` on 3 cells, which reads alarming. The round-trip
shows the SVI address is *not* lost: the render emits
`interface Vlan10 / ip address 192.168.10.1/24`, and `interfaces[].ipv4_addresses`
is preserved on every cell. `aruba_aoscx` renders VLAN L3 only from a sibling
interface stanza, so the address survives on the `interfaces[]` record and
merely stops being duplicated onto the `vlans[]` record. Do **not** put
"re-author SVI addressing" on the cutover checklist for this pair.

**2. `interfaces[].lag_member_of` drift is a naming artefact, not lost
membership.** The audit canonicalises LAG names before comparing
(`_LAG_NAME_RE` in `tools/run_phase4_reconciliation.py`), which accepts
`ae<N>` / `Po<N>` / `Port-channel<N>` / `trk<N>` / `agg<N>` / `bond<N>` — but
**not** AOS-CX's space-separated `lag <N>`. Verified directly:
`_canonical_lag_name("Port-channel1")` → `"LAG1"`, `_canonical_lag_name("lag 1")`
→ `None`. Equivalence fails, so a pure rename surfaces as drift on 3 cells.
Membership itself is intact — the member port points at `lag 1` on the target
exactly as it pointed at `Port-channel1` on the source. The real LAG loss on
this pair is the LACP mode, and it is measured on `lags`, not here.

**3. `lags` loses LACP, not members.** All 6 bundles keep their member lists
across the round-trip; all 6 arrive with `mode="static"` because no
`interface lag N` stanza was emitted for the `lacp mode` line to hang on.
`aruba_aoscx` declares `/lags/lag/mode` lossy with exactly this cross-vendor
rationale. A cutover that ships the bare render brings up every port-channel as
a static bundle with no LACP negotiation against the peer — that is an outage
on a live uplink, and it is the single highest-risk item on this pair.

**4. A hostname-less source config silently becomes a switch named `switch`.**
The one `hostname` drift is `'' → 'switch'` on `ntc_carrier_interfaces.txt`,
which carries no `hostname` line at all. `render.py` line 80 is
`hostname = tree.hostname or "switch"`. Nothing is lost — a value is *invented*
— but a device that joins the network as `switch` will confuse inventory and
log correlation. Set the hostname explicitly before rendering.

## A matrix over-declaration, flagged not fixed

`aruba_aoscx` declares `/interfaces/interface/config/type` **lossy** with the
name-shape reason, and `/lags/lag/mode` **lossy** with the cross-vendor reason.
Both are honest: they name the exact failure this pair hits.

The four sibling switchport paths are declared **supported**, with no lossy or
unsupported qualifier:

```
/interfaces/interface/switchport-mode
/interfaces/interface/access-vlan
/interfaces/interface/trunk-allowed-vlans
/interfaces/interface/trunk-native-vlan
```

All four are dropped by the *same* name-shape gate, on the same records, in the
same render — 40 L2 ports and 95 VLAN bindings, measured. The declaration is
correct for a same-vendor round-trip and correct for a cross-vendor render with
port names translated; it is wrong for the bare cross-vendor render, which is
precisely the case `/lags/lag/mode` was declared lossy to cover.

That inconsistency is an over-declaration in `aruba_aoscx`, not a pair-specific
fact. It is recorded here and left for a codec change rather than papered over
in the expectation YAML. Note which way it cuts: because the target genuinely
*does* model the switchport surface, `vlans[].untagged_ports` and
`vlans[].tagged_ports` are recorded `lossy` rather than `unsupported` — calling
them unsupported would tell an operator AOS-CX cannot hold VLAN port
membership, which is false.

## Credential material

Three separate credential surfaces degrade on this pair, and all three need
hand work on the target.

**Local user passwords.** `local_users[].hashed_password` drifts on 6 of the 7
populated cells; 10 of the 11 users in the corpus lose the secret. The render
emits the Cisco value verbatim into an AOS-CX `password ciphertext` slot, which
expects a device-key-encrypted blob rather than a Cisco type-N encoding — and
the AOS-CX re-parse then keeps only the leading type token. The measured shape
is: a Cisco type marker plus a salted digest (36–72 characters) on the source
side, collapsing to a **1-character** value on the target. Every migrated
account therefore arrives **without a working credential**. Set passwords on
the target before cutover.

The corpus contains both synthetic placeholders and at least one real-looking
crypt-style digest. **No hash, salt or ciphertext value is reproduced in this
file or in the expectation YAML** — only lengths and prefix classes. Per
`AGENTS.md`, encrypted secrets are operator-traceable even when encrypted, and
a document that quotes the value it claims to redact defeats its own redaction.

**SNMPv3.** `snmp.v3_users` drifts on 1 of the 2 populated cells, and the drift
is a **cryptographic downgrade**, not a dropped record. Measured on
`kitchen_sink.txt`: the user survives by name, but `auth_protocol` `sha256` →
`sha`, `priv_protocol` `aes256` → `aes` (AES-128), and the VACM `group` binding
is dropped entirely. `aruba_aoscx` declares six `/snmp/v3-user/*` paths lossy
covering exactly this. The passphrases carry across unchanged in length, which
means the migrated user *looks* configured while negotiating weaker crypto than
the source did. Re-create SNMPv3 users on the target with the intended
algorithms.

**RADIUS.** `radius_servers` drops entirely (both servers, 1 cell), and the
shared secret goes with the host — `aruba_aoscx` declares
`/radius-servers/server/key` unsupported in its own right. There is nothing to
verify on the target because nothing arrives; re-author AAA by hand.
