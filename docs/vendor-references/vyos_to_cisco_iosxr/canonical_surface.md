# VyOS → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every loss recorded was additionally re-derived by hand —
`vyos.parse()` → `cisco_iosxr.render()` → `cisco_iosxr.parse()` on each of the
13 fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the codec sources themselves, the measured mesh run, and hand
> round-trips of the committed fixtures. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is a **Linux software router**: a VM or container
gateway with `ethN` NICs, `ethN.NNN` dot1q sub-interfaces, `bondN`
aggregates, `dumN` dummy interfaces and `lo`. The captures are lab and CI
gateways (`wcni-kind-gw0/gw1`, the `pc5-round*` lab topologies), a home /
small-site edge (`houdev`, `scottlaird`) and one synthetic kitchen-sink. Its
input is a curly-brace `config.boot`; set-form input is converted via
`_setform_to_brace` before parsing.

`cisco_iosxr` is a **service-provider edge/core router** — 4-segment interface
names, `Bundle-Ether` aggregates, `BVI`, and a VRF surface whose RD is
harvested from `router bgp`.

The realistic migration is therefore a **software router promoted onto SP
iron**: the routed edge — interface names, descriptions, admin state,
IPv4/IPv6 addressing, static routes, VRF identity and local-user identity — is
the shared surface. The overlay (VXLAN) and the management plane (SNMP) are
not.

## The structural finding: the interface inventory is fully preserved

Anyone arriving here from a pair whose dominant loss was structural should not
assume the same shape. Here the interface plane is intact.

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **55** |
| cells where the interface name set differs | **0** |

VyOS `ethN`, `ethN.NNN` dot1q sub-interfaces, `bondN`, `dumN` and `lo` all
survive the IOS-XR render verbatim — the mesh runs `render()` without port
translation, so the names are carried across unrenamed rather than re-shaped
into IOS-XR 4-segment form.

The consequence is the useful one: **every interface loss on this pair is a
genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than being dragged
down by a vanishing parent. Nothing in the `interfaces[]` block is correlated
drift.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 1 | 0 | 12 |
| dns_servers | 1 | 0 | 12 |
| ntp_servers | 11 | 1 | 1 |
| interfaces[].name | 13 | 0 | 0 |
| interfaces[].description | 7 | 0 | 6 |
| interfaces[].enabled | 13 | 0 | 0 |
| interfaces[].mtu | 1 | 0 | 12 |
| interfaces[].ipv4_addresses | 9 | 0 | 4 |
| interfaces[].ipv6_addresses | 5 | 0 | 8 |
| interfaces[].interface_type | 0 | 13 | 0 |
| interfaces[].lag_member_of | 0 | 1 | 12 |
| vlans[].* | 0 | 1 | 12 |
| static_routes | 4 | 0 | 9 |
| snmp.community | 1 | 3 | 9 |
| snmp.location / snmp.contact / snmp.v3_users | 2 | 2 | 9 |
| snmp.trap_hosts | 4 | 0 | 9 |
| lags | 0 | 1 | 12 |
| local_users[].name / role | 13 | 0 | 0 |
| local_users[].hashed_password | 12 | 0 | 1 |
| vxlan_vnis[].* | 0 | 3 | 10 |
| routing_instances[].name | 1 | 0 | 12 |

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `routing_instances[].description`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface block

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 55 | 55 | empty string → `ianaift:other` (target **gains** a hint) |
| `lag_member_of` | 2 | 2 populated | `bond0` → `Bundle-Ether0` |
| `dhcp_client` * | 3 | 3 populated | `True` → `False` |
| `dhcp_client_v6` * | 1 | 1 populated | `dhcpv6` → empty string |
| `name` / `description` / `enabled` / `mtu` / `ipv4_addresses` / `ipv6_addresses` / `vrrp_groups` | 0 | 55 | — |

\* `dhcp_client` and `dhcp_client_v6` have **no key** in the audited key set;
they are recorded here because they were measured, not because any YAML entry
claims them. See "Two real drifts with no key" below.

Populated-value totals that round-trip unchanged: 15 descriptions, 55 admin
states (53 up, 2 `shutdown`), 1 MTU, 21 IPv4 addresses, 20 IPv6 addresses —
all identical on both sides.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for IOS-XR to lose:

