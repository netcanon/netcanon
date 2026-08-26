# IOS-XE CLI → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__vyos.yaml`.

**Source of every number here:** the committed fixture corpus round-tripped by
hand — `cisco_iosxe_cli.parse()` → `vyos.render()` → `vyos.parse()` on each of
the 15 cells — with per-key dispositions resolved through the audit's own
`actual_disposition()` rather than inferred from the drift shape, so this file
and the ratchet agree by construction. Every record comparison below is keyed
by the same identity key the audit uses (`_LIST_ID_KEYS` in
`tools/run_full_mesh.py`: `interfaces`→`name`, `static_routes`→`destination`,
`local_users`→`name`, `routing_instances`→`name`), not by list position — a
positional read of this pair invents drift that is only reordering.

- Fixture cells: **15** (14 under `tests/fixtures/real/cisco_iosxe/`, plus
  `tests/fixtures/synthetic/cisco_iosxe_cli/kitchen_sink.txt`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and hand round-trips of the committed fixtures. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`cisco_iosxe_cli` declares `device_classes = [router, switch]`. `vyos` declares
`[router, firewall]`. **The shared class is `router`, and the whole story of
this pair follows from that.**

The corpus reflects it: alongside CSR1000v / Cat8000v routers it carries a
Catalyst 9300 (`user_contrib_cat9300_iosxe1712.txt`, 47 interfaces, 3
port-channels, 6 VLANs) and a `kitchen_sink` that exercises both halves. The
routed edge — interface names, addressing, MTU, admin state, descriptions, VRF
identity, local-user identity and credentials — migrates cleanly. The **campus
L2 surface does not exist on the target at all**: the VLAN database, the
port-channels and the LAG membership pointers are dropped outright, because a
router/firewall target has nowhere to put them.

## Interface inventory: preserved, so the interface losses stand alone

This matters for how the YAML is read, so it is stated up front.

| measurement | value |
|---|---|
| source interface records, all 15 cells | **144** |
| records after parse → render → re-parse | **144** |
| cells where the interface name set differs | **1 of 15** |
| name-matched records available for sub-field comparison | **143** |

Because the inventory holds, **every `interfaces[].*` loss below is a genuine
per-attribute loss measured on its own**, and every interface sub-field that
survives is recorded `good` rather than dragged down by a vanishing parent.
Nothing in the interface block is correlated drift. (Contrast `vlans[].*`,
which is entirely correlated — see below.)

## Per-field measurement (15 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 14 | 1 | 0 |
| domain | 3 | 0 | 12 |
| dns_servers | 1 | 0 | 14 |
| ntp_servers | 1 | 0 | 14 |
| syslog_servers | 0 | 3 | 12 |
| interfaces | 0 | 11 | 4 |
| vlans | 0 | 4 | 11 |
| static_routes | 2 | 5 | 8 |
| dhcp_servers | 0 | 1 | 14 |
| snmp | 0 | 2 | 13 |
| lags | 0 | 3 | 12 |
| local_users | 5 | 2 | 8 |
| radius_servers | 0 | 1 | 14 |
| vxlan_vnis | 0 | 1 | 14 |
| routing_instances | 1 | 2 | 12 |

Fields the source populates on **zero** of the 15 cells: `timezone`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

### Per-record detail behind the interface drift (143 name-matched records)

| sub-field | populated on source | drifted | shape |
|---|---|---|---|
| `interface_type` | 143 | **143** | value → empty string |
| `lag_member_of` | 13 | **13** | value → null |
| `description` | 40 | 0 | — |
| `enabled` | 138 | 0 | — |
| `ipv4_addresses` | 40 | 0 | — |
| `mtu` | 5 | 0 | — |
| `ipv6_addresses` | 5 | 0 | — |

## Six findings worth carrying forward

### 1. Operator accounts arrive as administrators

This is the finding to act on before any other.

11 local-user records across 7 cells are matched by name; **none disappears**.
`role` drifts on exactly 2 of them, and in both cases the direction is the same:

| cell | account | role | privilege_level |
|---|---|---|---|
| `user_contrib_cat9300_iosxe1712.txt` | `monitor` | `operator` → **`admin`** | 5 → **15** |
| `kitchen_sink.txt` | `operator1` | `operator` → **`admin`** | 5 → **15** |

The other 9 accounts were already `admin` / 15, which is why only 2 of 11 drift
— not because the collapse is rare, but because most of the corpus had nothing
left to collapse.

`vyos` declares `/local-users/user/privilege-level` **lossy** and states the
mechanism itself: *"VyOS `system login user` accounts have no numeric privilege
level in the common case (configured users have full operator/admin access);
the codec maps every login user to privilege 15 / role `admin`."*

**The direction is fail-open.** A read-only account on the source becomes a
full administrator on the target. Diff the migrated account list against the
source and demote before cutover.

Credentials themselves are clean: all **11 of 11** `hashed_password` values
round-trip byte-identical, and `vyos` declares
`/local-users/user/hashed-password` supported. One honest caveat — **none of
the 11 begins with a `$N$` crypt marker**; every credential on this corpus is
an IOS-XE non-crypt secret form. What is measured is that the opaque string
survives verbatim, not that a crypt hash was correctly re-encoded.

### 2. The LAG surface is a total concept drop, and it has two faces

**6 LAG records across 3 cells become 0.** The mechanism is visible in the
render: VyOS emits the bundle as an ordinary interface —

```
    ethernet Port-channel1 {
```

— and **no `bonding` stanza appears in any of the three renders**. On re-parse
the bundle is therefore an ordinary `CanonicalInterface` named
`Port-channel1`, not a `CanonicalLAG`.

The second face is on the member ports: all **13** interface records carrying a
`lag_member_of` value come back null, while the member interfaces themselves
survive intact. That is the dangerous shape — the ports come up standalone
rather than bundled.

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported`, since
a vanished record is not lossy (#436) and `lossy` — which warns but stays
compatible — would understate losing every port-channel on a campus switch.
**They are one mechanism, not two independent findings.** Neither is cited as
evidence for the other; each is recorded where it is measured.

Standing observation, in the same spirit as the arista_eos `/lags/lag` note on
the IOS-XR pair: `vyos` declares `/lags/lag/name` and `/lags/lag/members`
**supported** while dropping every LAG on this pair, and `cisco_iosxe_cli`
declares nothing under `/lags/lag` at all. That is a matrix under-declaration
on both sides, not a pair-specific fact, and belongs to a codec change rather
than to this file.

### 3. A VRF static route silently lands in the global table

Every static-route destination survives — **0 missing, 0 extra** across the 6
cells that populate routes, 39 destination-matched records. Three separate
sub-losses ride on those surviving records:

| sub-loss | records | detail |
|---|---|---|
| next-hop kind | `interface` 30, `gateway` 27 | interface-vs-gateway discrimination collapses |
| **VRF** | **1** | `172.16.0.0/16` loses `CUSTOMER-A` |
| description | 2 | `bippety`, `UMBRELLA_SIG` → empty |

**Next-hop kind.** VyOS renders every next-hop with one grammar,
`next-hop <token>`, so an IOS-XE interface next-hop is indistinguishable from a
gateway address after the round-trip:

```
            route 10.20.0.0/16 {
                next-hop GigabitEthernet0/0/0 {
                }
            }
```

Across the corpus 33 source routes carry an interface-only next-hop — those
tokens migrate into `gateway` — and 3 carry both an interface and a gateway, in
which case the interface is simply dropped and the gateway kept. The route
still points somewhere; which *kind* of thing it points at is no longer
recorded.

**VRF.** `vyos` declares `/routing/static-route/vrf` **unsupported** — *"VyOS
per-VRF static routes (`vrf name <X> { protocols static route ... }`) are
deferred past the Phase-3 VRF wire-up"* — while `cisco_iosxe_cli` declares it
**supported** as a source. The measured consequence on `kitchen_sink.txt` is
that the `CUSTOMER-A` route renders into the *global* `protocols static` block.
A tenant route leaking into the global table is worth a per-route diff before
cutover, and is why `static_routes` is `lossy` rather than waved through.

### 4. The IANA type hint is lost on every single interface — loopbacks included

**143 of 143** name-matched records lose `interface_type`, all to the empty
string. **Zero survive.**

| source type | records lost |
|---|---|
| `ianaift:ethernetCsmacd` | 88 |
| `ianaift:softwareLoopback` | 17 |
| `ianaift:l3ipvlan` | 17 |
| `ianaift:other` | 12 |
| `ianaift:ieee8023adLag` | 5 |
| `ianaift:tunnel` | 4 |

Both matrices declare `/interfaces/interface/config/type` lossy, and `vyos`
states the cause: *"VyOS declares no IANA ifType; the codec infers it from the
interface-name shape (`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback,
`bondN` → ieee8023adLag). Best-effort."*

