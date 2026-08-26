# VyOS → Aruba AOS-S: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__aruba_aoss.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`vyos.parse()` → `aruba_aoss.render()` → `aruba_aoss.parse()` on each of the 13
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures under `tests/fixtures/real/vyos/`
  plus `tests/fixtures/synthetic/vyos/kitchen_sink.conf`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is a **software edge/lab router**: Linux netdev interface
names (`eth0`…`eth7`, `lo`, `dum0`, `bond0`), `vif` sub-interfaces modelled as
`eth1.100`, a curly-brace `config.boot`, VXLAN netdevs, and a single VRF.
`aruba_aoss` is a **campus L2/L3 access switch** — the ProVision-lineage CLI,
where L3 is mounted on the VLAN record and the feature set stops well short of
overlay and VRF.

The shared surface is therefore the **routed edge plus box management**:
hostname, DNS/NTP, interface addressing and admin state, static routes, SNMP,
and local-user identity. There is no campus L2 surface arriving from this
source — not one committed VyOS fixture populates `vlans` — and no overlay or
VRF surface surviving into this target.

## The structural finding — bare interfaces are elided, not translated

The interface inventory shrinks, and the rule behind it is exact.

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **45** |
| cells where the interface name set differs | **5** of 13 |
| records lost | **10** |

The AOS-S render applies a tiered-elision rule (`render.py::_has_body`, mirrored
from the Junos renderer): an interface stanza is emitted only when the record
carries a description, an address, an MTU, an explicit `disable`, a switchport
binding or LAG membership. `enabled=True` alone is the implicit admin-up state
and is **not** body — so an interface whose only canonical content is its name
renders nothing at all, and the re-parse cannot see it.

Every one of the 10 lost records fits that rule:

| cell | vanished |
|---|---|
| `metasploit-vyos-config.conf` | `eth1`, `lo` |
| `scottlaird-vyos-parser.conf` | `eth2`, `eth3`, `eth4`, `eth5`, `lo` |
| `vyos_forum_snmpv3_user_eq13.conf` | `lo` |
| `wcni-kind-gw0.conf` | `lo` |
| `wcni-kind-gw1.conf` | `lo` |

Nine of the ten carry `name` + `enabled=True` and nothing else. The tenth,
`scottlaird` `eth5`, additionally carries `dhcp_client=True` — which the
elision rule does not count as body either, so a DHCP-client port with no
static address disappears along with the bare ones.

Operationally that is mild: a VyOS `lo` with no address and an unconfigured
`ethN` are placeholders, not forwarding state. It is not nothing, though — the
port inventory an operator reads off the migrated config is shorter than the
one they started with, and `eth5` was doing something (DHCP client) that is now
invisible.

