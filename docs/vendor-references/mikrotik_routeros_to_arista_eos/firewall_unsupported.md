# Firewall / NAT / queues / wireless / scripts: RouterOS Tier-3 plumbing has no Arista home

## MikroTik RouterOS

Sources:
- [Firewall — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/250708066/Firewall)
- [NAT — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/3211299/Network+Address+Translation+-+NAT)
- [Queues — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/120324146/Queues)
- [Wireless Interface — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805485/Wireless+Interface)
- [Scripting — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579215/Scripting)
- [Hotspot — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/HotSpot)

Retrieved: 2026-05-01

RouterOS carries a substantial body of configuration that lives
**outside** the canonical-portable surface.  These surfaces
typify the platform's router-first ethos: RouterOS expects to
own packet-by-packet handling on the data plane, scheduled
maintenance on the control plane, and end-user services on the
edge.

Surfaces that lift to `CanonicalIntent.raw_sections` on parse
and have no canonical-stable cross-vendor field:

```
/ip firewall filter
add chain=input action=accept connection-state=established,related
add chain=input action=drop in-interface=ether1
add chain=forward action=accept connection-state=established,related
add chain=forward action=accept src-address=10.0.0.0/24 out-interface=ether1
add chain=forward action=drop

/ip firewall nat
add chain=srcnat action=masquerade out-interface=ether1
add chain=dstnat action=dst-nat to-addresses=10.0.0.50 to-ports=80 \
    protocol=tcp dst-address=198.51.100.2 dst-port=80

/ip firewall mangle
add chain=prerouting action=mark-connection new-connection-mark=conn-WAN \
    in-interface=ether1

/queue tree
add name=upload parent=ether1 max-limit=100M

/queue simple
add name=qos-VoIP target=10.0.0.0/24 max-limit=10M/10M priority=1

/interface wireless
add name=wlan1 ssid=GuestWiFi mode=ap-bridge band=2ghz-b/g/n disabled=no

/ip hotspot
add name=hs-public interface=bridge1 address-pool=hotspot-pool \
    profile=hs-default

/ip ipsec peer
add address=198.51.100.10/32 secret="fake-ipsec-psk" exchange-mode=ike2

/interface wireguard
add name=wg-tunnel listen-port=51820 private-key="fake-wg-private"

/interface ovpn-server server
set enabled=yes auth=sha1 cipher=aes256 default-profile=ovpn-default

/interface l2tp-server server
set authentication=mschap2 default-profile=default-encryption \
    enabled=yes use-ipsec=yes ipsec-secret="fake-l2tp-psk"

/interface pppoe-client
add name=pppoe-out1 interface=ether1 user=isp-user password="fake-isp-pw" \
    add-default-route=yes disabled=no

/system script
add name=daily-backup source=":log info \"Backing up\"; /export file=daily"

/system scheduler
add name=daily-export start-time=03:00:00 interval=1d on-event=daily-backup
```

The `mikrotik_routeros` codec capability matrix lists
`/filter/rule` and `/nat/rule` under **unsupported** with
explicit rationale ("Firewall filter rules are Tier 3
(informational) and not auto-rendered by the canonical bridge.";
"NAT rules are Tier 3 — informational only.").

The remaining surfaces (mangle, queues, wireless, hotspot,
IPsec, WireGuard, OVPN/L2TP/PPPoE tunnels, scripts, scheduler)
are not modelled at all in v1.  They lift to `raw_sections` on
parse for operator review.

## Arista EOS

Arista does have parallels for some of these — `ip access-list`
for filtering, `route-map` for policy-based-forwarding, `qos
profile` for QoS — but they are vendor-specific and structurally
different from RouterOS's mangle/queue/firewall pipeline.

Arista does NOT have:

* Wireless interfaces (Arista is a wired DC switch family;
  wireless lives on Aruba / Mist / Cisco product lines).
* Hotspot / captive portal (typically lives on a separate
  AP-controller appliance).
* IPsec / WireGuard / OVPN / L2TP / PPPoE on the management
  plane (Arista is a fabric switch, not an edge VPN
  concentrator).
* PPPoE client on a wired uplink (DC fabric uplinks are
  typically L3 routed peerings, not consumer-broadband links).
* `/system scheduler` (Arista uses CloudVision /eAPI / external
  scheduling rather than on-device cron).
* `/system script` (Arista uses Python / eAPI scripts but they
  live in a different surface).

## Cross-vendor mapping

The canonical surface for this body of plumbing is **empty** —
there is no `firewall_rules` / `nat_rules` / `queues` / `vpn` /
`wireless` field on `CanonicalIntent`.  RouterOS source content
lifts to `raw_sections` on parse and drops on Arista render with
banners.

**This is the largest source of cross-vendor information loss in
the mikrotik_routeros -> arista_eos direction.**  A typical
RouterOS edge config might be 50% canonical-portable (interfaces,
addresses, routes, DHCP, DNS, NTP, hostname, SNMP, RADIUS) and
50% Tier-3 plumbing (firewall, NAT, mangle, queues, wireless,
hotspot, tunnels, scripts, scheduler).  The Arista render
captures only the canonical-portable half.

Operators planning this migration should:

1. Audit the RouterOS source's `raw_sections` content before
   migration to identify which Tier-3 surfaces carry load-
   bearing semantics (firewall policy enforcing security
   posture, NAT rules carrying public service exposure, IPsec
   tunnels carrying inter-site connectivity).
2. Re-implement each load-bearing surface using Arista's native
   primitives (`ip access-list`, `route-map`, etc.) or by
   pushing the responsibility upstream / downstream of the
   Arista device (firewall to a dedicated appliance, IPsec to a
   VPN concentrator, etc.).
3. Accept that this is a **scope shift**, not a config
   translation: moving from RouterOS to Arista is moving from
   "router-first does it all" to "fabric switch does the
   forwarding, dedicated appliances do the rest."

The MikroTik synthetic kitchen-sink intentionally exercises the
canonical-portable surface only, but realistic RouterOS configs
should expect to land most of their content in `raw_sections`
when migrating to Arista.

Disposition: **not_applicable** — `raw_sections` is Tier 3 by
design and never auto-rendered.  No translation to Arista is
attempted; the surface drops with operator review-required
banners.  The canonical model deliberately does not capture
these surfaces because no cross-vendor target carries them in a
shape-compatible form.