Worth flagging against the IOS-XR → Arista pair, where all 18
`softwareLoopback` records survived because EOS re-derives the type from
`interface Loopback<N>`. **Here even the loopbacks are lost**, because the
render keeps the IOS-XE name `Loopback0` rather than rewriting it to `lo`, and
`Loopback0` matches none of the three shapes VyOS infers from. This is a lost
hint, not lost forwarding state — the interface, its addressing and its admin
state are all unaffected — which is why it is `lossy` and not `unsupported`.

### 5. The campus L2 database has nowhere to land

**22 VLAN records across 4 cells become 0**, on every one of the 4.

`vyos` declares `/vlans/vlan/id` **unsupported** and gives the reason: *"VyOS
has no top-level VLAN database; 802.1Q VLANs are modelled as `vif <vid>`
sub-interfaces (rendered as `ethN.<vid>` CanonicalInterfaces), which ARE
supported."*

This is a real loss, not an empty-corpus artifact. Those 22 records carry:

| sub-field | populated on source |
|---|---|
| `name` | 6 of 22 |
| `tagged_ports` | 9 of 22 |
| `untagged_ports` | 6 of 22 |
| `ipv4_addresses` | 6 of 22 |
| `description` | **0 of 22** |

The whole-record loss is recorded **once**, on `vlans[].id`. The five sibling
keys are recorded `good` — deliberately. Each of them measures what happens to
the *value* when the record survives, and on this pair no VLAN record survives
at all, so there is no surviving record on which those sub-fields could
independently drift. Recording the same disappearance six times would
double-count one loss, and five of those six claims could never be evidenced.

