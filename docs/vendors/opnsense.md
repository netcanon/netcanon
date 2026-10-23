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
- VLANs — `<vlans><vlan>` block: each `<vlan>` is a VLAN device,
  kept on the parent (`<if>`) and tag it states, under its own name
  (`<vlanif>`), which the zone that assigns it names (see "VLAN
  devices" below); one on a port or a LAGG is a sub-interface of it
- DHCP server pools — `<dhcpd>` with per-zone configuration; a
  pool is on the device its zone is assigned to

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
- **A VLAN's name is its device.**  An OPNsense `<vlan>` has no name
  of its own: the parser names a VLAN after its device (`<vlanif>`),
  and the renderer writes another vendor's VLAN name as the `<descr>`
  where the VLAN has no description, and drops it where it has one
  (`/vlans/vlan/name` is lossy).  Onto IOS-XE CLI, NX-OS, EOS, AOS-S, Junos and OS10,
  which write one label for a VLAN, the `<descr>` is written as the
  VLAN's name (`name USER VLAN`; `USER_VLAN` on EOS, quoted on
  Junos, the SVI's `description` on OS10); onto AOS-CX it is the
  VLAN's `description` beside the device's name.  Onto FortiOS and
  RouterOS it is the alias or `comment=` of the VLAN's interface,
  unless the device is assigned to a zone whose `<descr>` the
  interface takes: then the VLAN's `<descr>` is in a `# review:`
  line beside it, and the job lists `/vlans/vlan/description` as a
  loss.
- **A VLAN device on a port or a LAGG is a sub-interface of it.**
  It tags the frames of that one parent, and OPNsense takes the same
  tag on another parent as another device, so the parser reads the
  parent: a bridge (one `<bridges>` names, or one named `bridge` and
  digits), another VLAN device, a zone's key (`lan`, `opt3`: never a
  device's name, and what Netcanon writes for the parent of a VLAN in
  a config with no port), or a name that says it is a VLAN
  interface, a loopback or a tunnel keeps the device a VLAN
  interface and a VLAN of its tag; any other parent is a port, or a
  LAGG where `<laggs>` names it, whatever its name -- zones are not
  typed, and no classifier reads every driver's name (`igc0`).  The
  device is then typed as its parent, its tag its own, and makes no
  VLAN; its description is its zone's, or its `<descr>` where the
  zone has none, and a `<descr>` beside a zone's own is said in a
  row.  Onto another vendor it goes where its parent goes, named by
  its tag (`vlan01` on `igb2` with tag 20 onto EOS is `interface
  Ethernet2.20` with `encapsulation dot1q vlan 20`); between two
  OPNsense configs it keeps its name.  A parent no classifier reads
  (`igc0`) is listed, with the device on it, until an entry in the
  port map names it, and the device goes with that entry.  Onto
  AOS-S, AOS-CX, OS10 and IOS-XE over NETCONF, which have no form
  for a sub-interface's tag, the job is `partial`, the validation
  report listing the tag.  ⚠️ Up to 0.7.7 every device was a VLAN
  interface and a VLAN: onto IOS-XE, NX-OS, EOS or Junos one on a
  port came out as `interface Vlan10` or `irb.10`, which nothing on
  the port carries.
- **Another platform's VLAN is a VLAN device, and comes back as one
  where it rides on a bridge.**  OPNsense has no VLAN apart from a
  VLAN device on one parent, so the renderer writes a switch's VLAN
  (`vlan 10` with tagged ports) on a LAGG or a port that carries it,
  else on the first LAGG, the first interface that looks like a
  port, or `lan`.  On a port or a LAGG the parser reads that device
  back as a sub-interface of it (above): its tag is the VLAN's id,
  its `<descr>` the sub-interface's description, and there is no
  VLAN record (`/vlans/vlan/id` and `/vlans/vlan/description` are
  lossy).  ⚠️ Up to 0.7.7 every device was read back as a VLAN.
