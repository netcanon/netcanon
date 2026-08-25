# AOS-CX → AOS-S: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__aruba_aoss.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every claim below that goes beyond the mesh counters was produced
by re-running the round trip directly —
`aruba_aoss.parse(aruba_aoss.render(aruba_aoscx.parse(raw)))` — over all seven
cells and diffing record by record.

- Fixture cells: **7** (six under `tests/fixtures/real/aruba_aoscx/`, plus
  `tests/fixtures/synthetic/aruba_aoscx/kitchen_sink.cfg`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

This is the one **same-vendor, cross-generation** pair in the AOS-CX mesh, and
it runs in the harder direction. `aruba_aoscx` is the modern campus/DC switch —
`1/1/x` port naming, `lag N` bundles, VSX active-gateway, VRFs, VXLAN.
`aruba_aoss` is the legacy ProVision-lineage campus L2/L3 switch — `trkN`
trunks, a two-level `manager` / `operator` privilege model, no VRF and no VXLAN.

The realistic migration is therefore a **downgrade**: an AOS-CX config being
expressed on AOS-S hardware, e.g. re-homing a closet onto surviving legacy
switches during a staged refresh. That framing predicts where the losses land,
and the measurement confirms it: the campus L2 edge survives almost completely,
while everything AOS-CX gained over AOS-S — VRFs, VXLAN, the anycast gateway —
is dropped whole.

## The structural finding

The interface inventory shrinks on **all 7 cells**, so every `interfaces[].*`
sub-field measures as drifted and none of them may be declared `good` without
manufacturing a false `CODEC_BUG`.

But on this pair the shrinkage is not the diffuse "AOS-CX enumerates more ports"
effect seen against `arista_eos`. **No physical port is ever dropped.** The 49
records that disappear across the corpus are exactly three kinds:

| dropped record kind | count across 7 cells |
|---|---|
| `lag N` bundle pseudo-interface | 34 |
| `loopback N` | 10 |
| `mgmt` | 5 (survives on 2 of 7 cells) |

Plus 18 SVI records that are **renamed**, not dropped: `vlan 101` → `Vlan101`.
The comparator keys interface records on the name, so a rename presents as one
record leaving and another arriving.

Operationally, only two of those four movements are a real loss. The `lag N`
pseudo-interfaces are re-expressed as `trunk … trkN lacp` lines (see below), and
the SVI is re-mounted from the VLAN record. The **loopbacks vanish outright** —
on a routed spine or leaf that is the BGP router-id and update-source, so it has
to be re-authored by hand — and `mgmt` vanishes on most cells.

## The dangling `lag N` reference

Worth stating loudly because it is invisible in the drift counters. Rendering
`aoscx_dcn_arch4_core1_1.cfg` to AOS-S produces, in the same file:

```
trunk 1/1/1,1/1/2 trk1 lacp
vlan 1
   untagged lag 1,lag 2,lag 101,lag 102,lag 256
   exit
interface lag 1
   name "RACK-1"
   enable
   exit
```

The bundle is named `trk1` on the `trunk` line and `lag 1` everywhere else. The
`aruba_aoss` parser reads back only the `trk1` form, which is why the 34
`interface lag N` stanzas do not survive the re-parse — and why the VLAN
membership lists round-trip *verbatim* while naming a bundle that does not exist
in the target's own LAG list. **63 such dangling member tokens** across the 7
cells (1, 1, 7, 7, 15, 30, 2).

This matters for the `vlans[].untagged_ports` / `vlans[].tagged_ports`
dispositions: both are measured `good` — the token lists are preserved exactly —
but "preserved" here means the *strings* survived, not that the reference
resolves. Treat LAG-attached VLAN membership as re-authoring work regardless of
the `good`.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces (all sub-fields) | 0 | 7 | 0 |
| vlans[].id | 7 | 0 | 0 |
| vlans[].name | 7 | 0 | 0 |
| vlans[].untagged_ports | 7 | 0 | 0 |
| vlans[].tagged_ports | 5 | 0 | 2 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].description | 0 | 4 | 3 |
| static_routes | 2 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 3 | 1 | 3 |
| lags | 0 | 7 | 0 |
| local_users[].name | 6 | 0 | 1 |
| local_users[].role | 0 | 6 | 1 |
| local_users[].hashed_password | 0 | 6 | 1 |
| vxlan_vnis[].vni / vlan_id / mcast_group | 0 | 3 | 4 |
| routing_instances[].name / description | 0 | 3 | 4 |
| anycast_gateway_mac | 0 | 5 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`.

## Which interface sub-fields lose independently

The trap on any pair with a record-count drift is to read the eight
`interfaces[].*` drift flags as eight findings when they are one. They are not
independent evidence for each other. To separate the correlated flags from the
real ones, the 108 records that survive the round trip (108 = 5+5+11+35+17+27+8)
were diffed sub-field by sub-field:

| sub-field | agree | disagree | what actually changed |
|---|---|---|---|
| `interface_type` | 108 | 0 | nothing — drift is purely the record-count effect |
| `ipv4_addresses` | 31/31 addresses kept | 0 | nothing — purely the record-count effect |
| `description` | 96 | 12 | SVI records only: the AOS-S SVI is re-mounted from the VLAN record, so the SVI description is replaced by the VLAN name (`PROD-WEB-SVI` → `PROD-WEB`) |
| `enabled` | 92 | 16 | SVI records only, and **all 16 in the same direction: `False` → `True`** |
| `mtu` | 58 | 50 | physical ports only, and **all 50 the same transition: `9198` → unset** |
| `lag_member_of` | 64 | 44 | `lag N` → `trkN`; the membership itself is intact |
| `ipv6_addresses` | 0/2 addresses kept | 2 | every IPv6 address in the corpus is dropped (2 source-side, 0 target-side) |

So on this pair `interface_type` and `ipv4_addresses` are declared lossy purely
because their parent record list lost coherence, while `mtu`, `enabled`,
`description` and `ipv6_addresses` fail on records that *do* survive. The YAML
says which is which per key rather than implying all eight share one cause.

## Three findings worth carrying forward

**1. A shut SVI comes back up.** 16 of the 18 SVI records that survive the round
trip flip `enabled` from `False` to `True`, and none flips the other way. An SVI
deliberately left `shutdown` on AOS-CX is administratively **up** after
migration. This is a fail-open, and it is the single change on this pair most
likely to put unintended traffic on a wire at cutover. Diff admin state on every
SVI before committing the target config.

**2. Jumbo MTU is dropped, and the matrix does not admit it.** All 50 physical
ports carrying `9198` arrive with no MTU. The `aruba_aoss` `CapabilityMatrix`
declares **nothing at all** for `/interfaces/interface/config/mtu` — not
supported, not lossy, not unsupported — while dropping it on every record. That
is a matrix under-declaration, not a pair-specific fact; it is recorded here and
left for a codec change rather than patched from this file.

**3. `lags` drift is mostly a naming shape the audit does not canonicalise.** On
6 of 7 cells the *only* difference is `lag N` → `trkN`; members and LACP mode are
identical. `tools/run_phase4_reconciliation.py::_canonical_lag_name` collapses
`ae<N>` / `Po<N>` / `Port-channel<N>` / `trk<N>` / `agg<N>` / `bond<N>` to a
common token, but its regex is anchored and AOS-CX's native `lag <N>` spelling —
with the space — does not match, so the rename falls through to raw equality and
fires drift. The 7th cell is a genuine loss: `kitchen_sink.cfg` carries a
memberless `lag 2` (`mode static`) and the count drops 2 → 1, because the AOS-S
render keys off `CanonicalInterface.lag_member_of` and a bundle with no member
port has nothing to render from.

## Credential material

`local_users[].hashed_password` drifts on all 6 populated cells, and the failure
mode is worse than a drop.

AOS-CX stores the user secret in its own encrypted form — an `AQB`-prefixed
ciphertext blob, 184 characters on each of the four real-capture fixtures that
carry one; the sanitised and synthetic cells carry short placeholder strings
instead, and are re-typed exactly the same way. The AOS-S render emits the value
as `password manager user-name "<user>" plaintext "<secret>"`, and the re-parse
returns it tagged `plaintext:`. Nothing is lost; the secret is **re-typed as a
literal cleartext password**. Two consequences for a cutover:

- No migrated account authenticates with its original password, because the
  target now treats the ciphertext as the password string itself.
- The rendered config contains the source's encrypted secret material on a line
  marked `plaintext`, so it inherits none of the handling the source form
  implied. Treat any rendered AOS-S config from an AOS-CX source as
  secret-bearing.

Set passwords on the target by hand before cutover.

The ciphertext values are deliberately not reproduced in this file or in the
expectation YAML — only the `AQB` prefix marker and the length class. Per
`AGENTS.md`, encrypted secrets are operator-traceable even when encrypted, and a
document that quotes the value it describes defeats its own redaction.

`local_users[].role` also drifts on all 6 populated cells, but as a re-mapping
rather than a loss: `administrators` → `manager` and `operators` → `operator`,
consistently. The account keeps a privilege level; the canonical string changes
to the AOS-S two-level vocabulary. Re-check the mapping if any source role was
something other than those two.

## Source-side gaps, symmetric gaps and target-side drops

Three different things produce an empty field, and the YAML distinguishes them
because the operator action differs.

**Source-side gap** — `aruba_aoscx` declares the path unsupported, so as a
*source* it never emits it and there is nothing for AOS-S to lose. Recorded
`not_applicable`:

`/system/dns-server` · `/system/ntp-server` · `/radius-servers/server/host` ·
`/radius-servers/server/key`

For `dns_servers` and `ntp_servers` this is worth acting on: **`aruba_aoss`
declares both SUPPORTED**, so re-authoring name-servers and NTP peers on the
target will stick.

**Symmetric gap** — both matrices declare the path unsupported. Recorded
`unsupported`, because neither side can carry it and no re-authoring in the
migration will help:

`/system/domain` · `/system/timezone` · `/system/syslog-server` ·
`/dhcp-servers/pool`

**Target-side drop** — the source populates the field and `aruba_aoss` declares
it unsupported, so it vanishes on render. Recorded `unsupported`, and each is a
measured total drop, not a degradation:

- `/anycast-gateway-mac` — `02:00:0a:01:65:01`-shaped value → empty on all 5
  populated cells.
- `/routing-instances/instance` — all VRFs dropped on all 3 populated cells
  (2 instances each).
- `/vxlan-vnis/vni` — all VNIs dropped on all 3 populated cells.

## The anycast gateway fails on both mounts

Unlike the `arista_eos` pair — where the fabric-wide MAC survives while the
per-SVI gateway address does not — on AOS-S **both halves are lost**:

- `anycast_gateway_mac` drops to empty on all 5 cells that set it.
- `vlans[].ipv4_addresses` drifts on all 5 cells that populate it, and the
  measured difference is always the same: the SVI's own address and prefix
  survive intact, the `virtual_gateway_address` companion is emptied (15 address
  records across the corpus, e.g. `10.12.101.2/24` keeps its address and loses
  gateway `10.12.101.1`).

`aruba_aoss` declares `/vlans/vlan/ipv4/address/virtual-gateway-address` and
`/vlans/vlan/ipv4/address/virtual-gateway-mac` unsupported with the reason "AOS-S
is a campus L2/L3 codec with no anycast-gateway / VARP grammar", which matches
the measurement exactly. First-hop redundancy must be rebuilt on the target —
`aruba_aoss` declares `/interfaces/interface/vrrp-groups/group` supported, so
VRRP is the available replacement.

## Matrix under-declarations found while authoring

Recorded, not fixed — these are codec-level facts, out of scope for an
expectation file:

- **`/interfaces/interface/config/mtu`** — `aruba_aoss` declares nothing while
  dropping MTU on 50 of 108 surviving records.
- **`/local-users/*`** — `aruba_aoss` declares nothing at all (no supported, no
  lossy, no unsupported paths) while rendering `password manager …` lines,
  re-mapping the role and re-typing the secret as plaintext. The two most
  operator-visible identity losses on this pair are entirely undeclared by the
  target matrix.
- **`/lags/lag`** — `aruba_aoss` declares only `/lags/lag/mode` lossy and nothing
  supported, while rendering `trunk … lacp` lines and silently dropping
  memberless bundles.
