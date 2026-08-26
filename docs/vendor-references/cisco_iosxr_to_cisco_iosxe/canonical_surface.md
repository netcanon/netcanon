# IOS-XR → IOS-XE (NETCONF): measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__cisco_iosxe.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every aggregate in the tables below was additionally re-derived by
round-tripping all 12 fixtures directly through the two codecs.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and a direct parse → render → re-parse
> of each committed fixture. Where a disposition rests on a declaration rather
> than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router**:
4-segment interface names, `Bundle-Ether` LAGs, jumbo core MTU, per-interface
VRF bindings, and L3VPN PEs. There is no campus L2 surface to speak of — the
only canonical VLAN records IOS-XR ever produces are synthesised from routed
sub-interface `dot1q` tags (a bare id, with empty name, description and port
lists).

`cisco_iosxe` here is **not** the CLI codec. It is the NETCONF/OpenConfig codec,
and its own capability matrix describes it as a **Phase 0.5 stub**. That single
fact, not any vendor-to-vendor modelling difference, is what this pair measures.
The CLI sibling is `cisco_iosxe_cli`, a separate pair with a separate file.

## The structural finding

The dominant behaviour on this pair is **not** a shrinking interface inventory
and **not** per-attribute degradation. It is a render that emits exactly one
subtree and nothing else.

`CiscoIOSXECodec._render_canonical` walks `intent.interfaces` and builds an
openconfig `<interfaces>` document. It never emits `<system>`, never emits
`<network-instances>`, never walks `intent.vlans`, `intent.static_routes`,
`intent.lags`, `intent.local_users`, `intent.snmp` or `intent.routing_instances`.
The rendered document on `batfish_ibgp_border01.txt` contains no `hostname`
string, no `network-instance` element, no `vlan`, no `user`, no `snmp` and no
`static` anywhere in 6,339 bytes.

The consequence splits the canonical surface cleanly in two, with no middle
ground: what is inside the interfaces subtree round-trips **perfectly**, and
what is outside it **vanishes entirely**. There is not one field on this pair
that arrives degraded-but-present. That is why the expectation YAML declares
**zero `lossy`** fields — every non-`good` field is a total drop, and #436 is
explicit that a vanished record is `unsupported`, not `lossy`.

## Per-field measurement (12 cells)

Record-level aggregate over the whole corpus, reproduced with a direct
parse/render/re-parse of all 12 fixtures:

| surface | source records | surviving | outcome |
|---|---|---|---|
| interfaces (inventory) | 156 | 156 | preserved, **in identical order on every cell** |
| interfaces[].description | 39 populated | 39 | preserved |
| interfaces[].enabled | 156 | 156 identical | preserved |
| interfaces[].interface_type | 156 | 156 identical | preserved |
| interfaces[].ipv4_addresses | 60 addresses | 60 | preserved |
| interfaces[].ipv6_addresses | 11 addresses | 11 | preserved |
| interfaces[].mtu | 11 populated | 0 | dropped |
| interfaces[].lag_member_of | 15 populated | 0 | dropped |
| vlans | 4 | 0 | dropped |
| lags | 10 | 0 | dropped |
| local_users | 14 | 0 | dropped |
| static_routes | 20 | 0 | dropped |
| routing_instances | 15 | 0 | dropped |

