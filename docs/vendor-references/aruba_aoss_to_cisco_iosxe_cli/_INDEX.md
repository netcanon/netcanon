# Aruba AOS-S to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/aruba_aoss__cisco_iosxe_cli.yaml`
per-field expectations.  See sibling `README.md` (one level up) for the
canonical schema definition.

This is the **reverse direction** of the cisco_iosxe_cli to aruba_aoss
pair (a campus refresh Aruba -> Cisco).  The ProCurve heritage line
is L2/basic-L3 only, so the Aruba source typically carries fewer
features than the Cisco target accepts — the asymmetry shows up in:

* `vrf_unsupported.md` — Aruba never populates VRFs (no concept).
* `dhcp_relay.md` — Aruba is relay-only (no server pools).
* `routing_protocols_unsupported.md` — Aruba lacks BGP / IS-IS / EIGRP.

The good news: the shared CLI lineage (Aruba ProCurve was originally
HP's Cisco-CLI-compatible offering) means the keyword-stable surface
(`hostname`, `vlan N`, `snmp-server`, `radius-server`) tracks closely.

| Topic | Summary |
|---|---|
| `vlans.md` | Aruba VLAN-centric `untagged 1-24 / ip address X/N` -> Cisco port-centric `switchport access vlan N` + separate `interface Vlan<N>`. |
| `port_naming.md` | Aruba bare-numeric `1` / `A1` / `1/1` -> Cisco `GigabitEthernet1/0/1` (default rename mesh). |
| `ip_addressing.md` | CIDR -> dotted-mask normalisation; v6 link-local discriminator preserved. |
| `static_routes.md` | Aruba CIDR `ip route X/N <gw>` -> Cisco dotted-mask `ip route X N <gw>`.  `ip default-gateway` legacy form normalises. |
| `snmp.md` | v1/v2c quoted-community + Operator/Manager mapping; v3 USM passphrases not cross-compatible. |
| `local_users.md` | Aruba two-role (manager/operator) -> Cisco numeric privilege; SHA-1 / bcrypt hashes Aruba-only. |
| `lags.md` | Aruba `Trk<N>` -> Cisco `Port-channel<N>`; `dt-lacp` / `fec` modes lossy. |
| `system_services.md` | Hostname (quoted) / DNS (priority-ordered) / SNTP -> NTP / minute-offset timezone -> name+offset timezone. |
| `vrf_unsupported.md` | Aruba has no VRF concept; field always empty on this direction. |
| `routing_protocols_unsupported.md` | Aruba lacks BGP/IS-IS/EIGRP; OSPF / RIP parse-and-ignore on both codecs. |
| `radius.md` | Flat `radius-server host` + global key form -> Cisco modern `radius server <name>` form. |
| `dhcp_relay.md` | Aruba is relay-only (no DHCP server pools to migrate). |
| `spanning_tree.md` | Aruba MSTP default vs Cisco rapid-pvst default; canonical not modelled, Tier 3. |

Retrieved 2026-04-30 to 2026-05-01.

See also: `../README.md` (citation cache layout).
