# Routing protocols (BGP / OSPF / static): Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing Configuration Guide — BGP, OSPF,
EIGRP chapters.

```
router ospf 1
 router-id 10.0.0.1
 network 10.0.0.0 0.0.0.255 area 0
 passive-interface default
 no passive-interface GigabitEthernet0/0/0
!
router bgp 65000
 bgp router-id 10.0.0.1
 neighbor 10.0.0.2 remote-as 65001
 neighbor 10.0.0.2 description "Peer to ISP"
 address-family ipv4
  network 10.1.0.0 mask 255.255.0.0
  neighbor 10.0.0.2 activate
 exit-address-family
!
router eigrp 100
 network 10.0.0.0 0.0.0.255
```

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Networking / Routing](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config router bgp`, `config router ospf`.
Retrieved: 2026-04-30

FortiOS has its own routing engine (FortiOS quagga / FRR-based fork)
with `config router <protocol>` blocks:

```
config router ospf
    set router-id 10.0.0.1
    config area
        edit 0.0.0.0
        next
    end
    config network
        edit 1
            set prefix 10.0.0.0 255.255.255.0
            set area 0.0.0.0
        next
    end
    config interface
        edit "port1"
            set passive disable
        next
    end
end

config router bgp
    set as 65000
    set router-id 10.0.0.1
    config neighbor
        edit "10.0.0.2"
            set remote-as 65001
            set description "Peer to ISP"
        next
    end
    config network
        edit 1
            set prefix 10.1.0.0 255.255.0.0
        next
    end
end
```

FortiOS does not implement EIGRP (Cisco-proprietary).  RIP is
supported but rarely deployed in modern designs.

## Cross-vendor mapping

The canonical schema **does not model** dynamic routing protocols
in v1.  See `CanonicalIntent` — there are no `bgp` / `ospf` /
`eigrp` / `rip` fields, only `static_routes`.

Both codecs handle dynamic-routing intent as `raw_sections` (Tier 3)
parse-and-ignore.  The Cisco IOS-XE codec capability matrix and
the FortiGate codec capability matrix both omit any routing-protocol
xpath under `supported`.

Cross-vendor migration of BGP / OSPF / EIGRP / RIP configurations is
therefore **out of scope**.  Operators migrating between platforms
should manually recreate routing-protocol intent on the target,
treating the source's routing-protocol blocks as documentation
rather than as translatable artefacts.

Disposition: **unsupported** in both directions.
Reason: canonical schema gap; dynamic routing protocols are Tier 3
informational-only on every codec in v1.