### 6. A drift-shape reading that is wrong: `routing_instances`

A mechanical "is the target side empty?" pass over this pair reports
`routing_instances` as a **total drop**. It is not.

Keyed by name, **5 VRF records across 3 cells round-trip with 0 missing and 0
extra**. The render carries the instances:

```
    vrf {
        name CUSTOMER-A {
            table 100
        }
        name Mgmt-vrf {
            table 101
        }
    }
```

What actually empties is `routing_instances[].description`, on the 2 records of
the single cell that sets one — `Out-of-band management VRF` and
`Tenant A — corp-overlay` both return the empty string, because the `vrf name`
block has no description emit path. So the instance identity is `good`, the
description is `lossy`, and the "total drop" reading is an artifact of reading a
sub-field emptying as a record vanishing.

The RD/route-target plumbing empties alongside it (`route_distinguisher` on 3
records, `rt_imports` / `rt_exports` on 3, `l3_vni` on 1 — `vyos` declares
`/routing-instances/instance/l3-vni` unsupported). Those are not keys in the
audited set, but they are the reason a VRF that *looks* migrated still needs its
control plane rebuilt.

## The VyOS quote rewrite does not fire on this pair

The VyOS render replaces embedded double quotes in free text with apostrophes,
because VyOS rejects embedded quotes in value strings even when escaped
(vyos.dev/T1246). Every description drift on a VyOS-target pair has to be
checked against that before it is called a content loss. Checked here:

- **0 of 40** populated interface descriptions contain an embedded double
  quote, and **all 40 round-trip byte-identical**. `interfaces[].description`
  is `good` on measurement, not by assumption.
- **0 of 2** populated VRF descriptions contain an embedded double quote, and
  both return the **empty string** — not re-punctuated text.

So the one description loss on this pair is a **content loss**, not the
punctuation rewrite. The distinction is stated rather than implied because the
two look identical in a drift count and are completely different operationally.

## An invented hostname, not a lost one

`hostname` is preserved on 14 of 15 cells. The single drift is
`ntc_carrier_interfaces.txt`, and it runs the opposite direction from a loss:
the fixture carries **no `hostname` line at all**, so the source parses to the
empty string, and the VyOS render emits a literal

```
        host-name vyos
```

which re-parses as `vyos`. Nothing was dropped — a value was **invented**, and
it is the vendor default. The failure mode is a config pushed unreviewed that
renames the device `vyos`. Set the hostname explicitly on the target.

## Source-side gaps vs target-side drops

`cisco_iosxe_cli` populates **nothing** for `timezone`, `evpn_type5_routes`,
`raw_sections`, `apply_groups`, `group_content` and `anycast_gateway_mac` on any
of the 15 cells. Those are recorded `not_applicable` — except two, which are
recorded `unsupported` for reasons worth naming:

- **`timezone`** — *both* matrices declare `/system/timezone` unsupported. A
  symmetric gap, declared rather than observed.
