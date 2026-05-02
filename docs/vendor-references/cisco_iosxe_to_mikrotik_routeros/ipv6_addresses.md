# IPv6 address handling — cisco_iosxe NETCONF source to RouterOS target

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: [IPv6 — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328121/IPv6)
Retrieved: 2026-05-01

## OpenConfig IPv6 augment

OpenConfig's `openconfig-if-ip` module augments
`/interfaces/interface/subinterfaces/subinterface` with parallel
`<ipv4>` and `<ipv6>` containers.  Both have the same nested shape:

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

There is no scope or `link-local` discriminator at this level —
OpenConfig handles link-local addresses through a separate
`/interfaces/interface/.../ipv6/config/dup-addr-detect-transmits`
and `enabled` augment that the cisco_iosxe codec stub does not parse.

## RouterOS `/ipv6 address` model

RouterOS exposes IPv6 addresses through a separate top-level
`/ipv6 address` section that mirrors the IPv4 `/ip address` shape:

```
/ipv6 address
add address=2001:db8::1/64 interface=ether1
add address=fe80::1/64 interface=ether1 link-local=yes
```

The `link-local=yes` flag is mutually exclusive with global addresses
and selects the canonical fe80::/10 address for the interface.
RouterOS auto-derives a link-local from the interface MAC
(EUI-64) by default; the explicit form is only used for hand-pinned
link-local identities.

## The mismatch

The cisco_iosxe canonical-bridge helper hard-codes
`scope="global"` on every IPv6 address it constructs:

```python
iface.ipv6_addresses.append(CanonicalIPv6Address(
    ip=ip,
    prefix_length=int(prefix),
    scope="global",
))
```

This means: link-local addresses in the source XML are silently
flagged as global in the canonical record.  When the MikroTik
render sees `scope="global"` for a literal `fe80::1`, it emits
`add address=fe80::1/64 interface=...` with no `link-local=yes`
flag — RouterOS may accept this on /ipv6 address but the address
won't behave as link-local.

In practice this seldom triggers because:

* OpenConfig source configurations usually omit explicit link-local
  addresses (the device's autoconfiguration handles them).
* Operators rarely hand-pin link-local addresses in YANG.

But the lossy classification is correct: any explicit `fe80::`
address in the source XML will not survive the round-trip with its
scope semantic intact.

## Disposition

`ipv6_addresses`: `lossy` with reason citing the scope hard-coding
on the cisco_iosxe parse path.  The same hard-coding applies on
every codec pair where cisco_iosxe is source; this is not a property
of the cross-pair specifically.

When the cisco_iosxe codec grows link-local awareness (deferred to a
subsequent audit pass), this flips to `good` for the global subset
plus `lossy` for the link-local subset (since RouterOS does correctly
support both via the `link-local=yes` flag).
