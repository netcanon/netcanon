# IOS-XR → Arista EOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/cisco_iosxr__arista_eos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`cisco_iosxr.parse()` → `arista_eos.render()` → `arista_eos.parse()` on each of
the 12 fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **12**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`cisco_iosxr` in this corpus is a **service-provider edge/core router**:
4-segment interface names (`GigabitEthernet0/0/0/1`), channelized
sub-interfaces, `Bundle-Ether` LAGs, `BVI` interfaces, `MgmtEth0/RP0/CPU0/0`,
and a heavy VRF surface whose RD is harvested from `router bgp` rather than
read from a VRF stanza. `arista_eos` is a **DC leaf/spine**.

The shared surface is therefore the **routed edge** — interface addressing,
MTU, admin state, VRF identity, static routes, local users. There is no campus
L2 surface on either side of this pair to migrate.

## The structural finding — and it is the opposite of the AOS-CX pair

Anyone arriving here from `aruba_aoscx_to_arista_eos/canonical_surface.md`
should read this section before assuming the same shape. There, the dominant
loss was the interface inventory shrinking 9 → 5, which dragged every
`interfaces[].*` sub-field into `lossy` whether or not the attribute itself was
at fault.

**Here the interface inventory is fully preserved.**

| measurement | value |
|---|---|
| source interface records, all 12 cells | **156** |
| records after parse → render → re-parse | **156** |
| cells where the interface name set differs | **0** |

IOS-XR 4-segment names, channelized sub-interfaces (`…0/0/0/1.100`),
`Bundle-Ether`, `BVI` and `MgmtEth0/RP0/CPU0/0` all survive the EOS render
verbatim.

The consequence is the useful one: **every interface loss on this pair is a
genuine per-attribute loss** that stands on its own measurement, and every
interface sub-field that survives is recorded `good` rather than being dragged
down by a vanishing parent. Nothing in the interface block is correlated drift.

## Per-field measurement (12 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 12 | 0 | 0 |
| domain | 8 | 0 | 4 |
| ntp_servers | 1 | 0 | 11 |
| interfaces[].name / enabled / mtu / ipv4_addresses / ipv6_addresses | 12 | 0 | 0 |
| interfaces[].description | 8 | 1 | 3 |
| interfaces[].interface_type | 0 | 12 | 0 |
| interfaces[].lag_member_of | 0 | 4 | 8 |
| vlans[].id | 4 | 0 | 8 |
| static_routes | 6 | 0 | 6 |
| lags | 0 | 4 | 8 |
| local_users[].name / role | 5 | 4 | 3 |
| local_users[].hashed_password | 0 | 9 | 3 |
| routing_instances[].name | 8 | 0 | 4 |
| routing_instances[].description | 0 | 1 | 11 |

Fields trivially empty on all 12 cells: `dns_servers`, `timezone`,
`syslog_servers`, `interfaces[].vrrp_groups`, `vlans[].name`,
`vlans[].ipv4_addresses`, `vlans[].untagged_ports`, `vlans[].tagged_ports`,
`vlans[].description`, `dhcp_servers`, all five `snmp.*` keys,
`radius_servers`, all three `vxlan_vnis[].*` keys, `evpn_type5_routes`,
`raw_sections`, `apply_groups`, `group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift

| sub-field | records affected | of total | shape |
|---|---|---|---|
| `interface_type` | 138 | 156 | value → empty string |
| `lag_member_of` | 15 | 15 populated | value → null |
| `description` | 2 | 156 | surrounding `"` characters stripped |
| `enabled` / `mtu` / `ipv4_addresses` / `ipv6_addresses` / `vrrp_groups` | 0 | 156 | — |

`interface_type` breaks down cleanly by type: **126** `ianaift:ethernetCsmacd`,
**10** `ianaift:ieee8023adLag` and **2** `ianaift:other` all drop, while all
**18** `ianaift:softwareLoopback` records survive. EOS re-derives the type from
`interface Loopback<N>`; it cannot re-derive it from
`interface GigabitEthernet0/0/0/1`, because EOS names do not encode speed.
Both matrices already declare `/interfaces/interface/config/type` lossy.

## Source-side gaps vs target-side drops

`cisco_iosxr` declares these **unsupported at the exact path**, so as a
*source* it never emits them and there is nothing for EOS to lose:

