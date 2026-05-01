# Aruba AOS-S to Juniper Junos — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/aruba_aoss__juniper_junos.yaml`
per-field expectations.  See sibling `README.md` (one level up) for
the canonical schema definition.

This is a **switch-to-DC-router** pair (AOS-S = HPE ProCurve heritage
campus L2 / basic-L3 switch; Junos = full DC-class router with
EVPN-VXLAN + apply-groups inheritance).  The asymmetry shapes the
cross-pair:

* The Aruba source is L2 / basic-L3 only, so most Junos-only L3 / DC
  surface (VRFs, VXLAN, EVPN, apply-groups) is structurally empty
  on the source side rather than actively dropped on render.
* The wire formats differ fundamentally — Aruba uses stanzas with
  `;` comment markers and VLAN-centric port lists; Junos uses
  `set` form with hierarchical inheritance, name-keyed VLANs, and
  per-unit interface families.

The good news: the keyword-stable surface (`hostname`, `ip route`,
`snmp-server community`, `radius-server host`) tracks closely
through the canonical model despite the syntactic gap.

| Topic | Summary |
|---|---|
| `vlans.md` | Aruba VLAN-centric `untagged 1-24 / ip address X/N` -> Junos `set vlans NAME vlan-id N` + per-interface `family ethernet-switching vlan members`.  Name sanitisation (underscore -> hyphen). |
| `port_naming.md` | Aruba bare-numeric `1` / `A1` / `1/1` / `Trk1` -> Junos `ge-0/0/0` / `ae0` (default rename mesh).  Speed hint defaults to `ge-`. |
| `ip_addressing.md` | CIDR -> CIDR; v6 link-local discriminator preserved; SVI absorption -> Junos `irb` synthesis. |
| `static_routes.md` | Aruba CIDR + dotted-mask + `ip default-gateway` -> Junos `set routing-options static route X/N next-hop Y`. |
| `snmp.md` | v1/v2c quoted-community + Operator/Manager mapping; v3 USM passphrases NOT cross-compatible (engineID-derived salt). |
| `local_users.md` | Aruba two-role (manager/operator) -> Junos `class super-user` / `operator`; SHA-1 / bcrypt hashes Aruba-only. |
| `lags.md` | Aruba `Trk<N>` -> Junos `ae<N>`; `dt-lacp` / `fec` modes lossy; chassis-wide `device-count` synthesised on render. |
| `system_services.md` | Hostname (quoted) / DNS (priority-ordered) / SNTP -> NTP; domain / syslog / timezone / mtu absent on Aruba parse path. |
| `radius.md` | Flat `radius-server host` + global key form -> Junos `set system radius-server <host> secret`.  Shared secret cross-decrypt impossible. |
| `vrf_unsupported.md` | Aruba has no VRF concept (`routing-instances` always empty on Aruba source). |
| `vxlan_evpn_unsupported.md` | Aruba has no VXLAN / EVPN concept (`vxlan_vnis` always empty on Aruba source). |

Retrieved 2026-05-01.

See also: `../README.md` (citation cache layout).
