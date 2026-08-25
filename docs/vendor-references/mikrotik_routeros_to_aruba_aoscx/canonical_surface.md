# MikroTik RouterOS → ArubaOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/mikrotik_routeros__aruba_aoscx.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every ambiguous lossy-vs-unsupported call below was additionally
proved by round-tripping the fixture (parse with `mikrotik_routeros`, render
with `aruba_aoscx`, re-parse the render) and reading the emitted text.

- Fixture cells: **5**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and read-only round-trips of the five
> committed fixtures. Where a disposition rests on a declaration rather than an
> observed round-trip, the YAML says so explicitly.

The five cells:

| fixture | ifaces | vlans | lags | users | routes |
|---|---|---|---|---|---|
| `tests/fixtures/real/mikrotik/ntc_ip_address_export.rsc` | 2 → 2 | 0 | 0 | 0 | 0 |
| `tests/fixtures/real/mikrotik/routeros_diff_verbose_export.rsc` | 9 → 9 | 1 | 0 | 0 | 0 |
| `tests/fixtures/real/mikrotik/taqavi_initial_provisioning.rsc` | 7 → 7 | 0 | 0 | 0 | 0 |
| `tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc` | 16 → 16 | 5 | 0 | 0 | 0 |
| `tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc` | 12 → 12 | 3 | 2 | 3 | 4 |

## Device-class framing

`mikrotik_routeros` in this corpus is an **SMB / branch edge router** — RouterBoard
and CRS boxes terminating a WAN link, bridging a LAN, serving DHCP and resolving
DNS for the site. `aruba_aoscx` is a **campus access/aggregation switch**.

The pair is therefore asymmetric in a way that is the mirror image of the
AOS-CX → EOS pair: the shared surface is the L2/L3 edge (interface inventory,
interface addressing, the VLAN dictionary, static routes, SNMP scalars, LAG
bundles) and it survives well. What does not survive is the **router-services**
surface — DHCP server, DNS resolvers, NTP, RADIUS and local accounts — which
the AOS-CX renderer does not emit at all.

## The structural finding: the interface list does *not* shrink

Worth stating up front because the sibling AOS-CX pairs are dominated by the
opposite effect. Here the interface record count is **identical on every cell**
(2 → 2, 7 → 7, 9 → 9, 12 → 12, 16 → 16; 46 records total). No interface record
vanishes, so each `interfaces[].*` sub-key is judged on its own merits rather
than inheriting a record drop:

`name`, `description`, `enabled`, `mtu`, `ipv4_addresses` and `ipv6_addresses`
are all **preserved on every populated cell** and are recorded `good`. Only
`interface_type` and `lag_member_of` drift, and each has its own single,
identified cause.

## Per-key measurement (5 cells)

`d` = cells where the key drifted, `p` = preserved, `t` = trivially empty on
both sides.

| key | d | p | t |
|---|---|---|---|
| hostname | 3 | 2 | 0 |
| dns_servers | 1 | 0 | 4 |
| ntp_servers | 3 | 0 | 2 |
| domain / timezone / syslog_servers | 0 | 0 | 5 |
| interfaces[].name | 0 | 5 | 0 |
| interfaces[].enabled | 0 | 5 | 0 |
| interfaces[].ipv4_addresses | 0 | 5 | 0 |
| interfaces[].description | 0 | 3 | 2 |
| interfaces[].mtu | 0 | 3 | 2 |
| interfaces[].ipv6_addresses | 0 | 1 | 4 |
| interfaces[].interface_type | 5 | 0 | 0 |
| interfaces[].lag_member_of | 1 | 0 | 4 |
| interfaces[].vrrp_groups | 0 | 0 | 5 |
| vlans[].id / vlans[].name | 0 | 3 | 2 |
| vlans[].description | 0 | 2 | 3 |
| vlans[].ipv4_addresses / untagged_ports / tagged_ports | 0 | 0 | 5 |
| static_routes | 1 | 0 | 4 |
| dhcp_servers | 3 | 0 | 2 |
| snmp.community / location / contact | 0 | 3 | 2 |
| snmp.trap_hosts | 1 | 2 | 2 |
| snmp.v3_users | 3 | 0 | 2 |
| lags | 1 | 0 | 4 |
| local_users[].name / role / hashed_password | 1 | 0 | 4 |
| radius_servers | 1 | 0 | 4 |

