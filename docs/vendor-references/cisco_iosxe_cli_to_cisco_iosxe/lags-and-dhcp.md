# LAGs + DHCP server — IOS-XE CLI versus OpenConfig NETCONF

## LAGs (port-channel)

CLI form:

```
interface Port-channel1
 description Spine uplink LAG
 switchport mode trunk
 switchport trunk allowed vlan 100,200
!
interface GigabitEthernet1/0/49
 channel-group 1 mode active
!
interface GigabitEthernet1/0/50
 channel-group 1 mode active
!
```

OpenConfig models LAGs via `openconfig-if-aggregate` augment:

```xml
<interface>
  <name>Port-channel1</name>
  <config>
    <type xmlns:ianaift="urn:ietf:params:xml:ns:yang:iana-if-type">ianaift:ieee8023adLag</type>
  </config>
  <aggregation xmlns="http://openconfig.net/yang/interfaces/aggregate">
    <config>
      <lag-type>LACP</lag-type>
    </config>
  </aggregation>
</interface>
<interface>
  <name>GigabitEthernet1/0/49</name>
  <ethernet xmlns="http://openconfig.net/yang/interfaces/ethernet">
    <config>
      <aggregate-id>Port-channel1</aggregate-id>
    </config>
  </ethernet>
</interface>
```

Source: [openconfig-if-aggregate YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-aggregate.html)
(retrieved 2026-04-30).

The OpenConfig NETCONF codec in this repository does not wire the
aggregate augment — its parse/render only handle bare interfaces and
their IPv4 / IPv6 children.  The CLI codec parses port-channels and
populates `intent.lags`.

| Canonical field | CLI -> NETCONF | NETCONF -> CLI |
|---|---|---|
| `lags[].name` | unsupported (NETCONF render emits no aggregate XML) | not_applicable |
| `lags[].members` | unsupported | not_applicable |
| `lags[].mode` | unsupported | not_applicable |
| `interfaces[].lag_member_of` | unsupported | not_applicable |

Once wired, this is a `good`-disposition surface — same vendor, same
LACP machinery, same `Port-channel<N>` naming, no capitalisation
divergence (the CLI codec emits the IOS-XE convention which is the
same convention the device's NETCONF response uses).

## DHCP server

CLI form:

```
ip dhcp pool LAB
 network 192.168.10.0 /24
 default-router 192.168.10.1
 dns-server 192.168.10.10
 lease 7
!
ip dhcp excluded-address 192.168.10.1 192.168.10.10
```

OpenConfig has no fully-baked DHCP server model in widely-deployed
Cisco IOS-XE versions; the native YANG (`Cisco-IOS-XE-dhcp`) covers
it but bridging into OpenConfig is partial.

The OpenConfig NETCONF codec in this repository does not wire DHCP
at all.  The CLI codec parses pools and populates `intent.dhcp_servers`.

| Canonical field | CLI -> NETCONF | NETCONF -> CLI |
|---|---|---|
| `dhcp_servers` | unsupported (NETCONF render emits no DHCP XML) | not_applicable |

Disposition is `unsupported` rather than `lossy` because there's no
OpenConfig path to render to.  `lossy: deferred` would be the right
classification if we expected a future wire-up via the native model.
For now, the cleaner classification is `unsupported`: the codec's
declared scope is OpenConfig, and OpenConfig doesn't model DHCP
server pools at the cross-vendor canonical level.
