# Juniper Junos to Aruba AOS-S — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/juniper_junos__aruba_aoss.yaml`
per-field expectations.  See sibling `README.md` (one level up) for
the canonical schema definition.

This is a **DC-router-to-switch** pair (Junos = full DC-class router
with EVPN-VXLAN + apply-groups inheritance; AOS-S = HPE ProCurve
heritage campus L2 / basic-L3 switch).  The asymmetry is heavier in
this direction than in the reverse:

* Junos source carries VRFs, VXLAN, EVPN, apply-groups, sub-interface
  units, instance-typed routing-instances — none of which Aruba can
  render.  These are `unsupported` (active drop on render) rather
  than `not_applicable` (structurally empty).
* Junos's hash formats (`$1$` / `$5$` / `$6$`) and Aruba's
  (sha1 / bcrypt) do not overlap; cross-vendor migration of user
  accounts always requires re-keying.
* The aruba_aoss codec lacks parse / render paths for several
  Junos-supported scalars (`domain`, `syslog`, `mtu`, `timezone`),
  so even Tier-1 surface partially drops.

The good news: the keyword-stable surface (`set vlans`, `set system
host-name`, `set snmp community`, `set system radius-server`) maps
cleanly through the canonical model when both sides have a parse /
render path.

| Topic | Summary |
|---|---|
| `vlans.md` | Junos `set vlans NAME vlan-id N` + per-interface `family ethernet-switching vlan members` -> Aruba VLAN-centric `untagged 1-24` / `tagged ...` + absorbed SVI. |
| `port_naming.md` | Junos `ge-0/0/0` / `ae0` / `irb.100` -> Aruba `1` / `Trk1` / VLAN-absorbed (default rename mesh).  Speed hint and loopback drop. |
| `ip_addressing.md` | CIDR -> CIDR; v6 link-local discriminator preserved; Junos `irb` units transpose to VLAN-absorbed SVI on Aruba. |
| `static_routes.md` | Junos `set routing-options static route X/N next-hop Y` -> Aruba `ip route X/N Y`.  Per-VRF / qualified-next-hop / IPv6 lossy. |
| `snmp.md` | v1/v2c communities + trap-group flatten; v3 USM Junos-only auth/priv variants collapse + passphrase re-key required. |
| `local_users.md` | Junos `class super-user` / `operator` / `read-only` -> Aruba `manager` / `operator`; `$1$/$5$/$6$` hashes Aruba-incompatible. |
| `lags.md` | Junos `ae<N>` -> Aruba `Trk<N+1>`; LACP active/passive collapse to `lacp` keyword. |
| `system_services.md` | Hostname / DNS round-trip; NTP protocol distinction; domain / syslog / timezone drop on Aruba target (codec parse gap). |
| `radius.md` | Junos `set system radius-server <host> secret` -> Aruba `radius-server host <ip> key`.  Shared secret cross-decrypt impossible. |
| `vrf_unsupported.md` | Junos `set routing-instances` actively populated; Aruba has no VRF concept (active drop on render). |
| `vxlan_evpn_unsupported.md` | Junos VXLAN VNI bindings + EVPN Type-5 routes drop on Aruba render. |
| `apply_groups.md` | Junos's apply-groups inheritance flattens into canonical content; the group structure itself drops on Aruba render. |

Retrieved 2026-05-01.

See also: `../README.md` (citation cache layout).