- **`anycast_gateway_mac`** — `cisco_iosxe_cli` declares it **supported**, so
  the source *can* emit it; `vyos` declares it **unsupported** (*"VyOS has no
  VARP / distributed-anycast-gateway grammar"*). Calling that `not_applicable`
  would misdescribe a real target gap that this corpus simply never exercises.

The target-side drops that the source *did* feed are the ones that cost
something. All are `unsupported` — a vanished record is not lossy (#436):

| field | measured | `vyos` declaration |
|---|---|---|
| `syslog_servers` | 10 servers on 3 cells → 0 | `/system/syslog-server` unsupported |
| `dhcp_servers` | 2 pools on 1 cell → 0 | `/dhcp-servers/pool` unsupported |
| `radius_servers` | 2 servers on 1 cell → 0 | `/radius-servers/server/{host,key}` unsupported |
| `snmp.trap_hosts` | 7 entries on 2 cells → 0 | **undeclared** |
| `interfaces[].vrrp_groups` | 1 group on 1 cell → 0 | `/interfaces/interface/vrrp-groups/group` unsupported |

Two of those deserve a sentence each.

**`snmp.trap_hosts`** is the one nobody declared. `cisco_iosxe_cli` declares
`/snmp/trap-host` **supported**; `vyos` declares nothing for it either way, and
drops it. The rendered SNMP block carries the community and stops:

```
        snmp {
            community dummycommunity {
                authorization ro
            }
```

Same class of matrix under-declaration as `/lags/lag`, and same disposition:
recorded here, fixed in a codec change.

**`interfaces[].vrrp_groups`** — the source group on
`batfish_iosxe_basic_vrrp.txt` (group 12 on `GigabitEthernet0/2`, IETF `vrrp`
mode, one virtual IP, priority 110, preempt on) vanishes completely. The only
occurrence of the string `vrrp` anywhere in the render is inside the
`// vyos-config-version` component-version trailer (`vrrp@4`) — not a config
stanza. First-hop redundancy has to be rebuilt by hand on the target.

## SNMPv3 survives, at a weaker algorithm

The 2 USM users on `kitchen_sink.txt` both survive as records, with names and
group intact. What changes is the cryptography:

| user | auth | privacy |
|---|---|---|
| `monitor1` | `sha` → `sha` | `aes128` → **`aes`** |
| `monitor2` | `sha256` → **`sha`** | `aes256` → **`aes`** |

`vyos` declares both `/snmp/v3-user/auth-protocol` and `/priv-protocol` lossy
and calls it a cryptographic downgrade in its own reason text: *"a stronger
source auth algorithm (SHA-224/256/384/512) is collapsed to `sha` (SHA-1)"*,
and *"AES key-length variants (AES-192/256) and 3DES lose their exact strength
on render."*

The account keeps working; it keeps working at SHA-1/AES-128 regardless of what
the source specified. Re-key and re-select algorithms on the target rather than
trusting the migrated values. `vyos` also declares both passphrase paths lossy —
they are opaque `encrypted-password` blobs that require re-keying cross-vendor.

## The one name-set change

`interfaces[].name` is recorded `lossy` on the strength of a single cell,
`batfish_cisco_interface.txt` (24 records in, 24 out). Two things happen there:

- the source parses **two** interface records both named `ethernet`, and only
  one survives. Both source records carry identical content (no description, no
  addresses, enabled, `ianaift:ethernetCsmacd`), so no operator intent rides on
  the twin that collapses.
- a record named **`Port-channel1` appears** that the source carried in `lags`,
  not in `interfaces` — the same mechanism as finding 2, arriving from the other
  side.

The two cancel in the count, which is exactly why the record total is not a
sufficient check. On the other 14 cells the name set is identical, and IOS-XE
naming survives verbatim — `TenGigabitEthernet1/0/1`,
`FortyGigabitEthernet1/1/1`, `TwentyFiveGigE1/1/1`, `AppGigabitEthernet1/0/1`,
`Vlan111`, `Tunnel100`, `Port-channel2`, `Modular-Cable1/2/3:4` and
`Wideband-Cable1/2/3:4` all round-trip unchanged. `lossy`, not `unsupported`:
the inventory is not vanishing.

## Credential material

No hash body, passphrase or shared secret is reproduced in this file or in the
expectation YAML — only whether a credential is present, its length class, and
whether a `$N$` crypt marker is present (it is not, on any of the 11). Per
`AGENTS.md`, password hashes are operator-traceable even when they are hashes,
and a document that quotes the value it describes defeats its own redaction.
The RADIUS shared secrets on `kitchen_sink.txt` are recorded as *present on
both source records and dropped by the render*; their values appear nowhere.
