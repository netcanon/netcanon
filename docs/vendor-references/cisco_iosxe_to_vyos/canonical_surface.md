# IOS-XE (NETCONF/OpenConfig) → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__vyos.yaml`.

**Source of every number here:** a `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every loss recorded was additionally re-derived by hand —
`cisco_iosxe.parse()` → `vyos.render()` → `vyos.parse()` on the fixture — so no
claim below rests on the drift shape alone.

- Fixture cells: **1** — `tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml`
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and a hand round-trip of the committed
> fixture. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Read the corpus size before you read the numbers

This pair has **one** cell, and it is worth being blunt about why. The
`cisco_iosxe` codec is the NETCONF / OpenConfig **XML** adapter, not the
`show running-config` text one — `tests/fixtures/real/cisco_iosxe/` maps to
`cisco_iosxe_cli` via `netcanon/migration/fixture_dirs.py::DIR_TO_CODEC_NAME`,
so all fourteen real IOS-XE captures belong to the sibling codec. The only
fixture this codec parses is its synthetic kitchen-sink.

The consequence runs through the whole file: **24 of 43 keys are trivially
empty on both sides** and rest on capability declarations, not on a
round-trip. Those keys say so in their own words rather than implying a
measurement that does not exist. The three keys that *are* measured were
measured completely — every record, not a sample.

## Device-class framing

`cisco_iosxe` here is a **Phase-0.5 OpenConfig stub**. It parses only the
`/openconfig-interfaces/` subtree; `<system>`, `<vlans>`,
`<network-instances>` and the rest are declared in its `CapabilityMatrix` but
not wired into `parse()`. Whatever the device class of the box behind the
NETCONF session, what reaches the canonical tree is an **interface inventory
and nothing else**.

`vyos` is a Linux software router: `config.boot` curly-brace grammar, netdevs
under `interfaces { … }`, 802.1Q as `vif` sub-interfaces, and **no top-level
VLAN database at all**.

So the realistic migration this pair describes is narrow and should be stated
narrowly: *harvest an IOS-XE box over NETCONF, stand the addressing up on a
VyOS router.* Interface identity, description, admin state and dual-stack
addressing carry. Nothing else in the config does, because nothing else was
ever collected.

## The structural finding: the inventory holds, the VLAN database does not

| measurement | value |
|---|---|
| source interface records | **10** |
| records after parse → render → re-parse | **10** |
| interface name sets identical | **yes** |
| source VLAN records | **1** |
| VLAN records after the round-trip | **0** |

Both halves matter, and they are **one mechanism seen from two ends**, not two
independent findings.

`cisco_iosxe` has no `<vlans>` parse path. Its single VLAN record is
*synthesised* from the `Vlan10` SVI by
`_synthesize_vlans_from_svis()` (`netcanon/migration/codecs/cisco_iosxe/codec.py`,
`_SVI_NAME_RE = ^Vlan(\d+)$`): `id` from the name, `name` from the SVI's
description, `ipv4_addresses` copied off the SVI. So the VLAN record is a
projection of an interface record.

That interface record **survives**. The render carries
`ethernet Vlan10 { address "10.10.10.1/24"; address "2001:db8:10::1/64" }`, and
both addresses come back on re-parse. What is lost is the **VLAN declaration**
— the `id`, and the name/membership fields that were empty anyway — not the
SVI or its addressing. VyOS declares `/vlans/vlan/id` unsupported and says why:
it has no VLAN database, only `vif <vid>` sub-interfaces.

This is why `vlans[].id` is `unsupported` (a record vanishes; #436) while
`interfaces[].ipv4_addresses` is `good` (the same addresses survive on their
own record). Reading the VLAN drop as "the L3 was lost" is the wrong reading.

## Per-field measurement (1 cell)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 0 | **1** | 0 |
| interfaces (record set) | 1 | 0 | 0 |
| interfaces[].name / description / enabled / ipv4_addresses / ipv6_addresses | 1 | 0 | 0 |
| interfaces[].interface_type | 0 | **1** | 0 |
| vlans (record set) | 0 | **1** | 0 |

Every other audited field — `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `interfaces[].mtu`,
`interfaces[].lag_member_of`, `interfaces[].vrrp_groups`, `static_routes`,
`dhcp_servers`, all five `snmp.*` keys, `lags`, all three `local_users[].*`
keys, `radius_servers`, all three `vxlan_vnis[].*` keys,
`evpn_type5_routes`, both `routing_instances[].*` keys, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac` — is **empty on both
sides**, because the source parser never populates it.

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | **10** | 10 | value → empty string |
| `name` | 0 | 10 | — |
| `description` | 0 | 9 populated | — |
| `enabled` | 0 | 10 | — |
| `ipv4_addresses` | 0 | 7 populated | — |
| `ipv6_addresses` | 0 | 4 populated | — |
| `mtu` / `lag_member_of` / `vrrp_groups` | 0 | 0 populated | — |

`interface_type` drops **uniformly**, which is the difference from the
IOS-XR → EOS pair where loopbacks survived. Source census: 5
`ianaift:ethernetCsmacd`, 2 `ianaift:softwareLoopback`, 1 `ianaift:tunnel`, 1
`ianaift:l2vlan`, 1 `ianaift:ieee8023adLag` — **all ten** return as the empty
string.

The mechanism is visible in the render. Every interface is emitted under the
`ethernet` netdev class regardless of what it was:

```
interfaces {
    ethernet GigabitEthernet0/0/0 { … }
    ethernet Loopback0 { … }
    ethernet Port-channel1 { … }
    ethernet Vlan10 { … }
    ethernet Tunnel100 { … }
}
```

The vyos matrix already declares `/interfaces/interface/config/type` lossy and
states that the codec re-derives the type from the **interface-name shape**
(`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback, `bondN` →
ieee8023adLag). A name like `Loopback0` matches none of those shapes, so the
inference returns empty for every record. Nothing about the interface's
identity, addressing or admin state is affected — this is a lost hint, which is
why it is `lossy` and not `unsupported`.