**Consequence for this file:** `interfaces[].name` carries that record-level
loss for the whole `interfaces` list. Every other `interfaces[].*` sub-field is
judged on the **45 records that survive**, matched by name, where the picture is
much cleaner.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 0 | 1 | 12 |
| dns_servers | 1 | 0 | 12 |
| ntp_servers | 11 | 1 | 1 |
| interfaces | 0 | 13 | 0 |
| static_routes | 4 | 0 | 9 |
| snmp | 2 | 2 | 9 |
| lags | 0 | 1 | 12 |
| local_users | 0 | 13 | 0 |
| vxlan_vnis | 0 | 3 | 10 |
| routing_instances | 0 | 1 | 12 |

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`, `vlans`
(the whole list — no committed VyOS fixture produces a VLAN record),
`dhcp_servers`, `radius_servers`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

### Interface sub-fields, measured on the 45 surviving records

| sub-field | differing | of matched | shape |
|---|---|---|---|
| `interface_type` | **45** | 45 | `""` → `ianaift:ethernetCsmacd` (see below) |
| `lag_member_of` | 2 | 45 | `bond0` → `trk0` (vendor-correct LAG rename) |
| `dot1q_vlan` | 2 | 45 | `100` / `200` → `null` |
| `dhcp_client` | 2 | 45 | `true` → `false` |
| `dhcp_client_v6` | 1 | 45 | `dhcpv6` → `""` |
| `mtu` | 1 | 45 | `1500` → `null` |
| `vrf` | 1 | 45 | `BLUE` → `""` |
| `name` / `description` / `enabled` / `ipv4_addresses` / `ipv6_addresses` / `vrrp_groups` | **0** | 45 | — |

Populated-field density on those 45 records: **15** carry a description, **21**
carry at least one IPv4 address, **20** carry at least one IPv6 address, **2**
are administratively down. All of it round-trips unchanged.

`dot1q_vlan`, `dhcp_client`, `dhcp_client_v6` and `vrf` are not keys in the
expectation YAML; they are recorded here because they are real and because
`vrf` is the interface-side half of the routing-instance drop discussed below.
`dot1q_vlan` is declared `unsupported` on **both** codecs, so the VyOS
`eth1.100` / `eth1.200` sub-interfaces arrive as ordinary interfaces with their
addressing intact but with the 802.1Q tag stripped from the canonical record;
`dhcp_client_v6` is declared lossy on the AOS-S side (no DHCPv6 client grammar).

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for AOS-S to lose:

`/vlans/vlan/id` · `/vlans/vlan/ipv4/address/{secondary-ip,virtual-gateway-address,virtual-gateway-mac}` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}` ·
`/interfaces/interface/vrrp-groups/group/*` · `/dhcp-servers/pool` ·
`/radius-servers/server/{host,key}` · `/system/timezone` ·
`/system/syslog-server` · `/anycast-gateway-mac`

Those split three ways in the YAML, and the split is deliberate:

- **`not_applicable`** where the source cannot emit it but the target models it
  — the six `vlans[].*` keys, `radius_servers`, `interfaces[].vrrp_groups`.
  AOS-S declares `/vlans/vlan/{id,name,tagged-ports,untagged-ports}`,
  `/vlans/vlan/ipv4/address/ip` and `/interfaces/interface/vrrp-groups/group`
  **supported**, so a campus L2 surface or a VRRP group authored on the target
  after cutover will stick. The migration report should say that rather than
  implying AOS-S cannot hold it.
- **`unsupported`** where **both** matrices declare the gap — `timezone`,
  `syslog_servers`, `dhcp_servers`, `anycast_gateway_mac`. Symmetric, and
  nothing carries them.
- **`not_applicable`** for the structurally-absent Junos surfaces
  (`apply_groups`, `group_content`), for `evpn_type5_routes` (neither codec
  declares a path and no cell populates it), and for `raw_sections` — where
  `vyos` does declare `/system/raw-sections/version-banner` lossy on its own
  side, but no committed VyOS fixture carries a raw section that reaches the
  render.

The `vlans[].*` entries are grounded in measurement, not only declaration:
**zero** of the 13 cells produce a single VLAN record. VyOS expresses tagging as
a `vif` sub-interface, which lands in `interfaces[]` as `eth1.100`, and expresses
L3 on the interface record. A software router has no campus VLAN database to
migrate.

## Six findings worth carrying forward

### 1. Credentials do not migrate — they are re-typed as cleartext

`local_users[].hashed_password` drifts on 12 of the 13 cells that populate
users — every cell whose user records survive — and the failure mode is worse
than a drop.

Every one of the 17 source accounts in this corpus carries a **`$6$` crypt
digest** (SHA-512), except one discussed in finding 2. The AOS-S render emits
the value as `password manager user-name "<user>" plaintext "<secret>"`, and the
re-parse returns it tagged `plaintext:`. Measured on **16 of 16** surviving
records: the canonical value goes from `$6$…` to `plaintext:$6$…`, ten
characters longer, digest body byte-identical. Nothing is lost; the secret is
**re-typed as a literal cleartext password**.

Two consequences for a cutover:

- No migrated account authenticates with its original password, because the
  target now treats the crypt digest as the password string itself.
