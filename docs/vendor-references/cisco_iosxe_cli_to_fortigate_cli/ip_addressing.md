# IP addressing: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE Interface and Hardware Component Configuration
Guide — IP Addressing chapter.

```
interface GigabitEthernet0/0/0
 ip address 198.51.100.2 255.255.255.252
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
 no shutdown
```

Cisco uses **dotted-decimal subnet masks** for IPv4 (`255.255.255.252`)
and CIDR for IPv6 (`/64`).  Link-local addresses use an explicit
`link-local` keyword.

Multiple IPv4 addresses on a single interface use the `secondary`
keyword:

```
 ip address 10.1.1.1 255.255.255.0
 ip address 10.1.1.2 255.255.255.0 secondary
```

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / IP](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings)
Source: FortiOS CLI Reference — `config system interface / set ip` /
`set ip6-address` / `set secondaryip`.
Retrieved: 2026-04-30

FortiOS uses **dotted-decimal masks** for IPv4 and CIDR for IPv6:

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

Multiple IPv4 addresses per interface require enabling
`set secondary-IP enable` and a nested `config secondaryip` table:

```
config system interface
    edit "port1"
        set ip 10.1.1.1 255.255.255.0
        set mode static
        set secondary-IP enable
        config secondaryip
            edit 1
                set ip 10.1.1.2 255.255.255.0
            next
        end
    next
end
```

FortiOS link-local addresses live under
`config system interface / config ipv6 / set ip6-address` (with
`fe80::/10` prefix), with no separate `link-local` keyword — the
prefix range itself signals link-local scope.  The current FortiGate
codec simplifies this to a single `set ip6-address <addr>/<prefix>`
form on render and treats `::/0` as "no IPv6 address" placeholder
(see `parse._apply_system_interface`).

## Cross-vendor mapping

Canonical surface:

```
class CanonicalIPv4Address(BaseModel):
    ip: str
    prefix_length: int          # canonical CIDR form

class CanonicalIPv6Address(BaseModel):
    ip: str
    prefix_length: int
    scope: str = "global"       # 'global' | 'link-local'

class CanonicalInterface(BaseModel):
    ipv4_addresses: list[CanonicalIPv4Address]
    ipv6_addresses: list[CanonicalIPv6Address]
    dhcp_client: bool
    ...
```

- **ipv4_addresses[].ip / prefix_length** — `good`.  Both vendors emit
  the same `<dotted>+<mask>` shape and `_mask_to_prefix`
  / `_prefix_to_mask` round-trips it cleanly.  Multi-address support
  is partial: the FortiGate render path emits only the first
  CanonicalIPv4Address per interface (see render.py:148-152), so
  Cisco secondaries drop on Cisco -> FortiGate.  Marked lossy below
  for the secondary-address case.
- **ipv6_addresses[].ip / prefix_length** — `good` for the primary
  address.  Same single-record render limitation — additional v6
  addresses drop.
- **ipv6_addresses[].scope (link-local)** — `lossy`.  The FortiOS
  codec writes a single `set ip6-address` line and the currently-
  shipped renderer does not branch on scope; cross-vendor migration
  loses the explicit Cisco `link-local` keyword.  The address is
  preserved but the scope discriminator drops.
- **dhcp_client** — `lossy`.  Cisco `ip address dhcp` -> FortiOS
  `set mode dhcp`.  Both vendors model this; the FortiGate render
  path currently always emits `set mode static`, so cross-vendor
  migration of DHCP-client interfaces drops the dynamic-addressing
  intent.  Documented but not yet wired in render.

Disposition for primary IPv4 / IPv6 address: **good**.

Disposition for IPv4 secondary addresses: **lossy** (truncated to
first record on FortiGate render).

Disposition for IPv6 link-local scope: **lossy** (explicit scope
keyword dropped).

Disposition for DHCP-client interfaces: **lossy** (dhcp_client field
not yet wired in FortiGate render).
