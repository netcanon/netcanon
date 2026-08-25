# cisco_iosxe (NETCONF/OpenConfig) → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__aruba_aoscx.yaml`.

**Source of every number here:** the committed `tools/run_full_mesh.py` pass
(`tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`), with per-key
dispositions resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. The three drifting keys were additionally re-proved by hand:
parse the fixture with `cisco_iosxe`, render with `aruba_aoscx`, read the
output, re-parse it.

- Fixture cells: **1**
- Render errors: **0** · re-parse errors: **0**
- Fixture: `tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml` (synthetic)
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, their parse/render source, and the measured mesh run. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly in that entry's own words.

## Coverage caveat, stated first

This pair has **one** cell and it is **synthetic**. Thirty-three of the
forty-three audited keys are empty on both sides of it, so they resolve to
`TRIVIAL_EMPTY` in the reconciler and their disposition rests on the two
capability matrices, not on evidence. Only ten keys carry a measurement:
seven preserved, three drifted.

Read this file as "what the codecs declare, plus a very good look at the L3
interface edge" — not as a broad fidelity result.

## Wire-format framing

`cisco_iosxe` is the **OpenConfig NETCONF XML** codec, distinct from
`cisco_iosxe_cli` (operator-paste `show running-config` text). Its parse path
is a Phase 0.5 stub: it walks `<interfaces>` and nothing else, then calls
`_synthesize_vlans_from_svis()` to build `intent.vlans` from any `Vlan<N>` SVI
it found. Hostname, SNMP, static routes, VRFs, LAGs, local users, RADIUS and
VXLAN are empty after parse **regardless of what the source XML contains**.

So the shared surface with AOS-CX is exactly the L3 interface edge. A NETCONF
snapshot re-rendered as AOS-CX is a faithful render of a **narrow projection**
of the device, not a recovery of its full state. Operators wanting full
fidelity on the Cisco side should route through `cisco_iosxe_cli`.

## The structural finding — and it is the opposite of the AOS-CX→EOS pair

On `aruba_aoscx → arista_eos` the dominant loss is the interface inventory
shrinking, which drags *every* `interfaces[].*` sub-field down with it. **That
does not happen here.**

Measured: **10 source interfaces → 10 rendered → 10 re-parsed**, matched by
name, zero records dropped. Exactly **one** interface sub-field drifts. Name,
description, admin state, IPv4 and IPv6 addressing are each independently
preserved on all ten records, so each is recorded `good` on its own evidence
rather than being dragged down by a neighbour.

This is worth stating loudly because the correlated-drift trap runs in both
directions: on that pair, citing one `interfaces[].*` key as corroborating
another was wrong because they shared a single cause. Here, treating
`interface_type` as evidence about `ipv4_addresses` would be equally wrong —
for the opposite reason.

## Per-field measurement (1 cell)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 0 | 1 | 0 |
| interfaces[].name / description / enabled | 1 | 0 | 0 |
| interfaces[].ipv4_addresses / ipv6_addresses | 1 | 0 | 0 |
| interfaces[].interface_type | 0 | 1 | 0 |
| vlans[].id / name | 1 | 0 | 0 |
| vlans[].ipv4_addresses | 0 | 1 | 0 |

Keys trivially empty on the one cell — that is, no data on either side, so no
observation exists: `domain`, `dns_servers`, `ntp_servers`, `timezone`,
`syslog_servers`, `interfaces[].mtu`, `interfaces[].lag_member_of`,
`interfaces[].vrrp_groups`, `vlans[].untagged_ports`, `vlans[].tagged_ports`,
`vlans[].description`, `static_routes`, `dhcp_servers`, `snmp.community`,
`snmp.location`, `snmp.contact`, `snmp.trap_hosts`, `snmp.v3_users`, `lags`,
`local_users[].name`, `local_users[].role`, `local_users[].hashed_password`,
`radius_servers`, `vxlan_vnis[].vni`, `vxlan_vnis[].vlan_id`,
`vxlan_vnis[].mcast_group`, `evpn_type5_routes`, `routing_instances[].name`,
`routing_instances[].description`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

