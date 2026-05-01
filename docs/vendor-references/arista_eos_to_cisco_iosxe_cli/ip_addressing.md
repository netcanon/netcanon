# IPv4 / IPv6 addressing: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — IPv4](https://www.arista.com/en/um-eos/eos-ipv4)
Retrieved: 2026-04-30

Arista uses CIDR notation natively for both v4 and v6:

```
interface Ethernet1
 no switchport
 ip address 192.0.2.1/24
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
```

Quoting the EOS manual: "An IP address can be assigned to a routed
port for the direct routing of packets to and from the interface....
The no switchport command places the configuration mode interface in
routed port mode."

Both dotted-quad-mask and CIDR forms are accepted on input; running-
config emits CIDR.

## Cisco IOS-XE

Source: [Cisco IOS XE Routing Configuration Guide — `ip address` command reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/interface/command/ir-cr-book/ir-s7.html)
Retrieved: 2026-04-30

Interface IPv4 syntax uses a separate dotted-quad subnet mask:

```
interface GigabitEthernet1/0/1
 no switchport
 ip address 192.0.2.1 255.255.255.0
```

IPv6 form uses CIDR (matches Arista):

```
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
```

Secondary addresses use the explicit `secondary` keyword:

```
 ip address 192.0.2.2 255.255.255.0 secondary
```

`no switchport` flips a Layer-2 port to a routed port — same as
Arista.

## Cross-vendor mapping

The canonical schema stores prefix-length as an integer
(`CanonicalIPv4Address.prefix_length: int = Field(ge=0, le=32)`) and
the address as a string.  Both codecs convert at the parse / render
boundary:

- Arista EOS parse: `192.0.2.1/24` -> (`"192.0.2.1"`, `24`) directly.
- Cisco IOS-XE render: `24` -> `255.255.255.0` via the `_prefix_to_mask`
  helper.  Arista source on the input side; Cisco target on the output
  side.

Round-trip is lossless for any contiguous mask.  IPv6 link-local scope
is preserved via `CanonicalIPv6Address.scope` ("global" /
"link-local"); both codecs emit the explicit `link-local` keyword.

Disposition: **good**.