Two observations belong to the codec rather than to this pair, and are recorded
here rather than acted on: the render places non-Ethernet netdevs under
`ethernet`, and the names it emits are Cisco-shaped rather than VyOS-shaped.
Both are pre-existing render behaviour, not something this pair introduces.

### The description key is clean, and not by accident

`interfaces[].description` is `good` on measurement: 9 of 10 records carry a
description and **0 differ**.

That is worth stating explicitly because of a known VyOS-target hazard. The
vyos render **rewrites free text**: `_q()` in
`netcanon/migration/codecs/vyos/render.py` replaces an embedded `"` with an
apostrophe, because VyOS rejects embedded quotes in value strings even when
backslash-escaped (vyos.dev/T1246). A description can therefore come back with
altered **punctuation** while its **text** survives.

On this cell the rewrite does not fire: **0 of 9** descriptions contain an
embedded double-quote. So the `good` here is a real clean round-trip, not a
rewrite that happened to go unmeasured. On a production config that quotes a
circuit ID, expect the punctuation change — and read it as punctuation, not as
content loss.

## Source-side gaps vs symmetric gaps

The `cisco_iosxe` matrix declares these **unsupported at the exact path**, and
the parser correspondingly never populates them, so there is nothing for VyOS
to lose:

`/system/{hostname,domain,dns-server,ntp-server}` · `/vlans/vlan/{id,name}` ·
`/routing/static-route` (+ `/gateway`, `/vrf`) · `/snmp/community` ·
`/snmp/{location,contact,trap-host}` · `/snmp/v3-user` (+ four sub-paths) ·
`/lags` · `/local_users` · `/radius-servers/server/{host,key}` ·
`/vxlan-vnis/{vni,source-interface,udp-port}` · `/evpn-type5-routes/route` ·
`/routing-instances/instance` · `/interfaces/interface/config/mtu` (declared
lossy; see below)

These are recorded `not_applicable`, not `unsupported`, and the distinction is
operational: for most of them **vyos declares the path SUPPORTED** — hostname,
domain, DNS and NTP servers, static routes, SNMP community/location/contact,
local users with `name` / `role` / `hashed-password`, bonding via
`/lags/lag/{name,members}` and `/interfaces/interface/lag-member-of`, VRF
identity via `/routing-instances/instance/name`, and VXLAN VNIs with
`mcast-group`. Re-authoring any of them on the VyOS side will stick. The
migration report should say that rather than implying VyOS cannot hold them.

