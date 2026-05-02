# IPv6 addresses — `fortigate_cli` source to `cisco_iosxe` target

Source: [openconfig-if-ip YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Administration Guide — Interface settings (IPv6 addressing)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

## FortiGate IPv6 source

FortiOS emits IPv6 addresses via `config ipv6 / set ip6-address
<addr>/<prefix>` inside `config system interface / edit "<name>"`.
The FortiGate parser populates `CanonicalIPv6Address` records with
`scope="global"` by default — FortiOS infers link-local from the
prefix internally, but the canonical layer only carries the
explicit configured address, not implicit link-local.

## OpenConfig IPv6 target

The `openconfig-if-ip` model carries `<address>` records keyed by
`<ip>` with `<config><ip>` + `<config><prefix-length>` (range
0-128).  OpenConfig also models a `<config><type>` leaf
distinguishing global / link-local scope, but the cisco_iosxe
renderer does NOT emit this leaf — the render path emits only
`<ip>` + `<prefix-length>`:

```python
if iface.ipv6_addresses:
    ipv6_el = ET.SubElement(si_el, f"{{{_NS_IP}}}ipv6")
    v6_addrs_el = ET.SubElement(ipv6_el, f"{{{_NS_IP}}}addresses")
    for v6 in iface.ipv6_addresses:
        a_el = ET.SubElement(v6_addrs_el, f"{{{_NS_IP}}}address")
        ET.SubElement(a_el, f"{{{_NS_IP}}}ip").text = v6.ip
        ac_el = ET.SubElement(a_el, f"{{{_NS_IP}}}config")
        ET.SubElement(ac_el, f"{{{_NS_IP}}}ip").text = v6.ip
        ET.SubElement(ac_el, f"{{{_NS_IP}}}prefix-length").text = str(v6.prefix_length)
```

No scope leaf.  Even if the FortiGate source had carried a
link-local address (which the codec parses with `scope="global"`
anyway), the cisco_iosxe target render would emit it as a bare
address with the global namespace — a downstream OpenConfig
consumer would treat the inference as authoritative.

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `interfaces[].ipv6_addresses[].ip` | good | FortiOS `set ip6-address` -> OpenConfig `<ip>` |
| `interfaces[].ipv6_addresses[].prefix_length` | good | FortiOS `/prefix` -> OpenConfig `<prefix-length>` |
| `interfaces[].ipv6_addresses[].scope` | lossy | Both codecs default `scope="global"`; no link-local discriminator on either side |

The lossy classification reflects a canonical-model + render-side
gap, not introduced by this specific codec pair.  Promotes when
either codec wires explicit scope handling.
