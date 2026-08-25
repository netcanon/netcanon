# Junos → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/juniper_junos__aruba_aoscx.yaml`.

**Source of every number here:** the committed `tools/run_full_mesh.py` corpus
for this pair, re-driven field-by-field with the same `parse → render → parse`
sequence `process_cell` uses. Per-key dispositions were resolved through the
audit's own `actual_disposition()` rather than inferred from the drift shape,
so this file and the ratchet agree by construction.

- Fixture cells: **11** — 10 real Junos `set`-form captures under
  `tests/fixtures/real/junos/` plus the synthetic
  `tests/fixtures/synthetic/juniper_junos/kitchen_sink.set`
- Render errors: **0** · re-parse errors: **0**
- Interface records: **151 in → 151 out**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured round-trip. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`juniper_junos` in this corpus spans QFX leaf/spine (5100 / 5110 / 10k2), an
EX4550 campus aggregation switch, an MX-class L3VPN PE and a vSRX — a **wide,
multi-role model**. `aruba_aoscx` is a **campus access/aggregation switch with
a Phase-1 EVPN/VXLAN surface**. The pair is asymmetric in the direction that
matters: Junos models more than AOS-CX renders, so almost every loss on this
page is a target-side drop, not a source-side gap.

## The structural finding — the inverse of the AOS-CX → EOS pair

On `aruba_aoscx__arista_eos` the dominant loss was structural: the interface
list shrank and dragged every `interfaces[].*` sub-field down with it. **That
does not happen here.** Across all 11 cells the source carries 151 interface
records and the AOS-CX render re-parses to 151 — every record survives, by
name. `only_in_source` and `only_in_target` are both empty on every cell.

The consequence is the useful one: on this pair each `interfaces[].*` sub-field
carries **independent** signal and had to be judged on its own evidence. Two of
them drift and four do not, and the two that drift do so for two unrelated
reasons:

| sub-field | records drifted | cause |
|---|---|---|
| `interface_type` | 151 of 151 | AOS-CX infers ifType from the *name shape* |
| `lag_member_of` | 25 of 151 | `ae<N>` → `lag <N>` rename |
| `ipv4_addresses` | 6 of 151 | per-address anycast MAC blanked |
| `ipv6_addresses` | 6 of 151 | IPv6 anycast gateway address blanked |
| `name` / `description` / `enabled` / `mtu` | 0 of 151 | — |

`interface_type` is the pair's widest single drift and it is entirely
name-driven: the aruba_aoscx matrix declares
`/interfaces/interface/config/type` lossy because AOS-CX carries no IANA
ifType and the codec derives it from the interface name (`1/1/1` →
`ethernetCsmacd`, `vlan N` → `l3ipvlan`, `lag N` → `ieee8023adLag`). No Junos
name matches those shapes, so `ge-`, `xe-`, `et-`, `ae`, `irb` and `lo0` all
land on `ianaift:other`. Nothing forwarding-relevant changes; it is a metadata
collapse, and it is why the raw `interfaces` drift count on this pair looks
alarming.

## Per-field measurement (11 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 10 | 1 | 0 |
| domain | 0 | 2 | 9 |
| dns_servers | 0 | 6 | 5 |
| ntp_servers | 0 | 6 | 5 |
| timezone | 0 | 0 | 11 |
| syslog_servers | 0 | 6 | 5 |
| interfaces[].name | 11 | 0 | 0 |
| interfaces[].description | 9 | 0 | 2 |
| interfaces[].enabled | 11 | 0 | 0 |
| interfaces[].mtu | 5 | 0 | 6 |
| interfaces[].ipv4_addresses | 9 | 1 | 1 |
| interfaces[].ipv6_addresses | 5 | 1 | 5 |
| interfaces[].interface_type | 0 | 11 | 0 |
| interfaces[].lag_member_of | 0 | 5 | 6 |
| interfaces[].vrrp_groups | 0 | 0 | 11 |
| vlans[].id | 7 | 0 | 4 |
| vlans[].name | 7 | 0 | 4 |
| vlans[].ipv4_addresses | 0 | 1 | 10 |
| vlans[].untagged_ports | 0 | 0 | 11 |
| vlans[].tagged_ports | 0 | 6 | 5 |
| vlans[].description | 0 | 0 | 11 |
| static_routes | 5 | 4 | 2 |
| dhcp_servers | 0 | 2 | 9 |
| snmp.community / .location / .contact | 6 | 0 | 5 |
| snmp.trap_hosts | 5 | 1 | 5 |
| snmp.v3_users | 4 | 2 | 5 |
| lags | 0 | 5 | 6 |
| local_users[].name / .role / .hashed_password | 7 | 1 | 3 |
| radius_servers | 0 | 0 | 11 |
| vxlan_vnis[].vni / .vlan_id | 3 | 0 | 8 |
| vxlan_vnis[].mcast_group | 0 | 0 | 11 |
| evpn_type5_routes | 0 | 0 | 11 |
| routing_instances[].name | 6 | 0 | 5 |
| routing_instances[].description | 0 | 2 | 9 |
| raw_sections | 0 | 0 | 11 |
| apply_groups | 0 | 6 | 5 |
| group_content | 0 | 6 | 5 |
| anycast_gateway_mac | 0 | 0 | 11 |

