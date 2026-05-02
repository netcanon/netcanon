# Interfaces (naming / IP addressing / MTU / status): FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings) — `config system interface / edit "<name>" / set ip <addr> <mask> / set mtu / set status`.
- [FortiGate / FortiOS 7.4 CLI Reference — `config system interface`](https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/) — full attribute list.

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

Notable FortiOS specifics:

- Interface names are **opaque labels** (`port1` / `wan1` / `internal` / `dmz`); they encode neither speed nor slot/port path.  Aliases (`set alias`) provide a human description capped at 25 characters.
- IPv4 uses dotted-decimal mask form (`set ip ADDR MASK`).  IPv6 uses CIDR (`set ip6-address ADDR/N`).
- `set mtu` only takes effect when `set mtu-override enable` is also set; otherwise FortiOS uses the platform default (1500 for ethernet).
- `set status up | down` is the admin-up flag.
- Loopback interfaces require an explicit `set type loopback`.  VLAN child interfaces require `set type vlan`, `set vlanid`, and `set interface "<parent>"`.

## MikroTik RouterOS

Sources:
- [Ethernet — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/41746442/Ethernet) — `/interface ethernet set [find default-name=...] mtu=<N> disabled=yes/no comment="..."`.
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing) — `/ip address add address=<CIDR> interface=<NAME>`.
- [IPv6 Address — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/40992803/IPv6+Address) — `/ipv6 address add address=<CIDR> interface=<NAME>`.

Retrieved: 2026-04-30

```
/interface ethernet
set [ find default-name=ether1 ] comment="WAN uplink to ISP" disabled=no mtu=1500

/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.255.0.1/32 interface=lo0

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
```

RouterOS uses **flat per-product naming**: `etherN` for ethernet, `wlanN` for wireless, `bondN` for LAGs, `vlanN` (operator-named) for VLAN sub-interfaces.  Speed is not in the name — every port is `etherN` regardless of physical link rate.

Each port has a `default-name=etherN` factory token that operators commonly reference via `[find default-name=etherN]` indirection so the rename of the port does not break references later.  RouterOS does not have a first-class loopback interface family — operators emulate via empty bridges or `/interface bridge add name=lo0`.

IPv4 / IPv6 addresses live under separate `/ip address` and `/ipv6 address` tables and reference the interface by name; CIDR is the wire format on both.

`mtu` is a per-port attribute on `/interface ethernet`.  `disabled=yes/no` is the admin flag (inverse of FortiOS `status up/down`).

## Cross-vendor mapping (FortiGate → RouterOS)

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

- **name** — `lossy`.  FortiGate `port1` / `wan1` / `internal` are opaque labels with no analogue in RouterOS's `etherN` flat namespace; the port-rename mesh applies operator-curated mappings on cross-vendor render.  Loopback interface names also differ structurally (FortiOS `loopback0` with `set type loopback` versus RouterOS bridge emulation).
- **description** — `lossy`.  FortiOS `set alias "..."` (25-char cap) parses into the canonical `description`; RouterOS renders as `comment="..."` on the relevant `/interface ethernet` line.  RouterOS `comment` is unbounded so no truncation in this direction.
- **enabled** — `good`.  FortiOS `set status up/down` inverts cleanly to RouterOS `disabled=no/yes`.
- **interface_type** — `lossy`.  FortiOS `set type loopback` / `set type vlan` / `set type aggregate` parse into canonical interface_type but RouterOS has no IANA ifType field; the MikroTik codec infers it from the interface-name prefix on render.  Loopback in particular has no first-class RouterOS analogue.
- **ipv4_addresses** — `good`.  FortiOS dotted-mask `set ip ADDR MASK` converts cleanly to RouterOS CIDR `/ip address add address=ADDR/N` via the codec helpers.  FortiOS allows only one primary `set ip` per interface, so secondary-address concerns do not arise on this direction.
- **ipv6_addresses** — `lossy`.  Global addresses round-trip cleanly via `set ip6-address ADDR/N` -> `/ipv6 address add address=ADDR/N`.  Link-local scope is preserved in canonical but the FortiGate source rarely populates an explicit `set ip6-address fe80::/64` (FortiOS auto-derives link-local from MAC); RouterOS source carries explicit `fe80::/64` lines that drop on round-trip back to FortiGate.
- **mtu** — `lossy`.  FortiOS `set mtu N` only takes effect when `set mtu-override enable` is also set.  The FortiGate codec parses MTU when `mtu-override` is present, populating the canonical field; RouterOS render emits `/interface ethernet set [find default-name=etherX] mtu=<N>` cleanly.  For interface families that RouterOS does not parse MTU on (bonding parent, vlan child) the value drops.
- **lag_member_of** — see [`lags.md`](lags.md).
- **dhcp_client** — `lossy`.  FortiOS `set mode dhcp` parses to canonical `dhcp_client=True`; RouterOS render would emit `/ip dhcp-client add interface=etherX disabled=no` which the MikroTik codec does not yet emit on render.  Drops on this direction.
- **switchport_mode / access_vlan / trunk_allowed_vlans / trunk_native_vlan / voice_vlan** — `unsupported` on this direction.  FortiGate is L3-only beyond the hardware-switch sub-feature on a few low-end models; the source interfaces never populate these canonical fields.  RouterOS's bridge VLAN filtering (Plane-2) would be the analogue but the field is structurally empty on the FortiGate-source side.
- **vrf** — `unsupported`.  FortiGate's per-interface integer VRF (FortiOS 7.x) is not yet parsed by the FortiGate codec; even if it were, RouterOS 7+ `/ip vrf` is not yet wired in the MikroTik codec.  See [`routing_instances_vrf.md`](routing_instances_vrf.md).
