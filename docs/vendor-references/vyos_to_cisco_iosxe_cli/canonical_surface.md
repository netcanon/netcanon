# VyOS → Cisco IOS-XE (CLI): measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__cisco_iosxe_cli.yaml`.

**Source of every number here:** per-key dispositions were resolved through the
audit's own `actual_disposition()`, with the reconciler's `STRUCTURAL_ONLY`
collapse replayed, so this file and the ratchet agree by construction. Every
number below was additionally re-derived by hand — `vyos.parse()` →
`cisco_iosxe_cli.render()` → `cisco_iosxe_cli.parse()` over each of the 13
committed fixtures — so no claim rests on the drift shape alone.

- Fixture cells: **13** (12 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

This is the **last blind codec** in the mesh audit. With it, every codec has
cross-vendor expectation coverage.

## Device-class framing

`vyos` in this corpus is a **Linux-based software edge router**: Debian-style
interface names (`eth0`…`eth5`, `lo`, `bond0`), a curly-brace `config.boot`,
IPv4+IPv6 dual-stack addressing, a handful of static routes, one VRF, and a
small VXLAN netdev surface. `cisco_iosxe_cli` is a **classic enterprise
branch/campus router** parsed from `show running-config` text.

The shared surface is the **routed edge** — interface addressing, admin state,
static routes, VRF identity, SNMP and local users. Neither side is running a
campus L2 VLAN database on this corpus, and the VyOS parser does not emit
canonical VLAN records at all.

The headline for this pair is unusual and worth stating up front: **this is one
of the cleanest pairs in the mesh.** Addressing, descriptions, admin state,
MTU, static routes, SNMP scalars, VRF identity and user credentials all
round-trip with **zero** drift. The six losses are narrow and each has a
single, identified mechanism.

## The structural finding — an empty-record prune, not a naming collapse

The interface inventory shrinks, but not in the way the drift shape suggests.

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **46** |
| records that vanish | **9** |
| cells where the interface name set differs | **5** of 13 |
| surviving records whose **name** was rewritten | **0** |

VyOS names pass through the IOS-XE CLI render **verbatim** — `eth0`, `eth1`,
`eth5` come back as `eth0`, `eth1`, `eth5`. The render does *not* re-shape them
into `GigabitEthernet0/0`. Nothing is lost to renaming.

What vanishes is **attribute-free records**. The mechanism was tested
falsifiably: classify every source record as *bare* (no IPv4, no IPv6, no
description, no MTU, no VRF, no LAG membership, no DHCP client, not shut, no
VRRP) and compare against what survives.

| class | count | outcome |
|---|---|---|
| vanished **and** bare | 9 | consistent with the hypothesis |
| vanished but **not** bare | **0** | would have falsified it |
| survived but bare | **0** | would have falsified it |

The IOS-XE CLI render emits an `interface <name>` stanza only when there is
something to write inside it, so a record with no attributes produces no text
and the re-parse never sees it.

The control case makes this conclusive. `lo` is among the vanished records on
five cells — which invites the wrong reading, "loopbacks are dropped". On
`kitchen_sink.conf`, `lo` carries one IPv4 and one IPv6 address, and it
**survives**. It is the only `lo` in the corpus that carries any address, and
it is the only `lo` that survives. The prune is attribute-driven, not
name-driven.

Vanished records, in full: `eth1` and `lo` (`metasploit-vyos-config.conf`);
`eth2`, `eth3`, `eth4` and `lo` (`scottlaird-vyos-parser.conf`); `lo`
(`vyos_forum_snmpv3_user_eq13.conf`, `wcni-kind-gw0.conf`,
`wcni-kind-gw1.conf`).

**Operationally this is close to harmless** — no configured state is lost,
because the pruned records had none. It is recorded `lossy` rather than
`unsupported` because the target plainly models interfaces: 46 of 55 records
survive with every attribute intact. It is recorded rather than waved through
because a port that exists in the source inventory and not in the target
inventory is a real difference an operator should see before cutover.

## Per-field measurement (13 cells)

Counts are **name-matched records** across the whole corpus (46 interface
records survive to be matched; 16 local-user records; 7 static routes).

| key | populated (source) | drift | disposition |
|---|---|---|---|
| `hostname` | 13 cells | 0 | good |
| `domain` | 1 cell | 0 | good |
| `dns_servers` | 1 cell | 0 | good |
| `ntp_servers` | 12 cells | **1 cell** | lossy |
| `interfaces[].name` | 55 records | **9 records vanish / 5 cells** | lossy |
| `interfaces[].description` | 15 records | 0 | good |
| `interfaces[].enabled` | 44 records | 0 | good |
| `interfaces[].mtu` | 1 record | 0 | good |
| `interfaces[].ipv6_addresses` | 20 records | 0 | good |
| `interfaces[].ipv4_addresses` | 21 records | 0 | good |
| `interfaces[].interface_type` | 0 records | **46 of 46 records** | lossy |
| `interfaces[].lag_member_of` | 2 records | rename, see below | good |
| `interfaces[].vrrp_groups` | 0 records | 0 | good |
| `static_routes` | 4 cells / 7 routes | 0 | good |
| `snmp.community` | 3 cells | 0 | good |
| `snmp.location` | 2 cells | 0 | good |
| `snmp.contact` | 2 cells | 0 | good |
| `snmp.trap_hosts` | 0 cells | 0 | good |
| `snmp.v3_users` | 2 cells | **2 cells** | lossy |
| `lags` | 1 cell | **1 cell** | lossy |
| `local_users[].name` | 17 records | **1 record / 1 cell** | lossy |
| `local_users[].role` | 16 matched | 0 | good |
| `local_users[].hashed_password` | 16 matched | 0 | good |
| `vxlan_vnis[].vni` | 3 cells | 0 | good |
| `vxlan_vnis[].vlan_id` | 3 cells | 0 | good |
| `vxlan_vnis[].mcast_group` | 0 cells | 0 | good (declared) |
| `routing_instances[].name` | 1 cell | 0 | good |

Trivially empty on all 13 cells: `timezone`, `syslog_servers`, all six
`vlans[].*` keys, `dhcp_servers`, `radius_servers`, `evpn_type5_routes`,
`routing_instances[].description`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

## Correlated drift, isolated once

Five of the thirteen cells change interface-record count. On those cells the
comparator cannot align records, so **every** `interfaces[].*` sub-field
reports drift for that one reason. That signal is claimed exactly once, by
`interfaces[].name`, which is where the records actually vanish.

The other interface sub-fields are recorded `good` because they measure what
happens to the **value when the record survives** — and on all 46 surviving
records, `description`, `enabled`, `mtu`, `ipv4_addresses`, `ipv6_addresses`
and `vrrp_groups` drift **zero** times. Recording a loss on any of them would
count one disappearance up to seven times.

`interfaces[].interface_type` is the exception, and legitimately so: it drifts
on all 46 *surviving* records, on every cell including the eight with no
structural change. Its measurement stands on its own.

## Findings worth carrying forward

### 1. `interface_type` drifts in the fail-OPEN direction

This is a loss of *agreement*, not a loss of data, and the distinction matters
enough to state plainly.

| direction | records |
|---|---|
| source empty → target populated | **46** |
| source populated → target empty | **0** |
| both populated, values differ | **0** |

Every one of the 46 drifting records has the same shape: the VyOS parser emits
`interface_type = ""`, and the IOS-XE CLI re-parse manufactures
`"ianaift:other"` from the interface name. **Nothing the source carried was
dropped** — a value the source never had was invented.

It is recorded `lossy` because the canonical value after the round-trip is not
the canonical value before it, and both matrices already declare
`/interfaces/interface/config/type` lossy on their own merits — `vyos` because
it does not derive a type from a Linux netdev name, `cisco_iosxe_cli` because
its CLI parser "infers interface type from the name prefix … but cannot detect
all IANA types". `eth0` matches no IOS-XE prefix, so it falls through to
`ianaift:other`.

It is **not** `unsupported`: no interface record, address or admin state is
affected. Do not read this row as "the migration lost the interface types" —
there were none to lose.

### 2. A passwordless account disappears, and every surviving secret lands behind the cleartext marker

Two separate facts about the same 17 user records, both measured.

**The record loss.** 17 local-user records across 13 cells; **16 survive**.
The single loss is `netadmin` on `houdev_vyos_dhcpv6_pd_client.conf` — the one
account in the corpus with **no** password. The render emits
`username netadmin privilege 15 nopassword`; the IOS-XE CLI re-parser does not
recognise the `nopassword` form, so the account is not recovered. It is the
only cell where the user list changes length.

This is recorded `lossy`, not `unsupported`: `cisco_iosxe_cli` emits
`username` lines on **all 13 cells** and 16 of 17 accounts round-trip with
`role` and credential intact. It is a partial record loss inside a concept the
target models, not a concept-level gap.

`local_users[].role` and `local_users[].hashed_password` are `good`, and
deliberately so: on all 16 matched records both drift **zero** times. Those
keys measure the value when the record survives. The one disappearance is
accounted for once, under `local_users[].name`.

**The deployability caveat**, which is not a fidelity loss and is not scored as
one. 16 of the 17 source accounts carry a SHA-512 crypt secret (scheme marker
`$6$`). The IOS-XE CLI render places every one of them behind
`secret 0` — and on IOS-XE, `secret 0` is the **cleartext** marker. The
canonical round-trip is clean because the re-parser reads the same string back,
so `hashed_password` is genuinely `good`. But a real IOS-XE box fed that line
would treat the crypt-hash text as a literal plaintext password. Set passwords
on the target before cutover rather than trusting the rendered `username`
lines.

### 3. The one NTP drift is a source-side parse artifact the round-trip cleans

`ntp_servers` is populated on 12 of 13 cells and drifts on exactly one:
`houdev_vyos_dhcpv6_pd_client.conf`.

That fixture uses the VyOS 1.4-era `server <host> { }` form — a server with an
empty options block on the same line:

```
server         time1.vyos.net { }
```

The VyOS parser captures the brace residue as part of the hostname, producing
canonical values `time1.vyos.net { }`, `time2.vyos.net { }`,
`time3.vyos.net { }`. The render passes that through
(`ntp server time1.vyos.net { }`) and the IOS-XE CLI re-parse takes the first
whitespace-delimited token, yielding the clean `time1.vyos.net`.

So the canonical value differs, which is why the key is `lossy` — but the
direction is favourable: **the round-trip strips a defect the source
introduced**, and the three NTP servers are correct on the target. The other 11
populated cells use the bare `server <host>` form and round-trip untouched.

The underlying `vyos` parser bug is real and belongs to a codec change, not to
this file: the brace-block suffix should not survive into
`CanonicalIntent.ntp_servers`. Recorded here so the next reader does not
re-hunt it as an IOS-XE rendering problem.

### 4. The LAG rename is one mechanism, recorded once

One cell (`kitchen_sink.conf`) carries a LAG. It **survives** the round-trip
with its members and mode intact, and is renamed:

| | source | target |
|---|---|---|
| `lags[0].name` | `bond0` | `Port-channel0` |
| `lags[0].members` | `eth4`, `eth5` | `eth4`, `eth5` |
| `lags[0].mode` | `active` | `active` |
| `lag_member_of` on `eth4`/`eth5` | `bond0` | `Port-channel0` |

The render emits two `channel-group 0 mode active` lines. No record vanishes,
so this is `lossy`, not `unsupported` — the VyOS `bondN` name is translated
into the IOS-XE `Port-channelN` name, which is the correct target-native form
and is exactly the known cross-vendor naming artifact the audit warns about.

`lags` and `interfaces[].lag_member_of` are **one mechanism, not two
findings.** Neither is cited as evidence for the other. The signal is claimed
once, under `lags`, where the record is measured; `interfaces[].lag_member_of`
is `good` because the membership pointer is not lost — it is re-spelled to
match the LAG it still points at.

### 5. SNMPv3 loses its engine ID and has its privacy protocol normalised

`snmp.v3_users` drifts on both cells that carry a USM user
(`vyos_forum_snmpv3_user_eq13.conf`, `kitchen_sink.conf`). Two changes, both
per-value on a record that survives:

| sub-field | source | target |
|---|---|---|
| `engine_id` | populated | **emptied** |
| `priv_protocol` | `aes` | `aes128` |
| `name` / `group` / `auth_protocol` | — | unchanged |
| `auth_passphrase` / `priv_passphrase` | — | unchanged (length preserved) |

`cisco_iosxe_cli` declares `/snmp/v3-user/engine-id` lossy and states the
cause: engine IDs are device-assigned or global, so no per-user engine ID is
emitted on render. The `aes` → `aes128` change is a normalisation to the
IOS-XE-native spelling of the same cipher, not a downgrade.

Recorded `lossy`, not `unsupported`: the USM user record survives with its
identity and both passphrases. Re-pin the engine ID on the target if the
deployment depends on a non-default one.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for IOS-XE to lose:

`/system/syslog-server` · `/vlans/vlan/id` ·
`/vlans/vlan/ipv4/address/{secondary-ip,virtual-gateway-address,virtual-gateway-mac}` ·
`/dhcp-servers/pool` · `/radius-servers/server/{host,key}` ·
`/anycast-gateway-mac` · `/interfaces/interface/vrrp-groups/group/*` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}` ·
`/interfaces/interface/dot1q-vlan` · `/routing-instances/instance/l3-vni` ·
`/vxlan-vnis/l2vni-route-target`

These are recorded `not_applicable`, not `unsupported`, and the distinction is
operational: for several of them **cisco_iosxe_cli declares the field
supported** — `/system/syslog-server`, `/snmp/trap-host`, `/vlans/vlan/*` and
`/anycast-gateway-mac`. Re-authoring those on the target will stick, and a
migration report should say so rather than implying the target cannot hold
them.

`timezone` is different: **both** matrices declare `/system/timezone`
unsupported — a symmetric gap. That one is `unsupported`.

The six `vlans[].*` entries are grounded in measurement as well as
declaration: **zero** of the 13 cells produce a single canonical VLAN record,
because `vyos` declares `/vlans/vlan/id` unsupported outright. A VyOS box
expresses tagging as a `ethN.<vid>` netdev, which lands in `interfaces[]`.

## Matrix under-declaration on the target side

Standing observation, not a pair-specific fact, and left for a codec change
rather than fixed here. The `cisco_iosxe_cli` matrix declares **nothing** —
neither supported, lossy nor unsupported — for:

`domain` · `dns_servers` · `ntp_servers` · `lags` · `local_users` ·
`dhcp_servers` · `radius_servers`

…while demonstrably rendering and re-parsing the first five. Measured: `domain`
and `dns_servers` round-trip cleanly on the one cell that populates each,
`ntp_servers` on 11 of 12, `lags` survives as a renamed record, and
`local_users` survives on 16 of 17 records. The `good` dispositions on those
keys therefore rest on the **measured round-trip**, not on a target
declaration, and the YAML says so at each one.

## Credential material

No secret value is reproduced in this file or in the expectation YAML. Only the
crypt-scheme marker (`$6$`), the IOS-XE secret-type marker (`secret 0`,
`nopassword`) and record counts are described. SNMPv3 passphrases are referred
to only by "unchanged" and their preserved length; no passphrase body appears
anywhere. Per `AGENTS.md`, password hashes are operator-traceable even when
they are hashes, and a document that quotes the value it describes defeats its
own redaction.

## Two drift-shape readings that are wrong

**"`local_users` is a total drop."** A mechanical vanish classifier reports
`local_users TOTAL -> unsupported` on this pair, because on the single cell
where the field drifts the count goes 1 → 0, which looks total in isolation.
Across the corpus it is not: 16 of 17 accounts survive, on 12 of 13 cells, with
`role` and credential drift of zero, and the render emits `username` lines on
every cell including the failing one. The correct reading is a **partial record
loss inside a modelled concept** — `lossy`. This file resolved the
disagreement by round-tripping all 13 cells rather than trusting the
classifier's per-cell verdict.

**"`interface_type` lost the type hints."** It did not — see finding 1. The
source never carried a type on any of the 55 records. The round-trip
*manufactures* `ianaift:other`. The row is `lossy` because the value changed,
not because information was destroyed.

## A VyOS-as-target caveat that does **not** apply here

The `vyos` renderer rewrites free text, replacing embedded double quotes with
apostrophes, because VyOS rejects embedded quotes in value strings even when
escaped. On pairs where vyos is the **target**, a `description` can come back
with altered punctuation — text intact, punctuation not.

**On this pair vyos is the source, so that mechanism is not in play.** It was
checked rather than assumed: 15 surviving interface records carry a non-empty
description and **all 15 round-trip byte-identical**, with zero
quote-punctuation drift. `interfaces[].description` is `good` on its own
measurement.
