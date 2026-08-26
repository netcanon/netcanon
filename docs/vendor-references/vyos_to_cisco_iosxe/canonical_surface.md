# VyOS → Cisco IOS-XE (NETCONF/OpenConfig): measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__cisco_iosxe.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`vyos.parse()` → `cisco_iosxe.render()` → `cisco_iosxe.parse()` on each of the
13 fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures + 1 synthetic kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Read this first: the target is a Phase-0.5 stub, not a vendor limit

This pair looks catastrophic — 21 of 43 keys `unsupported` — and it would be
badly misread as "Cisco IOS-XE cannot hold a hostname". It cannot hold one
*through this codec*. The `cisco_iosxe` codec is an **experimental Phase-0.5
NETCONF/OpenConfig stub whose render emits only the `openconfig-interfaces`
subtree**. Its own matrix says so out loud: **40 of its 67 `unsupported`
declarations name the Phase-0.5 stub as the cause**, six of them in the literal
form *"Phase 0.5 stub render emits only interfaces; `intent.<field>` dropped on
render."*

Verified on the rendered document rather than taken from the declaration —
substring counts over `cisco_iosxe.render(vyos.parse(kitchen_sink.conf))`:

| token in the rendered XML | occurrences |
|---|---|
| `system` | **0** |
| `hostname` | **0** |
| `username` | **0** |
| `snmp` | **0** |
| `static` | **0** |
| `network-instance` | **0** |
| `channel` / `aggregat` | **0** / **0** |
| `mtu` | **0** |

The render is a single `<interfaces xmlns="http://openconfig.net/yang/interfaces">`
document and nothing else. So the shape of this pair is: **the interface plane
survives essentially intact; every other plane is dropped whole.** That is a
codec-maturity story, not a device-class story, and the expectation YAML says
so on every affected key rather than implying an IOS-XE platform gap.

### The actionable consequence

The sibling **`cisco_iosxe_cli`** codec declares `/system/hostname`,
`/routing/static-route`, `/routing/static-route/vrf`, `/snmp/community`,
`/snmp/location`, `/snmp/contact`, `/snmp/trap-host`, `/snmp/v3-user`,
`/vlans/vlan/id`, `/vlans/vlan/name`, `/vxlan-vnis/vni`,
`/interfaces/interface/vrrp-groups/group` and `/anycast-gateway-mac` **all
supported** — precisely the surface the NETCONF stub drops. For a real VyOS →
IOS-XE migration, target `cisco_iosxe_cli` unless NETCONF/OpenConfig output is
itself the requirement. This is not advice extrapolated from a vendor doc; it
is the two matrices side by side in this repo.

## Device-class framing

`vyos` in this corpus is a **Linux-based software router / edge gateway**:
`ethN` and `ethN.M` interface naming, `bondN` aggregation, `dumN` dummy
interfaces, `lo`, DHCP client on WAN ports, DHCPv6-PD, a small local-user set
and a curly-brace `config.boot`. The cells are small — 55 interface records
across 13 configs, a median of 3 per cell — and **none of them populates
`vlans` at all**, so there is no campus L2 database on this pair to migrate.

`cisco_iosxe` (this codec) is a **NETCONF/OpenConfig interface renderer**. The
only shared surface is therefore the **routed interface plane** — names,
descriptions, admin state, IPv4/IPv6 addressing — and that surface is clean.

## The structural finding: the interface inventory is fully preserved

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **55** |
| cells where the interface name set differs | **0** |

VyOS `ethN`, dot1q sub-interfaces (`eth1.100`, `eth1.200`), `lo`, the dummy
`dum0` and even `bond0` itself all survive the OpenConfig render verbatim as
interface records.

The consequence matters for how the YAML is read: **no `interfaces[].*` key on
this pair is correlated drift**. Each interface loss below stands on its own
measurement, and each interface sub-field that survives is `good` on its own
merits rather than being dragged along by a vanishing parent.

Outside `interfaces[]` the situation inverts: `local_users`, `lags`,
`static_routes`, `vxlan_vnis`, `routing_instances` and the whole `snmp` block
lose **every record on every populated cell**. Those are the structural losses,
and each is claimed exactly once — on the identity key of its list — per the
audit's structural-collapse rule.

