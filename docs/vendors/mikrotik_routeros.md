# MikroTik RouterOS — What works for me?

If you operate MikroTik RouterOS devices and want to know what
Netcanon does for you, this is the page.

## TL;DR

- **`mikrotik_routeros`** — RouterOS `/path` slash-prefixed CLI
  export (`/export verbose` output) parse + render.
  **Certification: certified.**  Bidirectional.

The codec covers RouterOS 6.48.x and 7.18+ across home-router (RB952),
provisioning-script, and CRS310 + Proxmox-cluster fixtures.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (`/system identity`)
- Interfaces — physical (`ether<N>`, `sfp-sfpplus<N>`), bridge
  (`/interface bridge`), VLAN (`/interface vlan` named e.g.
  `gn-mgmt`); IPv4 (`/ip address`), IPv6 (`/ipv6 address`)
- VLANs — `/interface bridge port` with vlan-id mappings + tagged
  / untagged port assignment
- Static routes (`/ip route`)
- LAGs (`/interface bonding`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP — `/snmp community` (RouterOS overloads its `/snmp community`
  section for both v1/v2c and v3 — community + auth-protocol +
  auth-password + encryption-protocol + encryption-password)
- RADIUS — `/radius`
- Local users — `/user`
- DHCP server pools — `/ip pool` + `/ip dhcp-server network`
  (per-pool subnet, gateway, range, options)
- **Renamed-port preservation** — RouterOS lets operators rename
  `ether2` to "Access Point" etc.; Netcanon preserves the renamed
  name + the factory `default-name` so render emits
  `set [ find default-name=ether2 ] ...` lookup syntax (intra-vendor
  round-trip preservation; not a cross-vendor translation surface)
- Wireless config — `/interface wireless` (parse-tolerant; carry-
  through for cross-vendor scenarios where wireless isn't shared)

## L3 redundancy: VRRP (no anycast)

**New in v0.2.0** (Wave B — classic VRRP wire-up).

RouterOS models VRRP as a top-level pseudo-interface declared in
`/interface vrrp`, with the virtual IP bound via a separate
`/ip address` line that references the synthetic pseudo-name.  The
codec does a two-stage cross-reference: parse walks both sections
and stitches the VIP onto the parent interface; render emits the
two-stage structure with a deterministic `vrrp<vrid>` pseudo-name.

### Grammar

```text
/interface vrrp
add interface=ether1 name=vrrp10 vrid=10 priority=110 \
    preemption-mode=yes interval=3s \
    authentication=ah password=hmackey
/ip address
add address=10.0.10.254/24 interface=vrrp10
```

Keywords handled (on `/interface vrrp add ...`): `interface=` (the
parent — the group lands here, NOT on the pseudo-name), `vrid`,
`priority`, `preemption-mode=yes|no`, `interval=Ns` (the trailing
`s` time-unit suffix is stripped), `v3-protocol=ipv4|ipv6` (an IPv6
discriminator — when `ipv6`, the cross-referenced `/ipv6 address`
populates `virtual_ipv6s`), `authentication=simple|ah` +
`password=<token>` (merged into `<scheme>:<token>` canonical form).

The pseudo-name (`vrrp10`) is NOT materialised as a
`CanonicalInterface` — the v0.2.0 schema models the group as a
property of the parent.  Pre-walk ordering is tolerant: `/ip address`
can appear BEFORE `/interface vrrp` in the source.

### Known limitations

- **No description / track surface.**  RouterOS `/interface vrrp`
  has no description field and no native interface-track grammar
  (priority adjustments come from `on-master` / `on-backup` scripts).
  Canonical `description` and `track_interfaces` round-trip empty
  when RouterOS is the target.
- **`on-master` / `on-backup` scripts are Tier-3** and drop with
  a review comment.
- **No anycast-gateway grammar.**  All three anycast canonical
  paths (`virtual-gateway-address` v4/v6, `anycast-gateway-mac`)
  are declared `unsupported` — RouterOS targets a SOHO / SMB
  router niche without fabric-anycast primitives.
- **HSRP / CARP / anycast modes** on incoming canonical records
  (e.g. cross-vendor migration FROM an Arista VARP or OPNsense
  CARP source) surface as `# review:` comments on render instead of
  silently dropping.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model; see `02-per-vendor-grammar.md` §
  "MikroTik RouterOS" for the pseudo-interface cross-reference
  pattern.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (RouterOS out of scope; SOHO/SMB
  platform without fabric grammar).

## Lossy paths

- **`/queue tree`** — QoS queue tree carry-through; cross-vendor QoS
  translation doesn't share semantics, so this drops on cross-
  vendor render (intra-MikroTik round-trip preserves it).
- See per-codec `CapabilityMatrix.lossy` declarations.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall** — `/ip firewall filter`, `/ip firewall mangle`,
  `/ip firewall raw`
- **NAT** — `/ip firewall nat`
- **VPN** — `/ip ipsec`, `/interface ovpn-server`,
  `/interface l2tp-server`, `/interface sstp-server`,
  `/interface wireguard`
- **QoS** — `/queue simple`, `/queue tree` (carry-through only;
  not translated across vendors)
- **Routing protocols** — `/routing bgp`, `/routing ospf`,
  `/routing rip`
- **MPLS** — `/mpls`
- **PKI** — `/certificate`

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`ntc_ip_address_export.rsc`** — RouterOS 6.48.6 `/export verbose`
  snippet from the networktocode/ntc-templates corpus (Apache-2.0)
- **`routeros_diff_verbose_export.rsc`** — RouterOS 6.48.1
  `/export verbose` from RB952Ui-5ac2nD home router ("Quinta
  Router") with bridge / VLAN (gn-mgmt) / DHCP / queue tree
  (MIT, adamcharnock/routeros-diff)
- **`taqavi_initial_provisioning.rsc`** — provisioning script
  (not a `/export` capture — a script an admin runs to provision
  an L009UiGS-2HaxD), bridge port + ip service + DHCP +
  WireGuard + firewall (MIT)
- **`user_contrib_crs310_ros7.rsc`** — operator-contributed
  CRS310-8G+2S+ on RouterOS 7.18.2 (630 lines; renamed
  ethernet-port fleet "Desktop" / "Access Point" / "CLUSTER -
  PVE3/5/NAS" / "PROD - PVE3/5/NAS" / "UPLINKSFP", 5 VLANs
  cluster/IOT/mgmt/server/user, BGP template stub, IPv6 ND,
  l2tp-server, sstp-server, MPLS, system clock + leds + watchdog)

Spans RouterOS 6.48.1, 6.48.6, and 7.18.2 — three OS versions.

## Common gotchas

- **Renamed ports** — operators commonly rename `ether2` to
  meaningful names like "Access Point" or "PROD - PVE3"; the
  parser captures both `name` and `default-name`, and the renderer
  emits `set [ find default-name=X ] ...` lookup syntax so the
  config remains valid even if port enumeration changes between
  device replacements.
- **6.x vs 7.x grammar drift** — RouterOS 7 reorganises some
  sections (`/snmp` vs `/snmp community`, `/routing/bgp/instance`
  vs `/routing bgp instance`); the parser handles both.
- **Bridge port + VLAN mapping** — RouterOS has a different
  data model from switch-vendor switches; the codec normalises
  via VLAN-centric projection so cross-vendor port-list
  semantics work.
- **Backup-side**: definition YAML lives at
  [`../../definitions/mikrotik/`](../../definitions/mikrotik/);
  uses `cisco_more_paging: false`.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
