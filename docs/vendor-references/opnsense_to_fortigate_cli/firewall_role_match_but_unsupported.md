# Firewall role match — but unsupported in canonical (reverse direction)

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/firewall_role_match_but_unsupported.md`.

This is the natural-fit pair: both ends are firewall-class platforms
with their own native firewall / NAT / VPN / VPN models.  And yet
the cross-vendor migration of those features through the canonical
tree is **unsupported** in v1 because the canonical schema does not
model firewall rules / NAT / VPN at all.

## OPNsense

Source: [OPNsense Firewall
manual](https://docs.opnsense.org/manual/firewall.html), [OPNsense
IPsec manual](https://docs.opnsense.org/manual/vpnet.html), [OPNsense
WireGuard
manual](https://docs.opnsense.org/manual/how-tos/wireguard-client.html)
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
    <onetoone uuid="...">
      <interface>wan</interface>
      <external>198.51.100.50</external>
      <source>
        <address>10.0.10.50</address>
      </source>
    </onetoone>
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
  <OPNsense>
    <wireguard>
      <client uuid="...">
        <name>tunnel-1</name>
        <pubkey>fakeBase64WireguardPubKey...</pubkey>
        <serveraddress>vpn.example.invalid</serveraddress>
      </client>
    </wireguard>
  </OPNsense>
</opnsense>
```

OPNsense firewall surface notes:

- pf-based stateful firewall (FreeBSD packet filter).
- NAT split: outbound (SNAT) / port-forward / one-to-one (NAT/PAT).
- IPsec phase1 / phase2 elements similar to FortiGate but different
  field names.
- WireGuard plugin (separate from IPsec) — popular alternative.
- Captive portal, traffic shaping, IDS (Suricata), HAProxy plugin —
  all separate top-level blocks.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/firewall_role_match_but_unsupported.md`
for the FortiGate-side shape.  Key points:

- `config firewall policy` — session-based, zone-aware, UTM-integrated.
- NAT lives INSIDE policy (`set nat enable`) plus
  `config firewall vip` for inbound.
- IPsec phase1-interface / phase2-interface model.
- VDOMs partition all of the above into multi-tenant contexts.

## Cross-vendor mapping

The canonical schema has NO model for firewall policy / NAT / VPN /
IPsec / WireGuard / captive portal in v1.  The OPNsense codec's
capability matrix lists `/filter/rule` and `/nat/outbound` as
unsupported with rationale: "Firewall rules require the netcanon-ext
YANG module (Phase 2) — OpenConfig has no firewall model".  The
FortiGate codec's capability matrix similarly lists `/filter/rule`
and `/nat/rule` as unsupported.

Therefore on this cross-pair (reverse direction):

- OPNsense filter rules: **unsupported** — drops on canonical parse.
- OPNsense NAT (outbound / port-forward / one-to-one):
  **unsupported** — drops on canonical parse.
- OPNsense IPsec / WireGuard: **unsupported** — drops on canonical
  parse.
- OPNsense plugin features (captive portal, traffic shaping, IDS,
  HAProxy): **unsupported** — drops on canonical parse.

The canonical schema gap is intentional in v1 (Tier 3 policy
semantics differ enough between vendors that auto-translation would
be unsafe).  Future work: extend canonical with a vendor-portable
firewall-rule model; currently not scheduled.

The asymmetry from the forward direction: the disposition is
**unsupported** in BOTH directions for these fields, because the
canonical schema gap is symmetric — neither side carries the data
through.