## The three measured losses

### 1. `hostname` — substitution, not loss

The source intent carries `hostname == ''`: the fixture has no `<system>`
element and `cisco_iosxe` declares `/system/hostname` unsupported. The AOS-CX
render emits the literal line `hostname switch`, because `render_intent()`
falls back to a hard-coded `"switch"` when the canonical hostname is empty.
Re-parse reads `'switch'`, and the comparator records drift.

Nothing an operator configured was dropped — a placeholder was **invented**.
Recorded `lossy` (warn, stays compatible) rather than `unsupported` (block):
the rendered config is usable, but every device migrated through this pair
arrives named `switch`. Set the real hostname before cutover.

`aruba_aoscx` declares `/system/hostname` **supported**, so the gap is
entirely on the source side.

### 2. `interfaces[].interface_type` — one cause, counted ten times

All ten source records carry a specific IANA ident (`ianaift:ethernetCsmacd`,
`softwareLoopback`, `tunnel`, `l2vlan`, `ieee8023adLag`). All ten re-parse as
`ianaift:other`.

Cause, verified against the codec rather than guessed: AOS-CX config carries
no IANA ifType at all, so `aruba_aoscx` declares
`/interfaces/interface/config/type` **lossy** and infers the type from the
interface-name **shape** — `1/1/1` → ethernetCsmacd, `vlan N` → l3ipvlan,
`lag N` → ieee8023adLag, `loopback N` → softwareLoopback — falling back to
`ianaift:other` when nothing matches.

The Cisco names pass through verbatim, so nothing matches, for any port —
including the loopbacks and the port-channel that would classify cleanly under
AOS-CX naming.

**Not fixable by enabling port-name translation.** Measured: running the
rename mesh over this cell produces 10 warnings
(`cisco_iosxe: could not classify port name …; left verbatim`), 0 renames
applied and 0 drops, because `cisco_iosxe` declares `"ports"` in
`unsupported_rename_categories` — its `classify_port_name` is the inherited
`CodecBase` no-op. Either supply an explicit rename map, or use
`cisco_iosxe_cli` as the source.

Ten drifting records here are **one cause counted ten times**, not ten
independent observations.

### 3. `vlans[].ipv4_addresses` — the two signals disagreed, so it was probed

The total-drop heuristic classified this **TOTAL** (source populated, target
side empty) and would have made it `unsupported`. The `aruba_aoscx` matrix
declares `/vlans/vlan/ipv4/address/ip` **lossy**. The matrix is right, and the
round-trip proves it:

- The source XML has **no `<vlans>` subtree at all**.
  `_synthesize_vlans_from_svis()` builds the VLAN record from the `Vlan10` SVI
  interface: `id` parsed from the name, `name` taken from the SVI
  **description**, and `ipv4_addresses` a **copy** of the SVI's IPv4 list.
- The render emits `vlan 10 / name …` with no L3, and separately
  `interface Vlan10` carrying that exact address and prefix.
- Re-parse: `vlans[0].ipv4_addresses == []`, and
  `interfaces['Vlan10'].ipv4_addresses` still holds the address.

What vanished is a **duplicate mount point**, not forwarding state. AOS-CX
renders SVI L3 only from the sibling interface stanza, so the copy on the VLAN
record has no render site. `lossy` is the honest severity; `unsupported`
(block) would over-claim a config that is fully usable.

**The caveat that matters operationally:** this holds because the address
exists at *both* canonical mount points on this cell. A source that populates
the VLAN record *without* a matching `Vlan<N>` interface would lose the
address outright. After cutover, verify SVI addressing against the original
device rather than against the canonical diff.

## Symmetric gaps vs source-side gaps

The distinction drives the `unsupported` / `not_applicable` split in the YAML,
and it is operational rather than cosmetic: it tells a reader whether
re-authoring the value on the target is worth doing.

