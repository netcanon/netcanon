# VLAN configuration: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.14 VLAN Configuration Guide — Configuring VLANs (Catalyst 9400)](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-14/configuration_guide/vlan/b_1714_vlan_9400_cg/configuring_vlans.html)
Retrieved: 2026-04-30

VLAN definition syntax (global config):

```
Switch(config)# vlan 100
Switch(config-vlan)# name engineering
Switch(config-vlan)# state active
Switch(config-vlan)# exit
```

Membership is **port-centric**: each port carries its own
`switchport access vlan N` or `switchport trunk allowed vlan ...`
line.  The VLAN stanza itself never lists ports.

VLAN ID range 1-4094 (1 reserved as default; 1002-1005 historically
reserved on legacy IOS).  Names truncated to 32 characters.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

VLAN definition syntax (global config) — verbatim shape from the
manual's worked examples:

```
ProCurve(config)# vlan 100
ProCurve(vlan-100)# name "engineering"
ProCurve(vlan-100)# untagged 1-24
ProCurve(vlan-100)# tagged 25-26
ProCurve(vlan-100)# ip address 192.168.10.1/24
ProCurve(vlan-100)# exit
```

Membership is **VLAN-centric**: the VLAN stanza itself enumerates the
port lists with `tagged <port-list>` / `untagged <port-list>` lines.
Port lists accept ranges (`1-24`), comma-separated lists (`25,26`),
or mixed (`A1-A4,B1`).  The SVI's L3 address (`ip address X.X.X.X/N`)
is also absorbed into the VLAN stanza — there is no separate
`interface Vlan100` stanza on AOS-S.

VLAN names are quoted; the manual notes "VLAN names can be 32
characters or fewer".  VLAN IDs 1-4094 are valid (1 reserved as
`DEFAULT_VLAN`).

## Cross-vendor mapping

The canonical model is VLAN-centric (see
`netcanon/migration/canonical/intent.py` design principle 1: "VLANs
carry their port lists, NOT the other way around").  Cross-vendor
translation hinges on the per-vendor projection transforms:

* `project_switchport_to_vlan` — Cisco's per-interface
  `switchport access vlan N` is transposed onto
  `CanonicalVlan.untagged_ports` on parse.
* `project_vlan_to_switchport` — Aruba's `untagged 1-24` is
  re-projected onto each port's `switchport_mode` + `access_vlan`
  before the Cisco renderer walks the interface list.

Round-trips for `CanonicalVlan.id`, `CanonicalVlan.name`, and the
port-membership lists are clean.  The L3-on-VLAN-stanza absorption is
also lossless: Cisco's `interface Vlan100 / ip address X` and
Aruba's `vlan 100 / ip address X/N` both populate
`CanonicalVlan.ipv4_addresses`.

Disposition: **good**.
