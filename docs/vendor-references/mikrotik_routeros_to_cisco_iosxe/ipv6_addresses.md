# IPv6 address handling — RouterOS source to cisco_iosxe NETCONF target

Source: [openconfig-if-ip YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [IPv6 — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328121/IPv6)
Retrieved: 2026-05-01

## RouterOS `/ipv6 address` model

RouterOS exposes IPv6 addresses through a top-level `/ipv6 address`
section that mirrors `/ip address`:

```
/ipv6 address
add address=2001:db8::1/64 interface=ether1
add address=fe80::1/64 interface=ether1 link-local=yes
```

Two relevant flags per address:

* `link-local=yes` — selects the canonical fe80::/10 scope; mutually
  exclusive with global addresses.  Without this flag, RouterOS auto-
  derives a link-local from the EUI-64 of the interface MAC.
* `eui-64=yes` — Cisco-equivalent `ipv6 address X eui-64`; auto-
  derives the host bits from the interface MAC.  RouterOS-side
  parsing of this is a deferred audit pass.

The MikroTik parser populates
`CanonicalIPv6Address.scope = "link-local"` when the source carries
`link-local=yes`, and `"global"` otherwise.

## OpenConfig IPv6 model

OpenConfig models IPv6 addresses under the `openconfig-if-ip`
augment as a subinterface child:

```
<ipv6 xmlns="http://openconfig.net/yang/interfaces/ip">
  <addresses>
    <address>
      <ip>2001:db8::1</ip>
      <config>
        <ip>2001:db8::1</ip>
        <prefix-length>64</prefix-length>
      </config>
    </address>
  </addresses>
</ipv6>
```

Link-local handling lives at a different leaf
(`/interfaces/interface/.../ipv6/config/dup-addr-detect-transmits`
and `enabled` augment) that the cisco_iosxe codec stub does not
emit.  An OpenConfig consumer treats every address in the
`<addresses>` list as global.

## The mismatch

The cisco_iosxe target render's `_render_canonical()` walks
`iface.ipv6_addresses` and emits each as a `<address>` element with
no scope discriminator:

```python
for v6 in iface.ipv6_addresses:
    a_el = ET.SubElement(v6_addrs_el, f"{{{_NS_IP}}}address")
    ET.SubElement(a_el, f"{{{_NS_IP}}}ip").text = v6.ip
    ac_el = ET.SubElement(a_el, f"{{{_NS_IP}}}config")
    ET.SubElement(ac_el, f"{{{_NS_IP}}}ip").text = v6.ip
    ET.SubElement(ac_el, f"{{{_NS_IP}}}prefix-length").text = str(v6.prefix_length)
```

The `scope` field is not consulted.  Link-local addresses on the
canonical tree (with `scope="link-local"`) emit indistinguishably
from global addresses (with `scope="global"`).

In practice this is rarely a fatal issue — most RouterOS source
configurations rely on auto-derived link-local addresses and don't
explicitly declare `fe80::` literals.  Configurations that DO
declare explicit link-local addresses (e.g. for OSPFv3 peer-pinning)
will not survive the round-trip with their scope semantic intact.

## Disposition

`ipv6_addresses`: `lossy` with reason citing the scope discriminator
not being respected on render.  When the cisco_iosxe codec grows
link-local awareness on render, this flips to `good` for the global
subset plus `lossy` only for explicit `fe80::` literals.

This is symmetric with the inverse direction (`cisco_iosxe ->
mikrotik_routeros`), where the parse-side scope hard-coding produces
the equivalent loss going the other way.