- **A sub-interface of another vendor is a VLAN device.**  IOS-XE
  `GigabitEthernet0/0/1.100` with `encapsulation dot1Q 200`, a Junos
  `unit 100 vlan-id 200`: OPNsense has no sub-interface of its own,
  so the renderer writes a `<vlan>` on the port the name is a unit of
  (`<if>igb1</if>`), with the sub-interface's own tag
  (`<tag>200</tag>`) under its name (`<vlanif>igb1.100</vlanif>`),
  and the zone that holds its address assigns that device; one that
  holds nothing a zone holds is the device alone, its `<descr>` the
  sub-interface's description.  The parser reads it back as a
  sub-interface of the port again, and OPNsense's VLAN
  form refuses the dotted name when the VLAN is saved (the review
  comment beside it says so: rename it `vlan0.<n>` or
  `<port>_vlan<tag>`, and the zone's `<if>` with it).  A name an
  entry gives with no port in it rides on the parent chosen for every
  VLAN, under a review comment.  OPNsense keeps one VLAN device for a
  tag on a parent (`Vlan.xml`): where the output has a tag twice on
  one, the second `<vlan>` holds a review comment that names the
  first -- merge the two, or move one to another port.  A Q-in-Q
  sub-interface is a device of its outer tag, and its inner tag is
  listed as a loss.
- **Static routes are source-side only.**  The parser harvests
  `<staticroutes>` + `<gateways>` into `CanonicalStaticRoute` (since
  #350), so OPNsense-*as-source* routes translate outward — but the
  `config.xml` renderer emits **no** `<staticroutes>`/`<route>` block,
  so an X→OPNsense migration drops every static route on render.
  Because the record does not survive at all, this is declared
  **unsupported**, not lossy: `/routing/static-route` and every leaf
  beneath it (`gateway`, `metric`, `description`, `interface`, `vrf`)
  are `UnsupportedPath` entries, so validation reports `block` rather
  than `warn` and the operator is told to re-create routing on the
  target.  It was declared lossy until the scope re-weight wave —
  honest about the loss, but understating a total one as a skimmable
  warning.

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

- **A review comment shows `--` in a name as `- -`.**  XML allows no
  `--` inside `<!-- -->`, and `-->` ends it: a source account left out
  for its password, named with either, made the output malformed or
  wrote what followed as XML (an account the source never had).  The
  name in the comment is the source's name with a space after each
  hyphen that another follows.
- **A user whose password cannot be carried is left out** as a target,
  with an XML comment in its place.  Up to 0.7.7 the `<user>` element
  stayed, with no `<password>`.  A password the source holds as typed
  (IOS-XE `password 0`, AOS-CX `password plaintext`) is one of them:
  `<password>` is the hash `password_verify()` checks a password
  against, and up to 0.7.7 the typed string was written there.
- **Driver names onto another vendor** — an OPNsense interface is
  named for its FreeBSD driver, and the port translator reads some
  drivers' names (`igb0`, `ix1`, `em0`) and not others (`igc0`).
  One it does not read is left as it is on the target (`set
  interfaces igc0 ...` in a Junos config), and with no devices
  declared the job is `partial` and lists it in
  `untranslated_ports` until an entry of `port_rename_map` gives it
  a name.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § D1.
- **A DHCP pool goes with its zone's port.**  `<dhcpd>` is keyed
  by zone (`<lan>`), and the pool's interface is the device
  `<interfaces>` assigns to that zone (`<lan><if>igb1</if>`), so on
  another platform the pool is bound to the port that device
  became — and named after it, where the target names a pool after
  its interface (`ip dhcp pool GigabitEthernet0_1`, Junos
  `pool_ge_0_0_1`).  A pool whose zone `<interfaces>` does not have
  has no interface to be on: it is left out, and the migrate banner
  names the zone (`<dhcpd><opt9>: no <opt9> in <interfaces>, so its
  DHCP pool has no interface`).  Two zones assigned to ONE device
  are not handled: both pools are then on that port, and a target
  that names a pool after its interface writes two pools of one
  name (Junos reads its own two back as one).  OPNsense's own
  output then has the device's tag twice under `<dhcpd>` (`<igb1>`,
  and `<igb1>` again), where up to 0.7.7 it had the two zones'
  (`<lan>`, `<opt1>`).  A real config is not expected to have that
  — a device is assigned to one zone — which has not been checked
  against OPNsense's own validation; look for it in a `config.xml`
  edited by hand.  On an OPNsense TARGET a pool is written under
  the zone of its interface.  One that names no interface (a pool
  from IOS-XE or RouterOS, a Junos pool whose server group binds no
  interface) is written under `<lan>`, and an EOS pool, whose own
  name is where its interface goes, under a zone of that name
  (`<users>`): either serves nothing unless the output has a zone
  of that name, and read back such a pool is left out.  The
  validation report lists `/dhcp-servers/pool` as lossy for every
  pool written onto OPNsense, a bound one included.  Bind the pool
  to an interface, or move it by hand.
  ⚠️ Up to 0.7.7 the pool's interface was the zone's NAME: a Junos
  output bound its DHCP server to `interface lan`, FortiOS wrote
  `set interface "lan"`, and an OPNsense output had `<dhcpd><lan>`
  beside an `<interfaces>` with no `<lan>` in it.
- **A lagg's members** — OPNsense adds only an unassigned interface
  to a lagg ("Only unassigned interfaces can be added to LAGG",
  docs.opnsense.org, Other Types), so a member is named in `<laggs>`
  alone, and Netcanon gives it a port record of its own that names
  its lagg.  Onto OPNsense, a member of a LAG is written in the
  lagg's `<members>` and in no zone of `<interfaces>`; where the
  source gave the member something a zone would carry (a
  description, an MTU, an address, a disabled state), a comment in
  the `<lagg>` names the member and the elements not written, never
  their values.
  ⚠️ Up to 0.7.7 the members had no record: a target that writes a
  LAG on each member's own stanza (EOS, AOS-CX, IOS-XE, IOS-XR,
  NX-OS, OS10, Junos) wrote the LAG with no member, or none at all,
  in a job that could be `completed`; and an OPNsense output
  assigned each member a zone of its own.
