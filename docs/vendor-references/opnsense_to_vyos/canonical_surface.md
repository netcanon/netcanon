# OPNsense → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/opnsense__vyos.yaml`.

**Source of every number here:** the committed corpus was round-tripped by hand
— `opnsense.parse()` → `vyos.render()` → `vyos.parse()` on each of the 8
fixtures — and each per-key disposition was then reconciled with the audit's own
`actual_disposition()` so this file and the ratchet agree by construction. No
claim below rests on the drift shape alone; where a claim needed a mechanism, a
targeted probe was run and is described.

- Fixture cells: **8** (7 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the committed fixtures, and hand round-trips of them. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`opnsense` in this corpus is a **FreeBSD perimeter firewall / edge router**:
`em0` / `igc0` / `ixl0` NICs, `vlan0.<vid>` routed sub-interfaces, `lagg0`
bundles, CARP high-availability VIPs, a DHCP server, a VLAN database and a
handful of GUI login accounts. `vyos` is a **Debian + FRR software router**.

The realistic migration is an OPNsense edge box replaced by a VyOS router
carrying the same routed edge: interface addressing, hostname / domain / DNS,
static routing, the SNMP agent and local login identity. That surface migrates
well.

**The thing that does not migrate is the reason the OPNsense box exists.**
`CanonicalIntent` models no firewall rules, no NAT and no aliases — those
fields are not in the canonical schema at any fidelity — so this pair moves the
plumbing and leaves the security policy behind entirely. That is a scope
statement about netcanon, not a loss this pair can record, and it is the first
thing to say to anyone planning the cutover.

## Per-field measurement (8 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 1 | 0 |
| domain | 7 | 0 | 1 |
| dns_servers | 4 | 0 | 4 |
| interfaces (record set) | 7 | 1 | 0 |
| vlans | 0 | 2 | 6 |
| static_routes | 2 | 1 | 5 |
| dhcp_servers | 0 | 4 | 4 |
| snmp | 2 | 1 | 5 |
| lags | 0 | 1 | 7 |
| local_users | 5 | 2 | 1 |
| radius_servers | 0 | 1 | 7 |

Fields trivially empty on all 8 cells: `ntp_servers`, `timezone`,
`syslog_servers`, `vxlan_vnis[].*`, `evpn_type5_routes`,
`routing_instances[].*`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## The interface inventory: 30 records in, 31 out

This is the structural headline, and it runs the **opposite** direction from the
usual one. Nothing shrinks.

| measurement | value |
|---|---|
| source interface records, all 8 cells | **30** |
| records after parse → render → re-parse | **31** |
| cells where a source interface NAME was dropped | **0** |
| cells where the record set differs | **1** (`kitchen_sink.xml`, 7 → 8) |

The single differing cell **gains** a record: `lagg0`. The VyOS render
materialises the LAG netdev as its own interface stanza, so the bundle that
lived only in `intent.lags` on the source comes back as an eighth interface.
Every one of the 30 source names — `em0`–`em4`, `igc0`, `ixl0`, `lo0`,
`vlan0.10` … `vlan0.150`, `mismatch0` / `mismatch1` — survives on every cell.

Because the interfaces list changes length on that one cell, the reconciler's
structural collapse routes the whole list's record-level signal to
`interfaces[].name`, which is why that key is `lossy` while every surviving
`interfaces[].*` sub-field is `good`. Those `good` entries are not optimism:
they are separately measured below.

### Per-record detail behind the interface block

| sub-field | populated | of 30 | drifted | shape |
|---|---|---|---|---|
| `ipv4_addresses` | 22 | 30 | **0** | — |
| `description` | 16 | 30 | **0** | — |
| `vrrp_groups` | 4 | 30 | **4** | group → gone |
| `ipv6_addresses` | 3 | 30 | **0** | — |
| `lag_member_of` | 2 | 30 | **2** | value → null |
| `enabled` (`False`) | 1 | 30 | **0** | — |
| `mtu` | 1 | 30 | **0** | — |
| `interface_type` | **0** | 30 | — | source never emits it |

`interface_type` is worth stating plainly: the OPNsense parser populates the
IANA type hint on **zero** of the 30 records, so the `/interfaces/interface/config/type`
LOSSY declaration on the VyOS side — real enough for other sources — has nothing
to bite on here.

### The VyOS quote rewrite did not fire on this pair

`vyos/render.py::_q()` replaces an embedded `"` with an apostrophe, because VyOS
rejects embedded double-quotes in a value string even when backslash-escaped
(vyos.dev/T1246). On other `*__vyos` pairs that shows up as a description
coming back with altered punctuation — the **text** surviving and the
**punctuation** not.

Checked here and it does not apply: **0 of the 16 populated OPNsense
descriptions contain an embedded double quote**, so the sanitiser never runs and
all 16 round-trip byte-for-byte. Recorded so the next reader does not have to
re-derive it.

### One sub-field drift that has no YAML key

`interfaces[].dhcp_client_v6` drifts on **7 of 8 cells**, one record each:
five go `dhcp6` → `dhcpv6` and two go `track6` → `dhcpv6`. The first five are a
pure vocabulary normalisation. The two `track6` records (`em0` on both CARP
fixtures) are not: OPNsense `track6` means *derive this interface's IPv6 from a
delegated prefix on another interface*, and it arrives as a plain stateful
DHCPv6 client. The audited key list has no `interfaces[].dhcp_client_v6` entry,
so this pair's YAML cannot record it; it is logged here instead. Re-author IPv6
prefix delegation on the target by hand.

## Three findings worth carrying forward

### 1. The LAG drops because of a NAME SHAPE, and the fix is one rename

`kitchen_sink.xml` carries one LAG — `lagg0`, members `em2` + `em3`, mode
`active`. After the round-trip there are **0** LAG records, both members'
`lag_member_of` is `null`, and the rendered VyOS config contains no `bonding`
block, no `mode` line and no `member interface` line. What it contains instead
is:

```
    ethernet lagg0 {
    }
```

An empty ethernet netdev where the bundle should be. Both ports come up
standalone.

The mechanism is in `vyos/render.py::_vyos_type_and_name()`, which picks the
VyOS block type from the device-name shape: `re.match(r"^bond\d+$", name)` →
`bonding`, everything unrecognised → `ethernet`. OPNsense names its bundles
`laggN` (FreeBSD `lagg(4)`), which does not match, so `_bond_extra()` — the
function that emits `mode` and `member interface` — is never called.

**Probe that proves it is the name and nothing else:** re-render the same
canonical intent with the LAG renamed `lagg0` → `bond0` and the member pointers
updated to match. The render then emits

```
    bonding bond0 {
        mode 802.3ad
        member {
            interface em2 {
            }
            interface em3 {
            }
        }
    }
```

and the round-trip returns `1` LAG record with both members intact and both
`lag_member_of` pointers recovered. Nothing else changed.

So the target is fully capable — vyos declares `/lags/lag/name` and
`/lags/lag/members` SUPPORTED and honours both — and for this ordered pair every
LAG still drops, because OPNsense never produces a `bondN` name. Recorded
`unsupported` (a vanished record is not lossy, #436). The operator workaround is
concrete: rename bundles to `bondN` before migrating, or re-create the bond on
the target.

This is the same render-path gap already recorded on `cisco_iosxr__vyos` for
`Bundle-EtherN`. It is a codec issue, not a matrix edit: neither declaration
predicts the drop.

Note that `interfaces[].lag_member_of` is `good` in the YAML and that is not a
contradiction — it is the reconciler's structural collapse. The two member
pointers do go null, on the same single cell whose interface list changes
length, so that signal is claimed once at `interfaces[].name`. The bundle's
disappearance is recorded once more, where it is measured, under `lags`. **These
are one mechanism, not three findings.** Neither entry is cited as evidence for
another.

### 2. Local-user roles fail OPEN, and one cell makes it concrete

14 accounts across the 7 cells that populate local users. Names: **14 of 14
preserved**. Password hashes: **10 of 10 populated hashes preserved verbatim**.
Roles: **5 of 14 escalate**.

| cell | accounts | role change | privilege_level |
|---|---|---|---|
| `opnsense_acl_test_config.xml` | `test1`–`test4` | `user` → `admin` | 1 → 15 |
| `kitchen_sink.xml` | `readonly` | `user` → `admin` | 1 → 15 |

The cause is declared and honest on the VyOS side: `/local-users/user/privilege-level`
is LOSSY with the reason that VyOS `system login user` accounts have no numeric
privilege level in the common case, so the codec maps every login user to
privilege 15 / role `admin`. The `/local-users/user/role` path is declared
SUPPORTED while being flattened — an under-declaration on the target.

`opnsense_acl_test_config.xml` is the one to look at, because the four escalated
accounts also carry **no password hash at all** on the source. The render emits
them as bare login entries:

```
        user test1 {
        }
```

— no `authentication` block, no `encrypted-password` — and the re-parse reads
each back as `role='admin'`, `privilege_level=15`. Four credential-less accounts
arrive on the target described as administrators. Whether a real VyOS box would
let such an account authenticate is a device question this harness does not
answer; what is measured is that the canonical intent says `admin`, and a
migration report generated from it would say `admin` too.

Recorded `lossy`, not `unsupported`: the account record survives and the target
models roles, so the value degrades rather than vanishing (#436). Review every
migrated account's authority on the target before cutover.

### 3. `static_routes` is NOT a total drop — the drift-shape reading is wrong

A mechanical "is the target side empty / does the source declare it?" pass over
this pair reports `static_routes` as a **total drop → unsupported**. It is not,
and the round-trip says so plainly. 3 cells populate static routes, one route
each, and all three come back with destination and next-hop intact:

```
    static {
        route 172.16.0.0/12 {
            next-hop 10.0.0.254 {
            }
        }
    }
```

What actually empties is the route's **description**, on the single cell that
sets one: `Corporate transit` → `''`. vyos already declares
`/routing/static-route/description` LOSSY with the accurate reason — the render
emits destination + next-hop + distance only. So the field is `lossy`, not
`unsupported`.

The false reading has a traceable origin: **opnsense declares
`/routing/static-route` and its five sub-paths UNSUPPORTED**, and a heuristic
that reads the source declaration concludes nothing can leave. But that
declaration is about opnsense as a *target* — its own matrix reason says the
parse harvests routes (the `<gateways>` default route plus
`<staticroutes>/<route>` entries, promotion #15) while the `config.xml` renderer
emits no `<staticroutes>` block. As a **source**, opnsense emits static routes
just fine. Read the declaration in the direction it was written.

## Source-side gaps vs target-side drops

`opnsense` declares these unsupported at the exact path, so as a *source* it
never emits them and there is nothing for VyOS to lose. All are measured empty
on all 8 cells, and all are recorded `not_applicable`:

`/system/ntp-server` · `/vxlan-vnis/{vni,source-interface,udp-port}` ·
`/routing-instances/instance` · `/routing-instances/instance/instance-type` ·
`/vlans/vlan/{tagged-ports,untagged-ports}` · `/snmp/v3-user` and its four
sub-paths

The distinction from `unsupported` is operational: VyOS declares most of them
SUPPORTED on its own side — `/system/ntp-server`, `/vxlan-vnis/vni`,
`/routing-instances/instance/name`, `/snmp/v3-user` — so re-authoring them on
the target will stick, and a migration report should say so rather than implying
the target cannot hold them.

Three keys are different, because **both** matrices declare them unsupported —
a symmetric gap in the pair, not a VyOS limitation. Those are `unsupported`:
`/system/timezone` · `/system/syslog-server` · `/anycast-gateway-mac`.

And these are genuine **target-side drops** — the source emits them, VyOS does
not carry them, the record vanishes:

| field | measured | target declaration |
|---|---|---|
| `interfaces[].vrrp_groups` | 4 CARP groups on 2 cells → 0 | `/interfaces/interface/vrrp-groups/group` UNSUPPORTED |
| `vlans[].id` | 10 VLAN records on 2 cells → 0 | `/vlans/vlan/id` UNSUPPORTED |
| `dhcp_servers` | 4 pools on 4 cells → 0 | `/dhcp-servers/pool` UNSUPPORTED |
| `radius_servers` | 2 servers on 1 cell → 0 | `/radius-servers/server/{host,key}` UNSUPPORTED |
| `snmp.trap_hosts` | 2 hosts on 1 cell → 0 | **nothing declared** |
| `lags` | 1 bundle on 1 cell → 0 | `/lags/lag/{name,members}` SUPPORTED |

The last two rows are declaration bugs of opposite sign and are noted as
standing observations rather than fixed here. `snmp.trap_hosts`: opnsense
declares `/snmp/trap-host` SUPPORTED, the VyOS codec contains no trap handling
at all (no render path, no parse path) and declares nothing for the path in any
of its three lists — so the drop is real and invisible to the matrix.
`lags`: see finding 1 above.

## What the VLAN database loses, and what quietly survives

VyOS has no top-level VLAN database — its matrix says so directly:
`/vlans/vlan/id` is unsupported because 802.1Q VLANs are modelled as `vif <vid>`
sub-interfaces. So all 10 VLAN records across the 2 populated cells go to zero,
and the `vlans[].id` key carries that structural loss for the whole list.

But the L3 does **not** all vanish with it, and the split is worth knowing:

| cell | VLAN ids | surviving `vlan0.<vid>` interface twin |
|---|---|---|
| `user_contrib_supergate_opn25.xml` | 10, 11, 20, 100, 150 | all 5 |
| `kitchen_sink.xml` | 10, 20, 30, 100, 200 | only 20 and 30 |

So **7 of the 10** VLAN records have a routed sub-interface twin in
`interfaces[]` that survives with its addressing and description intact, and
**3** — VLANs 10, 100 and 200 on `kitchen_sink.xml` — leave no trace at all.

Every one of the 10 source VLAN records carries only `id` and `name`
(`USER VLAN`, `MGMT VLAN`, `IOT VLAN`, …); description, addressing and port
membership are empty on all 10, and opnsense declares `/vlans/vlan/tagged-ports`
and `/vlans/vlan/untagged-ports` unsupported so those two can never be
populated. The VLAN **name** is the one operator-authored value that is lost on
all 10 — the sub-interface twin carries its own description, not the VLAN's
name. Capture the id→name table before cutover.

## Credential material

No hash body is reproduced in this file or in the expectation YAML. Only shapes
are described: the OPNsense parser tags every account password with a literal
`bcrypt:` marker (`opnsense/parse.py`), and the VyOS render carries that whole
tagged string verbatim into the `encrypted-password` leaf. All 10 populated
hashes round-trip with the same marker and the same length (65–97 characters).

Two shape notes that do not change the `good` disposition:

- The `bcrypt:` tag is applied unconditionally, so on the two CARP fixtures it
  sits in front of a `$6$` SHA-512 crypt body rather than a `$2y$` bcrypt one.
  The canonical value is preserved exactly; the marker simply does not describe
  the body. That is a source-codec observation, not a loss on this pair.
- Preservation is not target-syntax validity. A VyOS `encrypted-password` leaf
  holding a `bcrypt:`-tagged string is the canonical value carried faithfully,
  which is what the fidelity harness scores — it does not score whether the
  target device would accept the line. Same caveat as interface names below.

Three other secrets pass through this pair and none is reproduced here either:
the SNMPv2c community string (which *is* the v2c authentication token, so it is
described and never quoted), the CARP authentication key on the two HA fixtures,
and the RADIUS shared secret on `kitchen_sink.xml`. The last two do not survive
in any case — both ride records the target drops outright — but that is a reason
to re-enter them deliberately on the target, not a reason to print them.

## Interface names are preserved, not translated

The 30 source names round-trip exactly, and that is what the harness measures.
It is not the same as a config a VyOS box will load: `ethernet em0`,
`ethernet igc0`, `ethernet vlan0.20` and `ethernet lagg0` are FreeBSD device
names rendered into VyOS grammar. Run the port-name translator before applying
the output — a bare `run_plan` skips it by design.
