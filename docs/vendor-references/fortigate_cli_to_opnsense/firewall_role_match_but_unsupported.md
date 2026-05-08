# Firewall role match — but unsupported in canonical

This is the natural-fit pair in the cross-mesh: both ends are
firewall-class platforms with their own native firewall / NAT / VPN
models.  And yet the cross-vendor migration of those features through
the canonical tree is **unsupported** in v1 because the canonical
schema does not model firewall rules / NAT / VPN at all.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Cookbook — Firewall
policies](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

FortiGate's firewall surface includes:

```
config firewall policy
    edit 1
        set name "lan-to-wan"
        set srcintf "internal"
        set dstintf "wan"
        set srcaddr "all"
        set dstaddr "all"
        set action accept
        set schedule "always"
        set service "ALL"
        set utm-status enable
        set ssl-ssh-profile "deep-inspection"
        set logtraffic all
    next
end
config firewall vip
    edit "web-server-vip"
        set extip 198.51.100.10
        set extintf "wan"
        set mappedip "10.0.10.50"
        set portforward enable
        set extport 443
        set mappedport 443
    next
end
config firewall address
    edit "lab-net"
        set subnet 10.0.10.0 255.255.255.0
    next
end
config vpn ipsec phase1-interface
    edit "site-to-site"
        set interface "wan"
        set peertype any
        set proposal aes256-sha256
        set psksecret ENC fakeEncodedIpsecSecret==
        set remote-gw 198.51.100.250
    next
end
```

Notes:

- FortiGate firewall is session-based, zone-aware, with deep UTM
  integration (IDS/IPS, web filter, SSL inspection, application
  control).  Policies reference named address objects, named
  service objects, and named UTM profiles.
- NAT lives INSIDE firewall policy (`set nat enable`) plus
  `config firewall vip` for inbound NAT (DNAT/PAT).
- IPsec VPN uses a phase1-interface + phase2-interface model.
- VDOMs partition all of the above into independent multi-tenant
  contexts (separate policy tables, address books, admin sessions).

## OPNsense

Source: [OPNsense Firewall
manual](https://docs.opnsense.org/manual/firewall.html) and
[OPNsense IPsec
manual](https://docs.opnsense.org/manual/vpnet.html)
Retrieved: 2026-05-01

OPNsense's firewall surface (pf-based):

```xml
<opnsense>
  <filter>
    <rule uuid="...">
      <type>pass</type>
      <interface>lan</interface>
      <ipprotocol>inet</ipprotocol>
      <source>
        <network>lan</network>
      </source>
      <destination>
        <any>1</any>
      </destination>
      <descr>Allow LAN to any</descr>
    </rule>
  </filter>
  <nat>
    <outbound>
      <mode>automatic</mode>
    </outbound>
  </nat>
  <ipsec>
    <phase1>
      <ikeid>1</ikeid>
      <descr>site-to-site</descr>
      <interface>wan</interface>
      <remote-gateway>198.51.100.250</remote-gateway>
      <pre-shared-key>shared-secret-cleartext</pre-shared-key>
    </phase1>
  </ipsec>
</opnsense>
```

Notes:

- OPNsense firewall is pf-based (FreeBSD packet filter).  Rules are
  list-ordered, interface-anchored, with zone semantics.
- NAT has separate outbound (SNAT) / one-to-one / port-forward
  blocks.
- IPsec uses phase1 / phase2 elements similar to FortiGate's model
  but with different field names.
- WireGuard plugin (separate from IPsec) is widely used.
- Captive portal, traffic shaping, IDS (Suricata) all live in
  separate top-level blocks.

## Cross-vendor mapping

The canonical schema has NO model for firewall policy / NAT / VPN /
IPsec / WireGuard / captive portal in v1.  The FortiGate codec's
capability matrix lists `/filter/rule` and `/nat/rule` as
unsupported with rationale: "FortiGate policy rules are Tier 3 —
policy semantics differ fundamentally from other vendors
(session-based, zone-aware, UTM-enabled)".  The OPNsense codec's
capability matrix similarly lists `/filter/rule` and `/nat/outbound`
as unsupported.

Therefore on this cross-pair:

- FortiGate firewall policy: **unsupported** — drops on canonical
  parse.  OPNsense renders nothing.
- FortiGate NAT (`config firewall vip` + policy-NAT):
  **unsupported** — drops on canonical parse.
- FortiGate VPN (`config vpn ipsec` / `config vpn ssl`):
  **unsupported** — drops on canonical parse.
- FortiGate UTM profiles (web filter, IPS, application control):
  **unsupported** — drops on canonical parse.
- VDOMs: **unsupported** — VDOMs are a heavyweight multi-tenancy
  primitive that requires per-VDOM canonical-tree splitting (out
  of v1 pipeline scope).

This is the unfortunate gap on what should be the most
role-compatible pair in the matrix: both ends are firewalls, both
have native models for the same concepts, but the canonical-portable
form does not carry the data.  Operators consolidating one firewall
into the other must manually reconstruct security policy after
migration.

The canonical schema gap is intentional in v1 (Tier 3 policy
semantics differ enough between vendors that auto-translation would
be unsafe).  Future work: extend canonical with a vendor-portable
firewall-rule model (likely netcanon-ext YANG style); currently
not scheduled.