- The rendered config contains the source's digest on a line marked
  `plaintext`, so it inherits none of the handling the `$6$` form implied. Treat
  any rendered AOS-S config from a VyOS source as secret-bearing.

Set passwords on the target by hand before cutover.

No digest body is reproduced in this file or in the expectation YAML — only the
crypt-scheme marker (`$6$`) and the length class are described. Per `AGENTS.md`,
password hashes are operator-traceable even when they are hashes, and a document
that quotes the value it describes defeats its own redaction. The one literal
that *is* quoted — the `plaintext:` tag — is a degradation artifact containing
no key material.

### 2. An account with no password disappears entirely

One account vanishes across the corpus: `netadmin` on
`houdev_vyos_dhcpv6_pd_client.conf`, the only user on that cell, whose canonical
`hashed_password` is the **empty string**. The render still emits a line —
`password manager user-name "netadmin" plaintext ""` — but the AOS-S parser's
`_PASSWORD_LINE_RE` requires at least one character inside the quotes
(`"([^"]+)"`), and its continuation-line fallback `_PASSWORD_HEAD_RE` requires
the line to end after the algorithm token. `plaintext ""` matches neither, so
the line is skipped and the record is gone: 17 source accounts, 16 after the
round-trip, and that cell renders a config with **zero** readable users.

The rule is clean enough to act on: **a source account with no secret is
silently dropped; every account with a `$6$` digest survives.** Diff the source
account list against the render before cutover — a silently missing admin
account is how a migration locks you out.

This is recorded `lossy` rather than `unsupported`: AOS-S plainly models local
users and emits them on 12 of 13 cells, so it is a partial record loss inside a
concept the target holds, not the concept-level gap that `vxlan_vnis` is. The
#436 rule that forces `unsupported` applies where the target cannot express the
thing at all.

`local_users[].role` is recorded separately and on its own measurement, over
the same 12 cells: all 17 source accounts carry role `admin`, and all 16
survivors come back `manager` —
a consistent re-mapping onto the AOS-S two-level `manager` / `operator`
vocabulary, not a drop. `privilege_level` 15 is preserved on all 16. The one
account that vanishes is accounted for **once**, under `local_users[].name`;
recording the same disappearance again under `role` or `hashed_password` would
double-count one loss.

### 3. `interface_type` is not lost here — it is invented

This is the drift-shape reading that is wrong on this pair, and it is the exact
inverse of the IOS-XR → EOS pair, where 138 of 156 records genuinely *lost* an
IANA type hint.

Measured across all 13 cells:

| side | `interface_type` values |
|---|---|
| source (`vyos`), 55 records | `""` on **all 55** |
| target (`aruba_aoss`), 45 records | `ianaift:ethernetCsmacd` on **all 45** |

The VyOS parser never populates the IANA ifType at all. The AOS-S parser
back-fills it from the interface-name shape, and its own matrix says so:
*"AOS-S does not declare IANA ifType; the codec infers type from interface-name
shape (bare number → ethernet, 'Trk' → port-channel, 'Vlan' → l3ipvlan)."* No
VyOS netdev name matches the `Trk` or `Vlan` shapes, so every record falls
through to ethernet.

So the canonical value drifts on 45 of 45 matched records, but the direction is
**gain, not loss** — and on `kitchen_sink.conf` the gained value is **wrong** on
three records: `lo` (a loopback), `dum0` (a dummy netdev) and `bond0` (a bundle)
all come back declared `ianaift:ethernetCsmacd`. That is the part worth acting
on. A migration report that says "the interface type was lost" is describing
the opposite of what happened; what an operator actually inherits is a type hint
that was never authored and is incorrect on every non-ethernet port.

Both matrices already declare `/interfaces/interface/config/type` lossy, so the
`lossy` disposition is the declared one as well as the measured one.

### 4. MTU is dropped silently, and neither matrix says so

`interfaces[].mtu` drifts on exactly one record: `kitchen_sink.conf` `eth0`,
`1500` → `null`. Thin, but the mechanism is total, not incidental.

