# Netcanon vs adjacent tools

Network engineers arriving here from "I'm looking for a Capirca /
Batfish / NAPALM alternative" deserve a clear answer about whether
Netcanon is competing or complementary.  This page lays out where
it fits.

---

## TL;DR

Netcanon translates between vendors' **native running-config formats**
through a canonical intermediate.  Most adjacent tools occupy a
different slot:

- **Batfish** — parses + analyses (no render)
- **Capirca / Aerleon** — render from a DSL forward-only (no parse)
- **NAPALM / Netmiko / Nornir** — orchestrate device interactions
  (no translation)
- **NetBox / Nautobot** — source-of-truth + Jinja rendering (no
  translation between vendor formats)
- **ciscoconfparse** — structural parsing of Cisco only

Netcanon's niche: **bidirectional between native vendor formats**, with
a cross-mesh audit that catches silent translation errors and explicit
per-field capability declarations.

---

## What device classes this is for

The table below answers *which tool*.  This section answers *which
box* — the axis a vendor list alone never settles.

| Device class | Netcanon's fit |
|---|---|
| **Switches** — campus / DC access, aggregation, leaf-spine | Primary target.  Most of what such a box carries is inside the canonical model: interfaces, VLANs and L2 membership, LAGs, SVIs, static routes, VRFs, SNMP, local users. |
| **Routers** — branch, edge, service-provider | Primary target.  Same canonical surface.  Dynamic-routing protocol stanzas (BGP / OSPF / IS-IS) are Tier 3 — detected when parsing, never rendered. |
| **Firewall platforms** — FortiGate, OPNsense | **The L2/L3 layer only.**  That covers interface addressing, VLAN interfaces and local users.  The policy table, NAT, VPN and UTM are out of scope in either direction — and on a firewall appliance those are the majority of the configuration.  If your migration's centre of gravity is policy, Netcanon is the wrong tool; Capirca / Aerleon render that layer for the same targets. |

Each codec declares its own device classes, most specific first, in
`netcanon/migration/vendors/<vendor>.yaml` (`device_classes`).  A codec
whose first declared class is `firewall` sits in the third row above.

---

## Comparison table