## Per-field measurement (13 cells)

| field | cells preserved | cells drifted | trivially empty |
|---|---|---|---|
| hostname | 0 | **13** | 0 |
| domain | 0 | **1** | 12 |
| dns_servers | 0 | **1** | 12 |
| ntp_servers | 0 | **12** | 1 |
| interfaces (record set) | 13 | 0 | 0 |
| vlans | 0 | 0 | 13 |
| static_routes | 0 | **4** | 9 |
| snmp | 0 | **4** | 9 |
| lags | 0 | **1** | 12 |
| local_users | 0 | **13** | 0 |
| vxlan_vnis | 0 | **3** | 10 |
| routing_instances | 0 | **1** | 12 |

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`, `vlans`
(every sub-key), `dhcp_servers`, `radius_servers`, `evpn_type5_routes`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`,
`interfaces[].interface_type`, `interfaces[].vrrp_groups`.

### Record counts behind the whole-record drops

| field | source records | after round-trip | cells |
|---|---|---|---|
| `ntp_servers` | 37 | 0 | 12 |
| `dns_servers` | 3 | 0 | 1 |
| `static_routes` | 7 | 0 | 4 |
| `local_users` | 17 | 0 | 13 |
| `lags` | 1 | 0 | 1 |
| `vxlan_vnis` | 3 | 0 | 3 |
| `routing_instances` | 1 | 0 | 1 |

### Per-record detail inside the surviving interface plane

| sub-field | records affected | of populated | shape |
|---|---|---|---|
| `name` / `enabled` | 0 | 55 | — |
| `description` | 0 | 15 | — |
| `ipv4_addresses` | 0 | 21 | — |
| `ipv6_addresses` | 0 | 20 | — |
| `mtu` | 1 | 1 | value → null |
| `lag_member_of` | 2 | 2 | value → null |
| `interface_type` | — | **0** | never populated by the source |
| `vrrp_groups` | — | **0** | never populated by the source |

## SNMP: four cells, one mechanism, four keys

`intent.snmp` is populated on 4 of 13 cells and becomes `None` on all four —
the stub never walks it. The four cells populate different sub-fields, which is
why the four SNMP keys carry different measured cell counts and why each one is
recorded where it is measured rather than by reference to its siblings:

| cell | community | location | contact | trap_hosts | v3_users |
|---|---|---|---|---|---|
| `metasploit-vyos-config.conf` | yes | — | — | 0 | 0 |
| `scottlaird-vyos-parser.conf` | yes | — | — | 0 | 0 |
| `vyos_forum_snmpv3_user_eq13.conf` | — | yes | yes | 0 | 1 |
| `kitchen_sink.conf` | yes | yes | yes | 0 | 1 |

So `snmp.community` drifts on 3 cells, `snmp.location` and `snmp.contact` on 2
each, `snmp.v3_users` on 2 — and **`snmp.trap_hosts` on 0**, because no
committed cell sets a trap host and the list is empty on both sides of every
comparison. `snmp.trap_hosts` is therefore recorded `good`: a loss there cannot
be evidenced on this corpus and would be an over-claim. The concept-level drop
that *would* take a trap host with it is already recorded on `snmp.community`,
where it is measured. **These are one mechanism, not four independent
findings** — none is cited as evidence for any other.

`vyos` declares `/snmp/community`, `/snmp/location`, `/snmp/contact` and
`/snmp/v3-user` supported, so the source side is not the problem.

## Three findings worth carrying forward

### 1. Every local user disappears, on every cell

17 user records across all 13 cells become **0**. The rendered document
contains zero `username` occurrences. This is not a subset rule as on some
other pairs — it is total and uniform.

`vyos` declares `/local-users/user/name`, `/role` and `/hashed-password`
supported. `cisco_iosxe` declares the whole-field marker `/local_users`
unsupported, and declares **nothing at all** at the granular
`/local-users/user/*` paths.

Recorded `unsupported` on `local_users[].name`, per #436: a vanished record is
not lossy, and `lossy` — which warns but stays compatible — would badly
understate a migration that silently produces a device with no accounts on it.