`aruba_aoss/render.py` reads `iface.mtu` in **one** place — `_has_body()`, where
a non-null MTU is enough to make the interface render a stanza at all. There is
no MTU emit line anywhere in the renderer, and no MTU regex anywhere in the
parser. Any MTU on any source record will drop.

`vyos` declares `/interfaces/interface/config/mtu` **supported**. `aruba_aoss`
declares **nothing** for that path — neither supported, lossy nor unsupported —
while dropping it unconditionally. That is a matrix under-declaration, not a
pair-specific fact, and belongs to a codec change rather than to this file.

Two sibling under-declarations of the same kind, recorded for the same reason:
`aruba_aoss` declares nothing at all under `/local-users/*` while rendering and
parsing users (see findings 1 and 2), and nothing for `/lags/lag/name` or
`/lags/lag/members` while rendering a `trunk` line (see finding 6). Only
`/lags/lag/mode` is declared, and only as lossy.

### 5. The overlay and VRF surfaces are total drops

`vxlan_vnis` — 3 cells populate it (`wcni-kind-gw0`, `wcni-kind-gw1`,
`kitchen_sink`), one VNI record each; **all three become 0** after the
round-trip, and the rendered AOS-S config contains no VXLAN construct of any
kind. `vyos` declares `/vxlan-vnis/{vni,mcast-group,flood-list,udp-port}`
supported, so the source side is not the problem; `aruba_aoss` declares
`/vxlan-vnis/vni` unsupported with the plain reason *"VXLAN not modelled —
AOS-S is a campus L2/L3 codec."*

`routing_instances` — 1 cell populates it (`kitchen_sink`, VRF `BLUE`); it
becomes 0. `aruba_aoss` declares `/routing-instances/instance` unsupported:
*"Render emits no VRF/routing-instance construct."*

