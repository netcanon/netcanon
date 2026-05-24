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

## L3 redundancy: CARP (no VRRP, no anycast)

**New in v0.2.0** (Wave B — BSD CARP wire-up).

OPNsense's HA primitive is BSD CARP (Common Address Redundancy
Protocol) — wire-incompatible with VRRP but semantically equivalent
from the operator's standpoint.  The canonical model collapses
CARP / VRRP / HSRP onto one `CanonicalVRRPGroup` shape via the
`mode` discriminator (`mode="carp"` for OPNsense).

### Grammar

CARP VIPs live under `<virtualip>` → `<vip>` envelopes in
`config.xml`.  The `<interface>` child carries a LOGICAL zone alias
(`lan` / `wan` / `opt2`) that the parser resolves through the
`<interfaces>` alias map to the canonical iface name.

```xml
<virtualip version="1.0.1" persisted_at="..." description="...">
  <vip>
    <mode>carp</mode>
    <interface>lan</interface>
    <vhid>10</vhid>
    <advskew>0</advskew>
    <advbase>1</advbase>
    <password>secret-passphrase</password>
    <subnet>10.0.10.254</subnet>
    <subnet_bits>24</subnet_bits>
    <descr>HA pair management VIP</descr>
  </vip>
</virtualip>
```

XML element mapping:

- `<mode>carp</mode>` → `mode="carp"` (other modes — `ipalias`,
  `proxyarp`, `other` — are NOT promoted to redundancy groups).
- `<vhid>N` → `group_id=N` (CARP VHID; same numeric range as VRRP
  VRID).
- `<subnet>` / `<subnet_bits>` → split by literal family — `:` and
  no `.` routes to `virtual_ipv6s`; otherwise `virtual_ips`.
- `<advskew>S` + `<advbase>B` → `priority=254-S`,
  `advertisement_interval=B`.  See "Known limitations" below for
  the inversion-lossiness caveat.
- `<password>HASH` → `authentication="carp-key:HASH"` (opaque,
  passed through; cross-vendor renders into VRRP devices surface a
  review comment).
- `<descr>` → `description`.
- `<interface>NAME` → back-pointer to `CanonicalInterface.name` via
  the OPNsense zone alias map.

### Known limitations

- **advskew↔priority inversion is declared lossy.**  CARP election
  uses advertisement-interval offsets (lower advskew wins;
  effective interval = advbase + advskew/256); VRRP priority is an
  advisory weight (higher wins).  The mapping `priority = 254 -
  advskew` preserves relative HA-pair ordering for same-vendor
  round-trip but NOT exact election timing.  Cross-protocol
  migration to / from VRRP devices loses the timing semantics —
  declared lossy on the codec capability matrix.
- **CARP-only on render.**  Canonical records with `mode="vrrp"`
  or `mode="hsrp"` are SKIPPED on OPNsense render — the codec
  doesn't emit pure-VRRP `<virtualip>` envelopes in v0.2.0 (rare in
  practice).  Only `mode="carp"` round-trips.
- **One VIP per VHID.**  Each `<vip>` carries one `<subnet>`.
  Multi-VIP canonical groups (Junos, IOS-XE secondaries) would need
  multiple VHIDs on render — same constraint as Aruba AOS-S.
- **Password is mandatory and bcrypt-opaque.**  Real CARP
  deployments always have a password; cross-vendor migration into
  VRRP targets surfaces a review comment because the bcrypt hash
  isn't a VRRP authentication-key.
- **No anycast-gateway grammar.**  OPNsense is a firewall codec
  without fabric primitives; all three anycast canonical paths
  parse-and-ignore as `unsupported`.
- **Orphan `<vip>` records skip silently.**  A `<vip>` whose
  `<interface>` doesn't match any parsed zone is dropped — we don't
  invent phantom `CanonicalInterface` records.
- **`<vip><mode>other</mode></vip>`** (`ipalias`, `proxyarp`, etc.)
  are NOT redundancy groups — they're additional IPs or ARP
  responders.  Parser excludes them from `vrrp_groups`.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP/CARP unified canonical model (`mode` discriminator
  rationale).  See `02-per-vendor-grammar.md` § "OPNsense" for the
  advskew↔priority inversion derivation.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (OPNsense out of scope — firewall
  platform without fabric grammar).

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
- **`opnsense_docs_carp_ha_master.xml`** — upstream
  `opnsense/docs` CARP HA tutorial master config (BSD-2-Clause).
  Two-router CARP pair MASTER side; Wave-B CARP-group wire-up
  reference fixture
- **`opnsense_docs_carp_ha_backup.xml`** — paired BACKUP side of
  the same CARP HA tutorial (BSD-2-Clause).  Together with the
  master fixture closes the headline CARP HA documentation gap

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
