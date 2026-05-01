# IP addressing: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/ip_addressing.md`](../cisco_iosxe_cli_to_fortigate_cli/ip_addressing.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / Interfaces / IP](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

```
config system interface
    edit "port1"
        set ip 198.51.100.2 255.255.255.252
        set mode static
        set ip6-address 2001:db8::1/64
        set status up
    next
end
```

FortiOS multi-address support requires `set secondary-IP enable`
plus a nested `config secondaryip` table.

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide.

```
interface GigabitEthernet0/0/0
 ip address 198.51.100.2 255.255.255.252
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
 no shutdown
```

Cisco multi-address: `ip address X Y secondary` (one per address).

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalIPv4Address(BaseModel):
    ip: str
    prefix_length: int

class CanonicalIPv6Address(BaseModel):
    ip: str
    prefix_length: int
    scope: str = "global"
```

- **ipv4_addresses[].ip / prefix_length** — `good`.  FortiOS dotted-
  mask form to Cisco dotted-mask form is identical surface.  Cisco
  also accepts CIDR via `ip address` newer-syntax variants but the
  default render is dotted-mask.
- **ipv4 secondary addresses** — `lossy`.  FortiGate's parser
  collects only the primary IP (see `parse._apply_system_interface`,
  the `secondary-IP` table is parse-and-ignored in v1).  Cross-
  vendor migration of multi-IP FortiGate interfaces drops the
  secondaries on the canonical-model side, before Cisco render
  even runs.
- **ipv6_addresses[].ip / prefix_length** — `good`.  FortiOS
  `set ip6-address X/N` -> Cisco `ipv6 address X/N`.  Single
  per-interface limit (FortiOS schema) means cross-vendor
  migration to Cisco emits at most one v6 address; if the Cisco
  source had multiple v6, the FortiGate-source path never had
  them (this is direction-asymmetric).
- **ipv6_addresses[].scope** — `lossy`.  FortiOS does not surface
  the link-local scope discriminator (the address prefix range
  `fe80::/10` is the only signal); the canonical record always
  carries `scope="global"` after FortiOS parse, so the Cisco
  render never emits the explicit `link-local` keyword.
- **dhcp_client** — `lossy`.  FortiOS `set mode dhcp` is parsed
  by the FortiGate codec into `dhcp_client = True`, but the Cisco
  render path emits `ip address dhcp` correctly — so this is
  actually `good` on the FortiGate -> Cisco direction.  (The
  forward direction was lossy because FortiGate render does not
  yet emit `set mode dhcp`.)

Disposition for primary IPv4 / IPv6 address: **good**.

Disposition for IPv4 secondary addresses: **lossy** (FortiGate
parse drops secondaries before they reach the canonical tree).

Disposition for IPv6 link-local scope: **lossy** (FortiOS source
has no explicit scope keyword; canonical defaults to global).
