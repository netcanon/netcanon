# IP addressing: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/ip_addressing.md`](../aruba_aoss_to_fortigate_cli/ip_addressing.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

```
config system interface
    edit "port1"
        set ip 198.51.100.2 255.255.255.252
        set ip6-address 2001:db8:cafe::2/64
        set status up
    next
end
```

- **IPv4 mask is dotted-decimal** in `set ip`.
- **Single IPv4 primary per interface.**  FortiGate parse drops
  any source-side secondaries before they reach canonical.
- **IPv6 is `set ip6-address` with CIDR.**  No explicit `link-local`
  keyword — FortiOS auto-detects from the `fe80::/10` prefix.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
interface 1
   routing
   ip address 198.51.100.2/30
   ipv6 address 2001:db8:cafe::2/64
   ipv6 address fe80::1/64 link-local
   enable
   exit
```

- **Mixed mask form.**  Aruba accepts both CIDR and dotted-decimal
  for `ip address`.  The codec normalises to canonical prefix-length
  on parse and renders CIDR by default.
- **IPv6 link-local discriminator.**  Explicit `link-local` suffix
  tags the address; canonical `scope = "link-local"`.

## Cross-vendor mapping (FortiGate -> Aruba)

- **ipv4_addresses[].ip / prefix_length** — `good`.  FortiOS
  dotted-mask -> canonical -> Aruba CIDR via the codec helpers.
- **ipv4_addresses (multiple per interface)** — `not_applicable`.
  FortiGate parse drops secondaries before canonical, so Aruba
  render only sees the primary (which it would render anyway).
- **ipv6_addresses[].ip / prefix_length** — `good`.  Direct
  preservation.
- **ipv6_addresses[].scope** — `lossy` on link-local.  FortiOS
  source carries no explicit scope keyword; the FortiGate codec
  populates `scope = "global"` by default on parse.  Even if the
  source had a `fe80::/10` address, the canonical scope tag is
  not preserved through FortiGate parse.  Aruba render therefore
  emits link-local addresses without the `link-local` suffix
  (Aruba accepts the address but loses the scope hint).

Disposition: **good** for primary IPv4 + IPv6 global; **lossy** for
IPv6 link-local scope (FortiGate-source codec gap).
