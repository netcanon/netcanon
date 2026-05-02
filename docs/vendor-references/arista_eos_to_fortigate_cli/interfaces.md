# Interfaces (naming / IP / MTU / IPv6 / DHCP-client): Arista EOS versus FortiGate FortiOS

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
interface Management1
   description "Out-of-band management"
   ip address 192.168.100.10/24
!
interface Vlan100
   description "Tenant A data SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
```

Notable Arista specifics:

- **Capitalised, hyphen-free port shapes**: `Ethernet1`,
  `Port-Channel10`, `Loopback0`, `Vlan100`, `Vxlan1`, `Management1`.
  No speed prefix in the name (Arista relies on `show interfaces
  status` for speed/transceiver context).
- **CIDR addressing on interfaces** (`ip address X/N`); dotted-mask
  form (`ip address X 255.255.255.0`) is accepted but `running-config`
  always emits CIDR on modern EOS.
- **IPv6 link-local is explicit** via `ipv6 address fe80::1
  link-local`; global addresses use the same `ipv6 address X/N` form
  without the trailing keyword.
- **MTU per interface** via `mtu N` (e.g. `9214` for jumbo frames).
- **DHCP client** via `ip address dhcp` (uncommon on a leaf switch but
  supported on management interfaces).
- **VRF binding** via `vrf <name>` inside the interface stanza.
- **SVIs** via `interface Vlan<N>`; loopbacks via `interface
  Loopback<N>`.

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
  physical ports; operator-named for aggregates (`agg1`, `LAG_X`);
  `loopback<N>` for software loopbacks; `<parent>.<vlanid>` or
  arbitrary edit-id for VLAN child interfaces.
- **Description is `set alias "..."`** and caps at 25 characters;
  longer Arista descriptions truncate on render.
- **Dotted-mask only** for IPv4 (`set ip 10.0.0.1 255.255.255.0`);
  no CIDR form.  Codec converts at the boundary.
- **IPv6 uses `set ip6-address X/N`** in CIDR form (the IPv4/IPv6
  dotted/CIDR asymmetry is a FortiOS-specific quirk).  No explicit
  link-local keyword — FortiOS auto-assigns link-local from MAC and
  doesn't surface a discriminator.
- **MTU requires `set mtu-override enable`** before `set mtu N` is
  effective; without override the platform default applies.  Arista
  source `mtu 9214` renders as both lines.
- **Enabled state** via `set status up` / `set status down`.
- **VLAN child interfaces** via `set type vlan / set vlanid <N> / set
  interface "<parent>"` — this is the FortiGate VLAN model (no per-
  VLAN port lists).
- **DHCP client** via `set mode dhcp` under the interface stanza
  (parser/render coverage varies by codec version).

## Cross-vendor mapping (Arista -> FortiGate)

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

- **name** — `lossy`.  Arista's CamelCase `Ethernet1` /
  `Port-Channel10` does not match FortiGate's flat `port1` / `agg1`
  naming.  Operators MUST author rename mappings via the per-pane
  port-rename surface; without overrides the source name is preserved
  verbatim and FortiGate's parser will reject names containing
  hyphens or capital letters.
- **description** — `good with truncation`.  FortiOS alias caps at
  25 characters; Arista descriptions of 25 or fewer round-trip.
- **enabled** — `good`.  Arista `no shutdown` (default) / `shutdown`
  -> FortiOS `set status up` / `set status down`.
- **mtu** — `good`.  Both vendors store integer MTU.  Arista jumbo
  9214 -> FortiGate `set mtu 9214` plus `set mtu-override enable`.
- **ipv4_addresses (primary)** — `good`.  Arista `ip address X/N` ->
  FortiOS `set ip X <dotted-mask>` via codec helpers.  FortiGate
  render emits only the first canonical address (no secondaries).
- **ipv4_addresses (secondaries)** — `lossy`.  Arista `ip address X/N
  secondary` lands on canonical but FortiGate render emits only the
  first.
- **ipv6_addresses** — `lossy on link-local scope`.  Arista's
  explicit `link-local` keyword preserves on canonical
  (`scope="link-local"`), but FortiOS has no equivalent keyword
  form — FortiGate auto-assigns link-local internally.  Render emits
  only `scope=global` records.
- **dhcp_client** — `lossy`.  Arista `ip address dhcp` populates the
  canonical bool; FortiGate codec render path does not currently
  emit `set mode dhcp`.  Lands when codec wire-up completes.
- **vrf** — `unsupported`.  See vxlan_evpn_unsupported.md for the
  per-interface VRF binding.  FortiGate's per-interface integer VRF
  (FortiOS 7.x) is not parsed/rendered by the codec in v1.
- **interface_type hint** — `lossy`.  Arista has no native ifType
  enum; FortiGate emits `set type vlan` / `set type loopback` / `set
  type aggregate` from canonical-side hints (loopback name shape,
  LAG membership).

Disposition summary: per-field mix.  **Good** for description
(truncation caveat), enabled, mtu, primary IPv4.  **Lossy** for name
(rename mesh), IPv6 link-local, secondaries, dhcp_client, type-hint.
**Unsupported** for vrf binding.
