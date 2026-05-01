# Cisco IOS-XE OpenConfig NETCONF to Cisco IOS-XE CLI — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__cisco_iosxe_cli.yaml`
per-field expectations.  See `../README.md` for the schema spec.

This is the **NETCONF -> CLI** direction of a same-vendor pair.  The
sibling direction (`cisco_iosxe_cli__cisco_iosxe.yaml` /
`../cisco_iosxe_cli_to_cisco_iosxe/`) is the CLI -> NETCONF mirror.

## Direction-specific framing

The most important fact about this direction is that **the loss
happens upstream of the codec boundary**.  When the device's NETCONF
agent emits the `<get-config>` reply, it has already projected the
running-config through the OpenConfig YANG model layer — anything
OpenConfig doesn't model (banner motd, service timestamps, comments,
ACLs, route-maps, AAA policy) is gone before the codec sees the XML.

Therefore many fields that look "lossy" in the CLI -> NETCONF
direction look `not_applicable` here.  The classification is
schematically different but carries the same operational meaning:
NETCONF is a lossy projection of CLI, and the CLI render is faithful
to the projection rather than to the original device config.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `oc-vs-native-yang.md` | OpenConfig vs Cisco-IOS-XE-native YANG framing — direction-specific consequences | Loss happens upstream of the codec |
| `interfaces.md` | Interface canonical core — what the parser actually populates | Switchport / VLAN / LAG / VRF fields are `not_applicable` (parser never reads them) |
| `vlans-and-switchport.md` | VLAN database + switched-vlan augment | Parser doesn't walk `<network-instances><vlans>` today |
| `static-routes.md` | Static routes via OpenConfig `<network-instances>` | Parser doesn't walk; flips to `good` on default-VRF when wired |
| `vrf-and-network-instance.md` | VRF / network-instance | Parser doesn't walk; flips to `good` on wire-up |
| `snmp.md` | SNMP v1/v2c/v3 | Parser doesn't walk; same-vendor v3 hashes round-trip cleanly when wired (vs cross-vendor re-key) |
| `system-services.md` | hostname / DNS / NTP / timezone / syslog | Parser doesn't walk `<system>`; timezone remains lossy after wire-up due to CLI-vs-IANA tz string format |
| `local-users-and-aaa.md` | Local users + RADIUS | Hash + RADIUS-key continuity is the cleanest same-vendor win |
| `banner-and-cli-only.md` | What CLI carries that OpenConfig doesn't model | Uniformly `not_applicable` (source never had it) |
| `vxlan-and-evpn.md` | VXLAN + EVPN Type-5 | Both codecs `unsupported` until VXLAN wire-up arrives |
| `lags-and-dhcp.md` | Port-channel LAGs + IP DHCP pools | LAG flips to `good` on wire-up; DHCP server stays `unsupported` (OpenConfig model gap) |

## Re-fetch notes

The same notes apply as in the sibling direction's INDEX.  The
authoritative ground truth for any specific field's CLI <-> NETCONF
correspondence is the device's own
`show running-config | format netconf-xml` output (IOS-XE 17.7+) —
but that output uses the **native** model, not OpenConfig, so it
characterises a different translation surface than the codecs in
this repository.

See also: `../cisco_iosxe_cli_to_cisco_iosxe/_INDEX.md` (sibling
direction) and `../README.md` (schema spec).