Fields trivially empty on all 11 cells — no observation exists, so the YAML
disposition rests on the two matrices and says so: `timezone`,
`interfaces[].vrrp_groups`, `vlans[].untagged_ports`, `vlans[].description`,
`radius_servers`, `vxlan_vnis[].mcast_group`, `evpn_type5_routes`,
`raw_sections`, `anycast_gateway_mac`.

## Source-side gaps vs target-side drops

Only two fields on this pair are genuine **source-side gaps** — the Junos
parser never populates them, so there is nothing for AOS-CX to lose:

- `anycast_gateway_mac` — `juniper_junos` declares `/anycast-gateway-mac`
  **unsupported**, while `aruba_aoscx` declares it **supported**. The gap runs
  the wrong way for the migration to help: re-author
  `active-gateway ip mac <mac>` on the target and it will stick.
- `raw_sections` — `juniper_junos` declares nothing under raw sections and no
  cell populates it.

Everything else that vanishes is a **target-side drop**, and the AOS-CX matrix
names most of them at the exact path: `/system/domain`, `/system/dns-server`,
`/system/ntp-server`, `/system/syslog-server`, `/dhcp-servers/pool`,
`/snmp/trap-host`, `/routing-instances/instance/description` and the whole
`/interfaces/interface/vrrp-groups/group` subtree are all declared
**unsupported** with a stated reason.

`timezone` and `radius_servers` are the symmetric cases — **both** matrices
declare them unsupported (`/system/timezone`; `/radius-servers/server/host`
and `/radius-servers/server/key`). Those are recorded `unsupported`, not
`not_applicable`, because neither side can hold them.

## Four findings worth carrying forward

**1. L2 port membership is a silent, total loss.** All 120 VLAN records that
carry `tagged_ports` on the source lose them: the AOS-CX render emits
`vlan <id>` / `name <name>` and no `vlan trunk allowed` line anywhere in the
file. The same loss shows up a second time on the interface side —
`switchport_mode: trunk → None` and `trunk_allowed_vlans → []` on 25 records —
so an operator reading only the VLAN table would still miss it. This is the
finding most likely to black-hole traffic on cutover, and it is worth stating
loudly because the aruba_aoscx matrix declares `/vlans/vlan/tagged-ports`
**supported**. The declaration is not wrong same-vendor; it is an
over-declaration relative to what this pair actually renders. Recorded
`unsupported` in the YAML on the measured behaviour, not on the declaration.

**2. The LAG drift is largely an audit-vocabulary artifact, not lost
membership.** `interfaces[].lag_member_of` drifts on 25 records, and every
single one is a pure `ae<N>` → `lag <N>` rename. The bundles themselves survive
with their member lists byte-identical — `ae1[et-0/0/48, et-0/0/49]` re-parses
as `lag 1[et-0/0/48, et-0/0/49]`. The audit *does* canonicalise LAG names
(`_canonical_lag_name` in `tools/run_phase4_reconciliation.py`) but its regex
`^(?:ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond)(\d+)$` is anchored and
does not admit AOS-CX's space-separated `lag 1`, so the rename registers as
drift. What *is* a real loss on `lags` is the LACP mode: all 18 bundles across
5 cells go `active → static`, exactly as the aruba_aoscx `/lags/lag/mode`
declaration predicts. Check LACP mode after cutover; do not bother re-checking
membership.

