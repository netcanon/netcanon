# FortiGate CLI → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/fortigate_cli__vyos.yaml`.

**Source of every number here:** hand round-trips of the committed corpus —
`fortigate_cli.parse()` → `vyos.render()` → `vyos.parse()` on each of the 4
fixtures — cross-checked against the two codecs' `CapabilityMatrix`
declarations. Per-key dispositions were resolved through the audit's own
`actual_disposition()` rather than inferred from the drift shape, so this file
and the ratchet agree by construction. No claim below rests on the drift shape
alone.

- Fixture cells: **4** (3 real captures + `kitchen_sink.conf`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the committed fixtures, and hand round-trips of them. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`fortigate_cli` in this corpus is a **branch / hub NGFW**: `port1`…`portN`
physical ports, a `fortilink` FortiSwitch uplink, LACP aggregates with free-form
names, VLAN child-interfaces named after their purpose (`VL_100`,
`cluster-vlan`), blackhole routes, DHCP scopes served on the inside interfaces,
and RADIUS-backed administrator accounts. `vyos` is a **Linux software router**.

The realistic migration is a FortiGate being replaced at the edge by a VyOS
appliance, so the shared surface is the **routed plane** — interface inventory,
addressing, descriptions, admin state, gateway'd static routes, SNMP identity,
local account names and their stored credentials. What does not cross is
everything the firewall was doing *as a firewall*: the VLAN database, the LAG
surface, DHCP scopes, RADIUS, trap destinations, blackhole routing, and every
notion of *authority* on a local account.

## The structural finding — two halves, in opposite directions

### The interface inventory is fully preserved

| measurement | value |
|---|---|
| source interface records, all 4 cells | **86** |
| records after parse → render → re-parse | **86** |
| cells where the interface name set differs | **0** |

`port1`, `wan1`, the single-letter FortiSwitch ports `a` / `b`, `loopback0`,
`agg1`, the dotted child-interfaces `agg1.100` / `port4.300` and the named VLAN
interfaces `VL_100` / `cluster-vlan` all survive the VyOS render under the same
name. The consequence is the useful one: **every interface loss on this pair is
a genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than dragged down by
a vanishing parent.

### The VLAN database vanishes whole

10 VLAN records across the 3 cells that carry them become **0**. That is ONE
structural loss with ONE cause, so it is claimed exactly once — on `vlans[].id`
— and the five sibling `vlans[].*` keys are `good`. Recording a loss on each of
them would count one disappearance six times and could never be evidenced
independently.

Be precise about what does survive: the FortiGate VLAN child-interface `VL_100`
comes back as an interface record called `VL_100` with its `192.168.100.1/24`
intact. **The INTERFACE survives; the VLAN DATABASE RECORD does not** — and
neither does the 802.1Q tag, because *both* codecs declare
`/interfaces/interface/dot1q-vlan` unsupported. The migrated box has an
interface named after a VLAN that is not on a VLAN.

## Per-field measurement (4 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 4 | 0 | 0 |
| domain | 1 | 0 | 3 |
| dns_servers | 4 | 0 | 0 |
| ntp_servers | 1 | 0 | 3 |
| interfaces[].name / description / enabled / mtu / ipv4_addresses / ipv6_addresses | 4 | 0 | 0 |
| interfaces[].interface_type | 0 | 4 | 0 |
| interfaces[].lag_member_of | 0 | 3 | 1 |
| vlans[].* | 0 | 3 | 1 |
| static_routes | 0 | 3 | 1 |
| dhcp_servers | 0 | 4 | 0 |
| snmp.community / location / contact | 2 | 0 | 2 |
| snmp.trap_hosts | 0 | 2 | 2 |
| snmp.v3_users | 1 | 1 | 2 |
| lags | 0 | 4 | 0 |
| local_users[].name / hashed_password | 4 | 0 | 0 |
| local_users[].role | 0 | 4 | 0 |
| radius_servers | 0 | 2 | 2 |

Fields trivially empty on all 4 cells: `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, all three `vxlan_vnis[].*` keys,
`evpn_type5_routes`, both `routing_instances[].*` keys, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 86 | 86 | value → empty string |
| `lag_member_of` | 12 | 12 populated | value → null |
| `description` | 0 | 24 populated | — |
| `enabled` | 0 | 4 shut records | — |
| `mtu` | 0 | 1 populated | — |
| `ipv4_addresses` | 0 | 44 populated | — |
| `ipv6_addresses` | 0 | 3 populated | — |

`interface_type` drops with **zero survivors of any type**: 68
`ianaift:ethernetCsmacd`, 10 `ianaift:l3ipvlan`, 7 `ianaift:ieee8023adLag` and
the single `ianaift:softwareLoopback` all go to the empty string. The mechanism
is stated in the vyos matrix and confirmed in `_vyos_type_and_name()`
(`netcanon/migration/codecs/vyos/render.py`): VyOS declares no IANA ifType, so
the codec re-derives one from the interface-NAME shape — `lo` →
softwareLoopback, `dum\d+` → dummy, `bond\d+` → ieee8023adLag, and *everything
else* → ethernet. Because the render preserves FortiGate names verbatim, none
of `port1` / `agg1` / `loopback0` / `VL_100` matches those shapes.

Note the near-miss: `loopback0` is not `lo`, so even the loopback loses its
type. On the IOS-XR → EOS pair every loopback survived, because EOS re-derives
the type from `interface Loopback<N>`. Same canonical field, opposite outcome,
for a reason that is entirely about naming.

## Source-side gaps vs target-side drops

`fortigate_cli` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for VyOS to lose:

`/vxlan-vnis/{vni,source-interface,udp-port}` ·
`/routing-instances/instance` · `/routing-instances/instance/instance-type` ·
`/anycast-gateway-mac` · `/system/timezone` · `/system/syslog-server` ·
`/interfaces/interface/{dot1q-vlan,trunk-allowed-vlans}` ·
`/vlans/vlan/{tagged-ports,untagged-ports}`

Neither codec declares any `/evpn-type5-routes/*` path at all, and neither
declares `/apply-groups` or `/group-content`; all three are empty on every cell.

Most of these are recorded `not_applicable`, not `unsupported`, and the
distinction is operational: for the VXLAN and routing-instance families **vyos
declares the field SUPPORTED** (`/vxlan-vnis/vni`, `/vxlan-vnis/mcast-group`,
`/vxlan-vnis/udp-port`, `/routing-instances/instance/name`), so re-authoring
them on the target will stick and the migration report should say so.

Three are different and are recorded `unsupported`, because **both** matrices
declare them unsupported — a symmetric gap, not a VyOS limitation:
`/system/timezone`, `/system/syslog-server`, `/anycast-gateway-mac`.

One more is a pure target-side block on a surface the source *can* emit:
`fortigate_cli` declares `/interfaces/interface/vrrp-groups/group` SUPPORTED
(with five lossy sub-paths for VIP lists, tracking, virtual-MAC and mode),
while `vyos` declares the entire group subtree unsupported — "VyOS VRRP /
VRRPv3 is not modelled by the codec; the group is dropped on migration". No
committed cell populates VRRP, so that one rests on the declarations.

## Five findings worth carrying forward

### 1. The LAG surface drops — and it is a NAME-SHAPE gate, not a concept gap

7 LAG records across all 4 cells become **0**, and all 12 interface records
carrying a `lag_member_of` pointer come back null. The rendered `config.boot`
contains no `interfaces bonding` node and no `member` list on any cell — the
only occurrences of the string `bond` anywhere in the corpus renders are inside
interface *descriptions* (`"downstream-bond"`, `"passive-bond"`).

This is the known `lags` trap on this mesh, so it was probed rather than read
off the drift counts. The probe went one step further than the sibling pairs and
isolated the cause:

| intent | LAG names | `lags` in → out | `lag_member_of` in → out | `bonding` node |
|---|---|---|---|---|
| `kitchen_sink.conf` as parsed | `agg1`, `agg2` | 2 → **0** | 4 → **0** | absent |
| same intent, renamed in memory | `bond1`, `bond2` | 2 → **2** | 4 → **4** | emitted, with `mode 802.3ad` and the `member { interface … }` list |

Same codec, same data, only the name changed. `_vyos_type_and_name()` emits a
`bonding` block **only** for a name matching `^bond\d+$`; a LAG called
`fortilink`, `LAG_INTERNAL`, `lacp trunk`, `agg1` or `agg2` is emitted as an
ordinary `ethernet <name>` block, the `member` list is never written, and the
vyos parser — which builds `CanonicalLAG` only from `interfaces bonding` — finds
nothing to re-parse.

The dangerous shape is that the member ports themselves survive: they come up
standalone rather than bundled, under a name that will not exist on a VyOS box.

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported`, since a
vanished record is not lossy (#436) and `lossy` — which warns but stays
compatible — would badly understate losing every aggregate on an edge firewall.
**They are one mechanism, not two independent findings.** Neither is cited as
evidence for the other; each is recorded where it is measured.

Matrix observation, left to a codec change rather than fixed here: `vyos`
declares `/lags/lag/name`, `/lags/lag/members` and
`/interfaces/interface/lag-member-of` SUPPORTED and `/lags/lag/mode` lossy, then
delivers zero from this source. That is a target **over-declaration** — the
matrix promises a surface the render only reaches for `bondN`-shaped names. It
is the same finding the `arista_eos → vyos` pair recorded; the rename experiment
above is the added detail. `fortigate_cli` declares nothing for `/lags/lag` at
all, which is the mirror-image under-declaration on the source side.

The operator remedy is correspondingly cheap: rename aggregates to `bondN`
before rendering and the whole surface crosses.

### 2. Passwords survive; authority does not, and it fails OPEN

8 accounts across the 4 cells. **Every account name survives** and **every
stored credential survives byte-identical** — 6 of the 8 carry one, and all 6
round-trip unchanged; the other 2 carry none in the source.

Every `role` collapses to the literal `admin`:

| source role | accounts | outcome |
|---|---|---|
| `super_admin` | 4 | → `admin` |
| `fortigate_ro` | 1 | → `admin` |
| `fortigate_admins` | 1 | → `admin` |
| `super_admin_readonly` | 1 | → `admin` |
| `prof_admin` | 1 | → `admin` |

Two of those are **read-only** administrators on the FortiGate side and arrive on
VyOS as full administrators. The companion `privilege_level` field moves the
same way on the same 4 records (1 → 15). That is the SAME mechanism, stated for
completeness, not independent corroboration of it.

`vyos` declares `/local-users/user/role` SUPPORTED while flattening every role —
an under-declaration on the target — and separately declares
`/local-users/user/privilege-level` LOSSY with the honest reason: VyOS
`system login user` accounts have no numeric privilege level in the common case,
so the codec maps every login user to privilege 15 / role `admin`.

Recorded `lossy`, not `unsupported`: the account record survives and the target
models roles, so the value degrades rather than vanishing (#436).

Read the two keys together. This pair carries accounts across with **working
stored credentials and rights they did not have**. A migration that silently
PROMOTES a read-only operator is more dangerous than one that drops the account,
because nothing looks wrong afterwards. Review every migrated account's
authority before cutover.

### 3. Blackhole routes vanish; surviving routes lose their egress interface

4 canonical static routes enter the pair across 3 cells. Two different things
happen to them:

| shape | count | outcome |
|---|---|---|
| FortiOS `set blackhole enable` discard route (no gateway, no device) | 2, on 2 cells | **record vanishes** — no `protocols static` node is rendered at all |
| gateway'd route with a `device` binding | 2, on `kitchen_sink.conf` | record survives with destination + gateway; `interface` goes `port1` → `""` and `agg1` → `""` |

The mechanism is visible in the render: VyOS routes are emitted as
`route <dst> { next-hop <gw> { } }`, so a canonical route with an empty gateway
has nothing to emit, and no `interface` sub-node is written for the routes that
do render. The discard semantics were already gone one step earlier —
`CanonicalStaticRoute` carries `destination`, `gateway`, `interface`, `metric`,
`description` and `vrf`, and has no blackhole flag — so a FortiOS discard route
arrives at the renderer indistinguishable from a route whose next-hop failed to
parse.

Declaration coverage is thin on both ends: `fortigate_cli` declares
`/routing/static-route/interface` SUPPORTED, and `vyos` declares no path for the
route interface at any level while dropping it. That is a target
under-declaration of the same shape as the trap-host gap below.

Recorded `unsupported`: half the records vanish outright with no target grammar
to land in (#436). Re-author discard routes as VyOS `blackhole` next-hops by
hand, and re-add the egress-interface binding on the routes that do survive.

Worth stating so the numbers are not over-read: the source parser already
reduces the FortiOS block before the pair sees it. `kevinguenay_fgt_vm_hub.conf`
carries five `config router static` stanzas and yields **one** canonical route —
the others use named address-group destinations (`set dstaddr`) or carry no
`set dst`. That reduction is a source-side property, not a loss this pair
causes, and it is not counted as one.

### 4. SNMP identity crosses; trap destinations do not, and v3 downgrades

2 of the 4 cells carry an SNMP block. Community, location and contact all
round-trip cleanly on both.

**Trap hosts vanish.** 1 host on `user_contrib_fg100e_fos7213.conf` and 2 on
`kitchen_sink.conf` become zero. Verified by reading the render rather than the
drift counts: the emitted `service snmp` node contains community, contact,
location and the v3 users, and **no trap-target node of any kind** — the string
`trap` does not appear in any of the four rendered configs.
`fortigate_cli` declares `/snmp/trap-host` SUPPORTED; `vyos` declares **no path
for trap hosts at any level** — not supported, not lossy, not unsupported —
while dropping them entirely. That is a target matrix under-declaration and
belongs to a codec change rather than to this file. Recorded `unsupported`, and
verify at the NMS after cutover: this failure is invisible from the device.

**v3 users survive, their algorithms degrade.** Both users on
`kitchen_sink.conf` come back with their names, their groups and their opaque
auth/privacy key blobs carried verbatim. What changes is the ALGORITHM, in the
unsafe direction: `auth_protocol` sha256 → sha and sha512 → sha (SHA-1);
`priv_protocol` aes256 → aes on both. `vyos` declares
`/snmp/v3-user/auth-protocol` and `/snmp/v3-user/priv-protocol` LOSSY and names
it exactly that — a cryptographic downgrade, because `auth type` renders only
md5/sha and `privacy type` only bare des/aes, so key-length variants lose their
strength on render. It also declares both passphrases and the engine-id lossy:
the VyOS keys are opaque `encrypted-password` blobs that round-trip verbatim
same-vendor but require re-keying cross-vendor. Recorded `lossy` — the records
survive and the target models v3. Re-key every v3 user on the target.

### 5. DHCP, RADIUS, and the accounts left with nothing to authenticate against

10 DHCP scopes across all 4 cells become **0**; `vyos` declares
`/dhcp-servers/pool` unsupported ("Render emits no DHCP server pool"). Verified
against a false positive: the string `dhcp-server` DOES appear in the rendered
output, but only inside the `// vyos-config-version` component-version trailer —
there is no DHCP configuration node.

3 RADIUS servers across 2 cells become **0**; `vyos` declares
`/radius-servers/server/host` and `/radius-servers/server/key` unsupported
("Render emits no RADIUS config; the RADIUS shared secret is dropped on
migration"). Unlike most gaps on this pair, re-authoring RADIUS on the VyOS side
will not stick either — configure AAA outside the migration path.

Those two combine into an operational hazard worth stating once, explicitly as a
consequence and **not** as evidence for any of the three keys involved. On
`user_contrib_fg100e_fos7213.conf` the accounts `radius_ro_admin` and
`radius_super_admin` carry no local credential — they are RADIUS-backed. After
the round-trip they exist on the target with an empty password, role `admin`,
and no RADIUS server to authenticate them. Each of the three losses is recorded
on the key where it is measured; this paragraph is the join, and the join is
what an operator needs before cutover.

## Credential material

No credential body is reproduced in this file or in the expectation YAML. The
FortiGate secrets on this corpus are opaque vendor `ENC` blobs, not
`$`-prefixed crypt hashes — 41 to 226 characters — and only that shape, the
account name and the round-trip verdict are described. The same applies to the
SNMPv3 auth and privacy keys: algorithm labels and blob shape only.

Per `AGENTS.md`, password material is operator-traceable even when it is
hashed, and a document that quotes the value it describes defeats its own
redaction.

One honesty note that belongs next to the `good` on
`local_users[].hashed_password`: preserved is not the same as usable. The blob
is carried verbatim into VyOS `system login user … encrypted-password` under
the codec's own vendor-tag marker, and the vyos matrix says plainly that
cross-vendor migration requires re-keying. This audit scores **preservation**,
not target-syntax validity. Set passwords on the target before cutover anyway.

## Two drift-shape readings that are wrong

**`static_routes` is not a clean total drop.** A mechanical "is the target side
empty?" pass calls the whole field gone. On `kitchen_sink.conf` both routes
survive with destination and gateway intact; what they lose is the egress
interface. The `unsupported` disposition is earned by the two blackhole routes
on the other two cells, not by a uniform disappearance.

**`lags` is not a target concept gap.** The same mechanical pass calls VyOS
unable to model aggregation. It models it fine — the render simply never reaches
the `bonding` branch for a name that is not `bondN`. Section 1 above shows the
same intent crossing intact after an in-memory rename. The disposition stays
`unsupported` because that is what the *measured, bare* render does, but the
reason recorded is the naming gate, not an absent concept.

## One measured drift no audited key covers

`interfaces[].dhcp_client_v6` drifts on 2 records on
`kevinguenay_fgt_70g_branch.conf`: the FortiOS token `dhcp6` re-parses from the
VyOS render as `dhcpv6`. Both codecs declare
`/interfaces/interface/dhcp-client-v6` supported, and the render line is
`address dhcpv6`, so this is a vocabulary normalisation rather than a lost
setting — the interface still requests a DHCPv6 address.

It is recorded here and nowhere else because the audited key list has no entry
for it. It is noted so a future reader who reproduces the round-trip and sees a
non-zero interface drift beyond `interface_type` and `lag_member_of` knows what
it is.
