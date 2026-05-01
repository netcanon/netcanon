# Cisco IOS-XE CLI to Cisco IOS-XE OpenConfig NETCONF — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/cisco_iosxe_cli__cisco_iosxe.yaml`
per-field expectations.  See `../README.md` for the schema spec.

This pair is **same vendor, different wire format** — both codecs
target Cisco IOS-XE 17.x platforms.  They differ only in HOW the
config is delivered:

* `cisco_iosxe_cli` — operator-paste `running-config` text
* `cisco_iosxe` — NETCONF / OpenConfig YANG-modelled XML

In theory the cross-pair should be near-100% bidirectional because
both wire formats target the same operational state.  In practice
this repository's `cisco_iosxe` codec is a Phase-0.5 stub that
declares many paths as `supported` in its capability matrix but does
not actually emit them on render — its parse/render only walks
`<interfaces>` and IPv4 / IPv6 addresses.  Drift on this cross-pair
is therefore **codec wire-up gap** rather than **model gap**.

## Topics

| File | Topic | Citation ids |
|---|---|---|
| `oc-vs-native-yang.md` | OpenConfig vs Cisco-IOS-XE-native YANG framing — what each model covers and what gets stripped | `cisco-yang-blog`, `iosxe-prog-guide-1715` |
| `interfaces.md` | Interface name / description / enabled / mtu / type / IPv4 / IPv6 — the canonical-supported core | `oc-interfaces`, `iosxe-interface-cg` |
| `vlans-and-switchport.md` | VLAN database + switched-vlan augment (interface-mode, access-vlan, native-vlan, trunk-vlans) | `oc-vlan`, `iosxe-vlan-cg-1717` |
| `static-routes.md` | Static routes — default VRF and per-VRF; OpenConfig network-instance form | `oc-network-instance`, `iosxe-routing-cg` |
| `vrf-and-network-instance.md` | VRF declarations (`vrf definition` <-> `<network-instance type=L3VRF>`) | `oc-network-instance`, `iosxe-multivrf` |
| `snmp.md` | SNMP v1/v2c/v3 — Cisco-IOS-XE-snmp native model + OpenConfig partial | `iosxe-snmp-17`, `cisco-snmp-yang` |
| `system-services.md` | hostname / domain / DNS / NTP / timezone / syslog | `oc-system`, `iosxe-systemmgmt-cg` |
| `local-users-and-aaa.md` | Local users (privilege + secret hash) + RADIUS server config | `oc-system-aaa`, `iosxe-secusr-cg` |
| `banner-and-cli-only.md` | What CLI carries that OpenConfig has no slot for: banner motd, service timestamps, comments, ACLs, route-maps | `cisco-iosxe-native-yang`, `cisco-yang-blog` |
| `vxlan-and-evpn.md` | VXLAN + EVPN Type-5 — both codecs `unsupported` in v1 | `iosxe-vxlan-cg`, `oc-evpn` |
| `lags-and-dhcp.md` | Port-channel LAGs + IP DHCP pools — OpenConfig partial coverage | `oc-if-aggregate`, `iosxe-dhcp-cg` |

## Re-fetch notes

- `Cisco-IOS-XE-native.yang` is split across many feature-specific
  submodules (`Cisco-IOS-XE-ip`, `Cisco-IOS-XE-snmp`,
  `Cisco-IOS-XE-spanning-tree`, `Cisco-IOS-XE-vrf` etc.) and the
  monolithic top-level module mostly contains `include` statements.
  Direct YangModels GitHub fetches return a partial view — for the
  full enumeration of native-model containers consult the device
  itself via `show netconf-yang capabilities` or the YangModels
  `vendor/cisco/xe/<version>/` directory listing.
- The `show running-config | format netconf-xml` command (IOS-XE
  17.7+) is the device's authoritative ground truth for the
  CLI -> YANG translation it performs internally — but it emits the
  **native** model, not OpenConfig.  Future passes that want to
  characterise specific field drift should run this against a real
  Catalyst 9300 / Cat8000V to ground each field in actual wire
  output.

See also: `../README.md` (schema spec for the cross-vendor expectation
YAMLs).
