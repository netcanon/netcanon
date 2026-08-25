# AOS-CX → Cisco NX-OS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__cisco_nxos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every claim about *why* a field drifted was re-derived by
round-tripping the fixture directly (`cisco_nxos.parse(cisco_nxos.render(
aruba_aoscx.parse(raw)))`), not read off a single drift sample.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and direct round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

Unlike the sibling `aruba_aoscx → arista_eos` pair, the device classes here
line up. Both codecs describe DC-capable switches: the AOS-CX corpus is
spine/leaf and VSX-core material (`aoscx_dcn_arch3/4`, a CANU CSM spine), and
`cisco_nxos` is a DC leaf/spine. The shared surface is correspondingly wide —
VLANs, SVI addressing, port-channels, VRFs, VXLAN VNIs and the fabric anycast
gateway are all modelled on both sides.

## The structural finding

**The interface inventory does not shrink.** 157 source interface records
produce 157 re-parsed records across the 7 cells; not one cell loses a port.
That is the opposite of the AOS-CX → EOS pair, where the inventory collapsed
9 → 5 and dragged every `interfaces[].*` sub-field into a loss. Here
`description`, `enabled`, `mtu` and `ipv6_addresses` are all measured
**preserved**, and declaring them `good` is safe.

What is lost instead is **identity**. AOS-CX writes two-token interface names
(`lag 1`, `vlan 101`, `loopback 0`). The NX-OS render emits the canonical name
verbatim, and the NX-OS parser keeps only the leading keyword, so those records
come back as bare `lag` / `vlan` / `loopback`:

- **62** records renamed across the corpus — every one a two-token name.
- **56** of the 157 records end up sharing a name with at least one other
  record (on one cell, five distinct port-channels all become `lag`).
- Physical ports (`1/1/1`) and `mgmt` are untouched.

That single mechanism is the proximate cause of five separate keys drifting:
`interfaces[].name`, `interfaces[].interface_type` (NX-OS infers type from the
name prefix, so 122 records degrade to `ianaift:other`),
`interfaces[].lag_member_of`, `lags`, and the VLAN membership lists (a
`["lag 1","lag 2","lag 101","lag 102","lag 256"]` untagged list de-duplicates
to `["lag"]`).

**These are correlated, not independent.** One cause, five measurements. None
of them corroborates any of the others, and this file does not use one as
evidence for another.

## Bare path vs the planner's rename path

`tools/run_full_mesh.py` measures the bare
`target.parse(target.render(source.parse(raw)))` path, which never calls
`netcanon.migration.canonical.port_names.translate_port_names`. That helper
rewrites exactly the references that drift here — `interfaces[].name`,
`interfaces[].lag_member_of`, `vlans[].tagged_ports`,
`vlans[].untagged_ports`, `lags[].name`, `lags[].members`.

Re-running all 7 cells through it (source `aruba_aoscx`, target `cisco_nxos`,
empty rename map, **0 dropped records**) separates the naming artifacts from
the real losses:

| measurement (7 cells) | bare path | `translate_port_names` path |
|---|---|---|
| interface records in → out | 157 → 157 | 157 → 157 |
| records renamed | 62 | 0 |
| records sharing a name | 56 | 0 |
| records whose `interface_type` changed | 122 | 0 |
| LAG records in → out | 34 → 33 | 34 → 34 |
| member → bundle map identical | no (44 renames) | yes, on 7 of 7 |
| VLAN untagged members | collapse (29 → 25 on the largest cell) | 64 → 64 |
| VLAN tagged members | collapse | 32 → 32 |
| IPv4 addresses on the VLAN record | 18 → 0 | 18 → 18 |
| **active-gateway virtual addresses** | **15 → 0** | **15 → 0** |
| **VLAN descriptions** | **6 → 0** | **6 → 0** |

The two bold rows are the losses that survive translation. They are the ones
to plan a cutover around; the rest are a naming-discipline problem with a
tool-supported fix.

