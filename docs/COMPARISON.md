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

## Comparison table

| Tool | Scope | Direction | Multi-vendor? | Translation accuracy posture |
|---|---|---|---|---|
| **Netcanon** | Multi-vendor native running-config translation | Parse + Render bidirectional | ✅ 8 vendor families | Per-field capability matrix (supported / lossy / unsupported with cited reasons); cross-mesh audit harness; explicit Tier-3 boundary; matrix-honesty discipline |
| [**Batfish**](https://github.com/batfish/batfish) | Network config analysis + routing simulation | Parse only | ✅ Many | Models behaviour; doesn't translate to other formats |
| [**Capirca**](https://github.com/google/capirca) / [**Aerleon**](https://github.com/aerleon/aerleon) | Firewall ACL DSL → vendor-native syntax | Render only (DSL → multiple vendors) | ✅ Firewall scope | DSL is the source of truth; not a translator between native vendor formats |
| [**NAPALM**](https://github.com/napalm-automation/napalm) | Get / set running-config; vendor-agnostic device interactions | Wraps device drivers | ✅ | Each device sees its native syntax; no translation |
| [**Netmiko**](https://github.com/ktbyers/netmiko) / [**Nornir**](https://github.com/nornir-automation/nornir) | SSH transport / concurrency framework | Wraps device CLI / NETCONF | ✅ | Orchestration not translation |
| [**Ansible network modules**](https://docs.ansible.com/ansible/latest/network/) | Automation via Jinja + per-vendor modules | Render via templates | ✅ | Templates per-vendor; not a translator |
| [**NetBox**](https://github.com/netbox-community/netbox) / [**Nautobot**](https://github.com/nautobot/nautobot) | Source-of-truth (IPAM / DCIM) + Jinja rendering | Render from data | ✅ | Render from data model, not translate from native running-config |
| [**ciscoconfparse**](https://github.com/mpenning/ciscoconfparse) | Structural parsing of Cisco IOS | Parse only | ❌ Cisco only | Single-vendor structural manipulation |

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
  lossy, or out-of-scope per vendor pair
- [`docs/METHODOLOGY.md`](METHODOLOGY.md) — the matrix-honesty
  discipline that backs the accuracy claim
- [`docs/IDENTITY.md`](IDENTITY.md) — tagline / GitHub
  description / Topics / logo brief
- [`tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md)
  — per-codec certification state
- [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — live cross-mesh audit