- **Declaring an OPNsense device** — BSD device names are the
  system's and are lower-case, so with both devices declared on the
  API or in the Interface rename modal an override typed in another
  case (`IGB0`) is read as the port
  `igb0`, not as a second interface.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
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
- **VLAN devices** — a `<vlan>` is a device, named by its
  `<vlanif>`: OPNsense names a new one `vlan01`, `vlan02` ... (older
  configs `<parent>_vlan<tag>`), or takes a typed `vlan0` and digits
  and dots, so the digits of the name are NOT the tag.  The parser
  gives each device the record of the zone that assigns it (or a
  record of its own where none does), with its parent from `<if>`:
  on a port or a LAGG it is a sub-interface of it (above); on a
  bridge, another VLAN device or a zone's key it is typed
  `ianaift:l3ipvlan`, and
  the VLAN is named after the device, its `<descr>` the VLAN's
  description.  The renderer writes each VLAN
  interface as the device of that name on its parent, and no zone for
  a device that holds nothing a zone holds.  A name OPNsense's VLAN
  form would refuse (`Vlan.php`: `vlan0` and digits and dots, `qinq0`
  ... on a parent whose name holds `vlan`, or `<parent>_vlan<tag>`) is
  written with a `<!-- review: -->` comment beside it; an SVI from
  another vendor is named `vlan0.<id>`.  Not translated, and said in
  a row: a device that is not one 802.1Q tag (`802.1ad`, or a blank
  `<proto>` on a device another VLAN rides on, which OPNsense sends as
  802.1ad; a tag outside 1-4094), with what rides on it, its zone and
  a DHCP pool on it; and a `<pcp>` other than 0, whose VLAN is kept.
  Known limitation: onto another vendor, a device `vlan0.<n>` on a
  bridge, another VLAN device or a zone's key is the SVI of VLAN `n`
  whatever its
  tag (CHANGELOG, known limitations); on a port it is a sub-interface
  named by its tag.
  Guarded by
  `tests/unit/migration/codecs/opnsense/test_a_vlan_device_is_defined.py`.
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