Seven keys are different — **both** matrices declare them unsupported, a
symmetric gap in the pair:

`/system/timezone` · `/system/syslog-server` ·
`/interfaces/interface/vrrp-groups/group` (and all seven sub-paths) ·
`/vlans/vlan/id` · `/dhcp-servers/pool` ·
`/radius-servers/server/{host,key}` · `/anycast-gateway-mac`

Those are `unsupported`.

### `interfaces[].mtu` is the one worth calling out

The fixture carries three `<mtu>` elements on the wire — 1500, 9000, 9216 — and
**zero** of the ten canonical interface records end up with an MTU. The
`cisco_iosxe` stub parses MTU into its transient nested dict but does not carry
it through to `CanonicalInterface`; the matrix declares
`/interfaces/interface/config/mtu` lossy on the source side for a
related-but-different reason (CLI-only platform MTU distinctions).

So this is not "VyOS lost the MTU" — VyOS declares
`/interfaces/interface/config/mtu` **supported** and would have rendered it.
The MTU never left the source. Recorded `not_applicable` on that basis, with
the caveat that a wider `cisco_iosxe` fixture corpus would not change the
answer: the drop is in `parse()`, not in the fixture.

## The hostname finding

This is the one result that is a drift rather than an absence, and it deserves
its own section because the shape is easy to misread.

- Source canonical `hostname`: `''` — the OpenConfig stub emits no `<system>`
  parse path, and `/system/hostname` is declared unsupported.
- After `vyos.render()` → `vyos.parse()`: `'vyos'`.

The render is not passing an empty value through. It **substitutes the VyOS
factory default**. `netcanon/migration/codecs/vyos/render.py` line 110:

```python
lines.append(f"    host-name {tree.hostname or 'vyos'}")
```

`system { host-name vyos }` lands in the output unconditionally, so the
migrated device asserts an identity the source never supplied.

Recorded `lossy`, not `unsupported`, and the reasoning is the #436 rule read
carefully: nothing vanishes here — a value is **substituted**. `lossy` warns
and stays compatible, which is the correct signal for "the target will come up,
but not under the name you expect". `unsupported` would block a migration that
is otherwise fine.

The operational note that belongs in a runbook: set the hostname on the VyOS
side by hand. A NETCONF-sourced migration will silently name every box `vyos`,
and two boxes named `vyos` on the same segment is a real outage, not a
cosmetic one.

## Credential material

Nothing to redact on this pair, and that is itself the finding. `local_users`,
`radius_servers` and `snmp.v3_users` are all **empty on the source side** —
the OpenConfig stub has no `<aaa>`, `<snmp>` or RADIUS parse path — so no
credential of any form enters the canonical tree and none is quoted anywhere in
this file or the expectation YAML.

Two forward-looking notes, both grounded in declarations rather than in a
measurement on this cell:

- vyos declares `/local-users/user/hashed-password` **supported**, so accounts
  re-authored on the target will carry a hash. It declares
  `/local-users/user/privilege-level` lossy — every login user maps to a single
  privilege level.
- vyos declares five `/snmp/v3-user/*` paths lossy, two of them explicitly as
  **cryptographic downgrades**: a stronger source auth algorithm collapses to
  `sha` (SHA-1), and AES-192/256 or 3DES lose their exact strength. USM keys
  are stored as an opaque blob that does not survive a cross-vendor move.
  SNMPv3 users must be re-keyed on the target regardless.

## Two drift-shape readings that are wrong

**"`interfaces` is a total drop."** A mechanical vanish-classifier over this
pair reports exactly that. It is wrong: 10 records in, 10 out, identical name
sets, and every populated sub-field except `interface_type` byte-identical. The
classifier is reacting to the single `interface_type` sub-field drifting on the
one cell in the corpus. Every `interfaces[].*` key except `interface_type` is
`good` on its own measurement, not on a sibling's.

**"The VLAN drop cost us the SVI's addressing."** It did not. The VLAN record
was a synthesised projection of `Vlan10`; `Vlan10` and both of its addresses
survive. The loss is the VLAN declaration, and it is claimed exactly once —
under `vlans[].id`, where the reconciler's structural-only collapse assigns it.
The remaining five `vlans[].*` keys are `good` because they measure what
happens to the *value* when the record survives, and recording the same
disappearance six times would multiply one loss into six.
