# AOS-S → Cisco IOS-XR: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoss__cisco_iosxr.yaml`.

**Source of every number here:** the committed `tools/run_full_mesh.py` run
(`tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`), re-measured
independently by parsing each of the seven fixtures with the `aruba_aoss`
codec, rendering with `cisco_iosxr` and re-parsing the render. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the codec source, and the measured mesh run. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`aruba_aoss` in this corpus is a **campus access/aggregation** switch — the
committed fixtures are HP/Aruba 2920, 2930F, 2930M, 5406R zl2 and a five-member
stack, all ProVision/AOS-S `show running-config` text. `cisco_iosxr` is a
**service-provider edge/core router**: four-segment interface names, a heavy
VRF surface, `router static` address-families, and no campus L2 model at all.

This is the most asymmetric pair in the AOS-S row, and the asymmetry runs the
opposite way to `aruba_aoscx__arista_eos`. There, the interface inventory was
the thing that shrank. Here the **interface inventory survives completely** —
every one of the seven cells re-parses with exactly the interface count it
started with (49→49, 9→9, 10→10, 4→4, 0→0, 0→0, 13→13) — and it is the
**VLAN database that vanishes wholesale**.

## The structural finding

**Every VLAN record is dropped on every cell**: 3→0, 2→0, 12→0, 4→0, 3→0,
3→0, 5→0. The rendered IOS-XR config contains zero `vlan` stanzas.

This is not a corpus accident, and it is worth stating precisely because the
capability matrix says otherwise. `cisco_iosxr` declares **`/vlans/vlan/id`
and `/vlans/vlan/name` SUPPORTED**. Read the declaration in context
(`netcanon/migration/codecs/cisco_iosxr/codec.py`) and it is annotated:

> Phase 2 — sub-interface `encapsulation dot1q` → synthesised VLAN id-list
> (no port membership; name always empty)

That is a **parse-side** declaration: XR-as-source synthesises canonical VLANs
from `encapsulation dot1q` tags.

There is no matching render path. `netcanon/migration/codecs/cisco_iosxr/
render.py` contains exactly one VLAN-related emission — `encapsulation dot1q
<n>`, driven by `CanonicalInterface.dot1q_vlan` — and nothing at all that walks
`intent.vlans`. So for a source whose VLANs are a campus VLAN *database*
rather than a set of routed sub-interface tags, the entire list is dropped by
construction.

The codec authors already knew half of this: the XR matrix declares
`/vlans/vlan/ipv4/address/ip` lossy with the reason "this codec renders no SVI
from the VLAN record". The `id` / `name` over-declaration is the unfixed
remainder. It is a **matrix over-declaration on the target side, not a
pair-specific fact**, and is left for a codec change rather than papered over
here.

### Why inter-VLAN addressing survives anyway

Confusingly, the L3 does come across. The AOS-S parser materialises a sibling
`Vlan<N>` **interface** record for every SVI, and the XR renderer emits those
as ordinary interface stanzas:

```
interface Vlan10
 description wifi
 ipv4 address 10.1.0.27 255.255.0.0
```

So on `hpe_community_2930f_wc1607_intervlan.cfg` all nine addressed SVIs
arrive with their addresses intact (and the VLAN name promoted to the
interface description) while all twelve VLAN records, their names and their
tagged/untagged port lists are gone. **Do not read the surviving SVI
addressing as "the VLANs migrated."** The L3 interface exists; the broadcast
domain it is supposed to serve, and every port assigned to it, does not.

### Structural-collapse ownership

Because the parent list drift is a wholesale "all N dropped" string, *every*
`vlans[].*` sub-field measures as drifted on all 7 cells. The reconciler
collapses that: the first `vlans[].*` key in YAML order carries the
record-level signal and the rest become `STRUCTURAL_ONLY`.

`vlans[].id` is therefore written **first** in the YAML and is the key that
declares the loss. The other five (`name`, `ipv4_addresses`,
`untagged_ports`, `tagged_ports`, `description`) are declared **`good`** — not
because nothing happens to them, but because their only drift is the parent
record vanishing, which `vlans[].id` already claims. A loss declared on those
five could never be evidenced separately by any cell. Key order in that block
is load-bearing; do not reorder it.

## Per-field measurement (7 cells)

