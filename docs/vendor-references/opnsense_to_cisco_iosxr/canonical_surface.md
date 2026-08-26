# OPNsense → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/opnsense__cisco_iosxr.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every record-level count below was additionally re-derived by
hand, parsing each fixture with the `opnsense` codec and rendering it with
`cisco_iosxr`.

- Fixture cells: **8**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the eight
> committed OPNsense fixtures. Where a disposition rests on a declaration
> rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`opnsense` in this corpus is an **x86 BSD firewall / perimeter appliance**;
`cisco_iosxr` is a **service-provider edge/core router**. The shared surface is
the routed L3 edge — interface addressing, descriptions, MTU, admin state,
static routes, local user identity, hostname/domain/DNS — and essentially
nothing else.

Two device-class asymmetries dominate the pair, and they point in opposite
directions:

- **IOS-XR's deep surface is unreachable from this source.** XR is built around
  VRFs, RD-from-`router bgp`, and 4-segment interface naming. OPNsense declares
  `/routing-instances/instance` unsupported and emits **zero** routing
  instances on all 8 cells, so the richest part of the target model is never
  exercised. The XR-side declarations for `4th-port-segment`,
  `instance-type` and route-distinguisher handling are all inert on this pair.
- **OPNsense's appliance surface has nowhere to land.** DHCP server pools,
  RADIUS servers, SNMP and CARP first-hop redundancy are the services an
  OPNsense box actually runs, and IOS-XR declares every one of them out of v1
  scope. These are the pair's real losses.

## The structural finding — and it is the INVERSE of the AOS-CX pair

On `aruba_aoscx__arista_eos` the dominant loss was record attrition: the
interface list shrank and every `interfaces[].*` sub-field measured as drifted
for that one reason. **That does not happen here.**

Across all 8 cells the interface inventory is **30 records in, 30 records out,
zero dropped**, and on every one of those 30 records `description`, `enabled`,
`mtu`, `ipv4_addresses` and `ipv6_addresses` are identical after the
round-trip. OPNsense interface names (`em0`, `igc0`, `vlan0.20`) pass through
the XR render unchanged — they are emitted verbatim as `interface <name>`
stanzas rather than being normalised into XR 4-segment form.

The consequence is that six of the nine `interfaces[].*` keys are honestly
`good`, which is unusual for this mesh. The losses on this pair are
**whole-subsystem drops**, not per-record attrition — a different failure
shape that a reader coming from the AOS-CX notes should not assume.

## Per-field measurement (8 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 1 | 0 |
| domain | 7 | 0 | 1 |
| dns_servers | 4 | 0 | 4 |
| interfaces[].name / .enabled / .ipv4_addresses | 8 | 0 | 0 |
| interfaces[].description | 5 | 0 | 3 |
| interfaces[].ipv6_addresses | 2 | 0 | 6 |
| interfaces[].mtu | 1 | 0 | 7 |
| interfaces[].interface_type | 0 | 8 | 0 |
| interfaces[].vrrp_groups | 0 | 2 | 6 |
| interfaces[].lag_member_of | 0 | 1 | 7 |
| vlans (every sub-field) | 0 | 2 | 6 |
| static_routes | 2 | 1 | 5 |
| dhcp_servers | 0 | 4 | 4 |
| snmp.community | 0 | 3 | 5 |
| snmp.location / .contact / .trap_hosts | 2 | 1 | 5 |
| snmp.v3_users | 3 | 0 | 5 |
| lags | 0 | 1 | 7 |
| local_users[].name / .role / .hashed_password | 7 | 0 | 1 |
| radius_servers | 0 | 1 | 7 |