`/system/syslog-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/{host,key}` · `/system/timezone` ·
`/anycast-gateway-mac` · `/vlans/vlan/id` ·
`/interfaces/interface/vrrp-groups/group/*` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}`

Where **both** matrices declare the path unsupported the YAML records
`unsupported` — a symmetric gap in the pair, not a target limitation. That
applies to `timezone`, `dhcp_servers`, `radius_servers`,
`interfaces[].vrrp_groups` and `anycast_gateway_mac`.

Where only the **source** cannot emit it, the YAML records `not_applicable`
and says which side re-authoring belongs on. `syslog_servers` is the clean
example: vyos declares `/system/syslog-server` unsupported while cisco_iosxr
declares it supported, so logging hosts must be re-entered on the target and
the migration report should say so rather than implying IOS-XR cannot hold
them.

Three keys are `not_applicable` because the vyos parser structurally cannot
produce them, verified in the codec source rather than assumed:

- `routing_instances[].description` — `vyos/parse.py` builds VRFs as
  `CanonicalRoutingInstance(name=name)`, name only. Description is always
  empty.
- `raw_sections` — vyos declares `/system/raw-sections/version-banner` lossy
  and its own reason says the trailer is *discarded on parse*, so nothing is
  ever carried into the canonical tree.
- `evpn_type5_routes` — neither declared nor populated on the vyos side;
  `protocols bgp … address-family l2vpn-evpn` is Tier-3 there. cisco_iosxr
  declares `/evpn-type5-routes/route` unsupported in its own right, which is
  moot when the source emits nothing.

## Five findings worth carrying forward

### 1. SNMP is a total block drop

4 of 13 cells populate SNMP (`kitchen_sink`, `metasploit-vyos-config`,
`scottlaird-vyos-parser`, `vyos_forum_snmpv3_user_eq13`). On every one of
them the rendered IOS-XR config contains **zero** lines matching `snmp`, and
the re-parsed `intent.snmp` is `None`. The block does not degrade — it
vanishes.

cisco_iosxr declares `/snmp/community` unsupported with the reason "SNMP parse
+ render is out of the v1 XR scope", and anchors the four
`/snmp/v3-user/{auth-protocol,priv-protocol,priv-passphrase,group}`
declarations to it ("see /snmp/community"). `/snmp/location` and
`/snmp/contact` carry no declaration of their own but ride the same whole-block
scope gap, which is why they are recorded `unsupported` on the measurement
rather than on a path.

Per #436 a vanished record is not lossy, so `snmp.community`, `snmp.location`,
`snmp.contact` and `snmp.v3_users` are `unsupported`.

`snmp.trap_hosts` is `good`, and the reason is worth stating plainly rather
than implying: **no committed cell populates trap hosts**, so an empty source
list matches the absent target block and the comparator sees no drift. It is
an empty-to-empty match, not evidence that trap destinations survive. The
concept-level drop is claimed exactly once, under `snmp.community`.

Two of the four SNMP-carrying cells define an SNMPv3 USM user with auth and
privacy passphrases. Those never reach the target. No passphrase, engine-ID
body or community string value is reproduced in this file or the YAML — only
the fact that the records exist and where they stop.

### 2. VXLAN VNIs drop outright

3 of 13 cells carry exactly one VXLAN VNI each (`kitchen_sink` vni 10100,
`wcni-kind-gw0` and `wcni-kind-gw1` vni 10). After the round-trip all three
lists are empty, and the rendered config contains no `nve`, `vxlan` or `vni`
line anywhere.

cisco_iosxr declares `/vxlan-vnis/vni`, `/vxlan-vnis/source-interface` and
`/vxlan-vnis/udp-port` unsupported — "IOS-XR VXLAN (NCS 5500 / 540 `nve`
interfaces) is rare in the SP corpus; no canonical demand surfaced.
Parse-and-ignore in v1."

The record-level drop is claimed **once**, on `vxlan_vnis[].vni`.
`vxlan_vnis[].vlan_id` and `vxlan_vnis[].mcast_group` are `good`: they drift
only because their parent record vanished, which is the same single mechanism,
and a loss recorded on them could never be evidenced independently. Two
further facts support that reading rather than merely permitting it —
`mcast_group` is empty on all three source records, and `vlan_id` is not
operator-authored at all but synthesised by the vyos parser from the VNI
(`((vni - 1) % 4094) + 1`), a derivation its own comment calls out.

### 3. The LAG surface is renamed, not lost — and it is ONE mechanism

`kitchen_sink` is the only cell with an aggregate. The round-trip is:

| | source | target |
|---|---|---|
| `lags[0].name` | `bond0` | **`Bundle-Ether0`** |
| `lags[0].members` | `eth4`, `eth5` | `eth4`, `eth5` |
| `lags[0].mode` | `active` | `active` |
| `interfaces[].lag_member_of` on `eth4`/`eth5` | `bond0` | **`Bundle-Ether0`** |

Nothing vanishes: the LAG record survives with its members and its LACP mode,
and both member ports keep their membership pointer. What changes is the
**name**. The mechanism is visible in the render — `interface eth4 / bundle id
0 mode active` — and in `cisco_iosxr/parse.py`, which reconstructs the
aggregate name as `f"Bundle-Ether{int(bm.group(1))}"`.

Both keys are `lossy`, not `unsupported`, precisely because the record
survives (#436 cuts the other way here than it does for `snmp` and
`vxlan_vnis`).

**`lags` and `interfaces[].lag_member_of` are one mechanism, not two
independent findings.** Neither is cited as evidence for the other; each is
recorded where it is measured.

The operator-visible consequence is worth one line: the target-side tree ends
up carrying an interface still named `bond0` (it renders as a plain
`interface bond0` stanza with the aggregate's description and IPv4 address)
alongside a LAG record named `Bundle-Ether0`. The aggregate's L3 and its
identity no longer agree by name. Rename the bundle and re-home its addressing
before cutover.

### 4. `interface_type` drifts in the *gain* direction

This is the widest drift on the pair — all 55 records on all 13 cells — and
reading it as "IOS-XR loses the type hint" would be backwards.

- The **source** value is the empty string on **all 55 records**. The vyos
  parser never populates `interface_type`: the strings `interface_type` and
  `ianaift` do not appear anywhere in `netcanon/migration/codecs/vyos/*.py`.
- The **target** value is `ianaift:other` on all 55. `cisco_iosxr/parse.py`
  infers a type from the interface-name prefix via `_TYPE_HINTS`, and `ethN`,
  `bondN`, `dumN` and `lo` match no IOS-XR prefix, so `_infer_type` returns its
  fallback, `ianaift:other`.

So the round-trip **invents** a hint the source never asserted, and it is the
uninformative one. No forwarding state is affected; the record, its addressing
and its admin state are untouched. That is why the key is `lossy` and not
`unsupported`.

Both matrices already declare `/interfaces/interface/config/type` lossy.

**Standing observation, not fixed here:** the vyos declaration's reason claims
the codec "infers it from the interface-name shape (`ethN` → ethernetCsmacd,
`lo`/`dumN` → softwareLoopback, `bondN` → ieee8023adLag)". Measured, it does
not — 0 of 55 records carry a type, and the field is never assigned in the
codec. That is a matrix-vs-code mismatch on the vyos side, not a pair-specific
fact, and belongs to a codec change rather than to this file.

### 5. The VLAN list drifts by *gaining* records

VyOS has no VLAN database — it expresses tagging as an `ethN.NNN`
sub-interface — and its matrix declares `/vlans/vlan/id` unsupported. Source
`vlans` is empty on all 13 cells.

On `kitchen_sink`, the IOS-XR render emits `encapsulation dot1q 100` and
`encapsulation dot1q 200` on `eth1.100` / `eth1.200`, and the IOS-XR parser
materialises one bare `CanonicalVlan` per distinct tag — its own docstring
says so: "IOS-XR routers have no classic `vlan N / name X` stanza — VLAN ids
appear only on sub-interfaces via `encapsulation dot1q <vid>`. Each distinct
tag becomes a bare `CanonicalVlan`."

Result: 0 VLAN records in, **2** out (ids 100 and 200, everything else empty).
The drift is real and comparator-visible, but it is in the *adding* direction
and the two ids are faithful re-derivations of tags the source did carry on
its sub-interfaces. That is why `vlans[].id` is `lossy` — it warns, it stays
compatible — rather than `unsupported`, which would claim a vanished concept
that did not vanish.

`vlans[].name`, `vlans[].ipv4_addresses`, `vlans[].untagged_ports`,
`vlans[].tagged_ports` and `vlans[].description` are `good`. They drift only
because the parent list changed length — the same single mechanism, already
claimed by `vlans[].id` — and every one of them is empty on both sides of
every cell. Recording a second loss on any of them would double-count one
event and could never be evidenced.

## `ntp_servers`: the one drift that is a source-side artifact

11 of 13 cells preserve their NTP servers exactly; 1 cell is trivially empty.
The single drifting cell is `houdev_vyos_dhcpv6_pd_client.conf`, whose raw
config writes the servers with an inline empty brace block:

```
server         time1.vyos.net { }
```

The vyos brace parser carries the whole remainder into the canonical value, so
the source-side list is `['time1.vyos.net { }', 'time2.vyos.net { }',
'time3.vyos.net { }']`. The IOS-XR render emits `server time1.vyos.net { }`
verbatim and its `_NTP_SERVER_LINE_RE` captures only the first token, so the
target-side list is the clean `['time1.vyos.net', 'time2.vyos.net',
'time3.vyos.net']`.

All three server hostnames survive, and the target value is the *usable* one.
What disappears is a trailing ` { }` token that the vyos parser should not
have attached in the first place. The key is recorded `lossy` because the
comparator sees a real value difference on that cell and the audit must not
paper over it — but the cause is a source-side parse artifact, not an IOS-XR
drop of operator-authored data.

## Credential material

`local_users` is clean at the canonical level and the YAML records all three
keys `good`, on measurement:

- **17 user records across 13 cells; zero accounts dropped.** Every name
  present on the source is present on the target.
- **`role` preserved on 17 of 17** — `admin` in, `admin` out.
- **`hashed_password` preserved byte-identical on all 16 populated records**
  (the 17th, `netadmin` on `houdev`, has no password on either side). All 16
  are SHA-512 crypt (`$6$`).

No hash body is reproduced in this file or in the expectation YAML — only the
crypt-scheme marker and the fact of preservation. Per `AGENTS.md`, password
hashes are operator-traceable even when they are hashes, and a document that
quotes the value it describes defeats its own redaction.

**One operational caveat that does not change the disposition.** The IOS-XR
render emits each account as:

```
username <name>
 group admin
 secret 0 <sha-512 crypt hash>
```

`secret 0` is the type-0 marker. `cisco_iosxr/render.py` documents the
fallback explicitly — "the hash is preserved with its type-digit prefix (parse
stored `10 $6$…`); a bare value renders as the type-0 (plaintext-marker)
form" — and vyos-origin hashes carry no IOS-XR type digit, so every account
lands on that branch. The canonical value round-trips intact because
`_fmt_secret` stores type-0 payloads bare, which is why the key is honestly
`good`. But the *rendered artifact* labels a hash as a cleartext secret. Do
not paste the render at a device and expect the accounts to work: set
passwords on the target before cutover.

## Two real drifts with no key

Both are recorded here because they were measured. Neither is claimed in the
YAML, because the audited key set has no key for them — inventing one would
put an unevidenceable entry in front of the ratchet.

1. **`interfaces[].dhcp_client` — `True` → `False` on 3 records / 3 cells**
   (`houdev` `eth0`, `kitchen_sink` `eth2`, `scottlaird-vyos-parser` `eth5`),
   and **`interfaces[].dhcp_client_v6` — `dhcpv6` → empty on 1 record**
   (`houdev` `eth0`). The IOS-XR render emits no address line at all for a
   DHCP-addressed interface, so the interface arrives on the target with its
   name, description and admin state but no addressing method. On a WAN-facing
   port that is the difference between an uplink and a dead port. Re-author
   the address method by hand.

2. **`local_users[].privilege_level` — 15 → 1 on all 17 records.** The vyos
   side declares `/local-users/user/privilege-level` lossy already ("VyOS
   `system login user` accounts have no numeric privilege"), and the IOS-XR
   side completes the round-trip badly: the render emits `group admin`
   (the canonical `role` verbatim), and `cisco_iosxr/parse.py` maps only
   `root-lr` and `root-system` to privilege 15 — every other group maps to 1,
   which its own comment flags as lossy. `role` still reads `admin`, so an
   operator diffing roles sees nothing wrong while the numeric privilege has
   silently dropped to the lowest level. Check privilege on the target, not
   just role.

## One drift-shape reading that is wrong

A mechanical "did the field drift?" pass reports `local_users` as drifting on
**all 13 cells** — the widest drift on the pair after `interfaces`. Read
naively, that says the migration mangles every account.

It does not. Names, roles and password hashes are preserved on all 17 records.
The entire 13-cell drift is carried by one unkeyed sub-field,
`privilege_level`, described above. All three keyed `local_users[].*` entries
are `good`, and that is a measurement, not an optimism.
