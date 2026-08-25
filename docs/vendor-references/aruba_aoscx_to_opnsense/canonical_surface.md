# AOS-CX → OPNsense: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__opnsense.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus
direct `aruba_aoscx.parse → opnsense.render → opnsense.parse` round-trips over
all 7 cells for the calls the drift shape alone could not settle. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`aruba_aoscx` in this corpus is a **campus / small-DC access-aggregation
switch** — every cell is an L2 switch with VLANs, SVIs, LACP uplinks and a
switchport on every port, and three cells carry a VXLAN overlay. `opnsense` is
a **BSD firewall / routing appliance**: no switching fabric, no VRF, no
overlay, and an XML configuration file rather than a CLI.

The realistic migration is therefore not a like-for-like swap. It is an AOS-CX
aggregation switch replaced at the routed boundary by an OPNsense box that
inherits the port inventory, the LACP bundles, the SVI subnets and the admin
identity — while the L2 switching it sat on top of stays behind.

## The structural finding — nothing structural is lost

Read this first, because it inverts the reflex the other `aruba_aoscx` pairs
train. On `aruba_aoscx__arista_eos` the interface inventory **shrinks**; on
`aruba_aoscx__fortigate_cli` it **grows**. Here it is preserved **exactly**:

| cell | source ifaces | target ifaces | VLANs | LAGs |
|---|---|---|---|---|
| `aoscx_dcn_arch3_ebgp_leaf1a` | 9 | 9 | 2 → 2 | 1 → 1 |
| `aoscx_dcn_arch3_ibgp_leaf1a` | 9 | 9 | 2 → 2 | 1 → 1 |
| `aoscx_dcn_arch4_core1_1` | 18 | 18 | 4 → 4 | 5 → 5 |
| `aoscx_dcn_arch4_core1_2` | 42 | 42 | 4 → 4 | 5 → 5 |
| `canu_csm17_spine001_ipv6_vrf` | 22 | 22 | 8 → 8 | 4 → 4 |
| `netutils_aoscx_snmpv3_glcx1009` | 44 | 44 | 6 → 6 | 16 → 16 |
| `kitchen_sink` (synthetic) | 13 | 13 | 4 → 4 | 2 → 2 |
| **total** | **157** | **157** | **30 → 30** | **34 → 34** |

**No parent record count changes anywhere in the corpus.** The consequence
matters more than the fact: the correlated-drift trap — one shrinking list
making all nine `interfaces[].*` keys measure as drifted for a single reason —
**does not apply on this pair**. Every `good` below is a real observation about
a real surviving record, and every `lossy` is an independent per-attribute
measurement taken on records that exist on both sides.

### Interface sub-fields, measured independently

| sub-field | records drifted (of 157) | what happened |
|---|---|---|
| `name` | **0** | verbatim — `1/1/1`, `lag 1`, `vlan 4000`, `loopback 0` |
| `description` | **0** | `<descr>`; nothing truncated |
| `enabled` | **0** | `<enable/>` present / absent |
| `mtu` | **0** | jumbo values kept (`<mtu>9198`) |
| `ipv6_addresses` | **0** | only 2 records carry IPv6 corpus-wide (one SVI each on `canu_csm17_spine001_ipv6_vrf` and `kitchen_sink`); neither drifts |
| `lag_member_of` | **0** | all 44 member ports keep their bundle |
| `ipv4_addresses` | **15 of 41 populated** | address kept; `virtual_gateway_address` companion dropped |
| `interface_type` | **157 of 157** | every canonical ifType → empty string |
| `vrrp_groups` | n/a | AOS-CX declares the whole subtree unsupported; 0 groups exist |

Separately, and **on records present on both sides**, the switchport surface is
wiped: `switchport_mode` on **64** records, `trunk_native_vlan` on **34**,
`access_vlan` on **30**, `trunk_allowed_vlans` on **23**. All four canonical
paths are declared `unsupported` by `opnsense` — "OPNsense (BSD) has no
Cisco-style access/trunk port mode; dropped on render". This is the
independent, per-record proof behind the `unsupported` call on
`vlans[].untagged_ports` / `vlans[].tagged_ports`, and on this pair it really
is independent — there is no record-count effect for it to be confused with.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces[].name / description / enabled / mtu / lag_member_of | 7 | 0 | 0 |
| interfaces[].ipv6_addresses | 2 | 0 | 5 |
| interfaces[].ipv4_addresses | 2 | 5 | 0 |
| interfaces[].interface_type | 0 | 7 | 0 |
| vlans[].id / name | 7 | 0 | 0 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].untagged_ports | 0 | 7 | 0 |
| vlans[].tagged_ports | 0 | 5 | 2 |
| vlans[].description | 0 | 4 | 3 |
| static_routes | 0 | 2 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 2 | 2 | 3 |
| lags | 7 | 0 | 0 |
| local_users[].name | 6 | 0 | 1 |
| local_users[].role / hashed_password | 0 | 6 | 1 |
| vxlan_vnis[].vni / vlan_id / mcast_group | 0 | 3 | 4 |
| routing_instances[].name / description | 0 | 3 | 4 |
| anycast_gateway_mac | 0 | 5 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`interfaces[].vrrp_groups`.