`local_users[].role` and `local_users[].hashed_password` are recorded `good`,
and that needs saying precisely so it is not misread. Those two keys measure
what happens to a **value when its record survives**. On this pair no record
survives on any cell, so there is no surviving-record value drift to record —
the disappearance itself is claimed once, on `local_users[].name`. Recording it
three times would triple-count one mechanism and is exactly what the audit's
structural collapse exists to prevent.

Operationally the advice is unchanged and blunt: the target comes up with no
local accounts. Establish console/AAA access before cutover.

### 2. `bond0` survives as an interface while the LAG that owns it does not

On `kitchen_sink.conf` the source carries one LAG — `bond0`, members
`eth4`/`eth5`, mode `active`. After the round-trip:

- `lags` = **0 records**;
- `eth4.lag_member_of` and `eth5.lag_member_of` both **`bond0` → null**;
- `bond0`, `eth4` and `eth5` all **survive as ordinary interface records**.

That is the dangerous shape: the member ports come up standalone rather than
bundled, and `bond0` comes up as an unrelated interface. The rendered document
contains no `channel-group` and no aggregation element of any kind.

`vyos` declares `/lags/lag/name` and `/lags/lag/members` supported (and
`/lags/lag/mode` lossy), so the source side is not the problem.

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported`, since
a vanished record is not lossy (#436). **They are one mechanism, not two
independent findings** — neither is cited as evidence for the other; each is
recorded where it is measured, `lags` on the LAG list and `lag_member_of` on
the interface record.

Standing matrix observation, not a pair-specific fact: `cisco_iosxe` declares
the whole-field markers `/lags` and `/local_users` unsupported but declares
nothing at the granular `/lags/lag/name`, `/lags/lag/members`,
`/local-users/user/name` paths that the rest of the mesh keys on. The same
matrix also carries underscore field-name aliases alongside the canonical
xpaths — `/hostname`, `/domain`, `/dns_servers`, `/ntp_servers`, `/timezone`,
`/syslog_servers`, `/static_routes`, `/routing_instances`, `/vxlan_vnis`,
`/radius_servers`, `/evpn_type5_routes`, `/vlans`, `/dhcp_servers` — which are
not the canonical vocabulary normalised in the 2026-06 vocab pass. Both belong
to a codec change, not to this file.

### 3. Sub-interfaces keep their address and lose their VLAN tag

Measured on `kitchen_sink.conf`: `eth1.100` and `eth1.200` survive as interface
records with their descriptions and IPv4 addresses intact, but
`dot1q_vlan` goes `100 → None` and `200 → None`. The sub-interface exists on
the target and is untagged.

There is no expectation key for `interfaces[].dot1q_vlan`, so this loss is
recorded here rather than in the YAML. It is a *symmetric* declared gap —
**both** codecs declare `/interfaces/interface/dot1q-vlan` unsupported — so it
is not a `cisco_iosxe` regression; it is a canonical-surface gap that the
`cisco_iosxe_cli` sibling closes (that codec declares the path supported).

Three further interface sub-fields drift with no expectation key of their own,
listed here for completeness rather than folded into any key above:

| sub-field | records | cells | shape |
|---|---|---|---|
| `dhcp_client` | 3 | 3 | `True → False` |
| `dhcp_client_v6` | 1 | 1 | `'dhcpv6' → ''` |
| `vrf` | 1 | 1 | `'BLUE' → ''` |

`vyos` declares `/interfaces/interface/dhcp-client` and `/dhcp-client-v6`
supported; the OpenConfig stub models neither, so a WAN port configured for
DHCP arrives on the target with no address source at all. The `vrf` drift is
the interface-side companion of the `routing_instances` drop and is the same
mechanism, not a second finding.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for the target to lose:

`/vlans/vlan/id` · `/vlans/vlan/ipv4/address/{secondary-ip,virtual-gateway-address,virtual-gateway-mac}` ·
`/interfaces/interface/vrrp-groups/group` (and all seven sub-leaves) ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}` ·
`/dhcp-servers/pool` · `/radius-servers/server/{host,key}` ·
`/system/timezone` · `/system/syslog-server` · `/anycast-gateway-mac` ·
`/routing/static-route/vrf` · `/routing-instances/instance/l3-vni` ·
`/vxlan-vnis/l2vni-route-target`