| Tool | Scope | Direction | Multi-vendor? | Translation accuracy posture |
|---|---|---|---|---|
| **Netcanon** | Multi-vendor native running-config translation | Parse + Render bidirectional | ✅ Cisco / Juniper / Fortinet / Aruba / Arista / MikroTik / OPNsense / VyOS | Per-field capability matrix (supported / lossy / unsupported with cited reasons); cross-mesh audit harness; explicit Tier-3 boundary; matrix-honesty discipline |
| [**Batfish**](https://github.com/batfish/batfish) | Network config analysis + routing simulation | Parse only | ✅ Many | Models behaviour; doesn't translate to other formats |
| [**Capirca**](https://github.com/google/capirca) / [**Aerleon**](https://github.com/aerleon/aerleon) | Firewall ACL DSL → vendor-native syntax | Render only (DSL → multiple vendors) | ✅ Firewall scope | DSL is the source of truth; not a translator between native vendor formats |
| [**NAPALM**](https://github.com/napalm-automation/napalm) | Get / set running-config; vendor-agnostic device interactions | Wraps device drivers | ✅ | Each device sees its native syntax; no translation |
| [**Netmiko**](https://github.com/ktbyers/netmiko) / [**Nornir**](https://github.com/nornir-automation/nornir) | SSH transport / concurrency framework | Wraps device CLI / NETCONF | ✅ | Orchestration not translation |
| [**Ansible network modules**](https://docs.ansible.com/ansible/latest/network/) | Automation via Jinja + per-vendor modules | Render via templates | ✅ | Templates per-vendor; not a translator |
| [**NetBox**](https://github.com/netbox-community/netbox) / [**Nautobot**](https://github.com/nautobot/nautobot) | Source-of-truth (IPAM / DCIM) + Jinja rendering | Render from data | ✅ | Render from data model, not translate from native running-config |
| [**ciscoconfparse**](https://github.com/mpenning/ciscoconfparse) | Structural parsing of Cisco IOS | Parse only | ❌ Cisco only | Single-vendor structural manipulation |

---

## The backup + sanitiser half

Netcanon is two co-hosted tools.  Everything above is the
**translation** engine; the other half is **backup** — pull
running-configs from devices over SSH / NETCONF / REST, on a schedule —
plus a built-in **config sanitiser**.  Those overlap a different set of
tools than the translation half:

| Tool | Slot | vs Netcanon |
|---|---|---|
| [**Oxidized**](https://github.com/ytti/oxidized) | Multi-vendor config backup + diff (the modern RANCID) | Backup-only — no translation, no per-field audit.  Far broader device-driver coverage; Netcanon's backup half is narrower and exists to *feed* the canonical translation + audit pipeline |
| [**RANCID**](https://shrubbery.net/rancid/) | The original config-backup-and-diff daemon | Mature + battle-tested for backup/diff via a VCS; no web UI, no translation |
| [**netconan**](https://github.com/intentionet/netconan) | Network-config anonymiser (Intentionet, the Batfish authors) | Netcanon ships its own sanitiser (`netcanon sanitize` CLI, the `/sanitize` page, and `POST /api/v1/sanitize` — all one library) wired to the same canonical model, so it scrubs structurally (interface IPs, password hashes, SNMP / RADIUS secrets, hostnames) rather than purely by regex |

If config **backup + diff** is your only need, Oxidized / RANCID are
purpose-built and more mature on device-driver breadth — Netcanon's
backup half exists to feed translation, not to replace a dedicated
backup daemon.  If config **anonymisation** is your only need, netconan
is a focused standalone tool; Netcanon's sanitiser is integrated, so the
same engine that parses a config also scrubs it.

---

## Where Netcanon competes

- **Capirca / Aerleon** for cross-vendor configuration translation.
  But: Netcanon explicitly defers firewall / NAT / VPN / QoS to
  Tier 3 (see [`docs/CAPABILITIES.md`](CAPABILITIES.md)); operators
  with firewall translation as the primary need should use
  Capirca / Aerleon.  Netcanon's scope is the broader configuration
  surface (interfaces, VLANs, static routes, DHCP, NTP, SNMP,
  routing instances, LAGs, local users, etc.), not firewall ACLs.

---

## Where Netcanon is complementary

- **Batfish** — Netcanon translates the config; Batfish analyses
  what it does.  The two compose: translate with Netcanon, validate
  behaviour with Batfish.
- **NAPALM / Netmiko** — Netcanon stores + translates the config;
  NAPALM / Netmiko deploy it back to the target device.  Together
  they form a complete migration pipeline.
- **NetBox / Nautobot** — source-of-truth tools generate the
  desired-state config from a data model; Netcanon translates an
  existing-state config when migrating between vendors.  Different
  inputs, complementary purposes.
- **Ansible** — for the orchestration / push side; Netcanon
  produces the translated config that Ansible then deploys.

---

## What Netcanon won't do

- **Firewall, NAT, VPN, QoS rule translation.**  Explicit Tier-3
  boundary; see [`docs/CAPABILITIES.md`](CAPABILITIES.md).  These
  surfaces are deliberately deferred — we may build a sister
  product for them, but they will not be added to this one.
- **Device deployment.**  Netcanon outputs the translated config;
  deploying it to the target device is the operator's
  responsibility (or via NAPALM / Netmiko / Ansible).
- **Network behaviour simulation.**  That's Batfish's territory.
- **Source-of-truth / IPAM.**  That's NetBox / Nautobot's territory.

---

## See also

- [`docs/CAPABILITIES.md`](CAPABILITIES.md) — what's supported,
  lossy, or out-of-scope per vendor pair, and § Platform fit for the
  per-device-class scope gradient the table above summarises
- [`docs/glossary.md`](glossary.md) — "primary device class" and the
  rest of the vocabulary used here
- [`docs/METHODOLOGY.md`](METHODOLOGY.md) — the matrix-honesty
  discipline that backs the accuracy claim
- [`docs/IDENTITY.md`](IDENTITY.md) — tagline / GitHub
  description / Topics / logo brief
- [`tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md)
  — per-codec certification state
- [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — live cross-mesh audit
