# Routing protocols (BGP / OSPF / EIGRP): Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Cisco supports the full enterprise routing-protocol stack: BGP,
OSPF (v2/v3), IS-IS, EIGRP, RIP.  Configuration lives under
top-level stanzas:

```
router bgp 65000
 neighbor 192.0.2.1 remote-as 65001
 address-family ipv4
  neighbor 192.0.2.1 activate
!
router ospf 1
 router-id 10.255.0.1
 network 10.0.0.0 0.0.0.255 area 0
```

The `cisco_iosxe_cli` codec **parse-and-ignores** these stanzas
entirely; they do not surface in the `CanonicalIntent` tree.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S is a **campus L2/L3 switch with limited dynamic routing**.
The 2930F supports static routing only; 2930M / 3810 / 5400R add
basic OSPFv2, RIP, and PIM.  **No BGP**, **no IS-IS**, **no EIGRP**
on any AOS-S platform.

Where dynamic routing exists, the syntax differs from Cisco:

```
router ospf
 area 0
 enable
 exit
ip routing
```

The `aruba_aoss` codec **parse-and-ignores** dynamic routing
stanzas — only `static_routes` and `ip default-gateway` populate the
canonical tree.

## Cross-vendor mapping

Both codecs parse-and-ignore dynamic routing protocols, so the
canonical tree's `static_routes` field is the only routing data
that survives migration.

For deployments that depend on dynamic routing:

* Cisco -> Aruba: BGP / IS-IS / EIGRP have no Aruba target;
  operator must reconcile manually.
* Cisco OSPF -> Aruba OSPF: syntactically possible on
  2930M/3810/5400R but neither codec parses it; manual
  reconciliation required.

Disposition for dynamic routing: **unsupported** on this cross-
pair; manual reconciliation banner expected.