Trivially empty on all 5 cells: `domain`, `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, `vlans[].ipv4_addresses`, `vlans[].untagged_ports`,
`vlans[].tagged_ports`, `vxlan_vnis[].*`, `evpn_type5_routes`,
`routing_instances[].*`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## Finding 1 — `interface_type` collapses to `ianaift:other` on all 46 records

The AOS-CX capability matrix declares `/interfaces/interface/config/type` lossy
and explains why: *"AOS-CX declares no IANA ifType; the codec infers it from the
interface-name shape (`1/1/1` → ethernetCsmacd, `vlan N` → l3ipvlan, `lag N` →
ieee8023adLag, `loopback N` → softwareLoopback)."*

RouterOS interface names match **none** of those shapes. `ether1`,
`sfp-sfpplus1`, `bridge1`, `vlan100`, `bond1`, `wireguard-office` all fall
through to the default, so every record on every cell reads
`ianaift:other` after the round-trip:

- `ianaift:ethernetCsmacd` → `ianaift:other` (physical ports)
- `ianaift:bridge` → `ianaift:other` (RouterOS bridges)
- `ianaift:l3ipvlan` → `ianaift:other` (RouterOS VLAN interfaces)
- `ianaift:ieee8023adLag` → `ianaift:other` (RouterOS bonds)
- `""` → `ianaift:other` (records with no source type — an invention, not a loss)

**This is one cause producing 46 drifted records.** It is not independent
evidence for anything else on the interface surface, and it is not cited as
corroboration anywhere in the YAML.

## Finding 2 — preserved names are *not* AOS-CX port names

`interfaces[].name` is `good`: `ether1` goes in and `ether1` comes out. That
measures **preservation**, not target-syntax validity. The mesh round-trip is a
bare parse → render → re-parse; it does not run `translate_port_names`, and the
rendered config contains stanzas like `interface ether1` and `interface bond1`,
which are not configurable interface names on an AOS-CX switch.

Read `good` here as "the canonical string survived the migration intact", and
plan a port-rename map (`run_plan_with_overrides(port_rename_map=...)`) as a
separate, mandatory cutover step. Finding 1 is the visible symptom of the same
gap: because the names are not AOS-CX-shaped, the target cannot even infer the
port type from them.

## Finding 3 — every local user vanishes, and the cause is the *missing* password

Proved by round-tripping `tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc`:
3 users in, **0 users out**. The mechanism is a three-step interaction, and it is
worth spelling out because the target matrix does not predict it:

1. The RouterOS parser sets `hashed_password=""` unconditionally — its own
   comment reads *"/export omits hashes"*. RouterOS never exports user secrets,
   so this source can never carry one.
2. The AOS-CX renderer emits the **short** form when `hashed_password` is empty:
   `user <name> group <role>`, with no `password` clause.
3. The AOS-CX parser's user pattern **requires** the password clause —
   `^user\s+(\S+)\s+group\s+(\S+)\s+password\s+ciphertext\s+(\S+)`. The short
   form matches nothing, so all three accounts are dropped on re-parse.

The record vanishes entirely, so `local_users[].name`, `.role` and
`.hashed_password` are all recorded `unsupported`, not `lossy` (netcanon #436:
a vanished record is not lossy). All three drift for **this one reason**; the
YAML states the cause once and cross-references it rather than treating three
correlated keys as three findings.

Two things follow that an operator should act on:

- **The AOS-CX matrix declares `local_users` supported** (3 supported paths,
  `/local-users/user/privilege-level` lossy) while dropping every account from a
  passwordless source. That is a matrix under-declaration, conditional on the
  source carrying no secret. It is a codec-side call, not a pair-specific fact,
  and is recorded here rather than worked around.
- Even on the path where a password *does* exist, the rendered group token is
  the canonical `role` verbatim (`group admin`, `group operator`), not one of
  the AOS-CX group names (`administrators` / `operators` / `auditors`). The line
  would re-parse cleanly and still need editing before it is accepted by a box.

Re-create every account on the AOS-CX side by hand, with fresh credentials.

## Finding 4 — LAG: a naming artifact the canonicaliser misses, plus a real mode loss

Both halves of this were verified against the round-trip, not inferred from the
drift shape.

**The name drift is an artifact.** `tools/run_phase4_reconciliation.py`
canonicalises LAG names before comparing (`_LAG_NAME_FIELDS` /
`_canonical_lag_name`) so a vendor-native rename does not fire as drift. Its
regex is `^(?:ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond)(\d+)$`. The
source name `bond1` matches and canonicalises to `LAG1`; the AOS-CX target name
is **`lag 1`** — space-separated, and `lag` is not in the prefix set — so it
canonicalises to `None`, the comparison falls back to raw equality, and the
rename surfaces as drift. Membership itself is intact: 2 bundles in, 2 out,
`ether3`/`ether4` → `lag 1` and `ether5`/`ether6` → `lag 2`.

**The mode drift is real.** `bond1` carries `mode: active` (LACP) in the source
and re-parses as `mode: static`. The AOS-CX matrix predicts exactly this for
`/lags/lag/mode`: the `lacp mode` line is emitted only for a kind-`lag`
interface present in the tree. Here the bundle renders as `interface bond1` —
a RouterOS name — so there is no `interface lag 1` anchor to hang `lacp mode
active` on, and the bundle arrives static.

That is the operationally dangerous half: an LACP bundle that silently becomes a
static bundle will not negotiate with a peer that is still running LACP.
Re-create the bundle as `interface lag <N>` with `lacp mode active` explicitly.

The same render also splits the bundle's identity: `interface bond1` holds the
bundle's description and its `ip address 10.255.0.1/32`, while the member ports
reference `lag 1`. Anchor and members disagree by name in the emitted text.

## Finding 5 — `hostname` drifts by two different mechanisms, neither a plain drop

3 of 5 cells drift, and the two causes need different operator responses:

- **Fabrication (2 cells).** `ntc_ip_address_export.rsc` and
  `taqavi_initial_provisioning.rsc` carry no `/system identity` line, so the
  canonical hostname is empty. The AOS-CX renderer substitutes its platform
  default — `hostname = tree.hostname or "switch"` — and the re-parse reads back
  `switch`. Nothing was lost; a name was **invented**. Set the hostname
  explicitly rather than accepting a device called `switch`.
- **Truncation (1 cell).** `routeros_diff_verbose_export.rsc` has the identity
  `Quinta Router`. The render emits `hostname Quinta Router` verbatim, and the
  AOS-CX parser's `^hostname\s+(\S+)` stops at the space, yielding `Quinta`.
  This is a real loss, and it generalises: RouterOS `/system identity` routinely
  contains spaces, AOS-CX hostnames cannot. Audit source identities for
  whitespace before the cutover.

## Finding 6 — SNMP splits three ways

- `community`, `location`, `contact` — **preserved on all 3 populated cells**.
  Rendered as `snmp-server community`, `snmp-server system-location`,
  `snmp-server system-contact`.
- `trap_hosts` — **total drop**. The rendered AOS-CX config contains no
  `snmp-server host` line whatsoever, and the target matrix declares
  `/snmp/trap-host` unsupported (the trap-receiver grammar is not wired in this
  codec phase). Recorded `unsupported`.
- `v3_users` — **survives, degraded**, on both of the mechanisms present in the
  corpus. Recorded `lossy`:
  1. *Cryptographic downgrade* (`kitchen_sink.rsc`). AOS-CX renders SHA-1 auth
     and AES-128 privacy only. A source user with SHA-256 auth and AES-256
     privacy re-parses as `sha` / `aes`. Both users survive as records; the
     algorithm strength does not. The matrix declares this on four
     `/snmp/v3-user/*` paths and it reproduced exactly.
  2. *Empty-passphrase mis-tokenisation* (`routeros_diff_verbose_export.rsc`,
     `user_contrib_crs310_ros7.rsc`). Where the source USM user carries no
     passphrase, the rendered line leaves an empty slot after
     `auth-pass ciphertext`. The parser's `(\S+)` capture then swallows the
     *next keyword* as the passphrase, and the optional privacy clause no longer
     matches, so `priv_protocol` is lost. The user record survives with a
     nonsense auth secret and no privacy protocol.

  Re-create SNMPv3 users on the target. They cannot be migrated, and case 2
  produces a record that looks populated but is not usable.

## The router-services cliff

Four whole fields are dropped in their entirety by the AOS-CX render — verified
by round-trip (no matching line appears anywhere in the emitted config), and
declared unsupported at the exact path by the target matrix:

| field | measured | target declaration |
|---|---|---|
| `dns_servers` | all 2 dropped (1 cell) | `/system/dns-server` unsupported |
| `ntp_servers` | all 1–2 dropped (3 cells) | `/system/ntp-server` unsupported |
| `dhcp_servers` | all 1–2 dropped (3 cells) | `/dhcp-servers/pool` unsupported |
| `radius_servers` | all 2 dropped (1 cell) | `/radius-servers/server/host` + `/key` unsupported |

This is the single most important planning item on the pair. A MikroTik branch
router is usually the site's DHCP server and DNS resolver; an AOS-CX access
switch is neither, and this codec renders neither. Every one of these services
needs a new home — a DHCP relay pointing at a central server, an upstream
resolver, an NTP source and a RADIUS configuration authored directly on the
target — before the MikroTik is switched off.

## Source-side gaps vs target-side drops

The distinction drives the `not_applicable` / `unsupported` split, and it tells
a reader whether re-authoring on the target would help.

**Source cannot emit (recorded `not_applicable`).** The RouterOS matrix declares
these unsupported at the exact path, so nothing reaches the target:
`/vlans/vlan/tagged-ports` · `/vlans/vlan/untagged-ports` · `/vxlan-vnis/vni` ·
`/routing-instances/instance` · `/anycast-gateway-mac`.

AOS-CX **supports** VLAN port membership, the VLAN↔VNI binding, the `vrf <name>`
anchor and the switch-wide anycast gateway MAC — so re-authoring all of them on
the target will stick. That is worth saying plainly rather than letting a
`not_applicable` read as "the target cannot hold it".

`vlans[].ipv4_addresses` is a source-*shape* gap rather than a declared one:
RouterOS expresses VLAN L3 as an address on the `vlanN` **interface**, which
lands on `interfaces[].ipv4_addresses` (measured `good` on all 5 cells) and
leaves the VLAN record's own address list empty on every cell. Both matrices
declare `/vlans/vlan/ipv4/address/ip` lossy, so a source that *did* mount an
address on the VLAN record would degrade — but no committed cell does.

**Symmetric gaps (recorded `unsupported`).** Both matrices declare these
unsupported, so the gap belongs to the pair rather than to Aruba:
`/system/domain` · `/system/timezone` · `/system/syslog-server` ·
`/routing-instances/instance/description`.

**Target-side blocks (recorded `unsupported`).** The source models these and the
target refuses them: the four router services above, `/snmp/trap-host`, and the
whole `/interfaces/interface/vrrp-groups/group` subtree. AOS-CX VRRP is not
wired in this codec phase; its first-hop-redundancy surface is the `active-gateway`
anycast construct instead. No committed cell on this pair carries a VRRP group,
so that one rests on the declaration, not on an observation — the YAML says so.

## Credential material

Two credential surfaces cross this pair and **neither value is reproduced** in
this file or in the expectation YAML.

- RouterOS `/export` omits password hashes entirely, so
  `local_users[].hashed_password` is empty on the source side of every cell. The
  loss recorded against it is the record drop of Finding 3, not a hash-format
  incompatibility.
- AOS-CX stores user and SNMPv3 secrets as device-key ciphertext blobs (an
  `AQB…`-shaped prefix). Only the shape is described here. Per `AGENTS.md`,
  encrypted secrets are operator-traceable even when encrypted, and a document
  that quotes the value it describes defeats its own redaction.
