# IOS-XR → AOS-S: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__aruba_aoss.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction. Every claim marked *verified* below was additionally
re-derived by hand: `cisco_iosxr.parse()` → `aruba_aoss.render()` →
`aruba_aoss.parse()` over all 12 cells.

- Fixture cells: **12** (11 committed IOS-XR captures + the synthetic
  kitchen-sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router** —
4-segment port names (`GigabitEthernet0/0/0/2`), `Bundle-Ether` LAGs,
`vrf` as a top-level stanza, RD read from `router bgp`. `aruba_aoss` is a
**campus L2/L3 access switch**. The pair is therefore asymmetric in the
opposite direction from most of the mesh: the source carries a heavy routing
surface the target cannot hold at all, while the campus surface the target is
built around (VLAN port membership, SVI-on-VLAN L3, SNMP) is empty on the
source side.

The practical migration this pair describes is narrow: an IOS-XR box being
replaced at a small site by an AOS-S switch that keeps the hostname, the
interface inventory and the global-table routes, and keeps nothing else.

## The structural finding — and how it differs from the campus pairs

On the campus→DC pairs the dominant loss is the interface inventory shrinking.
**That does not happen here.** Every interface record survives:
147 of 147 interface names across the 11 real captures, 9 of 9 on the
kitchen-sink cell (*verified*). `description` (32/32), `enabled` (147/147),
`ipv4_addresses` (54/54) and `ipv6_addresses` (10/10) are preserved on every
record that carries them.

The structural loss on this pair is elsewhere — in three whole *concepts* the
target has no grammar for:

| concept | what happens | claimed by |
|---|---|---|
| VRF / routing-instance | every record dropped, all 8 populated cells | `routing_instances[].name` |
| local user (type-5 / type-7 secret) | record replaced by a `;` review comment | `local_users[].name` |
| memberless LAG bundle | record dropped | `lags` |

Because `routing_instances` loses whole records, the audit marks **every**
`routing_instances[].*` sub-field drifted for that one reason. The reconciler's
STRUCTURAL_ONLY collapse assigns that signal to the first sub-field in YAML key
order, which is why `routing_instances[].name` is `unsupported` and
`routing_instances[].description` is `good` — the description on the
kitchen-sink cell's two VRFs (`customer a l3vpn`, `out-of-band management`) is
genuinely lost, but it is lost *with the record*, and no cell shows a
description drifting on a record that survived. Declaring a loss on the
description key would be unevidenceable by construction.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 0 | 8 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces[].name | 12 | 0 | 0 |
| interfaces[].enabled | 12 | 0 | 0 |
| interfaces[].ipv4_addresses | 12 | 0 | 0 |
| interfaces[].description | 9 | 0 | 3 |
| interfaces[].ipv6_addresses | 3 | 0 | 9 |
| interfaces[].mtu | 0 | 4 | 8 |
| interfaces[].interface_type | 0 | 12 | 0 |
| interfaces[].lag_member_of | 0 | 4 | 8 |
| vlans[].id | 4 | 0 | 8 |
| static_routes | 0 | 6 | 6 |
| lags | 0 | 4 | 8 |
| local_users[].name | 1 | 8 | 3 |
| local_users[].role | 0 | 9 | 3 |
| local_users[].hashed_password | 0 | 9 | 3 |
| routing_instances[].name | 0 | 8 | 4 |
| routing_instances[].description | 0 | 8 | 4 |

Trivially empty on all 12 cells: `dns_servers`, `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, `vlans[].name`, `vlans[].ipv4_addresses`,
`vlans[].untagged_ports`, `vlans[].tagged_ports`, `vlans[].description`,
`dhcp_servers`, every `snmp.*` key, `radius_servers`, every `vxlan_vnis[].*`
key, `evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`anycast_gateway_mac`.

## Source-side gaps vs target-side drops vs symmetric gaps

Three different shapes hide behind "the field is empty on every cell", and the
YAML distinguishes them because they give opposite operator advice.

**Source-side gap → `not_applicable`.** `cisco_iosxr` declares the path
unsupported (or, for the VLAN campus surface, synthesises records that cannot
carry it), so nothing ever reaches the target:

- `/interfaces/interface/vrrp-groups/group` and its seven child paths — and
  `aruba_aoss` declares the group **supported**, so re-authoring VRRP on the
  target will stick.
- `/snmp/community` plus four `/snmp/v3-user/*` paths — `aruba_aoss` declares
  five `/snmp/*` paths supported, so SNMP is re-authorable on the target too.
- `/radius-servers/server/host` + `/key`, `/evpn-type5-routes/route` — neither
  of which `aruba_aoss` declares either, so those are hand work outside the
  migration entirely.
- The VLAN campus sub-fields. IOS-XR does not have a VLAN database; the codec
  synthesises `/vlans/vlan/id` from routed sub-interface `encapsulation dot1q`
  and its own matrix comment records that the name is "always empty" and there
  is "no port membership". *Verified*: across all 12 cells, zero VLAN records
  carry a name, an address, a description, or a tagged/untagged port.

**Target-side drop → `unsupported`.** `aruba_aoss` declares the path
unsupported and renders nothing:

- `/system/domain` — observed, 8 cells (`test.com` → `''`).
- `/system/syslog-server` — declared, never exercised on this corpus.
- `/routing-instances/instance` — observed, 8 cells.

**Symmetric gap → `unsupported`.** Both matrices declare it unsupported:
`/system/timezone`, `/dhcp-servers/pool`, `/vxlan-vnis/*`,
`/anycast-gateway-mac`.

## Four findings worth carrying forward

**1. `lags` and `interfaces[].lag_member_of` drift for ONE reason, not two.**
IOS-XR names bundles `Bundle-Ether<N>`; AOS-S renders `trk<N>`. *Verified*: on
every LAG cell the member list and the LACP mode round-trip byte-identical
(`Bundle-Ether23` → `trk23`, members `Gi0/0/0/2` + `Gi0/0/0/3`, mode `active`)
and only the name token changes. These two keys therefore **do not corroborate
each other** — citing one as evidence for the other would be counting a single
rename twice.

The reason the rename registers as drift at all is a reconciler gap, not a
codec loss: `_LAG_NAME_RE` in `tools/run_phase4_reconciliation.py` canonicalises
`ae` / `Po` / `Port-channel` / `trk` / `agg` / `bond` to a stable `LAG<N>`
token, and **`Bundle-Ether` is not in that set**. Both keys are still declared
`lossy`, because the operator-facing consequence is real — anything keyed on
`Bundle-Ether23` breaks — but the LAG *binding* survives.

**2. `lags` has an independent, genuine record loss underneath the rename.**
*Verified* on `iosxr_design_cst_pa3_xr752.cfg`: 5 bundles in, 3 out. The two
that vanish (`Bundle-Ether2123`, `Bundle-Ether2124`) are exactly the two whose
member list is empty — AOS-S renders a trunk from its ports, so a bundle with
no ports has nothing to render. Configured-but-unpopulated bundles disappear
silently.

**3. A VRF-scoped static route survives into the GLOBAL table.** This is the
most dangerous single behaviour on the pair. `aruba_aoss` declares
`/routing/static-route/vrf` unsupported ("parses-and-ignores in v1"), and
*verified* on two cells the route record survives with its VRF binding
stripped:

- `batfish_vpnv4_pe1.txt`: `11.0.0.0/8 via 11.1.1.2` leaves VRF `blue` and
  lands unscoped.
- `kitchen_sink.cfg`: `10.99.0.0/16 via 203.0.113.2` leaves VRF `CUSTOMER-A`
  and lands unscoped.

Nothing in the render marks it. The failure mode is not a missing route — it
is a route in the wrong table, which is a leak between customers rather than an
outage. Meanwhile routes whose only next-hop is an *interface* vanish outright
(`192.0.2.0/24 → Null0`, `0.0.0.0/1 → Null0`, `2001:db8:23:23::2/128 → BVI500`,
`192.0.2.1/32 → Null0`), because AOS-S renders destination + gateway only.

**4. `interfaces[].name` is `good` but that is preservation, not validity.**
*Verified*: the AOS-S render carries the IOS-XR names through verbatim —
`GigabitEthernet0/0/0/2`, `Bundle-Ether500`, `Loopback0`. Those are not legal
AOS-S port identifiers. The fidelity harness scores whether the identity
survived the round-trip, not whether the rendered text would load on the box;
port-shape translation is a separate step
(`netcanon/migration/canonical/port_names.py::translate_port_names`, engaged by
the rename/override plan paths, not by a bare render). Read `good` here as "no
interface was lost", not as "the config is deployable".

## Two matrix under-declarations, recorded not fixed

- **`/interfaces/interface/config/mtu`** — `cisco_iosxr` declares it supported;
  `aruba_aoss` declares it nowhere at all, and drops it. *Verified* on 4 cells:
  `9216 → null` (×3) and `9192 → null`; the render contains no `mtu` line of
  any kind. The pair-level disposition is `lossy`, matching the sibling
  `cisco_nxos__aruba_aoss` declaration for the same field and the same
  mechanism.
- **`/local-users/user/*`** — `cisco_iosxr` declares name, role and
  hashed-password supported; `aruba_aoss` declares nothing for local users at
  all, while dropping most of them.

Both are codec-matrix work, not per-pair work, and are left for a codec change
rather than papered over here.

## Credential material

`local_users[].hashed_password` drifts on all 9 populated cells, and the
mechanism depends on the IOS-XR secret *type marker*. *Verified* across three
cells:

- **type-5 and type-7 secrets** — the user is not rendered. AOS-S emits a
  `;`-prefixed review comment naming the account and instructing a manual
  password reset, which by design does not re-parse into a user. The account
  vanishes; this is the record-level loss `local_users[].name` claims.
- **type-10 secrets** — the user IS rendered, but the digest is emitted under
  the AOS-S `plaintext` keyword. Re-parsing therefore returns the canonical
  `hashed_password` with a `plaintext:` marker in front of the original string:
  the target's stored credential is the digest treated as a literal password,
  which is not the operator's password and not a hash the box will verify
  against.

Either way, **no migrated account arrives with a working credential.** Set
passwords on the target before cutover.

`local_users[].role` collapses onto the AOS-S two-level model: the render emits
`password manager` / `password operator` only, so *verified* `operator` →
`operator` round-trips while `root-lr` → `manager` on every cell that carries
it. Any finer IOS-XR task-group distinction is gone.

No secret value — hash, ciphertext or plaintext — is reproduced in this file or
in the expectation YAML. Per `AGENTS.md`, secrets are operator-traceable even
when hashed, and a document that quotes the value it describes defeats its own
redaction.