Independently reproduced with a parse → render → re-parse loop over all seven
fixtures; the numbers below match the audit's `actual_disposition()` exactly.

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| dns_servers | 3 | 0 | 4 |
| ntp_servers | 1 | 0 | 6 |
| interfaces[].name / description / enabled | 5 | 0 | 2 |
| interfaces[].ipv4_addresses | 4 | 0 | 3 |
| interfaces[].ipv6_addresses | 1 | 0 | 6 |
| interfaces[].interface_type | 0 | 5 | 2 |
| interfaces[].lag_member_of | 0 | 2 | 5 |
| vlans[].* (all six sub-fields) | 0 | 7 | 0 |
| static_routes | 5 | 0 | 2 |
| snmp.community | 0 | 6 | 1 |
| snmp.contact | 3 | 3 | 1 |
| snmp.trap_hosts | 4 | 2 | 1 |
| snmp.location / snmp.v3_users | 5 | 1 | 1 |
| lags | 0 | 2 | 5 |
| local_users[].name / role / hashed_password | 3 | 0 | 4 |
| radius_servers | 0 | 1 | 6 |

Fields trivially empty on all 7 cells: `domain`, `timezone`, `syslog_servers`,
`dhcp_servers`, `interfaces[].mtu`, `interfaces[].vrrp_groups`, `vxlan_vnis[].*`,
`evpn_type5_routes`, `routing_instances[].*`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

## Source-side gaps vs target-side drops vs symmetric gaps

Three different shapes hide behind "this field is empty on both sides", and
the YAML distinguishes them because they imply different operator action.

**Source-side gaps — `not_applicable`.** `aruba_aoss` declares
`/system/domain`, `/system/syslog-server` and `/routing-instances/instance`
unsupported at the exact path, and declares no `/interfaces/interface/config/
mtu` path at all. As a *source* it never emits them, so there is nothing for
XR to lose. For `syslog_servers`, `interfaces[].mtu` and the VRF surface,
`cisco_iosxr` declares the field supported (VRFs as `lossy`, i.e. it does
parse and render them) — **re-authoring on the XR side will stick**, and the
migration report should say so rather than implying XR cannot hold them.

The VRF case is the one worth flagging to an operator: IOS-XR is a VRF-heavy
platform and this pair carries **zero** VRFs, purely because an AOS-S campus
switch has no routing-instance grammar for the parser to read. That is the
device-class gap, not an XR limitation.

