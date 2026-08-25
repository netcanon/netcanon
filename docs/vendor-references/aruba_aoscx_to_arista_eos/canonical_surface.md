# AOS-CX → Arista EOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__arista_eos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured mesh run. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Device-class framing

`aruba_aoscx` in this corpus is a **campus access/aggregation** switch;
`arista_eos` is a **DC leaf/spine**. The pair is therefore asymmetric: the
shared surface is the L2/L3 edge (VLANs, SVI addressing, port membership, LAGs,
local users, SNMP), not the fabric surface EOS is designed around.

## The structural finding

The dominant loss is **not** per-attribute — it is the interface inventory
shrinking, 9 → 5 on the representative cell. AOS-CX enumerates every physical
campus port in `show running-config`, including ports carrying only default
configuration; the EOS render emits what the canonical model considers
configured.

Consequence, and the reason it is worth stating loudly: **every
`interfaces[].*` sub-field measures as drifted on all 7 cells**, because a
dropped record takes all of its attributes with it. Declaring any of them
`good` — even ones like `description` or `mtu` that are declared supported on
both sides and are intact on every *surviving* record — would manufacture a
false `CODEC_BUG`.

This is the trap that makes reasoning from the capability matrices alone
unsafe on this pair. Both matrices declare description, enabled and MTU
supported. The matrices are right; the records still vanish.

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces (all sub-fields) | 0 | 7 | 0 |
| vlans[].id | 7 | 0 | 0 |
| vlans[].name | 5 | 2 | 0 |
| vlans[].ipv4_addresses | 0 | 5 | 2 |
| vlans[].untagged_ports | 0 | 7 | 0 |
| vlans[].tagged_ports | 1 | 4 | 2 |
| vlans[].description | 0 | 4 | 3 |
| static_routes | 2 | 0 | 5 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 3 |
| snmp.v3_users | 2 | 2 | 3 |
| lags | 0 | 7 | 0 |
| local_users[].name / role | 6 | 0 | 1 |
| local_users[].hashed_password | 0 | 6 | 1 |
| vxlan_vnis[].vni / vlan_id | 3 | 0 | 4 |
| routing_instances[].name | 3 | 0 | 4 |
| anycast_gateway_mac | 5 | 0 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`evpn_type5_routes`, `raw_sections`, `apply_groups`, `group_content`,
`vxlan_vnis[].mcast_group`, `routing_instances[].description`.

## Source-side gaps vs target-side drops

AOS-CX declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for EOS to lose:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/syslog-server` · `/dhcp-servers/pool`

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational: for `dns_servers`, `ntp_servers` and `syslog_servers`,
**arista_eos declares the field SUPPORTED** — so re-authoring them on the
target will stick, and the migration report should say so rather than implying
the target cannot hold them.

`timezone` is different: **both** matrices declare it unsupported, a symmetric
gap. That one is `unsupported`.

## Two findings worth carrying forward

**1. `lags` here is a real loss, not the naming artifact.** The audit
canonicalises LAG names before comparing (`_LAG_NAME_FIELDS`), so a bare
`lag1` ↔ `Port-Channel1` rename does not count as drift. It drifts anyway on
all 7 cells, and `interfaces[].lag_member_of` drifts independently on the same
cells. Membership is genuinely lost.

**2. `anycast_gateway_mac` is `good` but do not read it as "anycast works".**
The fabric-wide MAC round-trips on all 5 populated cells while the per-SVI
`virtual_gateway_address` does **not** (`vlans[].ipv4_addresses` drifts on all
5 cells that populate it). The MAC survives; the gateway addressing it is
supposed to serve does not.

## Credential material

`local_users[].hashed_password` drifts on all 6 populated cells. AOS-CX stores
the user secret in its own encrypted form — an `AQB…`-prefixed ciphertext blob
— which is neither a crypt(3) hash nor anything the EOS render can re-emit.

Every migrated account therefore arrives **without a working credential**.

The ciphertext values are deliberately not reproduced in this file or in the
expectation YAML. Per `AGENTS.md`, encrypted secrets are operator-traceable
even when encrypted, and a document that quotes the value it describes defeats
its own redaction.
