# AOS-S → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoss__aruba_aoscx.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Two contested calls were additionally settled by an explicit
parse-render-reparse round-trip; both are written up below.

- Fixture cells: **7** (6 real AOS-S captures + the synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and direct reads of
> `netcanon/migration/codecs/aruba_aoscx/`. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

This is the only **same-vendor, same-device-class** pair in the `aruba_aoscx`
expectation mesh. `aruba_aoss` is HPE/Aruba ProVision — the 2530 / 2920 /
2930F / 2930M / 5406R campus access and aggregation line; `aruba_aoscx` is its
successor platform in the same role. The realistic migration is an in-vendor
refresh: the AOS-S switch in the closet is replaced by an AOS-CX switch
carrying the same VLANs, the same SVI addressing and the same uplink bundle.

That closeness shows in the score. **15 of 43 keys are `good`** — the widest
surviving surface of any pair targeting `aruba_aoscx`, and it includes the one
field that dies on every other pair in the mesh: `local_users[].hashed_password`.

## The structural finding

The interface inventory **does not shrink**. 85 interface records in, 85 out,
name-for-name, across the five cells that carry interfaces (49→49, 9→9, 10→10,
4→4, 13→13; two cells carry none). That is the opposite of
`aruba_aoscx__arista_eos`, where a shrinking record count made every
`interfaces[].*` sub-field measure as drifted.

Instead, **one root cause produces three separate symptoms**. It is stated
once here so the YAML entries are not read as three independent findings.

The `aruba_aoscx` codec derives an interface's kind from the **shape of its
name** (`classify_port_name` in
`netcanon/migration/codecs/aruba_aoscx/port_names.py`): `1/1/25` → physical,
`vlan 10` → svi, `lag 1` → lag, `loopback 0` → loopback, `mgmt` → mgmt,
everything else → `unknown`. Checked directly against the classifier, **every**
AOS-S port name lands in `unknown`:

| AOS-S name | AOS-CX classification |
|---|---|
| `1/25` | `unknown` (needs the 3-segment `m/s/p` triple) |
| `13` | `unknown` |
| `A1` | `unknown` |
| `Vlan1` | `unknown` (AOS-CX wants `vlan 1`, space-separated) |
| `Trk1` | `unknown` (AOS-CX wants `lag 1`) |

From that single fact:

1. **`interfaces[].interface_type` degrades to `ianaift:other`** on all 85
   records. Both codecs infer the IANA ifType from the name shape and their
   shapes disagree — and, fairly, **both matrices already declare
   `/interfaces/interface/config/type` lossy**.
2. **All per-port VLAN membership is dropped.** The render's L2 branch is
   gated on `kind in ("physical", "lag")`, so it never fires. There is **not
   one `vlan access`, `vlan trunk` or `no routing` line in any of the seven
   rendered configs** — 357 VLAN member-port tokens in, 0 out.
3. **The names themselves survive**, which is why `interfaces[].name` is
   `good`: `format_port_identity` returns `None` for an `unknown` kind and the
   orchestrator leaves the name verbatim. The rendered config reads
   `interface 1/25`, not the AOS-CX-native `interface 1/1/25`.

**There is a remediation, and it is worth knowing before cutover.** The bare
mesh path measures a raw parse → render. Routing the migration through the
port-rename path instead — `run_plan_with_overrides`, which engages
`translate_port_names` — classifies the name with the **source** codec and
formats it with the **target** codec, rewriting `1/25` → `1/1/25` and
`Trk1` → `lag 1`. Measured on the kitchen-sink cell, that restores real
`vlan access 10` / `vlan trunk allowed 10,20,30,40` lines and brings back 11 of
31 member tokens plus correct `ethernetCsmacd` / `ieee8023adLag` types. It
converts a total drop into a partial one. It does **not** close it: `Vlan<N>`-
and `A<N>`-shaped names still do not map.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces[].name / description / enabled | 5 | 0 | 2 |
| interfaces[].ipv4_addresses | 4 | 0 | 3 |
| interfaces[].ipv6_addresses | 1 | 0 | 6 |
| interfaces[].interface_type | 0 | 5 | 2 |
| interfaces[].lag_member_of | 0 | 2 | 5 |
| vlans[].id | 7 | 0 | 0 |
| vlans[].name | 6 | 0 | 1 |
| vlans[].ipv4_addresses | 0 | 4 | 3 |
| vlans[].untagged_ports | 0 | 6 | 1 |
| vlans[].tagged_ports | 0 | 5 | 2 |
| static_routes | 5 | 0 | 2 |
| dns_servers | 0 | 3 | 4 |
| ntp_servers | 0 | 1 | 6 |
| radius_servers | 0 | 1 | 6 |
| snmp.community / location / contact | 6 | 0 | 1 |
| snmp.trap_hosts | 4 | 2 | 1 |
| snmp.v3_users | 5 | 1 | 1 |
| lags | 0 | 2 | 5 |
| local_users[].name / role / hashed_password | 3 | 0 | 4 |

Fields trivially empty on all 7 cells: `domain`, `timezone`, `syslog_servers`,
`dhcp_servers`, `interfaces[].mtu`, `interfaces[].vrrp_groups`,
`vlans[].description`, `vxlan_vnis[].vni` / `vlan_id` / `mcast_group`,
`evpn_type5_routes`, `routing_instances[].name` / `description`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`.

## Source-side gaps vs target-side drops vs symmetric gaps

Three different shapes of "nothing happened", recorded differently because
they tell an operator different things.

**Source-side gaps** (`not_applicable`) — `aruba_aoss` cannot emit the field,
so there is nothing for AOS-CX to lose. `interfaces[].mtu` (no
`/interfaces/interface/config/mtu` path declared at all),
`vlans[].description`, `routing_instances[].name`
(`/routing-instances/instance` unsupported), all three `vxlan_vnis[].*`
(`/vxlan-vnis/vni` unsupported — "VXLAN not modelled, AOS-S is a campus L2/L3
codec"), `anycast_gateway_mac` (`/anycast-gateway-mac` unsupported),
`raw_sections`, `evpn_type5_routes`, and the two Junos-only keys.

For `interfaces[].mtu`, `vlans[].description`, `routing_instances[].name` and
`anycast_gateway_mac` the **target declares the field supported** — so
re-authoring on the AOS-CX side will stick, and the migration report should
say so rather than implying the target cannot hold it.

**Target-side drops** (`unsupported`) — the source emits it, AOS-CX declares
it unsupported at the exact path, and the record vanishes:
`/system/dns-server`, `/system/ntp-server`, `/snmp/trap-host`,
`/radius-servers/server/host` + `/key`.

**Symmetric gaps** (`unsupported`) — both matrices declare it unsupported:
`/system/domain`, `/system/timezone`, `/system/syslog-server`,
`/dhcp-servers/pool`, and `routing_instances[].description`. Worth one note:
one committed fixture is literally an AOS-S **DHCP-server** config and
`dhcp_servers` is *still* empty on it, because the source parser never
populates a pool.

`interfaces[].vrrp_groups` is its own case: `aruba_aoss` declares the group
anchor **supported**, `aruba_aoscx` declares it **unsupported** (AOS-CX
expresses first-hop redundancy as VSX `active-gateway`; its VRRP wire-up is
deferred). No cell exercises it, so the call rests on the declarations — but
if your AOS-S aggregation pair runs VRRP, this is the one field on this pair
that can silently cost you a default gateway.

## Three findings worth carrying forward

### 1. `vlans[].ipv4_addresses` looks like a vanish and is not

The total-drop heuristic flags the `vlans` parent as a **TOTAL** vanish. The
`aruba_aoscx` matrix declares `/vlans/vlan/ipv4/address/ip` merely **lossy**.
The signals disagreed, so this was settled by round-trip rather than by
grammar.

**All 18 VLAN-record IPv4 addresses in the corpus appear verbatim in the
AOS-CX render text, and all 18 re-parse onto the sibling `interface Vlan<N>`
record.** AOS-S mounts an SVI address on *both* the VLAN record and an
interface record; AOS-CX renders SVI L3 only from the interface stanza, so the
duplicate mount is what empties.

`lossy` is therefore correct and `unsupported` would be actively misleading —
it would tell an operator the SVI address is gone when it is sitting in the
output. **Verify SVI addressing against `interfaces[].ipv4_addresses` after
cutover, not against this field.**

The heuristic's "TOTAL" verdict on the `vlans` parent is an artifact of
aggregating sub-fields: `untagged_ports` and `tagged_ports` genuinely do
vanish (finding 2), and they dominate the parent-level count.

### 2. VLAN port membership is a real total drop — and a matrix under-declaration

357 member-port tokens in, 0 out; zero membership lines in seven renders.
Recorded `unsupported` rather than `lossy` per netcanon #436: `lossy` warns and
stays compatible, and a config in which every access port lands in no VLAN is
not a nuance.

But note what this is **not**. It is not an AOS-CX capability limit — the
platform and the codec both model `vlan access <id>` perfectly well, and the
`aruba_aoscx` matrix declares `/vlans/vlan/untagged-ports` and
`/vlans/vlan/tagged-ports` **supported**. That declaration is a **matrix
under-declaration** against this pair's measured behaviour. It is flagged here
and left for a codec change rather than fixed in an expectation file — the
same call the `aruba_aoscx__arista_eos` pair made about `arista_eos` declaring
nothing for `/lags/lag`.

`vlans[].untagged_ports` and `vlans[].tagged_ports` share this one cause, so
neither is cited as corroborating the other. They are recorded separately only
because the consequences differ: a trunk with no allowed-VLAN list fails
loudly at cutover, a mis-VLANed access port may not.

### 3. `lags` drift is mostly a naming artifact — but check LACP mode

The audit's `_canonical_lag_name` collapses `ae<N>` / `Po<N>` /
`Port-channel<N>` / `trk<N>` / `agg<N>` / `bond<N>` to a common token so a pure
rename does not count as drift. It does **not** recognise the space-separated
AOS-CX `lag <N>` form, so `trk1` → `lag 1` surfaces as drift on both
`lags[].name` and `interfaces[].lag_member_of` even though the member set is
byte-identical (`['23','24']` in, `['23','24']` out) and `lag 1` is present
under the member interface in the render. That canonicaliser gap is a
tools-side matter, noted rather than papered over.

Two things in `lags` are *not* artifacts:

- **LACP mode falls from `active` to `static`.** Both matrices declare
  `/lags/lag/mode` lossy. An active-LACP uplink arriving as a static bundle
  will not negotiate with the far end. Check this first on any uplink.
- **One bundle vanished entirely** on the synthetic cell (2 LAGs → 1). Its
  members exist as member *names* but not as interface *records* in the source
  intent, and the AOS-CX renderer emits a LAG from
  `CanonicalInterface.lag_member_of` rather than from `CanonicalLAG.members` —
  so a bundle with no member interface record renders nothing. The surviving
  bundle keeps its exact member set, which is why the field as a whole is
  `lossy` rather than `unsupported`.

## Credential material

This pair is the exception in the mesh: **`local_users[].hashed_password` is
`good`**, preserved on all 3 cells that populate local users (5 accounts). It
survives because source and target are the same vendor family, so AOS-CX
re-emits the AOS-S secret token in the form it arrived in. The corpus carries
`sha1:`-prefixed digests and one `plaintext:`-marked account.

Do not generalise this. It holds for AOS-S → AOS-CX specifically. And the
`plaintext:` marker is a standing reminder to audit what you are carrying
across before you carry it.

`snmp.v3_users` is the opposite story dressed as a survivor. The user records
persist with names and auth protocols intact, so the field is `lossy` — but
`aruba_aoscx` renders SNMPv3 with SHA-1 auth and AES-128 privacy **only**, so
a source using SHA-224/256/384/512 or AES-192/256 is silently **downgraded**;
the VACM group binding drops; and the passphrases re-emit as device-key
ciphertext tokens (crypt-style, `$1$` marker) that are portable to the same
device only. Treat SNMPv3 accounts as re-created, not migrated.

`radius_servers` drops the host and the shared secret together
(`unsupported`); re-key RADIUS out of band on the target.

No secret value — AOS-S digest, `plaintext:` token, SNMPv3 passphrase or
RADIUS key — is reproduced in this file or in the expectation YAML. Per
`AGENTS.md`, encrypted and hashed secrets are operator-traceable even when not
plaintext, and a document that quotes the value it describes defeats its own
redaction.