`/dhcp-servers/pool` · `/radius-servers/server/host` ·
`/radius-servers/server/key` · `/snmp/community` ·
`/snmp/v3-user/{auth-protocol,priv-protocol,priv-passphrase,group}` ·
`/vxlan-vnis/{vni,source-interface,udp-port}` · `/evpn-type5-routes/route` ·
`/anycast-gateway-mac` · `/interfaces/interface/vrrp-groups/group/*` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan}`

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational: for most of them **arista_eos declares the field SUPPORTED** —
DHCP pools, SNMP communities/location/contact/trap-hosts, VXLAN VNIs, VRRP
groups and the anycast gateway MAC. Re-authoring them on the target will
stick, and the migration report should say so rather than implying the target
cannot hold them.

`timezone` is different: **both** matrices declare `/system/timezone`
unsupported, a symmetric gap. That one is `unsupported`.

The four `vlans[].*` `not_applicable` entries are grounded in measurement, not
just declaration: 4 of 12 cells populate `vlans`, each with exactly **one**
record carrying **only** an `id` (35, 100, 200). These are dot1q encapsulation
VLANs behind a sub-interface or BVI, not a campus VLAN database — name,
description, addressing and port membership are empty on every one. The
matching L3 lives on the interface record, where it round-trips cleanly.

`snmp` is the starkest source-side gap: the cisco_iosxr parser produced **no
SNMP block at all** — `intent.snmp` is `None` on all 12 fixtures.

## Three findings worth carrying forward

### 1. The LAG surface is a total concept drop

10 LAG records across the 4 bundle-carrying cells become **0** after the
round-trip, and the rendered EOS config contains no `Port-Channel` interface
and no `channel-group` line anywhere. All 15 interface records with a
`lag_member_of` value come back null while the member ports themselves survive
— which is the dangerous shape, because the ports come up standalone rather
than bundled.

`cisco_iosxr` declares `/lags/lag/name`, `/lags/lag/members` and
`/lags/lag/mode` supported, so the source side is not the problem.

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported`, since
a vanished record is not lossy (#436) and `lossy` — which warns but stays
compatible — would badly understate losing every bundle on a provider-edge
router. **They are one mechanism, not two independent findings.** Neither is
cited as evidence for the other; each is recorded where it is measured.

Standing observation, carried over unchanged from the aruba_aoscx pair because
it is the same fact: the arista_eos matrix declares **nothing** for
`/lags/lag` — neither supported, lossy nor unsupported — while dropping LAGs
entirely. That is a matrix under-declaration, not a pair-specific fact, and
belongs to a codec change rather than to this file.

### 2. Accounts disappear, and which ones is predictable

9 of 12 cells populate local users. On 4 of them, **5 user records vanish from
the render**. The rule is clean:

| source secret form | outcome |
|---|---|
| type-7 (reversible vendor obfuscation) | **account dropped entirely** |
| type-5 (crypt `$1$`) | account survives |
| type-10 (crypt `$6$`) | account survives |

On `batfish_vpnv4_pe1.txt` the single type-7 account is the only user, and the
render emits **zero** `username` lines.

This is recorded `lossy` rather than `unsupported`: arista_eos declares
`/local-users/user/name` supported and does emit users, so it is a partial
record loss inside a concept the target models — not the concept-level gap
`lags` is. Diff the source account list against the render before cutover; a
silently missing admin account is how a migration locks you out.

`local_users[].role` is `good`, and deliberately so. Role is preserved on every
record that survives — zero role drift on any cell. That key measures what
happens to the *value* when the record survives, and the answer is: nothing.
The accounts that vanish are accounted for once, under `local_users[].name`.
Recording the same disappearance twice would double-count one loss.

### 3. Type-10 secrets degrade into a cleartext marker

`local_users[].hashed_password` drifts on all 9 populated cells, with two
distinct failure modes:

- **type-5 (`$1$`)** — the hash body survives intact, re-encoded with an
  EOS-side `arista:5:` prefix. The canonical value differs; the credential is
  carried. Recoverable.
- **type-10 (`$6$`, SHA-512)** — the credential does **not** survive. The
  render emits the account with the EOS *cleartext* secret marker, in the form
  `username <name> … secret 0 10 <hash>`, where `secret 0` means plaintext and
  the token EOS reads as the password is the literal string `10` — the
  leftover IOS-XR type marker. Re-parsing that line yields a canonical
  `hashed_password` of exactly `arista:0:10`; the SHA-512 body is gone.
  Measured on 4 records across 2 cells (`iosxr_design_cst_pa3_xr752.cfg`,
  `kitchen_sink.cfg`).

Treat every migrated account as having no usable credential, and set passwords
on the target before cutover.

## Credential material

No hash body is reproduced in this file or in the expectation YAML — only the
crypt-scheme marker (`$1$`, `$6$`), the IOS-XR type number and the string
length are described. Per `AGENTS.md`, password hashes are operator-traceable
even when they are hashes, and a document that quotes the value it describes
defeats its own redaction. The one literal that *is* quoted — `arista:0:10` —
is a degradation artifact containing no source key material.

## One drift-shape reading that is wrong

A mechanical "is the target side empty?" pass over this pair reports
`routing_instances` as a **total drop**. It is not. The round-trip shows the
VRF records surviving with their names on all 7 cells that carry them —
`AZURE`, `red` / `blue` / `management`, `CUSTOMER`, `CUSTOMER-A` / `MGMT` and
the numeric `100`. What actually empties is `routing_instances[].description`,
on the single cell that sets one: `customer a l3vpn` and
`out-of-band management` both return empty.

arista_eos already declares `/routing-instances/instance/description` lossy and
states the cause — the VRF is harvested with its RD and route-targets, which
render under `router bgp / vrf`, but there is no `vrf instance <name> /
description` emit path. So the field is `lossy`, the instance identity is
`good`, and the "total drop" reading is an artifact of reading a sub-field
emptying as a record vanishing.

It still matters: on a PE, the VRF description is usually the only place the
customer name is written down.
