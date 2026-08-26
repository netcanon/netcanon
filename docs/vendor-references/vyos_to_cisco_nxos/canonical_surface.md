# VyOS → Cisco NX-OS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__cisco_nxos.yaml`.

**Source of every number here:** a 13-cell round-trip over the committed VyOS
corpus — `vyos.parse()` → `cisco_nxos.render()` → `cisco_nxos.parse()` on each
of the 12 real captures under `tests/fixtures/real/vyos/` plus
`tests/fixtures/synthetic/vyos/kitchen_sink.conf`. Per-key dispositions were
resolved through the audit's own `actual_disposition()` rather than inferred
from the drift shape, so this file and the ratchet agree by construction, and
every loss recorded below was additionally re-derived by hand from the
rendered NX-OS text — no claim here rests on a drift count alone.

- Fixture cells: **13**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured round-trip, and the rendered NX-OS text of the
> committed fixtures. Where a disposition rests on a declaration rather than
> an observed round-trip, the YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is a **Linux-based software router** — lab, virtual or
small edge. Its interface vocabulary is the kernel's (`eth0`..`eth7`, `lo`,
`dum0`, `bond0`, `eth1.100`), its local-user passwords are bare `$6$` SHA-512
crypt strings, and its VLANs exist only as `vif <vid>` sub-interfaces.
`cisco_nxos` is a **DC leaf/spine**: `Ethernet1/1` / `loopback0` / `Vlan10` /
`port-channel1` / `nve1`, a real VLAN database, and VXLAN/EVPN.

The realistic migration is a VyOS edge or lab router re-homed onto a Nexus, so
the shared surface is the **routed edge plus the overlay** — addressing, admin
state, MTU, static routes, SNMP, VRF identity, the VXLAN VNI-to-VLAN binding
and user identity. There is no campus L2 surface on the VyOS side to migrate:
`vyos` declares `/vlans/vlan/id` unsupported outright.

## The structural finding — the interface inventory is fully preserved

Anyone arriving here from `vyos_to_arista_eos/canonical_surface.md` should read
this section before assuming the same shape. There the inventory **shrinks**,
55 records in and 46 out on 6 of 13 cells, because the EOS render elides
content-free VyOS stubs — so `interfaces[].name` carries a structural loss and
every interface sub-field inherits that one signal.

**Here nothing is elided.**

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **55** |
| cells where the interface name set differs | **0** |

The NX-OS render emits `interface eth0`, `interface lo`, `interface dum0`,
`interface bond0` and `interface eth1.100` under their VyOS names verbatim, and
the NX-OS parser reads every one of them back. Bare, content-free stubs
(`interface eth3` with nothing but `shutdown`) survive too.

The consequence is the useful one: **every interface loss on this pair is a
genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than being dragged
down by a vanishing parent. Nothing in the interface block is correlated drift.

The one structural movement on this pair goes the *other* way: on 3 cells the
target gains a VLAN record the source never had. See "The VLAN registry is
synthesised, not lost" below.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 1 | 0 | 12 |
| dns_servers | 1 | 0 | 12 |
| ntp_servers | 11 | 1 | 1 |
| interfaces (whole field) | 0 | 13 | 0 |
| vlans | 0 | 3 | 10 |
| static_routes | 4 | 0 | 9 |
| snmp | 2 | 2 | 9 |
| lags | 0 | 1 | 12 |
| local_users | 0 | 13 | 0 |
| vxlan_vnis | 1 | 2 | 10 |
| routing_instances | 1 | 0 | 12 |

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`,
`dhcp_servers`, `radius_servers`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`, and every interface's
`vrrp_groups`.

`interfaces` and `local_users` drift on **every** cell, which looks alarming
until the sub-field walk is read. Both are single-attribute effects:

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 55 | 55 | empty string → `ianaift:other` |
| `lag_member_of` | 2 | 2 populated | `bond0` → `port-channel0` |
| `name` / `description` / `enabled` / `mtu` / `ipv4_addresses` / `ipv6_addresses` / `vrrp_groups` | 0 | 55 | — |

Populated counts for the clean sub-fields, so the `good` verdicts are not
mistaken for untested ones: `description` on **15** records across 7 cells,
`ipv4_addresses` on **21** records across 9 cells, `ipv6_addresses` on **20**
records across 5 cells, `mtu` on **1** record, and **2** admin-down records —
all preserved, none drifting.