**Target-side drops — `unsupported`.** `aruba_aoss` declares
`/interfaces/interface/vrrp-groups/group` **supported**; `cisco_iosxr`
declares the whole VRRP subtree unsupported ("VRRP / FHRP redundancy groups
are out of the v1 IOS-XR scope"). No committed cell populates it, so it is
untested here — but the direction is unambiguous and re-authoring is required.
Same shape for `/snmp/community` and `/radius-servers/server/{host,key}`.

**Symmetric gaps — `unsupported`.** `/system/timezone`, `/dhcp-servers/pool`,
the whole `/vxlan-vnis` subtree and `/anycast-gateway-mac` are declared
unsupported by **both** codecs. Nothing carries them in either direction; set
them by hand on the target.

## Total drops verified by round-trip, not inferred

The `unsupported` vs `lossy` split is a behavioural question, not a
grammatical one — a vanished record is not lossy (#436). Each of these was
checked by rendering and re-parsing rather than read off the drift shape:

- **`snmp` — total.** `snmp` is populated on 6 of 7 cells and the re-parsed
  intent has `snmp is None` on **every one of them**; the render contains zero
  `snmp-server` lines. All five `snmp.*` keys are `unsupported`. Note the
  automated vanish heuristic scores this pair's `snmp` as "partial → lossy",
  because the drift string ends in `None` rather than the word "dropped" — the
  heuristic is wrong here and the round-trip is right.
- **`radius_servers` — total.** The one cell that populates it
  (`kitchen_sink.cfg`) goes 2 → 0, and the render contains no `radius` line.
  `unsupported`.
- **`vlans` — total.** Covered above. `unsupported`, on `vlans[].id`.
- **`lags` — partial, so `lossy`.** This one genuinely is a degradation and
  not a vanish; see below.

## The LAG surface: two separate things, only one of them a loss

`lags` drifts on the 2 cells that populate it, and it is tempting to read that
as "LAGs don't migrate". They partly do.

**On `aruba_central_5memberstack_rendered.cfg`** the LAG survives intact:
`trk1` with members `1/25`, `1/26` renders as `bundle id 1 mode on` on both
member interfaces and re-parses as `Bundle-Ether1` with the same two members.
Nothing was lost — the canonical *name* changed, vendor-correctly.

The audit does canonicalise LAG names before comparing
(`_LAG_NAME_FIELDS` / `_canonical_lag_name` in
`tools/run_phase4_reconciliation.py`), which is why `ae1` ↔ `Port-channel1`
does not fire drift. But `_LAG_NAME_RE` allows only
`ae|Po|Port-channel|Port-Channel|trk|Trk|agg|bond` — **`Bundle-Ether<N>` is not
in the list**, so `_canonical_lag_name("Bundle-Ether1")` returns `None`, the
comparison falls back to raw equality, and the vendor-correct IOS-XR rename is
scored as drift. That is the entire content of the
`interfaces[].lag_member_of` drift on both affected cells. Reproduce with:

```
py -c "import importlib.util,pathlib; s=importlib.util.spec_from_file_location('r4',pathlib.Path('tools/run_phase4_reconciliation.py')); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m._canonical_lag_name('trk1'), m._canonical_lag_name('Bundle-Ether1'))"
```

→ `LAG1 None`. Adding `Bundle-Ether` to that regex is a tools change, out of
scope for an expectation pair, and is deliberately **not** done here.

**On `kitchen_sink.cfg`** there is a real loss underneath: the source carries
two LAGs, `trk1` (members `23`, `24`) and `trk2` (members `A3`, `A4`), and the
re-parse yields only `Bundle-Ether1`. `trk2` is gone. The cause is the known
LAG trap: the renderer emits bundle membership from
`CanonicalInterface.lag_member_of`, **not** from `CanonicalLAG.members`, and
this fixture has no interface records named `A3` / `A4` for the membership to
hang on. So `trk2` has nothing to render from and disappears.

That makes `lags` a partial degradation — one bundle survives, one vanishes —
which is `lossy`, not `unsupported`. `cisco_iosxr` declares `/lags/lag/name`,
`/lags/lag/members` and `/lags/lag/mode` all supported, and the render proves
it can emit bundles. Re-check the member list of every port-channel after
cutover.

## Interface type collapses to `other` on every record

`interfaces[].interface_type` drifts on all 5 cells that carry interfaces, and
on **every record** of those cells: `ianaift:ethernetCsmacd` → `ianaift:other`,
and on `kitchen_sink.cfg` also `ianaift:l3ipvlan` → `ianaift:other` and
`ianaift:ieee8023adLag` → `ianaift:other`.

The mechanism is declared: `cisco_iosxr` marks
`/interfaces/interface/config/type` lossy because "CLI parser infers interface
type from the name prefix (GigabitEthernet → ethernetCsmacd, Loopback →
softwareLoopback, Bundle-Ether → ieee8023adLag, MgmtEth → ethernetCsmacd…)".
AOS-S port names are bare ordinals — `1/25`, `23`, `A1`, `Trk1` — which match
none of those prefixes, so the re-parse has nothing to infer from and every
port lands on `other`.

This is a pure classification loss: names, descriptions, admin state and
addressing all round-trip on the same records. It is `lossy`, not
`unsupported`. Renaming ports to XR-native four-segment form during migration
(the `translate_port_names` path) would resolve it; a bare render does not.

## Identity and credential material

`local_users[].name`, `.role` and `.hashed_password` are preserved on all 3
cells that populate local users, and the opaque secret string round-trips
byte-for-byte. Two caveats that the `good` disposition does not carry:

**1. Privilege level is silently downgraded.** `CanonicalLocalUser.
privilege_level` goes `15 → 1` on 4 of the 5 user records in the corpus
(`admin` on two real fixtures, `admin` and `siteops` on `kitchen_sink.cfg`;
`monitor` was already 1). The `role` *string* survives — the render emits
`group manager` — so the account is not obviously broken, but the canonical
privilege number is not. This field is **not** one of the audited keys for
this pair, so it carries no YAML disposition; it is recorded here because it
is real, verified, and fails in the safe direction (privileges drop, they do
not escalate).

**2. The secret is re-emitted as type 0.** `render.py` splits the source
secret on a leading Cisco type digit and, finding none on an AOS-S secret,
defaults `htype = "0"` — so the line written is `secret 0 <source string>`.
Type 0 is the plaintext marker. The canonical value round-trips, which is why
the key is `good`, but the *meaning* of the rendered line does not: the target
config presents the source's stored secret as a literal password. Reset every
migrated account's credential on the target before cutover.

Secret values are deliberately not reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, stored credential material is
operator-traceable even when hashed or encrypted, and a document that quotes
the value it describes defeats its own redaction. Only the shape is recorded:
AOS-S secrets in this corpus carry a `<algorithm>:<payload>` prefix rather
than a crypt(3) `$n$` marker, which is exactly why the XR renderer's type-digit
sniff misses them.

## What actually survives

For a reader skimming for the positive result: `hostname`, DNS and NTP
servers, the complete interface inventory with descriptions, admin state and
both IPv4 and IPv6 addressing, all static routes (destination, gateway,
metric, description and VRF all compared, all preserved on the 5 populated
cells), local user identity, and one of the two LAGs.

What does not: the VLAN database in its entirety, SNMP in its entirety,
RADIUS in its entirety, interface type classification, and the second LAG.
