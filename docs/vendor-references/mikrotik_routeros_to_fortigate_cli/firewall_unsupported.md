# Firewall / NAT / queues / wireless / scripts (unsupported on this direction)

## MikroTik RouterOS

Sources:
- [Firewall — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/130220/Firewall) — `/ip firewall filter / nat / mangle`.
- [Queues — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24871047/Queues) — `/queue`.
- [Wireless — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805388/Wireless) — `/interface wireless`.
- [Scripting — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Scripting) — `/system script`.

Retrieved: 2026-04-30

RouterOS carries Tier-3 surfaces that are out of canonical scope:

```
/ip firewall filter
add chain=input action=accept connection-state=established,related
add chain=input action=drop in-interface=ether1
add chain=forward action=accept connection-state=established,related

/ip firewall nat
add chain=srcnat action=masquerade out-interface=ether1
add chain=dstnat action=dst-nat to-addresses=10.0.0.10 to-ports=80 \
    protocol=tcp dst-port=8080 in-interface=ether1

/queue simple
add name=user-shaper target=10.0.0.0/24 max-limit=100M/100M

/interface wireless
set [ find default-name=wlan1 ] ssid=lab-ssid mode=ap-bridge \
    band=2ghz-b/g/n disabled=no

/system script
add name=daily-cleanup source=":log info \"daily cleanup\"; ..."
```

These surfaces are **not modelled in CanonicalIntent** in v1:

- **Firewall filter / NAT / mangle** — classical iptables-derived chain/match/action grammar.  Tier 3 by design; remains in `raw_sections` for review.
- **Queues** — RouterOS bandwidth shaping (`/queue simple`, `/queue tree`).  No canonical model.
- **Wireless** — RouterOS access-point and CAPsMAN configuration.  Specific to RouterOS deployments; out of scope.
- **Scripts** — RouterOS shell scripts and scheduler entries.  Out of scope.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Cookbook — Firewall policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) — `config firewall policy`.
- [FortiGate / FortiOS 7.4 Administration Guide — Traffic shaping](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
- [FortiGate / FortiOS 7.4 Administration Guide — Wireless controller](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).

Retrieved: 2026-04-30

FortiGate has its own firewall / NAT / VPN / wireless primitives:

```
config firewall policy
    edit 1
        set srcintf "port4"
        set dstintf "port1"
        set srcaddr "all"
        set dstaddr "all"
        set action accept
        set service "ALL"
        set nat enable
    next
end

config firewall vip
    edit "web-vip"
        set extip 198.51.100.10
        set mappedip "10.10.0.10"
        set extintf "port1"
    next
end
```

These surfaces are **not modelled in CanonicalIntent** in v1.  FortiGate's session-based zone-aware policy model is structurally distinct from RouterOS's iptables-derived chains.

## Cross-vendor mapping (RouterOS → FortiGate)

The fields below are **all `unsupported` on this direction** because the canonical model does not represent the source RouterOS concept (or the FortiGate target concept):

- **Firewall filter / NAT / mangle** — `unsupported`.  RouterOS `/ip firewall filter / nat / mangle` is parse-and-ignore in v1 (Tier 3).  Even if both codecs lifted the rules to a canonical filter table, the iptables-style chain semantic does not survive translation to FortiGate's session-based zone-aware policy model.
- **Queues / traffic shaping** — `unsupported`.  RouterOS `/queue` and FortiGate `config firewall shaper` have no canonical representation.
- **Wireless** — `unsupported`.  RouterOS `/interface wireless` and FortiGate `config wireless-controller` are independent product surfaces.
- **VPN / IPsec** — `unsupported`.  RouterOS `/ip ipsec` and FortiGate `config vpn ipsec` are independent product surfaces; cross-vendor migration is operator-curated.
- **Scripts** — `unsupported`.  RouterOS `/system script` has no FortiGate counterpart.

The corresponding canonical fields (where they exist — only `raw_sections` covers them) carry the source bytes for review but never auto-render.

Operators should treat the RouterOS firewall / queue / wireless / scripting config as **documentation rather than a translatable artefact** and reconstruct equivalent policy on FortiGate manually using FortiGate's product surfaces (firewall policy, traffic shaper, wireless controller).
