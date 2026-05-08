# Fortinet FortiGate → MikroTik RouterOS

## Scenario

You operate a fleet of FortiGate appliances (FG-100E, 70G branch, etc.)
in branch sites and you're migrating to MikroTik RouterOS for cost
reasons.  The shared-network-function subset — DNS, interfaces, DHCP
pools, static routes — should translate.  The FortiGate-flagship
surfaces (firewall, NAT, IPsec, SD-WAN, UTM) are explicitly out of
scope and you'll handle those separately.

## What Netcanon does for you

**Translates:**

- `config system global / set hostname` → `/system identity`
- `config system dns / set primary` → `/ip dns`
- `config system interface / edit <port> / set ip <addr> <mask>`
  → `/interface ethernet` + `/ip address`
- `config system dhcp server` → `/ip pool` + `/ip dhcp-server` +
  `/ip dhcp-server network`
- VLAN sub-interfaces (`config system interface / edit "VL_10" /
  set type vlan / set vlanid 10 / set interface "internal1"`) →
  `/interface vlan` with parent binding
- Static routes (`config router static`) → `/ip route`

**Deferred (Tier-3):**

- **Firewall policy table** — `config firewall policy`, the zone-pair /
  interface-pair stateful policy that's FortiGate's primary semantic
- **NAT** — VIPs (`config firewall vip`), IP pools, central-NAT
- **IPsec VPN** — `config vpn ipsec phase1-interface` /
  `phase2-interface`
- **SSL-VPN** — `config vpn ssl settings`, portal config
- **UTM profiles** — web-filter, antivirus, IPS, application-control
- **SD-WAN** — health-check, SLA, performance-SLA rules
- **FortiGuard categories** — license-bound URL category lists

If firewall translation is your primary need, see
[`../COMPARISON.md`](../COMPARISON.md) for Capirca / Aerleon.

## Run the demo

```bash
python tools/demo.py --pair fortigate__mikrotik
```

The embedded scenario covers system global (hostname), system dns,
two interfaces (`internal1`, `internal2`), and a DHCP server pool.

## Tier-3 boundary in this scenario

Most of a FortiGate config is Tier-3.  A real-world FortiGate backup
typically splits into:

- A small fraction of Tier-1/2 (interfaces, VLANs, DHCP, DNS, basic
  routes, RADIUS, SNMP) — Netcanon translates this
- The bulk Tier-3 (firewall policies, NAT, VPN, UTM, SD-WAN) —
  Netcanon's parser surfaces these via the migrate-page Tier-3
  banner but does NOT auto-render them

That's the matrix-honesty discipline working as designed: the
operator sees explicitly what didn't translate, with a count and the
section names, rather than getting silently-truncated output.

## Manual review checklist

Before deploying the rendered RouterOS config to a real MikroTik
device, verify:

- [ ] **Port naming**: FortiGate's `internal1` / `wan1` / `port5`
      become opaque port names in RouterOS.  RouterOS's renamed-port
      preservation feature lets you use meaningful names like
      "Uplink-WAN" via `set [ find default-name=ether1 ] name=...` —
      verify the mapping makes sense for your hardware.
- [ ] **DHCP pool ranges**: FortiGate's
      `config ip-range / edit 1 / set start-ip / set end-ip` form
      translates to RouterOS's `/ip pool` ranges; verify the
      start/end IPs align with your existing DHCP plan.
- [ ] **VLAN sub-interface naming**: FortiGate `VL_10` →
      `/interface vlan` (default-named); rename if you have a
      naming convention.
- [ ] **NO firewall policy** — RouterOS has its own firewall model.
      Plan to author the firewall rules natively in RouterOS
      (`/ip firewall filter` / `nat` / `mangle`) since FortiGate's
      zone-based stateful policy doesn't translate cross-vendor.
- [ ] **NO NAT** — same.  Native RouterOS NAT design.
- [ ] **License-bound features (FortiGuard, IPS, web-filter)** —
      FortiGate-only.  Replace with RouterOS-native equivalents
      (DNS-based filtering, custom firewall rules) or offload to
      external appliances.

## See also

- [FortiGate vendor page](../vendors/fortigate.md)
- [MikroTik RouterOS vendor page](../vendors/mikrotik_routeros.md)
- [`../CAPABILITIES.md`](../CAPABILITIES.md)
- [`../COMPARISON.md`](../COMPARISON.md) — Capirca / Aerleon for
  firewall ACL translation
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