The dispositions in the YAML follow the **bare** column, because that is what
the ratchet measures. Each reason says which column it is describing.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces[].description / enabled / mtu | 7 | 0 | 0 |
| interfaces[].ipv6_addresses | 2 | 0 | 5 |
| interfaces[].name / interface_type / lag_member_of | 0 | 7 | 0 |
| interfaces[].ipv4_addresses | 2 | 5 | 0 |
| vlans[].id / name | 7 | 0 | 0 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].untagged_ports | 0 | 7 | 0 |
| vlans[].tagged_ports | 1 | 4 | 2 |
| vlans[].description | 0 | 4 | 3 |
| static_routes | 2 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 3 | 1 | 3 |
| lags | 0 | 7 | 0 |
| local_users[].name / role / hashed_password | 6 | 0 | 1 |
| vxlan_vnis[].vni / vlan_id | 3 | 0 | 4 |
| routing_instances[].name | 3 | 0 | 4 |
| anycast_gateway_mac | 5 | 0 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`interfaces[].vrrp_groups`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `vxlan_vnis[].mcast_group`,
`routing_instances[].description`.

### Sub-field drift, aggregated over all cells

Counted per drifting record, not per cell — reading a single sample is how the
interface story gets told wrong.

| parent | sub-field | drifting records |
|---|---|---|
| interfaces | interface_type | 122 |
| interfaces | name | 62 |
| interfaces | lag_member_of | 44 |
| interfaces | ipv4_addresses | 15 |
| vlans | ipv4_addresses | 18 |
| vlans | untagged_ports | 8 |
| vlans | tagged_ports | 8 |
| vlans | description | 6 |
| lags | name | 32 |
| lags | whole record | 1 |
| local_users | privilege_level | 6 |
| snmp | v3_users | 1 cell |

Every other sub-field of those parents is preserved on every cell.
`local_users[].privilege_level` is not one of the audited keys; it is listed
because it explains why `local_users[].role` is `good` (see below).

## Source-side gaps vs target-side drops

AOS-CX declares these **unsupported at the exact path**, so as a *source* it
never emits them and no committed cell populates them:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/system/timezone` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` · `/radius-servers/server/key`

The split that matters operationally is what **cisco_nxos** declares for the
same path:

- `domain`, `dns_servers`, `ntp_servers`, `syslog_servers` — NX-OS declares
  them **supported**. Recorded `not_applicable`: re-authoring `ip domain-name`,
  `ip name-server`, `ntp server` and `logging server` on the target will stick,
  and the migration report should say so rather than implying the target
  cannot hold them.
- `timezone`, `dhcp_servers`, `radius_servers` — NX-OS declares them
  **unsupported too**, with explicit reasons (no clock stanza, no DHCP pool, no
  AAA radius-server config). These are symmetric gaps, recorded `unsupported`.
  Re-authoring on the source side would not help; they have to be configured on
  the target device outside this migration.

`interfaces[].vrrp_groups` is a third shape: AOS-CX declares the whole
`/interfaces/interface/vrrp-groups/group/*` subtree unsupported (it expresses
first-hop redundancy as VSX active-gateway), and 0 groups appear across the
corpus, so it is `not_applicable`. For a source that *does* carry VRRP, note
that NX-OS declares the group **lossy**, not unsupported: it renders every
canonical VRRP group as an `hsrp` block regardless of source mode, dropping the
advertisement interval, the group description and IPv6 virtual addresses. The
redundancy protocol silently changes.

## Three findings worth carrying forward

**1. `lags` mixes a rename with one genuine record loss.** On 6 of 7 cells the
LAG count is unchanged (32 in, 32 out) and the only change is
`lag 1` → `port-channel1`, with members and LACP mode intact. On the 7th, the
kitchen-sink fixture defines `lag 2` with **no member ports**, and the NX-OS
render keys channel membership off `CanonicalInterface.lag_member_of` — a
bundle nothing points at emits no `channel-group` line and does not come back.
That one record is the entire corpus-wide 34 → 33 drop. Recorded `lossy`, not
`unsupported`: 33 of 34 survive with full membership. Audit any LAG that has no
members yet before cutover.

