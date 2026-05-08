# OPNsense — What works for me?

If you operate OPNsense firewalls and want to know what Netcanon
does for you, this is the page.

## TL;DR

- **`opnsense`** — OPNsense `config.xml` parse + render.
  **Certification: certified.**  Bidirectional.

The codec covers OPNsense 25.x with full operator-contributed
fixture coverage (8 interfaces, 5 VLANs, DHCP per-zone, Unbound
DNS, NTP, SNMP, IPsec, WireGuard, self-signed CA + cert chain).

**Important scope note**: OPNsense's flagship surfaces — firewall
policy, NAT, web-proxy, IPS — are deliberately deferred (Tier 3).
Netcanon translates the shared-network-function subset.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (`<system>/<hostname>`), `domain` (`<system>/<domain>`),
  DNS servers (`<system>/<dnsserver>`)
- Interfaces — `<interfaces>` block with per-zone `<descr>`
  (USERVLAN / MGMTVLAN / SERVERVLAN etc.); IPv4 (`<ipaddr>`),
  IPv6 (`<ipaddrv6>`); track-interface forms
- VLANs — `<vlans><vlan>` block (tagged form with parent interface
  binding)
- Static routes (`<staticroutes>`)
- DHCP server pools — `<dhcpd>` with per-zone configuration

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- Local users — `<user>` blocks with bcrypt `<password>` hash
  form-preserving migration; `<groupname>` mappings
- SNMP v1/v2c via `<snmpd>` (community, contact, location);
  **SNMPv3 is Tier-3** for OPNsense (raw `snmpd.conf` snippet
  carry-through; no canonical model)

## Lossy paths

- See per-codec `CapabilityMatrix.lossy` declarations in the codec
  source.  Most fields parse + render cleanly within the
  documented surface.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall rules** — `<filter>` / `<rule>` policy table
  (OPNsense's primary semantic; doesn't translate cross-vendor)
- **NAT** — `<nat>` block (port forwards, outbound NAT, 1:1 NAT)
- **IPsec VPN** — `<ipsec>` configuration
- **WireGuard** — `<wireguard>` config (parse-tolerant)
- **OpenVPN** — server / client instances
- **Web proxy / IDS / IPS** — `<proxy>`, Suricata config
- **Captive portal** — `<captiveportal>`
- **Routing protocols** — FRR / OSPF / BGP plugins (parse-tolerant)
- **PKI / certificates** — `<cert>` / `<ca>` chains preserved
  byte-for-byte but not actively translated

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`opnsense_core_default.xml`** — upstream
  `src/etc/config.xml.sample` (BSD-2-Clause)
- **`opnsense_service_test_config.xml`** — service-layer test
  config from upstream OPNsense core (BSD-2-Clause); WAN/LAN
  zones, DHCP client, DHCPv6 prefix delegation, gateway tracking
- **`opnsense_acl_test_config.xml`** — ACL model test (4 groups +
  5 users, richest local_users surface in the corpus)
- **`user_contrib_supergate_opn25.xml`** — operator-contributed
  real OPNsense 25.x config (2,302-line `/conf/config.xml`; 8
  interfaces with USERVLAN/MGMTVLAN/SERVERVLAN/CLUSTERVLAN/IOTVLAN
  zones, 5 VLANs tagged 10/11/20/100/150, 2 local users with
  bcrypt hashes, per-zone DHCP server config with extensive static
  MAC reservations, Unbound DNS local overrides, NTP, SNMP,
  IPsec, WireGuard, routing tables, self-signed CA + server cert
  chain)
- **`opnsense_paramiko_shell_capture.xml`** — regression fixture
  for the paramiko-shell command-echo bug (OPNsense backups
  captured via SSH raw PTY shell originally landed with a literal
  `cat /conf/config.xml\r\r\n` preamble before the `<?xml`
  prolog, breaking ET.fromstring; codec now tolerates leading
  noise via `_trim_xml_prologue`)

## Common gotchas

- **Backup capture artifact** — OPNsense backups via SSH +
  `cat /conf/config.xml` historically left a `cat /conf/config.xml\r\r\n`
  prefix and trailing shell prompt on disk.  The collector now
  strips both; the codec tolerates leading noise on parse for
  legacy backups already on disk.
- **Bcrypt password hashes** — `$2y$11$...` form preserved
  through round-trip; cross-vendor migration form-preserves to
  `$2y$11$fakeBcryptHashValueXXXX` placeholders when targeting
  vendors without bcrypt support, with review-comment surface.
- **Self-signed cert chains** — preserved byte-for-byte; private
  keys are stripped on sanitisation (see
  [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) sanitiser
  rules).
- **VLANs render-side** — early codec version silently dropped
  `CanonicalVlan` entries because there was no `<vlans>` render
  block; fix + regression test landed in the same commit
  (operator-contributed fixture surfaced this).
- **Backup-side**: requires `paramiko_shell` collector strategy
  in the device-definition YAML (`opnsense_shell_menu: true`).

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../COMPARISON.md`](../COMPARISON.md) — Capirca / Aerleon for
  firewall ACL translation
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