**3. SNMPv3 survives as a user list and degrades as cryptography.** All four
v3 users across the two populated cells keep their names and re-parse cleanly,
but every one loses its VACM `group` binding, and three of four are
algorithm-downgraded: `sha256 → sha`, `aes256 → aes`, `aes128 → aes`. The
aruba_aoscx matrix declares each of those paths lossy and is explicit that this
is "a cryptographic downgrade, not just a re-key". Separately, `trap_hosts` is
a hard drop — `/snmp/trap-host` is declared unsupported and the render carries
no `snmp-server host` line at all.

**4. A VRF arrives as a bare name.** `routing_instances[].name` round-trips on
all 6 populated cells, which reads reassuring and is not. Everything that makes
the VRF useful is dropped or downgraded by the AOS-CX Phase-1 render:
`description` (declared unsupported), `route_distinguisher`, `rt_imports`,
`rt_exports` and `l3_vni` (all declared unsupported, all measured empty on the
target), and `instance_type` collapses `mac-vrf` / `virtual-router` → `vrf`.
The knock-on shows up in `static_routes`: `/routing/static-route/vrf` is
declared unsupported, and on the kitchen-sink cell the one VRF-scoped route
(`10.99.0.0/16` in `TENANT_A`) is dropped while all three default-VRF routes
render. Read `routing_instances[].name: good` as "the anchor exists", nothing
more.

## Credential material

`local_users[].hashed_password` drifts on 1 of 11 cells, and the cause is not
the hash. Of 13 user records across the corpus, **12 round-trip byte-identical**
— the Junos secret is a crypt-style hash carrying a `junos:` marker prefix
(`$1$` and `$6$` forms appear in this corpus) and the AOS-CX render re-emits it
verbatim behind the `password ciphertext` keyword. The 13th record, the
kitchen-sink `readonly` account, has an **empty** password on the source and
does not render at all: the user vanishes, taking its name, role and (absent)
credential with it. That single vanished record is the whole of the measured
drift on `local_users[].name`, `local_users[].role` and
`local_users[].hashed_password` — one cause, three keys, cited once and
cross-referenced rather than counted three times.

Two cautions that are declaration-grounded rather than measured:

- AOS-CX's native `password ciphertext` payload is an AES blob encrypted with
  the *device* key. The aruba_aoscx matrix states plainly that it is "portable
  same-device only" and that "cross-vendor migration requires re-keying on the
  target". A Junos crypt hash placed behind that keyword is syntactically
  accepted by the render and should not be expected to authenticate on real
  hardware. Plan to set passwords on the target.
- `privilege_level` collapses to 1 on 9 of 13 records (AOS-CX maps
  `administrators → 15` and everything else → 1). `role` itself is preserved on
  every surviving record, so authorisation intent survives in the named group
  even where the numeric privilege does not.

No secret value — hash, ciphertext blob or passphrase — is reproduced in this
file or in the expectation YAML. Per `AGENTS.md`, encrypted and hashed secrets
are operator-traceable even when unreadable, and a document that quotes the
value it claims to redact defeats its own redaction. Shapes only.

## Two matrix declarations this pair disagrees with

Recorded here rather than fixed, because a matrix edit is a codec change and
this wave is expectation-authoring only.

- **Over-declaration.** `aruba_aoscx` declares `/vlans/vlan/tagged-ports` and
  `/vlans/vlan/untagged-ports` supported. Trunk membership is nevertheless
  dropped in full on every populated record of this pair (finding 1).
- **Under-declaration.** Neither codec declares anything at all for
  `/apply-groups` or `/group-content`, yet the Junos two-pass parser populates
  both (`apply_groups: ['GLOBAL-SETTINGS']` on the kitchen sink) and the AOS-CX
  render emits neither. The flattened content mostly still reaches the target
  — verified on the kitchen sink, where the description and `mtu 9000` that
  `GLOBAL-SETTINGS` contributes to `ge-0/0/0` render as literal AOS-CX
  interface lines — but the group *structure* is gone, undeclared, on 6 cells,
  and any group content whose destination field is itself dropped (that same
  group's `system syslog host`) goes with it.