**Symmetric — both codecs declare the exact path unsupported.** Recorded
`unsupported`; re-authoring on AOS-CX will *not* survive a pass through this
codec either:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/timezone` · `/system/syslog-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` + `/key` · `/snmp/trap-host` ·
`/interfaces/interface/vrrp-groups/group` (whole subtree) ·
`/routing-instances/instance/description`

**Source-side only — the parser never produces it, but AOS-CX supports it.**
Recorded `not_applicable`; re-authoring on the target *will* stick:

`static_routes` (default VRF) · `snmp.community` / `.location` / `.contact` ·
`vlans[].untagged_ports` / `.tagged_ports` · `lags` · `local_users[].*` ·
`vxlan_vnis[].*` · `routing_instances[].name` · `anycast_gateway_mac`

`interfaces[].vrrp_groups` is the widest symmetric gap on the pair: both
codecs drop the anchor plus mode, priority, preempt, advertisement-interval,
authentication, virtual-ipv6s and description. AOS-CX expresses first-hop
redundancy as the `active-gateway` anycast form instead, and VRRP is a later
phase in that codec. Transcribe FHRP by hand and treat it as cutover-blocking.

## Three things that look clean and are not

**`interfaces[].mtu` is `not_applicable`, and that is not the same as safe.**
The fixture XML *does* carry `<mtu>` on three interfaces (1500, 9000, 9216),
but `_iface_dict_to_canonical()` never copies it onto
`CanonicalInterface.mtu`. The canonical tree holds `None` on all ten records,
on both sides. `aruba_aoscx` declares MTU supported and would render it — so
the target silently sits at its default and the audit cannot flag it. Re-check
jumbo frames on every uplink after cutover.

**`lags` is `not_applicable`, and the bundle still breaks.** `intent.lags` is
empty after parse even though the fixture contains a `Port-channel1` interface
typed `ianaift:ieee8023adLag`, because the parser does not walk
`openconfig-if-aggregate`. The bundle's L3 config is *not* lost —
`Port-channel1` survives as an ordinary interface with its description and
both its addresses — but it arrives with no members and no LACP mode. The
rendered config looks complete and would carry no traffic.

**`raw_sections` is empty on both sides, but the render is not.** The AOS-CX
render emits a `!Version ArubaOS-CX …` banner and an `!export-password:`
service line that the source never supplied; `aruba_aoscx` declares
`/system/raw-sections/version-banner` lossy on that account. Those lines are
not read back on re-parse, so they neither drift nor accumulate. Like the
`hostname switch` placeholder, they are render-side **fabrication** rather than
migrated content — review the header of any rendered config before pasting it.

## Two matrix under-declarations found while authoring

Neither is a fact about this pair; both belong in a codec change rather than
in an expectation file.

1. **`cisco_iosxe` declares nothing for `/lags/lag`** — not supported, not
   lossy, not unsupported — while never populating one.
2. **`aruba_aoscx` declares nothing for the EVPN type-5 surface** — same
   three-way silence.

Both are recorded in the YAML entries for `lags` and `evpn_type5_routes` so a
future reader does not mistake the silence for a considered `supported`.

## Credential material

No credential material exists on either side of this cell: the `cisco_iosxe`
parser does not walk `<system><aaa>`, so `intent.local_users` is empty and
`intent.snmp` is `None`. Nothing was inspected in authoring this file.

For planning rather than from measurement: AOS-CX stores the user secret in
its own device-encrypted form and Cisco stores a crypt-family or vendor-typed
hash — different shapes, with no cross-vendor re-encoding path in either
codec. `aruba_aoscx` additionally declares its SNMPv3 auth and privacy
protocol paths lossy as **cryptographic downgrades** (SHA-1 auth and
AES-128/DES privacy only, silently weakening a stronger source algorithm), and
its privacy key as a device-key-encrypted blob portable only on the same
device.

Assume every account has its password set on the target, and re-key SNMPv3
users rather than transcribing them.

No secret values are reproduced in this file or in the expectation YAML. Per
`AGENTS.md`, encrypted secrets are operator-traceable even when encrypted, and
a document that quotes the value it describes defeats its own redaction. Only
the *shape* of a secret is ever described here.
