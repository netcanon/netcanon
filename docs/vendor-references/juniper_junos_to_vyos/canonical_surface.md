# Junos → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/juniper_junos__vyos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` and
the reconciler's `STRUCTURAL_ONLY` collapse rather than inferred from the drift
shape, so this file and the ratchet agree by construction. Every loss recorded
was additionally re-derived by hand —
`juniper_junos.parse()` → `vyos.render()` → `vyos.parse()` on each of the 11
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **11** (10 real Junos `.set` captures + the synthetic
  kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`juniper_junos` in this corpus is **mixed but campus/DC-leaning**: EX/QFX
switches with a large `vlans` database and `aeN` aggregates
(`ksator_labmgmt_*`, `saidvandeklundert_*`), EVPN/VXLAN leaves
(`batfish_evpntype5_*`, `tsg8139_*`), an L3VPN PE (`batfish_l3vpn_pe1`), and an
SRX-style HA firewall (`jnprautomate_mnha_vsrx_a`). Interface names are
`ge-/xe-/et-0/0/N`, `irb.N`, `lo0`, `fxp0`, `st0` and `aeN`.

`vyos` is a **Linux software router**. It has no top-level VLAN database, no
switchport model, no VRRP model, no anycast-gateway grammar, and it names
netdevs `ethN` / `ethN.vid` / `bondN` / `lo` / `dumN`.

The shared surface is therefore the **routed edge plus the management plane** —
interface identity and addressing, MTU, admin state, VRF names, static route
destinations, DNS/NTP, SNMP v1/v2c, local accounts. What does not cross is the
campus L2 surface, link aggregation, and Junos' configuration-factoring
machinery.

## The structural finding — inventory survives, the L2 estate does not

| measurement | source | after round-trip |
|---|---|---|
| interface records, all 11 cells | **151** | **151** |
| cells where the interface name set differs | — | **0** |
| VLAN records | **126** | **0** |
| LAG records | **18** | **0** |
| static-route records | **23** | **23** |
| local-user records | **13** | **13** |
| routing-instance records | **19** | **19** |
| VXLAN VNI records | **13** | **13** |
| syslog servers | **12** | **0** |
| DHCP pools | **5** | **0** |
| apply-group records | **6** | **0** |

Junos 3-segment names (`ge-0/0/0`), unit-qualified names (`irb.100`,
`st0.100`), `lo0`, `fxp0` and even `aeN` all survive the VyOS render verbatim,
because `vyos/render.py::_vyos_type_and_name` falls through to
`ethernet <name>` for anything it does not recognise. That fall-through is also
the mechanism behind the LAG loss below.

The consequence is the useful one, and it matches the `cisco_iosxr__arista_eos`
pair rather than the AOS-CX one: **every interface loss on this pair is a
genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than dragged down
by a vanishing parent. Nothing in the interface block is correlated drift.

Two parents *do* vanish wholesale — `vlans` and `lags` — and each is claimed
exactly once, at `vlans[].id` and at `lags` respectively.

## Per-field measurement (11 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 10 | 1 | 0 |
| domain | 2 | 0 | 9 |
| dns_servers | 6 | 0 | 5 |
| ntp_servers | 6 | 0 | 5 |
| syslog_servers | 0 | 6 | 5 |
| interfaces[].name / description / enabled / mtu | 11 | 0 | 0 |
| interfaces[].ipv4_addresses | 8 | 2 | 1 |
| interfaces[].ipv6_addresses | 5 | 1 | 5 |
| interfaces[].interface_type | 0 | 11 | 0 |
| interfaces[].lag_member_of | 0 | 5 | 6 |
| vlans[].* | 0 | 7 | 4 |
| static_routes | 5 | 4 | 2 |
| dhcp_servers | 0 | 2 | 9 |
| snmp.community / location / contact | 6 | 0 | 5 |
| snmp.trap_hosts | 5 | 1 | 5 |
| snmp.v3_users | 4 | 2 | 5 |
| lags | 0 | 5 | 6 |
| local_users[].name / hashed_password | 8 | 0 | 3 |
| local_users[].role | 0 | 8 | 3 |
| vxlan_vnis[].vni | 3 | 0 | 8 |
| vxlan_vnis[].vlan_id | 0 | 3 | 8 |
| routing_instances[].name | 6 | 0 | 5 |
| routing_instances[].description | 0 | 2 | 9 |
| apply_groups / group_content | 0 | 6 | 5 |

Fields trivially empty on all 11 cells: `timezone`,
`interfaces[].vrrp_groups`, `radius_servers`, `vxlan_vnis[].mcast_group`,
`evpn_type5_routes`, `raw_sections`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 149 | 151 | value → empty string |
| `lag_member_of` | 25 | 25 populated | value → null |
| `ipv4_addresses` | 10 | 59 populated | anycast virtual-gateway attrs → empty |
| `ipv6_addresses` | 6 | 18 populated | anycast virtual-gateway attrs → empty |
| `description` / `enabled` / `mtu` | 0 | 151 | — |

`interface_type` drops uniformly across every IANA type Junos emits: **99**
`ianaift:ethernetCsmacd`, **18** `ianaift:ieee8023adLag`, **16**
`ianaift:l3ipvlan`, **13** `ianaift:softwareLoopback` and **3**
`ianaift:tunnel`. The two records that "survive" carried no type on the source
side to begin with. Note that even `lo0` loses the hint: the VyOS codec
re-derives `softwareLoopback` only from the exact name `lo`, and Junos names
its loopback `lo0`, which renders as `ethernet lo0`. Both matrices already
place `/interfaces/interface/config/type` in the lossy bucket.

## Source-side gaps vs target-side drops

Three keys are recorded `not_applicable` because `juniper_junos` as a *source*
cannot emit them at all — verified in the parser, not just in the matrix:

- `vxlan_vnis[].mcast_group` — `juniper_junos/parse.py` contains no
  `multicast-group` handling; 0 of 13 VNI records carry one.
- `evpn_type5_routes` — the Junos matrix declares `/evpn-type5-routes/route`
  lossy and states why: type-5 prefixes are modelled as a VRF property
  (`CanonicalRoutingInstance.l3_vni`), not as canonical route records. 0
  records on all 11 cells.
- `raw_sections` — the string appears in `juniper_junos/parse.py` only inside a
  docstring; nothing assigns it, and it measured empty on all 11 cells. The
  VyOS `/system/raw-sections/version-banner` lossy declaration only bites with
  VyOS as the source.

Everything else that empties on this pair is a **target-side drop**, and VyOS
declares most of them at the exact path: `/system/syslog-server`,
`/dhcp-servers/pool`, `/vlans/vlan/id`, `/routing/static-route/vrf`,
`/interfaces/interface/{ipv4,ipv6}/address/virtual-gateway-address`, and the
whole `/interfaces/interface/vrrp-groups/group/*` subtree.

`timezone`, `radius_servers` and `anycast_gateway_mac` are symmetric gaps —
**both** matrices declare them unsupported — so they are `unsupported` rather
than `not_applicable`, and no committed cell populates any of them.

## The VLAN estate: 126 records, none survive

7 of 11 cells populate `vlans`, and every VLAN record disappears. This is not a
thin dot1q registry like the IOS-XR pair's — these are real campus VLAN
databases with names and trunk membership:

| cell | VLAN records |
|---|---|
| saidvandeklundert_snmpv3_junos172 | 87 |
| ksator_labmgmt_qfx5100_junos173 | 16 |
| ksator_labmgmt_ex4550_junos151 | 6 |
| ksator_labmgmt_qfx10k2_junos173 | 6 |
| batfish_evpntype5_router1_junos2541 | 4 |
| kitchen_sink | 4 |
| ksator_labmgmt_qfx5110_junos173 | 3 |

VyOS declares `/vlans/vlan/id` unsupported and explains the model difference:
it has no top-level VLAN database, expressing 802.1Q only as `vif <vid>`
sub-interfaces. Junos' matching L2 surface — `switchport_mode` on 25 interface
records and `trunk_allowed_vlans` on the same 25 — is declared unsupported by
VyOS at four separate interface paths and drops with it.

Sub-field population across those 126 source records, measured:
`name` on 126, `tagged_ports` on 120, `ipv4_addresses` on 1 (VLAN 698 on
`saidvandeklundert_snmpv3_junos172`), `untagged_ports` on 0, `description` on 0.

**Only `vlans[].id` is recorded `unsupported`.** The other five `vlans[].*`
keys are recorded `good`, and that is a bookkeeping decision rather than a
claim that VLAN names survive — they do not. The reconciler awards the
structural signal to the first sub-field of a parent list that hits it
(`run_phase4_reconciliation.py`, `structural_parent_claimed`) and reclassifies
every later sibling as `STRUCTURAL_ONLY`. A loss declared on those five could
never be evidenced, so declaring one manufactures an unevidenced over-claim
that fails the per-pair ratchet. The disappearance is real, it is recorded
once, and `vlans[].id` is where to read it.

## Four findings worth carrying forward

### 1. Link aggregation is dropped because of a name shape, and the matrix says otherwise

18 LAG records across 5 cells become **0**, and all 25 interface records
carrying a `lag_member_of` value come back null while the member ports
themselves survive — the dangerous shape, because the ports come up standalone
rather than bundled.

The mechanism is exact and reproducible.
`netcanon/migration/codecs/vyos/render.py` maps a canonical interface to a VyOS
block header with:

```python
if re.match(r"^bond\d+$", name):
    return ("bonding", name)
return ("ethernet", name)
```

Junos aggregates are named `ae0` … `ae202`, which do not match `^bond\d+$`.
They render as `ethernet ae1 { … }`, so `_bond_extra()` is never called: no
`mode 802.3ad`, no `member { interface … }` list, and no `bond-group` line on
the members. Re-parsing that output yields an ordinary interface and no LAG.
Every rendered LAG line in the corpus is of the form `    ethernet aeN {`.

**This is a capability-matrix over-declaration.** `vyos` declares
`/lags/lag/name`, `/lags/lag/members` *and*
`/interfaces/interface/lag-member-of` all **supported**, while dropping every
LAG whose name is not `bondN`. That is a codec-level fact affecting every
non-VyOS source, not a fact about this pair, and it belongs to a codec change
rather than to this file.

One honest qualifier: the mesh renders bare, and `translate_port_names` — which
would rewrite `ae1` to `bond1` — is not engaged on a bare `run_plan`. A
migration driven through `run_plan_with_overrides` may well keep the bundles.
The measurement above is of the bare path, which is what the audit scores.

`lags` and `interfaces[].lag_member_of` are both recorded `unsupported`, since
a vanished record is not lossy (#436). **They are one mechanism, not two
independent findings.** Neither is cited as evidence for the other; each is
recorded where it is measured.

### 2. Every local account is flattened to `admin` — a fail-open, measured

All 13 user records survive with their names and their password material
byte-identical. What does not survive is authorisation: **13 of 13 records lose
their Junos class**, and every one becomes `admin`.

For the `super-user` accounts that is a fair mapping. For three records it is a
privilege escalation:

| cell | account | source role | source priv | after round-trip |
|---|---|---|---|---|
| saidvandeklundert_snmpv3_junos172 | `noc-read` | `READ` | 1 | `admin`, priv 15 |
| kitchen_sink | `operator` | `operator` | 1 | `admin`, priv 15 |
| kitchen_sink | `readonly` | `read-only` | 1 | `admin`, priv 15 |

The VyOS matrix declares `/local-users/user/privilege-level` lossy and states
the cause — "the codec maps every login user to privilege…" — but declares
`/local-users/user/role` **supported**, which the measurement contradicts.

Recorded `lossy`, not `unsupported`: the account record survives inside a
concept the target models, so this is value degradation rather than a
concept-level gap. The direction is what matters. Audit the account list on the
target before cutover and demote by hand; a read-only NOC account arriving as
a full administrator is not a warning an operator should have to infer from a
`lossy` badge.

`local_users[].name` and `local_users[].hashed_password` are `good`, and
deliberately so — 13 of 13 names and 13 of 13 secrets round-trip unchanged.
Recording the role collapse a second time under either key would double-count
one loss.

### 3. Static routes survive; their VRF binding does not — and that is a route leak

A mechanical "is the target side empty?" pass over this pair reports
`static_routes` as a **total drop**. It is not: 23 routes in, 23 routes out, on
all 9 cells that carry any. What empties is `vrf`, on 5 records across 4 cells:

| cell | route | source VRF | after |
|---|---|---|---|
| batfish_evpntype5_router1_junos2541 | `0.0.0.0/0` → `10.0.0.2` | `mgmt_junos` | *(global)* |
| batfish_l3vpn_pe1_junos2541 | `0.0.0.0/0` → `10.0.0.2` | `mgmt_junos` | *(global)* |
| jnprautomate_mnha_vsrx_a_junos | `0.0.0.0/0` → `192.168.100.1` | `mgmt_junos` | *(global)* |
| jnprautomate_mnha_vsrx_a_junos | `10.0.0.3/32` → `192.168.98.1` | `ISP-2` | *(global)* |
| kitchen_sink | `10.99.0.0/16` → `10.0.0.99` | `TENANT_A` | *(global)* |

VyOS declares `/routing/static-route/vrf` unsupported, and is explicit that
per-VRF statics are deferred past the Phase-3 VRF wire-up while `vrf name`
instances themselves are supported. So the VRFs arrive, and their routes arrive
in the wrong table.

Three of those five are a management-VRF default route landing in the global
table. Recorded `lossy` because the record survives and the field the target
genuinely models — destination and next-hop — is intact, but the reason says
plainly what to check: diff the target's global table against the source's
before cutover.

Two further cells (`ksator_labmgmt_qfx10k2`, `ksator_labmgmt_qfx5100`) differ
only in route *ordering*; the audit's comparator normalises that, and so does
this file — it is not counted as drift.

### 4. The VXLAN VLAN binding is replaced by an arithmetic artifact

All 13 VNI records survive with the right `vni`, `source_interface` and
`udp_port`. Every one of them comes back with the wrong `vlan_id`:

| cell | vni | source vlan_id | after |
|---|---|---|---|
| batfish_evpntype5_router1_junos2541 | 10100 | 100 | 1912 |
| ksator_labmgmt_qfx10k2_junos173 | 22021 | 2021 | 1551 |
| kitchen_sink | 10010 | 10 | 1822 |

The rule is deterministic and holds on **13 of 13** records: the returned
`vlan_id` is exactly `vni mod 4094`. VyOS models one VNI per `vxlan vxlanN`
netdev with no VLAN on the device, so the codec synthesises the required
canonical `vlan_id` from the VNI — a declared `/vxlan-vnis/vlan-id` lossy path.

This is the shape worth flagging in a migration report: the value is not empty
and not obviously wrong. `1912` is a legal VLAN ID and reads like real
configuration. Rebuild the VLAN↔VNI bindings from the source, not from the
render.

## Two smaller notes

**`hostname` is not lost — it is invented.** On
`tsg8139_evpn_leaf_dhcpv6_junos232` the Junos source sets no `host-name` at
all; the VyOS render emits the literal line `    host-name vyos`, and the
re-parse reads it back. Source data was not destroyed; a default was
manufactured where the source was silent. That is why the YAML calls it a
declaration-shaped drift and not a content loss. The other 10 cells preserve
the hostname exactly.

**The VyOS quote rewrite did not fire on this corpus.**
`vyos/render.py` replaces embedded double quotes in a free-text value with
apostrophes, because VyOS rejects embedded quotes in value strings even when
escaped (vyos.dev/T1246). It is the right thing to check first when a
description drifts on a VyOS target. Here it is not the cause of anything: of
**84** populated interface descriptions across the corpus, **0** contain an
embedded double quote, and `interfaces[].description` drifts on **0 of 151**
records. `interfaces[].description` is `good` on measurement, not on
assumption.

## Apply-groups: the container is lost, the configuration is not

`apply_groups` and `group_content` each drop on 6 cells — `MNHA-SYNC`,
`POC_Lab` (×4) and `GLOBAL-SETTINGS`. VyOS has no `groups` / `apply-groups`
grammar, so both are recorded `unsupported`.

The distinction that matters operationally: the Junos matrix declares `/groups`
lossy and states that apply-group *inheritance* is wired through a two-pass
parse. It is, and the inherited values do reach the target. On
`ksator_labmgmt_qfx5110_junos173` the entire management plane is defined inside
`groups POC_Lab` — hostname, name-server, NTP server, SNMP community, syslog
host, the `lab` login account and a default static route — and after the
round-trip the target carries hostname `QFX5110-169`, name-server
`172.29.131.60`, NTP `66.129.255.62`, community `public`, the `lab` account and
the `0.0.0.0/0` route. What is lost is the factoring: the group definition and
the `apply-groups` reference. The config arrives flattened.

The one inherited item that does *not* arrive is the syslog host, and that is
`syslog_servers` — a separate, separately-recorded target-side gap, not
evidence about apply-groups.

These two keys are one Junos mechanism viewed from two canonical fields.
Neither is cited as evidence for the other.

## Credential material

No hash body, USM passphrase blob or vendor ciphertext is reproduced in this
file or in the expectation YAML — only crypt-scheme markers, envelope prefixes
and lengths. Per `AGENTS.md`, password hashes are operator-traceable even when
they are hashes, and a document that quotes the value it describes defeats its
own redaction.

Shape of the 13 local-user secrets, source side, all 13 byte-identical after
the round-trip:

| envelope | crypt marker | body length | records |
|---|---|---|---|
| `junos:` | `$1$` (crypt-MD5) | 31 | 4 |
| `junos:` | `$6$` (SHA-512 crypt) | 95 | 2 |
| `junos:` | `$6$` | 37 | 1 |
| `junos:` | `$6$` | 27 | 1 |
| `junos:` | *(none — not a crypt hash)* | 2 | 4 |
| *(empty)* | — | 0 | 1 |

The four records with no crypt marker are on
`saidvandeklundert_snmpv3_junos172`, whose committed capture carries a
sanitisation placeholder in place of a real secret. They are noted here only so
the table sums to 13; nothing about them is a target-side finding.

SNMPv3 is the one place where credential handling degrades. 4 USM users across
2 cells; the auth and privacy keys round-trip verbatim as opaque Junos `$9$`
vendor-reversible blobs, which is itself worth knowing — a `$9$` blob is not a
valid VyOS `encrypted-password`, so v3 polling will fail on the target until
the users are re-keyed. On top of that, 3 of the 4 records lose algorithm
strength:

| cell | user | auth | privacy |
|---|---|---|---|
| saidvandeklundert_snmpv3_junos172 | POLLER-1 | `sha` → `sha` | `aes128` → `aes` |
| saidvandeklundert_snmpv3_junos172 | POLLER-2 | `sha` → `sha` | `aes128` → `aes` |
| kitchen_sink | readonly_v3 | `sha256` → `sha` | `aes256` → `aes` |
| kitchen_sink | monitor | `md5` → `md5` | `des` → `des` |

VyOS declares both `/snmp/v3-user/auth-protocol` and
`/snmp/v3-user/priv-protocol` lossy and names this exact downgrade. `sha256` →
`sha` is SHA-256 to SHA-1. Re-create SNMPv3 users on the target and pick the
algorithms explicitly.

`snmp.trap_hosts` is a separate, smaller gap: 2 trap destinations on
`kitchen_sink` become 0, and **neither** matrix declares `/snmp/trap-host` at
any level. That undeclared path is a second matrix gap on the VyOS side,
recorded here for the same reason as the LAG over-declaration — as a standing
observation belonging to a codec change, not to this file. The three declared
SNMP scalars (`community`, `location`, `contact`) round-trip cleanly on all 6
cells that populate them.

## Where the L3VPN control plane goes

`routing_instances` is the pair's other "total drop" misreading. 19 instances
in, 19 out, names preserved on all 6 cells — `TENANT-A`, `CUSTOMERS`,
`mgmt_junos`, `APP3`, `DCI-VRF`, `INTERNET`, `Tenant-A-1`, `RTR_C` and the
rest. What empties inside the surviving records is the control-plane plumbing:
`route_distinguisher` and both route-target lists on 10 records, `l3_vni` on 6,
`instance_type` (`virtual-router` / `mac-vrf` → `vrf`) on 7, and `description`
on 4.

Only `routing_instances[].description` is a key in the expectation file, and it
is `lossy`: `MANAGEMENT_VRF`, `Tenant A L3 VRF`, `Tenant B L2 mac-vrf` and
`Lightweight virtual router for transit` all return empty while their instances
survive. Neither matrix declares a
`/routing-instances/instance/description` path at all, so that disposition
rests on the measurement, not on a declaration — the YAML says so.

The RD / route-target / L3VNI loss is real and larger, but it has no key in the
canonical field list this file walks, so it is recorded here as context and
nowhere claimed as evidence for the description finding. On a PE migration it
is the thing to re-author first.
