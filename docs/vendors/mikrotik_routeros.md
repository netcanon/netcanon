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
- Interfaces — physical (`ether<N>`, `sfp<N>`, `combo<N>`,
  `sfp-sfpplus<N>`, `sfp28-<N>`, `qsfp28-<N>-<lane>`), bridge
  (`/interface bridge`), VLAN (`/interface vlan` named e.g.
  `gn-mgmt`); IPv4 (`/ip address`), IPv6 (`/ipv6 address`)
- Tunnels — `/interface gre`, `/interface eoip`, `/interface ipip`:
  name, comment and `mtu`.  The endpoints are not translated: they
  come out as `remote-address=0.0.0.0`, for you to fill in.
  ⚠️ Up to 0.7.7 a tunnel's MTU was not written or read.
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

- **A value is written as one string where it holds anything but
  letters, digits and `- . _ / : , %`** — white space, `;`, `$`, a
  bracket, a quote.  RouterOS reads an imported `.rsc` as a script:
  outside a string white space parts two words, `;` ends the command
  and `$` and the brackets substitute a variable or run a command, and
  inside a string `$` still substitutes, so it is escaped there (`\$`),
  as an export escapes it.  ⚠️ Up to 0.7.7 the renderer escaped only
  `\` and `"` and wrote most values bare: a description
  `$[/system reset-configuration]` from any source was that command on
  the router that imported the output, and a value with a space or a
  `;` in it was cut there or ran on as another command.  Read an older
  output for `$`, `;`, `[` and `(` before it reaches a router.  The
  parser reads a string back whole; it reads `\` and the character
  after it as that character, so a hex escape (`\C3\A9`), `\n` or `\_`
  in an export reaches the target as the letters.
- **A user whose password cannot be carried is left out** as a target,
  with a `# ... review:` line in its place.  ⚠️ Up to 0.7.7 the `/user
  add group=... name=...` line stayed without its password, and
  RouterOS gives such a user a blank one; read old outputs for an
  `add` after a `review:` line.
- **A VLAN on a VLAN is one tag on a VLAN interface.**  An
  `/interface vlan` whose `interface=` is another `/interface vlan`
  (Q-in-Q on RouterOS) is read as a VLAN interface of one tag on that
  VLAN interface, not as a sub-interface of two tags.  Onto a target
  that writes tags the job is `partial`; a source's sub-interface of
  two tags (IOS-XE `second-dot1q`, EOS `inner`, Junos `vlan-tags`) has
  no form here, and is `partial` too.
- **VLAN interfaces, bridges and names of your own, onto another
  vendor** — the port translator reads the names RouterOS gives a
  port or a bond (`ether2`, `sfp-sfpplus1`, `bonding1`).  A VLAN
  interface, a named bridge or a port an operator named (`vlan10`,
  `bridge-lan`, `eth3_vlan1`) it does not read, and leaves under
  that name on the target.  With no
  devices declared such a job is `partial` and lists each in
  `untranslated_ports` until an entry of `port_rename_map` gives it
  the target's name — also where the name happens to read as one
  of the target's (`vlan100` onto OS10): a RouterOS name is
  whatever was typed, and `vlan100` may carry VLAN 20.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § D1.
- **Renaming or dropping a VLAN interface in the rename modal is
  not shown by the output.**  A translation from RouterOS to
  RouterOS lists each under *Other names in the config*.  RouterOS
  output writes a VLAN interface from the VLAN itself: renamed, the
  interface is written under the new name — with the number in that
  name as its `vlan-id` — and the old one again; dropped, it comes
  back; and one with a name of its own (`clustervlan100`) can come
  back as `vlan<id>`.  The job records the entry and says nothing.
  Edit the output.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.
- **Renamed ports** — operators commonly rename `ether2` to
  meaningful names like "Access Point" or "PROD - PVE3"; the
  parser captures both `name` and `default-name`, and the renderer
  emits `set [ find default-name=X ] ...` lookup syntax so the
  config remains valid even if port enumeration changes between
  device replacements.  An entry of `port_rename_map` gives a port a
  NAME: `{"ether1": "WAN"}` renders
  `set [ find default-name=ether1 ] name=WAN`, and the port is still
  found by the factory name it had: a `set [ find default-name= ]`
  line's, or the port's own name where that is one a MikroTik device
  gives a port — `etherN`, `sfpN`, `comboN`, `sfp-sfpplusN`, `sfp28-N`, and the
  QSFP lanes `qsfpplusN-L`, `qsfp28-N-L`, `qsfp56-N-L` and
  `qsfp56-dd-N-L`, whole and in lower case, as MikroTik's
  manual and exports show them.  So an SFP port the export mentions
  only in `/ip address` is found too.  A name of yours
  (`ether1_ADMIN`, `Ether1`) is not one, and a port known only by
  such a name, with no `set [ find default-name= ]` line for it, has
  none recorded: naming it renders `set [ find name=WAN ]`, a lookup
  by the new name that matches no port, unless both device models
  are declared (below).  RouterOS names are free text in their own
  letter case, so `SFP-SFPPLUS1` is not read as a port: onto another
  vendor the job lists it as a name the translator could not read.
  The key of an entry is the name the config uses for the port —
  yours, where you gave one; without devices declared an entry keyed
  by the factory name of a port you named matches nothing and is
  ignored with a warning.  Onto another vendor with no devices
  declared, a port you named is translated only by an entry: the
  translator reads a RouterOS port by the shape of its name, a name
  of your own has none, and the port's factory name is not used to
  place it.  The job lists such a port (`untranslated_ports`) and is
  `partial` until an entry decides it.
- **Moving a port onto other hardware needs both device models
  declared** (the *Source device* and *Target device* rows of the
  Interface rename modal; on the API, `source_profile` /
  `target_profile`).  Then every
  port the mapping places that the config has an interface for is
  looked up by the port of the target it is on — also when the config
  came from another vendor, or stated no factory name for the port —
  and a name you gave it is kept, unless that name is itself a port
  of the target; an
  entry whose target is a port of the declared target moves the port
  there, and one whose target is not names it (the plan says so in a
  line).  Nothing else can tell a move from a name: `sfp1` is a port
  of some RouterOS models and not of others.  Onto another vendor a
  port you named takes the name of the port it was paired with.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **A port named like a VLAN, a bridge, a LAG or a loopback**
  (`bond1`, `bridge-uplink`, `vlan10`, `lo0`) gets no Ethernet line
  in the output: the renderer goes by the shape of the name.  With
  both devices declared the plan lists such a port (`unbound_ports`)
  and the job is `partial`; without, nothing is reported.  Give the
  port another name.
- **A port a config from another vendor names only as a LAG member
  or in a route** (an IOS route's interface that no stanza configures)
  has no interface of its own, and so no line of its own in the
  output.  The name the mapping gives it — the target port's — needs
  none.  A name YOU give it in `port_rename_map` is written into
  `slaves=` or `gateway=` and defined nowhere; with both devices
  declared the plan lists a port the mapping PLACED (`unbound_ports`)
  and the job is `partial`.  Give such a port a port of the target,
  not a name.  A port with no place that you keep under a name is
  written the same way, and is said in a line of the plan, not in
  `unbound_ports`.  (A comma parts two names in either list, and an
  `@` or a `%` a next hop, so a name that holds one is pieces there;
  with both devices declared a placed port under such a name is
  listed in `unbound_ports`, whether or not it has a line of its
  own.)
- **`gateway=<interface>` routes** follow the interface when it is
  renamed, and are removed with it when it is dropped.  A list of
  gateways (`gateway=ether1,ether2`) and a routing-table suffix
  (`ether3@main`) are left as written.
- **A VLAN interface's parent** (`/interface vlan add
  interface=bridge name=mgmtvlan11 vlan-id=11`) is kept, and onto
  RouterOS the VLAN is written on it again.  An entry of
  `port_rename_map` for the parent moves its VLANs with it; an entry
  that drops it is said in the job's warnings, and the renderer then
  chooses a parent for the VLAN as below.  Onto FortiOS and OPNsense
  the parent is carried, and a FortiGate VLAN or an OPNsense VLAN
  device comes with its own.  Onto any other vendor it is not — no other codec writes a VLAN interface on a
  parent the config names — and nothing reports it.  From any other
  vendor every VLAN interface of a RouterOS output is on ONE parent
  the renderer chooses: the config's one port with an address or an
  allowed list, or a `bridge1` it adds where there is not exactly
  one.
- **6.x vs 7.x grammar drift** — RouterOS 7 reorganises some
  sections (`/snmp` vs `/snmp community`, `/routing/bgp/instance`
  vs `/routing bgp instance`); the parser handles both.
- **Bridge port + VLAN mapping** — RouterOS has a different
  data model from switch-vendor switches; the codec normalises
  via VLAN-centric projection so cross-vendor port-list
  semantics work.
- **Backup-side**: definition YAML lives at
  [`../../netcanon/definitions/library/mikrotik/`](../../netcanon/definitions/library/mikrotik/);
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
