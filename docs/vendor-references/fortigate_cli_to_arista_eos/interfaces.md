# Interfaces (naming / IP / MTU / IPv6 / DHCP-client): FortiGate FortiOS versus Arista EOS

## FortiGate FortiOS CLI

Source: [Fortinet Document Library — Interface Settings (FortiOS 7.4 Admin Guide)](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Retrieved: 2026-05-01

```
config system interface
    edit "port1"
        set alias "WAN-uplink"
        set ip 198.51.100.2 255.255.255.252
        set ip6-address 2001:db8:cafe::2/64
        set allowaccess ping https ssh
        set mtu-override enable
        set mtu 1500
        set status up
    next
    edit "loopback0"
        set alias "router-id"
        set type loopback
        set ip 10.255.255.1 255.255.255.255
        set ip6-address 2001:db8:0:ffff::1/128
        set status up
    next
    edit "agg1.100"
        set alias "data-vlan-100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
        set status up
    next
end
```

Notable FortiOS specifics:

- **Flat namespace**: `port1` / `port24` / `wan1` / `internal` for
  physical; `agg<N>` / operator-named for aggregates;
  `loopback<N>` for software loopbacks; `<parent>.<vlanid>` or
  arbitrary edit-id for VLAN child interfaces.
- **Description is `set alias "..."`** with a 25-character cap.
- **Dotted-mask IPv4** (`set ip X <mask>`); CIDR IPv6 (`set
  ip6-address X/N`).  No explicit link-local form.
- **MTU requires `set mtu-override enable`** before `set mtu N`.
- **Type discriminator** via `set type {loopback|aggregate|vlan|...}`;
  default (no type) is a physical port.
- **DHCP client** via `set mode dhcp` (codec parse coverage varies).

## Arista EOS

Source: [Arista EOS User Manual — Ethernet Ports (4.36.0F)](https://www.arista.com/en/um-eos/eos-ethernet-ports)
Source: [Arista EOS User Manual — Interface Configuration (4.35.2F)](https://www.arista.com/en/um-eos/eos-interface-configuration)
Retrieved: 2026-05-01

```
interface Ethernet1
   description "Spine uplink (L3 routed)"
   no switchport
   mtu 9214
   ip address 10.0.0.1/31
   ipv6 address 2001:db8:0:1::1/64
   ipv6 address fe80::1 link-local
!
interface Loopback0
   description "VTEP / router-id"
   ip address 10.255.0.1/32
!
interface Vlan100
   description "Tenant A data SVI"
   ip address 10.100.0.1/24
```

Notable Arista specifics:

- **CamelCase port shapes** without speed prefix: `Ethernet1`,
  `Port-Channel10`, `Loopback0`, `Vlan100`, `Vxlan1`, `Management1`.
- **CIDR addressing on interfaces** (`ip address X/N`); legacy
  dotted-mask form accepted but `running-config` always emits CIDR
  on modern EOS.
- **IPv6 link-local explicit** via `ipv6 address fe80::1 link-local`;
  global addresses via `ipv6 address X/N`.
- **MTU per interface** via `mtu N`.
- **DHCP client** via `ip address dhcp`.
- **Description is unquoted-or-quoted** (free-form, no length cap).
- **SVIs** via `interface Vlan<N>`; loopbacks via `interface
  Loopback<N>` (no `set type` discriminator needed — the name shape
  defines it).

## Cross-vendor mapping (FortiGate -> Arista)

Canonical surface:

```
interfaces[].name: str
interfaces[].description: str
interfaces[].enabled: bool
interfaces[].mtu: int | None
interfaces[].ipv4_addresses: list[CanonicalIPv4Address]
interfaces[].ipv6_addresses: list[CanonicalIPv6Address]   # with scope
interfaces[].dhcp_client: bool
interfaces[].vrf: str
```

- **name** — `lossy`.  FortiGate's flat `port1` does not match
  Arista's CamelCase `Ethernet1` — operators MUST author rename
  mappings via the per-pane port-rename surface.  Without
  overrides the source name is preserved verbatim and Arista's
  parser will reject `port1` (Arista expects `Ethernet<N>` /
  `Management<N>` / `Loopback<N>` / `Port-Channel<N>` / etc.).
- **description (alias)** — `good`.  FortiGate's 25-character
  alias fits comfortably in Arista's free-form description; no
  truncation in this direction.
- **enabled** — `good`.  FortiOS `set status up` / `set status
  down` -> Arista `no shutdown` / `shutdown`.
- **mtu** — `good`.  Both vendors store integer MTU.  FortiGate
  source's `set mtu-override enable` is consumed by parse; Arista
  render emits the bare `mtu N`.
- **ipv4_addresses (primary)** — `good`.  FortiOS `set ip X
  <dotted-mask>` -> Arista `ip address X/N` via codec helpers.
- **ipv4_addresses (secondaries)** — `not_applicable`.  FortiGate
  parse populates only the primary; secondaries don't exist on
  the source.
- **ipv6_addresses (global)** — `good`.  FortiOS `set ip6-address
  X/N` (already CIDR) -> Arista `ipv6 address X/N`.  Both vendors
  use CIDR for IPv6.
- **ipv6_addresses (link-local)** — `not_applicable`.  FortiOS
  source has no explicit link-local keyword form (auto-assigned
  internally); the canonical `scope="link-local"` field is never
  populated on FortiGate parse, so Arista render emits no
  `ipv6 address fe80::X link-local` line.
- **dhcp_client** — `lossy`.  FortiGate parse coverage of `set
  mode dhcp` may be inconsistent in v1; even when populated,
  Arista codec render of `ip address dhcp` is reliable.  Lands
  cleanly when the FortiGate parse path completes.
- **vrf** — `unsupported`.  See firewall_unsupported.md — FortiGate
  codec does not parse `set vrf <id>` (FortiOS 7.x per-interface
  integer VRF) into `CanonicalInterface.vrf` in v1.  Arista has a
  rich VRF model (`vrf <name>` inside the interface stanza) but
  the canonical field is empty on this direction so nothing
  renders.
- **interface_type hint** — `lossy`.  FortiGate's `set type
  loopback` / `set type aggregate` / `set type vlan` is consumed
  on parse; Arista has no `type` keyword (the name shape carries
  the type).  The canonical `interface_type` carries the FortiGate
  hint but Arista render uses name-shape inference instead.

Disposition summary: **good** for description, enabled, mtu, IPv4
primary, IPv6 global.  **Lossy** for name (rename mesh required),
dhcp_client (codec parse gap), interface_type hint.
**Not_applicable** for IPv4 secondaries, IPv6 link-local (FortiGate
source structurally absent).  **Unsupported** for vrf binding.
