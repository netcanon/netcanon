# AOS-CX → MikroTik RouterOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__mikrotik_routeros.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus
direct parse → render → re-parse probes run against all 7 cells for every call
where the drift shape and the capability matrices disagreed. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`aruba_aoscx` in this corpus is a **campus / small-DC access-aggregation
switch** with a hardware L2 forwarding plane. `mikrotik_routeros` is a
**router-first OS** whose L2 lives in a software bridge with VLAN filtering.
The shared surface is the routed edge — uplink addressing, SVIs, bonds, static
routes, SNMP, local accounts — and explicitly *not* the VLAN-centric switching
model AOS-CX is built around.

## The structural finding, and why it is the mirror image of the EOS pair

On `aruba_aoscx → arista_eos` the interface inventory **shrank** (9 → 5) and
every `interfaces[].*` key drifted because records were dropped.

Here it **grows**. Measured over all 7 cells:

- **0** of the **157** source interface records is dropped. Every AOS-CX port,
  LAG, loopback, SVI and `mgmt` survives by name.
- **37** records are **added** — one `bridge1` per config, plus one synthetic
  `vlan<id>` L3 interface per VLAN.

| cell | source ifaces | target ifaces | added |
|---|---|---|---|
| `aoscx_dcn_arch3_ebgp_leaf1a` | 9 | 12 | 3 |
| `aoscx_dcn_arch3_ibgp_leaf1a` | 9 | 12 | 3 |
| `aoscx_dcn_arch4_core1_1` | 18 | 23 | 5 |
| `aoscx_dcn_arch4_core1_2` | 42 | 47 | 5 |
| `canu_csm17_spine001_ipv6_vrf` | 22 | 31 | 9 |
| `netutils_aoscx_snmpv3_glcx1009` | 44 | 51 | 7 |
| `kitchen_sink` (synthetic) | 13 | 18 | 5 |

The consequence is still that **every `interfaces[].*` key measures as drifted
on all 7 cells** — declaring any of them `good` would manufacture a false
`CODEC_BUG` — but the *cause* is insertion, not deletion, and that changes the
operator advice completely. Nothing needs to be inventoried for rescue; the
rendered config needs to be de-duplicated.

### The double-mounted SVI

Each AOS-CX SVI ends up in the render twice under two different names:

- the carried-over `vlan 101` (with a space), which is what the `/ip address`
  line binds to, and
- the synthetic `vlan101`, created under `/interface vlan` and attached to
  `bridge1`, which carries no address.

The render never emits an `add name="vlan 101"`. Across the corpus, **20 of
the 43 `interface=` references inside address blocks point at an interface the
same file never creates** — all 20 are `vlan N` SVI names. A rendered config
will not apply clean without reconciling the SVI naming by hand.

## Correlated vs independent drift

This is the trap that had to be handled key by key. Because the record list
drifts on every cell, *every* `interfaces[].*` key inherits a loss. Four of
them **also** lose real per-attribute data; four do not. Measured separately:

| key | independent loss? | measurement |
|---|---|---|
| `interfaces[].interface_type` | **yes** | 157 populated → 113 blanked, 10 wrong, 34 intact |
| `interfaces[].enabled` | **yes** | 16 of 157 flip, **all** `false → true`, all on SVIs |
| `interfaces[].description` | **yes** | 66 populated → 10 lost, all on SVIs |
| `interfaces[].ipv4_addresses` | **yes** | 41 addresses intact; 15 lose the virtual-gateway companion |
| `interfaces[].mtu` | no | 50 populated, **0** drift |
| `interfaces[].lag_member_of` | no | 44 populated, **0** drift |
| `interfaces[].ipv6_addresses` | no | only 2 records exist, **0** drift |
| `interfaces[].name` | n/a | the record-count drift itself |

`interfaces[].vrrp_groups` is `unsupported` on its own merits: `aruba_aoscx`
declares the whole subtree unsupported, and parsing all 7 fixtures yields
**zero** VRRP groups. The block is on the source side — RouterOS does model
VRRP and declares only `.../group/mode` and `.../group/description` lossy.

Two of the "independent" findings deserve to be read as operational, not
bookkeeping:

- **The `enabled` flips are one-directional.** All 16 turn an SVI that was
  `disabled` on AOS-CX into an enabled interface on RouterOS. An SVI
  deliberately shut on the source comes up live on the target.
- **The `interface_type` errors are not all blanks.** All 10 *wrong* values are
  `loopback N`, which the render emits as `/interface bridge`, so the
  name-prefix inference returns `ianaift:bridge` instead of
  `ianaift:softwareLoopback`.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces (all sub-fields) | 0 | 7 | 0 |