The VLAN gap is measured, not merely declared: **0 of 13 cells populate
`vlans` at all**. VyOS expresses tagging as a dot1q sub-interface, which lands
in `interfaces[]`, and none of these fixtures runs a bridge with a VLAN
database. All six `vlans[].*` keys are therefore source-side gaps.

The distinction the YAML draws between `not_applicable` and `unsupported` on
these zero-observation keys is the same one the rest of the mesh uses:

- **both** matrices declare the path unsupported → `unsupported` (a symmetric
  gap; re-authoring through this codec pair will not stick). That covers
  `timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
  `anycast_gateway_mac`, `interfaces[].vrrp_groups` and `vlans[].id`.
- only the **source** cannot emit it → `not_applicable`. That covers
  `interfaces[].interface_type` (vyos declares
  `/interfaces/interface/config/type` lossy and populates it on **0 of 55**
  records, while `cisco_iosxe` declares the same path **supported**), the
  remaining five `vlans[].*` keys, `evpn_type5_routes`, `raw_sections`,
  `apply_groups` and `group_content`.

Every one of those rests on declarations plus a zero-observation measurement,
and the YAML says so on each key rather than implying a round-trip that was
never exercised.

## MTU is the one true `lossy` on this pair

`interfaces[].mtu` is the only key recorded `lossy` rather than `unsupported`,
and the reasoning is worth spelling out because the observed behaviour is a
total attribute drop:

- **Observed:** exactly one record in the whole corpus populates MTU —
  `kitchen_sink.conf` / `eth0`, `1500 → null`. The rendered document contains
  zero `mtu` elements.
- **Declared:** `cisco_iosxe` declares `/interfaces/interface/config/mtu`
  **lossy**, not unsupported — the OpenConfig model does carry MTU; the
  Phase-0.5 render simply does not emit it yet. `vyos` declares the path
  supported.
- **Record survives:** the interface itself is preserved. #436 forces
  `unsupported` where a *record* vanishes and the target has no grammar for it;
  here the record survives and the target's own matrix claims the grammar.

So: `lossy`. But state the exposure honestly — coverage is one record, and that
record's value happens to be 1500, which is the platform default anyway. A
jumbo-frame port would silently arrive at default MTU with no warning louder
than a `lossy` flag. Re-apply MTU by hand on any port that had a non-default
value.

## Credential material

No hash body is reproduced in this file or in the expectation YAML. The
committed VyOS fixtures carry `$6$`-scheme (SHA-512 crypt) user secrets and
`$6$`-prefixed SNMPv3 auth/priv passphrases; only the scheme marker is named.
Per `AGENTS.md`, password hashes are operator-traceable even when they are
hashes, and a document that quotes the value it describes defeats its own
redaction. On this pair the point is close to moot in one direction and sharper
in the other: no credential reaches the target at all, because no user record
and no SNMP block does — which means every account and every SNMP secret must
be re-established on the target by hand.

## One thing that is *not* happening here

`vyos` as a **render target** rewrites free text, replacing embedded double
quotes with apostrophes, because VyOS rejects embedded quotes in value strings
even when escaped (`vyos.dev/T1246`). That behaviour lives on the *render* side
of the vyos codec and this pair renders with `cisco_iosxe`, so it cannot apply
here. Consistent with that, `interfaces[].description` is measured preserved on
**15 of 15** populated records across 7 cells, with zero punctuation drift. If
you arrive here from a pair where vyos is the *target* and a description came
back with altered punctuation, that is the quote rewrite — the text survives,
its punctuation does not — and it is a different finding from this one.

## Reproducing every number in this file

```
python tools/run_full_mesh.py          # the mesh pass these counts come from
```

Each per-key claim was additionally re-derived by hand with
`vyos.parse()` → `cisco_iosxe.render()` → `cisco_iosxe.parse()` over the 13
committed cells at `tests/fixtures/real/vyos/*.conf` and
`tests/fixtures/synthetic/vyos/kitchen_sink.conf`, comparing the source-side
and round-tripped canonical trees field by field.
