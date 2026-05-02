# Firewall / NAT / VPN / VDOM (unsupported on this direction)

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Cookbook — Firewall policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/) — `config firewall policy`.
- [FortiGate / FortiOS 7.4 Administration Guide — VDOMs](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config vdom`.
- [FortiGate / FortiOS 7.4 Administration Guide — IPsec VPN](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config vpn ipsec phase1-interface / phase2-interface`.

Retrieved: 2026-04-30

FortiGate's primary product surface is firewall policy, NAT, and VPN.  These features account for most of the lines in a real FortiGate config:

```
config firewall policy
    edit 1
        set name "INTERNAL-to-WAN"
        set srcintf "port4"
        set dstintf "port1"
        set srcaddr "all"
        set dstaddr "all"
        set action accept
        set schedule "always"
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

config vdom
    edit root
    next
    edit dmz
    next
end

config vpn ipsec phase1-interface
    edit "to-branch"
        set interface "port1"
        set peertype any
        set proposal aes256-sha256
        set remote-gw 203.0.113.1
        set psksecret ENC fakeIPsecPSK==
    next
end
```

These surfaces are **not modelled in CanonicalIntent** in v1:

- **Firewall policy** (`config firewall policy`) is session-based, zone-aware, and UTM-enabled.  Cross-vendor translation to other vendors' L3/L4 ACL primitives loses the session/UTM dimension.  Tier 3 by design.
- **NAT** (`config firewall vip`, `config firewall ippool`, source/destination NAT inside policies) lives inside the firewall product surface; not auto-translatable.
- **VDOMs** (`config vdom`) are heavyweight multi-tenancy primitives carrying independent firewall policy tables, address objects, and admin sessions.  Not analogous to Cisco-style named-VRF; not modelled in canonical.
- **IPsec / SSL VPN** (`config vpn ipsec`, `config vpn ssl`) are FortiGate-specific and not in canonical scope.
- **UTM features** (antivirus, IPS, web filter, application control) are FortiGate-only.

## MikroTik RouterOS

Sources:
- [Firewall — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/130220/Firewall) — `/ip firewall filter / nat / mangle`.
- [VRF — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF) — `/ip vrf` (RouterOS 7+).

Retrieved: 2026-04-30

RouterOS has its own firewall primitives:

```
/ip firewall filter
add chain=input action=accept connection-state=established,related
add chain=input action=drop in-interface=ether1
add chain=forward action=accept connection-state=established,related

/ip firewall nat
add chain=srcnat action=masquerade out-interface=ether1
```

These RouterOS firewall / NAT primitives:

- Are **classical iptables-derived chain/match/action grammar** (chain=input/output/forward; action=accept/drop/reject/...; matches like in-interface, src-address, dst-port, etc.).
- Are **structurally distinct** from FortiGate's session-based zone-aware policy model — there is no clean cross-vendor translation surface.
- Are **Tier 3 (informational only)** in canonical scope and remain in `raw_sections` for review.

RouterOS 7+ has `/ip vrf` for VRF support; the MikroTik codec does not parse it in v1.

## Cross-vendor mapping (FortiGate → RouterOS)

The fields below are **all `unsupported` on this direction** because the canonical model does not represent the source FortiGate concept:

- **Firewall policy** — `unsupported`.  FortiGate `config firewall policy` is parse-and-ignore in v1 (Tier 3).  Even if both codecs lifted the rules to a canonical filter table, the session/UTM dimension would not survive translation to RouterOS's iptables-derived chains.
- **NAT** — `unsupported`.  FortiGate `config firewall vip` / `config firewall ippool` and source/destination NAT inside policies have no canonical representation; RouterOS-side `/ip firewall nat` is Tier 3.
- **VPN / IPsec** — `unsupported`.  FortiGate `config vpn ipsec phase1-interface / phase2-interface` and RouterOS `/ip ipsec` are independent product surfaces; cross-vendor migration is operator-curated.
- **VDOMs** — `unsupported`.  FortiGate VDOMs are heavyweight tenancy that does not map to RouterOS's flat single-config model.  Operators consolidating multi-VDOM FortiGate into RouterOS must manually plan device-per-VDOM splitting.
- **UTM** — `unsupported`.  Antivirus, IPS, web filter, and application control are FortiGate-only.

The corresponding canonical fields (where they exist) are `not_applicable` on the FortiGate-source side because FortiGate does not populate them — but firewall_policy specifically is `unsupported` rather than `not_applicable` because the FortiGate source DOES carry meaningful policy data; it just has nowhere canonical to land.

Operators should treat the FortiGate firewall config as **documentation rather than a translatable artefact** and reconstruct equivalent policy on RouterOS manually.