| vlans[].id | 7 | 0 | 0 |
| vlans[].name | 0 | 7 | 0 |
| vlans[].description | 0 | 7 | 0 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].untagged_ports | 0 | 7 | 0 |
| vlans[].tagged_ports | 0 | 5 | 2 |
| static_routes | 2 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 3 | 1 | 3 |
| lags | 7 | 0 | 0 |
| local_users[].name | 6 | 0 | 1 |
| local_users[].role / hashed_password | 0 | 6 | 1 |
| routing_instances[].name / description | 0 | 3 | 4 |
| vxlan_vnis[].vni / vlan_id / mcast_group | 0 | 3 | 4 |
| anycast_gateway_mac | 0 | 5 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`.

## The VLAN model: what a total drop looks like

RouterOS binds a VLAN interface to a single parent, so the VLAN-centric
membership lists have no target-side mount. The matrix declares both paths
unsupported *and* declares the per-port twins (`access-vlan`,
`trunk-allowed-vlans`, `trunk-native-vlan`, `switchport-mode`) unsupported, so
there is no second route for the data either. The measurement agrees exactly:

- **13 of 13** populated `untagged_ports` lists come back empty (one of them a
  29-entry list on the arch4 core cell).
- **11 of 11** populated `tagged_ports` lists come back empty.

Both are recorded `unsupported`, not `lossy`. Per netcanon #436 a vanished
record is not lossy: `lossy` warns and stays `compatible=True`, which would
badly understate losing every access and trunk assignment on the switch.

`vlans[].ipv4_addresses` looks identical in the drift matrix — 18 of 18
populated records come back empty — and is **not** the same thing. Following
the address rather than the drift count shows all 18 are re-homed intact onto
the sibling `vlan N` interface record. The prefix does not leave the config; it
changes mount point, exactly as the target's own `/vlans/vlan/ipv4/address/ip`
lossy declaration describes. What is genuinely lost is the anycast companion:
15 of the 18 carry a `virtual_gateway_address` and none survives. That is why
one is `unsupported` and the other `lossy` — the distinction came out of the
round-trip, not the grammar.

### Name and description are conflated, not merely dropped

RouterOS exposes a single per-VLAN `comment`. The render writes the source
**name** into it and the re-parse reads it back as the **description**:

- all **30** VLAN records are renamed to the synthetic `vlan<id>` form;
- **23 of 30** come back with a description equal to the source's *name*;
- on **6** of those, that clobbers a real source description (one cell turns
  name `VLAN 11` / description `Server VLAN` into description `VLAN 11`).

A migrated config therefore *looks* annotated while carrying the wrong
annotation. That is worse than an empty field, because an empty field is
obvious at review time.

## Three findings worth carrying forward

**1. `lags` is a clean win here — and it was verified, not assumed.** Preserved
on 7 of 7 cells with every bond's name, member list and mode identical, 16
bonds on the densest cell. The check matters because a bare `lags` result is
this pair's known artifact: the audit canonicalises LAG names before comparing,
and renderers key off `CanonicalInterface.lag_member_of` rather than
`CanonicalLAG.members`. Both were probed; all 44 `lag_member_of` values also
round-trip identical. Untested by this corpus: both matrices declare
`/lags/lag/mode` lossy, the target because RouterOS `mode=802.3ad` has no
passive variant — every bond in the corpus is already active.

**2. Anycast first-hop redundancy is lost end to end.** `anycast_gateway_mac`
drops on all 5 populated cells (target declares `/anycast-gateway-mac`
unsupported, "parses-and-ignores in v1") *and* all 15 per-SVI
`virtual_gateway_address` companions drop. This is the inverse of the
`aruba_aoscx → arista_eos` pair, where the fabric MAC survived and only the
addresses did not — there the `good` on the MAC needed a warning attached;
here there is nothing to soften. Rebuild first-hop redundancy on the target
from the source config.

**3. VRFs and VXLAN are architecture decisions, not checklist items.**
`routing_instances` drops totally on all 3 cells that populate it (6 instances
in, 0 out; the target declares `/routing-instances/instance` unsupported and
the interface-level `vrf` attribute empties with it), and `vxlan_vnis` drops
totally on all 3 cells that populate it (4 VNIs in, 0 out). Neither has a
target-side equivalent in this migration. If the source separates management
or keepalive traffic into a VRF, decide how that is replaced before cutover.

## Credential material

`local_users[].hashed_password` drifts on all 7 account records, and the
round-trip shows more than the drift count does.

AOS-CX stores the user secret in its own encrypted form — an `AQB…`-prefixed
ciphertext blob of roughly 180 characters, neither a crypt(3) hash nor
anything RouterOS can consume. The renderer does **not** drop it: on 7 of 7
cells it echoes the blob verbatim into a RouterOS `password=` field — a
plaintext credential slot — and the re-parse then recovers no password at all.

Two consequences:

1. Every migrated account arrives **without a working credential**. Set
   passwords on the target before cutover or the accounts are unusable.
2. The rendered artifact carries operator-traceable key material in a
   plaintext field. Treat a rendered RouterOS config produced from an AOS-CX
   source as a secret and store it accordingly.

`local_users[].role` drifts on all 7 records too, but benignly: the AOS-CX role
is routed through RouterOS group names on render (`administrators` →
`group=full`, `operators` → `group=read`) and read back under RouterOS's own
vocabulary as `admin` / `operator`. The privilege tier survives; the literal
string does not. Re-check which group each account lands in — neither matrix
declares anything for local users, so this measurement is the only warning.

The ciphertext values are deliberately not reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction.

## Matrix under-declarations noted, not fixed

Two places where the codecs promise less than the measurement shows. Both are
codec changes, not pair-specific facts, and are left alone here:

- `mikrotik_routeros` declares **nothing at all** for `/local-users/user` —
  neither supported, lossy nor unsupported — while dropping the password and
  re-stringing the role on every cell.
- `aruba_aoscx` declares `/snmp/trap-host` unsupported as a source. The
  `snmp.trap_hosts` key resolves `good` because no populated SNMP block drifts
  on it — but no committed cell carries a trap host either, so that `good`
  records an absence of drift rather than an observed migration. The YAML says
  so in its note rather than letting the disposition imply coverage.