### Per-record detail behind the local-user drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `privilege_level` | 16 | 16 surviving | `15` → `1` |
| whole record | 1 | 17 | account dropped |
| `name` / `role` / `hashed_password` | 0 | 16 surviving | — |

`privilege_level` is **not** one of the audited keys on this pair, so it gets no
disposition of its own — but it is the reason the whole `local_users` field
reads as drifted on 12 otherwise-clean cells, and it matters operationally.
Both matrices declare `/local-users/user/privilege-level` lossy. The mechanism
is visible in the code: `cisco_nxos` renders the canonical `role` verbatim, and
its parser maps a role back to a privilege only for `network-admin` /
`vdc-admin`. VyOS accounts carry the role string `admin`, which is in neither
set, so all 16 surviving accounts land on privilege 1.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for NX-OS to lose:

`/system/syslog-server` · `/interfaces/interface/vrrp-groups/group/*` ·
`/vlans/vlan/id` · `/anycast-gateway-mac` ·
`/routing-instances/instance/l3-vni` · `/routing/static-route/vrf` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan,dot1q-vlan}`

Those that map onto an audited key are recorded `not_applicable`, not
`unsupported`, and the distinction is operational: for most of them
**cisco_nxos declares the field supported** — syslog servers, the anycast
gateway MAC, per-VRF static routes, the whole switchport surface — and it
declares the VRRP group *lossy* (it renders every FHRP group as HSRP). Re-authoring
any of them on the Nexus will stick, and a migration report should say so
rather than implying the target cannot hold them.

Three fields are **symmetric** gaps, where both codecs declare the path
unsupported. Those are recorded `unsupported`, because the concept dies in
transit no matter which side you blame:

- `/system/timezone`
- `/dhcp-servers/pool`
- `/radius-servers/server/host` and `/radius-servers/server/key`

The RADIUS one deserves a sentence of its own: even if the server list had
migrated, `/radius-servers/server/key` is declared unsupported on both sides,
so the shared secret could never have travelled with it.

Two of these gaps are **not** untested empty fields, and a migration report
should not present them as such. `system time-zone` is set in **3 of the 13**
raw VyOS configs, and `scottlaird-vyos-parser.conf` carries a real remote
syslog host under `system syslog host <ip>`. Both are discarded by the *source*
parser before NX-OS is ever involved, so the canonical field reads empty on
both sides and the drift counters show nothing. The operator still loses them.

`routing_instances[].description` is the quiet asymmetry in the other
direction: `cisco_nxos` declares it **supported**, `vyos` declares no path for
it at all and emits none, so the field is `not_applicable` here and would need
re-checking on any pair where VyOS is the target.

## Four findings worth carrying forward

### 1. The interface type hint is invented on the target, not lost

`interfaces[].interface_type` drifts on **55 of 55 records, on all 13 cells** —
the single largest drift signal on the pair. The direction is the surprise:

```
source: ""   ->   target: "ianaift:other"
```

The source side is empty on every record measured. `vyos` declares
`/interfaces/interface/config/type` lossy and describes a name-shape inference
(`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback, `bondN` →
ieee8023adLag); on this corpus that inference does not populate the parsed
value, so nothing is carried into the render. `cisco_nxos` declares the same
path lossy and re-derives the hint from the rendered name prefix — Ethernet,
loopback, Vlan, port-channel, nve, mgmt. **No VyOS name matches any of those
prefixes**, `lo` included (NX-OS wants `loopback`), so every record falls
through to `ianaift:other`.

So the canonical value is not preserved, which is what the audit measures and
why the key is `lossy` — but no operator intent is destroyed. What arrives is a
type hint the source never asserted, uniformly wrong in the same harmless way.
Treat it as noise in a diff, not as a migration risk, and do not let its size
crowd out the two findings below.

### 2. The LAG is renamed, and its addressing is left behind

One cell carries a bundle (`kitchen_sink.conf`) and it drifts. The record does
**not** vanish: 1 LAG in, 1 LAG out, members `eth4` and `eth5` intact, mode
`active` intact. What drifts is the record's identity, `bond0` →
`port-channel0`, and the same rename shows up on the two member interfaces'
`lag_member_of`.

The rename itself is correct — `port-channel<N>` is NX-OS's native vocabulary.
The consequence is what the record count hides. In the rendered NX-OS text:

```
interface bond0
  description server lag
  no shutdown
  no switchport
  ip address 10.50.0.1/24
...
interface eth4
  no shutdown
  channel-group 0 mode active
interface eth5
  no shutdown
  channel-group 0 mode active
```

