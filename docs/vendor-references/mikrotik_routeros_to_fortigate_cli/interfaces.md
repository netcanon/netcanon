# Interfaces (naming / IP addressing / MTU / status): MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet) — `/interface ethernet`.
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing) — `/ip address`.
- [IPv6 Address — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992803/IPv6+Address) — `/ipv6 address`.

Retrieved: 2026-04-30

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500
set [ find default-name=ether2 ] comment="LAN trunk - bridge member" disabled=no

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.0.0.1/24 interface=bridge1

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
```

RouterOS uses **flat per-product naming**: `etherN` for ethernet, `wlanN` for wireless, `bondN` for bonds, `vlanN` (operator-named) for VLAN sub-interfaces, `bridgeN` for bridges.  Ports have a `default-name=etherN` factory token referenced via `[find default-name=etherN]` indirection.

`mtu=` is a per-port attribute on `/interface ethernet`.  `disabled=yes/no` is the admin flag (inverse of FortiOS `status up/down`).  `comment=` is the human description.

There is no first-class loopback interface family — operators emulate via empty bridges.

IPv4 / IPv6 addresses live under separate `/ip address` and `/ipv6 address` tables; CIDR is the wire format on both.  Link-local addresses (`fe80::/64`) appear explicitly in RouterOS source (FortiOS auto-derives them and does not include them in the parsed config).

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).

Retrieved: 2026-04-30

```
config system interface
    edit "port1"
        set alias "WAN-uplink"
        set ip 198.51.100.2 255.255.255.252
        set ip6-address 2001:db8:cafe::2/64
        set mtu-override enable
        set mtu 1500
        set status up
    next
    edit "loopback0"
        set type loopback
        set ip 10.255.255.1 255.255.255.255
        set status up
    next
end
```

Interface names are opaque labels with no slot/port encoding; aliases (capped at 25 characters) provide a description.  IPv4 uses dotted-decimal mask form; IPv6 uses CIDR.  `set mtu N` only takes effect when `set mtu-override enable` is also set.  Loopback interfaces require `set type loopback`; VLAN child interfaces require `set type vlan` + `set vlanid` + `set interface "<parent>"`.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface (per-interface):

```
CanonicalInterface.name: str
CanonicalInterface.description: str
CanonicalInterface.enabled: bool
CanonicalInterface.interface_type: str
CanonicalInterface.mtu: int | None
CanonicalInterface.ipv4_addresses: list[CanonicalIPv4Address]
CanonicalInterface.ipv6_addresses: list[CanonicalIPv6Address]
CanonicalInterface.lag_member_of: str | None
CanonicalInterface.dhcp_client: bool
```

- **name** — `lossy`.  RouterOS `etherN` flat namespace versus FortiGate operator-driven labels (`port1` / `wan1` / `internal`).  The port-rename mesh applies operator-curated mappings on cross-vendor render.  RouterOS bridge interfaces (used for loopback emulation) have no clean FortiGate analogue without `set type loopback`.
- **description** — `lossy`.  RouterOS `comment="..."` (unbounded) parses to canonical `description`; FortiOS `set alias "..."` caps at 25 characters — RouterOS-source comments longer than 25 chars truncate on FortiGate render.
- **enabled** — `good`.  RouterOS `disabled=yes/no` inverts cleanly to FortiOS `set status down/up`.
- **interface_type** — `lossy`.  The MikroTik codec infers interface_type from the name prefix (etherN → ethernetCsmacd, vlanN → l3ipvlan, bondN → ieee8023adLag).  FortiOS does not have an IANA ifType field; the FortiGate codec emits `set type loopback` / `set type vlan` / `set type aggregate` based on the inferred type.  Mapping is best-effort: a RouterOS bridge used as a loopback does not auto-render as FortiOS `set type loopback` without operator intervention.
- **ipv4_addresses** — `good`.  RouterOS `/ip address add address=ADDR/N interface=...` parses cleanly; FortiOS render emits `set ip ADDR DOTTED-MASK` via the codec helper.  Multiple `/ip address` lines per interface lose the tail because FortiOS allows only one primary `set ip` (FortiOS-side surface is single-primary).  This is a real RouterOS-source-rich-loss case: WISP deployments routinely carry multiple per-interface addresses.
- **ipv6_addresses** — `lossy`.  Global addresses round-trip cleanly via `/ipv6 address add address=ADDR/N` -> `set ip6-address ADDR/N`.  Link-local `fe80::/N` lines that appear explicitly in RouterOS source have no FortiGate counterpart (FortiOS auto-derives link-local from MAC and does not allow operator-set fe80::); the FortiGate render drops them with a banner.  Per-address `advertise=no` / `eui-64=yes` flags are not modelled canonically.
- **mtu** — `lossy`.  RouterOS `mtu=N` on `/interface ethernet` parses cleanly when present.  FortiOS render emits `set mtu N` plus the required `set mtu-override enable`.  RouterOS bonding parents and VLAN children where mtu is implicit do not surface to canonical, so those carry over as defaults.
- **lag_member_of** — see [`lags.md`](lags.md).
- **dhcp_client** — `lossy`.  RouterOS `/ip dhcp-client add interface=etherX` is not yet parsed by the MikroTik codec; even if it were, FortiOS render `set mode dhcp` is not yet emitted by the FortiGate codec.  Drops on this direction.
- **switchport_mode / access_vlan / trunk_allowed_vlans / trunk_native_vlan / voice_vlan** — `unsupported`.  RouterOS L2 switching is via bridge VLAN filtering (Plane 2) which the MikroTik codec parses partially in v1; the canonical switchport fields are populated only for bridge ports with explicit pvid / tagged / untagged config.  FortiGate is L3-only beyond the hardware-switch sub-feature on a few low-end models — the rendered FortiOS would not express the L2 surface even if canonical carried it.
- **vrf** — `unsupported`.  Neither codec parses VRF in v1.  See [`routing_instances_vrf.md`](routing_instances_vrf.md).
