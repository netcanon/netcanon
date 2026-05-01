# Routing protocols (BGP / OSPF / EIGRP / IS-IS): Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S is a **campus L2/L3 switch with limited dynamic routing**:

* 2930F: static routes only — no dynamic protocols.
* 2930M / 3810 / 5400R: OSPFv2, RIP, PIM (multicast).  **No BGP**,
  **no IS-IS**, **no EIGRP** on any AOS-S platform.

Where dynamic routing exists, the syntax differs from Cisco:

```
ip routing
router ospf
 area 0
 enable
 exit
```

The `aruba_aoss` codec **parse-and-ignores** dynamic routing
stanzas — only `static_routes` and `ip default-gateway` populate
the canonical tree.

## Cisco IOS-XE

Cisco supports the full enterprise routing-protocol stack: BGP,
OSPF (v2/v3), IS-IS, EIGRP, RIP.

The `cisco_iosxe_cli` codec **parse-and-ignores** these stanzas —
they do not surface in the `CanonicalIntent` tree.

## Cross-vendor mapping

Aruba -> Cisco direction:

* No BGP on Aruba source -> no BGP to lose.
* No IS-IS on Aruba source -> no IS-IS to lose.
* No EIGRP on Aruba source -> no EIGRP to lose.
* OSPF on Aruba source -> Cisco target syntactically possible
  but the Aruba codec parse-and-ignores it, so the canonical tree
  carries no OSPF data.

Disposition for dynamic routing: **unsupported** on this cross-
pair.  Operator-driven manual reconciliation required where the
Aruba source had OSPF or RIP configured.