There is **no `interface port-channel0` stanza anywhere in the render.** The
bundle's L3 and description stay on a stanza called `bond0`, which on a real
Nexus is an ordinary interface with a foreign name, while the members join a
`port-channel0` that is never configured. Re-home the bundle's addressing onto
`port-channel0` by hand before cutover.

`lags` and `interfaces[].lag_member_of` are **one mechanism observed at two
measurement sites, not two independent findings.** Neither is cited as evidence
for the other; each is recorded where it is measured. Both are `lossy` and not
`unsupported`, because nothing vanishes — `unsupported` is reserved for the
record that cannot exist on the target at all (#436), and NX-OS models LAGs
fully (`/lags/lag/{name,members,mode}` all declared supported).

### 3. A passwordless account disappears at re-parse

17 local-user records across the 13 cells; **16 survive with name, role and
password hash byte-identical**, and 1 disappears. The rule is clean and
predictable:

| source account | outcome |
|---|---|
| carries a `$6$` SHA-512 crypt hash (16 records) | survives, hash preserved verbatim |
| carries an empty `encrypted-password` (1 record) | **account dropped entirely** |

The dropped account is `netadmin` on `houdev_vyos_dhcpv6_pd_client.conf`, whose
VyOS stanza sets `encrypted-password ""`. It is the only account on that cell,
so the round-tripped user list is empty.

The mechanism is an asymmetry between the NX-OS render and its own parser, and
it is worth stating precisely because "the render dropped it" would be wrong.
The render **does** emit the account:

```
username netadmin role admin
```

The NX-OS username pattern requires a `password <type> <hash>` clause between
the name and the role, so that line matches nothing on re-parse and the account
is silently gone. Diff the source account list against the target before
cutover; a silently missing admin account is how a migration locks you out.

This is recorded `lossy` rather than `unsupported`: `cisco_nxos` declares
`/local-users/user/name` supported and does emit users, so it is a partial
record loss inside a concept the target models — not the concept-level gap that
forces `unsupported` under #436.

`local_users[].role` and `local_users[].hashed_password` are `good`, and
deliberately so. Both are preserved on every record that survives — zero drift
on any cell. Those keys measure what happens to the *value* when the record
survives, and the answer is: nothing. The one account that vanishes is
accounted for once, under `local_users[].name`. Recording the same
disappearance three times would triple-count one loss.

One caveat that belongs to the *rendered text* rather than to the canonical
comparison, and so changes no disposition: the surviving hashes are emitted
under NX-OS's **type-0 (cleartext) marker**, in the form
`username <name> password 0 <$6$ crypt body> role admin`. The canonical value
round-trips exactly — the parser strips the type digit again — but a Nexus
reading that line would take the crypt string itself as the plaintext password.
The fidelity harness scores preservation, not target-syntax validity. Set
passwords on the target before cutover and treat no migrated account as having
a working credential.

### 4. The VLAN registry is synthesised, not lost

`vlans[].id` is the key that carries this pair's structural signal, and the
signal points the opposite way from every other structural finding in the mesh:
the record count goes **up**.

`vyos` declares `/vlans/vlan/id` unsupported — VyOS has no VLAN database, only
`vif <vid>` sub-interfaces — so the source `vlans` list is empty on all 13
cells. On the 3 cells that carry a VXLAN VNI, the NX-OS render emits the VNI's
L2 binding as a VLAN stanza:

```
vlan 1912
vlan 1912
  vn-segment 10100
```

and the re-parse yields exactly one VLAN record carrying **only** an `id`. The
ids match each cell's `vxlan_vnis[].vlan_id` one for one: 10, 10 and 1912.
Name, description, port membership and addressing are empty on every one, which
is what grounds the five `good` verdicts on the other `vlans[].*` keys — when
the record exists, none of those values is lost, because none was ever carried.

`vlans[].id` is `lossy`, not `unsupported`: nothing vanishes, so the #436 rule
does not apply, and `lossy` — warn, stay compatible — is the honest severity
for a target that adds a correct VLAN the source never declared. The duplicated
`vlan 1912` line is a render artefact visible in the text above; it is worth an
eyeball on the generated config, and it does not affect what re-parses.

The `vif` sub-interfaces themselves are unaffected and do **not** produce VLAN
records: `interface eth1.100` renders with `encapsulation dot1q 100` and
round-trips as an interface, which is where the operator should expect to find
their tagged L3.

## Overlay: what survives and what quietly changes

`vxlan_vnis[].vni` and `vxlan_vnis[].vlan_id` are preserved on all 3 cells that
populate them (10/10, 10/10, 1912/10100), which is why both are `good` here
even though `cisco_nxos` declares `/vxlan-vnis/vni` lossy for its per-VNI
sub-flags. Two adjacent sub-fields that are **not** audited keys on this pair do
drift on 2 cells each, and an operator should know:

- `source_interface`: empty → `loopback0`. The NX-OS NVE render supplies a VTEP
  source the VyOS `vxlan` netdev did not name.
- `udp_port`: `8472` → `4789`. VyOS's Linux-legacy VXLAN port is dropped and
  re-parses as the IANA default. `cisco_nxos` declares `/vxlan-vnis/udp-port`
  lossy with exactly this reason. If the far-end VTEPs are still on 8472, the
  overlay will not come up.

## SNMP

Four cells populate an SNMP block. The community string is preserved
byte-for-byte on all **3** cells that set one; location and contact on both
cells that set them. So all three keys are `good` on measurement rather than on
declaration. No community string is reproduced here — it is a shared secret.

The SNMPv3 USM record drifts on both cells that carry one, and the drift is a
single token: the privacy protocol `aes` is rendered as NX-OS's `priv aes-128`
and re-parses as `aes128`. Everything else about the user survives — name,
group, auth protocol, engine ID, and both key blobs verbatim. That is why
`snmp.v3_users` is `lossy` and not `unsupported`: the USM record does not
vanish, its cipher discriminator gets more specific.

Both codecs declare the auth and privacy passphrase paths lossy in their own
right, and the mesh blanks those two sub-fields before comparing precisely
because a localized key never ports byte-for-byte across vendors. Re-key every
SNMPv3 user on the Nexus regardless of what the diff says.

`snmp.trap_hosts` is `good` with no populated round-trip behind it: `vyos`
declares no `/snmp/trap-host` path and emits none on any cell, while
`cisco_nxos` declares it supported. Stated plainly rather than implied.

## Credential material

No hash body, community string, engine ID or USM key is reproduced in this file
or in the expectation YAML — only the crypt-scheme marker (`$6$`), the NX-OS
type digit, and the algorithm tokens (`sha`, `aes` → `aes128`) are described.
Per `AGENTS.md`, password hashes and shared secrets are operator-traceable even
when hashed, and a document that quotes the value it describes defeats its own
redaction.

## Two drift-shape readings that are wrong

**"`interfaces` drifts on 13 of 13 cells, so the interface surface is broken."**
It is not. 55 records in, 55 out, identical names, and every attribute an
operator actually configured — description, addressing, MTU, admin state —
survives on every record. The 13-cell drift is one uniform, harmless
type-hint fabrication (finding 1) plus a two-record LAG rename on one cell.

**"`local_users` drifts on 13 of 13 cells, so credentials are being mangled."**
Also no. The hashes round-trip verbatim on all 16 surviving records. What
drifts on 12 of those cells is `privilege_level`, an unaudited numeric that both
matrices already declare lossy, and on the thirteenth a single passwordless
account disappears (finding 3). The real credential hazard on this pair is not
in the canonical diff at all — it is the type-0 cleartext marker in the rendered
text.

## VyOS-as-source note

The VyOS render's free-text rewrite — it replaces embedded double quotes with
apostrophes, because VyOS rejects embedded quotes in value strings
(vyos.dev/T1246) — is a **target-side** behaviour and does not apply to this
pair, where VyOS is the source. It is mentioned only to head off the wrong
diagnosis: `interfaces[].description` shows zero drift here across 15 populated
records on 7 cells, and none of those 15 strings contains a quote or an
apostrophe to begin with.

The one source-side parser artefact that does surface is on NTP.
`houdev_vyos_dhcpv6_pd_client.conf` writes its servers as one-line empty-body
blocks (`server         time1.vyos.net { }`); the VyOS brace parser captures the
whole token run, so the canonical value is `time1.vyos.net { }`. The NX-OS
render emits that verbatim and the NX-OS parser reads only the first token after
`ntp server`, returning the clean `time1.vyos.net`. All three hostnames are
present on both sides, in order — the text survives, the stray brace pair does
not, and the target value is the more correct of the two. It is still recorded
as a loss, because the audit compares canonical strings and this one is not
preserved.