Corpus totals for the surfaces that lose content:

- VLAN records with an L3 mount: **18 → 0** (relocated — see below)
- `virtual_gateway_address` values at the VLAN mount: **15 → 0** (dropped)
- `untagged_ports` entries: **64 → 0** (13 VLAN records)
- `tagged_ports` entries: **32 → 0** (11 VLAN records)
- VLAN descriptions: **6 → 0**
- static routes: **3 → 0** (2 cells)
- VRFs: **6 → 0** (3 cells) · interface `vrf` bindings: **10 → 0**
- VXLAN VNIs: **4 → 0** (3 cells)
- SNMPv3 users: **2 → 0** (2 cells)

## Total drop vs degradation — the calls that needed a round-trip

`lossy` warns and stays compatible; `unsupported` blocks (netcanon #436, "a
vanished record is not lossy"). Four keys looked like total drops from the
drift shape and are **not**:

**1. `vlans[].ipv4_addresses` — relocation, not loss.** The VLAN mount is empty
on the target for all 18 populated records. The round-trip shows every one of
those 18 prefixes present on the sibling interface record. From the `core1_1`
render — the AOS-CX SVI arriving as a plain interface:

```xml
    <vlan_101>
      <if>vlan 101</if>
      <descr>PROD-WEB-SVI</descr>
      <ipaddr>10.12.101.2</ipaddr>
      <subnet>24</subnet>
    </vlan_101>
```

`opnsense` declares `/vlans/vlan/ipv4/address/ip` **lossy** for exactly this
reason ("Renders VLAN SVI / management L3 only from a sibling interface
stanza"). Signal and declaration agree once you look at where the address
went. Recorded `lossy`: `unsupported` would tell an operator the subnet does
not migrate, which is false and is the more damaging error. What *is* genuinely
gone is the anycast companion — 15/15 `virtual_gateway_address` values.

**2. `vlans[].description` — a surviving record, an emptied scalar.** The
vanish classifier calls this a total drop because all 6 populated descriptions
land as `''`. The VLAN record survives with its id *and* its name, so nothing
is blocked, and `opnsense` declares `/vlans/vlan/description` **lossy** in its
own matrix. The classifier is record-blind; the two signals only appear to
disagree. The mechanism is visible in the render: the single `<descr>` element
per VLAN entry is occupied by the VLAN **name**, so the canonical description
has no second slot.

**3. `interfaces[].interface_type` — total for the attribute, harmless for the
record.** All 157 canonical types arrive as the empty string, because
OPNsense's `<interfaces>` grammar has no ifType element for the renderer to
write. `aruba_aoscx` declares `/interfaces/interface/config/type` lossy in its
own right; `opnsense` declares nothing at that path (see the under-declaration
section). Recorded `lossy` rather than `unsupported` deliberately: the
interface record round-trips complete and usable, so `warn` + compatible is the
honest operator signal, whereas `block` would stop the migration whose
interface inventory otherwise round-trips 157 of 157 records intact.
Cosmetic for
forwarding; real for inventory tooling that filters on canonical type.

**4. `local_users[].hashed_password` — re-labelled, not dropped.** See the
credential section.

Conversely, **seven surfaces are real total drops**, each with the target's own
matrix entry agreeing:

| key | measured | target declaration |
|---|---|---|
| `static_routes` | 3 routes → 0; no `<staticroutes>` and no `<gateways>` in the render | `/routing/static-route` + all 5 children unsupported |
| `routing_instances[].*` | "all 2 routing_instances dropped" on 3 cells; 10 interface `vrf` bindings lost | `/routing-instances/instance` unsupported |
| `vxlan_vnis[].*` | 4 VNIs → 0 on 3 cells | `/vxlan-vnis/vni` unsupported — "VXLAN not modelled — OPNsense is a firewall codec" |
| `vlans[].untagged_ports` | 64 entries → 0, plus 64 interface records stripped | `/vlans/vlan/untagged-ports` unsupported |
| `vlans[].tagged_ports` | 32 entries → 0 | `/vlans/vlan/tagged-ports` unsupported |
| `snmp.v3_users` | 2 users → 0 on 2 cells | `/snmp/v3-user` unsupported |
| `anycast_gateway_mac` | scalar → `''` on 5 of 5 populated cells | `/anycast-gateway-mac` unsupported |

### The static-route drop is the #436 case study

This exact surface is why the doctrine exists. While `/routing/static-route`
sat declared `lossy`, a plan over this codec reported `severity=warn,
compatible=True` — actively calling the migration **compatible** while
discarding the entire routing table. It is `unsupported` here for the same
reason. Measured: the kitchen sink's default route and `10.99.0.0/16` at
metric 200, and the `canu` default route, all vanish; the rendered
`config.xml` contains no `<staticroutes>` block at all.

### The VLAN parent-binding hazard (verify before you apply)

OPNsense binds a VLAN to **one** parent sub-interface. On
`aoscx_dcn_arch4_core1_1`, VLAN 4000 is tagged on both `lag 101` and `lag 102`
on the source and renders as a single entry:

```xml
    <vlan>
      <if>lag 101</if>
      <tag>4000</tag>
      <pcp>0</pcp>
      <proto/>
      <descr>CORE-ROUTING</descr>
      <vlanif>lag 101_vlan4000</vlanif>
    </vlan>
```

The second bundle's membership is simply absent. Check the parent chosen for
every VLAN child before pushing the config, and rebuild trunk membership on
whatever L2 switching remains behind the firewall.

## Source-side gaps vs symmetric gaps

AOS-CX declares these **unsupported at the exact path**, so as a *source* it
never emits them:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/system/timezone` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` · `/radius-servers/server/key` ·
`/snmp/trap-host` · the whole `/interfaces/interface/vrrp-groups/group/*`
subtree

The split in the YAML is not cosmetic. For `domain` and `dns_servers`,
**`opnsense` declares the field SUPPORTED** — the gap is one-sided, and
re-authoring on the target will stick. Those are `not_applicable`.

Three are **symmetric** — the target drops them too, so "re-author it on the
target" is advice that does not work. Those are `unsupported`:

- `/system/ntp-server` — "Render emits no `<system><timeservers>`;
  intent.ntp_servers are dropped on migration."
- `/system/timezone` — "Render emits no time-zone stanza."
- `/system/syslog-server` — "Render emits no remote-syslog config."

*(Note that `syslog_servers` is `not_applicable` on `aruba_aoscx__arista_eos`,
where EOS supports the field. Read the target column, not the source column,
before copying a disposition between pairs.)*

`dhcp_servers` and `radius_servers` are `not_applicable` with a weaker
guarantee still: `opnsense` declares **no path at all** under either field, so
there is no in-repo statement that a re-authored pool or RADIUS server would
render.

## Two matrix declarations that do not match the measurement

Neither is fixed here — this is an expectation file, not a codec change — but
both should be carried forward.

**1. `lags` is under-declared on the target.** `opnsense` declares nothing
*supported* under `/lags/lag`; its only entry is `/lags/lag/mode` lossy. The
surface nevertheless round-trips perfectly: **34 LAG records and 44 member
ports across all 7 cells, identical on name, members and mode**, verified by
re-parsing the render.

```xml
    <lagg>
      <laggif>lag 1</laggif>
      <members>1/1/1,1/1/2</members>
      <proto>lacp</proto>
    </lagg>
```

The one lossy declaration is real but **unexercised by this corpus**: "OPNsense
`lagg` uses a single `lacp` proto with no active/passive distinction, so a
`passive` LACP bundle re-parses as `active`". Measured mode distribution across
all 34 bundles is 33 `active` and 1 `static`, with zero mode drift — there is
no passive bundle here to lose. A source fleet that uses passive LACP will hit
that, and this pair's `good` does not cover it.

**2. `/interfaces/interface/config/type` is undeclared on the target.**
`opnsense` lists it neither supported, lossy nor unsupported, while emitting no
ifType at all — 157 of 157 records come back empty. The YAML records `lossy`
(the record survives) and flags the gap.

## Identity: roles and credentials

**Roles are remapped, not lost.** The AOS-CX `administrators` role renders to
the OPNsense `admins` group and re-parses as `admin`; `operators` maps to
`user` (measured on `kitchen_sink`, which carries both). The privilege intent
is preserved and arguably correct — but the canonical string changes, so any
downstream tooling keyed on the literal role name stops matching, and an
OPNsense `admin` has unrestricted access to a box that is now the security
boundary.

**Credentials do not migrate.** `local_users[].hashed_password` drifts on all 6
populated cells. AOS-CX stores the user secret in its own encrypted form — an
`AQB…`-prefixed ciphertext blob — and the OPNsense renderer writes that blob
verbatim into `<system><user><password>`. Re-parsing labels it as a bcrypt
hash: the canonical string grows by exactly the 7 characters of a `bcrypt:`
scheme prefix on every user on every cell and is otherwise byte-identical.

The bytes survive; the *meaning* does not. OPNsense authenticates `<password>`
as a crypt-format hash (the `$2y$` bcrypt shape). An ArubaOS-CX ciphertext
blob sitting in that element, labelled bcrypt, is not a password any OPNsense
box can ever verify.

Every migrated account therefore arrives **without a working credential**. Set
passwords on the target before cutover, or you will be locked out of the
firewall you just migrated.

The ciphertext values are deliberately not reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction. The same applies to the SNMPv3 auth and privacy passphrases
and to the SNMP community string.

## SNMP

`snmp.community`, `snmp.location` and `snmp.contact` are preserved on all 4
cells where the SNMP record is populated. Read that precisely: a non-empty
community is observed and preserved on **1** cell and non-empty
location/contact on **3**; on the remainder the scalars are empty on both sides
and the audit scores "unchanged" as preserved. The render carries them as
`<snmpd><rocommunity>`, `<syslocation>` and `<syscontact>`.

`snmp.trap_hosts` is `good` for the weaker of the two possible reasons.
**`aruba_aoscx` declares `/snmp/trap-host` unsupported**, so as a source it
never emits trap destinations; the list is empty on both sides on every cell.
The disposition means "no divergence", not "trap receivers migrate". Re-author
them on the OPNsense side by hand.

`snmp.v3_users` is a total drop: 1 user in and 0 out on each of the 2 cells
that carry one, while the scalars beside them survive. OPNsense's SNMPv3 user
store lives in the bsnmpd / net-snmp plugin's own configuration format, not in
the `config.xml` this codec reads and writes. SNMPv3 polling stops at cutover
and cannot be restored from the migrated config.

## First-hop redundancy is the cutover risk

Three keys have to be read together, because separately each looks survivable:

- `interfaces[].ipv4_addresses` — the interface keeps its own address, but 15
  of 41 populated records lose the `virtual_gateway_address` companion.
- `vlans[].ipv4_addresses` — the SVI subnet relocates and survives; all 15
  VLAN-mount `virtual_gateway_address` values are gone.
- `anycast_gateway_mac` — the fabric-wide VSX active-gateway MAC is empty on
  all 5 cells that set it.

Both halves of first-hop redundancy are therefore gone: the subnets migrate,
the address hosts actually point at does not. This is the single most likely
cause of a black-holed cutover on this pair. Re-design first-hop redundancy on
OPNsense as CARP virtual IPs — noting that `opnsense` declares
`/interfaces/interface/vrrp-groups/group` lossy because it renders CARP only
and skips `mode='vrrp'` / `mode='hsrp'` groups entirely, and `.../preempt`
lossy because the CARP `<vip>` grammar has no preempt element.

Contrast `aruba_aoscx__arista_eos`, where `anycast_gateway_mac` is `good` while
the per-SVI gateway address is not. Neither pair migrates first-hop redundancy
end to end; they fail at different halves of it.

## What actually survives a cutover

Worth stating positively, because most of this file is loss. This is also the
only `aruba_aoscx` pair in the mesh where `interfaces[].name`, `vlans[].id`
**and** `lags` are all clean at once — interface, VLAN and LAG record counts
every one preserved exactly:

- `hostname` — 7/7 cells.
- **The entire interface inventory** — 157/157 records, with names,
  descriptions, admin state and MTU intact, every IPv4 and IPv6 address kept
  (the anycast companion is the part that is not — see below).
- `lags` — 34 records, 44 member ports, 7/7 cells, including mode.
- `vlans[].id` and `vlans[].name` — 30/30 records, both fields.
- SVI subnets — relocated onto the sibling interface record, not lost.
- `local_users[].name` — 6/6 populated cells.
- SNMP community, location and contact.

Everything an operator must rebuild by hand: port-to-VLAN membership and the
whole switchport surface, VLAN descriptions, first-hop/anycast gateway
addressing, every static route, VRFs and per-port VRF binding, VXLAN, SNMPv3
users, SNMP trap receivers, syslog, NTP, timezone, and every local password.
