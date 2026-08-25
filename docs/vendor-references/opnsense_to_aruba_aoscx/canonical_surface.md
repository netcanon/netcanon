# OPNsense → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/opnsense__aruba_aoscx.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Four calls were additionally settled by round-tripping the fixture
and reading the render; each is marked **probed** below.

- Fixture cells: **8** (7 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`opnsense` in this corpus is a **FreeBSD-based edge firewall/router**;
`aruba_aoscx` is a **campus access/aggregation switch**. The pair is therefore
asymmetric in a specific direction: the firewall owns a *service* surface
(DHCP pools, DNS resolvers, RADIUS, SNMP trap receivers) and a *redundancy*
surface (CARP) that the switch has no stanza for at all, while the L2/L3
plumbing underneath — interfaces, addressing, VLANs, static routes — maps
across cleanly.

The realistic migration is not "replace the firewall with a switch". It is
re-homing the routed/switched plumbing behind a firewall onto AOS-CX while the
firewall's service and redundancy roles move somewhere else entirely. Read the
loss list below as *"here is what has to live somewhere else"*, not as codec
defects.

## The structural finding — and it is the opposite of the AOS-CX → EOS pair

On `aruba_aoscx__arista_eos` the dominant loss is structural: the interface
record count shrinks, so every `interfaces[].*` sub-field is forced to `lossy`
whether or not the attribute itself survives.

**That does not happen here.** The interface inventory is preserved *exactly*
on all 8 cells:

| cell | source ifaces | target ifaces |
|---|---|---|
| opnsense_acl_test_config | 2 | 2 |
| opnsense_core_default | 2 | 2 |
| opnsense_docs_carp_ha_backup | 3 | 3 |
| opnsense_docs_carp_ha_master | 3 | 3 |
| opnsense_paramiko_shell_capture | 2 | 2 |
| opnsense_service_test_config | 3 | 3 |
| user_contrib_supergate_opn25 | 8 | 8 |
| kitchen_sink (synthetic) | 7 | 7 |

Because no record vanishes, **each `interfaces[].*` key was measured on its own
merits** and six of the nine are honestly `good`. OPNsense-native names
(`em0`, `vlan0.20`, `lagg0`) pass through the render verbatim rather than being
re-shaped into AOS-CX `1/1/N` form.

This is worth stating because the reverse conclusion is the one an author is
primed to reach after reading the AOS-CX → EOS file. The correlated-drift trap
is real, but it does not apply to this pair's interface block. It *does* apply
to this pair's `local_users` block — see below.

## Per-field measurement (8 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 1 | 0 |
| domain | 0 | 7 | 1 |
| dns_servers | 0 | 4 | 4 |
| interfaces[].name / enabled / ipv4_addresses | 8 | 0 | 0 |
| interfaces[].description | 5 | 0 | 3 |
| interfaces[].mtu | 1 | 0 | 7 |
| interfaces[].ipv6_addresses | 2 | 0 | 6 |
| interfaces[].interface_type | 0 | 8 | 0 |
| interfaces[].lag_member_of | 0 | 1 | 7 |
| interfaces[].vrrp_groups | 0 | 2 | 6 |
| vlans[].id / name | 2 | 0 | 6 |
| static_routes | 2 | 1 | 5 |
| dhcp_servers | 0 | 4 | 4 |
| snmp.community / location / contact | 3 | 0 | 5 |
| snmp.trap_hosts | 2 | 1 | 5 |
| snmp.v3_users | 3 | 0 | 5 |
| lags | 0 | 1 | 7 |
| local_users[].name / role / hashed_password | 6 | 1 | 1 |
| radius_servers | 0 | 1 | 7 |

Fields trivially empty on all 8 cells: `ntp_servers`, `timezone`,
`syslog_servers`, `vlans[].ipv4_addresses`, `vlans[].untagged_ports`,
`vlans[].tagged_ports`, `vlans[].description`, `vxlan_vnis[].vni`,
`vxlan_vnis[].vlan_id`, `vxlan_vnis[].mcast_group`, `evpn_type5_routes`,
`routing_instances[].name`, `routing_instances[].description`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

## Source-side gaps vs target-side drops vs symmetric gaps

Three shapes, three dispositions, because the operator action differs.

**Target-side drops → `unsupported`.** The source emits them; the AOS-CX render
has nowhere to put them and they vanish whole. Per #436 a vanished record is
not `lossy` — `lossy` warns and stays compatible, which would understate these.

`/system/domain` · `/system/dns-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` + `/key` · `/snmp/trap-host` ·
`/interfaces/interface/vrrp-groups/group`

**Symmetric gaps → `unsupported`.** Both matrices declare the path unsupported,
so nothing was carried and nothing was lost, but nothing will migrate either:

`/system/ntp-server` · `/system/timezone` · `/system/syslog-server` ·
`/routing-instances/instance/description`

**Source-side gaps → `not_applicable`.** OPNsense declares these unsupported,
so as a *source* it never emits them and there is nothing for AOS-CX to lose:

`/vlans/vlan/tagged-ports` · `/vlans/vlan/untagged-ports` ·
`/routing-instances/instance` · `/vxlan-vnis/vni` · `/anycast-gateway-mac` ·
`/interfaces/interface/ipv4/address/secondary-ip` ·
`/interfaces/interface/ipv4/address/virtual-gateway-address`

The distinction matters at cutover. For the source-side gaps, **aruba_aoscx
declares the VRF anchor, VLAN port membership and the anycast gateway MAC
SUPPORTED** — so re-authoring them on the switch will stick. For the target-side
drops, re-authoring will not help until the codec grows the stanza.

## Four calls settled by probing, not by grammar

### 1. `static_routes` is a partial degradation, not a total drop — **probed**

The whole-drop heuristic classified this pair's `static_routes` as `TOTAL →
unsupported`. The measurement disagreed (2 preserved / 1 drifted / 5 trivial),
and a total drop is arithmetically impossible with two preserved cells. The
round-trip settles it: on all 3 populated cells the route count is 1 in and
1 out, and destination + next-hop gateway compare byte-identical. The single
drift is the route **description** arriving empty, which is exactly what
aruba_aoscx declares (`/routing/static-route/description` lossy — "Render emits
destination + next-hop only").

Recorded `lossy`. Forwarding survives cutover; the operator labelling does not.

### 2. `snmp.trap_hosts` is a total drop the counts understate — **probed**

The counts look mild: 2 preserved, 1 drifted. But the two "preserved" cells
carry an **empty** trap-host list on both sides, so they confirm nothing — the
per-key trivial flag is computed from the parent `snmp` object's emptiness, not
the key's. On the one cell that actually defines trap receivers, the render
contains only:

```
snmp-server community <name>
snmp-server system-location <text>
snmp-server system-contact <text>
```

No trap-receiver line at all; both receivers are gone. aruba_aoscx declares
`/snmp/trap-host` unsupported. Recorded `unsupported`.

**Polling survives this migration; trapping does not.** The NMS goes quiet
without any config diff explaining why.

### 3. `interfaces[].vrrp_groups` is a total vanish — **probed**

The two CARP fixtures carry two CARP groups (VRIDs 1 and 3, each with a virtual
IP, priority 254, preempt set). The rendered AOS-CX config contains no `vrrp`,
no `active-gateway` and no CARP line of any kind; re-parsing yields zero
interfaces with a VRRP group. aruba_aoscx declares the entire
`/interfaces/interface/vrrp-groups/group` subtree unsupported — "AOS-CX VRRP is
a deferred phase (the group anchor is unsupported)" — along with every child.

Recorded `unsupported`. **This is the highest-impact loss on the pair**: an
OPNsense HA pair migrated as-is arrives with no first-hop redundancy at all.
Treat it as a cutover blocker, not a warning.

Note the interaction with `interfaces[].ipv4_addresses`, which is `good`: the
interface's own address survives, but the CARP **virtual** IP lives on the VRRP
group and does not. A surviving interface address is not a surviving gateway.

### 4. `lags` — the loud half of the drift is cosmetic, the quiet half is real — **probed**

One cell carries a bundle. Both members (`em2`, `em3`) survive and stay bound
to it. Two things change:

- **`lagg0` → `lag 0`** — a rename, and operationally free. The audit's
  LAG-name canonicaliser (`_canonical_lag_name`) accepts only
  `ae<N>` / `Po<N>` / `Port-channel<N>` / `Port-Channel<N>` / `trk<N>` /
  `Trk<N>` / `agg<N>` / `bond<N>`. The FreeBSD `lagg0` form does not match, and
  the AOS-CX `lag 0` form contains a space so it cannot match either. Both
  sides fall through to raw equality and the rename surfaces as drift.
- **`active` → `static`** — the real loss. The render emits the per-member
  `lag 0` binding but **no `interface lag 0` stanza**, so no `lacp mode active`
  line is written and the bundle re-parses as a static bundle. aruba_aoscx
  declares `/lags/lag/mode` lossy for exactly this cause: a source whose LAG
  lives only in `intent.lags`, with no matching `lag N` interface record, loses
  the mode.

Recorded `lossy` (the bundle and its membership do survive). **Re-apply
`lacp mode active` on the target before turning the link up** — a static bundle
facing an LACP-speaking peer will not come up cleanly.

`interfaces[].lag_member_of` drifts on the same single cell for the same rename.
It is the same observation viewed through a second key, **not** independent
corroboration.

## The correlated-drift block: `local_users`

All three `local_users[].*` keys drift on **exactly one cell for exactly one
reason** — the account record count collapses **5 → 1** on
`opnsense_acl_test_config.xml`. They are three views of a single observation.
None corroborates the others.

The mechanism was confirmed by reading the render. All five accounts *are*
emitted, but the four with an empty password render as bare lines with no
credential clause:

```
user root  group admin password ciphertext <blob>
user test1 group user
user test2 group user
user test3 group user
user test4 group user
```

The AOS-CX parser does not recover an account from a line with no password, so
those four are lost on re-parse. Recorded `lossy`, not `unsupported`, because
the collapse is partial — the account *with* a password survives.

Operationally: OPNsense accounts that authenticate by certificate or API key,
and disabled placeholder accounts, will not appear on the target. Inventory the
source account list rather than diffing the migrated one.

Two more things this block hides:

- **`role` survives exactly** (`admin` → `admin`, `user` → `user`) on all 6
  populated cells. Its drift is purely the record collapse.
- **`privilege_level` drifts on all 8 accounts** across the corpus (15 → 1).
  The audit's key list has no key for it, so it appears in no disposition, but
  aruba_aoscx declares `/local-users/user/privilege-level` lossy: it maps its
  named groups back to a numeric privilege. The role *name* survives while the
  numeric privilege behind it does not — check any automation keyed on it.

## Credential material

`local_users[].hashed_password` drifts on 1 cell, and **only** because of the
record collapse above. On all 6 populated cells the stored secret compares
byte-identical after the round trip, and it was confirmed to appear verbatim in
the render.

That verbatim carry is the thing to be careful about, not a mangling. The
OPNsense secret is a fixed-length opaque string with **no crypt(3)
`$`-delimited prefix**. The AOS-CX render places it into a
`user <name> group <group> password ciphertext <blob>` line — i.e. it is
presented to the switch as an AOS-CX **`ciphertext`** value. The aruba_aoscx
matrix states of that encoding (on the SNMPv3 privacy key) that a `ciphertext`
blob is encrypted with the device key and is *"portable same-device only"*, and
that cross-vendor / cross-device migration "emits it verbatim and the operator
must re-set" it.

So a byte-perfect canonical round-trip is **not** evidence of a working
credential on the target device. Set passwords on the target before cutover and
treat every migrated account as unusable until you have.

No secret value is reproduced in this file or in the expectation YAML — only
its shape (length class and absence of a `$`-delimited prefix). Per `AGENTS.md`,
encrypted secrets are operator-traceable even when encrypted, and a document
that quotes the value it describes defeats its own redaction. The same rule
applies to the AOS-CX `AQB…`-shaped ciphertext blobs on the reverse pair and to
`$1$`/`$5$`/`$6$`/`$9$`/`$2y$` crypt hashes generally.

## Two `good` entries that must not be over-read

**1. `snmp.v3_users` is `good`, and the agreement is vacuous.** opnsense
declares `/snmp/v3-user` and its child paths unsupported, so the source emits
no v3 users at all; the round-trip confirms zero users on both sides of every
cell. "Preserved" here means *both sides are empty*. If a future OPNsense
source did carry v3 USM users, aruba_aoscx declares six of the v3-user child
paths lossy — including SHA-1 auth and AES-128 privacy **downgrades** — so
expect degradation, not fidelity.

**2. `interfaces[].description` is `good` against its own source matrix.** The
opnsense matrix declares `/interfaces/interface/config/description` LOSSY, yet
all 7 descriptions on the representative cell compare byte-identical after the
round trip. The disposition follows the measurement. That over-declaration is a
codec-matrix matter, not a pair-specific fact, and is left for a codec change
rather than adjusted here.

## Fabrication, not loss: two drifts that add rather than remove

Both of these are recorded as losses because they are measured drift, but the
direction is worth knowing before an operator goes hunting for missing config.

- **`hostname`** — on `opnsense_service_test_config.xml` the source carries no
  hostname at all, and the render emits a placeholder `hostname switch` which
  re-parses as a real hostname. Nothing configured was lost; a migrated device
  silently acquires a generic name. Set the hostname explicitly.
- **`interfaces[].interface_type`** — 30 interface records across all 8 cells,
  the single most-drifting sub-field on the pair. OPNsense declares no IANA
  ifType so the source value is empty; the AOS-CX codec infers one from the
  interface-name shape, and OPNsense-native names match none of the shapes it
  knows (`1/1/1`, `vlan N`, `lag N`, `loopback N`), so all 30 land on
  `ianaift:other`. Harmless on the wire — nothing keys off the canonical ifType
  — but do not use a post-migration type inventory to classify ports.
