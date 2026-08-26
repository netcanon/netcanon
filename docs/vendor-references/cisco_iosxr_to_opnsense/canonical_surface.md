# IOS-XR → OPNsense: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__opnsense.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` and
the reconciler's structural-collapse rule replayed in memory, so this file and
the ratchet agree by construction. Every claim below that names a count was
re-derived by parsing the fixture with `cisco_iosxr` and rendering it with
`opnsense` directly, not read off the drift matrix.

- Fixture cells: **12** (11 real IOS-XR captures + the synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the codec source, and the measured mesh run. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** —
4-segment interface names, `Bundle-Ether` LAGs, per-VRF static routing, MPLS
L3VPN PE roles, ISIS/SR/SRv6 labs. `opnsense` is a **BSD edge firewall** whose
entire model is `config.xml`.

The pair is therefore asymmetric in a very specific way: the two codecs agree
almost completely on the *interface* plane and almost not at all on the
*routing* plane. There is no campus L2 surface on either side to argue about.

## The structural finding — and it is the opposite of the usual one

On most pairs in this mesh the dominant loss is the interface inventory
shrinking, which makes every `interfaces[].*` sub-field drift for one shared
reason. **That does not happen here.** The interface record count is preserved
on all 12 cells:

| fixture | source ifaces | round-trip ifaces |
|---|---|---|
| batfish_ebgp_border01 | 15 | 15 |
| batfish_ebgp_border02 | 15 | 15 |
| batfish_ibgp_border01 | 17 | 17 |
| batfish_ibgp_rr | 16 | 16 |
| batfish_vpnv4_pe1 / pe2 / pe3 | 6 | 6 |
| iosxr_design_cst_pa3_xr752 | 55 | 55 |
| xrdtools_isis_r1 | 3 | 3 |
| xrdtools_sr_xrd1 | 5 | 5 |
| xrdtools_srv6_pe1 | 3 | 3 |
| kitchen_sink | 9 | 9 |

156 source interface records, 156 survivors. The 4-segment IOS-XR names
(`GigabitEthernet0/0/0/1.35`, `MgmtEth0/RP0/CPU0/0`) come back byte-identical,
and so do description, admin state, MTU, IPv4 and IPv6 addressing and LAG
membership — zero drift on every one of those, on every cell.

So the losses on this pair are **real per-attribute and per-record losses**,
each independently caused, not one structural signal reflected in a dozen
mirrors. Two consequences worth stating loudly:

1. Almost every `interfaces[].*` key is honestly `good` here. Copying the
   "interfaces are lossy because the list shrinks" pattern from a campus pair
   onto this one would be an unevidenced over-claim.
2. Where a loss *is* declared below, it is not corroborated by its siblings —
   each stands on its own measurement.

## The dominant loss is the routing plane

`opnsense` renders no routing construct that IOS-XR's routing config maps onto:

| surface | cells populated | records in | records out |
|---|---|---|---|
| `static_routes` | 6 | 20 | **0** |
| `routing_instances` (VRFs) | 8 | 15 | **0** |
| `ntp_servers` | 1 | 2 | **0** |

All three are whole-record drops, and all three are declared `unsupported` at
the exact path by the `opnsense` matrix — `/routing/static-route`,
`/routing-instances/instance`, `/system/ntp-server`. This is the migration's
headline: an IOS-XR PE carrying customer VRFs and a static-route table arrives
on OPNsense as an interface list and nothing else routing-wise.

The interface-level VRF binding goes with it: `interfaces[].vrf` drifts to
empty on 16 records across 8 cells. That key is not in the audited YAML key
set, so it is recorded here rather than there — it is the same VRF drop seen
from the interface side, not an independent finding.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| interfaces[].name / enabled / ipv4_addresses | 12 | 0 | 0 |
| interfaces[].description | 9 | 0 | 3 |
| interfaces[].mtu | 4 | 0 | 8 |
| interfaces[].ipv6_addresses | 3 | 0 | 9 |
| interfaces[].lag_member_of | 4 | 0 | 8 |
| interfaces[].interface_type | 0 | 12 | 0 |
| vlans[].id | 4 | 0 | 8 |
| static_routes | 0 | 6 | 6 |
| routing_instances | 0 | 8 | 4 |
| ntp_servers | 0 | 1 | 11 |
| lags | 4 | 0 | 8 |
| local_users[].name | 9 | 0 | 3 |
| local_users[].role | 0 | 9 | 3 |
| local_users[].hashed_password | 0 | 9 | 3 |

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`, every `vlans[]` sub-field except
`id`, `dhcp_servers`, all five `snmp.*` keys, `radius_servers`, all three
`vxlan_vnis[]` sub-fields, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`, `anycast_gateway_mac`.

`routing_instances[].description` is deliberately absent from both lists above.
It measures as drifted on the same 8 cells as `routing_instances[].name` — but
only because the parent list emptied, which is a signal `[].name` already
carries. The reconciler collapses it to `STRUCTURAL_ONLY`, so a loss declared
on that key could never be evidenced by any cell. It is recorded `good`; see
the expectation YAML entry for the full reasoning.

## Source-side gaps vs target-side drops

`cisco_iosxr` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for OPNsense to lose:

`/snmp/community` · `/snmp/v3-user/*` · `/radius-servers/server/host` ·
`/radius-servers/server/key` · `/dhcp-servers/pool` · `/vxlan-vnis/*` ·
`/evpn-type5-routes/route` · `/anycast-gateway-mac` ·
`/interfaces/interface/vrrp-groups/group/*`

Those are recorded `not_applicable` **except** where OPNsense declares the same
path unsupported too — a symmetric gap, recorded `unsupported`. The
distinction is operational: for `snmp.community`, `snmp.location`,
`snmp.contact` and `snmp.trap_hosts`, **`opnsense` declares the field
SUPPORTED**, so re-authoring SNMP on the firewall will stick and the migration
report should say so rather than implying the target cannot hold it. For
`/snmp/v3-user`, `/vxlan-vnis/*` and `/anycast-gateway-mac`, both sides
declare unsupported and re-authoring will not help.

Running the other way: `cisco_iosxr` declares `/system/ntp-server` and
`/system/syslog-server` SUPPORTED while `opnsense` declares both
**unsupported** — genuine target-side drops. `ntp_servers` was measured
dropping (2 → 0 on `iosxr_design_cst_pa3_xr752`); `syslog_servers` is not
populated by any committed IOS-XR fixture, so its `unsupported` rests on the
target's declaration and its stated render behaviour, not on an observed
round-trip.

## The VLAN surface exists but is one field wide

`vlans[].id` is `good` — 4 cells populate exactly one VLAN each (35, 35, 200,
100) and every one survives. That is the whole story, because
`cisco_iosxr/parse.py::_parse_dot1q_vlans` synthesises VLAN records from
`encapsulation dot1q <vid>` and returns `CanonicalVlan(id=vid, name="")` —
`name` is hard-coded empty and there is no port membership, no address and no
description. IOS-XR has no `vlan N / name X` stanza to harvest them from.

So `vlans[].name`, `vlans[].description`, `vlans[].ipv4_addresses`,
`vlans[].tagged_ports` and `vlans[].untagged_ports` are **source-side gaps**,
recorded `not_applicable`, even though `cisco_iosxr` declares
`/vlans/vlan/name` supported. The declaration describes the codec's render
side; the parse never produces one.

**Do not read `vlans[].id: good` as "the VLAN migrated."** On all 4 of those
cells the sub-interface tag that *generated* the VLAN record —
`interfaces[].dot1q_vlan` — drops to null (4 records, 4 cells), because
`opnsense` declares `/interfaces/interface/dot1q-vlan` unsupported. The VLAN id
survives as a bare number in a list; the routed sub-interface it belonged to
arrives untagged. That is a reachability change, and it is invisible in the
`vlans[].id` key.

## `interfaces[].interface_type` — a dropped attribute, not a dropped record

`interface_type` drifts on **156 of 156** interface records, on all 12 cells:
`ianaift:ethernetCsmacd`, `ianaift:softwareLoopback` and
`ianaift:ieee8023adLag` all arrive as the empty string. OPNsense's
`config.xml` `<interfaces>` block has no element that carries an ianaift type.

This is declared **`lossy`, not `unsupported`**, and the distinction was
checked rather than assumed. The repo's `_vanish` heuristic — "every drifting
observation shows the target side empty, therefore a total drop, therefore
`unsupported`" — reports `interfaces TOTAL` for this pair. That verdict is
computed at the *parent* level and pools `interface_type`, `vrf` and
`dot1q_vlan` together. At the sub-field level the interface **record** survives
intact on all 156 rows with its name, addressing and admin state, so
`unsupported` (which blocks: `compatible=False`) would overstate a migration
that is otherwise clean on the interface plane. `lossy` warns and stays
compatible, which is the truthful signal. Per netcanon #436 the rule is that a
vanished *record* is not lossy — here no record vanishes.

Supporting the same call from the declarations: `cisco_iosxr` declares
`/interfaces/interface/config/type` **lossy** in its own matrix, and `opnsense`
declares nothing at that path at all — neither supported, lossy nor
unsupported. The nearest target declaration is silence, not a block.

## Credential material

`local_users` records themselves are never lost — 14 source user records, 14
survivors across the 9 cells that populate the field. Both matrices declare
`/local-users/user/name`, `/role` and `/hashed-password` **supported**. Both
sub-fields below nevertheless drift on every single record, which makes the
target matrix an under-declaration on this surface. That is a codec-level
observation, left for a codec change rather than fixed here.

**`role` — a remap, measured on 14 of 14 records.** IOS-XR task-groups
collapse into OPNsense's two-tier model: `root-lr` → `admin` (13 records),
`operator` → `user` (1 record). The value is rewritten, not dropped, so this
is a genuine `lossy`. Any finer IOS-XR task-group grant does not survive.

**`hashed_password` — mixed, and the split is the interesting part.**

- **11 of 14 records lose the secret entirely.** These carry IOS-XR type-5
  (`5 $1$…` md5crypt) or short non-crypt forms. `opnsense/render.py` refuses
  them by design: `_TARGET_ACCEPTS["opnsense"] = {plaintext, bcrypt}` in
  `netcanon/migration/_user_secrets.py`, and a non-migratable hash is replaced
  by an XML review comment inside `<user>` naming the source algorithm, with
  `<password>` omitted. This is the correct, deliberate behaviour — the render
  comment cites `tests/fixtures/real/user_smoke_findings.md` issue #1, where
  emitting a foreign hash into `<password>` verbatim is recorded as a critical
  bug. Every one of those accounts arrives without a working credential and
  must have its password set on the target before cutover.
- **3 of 14 records keep the secret but are re-labelled.** These carry IOS-XR
  **type-10** (`secret 10 $6$…`, SHA-512-crypt). `classify_hash()` recognises
  the bare-digit Cisco forms `5`, `7`, `8` and `9` only; `10` is not in that
  set, so the string falls through to the plaintext branch —
  `classify_hash("10 $6$…")` returns `("plaintext", <the whole input>)` and
  `is_migratable(…, "opnsense")` returns `True`. The renderer therefore writes
  the entire `10 $6$…` string into `<password>` as if it were a literal
  password, and the re-parse tags it `bcrypt:`. Measured signature: the
  round-tripped value is exactly the source value plus a 7-character `bcrypt:`
  prefix (63 → 70, 64 → 71, 106 → 113 characters on the three affected
  records), with the `$6$` digest body unchanged.

  That second bullet is the same shape as the failure the first bullet's guard
  exists to prevent, reached through a type digit the guard does not enumerate.
  `user_smoke_findings.md` does not name type-10. It is recorded here as a
  measured behaviour of this pair; correcting it is a codec change and is out
  of scope for an expectation file.

No hash value, salt or digest is reproduced in this file or in the expectation
YAML. Per `AGENTS.md`, crypt-form secrets are operator-traceable even though
they are one-way, and a document that quotes the value it describes defeats its
own redaction. Only lengths, algorithm identifiers and structural prefixes are
recorded above.

## Two smaller things worth carrying forward

**1. `lags` is clean, and the one declared loss is unexercised.** `opnsense`
declares `/lags/lag/mode` lossy — its `lagg` interface has a single `lacp`
proto with no active/passive distinction, so a `passive` bundle would re-parse
as `active`. No committed IOS-XR fixture carries a passive bundle: the corpus
holds 10 `Bundle-Ether` records across 4 cells, 9 `active` and 1 `static`
(`Bundle-Ether500`), and all 10 round-trip with name, mode and member list
intact. The `good` disposition is honest for this corpus and does not clear
that declared path.

**2. `domain` survives without a source declaration.** `cisco_iosxr` declares
nothing for `/system/domain`, yet the field is populated and preserved on 8 of
8 populated cells (`test.com`, `lab.com`, `test.lab`, `lab.example.net`);
`opnsense` declares `/system/domain` supported. Recorded `good` on the
measurement. The gap is in the source matrix, not in the round-trip.
