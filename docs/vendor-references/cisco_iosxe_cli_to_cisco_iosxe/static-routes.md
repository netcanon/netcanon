# Static routes — IOS-XE CLI versus OpenConfig NETCONF

## CLI form

Source: [IP Routing Configuration Guide, Cisco IOS XE 17.x — Recursive
Static Route](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ip-routing/b-ip-routing/m_iri-recursive-static-route-xe.html)
(retrieved 2026-04-30).

```
ip route 0.0.0.0 0.0.0.0 198.51.100.1
ip route 10.1.0.0 255.255.0.0 10.0.0.2 100
ip route vrf TENANT-A 10.20.0.0 255.255.0.0 10.0.0.3
ipv6 route ::/0 2001:db8::1
```

The CLI grammar uses dotted-decimal masks for IPv4; the codec converts
to / from CIDR canonically.  Per-VRF routes prepend `vrf <name>`.

## OpenConfig NETCONF form

Source: [openconfig-network-instance YANG model schema docs](https://openconfig.net/docs/models/network_instance/)
(retrieved 2026-04-30).

Static routes live inside a network-instance under `protocols/static`:

```xml
<network-instances xmlns="http://openconfig.net/yang/network-instance">
  <network-instance>
    <name>default</name>
    <protocols>
      <protocol>
        <identifier>STATIC</identifier>
        <name>STATIC</name>
        <static-routes>
          <static>
            <prefix>0.0.0.0/0</prefix>
            <config>
              <prefix>0.0.0.0/0</prefix>
            </config>
            <next-hops>
              <next-hop>
                <index>0</index>
                <config>
                  <index>0</index>
                  <next-hop>198.51.100.1</next-hop>
                </config>
              </next-hop>
            </next-hops>
          </static>
        </static-routes>
      </protocol>
    </protocols>
  </network-instance>
</network-instances>
```

Per-VRF routes nest under a non-default `<network-instance>` whose
`name` matches the VRF.

## Cross-format mapping in this repository

The OpenConfig NETCONF codec in this repository declares
`/routing/static-route` as `supported` in its capability matrix but
its parse/render paths do not actually emit `<network-instances>`
XML — the codec is a Phase-0.5 stub that only walks `<interfaces>`.
The CLI codec parses static routes from `ip route ...` lines and
populates `intent.static_routes`.

| Direction | Disposition |
|---|---|
| CLI -> NETCONF | unsupported — `intent.static_routes` is silently dropped on render. |
| NETCONF -> CLI | not_applicable — NETCONF parser never populates static_routes. |

When the NETCONF codec is extended to emit
`openconfig-network-instance` XML, the disposition flips to `good`
for default-VRF static routes (`destination`, `gateway`, `metric`).
Per-VRF static routes remain `lossy` until `CanonicalStaticRoute`
gains a `vrf` field — same gap that the `cisco_iosxe_cli` codec lists
under its `/routing-instances/instance` `unsupported` declaration.
The CLI codec parses `ip route vrf X ...` lines today but
parse-and-ignores them (drops the VRF prefix).