Both are recorded `unsupported` rather than `lossy`, because a vanished record
is not lossy (#436) — `lossy` warns and stays compatible, which would understate
losing an entire overlay.

The interface-side companion, `interfaces[].vrf` (`BLUE` → `""` on one record),
is **the same mechanism, not a second finding**. It is reported in the table
above for completeness and is not cited as evidence for the routing-instance
drop; neither corroborates the other.

### 6. Two drifts that are actually the target cleaning up after the source

Both are declared `lossy` because the canonical value genuinely changes and the
audit compares values — but calling either a "loss" without saying which way it
points would be misleading.

**`ntp_servers`.** One cell of 12 drifts:
`houdev_vyos_dhcpv6_pd_client.conf`. The VyOS `config.boot` writes its NTP
servers as `server time1.vyos.net { }` — a node with an empty inline brace
block — and the brace-stack parser captures the whole token run, so the
**source-side canonical value is already `"time1.vyos.net { }"`**. The AOS-S
render emits that verbatim (`sntp server priority 1 time1.vyos.net { }`) and the
AOS-S parser, whose regex captures a single `(\S+)`, hands back
`"time1.vyos.net"`. All three server hostnames survive; what is stripped is a
VyOS parse artifact. The defect here is on the **source** side, and it is the
only thing this cell's NTP drift is evidence of.

**`lags`.** One cell of 13 populates it (`kitchen_sink`). The bundle survives
with its member list (`eth4`, `eth5`) and its mode (`active`) intact; the
**name** changes, `bond0` → `trk0`, because the AOS-S render expresses the
bundle as `trunk eth4,eth5 trk0 lacp`. That is a vendor-correct LAG rename, and
the audit knows it: `_canonical_lag_name()` maps both `bond0` and `trk0` to
`LAG0`, so at the sub-key level `lags[].name` and `interfaces[].lag_member_of`
resolve to **preserved**. The bare top-level `lags` key does not get that
equivalence — it compares whole records — which is exactly why `lags` is
recorded `lossy` here while `interfaces[].lag_member_of` is recorded `good`. The
two are consistent, not contradictory.

`/lags/lag/mode` is declared lossy on **both** codecs — AOS-S trunk LACP does
not preserve the active/passive distinction, so a `passive` bundle re-parses as
`active`. The single bundle in this corpus is already `active`, so that
particular collapse is **untested here** and is reported as declared, not
observed.

## What the domain drift really is

`domain` is populated on exactly one cell (`scottlaird-vyos-parser.conf`) and
comes back empty, so the YAML records it `unsupported` — matching the
`aruba_aoss` declaration for `/system/domain`.

The declaration's stated reason does not match the code. It reads *"Render emits
no system domain-name; intent.domain is dropped on migration"*, but
`aruba_aoss/render.py` **does** emit `ip dns domain-name <name>` (added under
finding 12 of `tests/fixtures/real/user_smoke_findings.md`, for an OPNsense
source that was being dropped silently), and the rendered config for that cell
carries `ip dns domain-name internal.sigkill.org` on line 3. What is missing is
the **read-back**: the AOS-S parser has a regex for `ip dns server-address` and
none for `ip dns domain-name`, so the canonical value is empty after the
round-trip.

The disposition is right either way — the domain does not survive the trip — but
the operational advice differs from what the declaration implies. The domain
suffix **is** present in the config you hand the switch; it is the audit's
canonical view that loses it. Recorded here rather than fixed: this file does
not change codecs.

## The clean half

Worth stating plainly, because most of this document is about losses. On this
pair the following are measured clean, not assumed:

- `hostname` — preserved on **13 of 13** cells.
- `interfaces[].ipv4_addresses` / `ipv6_addresses` — **zero** differing across
  45 matched records, 21 and 20 of them populated respectively. This is the
  field the migration most depends on and it is intact.
- `interfaces[].enabled` — zero differing; both administratively-down ports come
  back `disable`.
- `interfaces[].description` — zero differing across the 15 records that carry
  one, including free text with embedded semicolons and spaces, which the AOS-S
  render quotes as `name "…"` and reads back byte-identical. Note for anyone
  arriving from a pair where `vyos` is the **target**: the VyOS renderer rewrites
  embedded double quotes to apostrophes (VyOS rejects embedded quotes in value
  strings, `vyos.dev/T1246`). VyOS is the **source** here, so that rewrite is not
  in play and no description punctuation changes.
- `static_routes` — **7 routes across 4 cells**, all preserved: destination,
  gateway, and the one route carrying `metric: 20`
  (`10.99.0.0/16 → 10.10.10.254`, rendered as `ip route … distance 20`). AOS-S
  declares `/routing/static-route/metric` lossy; on this corpus that path is
  exercised once and survives. No committed route carries a description or a
  VRF, so those two declared-lossy / declared-unsupported paths are untested
  here.
- `snmp.community` / `location` / `contact` — zero differing on the 4 cells that
  carry an SNMP block.
- `dns_servers` — the one populated cell round-trips all three servers.

`snmp.trap_hosts` is recorded `good` on a vacuous measurement and the YAML says
so: the list is empty on both sides of all four SNMP-bearing cells, `vyos`
declares no `/snmp/trap-host` path, and `aruba_aoss` declares it supported.

The SNMPv3 exception is narrow and declared. `snmp.v3_users` drifts on 2 of the
4 SNMP cells, and the drift is confined to two attributes on the two USM records
in the corpus: `engine_id` → `""` (AOS-S declares `/snmp/v3-user/engine-id`
lossy — engineIDs are device-assigned) and `priv_protocol` `aes` → `aes128`
(AOS-S declares `/snmp/v3-user/priv-protocol` lossy). The second is the
declared lossy path running *backwards*: the matrix warns that AOS-S emits
`aes128` as a bare `aes` and loses the key-length designation; here the source
was already bare `aes` and the re-parse *added* `aes128`. User name, group and
auth protocol are preserved on both records. The auth and privacy passphrases
are opaque per-vendor material that the mesh blanks on both sides before
comparing, and they are not reproduced anywhere in this file or the YAML.
