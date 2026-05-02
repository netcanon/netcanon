# Juniper Junos to Arista EOS — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/juniper_junos__arista_eos.yaml`
per-field expectations.  See sibling `README.md` (one level up) for
the canonical schema definition.

This is a **DC-leaf-to-DC-leaf** pair — both vendors target the same
EVPN-VXLAN spine-leaf use case at parity feature depth.  The forward
direction (`arista_eos_to_juniper_junos/`) covered the canonical
overlay surface (VLAN-to-VNI binding, VTEP source interface, MAC-VRF,
EVPN Type-5).  The inverse direction here adds Junos-source-only
considerations:

* Junos's apply-groups inheritance flattens into canonical content on
  parse; the group structure itself drops on Arista render (no Arista
  analogue to `set apply-groups`).  Operator's intent is preserved
  via the flattened content; the inheritance plumbing is lost.
* Junos's `instance-type virtual-router` (CE-LAN style isolation
  without RD/RT) has no Arista analogue; only `vrf` and `mac-vrf`
  instance types translate cleanly.
* Junos models per-unit interface detail (sub-interfaces with
  independent families) that Arista's flat-interface model collapses;
  unit 0 round-trips, unit > 0 typically degrades.
* Local-user SSH public-key authentication (`set system login user X
  authentication ssh-rsa "<key>"`) on Junos has no canonical fit in
  the hash-shaped `CanonicalLocalUser.hashed_password` field —
  parse-and-ignore today (deferred).

Where forward-direction topics already cover the same vendor primitive
(e.g. VLAN-to-VNI binding, VTEP source interface, IPv6 link-local
discrimination), the YAML's `references:` block cites those forward
docs by `path:` rather than duplicating content here.  Topics in this
directory cover Junos-source-specific considerations or asymmetries
the forward direction did not surface.

| Topic | Summary |
|---|---|
| `system_services.md` | Junos `set system host-name` / `domain-name` / `name-server` / `ntp server` / `time-zone` -> Arista equivalents.  Olson timezone preserved (both accept). |
| `interfaces.md` | Junos `ge-0/0/0` / `xe-0/0/0` / `et-0/0/0` -> Arista `Ethernet1`.  Speed prefix lost on collapse to bare `Ethernet<N>`; per-unit families flatten. |
| `vlans.md` | Junos `set vlans NAME vlan-id N` (named, hyphen / period only) -> Arista `vlan N` (id-keyed, name liberal).  Junos name constraints survive Arista. |
| `vxlan_mac_vrf.md` | Junos `set vlans NAME vxlan vni X` + `set switch-options vtep-source-interface lo0.0` -> Arista `interface Vxlan1` per-VLAN VNI bindings.  MAC-VRF instance-type translates. |
| `static_routes.md` | Junos `set routing-options static route X/N next-hop Y` -> Arista `ip route X/N Y`.  Junos's `preference` / `qualified-next-hop` drop. |
| `snmp.md` | Junos `set snmp community` + trap-group + v3 USM -> Arista flat `snmp-server` directives.  v3 protocol variants narrow. |
| `local_users.md` | Junos `class super-user` / `operator` / `read-only` + `$1$/$5$/$6$` hashes -> Arista privilege levels + sha512.  SSH-key form drops. |
| `lags.md` | Junos `ae0` / `ether-options 802.3ad ae<N>` -> Arista `Port-Channel<N>` / `channel-group N mode <active|passive>`.  Index preserved. |
| `apply_groups_partial.md` | Junos's `groups <G> { ... } apply-groups <G>` flattens on parse; the inheritance structure itself drops on Arista render. |

Retrieved 2026-05-01.

See also: `../README.md` (citation cache layout); the forward-direction
peer at `../arista_eos_to_juniper_junos/_INDEX.md` shares many of the
same vendor primitives at the cross-pair level.