The audit's LAG canonicalisation does not rescue this pair. `_canonical_lag_name`
accepts `ae<N>` / `Po<N>` / `Port-channel<N>` / `Port-Channel<N>` / `trk<N>` /
`agg<N>` / `bond<N>`; AOS-CX's spaced `lag <N>` and NX-OS's lowercase
`port-channel<N>` match none of them, so the rename falls through to raw
equality on `interfaces[].lag_member_of` as well.

**2. `vlans[].ipv4_addresses` measures as an empty list but the subnet is not
lost.** The drift sample shows `[{10.12.101.2/24, …}] → []`, which reads like a
total drop. The round-trip says otherwise: the render carries
`interface vlan 101 / no switchport / ip address 10.12.101.2/24`, and the
address re-parses onto the sibling `interfaces[]` record. cisco_nxos declares
`/vlans/vlan/ipv4/address/ip` lossy for exactly that reason — it renders an SVI
only from a sibling interface stanza, never from the VLAN record. `lossy` is
therefore right and `unsupported` would be wrong: this must warn, not block.

**3. `anycast_gateway_mac` is `good`; anycast gateway is not.** The
fabric-wide MAC round-trips on all 5 populated cells via
`fabric forwarding anycast-gateway-mac`. Meanwhile **all 15** per-SVI
active-gateway virtual addresses in the corpus are dropped — on both the bare
and the translated path — and no per-SVI `fabric forwarding mode
anycast-gateway` line is emitted. Both matrices declare the virtual-gateway
path lossy, and the NX-OS reason gives the mechanism: NX-OS Distributed Anycast
Gateway requires the virtual address to *be* the interface's primary IP, while
the AOS-CX active-gateway is a separate VARP-style address (`10.12.101.1`
alongside the SVI's `10.12.101.2`). The MAC arrives; the gateway addressing it
exists to serve does not. This is the field most likely to break default-gateway
reachability at cutover.

## Credential material

`local_users[].hashed_password` is measured **preserved** on all 6 populated
cells — and that `good` needs its caveat stated, not buried.

AOS-CX stores the user secret in its own encrypted form: an `AQB`-prefixed
ciphertext blob, carrying no leading type digit. `_render_local_user` in the
`cisco_nxos` codec renders any value without a type digit behind NX-OS's
type-0 marker; the codec's own docstring calls type 0 "the plaintext type-0
form". The migrated line therefore presents an AOS-CX ciphertext blob as
though it were a cleartext password.

The round-trip proves the *string* survives. Whether the target device can
authenticate with it is outside what the round-trip measures, and the shape of
the artefact says it cannot. **Set passwords on the target before cutover.**

`local_users[].role` is preserved for a related reason: the NX-OS render emits
the source role string verbatim when one is set, so an AOS-CX `administrators`
role lands as `role administrators` — not an NX-OS built-in role name. The
knock-on is visible in the corpus: `privilege_level` degrades 15 → 1 on every
populated cell, because the re-parse cannot map the foreign role back to an
admin privilege. Map roles to `network-admin` / `network-operator` before
cutover.

SNMPv3 is the quieter case. Only 1 of the 4 SNMP-populated cells drifts, and
the measured change is a re-spelling — privacy protocol `aes` normalises to
`aes128` — with names, groups, auth protocol and key blobs intact; the
real-world SNMPv3 fixture round-trips with no drift at all. The *declared*
risk is wider: AOS-CX marks six `/snmp/v3-user/*` child paths lossy, and NX-OS
marks auth-passphrase, priv-passphrase and engine-id lossy because it
normalises keys to the older `localizedkey` digest form. Plan to re-key SNMPv3
users on the target rather than trusting a migrated key.

No ciphertext, hash or key value is reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction.