Fields trivially empty on all 8 cells: `ntp_servers`, `timezone`,
`syslog_servers`, `vxlan_vnis[].vni` / `.vlan_id` / `.mcast_group`,
`evpn_type5_routes`, `routing_instances[].name` / `.description`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`.

### Record-level census (re-derived by hand over the same 8 fixtures)

| canonical list | source records | records after render + re-parse |
|---|---|---|
| interfaces | 30 | **30** |
| local_users | 14 | **14** |
| static_routes | 3 | **3** |
| lags | 1 | **1** (renamed) |
| vlans | 10 | **0** |
| dhcp_servers | 4 | **0** |
| radius_servers | 2 | **0** |
| snmp blocks | 3 | **0** (whole object → `None`) |
| interface records carrying a CARP/VRRP group | 4 | **0** |

## The five total drops — `unsupported`, not `lossy`

Per netcanon #436, a vanished record is not lossy: `lossy` warns and stays
compatible, `unsupported` blocks. Each of these was confirmed by inspecting the
rendered IOS-XR text, not inferred from the drift shape.

1. **VLANs.** 10 VLAN records in, 0 out. The render emits **no `vlan` stanza of
   any kind**. IOS-XR has no campus L2 model — the XR matrix declares
   `switchport-mode`, `access-vlan`, `trunk-allowed-vlans`, `trunk-native-vlan`
   and `voice-vlan` all unsupported, because VLANs on XR are dot1q
   sub-interfaces.
   **The operationally important nuance:** the OPNsense *VLAN interfaces*
   (`vlan0.20`, `vlan0.100`, …) DO survive — as `interfaces[]` records with
   their addressing intact. What is lost is the standalone VLAN table: the ID,
   the operator-assigned name (`USER VLAN`, `MGMT VLAN`, …) and the
   description. Layer-3 reachability survives; the VLAN inventory does not.
2. **DHCP server pools.** 4 in, 0 out. XR declares `/dhcp-servers/pool`
   unsupported: "Render emits no DHCP server pool."
3. **RADIUS servers.** 2 in, 0 out. XR declares both
   `/radius-servers/server/host` and `/radius-servers/server/key` unsupported:
   "Render emits no AAA radius-server config."
4. **SNMP.** The whole `snmp` object goes to `None` on all 3 cells that carry
   one. XR declares `/snmp/community` unsupported with the blunt reason "SNMP
   parse + render is out of the v1 XR scope."
5. **CARP / VRRP groups.** 4 interface records carry a CARP group in the source
   (the two HA fixtures); 0 survive. XR declares the entire
   `/interfaces/interface/vrrp-groups/group` subtree unsupported: "VRRP / FHRP
   redundancy groups are out of the v1 IOS-XR scope."

This is the pair's headline for a migration report: **an OPNsense box's
service plane does not migrate.** DHCP, RADIUS, SNMP and first-hop redundancy
must all be re-authored on the target, or provided by something other than the
XR router.

## Two drifts that look like losses and are not

**1. `lags` is a rename, not a membership loss.** The bare drift is
`lagg0` → `Bundle-Ether0`. The audit canonicalises LAG names for
`interfaces[].lag_member_of` (`_LAG_NAME_FIELDS`), but the OPNsense `laggN`
form is not among the spellings it collapses, so both `lags` and
`interfaces[].lag_member_of` register drift. Round-tripping the kitchen-sink
fixture shows the LAG **survives with members intact**: source
`lagg0 [em2, em3] mode=active` → target `Bundle-Ether0 [em2, em3] mode=active`,
and both member interfaces still carry `lag_member_of`. The render emits
`bundle id 0 mode active` under each member and the XR parser rebuilds the
bundle from it. Both keys are therefore `lossy` (a rename that stays
compatible), never `unsupported`.

**2. `static_routes` survives; only the description is dropped.** 3 routes in,
3 routes out, destination and next-hop byte-identical. The single drifting cell
loses only the route's operator label. That matches the XR matrix exactly:
`/routing/static-route/description` is declared **lossy** — "Render emits
destination + next-hop only." A record-drop heuristic that keys off "target
side is empty" reads this as a total drop; the round-trip says otherwise, so
`lossy` is the honest call.

## Two drifts whose direction is ADDITION, not deletion

Worth stating because "drifted" is easy to read as "data was lost", and on this
pair twice it means the opposite — the target gained a value the source never
had.

- **`hostname`** drifts on exactly 1 of 8 cells, and the direction is
  `'' → 'Router'`. The OPNsense config carries no hostname; the XR render
  substitutes its own default `hostname Router`. Nothing was lost — a default
  was fabricated. It is still declared `lossy`, because "the source's absence
  of a hostname" does not round-trip.
- **`interfaces[].interface_type`** drifts on all 8 cells, always
  `'' → 'ianaift:other'`. OPNsense never populates the canonical interface
  type. The XR parser infers type from the name prefix (GigabitEthernet →
  `ethernetCsmacd`, Loopback → `softwareLoopback`, Bundle-Ether →
  `ieee8023adLag`), and OPNsense names match no prefix, so every record lands
  on the fallback. XR declares `/interfaces/interface/config/type` lossy in its
  own right.

## Correlated drift: what the parent-level signal does NOT prove

Two parent lists show drift on nearly every cell for reasons that belong to
sub-fields **not declared in this YAML**. Reading the parent signal as
corroboration for the declared keys would be wrong, so it is recorded here
instead.

- **`local_users` drifts on 7 of 8 cells — entirely via `privilege_level`**
  (`15 → 1` on every admin account). `name`, `role` and `hashed_password` are
  preserved on all 14 user records across all 8 fixtures. `privilege_level` is
  not one of this schema's declared `local_users[].*` keys, so it carries no
  disposition here; the drop is fail-*closed* (privilege reduced, not raised),
  which is the safe direction, but any account expecting full privilege on the
  target needs it re-granted.
- **`interfaces` drifts on 8 of 8 cells** partly via `dhcp_client` (`true →
  false`, 5 records) and `dhcp_client_v6` (`dhcp6 → ''`, 7 records) — again,
  neither is a declared key. A WAN interface configured for DHCP/DHCPv6 client
  addressing on OPNsense arrives on XR with no address source at all.

## The `vlans[]` structural collapse

All six `vlans[].*` keys drift on the same 2 cells, and for one reason only:
the parent list goes 5 → 0 (and 5 → 0 again on the other cell). The reconciler
collapses this — the first `vlans[].*` key in file order claims the record-level
loss and every later sibling is classified `STRUCTURAL_ONLY`.

`vlans[].id` is written first and carries the `unsupported`. `vlans[].name`,
`.ipv4_addresses`, `.untagged_ports`, `.tagged_ports` and `.description` are
declared **`good`** — not because they are unimportant, but because a loss
declared on them could never be evidenced by any cell and would fail the
per-pair ratchet by construction. Their `good` means "when a VLAN record
survives, this attribute survives with it", which on this pair is vacuous. The
record loss is real and it is stated once, on `vlans[].id`.

(Two of the six are additionally moot on their own merits: OPNsense declares
`/vlans/vlan/tagged-ports` and `/vlans/vlan/untagged-ports` unsupported, so it
never emits port membership in the first place. Both measure empty on both
sides of every cell.)

## Credential material

`local_users[].hashed_password` is **preserved on all 14 user records** —
unusual for this mesh, and the reason it is `good`. OPNsense stores the user
secret as a bcrypt hash and the IOS-XR render carries the string through
verbatim.

Two caveats that the `good` does not cover, both observed in the rendered
output:

- The hash is emitted behind a **type-0 marker** (`secret 0 <hash>`), which in
  Cisco grammar marks the following field as *plaintext*. The fidelity harness
  scores canonical **preservation**, not target-syntax **validity**; whether an
  XR device accepts a bcrypt string presented as a type-0 secret is a question
  this measurement does not answer and this file does not assert.
- `privilege_level` is reset (see above), so the account survives with its
  identity and secret but not its authority.

No hash value is reproduced in this file or in the expectation YAML. Per
`AGENTS.md`, credential material is operator-traceable even when hashed, and a
document that quotes the value it describes defeats its own redaction. Only the
*shape* is recorded: a bcrypt-family hash, 65–97 characters as carried in the
committed fixtures.

## Source-side gaps vs target-side drops vs symmetric gaps

OPNsense declares these **unsupported at the exact path**, so as a *source* it
never emits them — there is nothing for XR to lose:

`/system/ntp-server` · `/system/syslog-server` · `/routing-instances/instance`

These are recorded `not_applicable`, not `unsupported`, and the distinction is
operational: **cisco_iosxr declares `ntp_servers` and `syslog_servers`
SUPPORTED**, so re-authoring NTP and logging hosts on the XR side will stick.

`timezone`, `anycast_gateway_mac` and the `/vxlan-vnis/*` anchors are
different: **both** matrices declare them unsupported, a symmetric gap. Those
are `unsupported`.

`domain` is the odd one out in the other direction: cisco_iosxr declares
**nothing at all** for it — neither supported, lossy nor unsupported — yet it
round-trips cleanly on all 7 cells that populate it (the render emits
`domain name <x>`). That is a matrix under-declaration on the XR side, not a
pair-specific fact, and is left for a codec change rather than papered over
here.