Cell-level drift counts (drifted / preserved / trivially empty out of 12):
`hostname` 12/0/0 · `domain` 8/0/4 · `ntp_servers` 1/0/11 ·
`interfaces[].mtu` 4/0/8 · `interfaces[].lag_member_of` 4/0/8 ·
`vlans` 4/0/8 · `static_routes` 6/0/6 · `lags` 4/0/8 ·
`local_users` 9/0/3 · `routing_instances` 8/0/4.

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`, `dhcp_servers`, all five
`snmp.*` keys, `radius_servers`, all three `vxlan_vnis[].*` keys,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## Two losses the key list cannot address

The audited key list has no `interfaces[].vrf` and no `interfaces[].dot1q_vlan`
key, so two real per-record losses have nowhere to be declared and are recorded
here instead:

- **per-interface VRF binding**: 16 records across the corpus carry a `vrf`, and
  all 16 arrive with it empty. This is the loss an SP operator will feel first —
  `routing_instances` vanishing removes the VRF definitions, and this removes the
  interface-to-VRF attachment, so a PE's customer-facing ports land in the global
  table.
- **routed sub-interface 802.1Q tag**: 4 records carry a `dot1q_vlan`, all 4
  arrive `null`. The target declares `/interfaces/interface/dot1q-vlan`
  unsupported (ship-before-wire, GAP 7), so this one is at least honestly
  declared — it simply has no YAML key of its own.

Neither is cited in the YAML as corroboration for any other field. They are
independent observations on records that otherwise survive.

## Structural-only collapse: why five VLAN keys and three others are `good`

`run_phase4_reconciliation` collapses structural drift per (cell, parent list):
the **first** `parent[].sub` key in YAML iteration order claims the
list-length signal, and every later sibling whose drift is *purely* that same
wholesale "all N records dropped" string is reclassified `STRUCTURAL_ONLY`.

So on this pair the record-level loss for `vlans`, `local_users` and
`routing_instances` is carried by `vlans[].id`, `local_users[].name` and
`routing_instances[].name` respectively — each declared `unsupported`. Their
siblings (`vlans[].name`, `.ipv4_addresses`, `.untagged_ports`, `.tagged_ports`,
`.description`; `local_users[].role`, `.hashed_password`;
`routing_instances[].description`) are declared **`good`**, because a loss
declared on them could never be evidenced by any cell — the signal is already
owned by the sibling above.

Read those `good`s narrowly. They mean *"when the record survives, this value
survives intact"*, and on this corpus no record of these three lists survives at
all. **Key order in the YAML is therefore load-bearing**, not cosmetic: moving
`vlans[].id` below its siblings would hand the structural signal to whichever key
came first and invert which declarations are evidenced.

## Source-side gaps vs target-side drops

Almost nothing here is a source-side gap. IOS-XR emits a rich canonical intent;
the stub target drops it. Fields where the **target** declares an exact-path
`unsupported` and the source does not:

`/system/hostname` · `/system/domain` · `/system/dns-server` ·
`/system/ntp-server` · `/system/syslog-server` · `/vlans/vlan/id` ·
`/vlans/vlan/name` · `/routing/static-route` (+ `/gateway`, `/vrf`) ·
`/routing-instances/instance` (+ `/instance-type`) · the whole `/snmp` subtree

These are recorded `unsupported`, never `not_applicable`: re-authoring them on
the target will **not** stick while the codec stays a Phase-0.5 stub, and the
migration report must block rather than warn.

Genuinely symmetric gaps — both matrices declare the path unsupported —
are `timezone`, `dhcp_servers`, `radius_servers`, `vxlan_vnis[].*`,
`evpn_type5_routes`, `anycast_gateway_mac` and the whole
`/interfaces/interface/vrrp-groups/group` subtree. Also recorded `unsupported`.

SNMP is worth a sentence of its own. `iosxr_design_cst_pa3_xr752.cfg` carries
three `snmp-server` lines, and the parsed `CanonicalIntent.snmp` is `None`:
IOS-XR declares SNMP out of v1 scope, so the data never enters the canonical
model. The target then declares the entire `/snmp` subtree unsupported as well.
Both ends are shut, which is why all five `snmp.*` keys are `unsupported` rather
than `not_applicable`.

Only `raw_sections`, `apply_groups` and `group_content` are `not_applicable`:
neither codec populates them, and `apply_groups`/`group_content` are Junos-only
canonical surface.

## Two matrix under-declarations found while authoring

Both are recorded in the YAML `reason` text and left for a codec change rather
than fixed here — they are target-codec facts, not pair-specific ones.

**1. `/interfaces/interface/config/mtu` is declared `lossy`; it is a total
drop.** The declaration's reason describes an IP-vs-link MTU distinction that
survives only in CLI. The canonical render path does not get that far:
`_render_canonical` emits `name`, `description`, `enabled` and `type` into
`<config>` and no `mtu` element at all. The string `mtu` does not appear
anywhere in the rendered XML for a source carrying `mtu 9216`, and all 11
MTU-bearing records across the corpus re-parse with `mtu = None`. (The legacy
dict render path, `_render_interface`, *does* emit `mtu` — the `lossy`
declaration appears to describe that path, which the migration pipeline does not
use.) Per the project rule — empty on the far side ⇒ `unsupported`, present but
degraded ⇒ `lossy` — the YAML declares this `unsupported`.

**2. `/lags/lag` is declared nothing at all.** `cisco_iosxe` lists zero
supported, zero lossy and zero unsupported paths for `lags` and for
`local_users`, while dropping both entirely: 10 LAGs → 0 and 14 users → 0 across
the corpus. An undeclared path is the worse failure mode of the two, because
`classify()` has nothing to warn on.

Note also that `interfaces[].lag_member_of` is **independent** evidence of the
LAG loss, not a restatement of it. The audit canonicalises LAG names before
comparing, so a `Bundle-Ether23` ↔ `Port-Channel23` rename would not count as
drift; what is measured is 15 member records arriving with `lag_member_of =
None`, on interface records that themselves survive. The `lags` list vanishing
and the membership attribute nulling are two separate observations.

## Credential material

`local_users` drops wholesale: 14 accounts across the corpus, 0 survivors. Every
migrated device therefore arrives with **no local accounts at all** — not
accounts with broken passwords, but an empty user database. On a router reached
over the same management plane it is about to be re-homed onto, that is the
finding most likely to cause an outage during cutover.

The secrets in the source corpus span three Cisco password types: type-5
(MD5-crypt, `$1$` family), type-10 (SHA-512-crypt, `$6$` family) and type-7
(the reversible Vigenère encoding). Shapes only — no hash value is reproduced in
this file or in the expectation YAML. Per `AGENTS.md`, hashed secrets remain
operator-traceable, and a document that quotes the value it describes defeats
its own redaction.
