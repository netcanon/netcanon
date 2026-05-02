# Arista EOS to Cisco IOS-XE OpenConfig NETCONF — vendor reference index

Curated vendor-doc excerpts grounding the
`tests/fixtures/cross_vendor_expectations/arista_eos__cisco_iosxe.yaml`
per-field expectations.  See sibling
`tests/fixtures/cross_vendor_expectations/README.md` for the canonical
schema definition.

This is the **Arista EOS CLI source -> Cisco IOS-XE OpenConfig NETCONF
target** direction.  Distinct from the sibling pair
`../arista_eos_to_cisco_iosxe_cli/`: the target codec here is the
`cisco_iosxe` codec, NOT `cisco_iosxe_cli`.  Both Cisco codecs target
the same Catalyst 9K / ISR4K / ASR1K device family but emit different
wire formats:

| Target codec | Wire format | Certification |
|---|---|---|
| `cisco_iosxe_cli` | `show running-config` text | `certified` |
| `cisco_iosxe` | OpenConfig NETCONF YANG XML | `best_effort` (Phase-0.5 stub) |

## Direction-specific framing

The dominant fact for this pair is that the `cisco_iosxe` target
codec's `render()` only emits the `openconfig-interfaces` subtree
(name / description / enable / IANA interface-type / IPv4 / IPv6) plus
the `openconfig-if-ip` augment.  Everything else the Arista EOS
source codec parses (hostname / DNS / NTP / VLANs / SNMP / local
users / static routes / VRFs / VXLAN / EVPN MAC-VRF) lands on the
canonical tree but is silently dropped by the cisco_iosxe target
render.

Concretely, the matrix declares paths under `supported` that
`_render_canonical()` never walks — the declarations are aspirational
(cross-codec mesh friendliness), not behavioural.  The disposition
for these fields on this cross-pair is `unsupported` with reason
citing the render-side wire-up gap, NOT `lossy` (the target render
doesn't even attempt — there's no partial emission).

The result: the Arista source typically carries 5-10x more content
than the cisco_iosxe target can re-emit.  Operators wanting full
fidelity Arista -> Cisco IOS-XE should route through `cisco_iosxe_cli`
(certified) instead — that pair emits `show running-config` text
covering hostname, VLANs, SNMP, RADIUS, users, LAGs, static routes,
VRF declarations, VXLAN, and EVPN MAC-VRF.  The NETCONF target is
appropriate ONLY when a downstream OpenConfig orchestrator consumes
just the interfaces subtree.

## Topics

| File | Topic | Direction notes |
|---|---|---|
| `openconfig-yang-scope.md` | Why the cisco_iosxe codec emits a narrow YANG subset | OpenConfig vs Cisco-IOS-XE-native YANG modules |
| `interface-fields.md` | Per-field disposition for the interface canonical core | The only fields with `good` disposition on this direction |
| `ipv6-addresses.md` | IPv6 address forms and link-local handling | Arista explicit `link-local` keyword vs cisco_iosxe global-only |
| `vlan-render-gap.md` | Arista VLAN + switchport state -> render gap | Both VLAN definitions and `switched-vlan` augment dropped |
| `snmp-render-gap.md` | SNMP v1/v2c + v3 USM users -> render gap | Render-side gap; v3 doubly-unsupported (matrix `/snmp/v3-user`) |
| `vxlan-evpn-gap.md` | VXLAN VNIs + EVPN Type-5 + MAC-VRF | Source parses; target matrix declares `/vxlan-vnis/*` `unsupported` |
| `vrf-render-gap.md` | VRFs / routing-instances / per-interface VRF binding | Source parses; target render doesn't walk `<network-instances>` |

## Re-fetch notes

Arista TechHub manuals at `https://www.arista.com/en/um-eos/`
(EOS 4.27.0F / 4.35.2F / 4.36.0F trains).  OpenConfig models cited
here live at `https://openconfig.net/projects/models/`; specific YANG
modules are mirrored on GitHub at
`https://github.com/openconfig/public/tree/master/release/models`.
Cisco IOS-XE programmability guides at
`https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/`.

See also: `../README.md` (citation cache layout),
`../cisco_iosxe_to_arista_eos/_INDEX.md` (reverse direction),
`../arista_eos_to_cisco_iosxe_cli/_INDEX.md` (sibling CLI target).
