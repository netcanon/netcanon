# OPNsense → Juniper Junos

## Scenario

You operate an OPNsense edge firewall and you're migrating to a
Juniper SRX or vMX-class device for an enterprise edge.  OPNsense's
**flagship surfaces — firewall rules, NAT, IPsec / OpenVPN /
WireGuard — don't translate cross-vendor by design** (firewall
semantics differ too much vendor-to-vendor for safe automation).
What DOES translate is the interfaces / VLANs / DNS / static route /
local-user surface that's shared across all routers.

This walkthrough is the most useful as a **demonstration of the
Tier-3 boundary** working as advertised — the migrate-page banner
shows operators exactly what didn't translate, rather than
silently dropping it.

## What Netcanon does for you

**Translates:**

- `<hostname>` → `set system host-name`
- `<dnsserver>` → `set system name-server`
- `<interfaces><lan><ipaddr>` / `<subnet>` → `set interfaces <name>
  unit 0 family inet address <ip>/<prefix>`
- VLANs from `<vlans><vlan>` → `set vlans <name> vlan-id <id>`
- Static routes from `<staticroutes>` → `set routing-options static
  route ... next-hop`
- Local users (with bcrypt hashes form-preserved) → `set system
  login user <name>`

**Deferred (Tier-3 — substantial slice of OPNsense):**

- **`<filter>` firewall rules** — OPNsense's primary semantic; the
  whole reason most operators run OPNsense.  Doesn't translate to
  Junos's firewall-filter grammar.
- **`<nat>` NAT rules** — port forwards, outbound NAT, 1:1 NAT
- **`<ipsec>`** — IPsec VPN configuration
- **`<wireguard>`** — WireGuard config (parse-tolerant)
- **OpenVPN server / client instances**
- **`<proxy>` web proxy / IDS / IPS** — Suricata config
- **`<captiveportal>`** — captive portal
- **Routing-protocol plugins** — FRR / OSPF / BGP plugins
- **`<cert>` / `<ca>`** — PKI / certificate chains preserved
  byte-for-byte but not actively translated to Junos's PKI
  configuration

## Run the demo

```bash
python tools/demo.py --pair opnsense__junos
```

The embedded scenario is intentionally minimal (system + WAN/LAN
interfaces + DNS) so you can see the cross-paradigm grammar shift
clearly.  In production an OPNsense `config.xml` is typically
2,000+ lines, with the majority being Tier-3 (firewall/NAT/VPN).

## What the migrate page banner shows you

Real-world OPNsense input goes through:

1. Parser walks the XML
2. Tier-1/2 fields populate the canonical model
3. Tier-3 detection heuristic surfaces dropped sections by name +
   line count: e.g.
   ```
   Detected but not translated:
     - filter (847 rules)
     - nat: outbound (12 rules)
     - ipsec: phase1-interface (3 entries)
     - wireguard (1 instance)
     - openvpn-server (2 instances)
   ```
4. Junos rendering uses ONLY the Tier-1/2 surface

That banner is the matrix-honesty discipline made visible to the
operator — they see exactly what's NOT in the rendered output, with
counts, before they apply it.

## Manual review checklist

Before deploying the rendered Junos config to a real SRX/MX device,
verify:

- [ ] **Interface-name mapping**: OPNsense's `igc0` / `igc1` (NIC
      driver names) map to Junos's `ge-0/0/0` / `xe-0/0/0` etc.  The
      port-rename mesh handles common cases; verify your specific
      hardware's enumeration.
- [ ] **WAN interface mode**: OPNsense's `<ipaddr>dhcp</ipaddr>` →
      Junos's `set interfaces ... unit 0 family inet dhcp`.  If you
      use track-interface / IPv6 prefix delegation, those parse-and-
      ignore in v1; rebuild natively on Junos.
- [ ] **VLAN parent binding**: `<vlans><vlan><if>igc1</if><tag>10</tag>`
      → `set interfaces ge-0/0/1 unit 10 vlan-id 10`.  Verify the
      parent-interface mapping after the port rename.
- [ ] **Local user bcrypt hashes**: `<password>$2y$11$...</password>`
      preserves through round-trip but Junos prefers `$1$` or `$5$`
      crypt forms.  Re-issue passwords natively on Junos for
      production.
- [ ] **CRITICAL: rebuild firewall + NAT + VPN natively on Junos.**
      None of those translate.  This is by design (Tier-3 boundary)
      and is the largest chunk of an OPNsense config.  Do NOT
      assume Junos's `set security policies` is a 1:1 port of
      OPNsense's `<filter><rule>`.
- [ ] **Self-signed cert chains**: OPNsense's `<cert>` / `<ca>`
      content is opaque-carry; Junos PKI configuration is separate.
      Re-issue certs on Junos via `set security pki`.

## When NOT to use this pair

If your migration's primary need is firewall translation, this is
the wrong tool.  See [`../COMPARISON.md`](../COMPARISON.md) for
Capirca / Aerleon (firewall DSL → multiple vendors).  Netcanon's
OPNsense → Junos pair is for migrations where the firewall posture
is being **rebuilt natively** on the target (because the operator
is taking the migration as an opportunity to clean up firewall
rules) and only the *router* portion needs translation.

## See also

- [OPNsense vendor page](../vendors/opnsense.md)
- [Juniper Junos vendor page](../vendors/juniper_junos.md)
- [`../CAPABILITIES.md`](../CAPABILITIES.md) — see the Tier-3
  section enumerating what's deliberately deferred
- [`../COMPARISON.md`](../COMPARISON.md) — adjacent tools for
  firewall translation
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — diagnostic
  flowchart for "my Tier-3 surface didn't translate" (it's expected;
  here's what to do)
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
