# NetConfig Capabilities + Known Limitations

NetConfig is a multi-vendor network device configuration translator
with two co-hosted concerns:

1. **Backup** — pull `running-config` (or vendor equivalent) from
   devices over SSH / NETCONF / REST and store in
   `configs/<host>.<ext>`.
2. **Migration** — translate a stored backup from one vendor's native
   config grammar into another, via a shared canonical intent tree.

This document is the operator-facing source of truth for **what the
program does and does not do**.  Internal architecture lives in
[`../ARCHITECTURE.md`](../ARCHITECTURE.md); contributor rules live in
[`../CLAUDE.md`](../CLAUDE.md).  Per-codec live certification status
lives in [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md).

---

## Supported vendors

Eight migration codecs ship today, plus a `_mock` adapter used in
tests.  Backup-side device definitions are listed under
[`../definitions/`](../definitions/) (one YAML per vendor/OS family).

| Codec | Vendor | Wire format | Direction | Certainty |
|---|---|---|---|---|
| `cisco_iosxe_cli` | Cisco IOS-XE | `show running-config` text | bidirectional | certified |
| `cisco_iosxe`     | Cisco IOS-XE | NETCONF / OpenConfig XML  | bidirectional | best_effort (Phase 0.5 stub render) |
| `arista_eos`      | Arista EOS    | EOS CLI text              | bidirectional | certified |
| `aruba_aoss`      | Aruba AOS-S   | AOS-S CLI banner + positional port lists | bidirectional | certified |
| `juniper_junos`   | Juniper Junos | `set`-form CLI            | bidirectional | certified |
| `fortigate_cli`   | Fortinet FortiGate | nested `config / edit / set / next / end` CLI | bidirectional | certified |
| `mikrotik_routeros` | MikroTik RouterOS | `/path` slash-prefixed CLI export | bidirectional | certified |
| `opnsense`        | OPNsense      | `config.xml`              | bidirectional | certified |

Backup-side device-definition YAMLs ship for the same vendor families
plus per-OS-version overlays.  See
[`../definitions/README.md`](../definitions/README.md) for the
authoring guide and the live `/definitions` page in the running app
for the per-vendor inventory.  RESULTS.md is the source of truth for
current certification — this table summarises but does not gate.

---

## Translation tiers

The canonical intent model classifies every field by semantic
stability across vendors.  This drives both the validation report and
the UI's notification banners.

### Tier 1 — auto-translatable (cross-vendor stable)

Fully modelled; every shipped bidirectional codec parses and renders:

* `hostname`, `domain`
* `interfaces` — `name`, `description`, `enabled`, IPv4 + IPv6
  addresses, `vrf` binding, `kind` (physical / mgmt / loopback /
  uplink), `mtu`, `lag_member_of`
* `vlans` — `id`, `name`, `tagged_ports`, `untagged_ports`, SVI L3
  (via VLAN-centric projection)
* `static_routes`
* `dns_servers`, `ntp_servers`, `syslog_servers`, `timezone`

### Tier 2 — translatable with caveats

Modelled and wired across most codecs; cross-vendor mappings can be
lossy where vendors disagree on representation.

* `snmp` — community, contact, location, trap-host, plus SNMPv3 USM
  users (auth/priv/group/engine — see per-codec notes below)
* `lags` — name, mode (LACP / static), members; vendor-native names
  reconciled via the LAG name-equivalence helper (`Po1` /
  `Port-channel1` / `ae1` / `trk1` are recognised as the same bundle)
* `local_users` — name, privilege, role, hashed_password.  Hashes
  that the target's CLI cannot consume surface as comment-form
  review lines (see "Hash-portability policy" below) — **never** as
  a plaintext fallback
* `radius_servers`
* `dhcp_servers` (per-pool — network, gateway, range, options)
* `vxlan_vnis`, `evpn_type5_routes` (ship-before-wire — schema
  shipped ahead of wire-up; declared `unsupported` on each codec
  until the per-vendor wiring lands)
* `routing_instances` + per-interface `vrf` (cross-vendor VRF
  primitive — same ship-before-wire pattern)
* `apply_groups` + `group_content` (Junos-specific; preserved
  byte-for-byte through round-trip)

### Tier 3 — opaque carry / not auto-rendered

These are present in source devices but **never auto-translated**.
The codec parsers deliberately drop them; the
[`_tier3_detection.py`](../netconfig/migration/_tier3_detection.py)
heuristic surfaces what was dropped via the migrate page banner so
operators see the gap.

* `firewall_rules` — vendor-specific stateful policy; cross-vendor
  semantics don't translate cleanly (zone-pair vs interface ACL vs
  table-driven rule sets)
* `nat_rules` — tightly coupled to interface zone designations
* `vpn` — IPsec / SSL-VPN / WireGuard / OpenVPN; key material and
  peer-specific knobs aren't safely auto-portable
* `routing_protocols` — BGP / OSPF / EIGRP / IS-IS;
  protocol-internal state belongs to the operator, not the
  translator
* QoS — class-maps / policy-maps / shapers / queues
* PKI / crypto — certificate chains, IKE policies, key blobs
* Route-maps / policy-statements / prefix-lists

This is an architectural decision, not a backlog item.  See the
"Architectural decision (Cluster E.X deferred)" entry in
[`../CHANGELOG.md`](../CHANGELOG.md) for the rationale.

---

## Notification mechanisms operators see

The UI surfaces every place the translator can't faithfully cross
the vendor boundary.  Each surface is named so operators can grep
the rendered output or screen-grab the panel.

### A. Capability matrix "Unsupported" / "Lossy" panels

The migrate page renders three lists under **Validation details**:
Supported / Lossy / Unsupported.  Each codec declares its own matrix
in `netconfig/migration/codecs/<vendor>/codec.py`.  The table below
enumerates every `UnsupportedPath` and `LossyPath` declared today.

#### `cisco_iosxe_cli` (Cisco IOS-XE CLI, bidirectional)

| Path | Class | Reason summary |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | CLI parser infers IANA type from name prefix (GigabitEthernet → ethernetCsmacd, Loopback → softwareLoopback) but cannot detect all IANA types. |
| `/evpn-type5-routes/route` | Lossy | Per-prefix EVPN Type-5 records are a VRF property; no codec populates them today (lossy-by-default extension point). |
| `/interfaces/interface/subinterfaces/subinterface/ipv6` | Unsupported | Phase 0.5 scope — IPv4 only. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | IOS-XE VXLAN (`interface nve1 / member vni …`) parse-and-ignore in v1; wire-up deferred until Catalyst-to-Arista migration demand arrives. |
| `/routing-instances/instance` | Unsupported | VRF declarations and `vrf forwarding <name>` parse-and-ignore in v1; canonical schema exists; IOS-XE wire-up deferred. |
| `/access-list/{extended,standard,ipv6}` | Unsupported | Tier 3 — auto-translating ACL semantics across vendors risks shipping subtly-permissive rules. |
| `/firewall` | Unsupported | Zone-based firewall (zone-pair / policy-map type inspect) is Tier 3. |
| `/nat` | Unsupported | NAT is Tier 3 — semantics are tightly coupled to interface zone designations. |

#### `cisco_iosxe` (NETCONF / OpenConfig, bidirectional Phase 0.5 stub)

This codec is an experimental stub — its `_render_canonical()`
emits **only the `openconfig-interfaces` subtree**.  Every other
canonical surface is declared `unsupported` so the cross-mesh audit
matrix flags the gap honestly rather than masquerading as drift.

| Path (granular) | Class |
|---|---|
| `/interfaces/interface/config/mtu` | Lossy (YANG MTU drops platform-specific IP-vs-link distinction) |
| `/system/{hostname,dns-server,ntp-server}` | Unsupported |
| `/vlans/vlan/{id,name}` | Unsupported |
| `/routing/static-route` | Unsupported |
| `/snmp/{community,location,contact,trap-host,v3-user}` | Unsupported |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported |
| `/routing-instances/instance` | Unsupported |
| `/evpn-type5/route` | Unsupported |
| `/access-list`, `/firewall` | Unsupported (Tier 3) |

Top-level field markers (`/hostname`, `/domain`, `/dns_servers`,
`/ntp_servers`, `/timezone`, `/syslog_servers`, `/vlans`,
`/static_routes`, `/snmp`, `/lags`, `/local_users`, `/radius_servers`,
`/dhcp_servers`, `/routing_instances`, `/vxlan_vnis`,
`/evpn_type5_routes`) are also declared unsupported so the cross-mesh
audit's `f"/{field}"` shape match flips correctly.  Operators
selecting this codec as a target should expect interfaces-only
output.

#### `arista_eos` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | EOS interface names don't encode speed; parser defaults `Ethernet<N>` to a `gig` speed-hint and target codecs that care about speed (e.g. Cisco's GigabitEthernet vs TenGigabitEthernet distinction) may emit less-specific prefixes. |
| `/evpn-type5-routes/route` | Lossy | Per-prefix records are a lossy-by-default extension point — no codec populates them today (would require route-map / policy-statement parsing). |
| `/routing/bgp` | Unsupported | BGP neighbour tables / redistribution / address-families parse-and-ignore in v1. |
| `/routing/ospf` | Unsupported | OSPF areas / redistribution / per-interface cost tuning parse-and-ignore in v1. |
| `/access-list/{extended,standard,ipv6}` | Unsupported | Tier 3 — auto-translating ACL semantics across vendors risks shipping subtly-permissive rules. |

#### `aruba_aoss` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | AOS-S does not declare IANA `ifType`; codec infers type from interface-name shape (bare number → ethernet, `Trk` → port-channel, `Vlan` → l3ipvlan). |
| `/filter/rule` | Unsupported | AOS-S access-lists are Tier 3 (informational) and not yet auto-rendered. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | VXLAN not modelled — AOS-S is a campus L2/L3 codec. |

#### `juniper_junos` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/subinterfaces/subinterface` | Lossy | Unit 0 collapses into the parent; units 1+ materialise as distinct `<parent>.<unit>` interfaces, but per-unit VLAN tagging (`unit N vlan-id 100`) parses-and-ignores pending a canonical tagged-subinterface model. |
| `/groups` | Lossy | Apply-groups inheritance is wired for the dispatch surface (system / login / interfaces / protocols / SNMP / routing-options / routing-instances / vlans); group bodies for unsupported surfaces (policy-options, firewall filters, RADIUS server options) parse-and-ignore. |
| `/evpn-type5-routes/route` | Lossy | Per-prefix records lossy-by-default — VRF-property model uses `CanonicalRoutingInstance.l3_vni`; explicit per-prefix lists not populated by any codec today. |
| `/routing/bgp` | Unsupported | BGP / IS-IS / OSPF / MPLS stanzas parse-and-ignore in v1; Junos routing-options grammar warrants a dedicated follow-up. |
| `/firewall/filter` | Unsupported | Junos firewall filters (family / term / from / then) are Tier 3 — distinct from ACL models in other codecs. |

#### `fortigate_cli` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/description` | Lossy | FortiOS limits the interface alias to 25 characters; longer descriptions from other vendors are truncated. |
| `/interfaces/interface/config/type` | Lossy | FortiOS has no IANA `ifType`; inferred from `type vlan` sub-setting or name shape. |
| `/filter/rule` | Unsupported | `config firewall policy` is Tier 3 — session-based, zone-aware, UTM-enabled semantics don't translate cleanly. |
| `/nat/rule` | Unsupported | FortiGate NAT lives inside firewall policy and address / VIP objects — not auto-translatable. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | VXLAN not modelled — FortiGate is a firewall codec. |

#### `mikrotik_routeros` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/type` | Lossy | RouterOS does not expose IANA `ifType`; codec infers it from interface-name prefix (`etherN` → ethernetCsmacd, `vlanN` → l3ipvlan). |
| `/vlans/vlan/name` | Lossy | MikroTik stores a VLAN's name as the L3 interface name (e.g. `vlan10`), not a separate descriptive name field; cross-vendor rendering may conflate the two. |
| `/filter/rule` | Unsupported | Firewall filter rules are Tier 3 (informational) and not auto-rendered. |
| `/nat/rule` | Unsupported | NAT rules are Tier 3 — informational only. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | RouterOS VXLAN exists but is rare in canonical scope and not modelled in v1. |

#### `opnsense` (bidirectional)

| Path | Class | Reason |
|---|---|---|
| `/interfaces/interface/config/description` | Lossy | OPNsense imposes no length limit on description text; other vendors (Cisco 240 chars, Juniper 900) may truncate on render. |
| `/filter/rule` | Unsupported | `<filter>` is Tier 3. |
| `/nat/outbound` | Unsupported | `<nat>` is Tier 3. |
| `/snmp/v3-user` | Unsupported | OPNsense's SNMPv3 lives in raw `snmpd.conf` — Tier 3. |
| `/vxlan-vnis/{vni,source-interface,udp-port}` | Unsupported | VXLAN not modelled — OPNsense is a firewall codec. |

### B. Tier-3 sections detected banner

When a source codec parses a config that contains stanzas it
deliberately drops (firewall, NAT, QoS, route-maps, IPsec, etc.),
the parser's per-vendor heuristic detector populates
`CanonicalIntent.dropped_tier3_sections` with the matching
stanza headers.  The migrate page renders these as a warning banner:

> ⚠ Tier-3 sections detected in source — The source config contains
> N section(s) this tool does not translate (firewall rules, NAT,
> QoS, route-maps, IPsec, etc.).  These will NOT appear in the
> rendered output.  Operator must apply them manually on the target
> device.

Per-vendor detection patterns
([`netconfig/migration/_tier3_detection.py`](../netconfig/migration/_tier3_detection.py)):

| Source codec | Patterns matched (excerpt) |
|---|---|
| `cisco_iosxe_cli` / `arista_eos` / `aruba_aoss` (IOS-style CLI heuristic) | `ip access-list extended/standard <name>`, `ipv6 access-list <name>`, numbered `access-list N permit/deny`, `ip nat inside/outside/pool`, `class-map`, `policy-map`, `route-map <name>`, `crypto isakmp/ipsec/map/pki`, `zone-pair security` |
| `juniper_junos` (set form) | `set firewall [family X] filter <name>`, `set security {policies\|nat\|ike\|ipsec\|zones\|address-book\|flow\|screen\|alg\|utm\|application-tracking\|forwarding-options}`, `set policy-options {policy-statement\|prefix-list\|community} <name>`, `set class-of-service` |
| `fortigate_cli` | `config firewall {policy\|policy6\|vip\|vip6\|central-snat-map\|address\|addrgrp\|service\|shaper}`, `config vpn {ipsec\|ssl}`, `config {webfilter\|antivirus\|ips\|dlp\|application}`, `config router {policy\|route-map}` |
| `mikrotik_routeros` | `/ip firewall {filter\|nat\|mangle\|raw\|address-list}`, `/ipv6 firewall …`, `/queue`, `/ip ipsec`, `/routing {filter\|bgp\|ospf}` |
| `opnsense` | XML elements: `<filter>`, `<nat>`, `<ipsec>`, `<openvpn>`, `<wireguard>`, `<shaper>`, `<load_balancer>`, `<captiveportal>` |
| `cisco_iosxe` (NETCONF) | No-op (NETCONF input rarely carries Tier-3 stanzas — retained for codec-hook symmetry) |

Detection is intentionally heuristic on stanza headers — not a
parse.  False positives are preferred to false negatives.  The
output is **notification-only**: it never feeds the renderer or any
transform.

### C. Render-time review comments

When a render path can't faithfully emit a piece of canonical
state, it emits a comment in the target's native syntax instead of
guessing or silently dropping.  Operators searching for `review:`
in rendered output find every such site.

* **Hash-portability policy**
  ([`netconfig/migration/_user_secrets.py`](../netconfig/migration/_user_secrets.py)).
  Every render path that emits a local user calls
  `is_migratable(hash, target_vendor)` first; on a miss, it emits a
  vendor-correct comment of the form:

      password manager user-name "X" -- review: <alg> hash from
      source vendor cannot be re-used on <target>; reset this user
      password manually

  Comment delimiter varies by vendor: Aruba uses `;`, Cisco IOS-XE
  CLI / Arista EOS use `!`, Junos / FortiGate / MikroTik use `#`,
  OPNsense uses `<!-- … -->` (with `--` collapsed to `-` per XML
  1.0).  Per-target accepted-algorithm sets live in
  `_TARGET_ACCEPTS`.  A foreign hash NEVER falls back to plaintext
  (that would leak the hash literal as the password — a severe
  security bug).

* **Aruba AOS-S DHCP comment block**
  ([`aruba_aoss/render.py`](../netconfig/migration/codecs/aruba_aoss/render.py)).
  AOS-S is a DHCP-relay platform on most SKUs — it doesn't run a
  DHCP server.  When canonical carries DHCP pools, the renderer
  emits a header comment block:

      ; DHCP pools from source codec are not supported
      ; by AOS-S (AOS-S is a DHCP relay platform, not a
      ; DHCP server).  Reconfigure on a sibling server.

  …followed by one summary comment line per pool.

* **Aruba AOS-S OOBM IPv6**.  AOS-S has documented `oobm` IPv4
  syntax but unverified IPv6 syntax; the renderer emits the IPv6
  address as a comment-form review line rather than guessing.

* **MikroTik IPsec tunnel placeholders**.  When the canonical
  carries an IPsec peer with an empty/placeholder address, the
  renderer emits the line plus `comment="review: tunnel endpoint
  placeholder -- set local-address/remote-address"`.

* **Junos `apply-groups` round-trip**.  Group bodies are emitted
  verbatim before their `apply-groups` reference so the operator
  can audit; cross-vendor renderers do not include them.

* **Foreign port names** (Cisco IOS-XE CLI render path).  When the
  port-rename mesh hands a foreign port name to a target whose
  `classify_port_name` can't place it, the renderer emits
  `! interface <name> -- review: foreign port` rather than
  emitting an interface stanza for an unknown chassis position.

### D. Validation severity (`ok` / `warn` / `block`)

Every `MigrationJob` carries a validation severity computed from the
target's capability matrix vs. the canonical tree's actually-populated
fields.  The migrate page reflects this in the status banner and
`POST /api/v1/migration/plan` returns it on `job.validation`:

* `ok` — every populated canonical leaf maps to a `supported` xpath
  on the target.
* `warn` — at least one leaf hits a `lossy` xpath; render proceeds.
* `block` — at least one leaf hits an `unsupported` xpath; the job's
  status flips to `partial` (rendered output exists but should be
  reviewed before deploy).

Job status reaches `failed` only when a stage actually raises;
validation alone never fails the job.

### E. Compatibility-banner per rename pane

The rename modal (Tier-3 rename) shows an amber banner on a pane
when the active target codec declares that pane's category in
`unsupported_rename_categories`.  Today only the
`cisco_iosxe` (NETCONF) and `opnsense` codecs declare anything —
both list `"snmpv3"` because their SNMPv3 paths are unsupported in
the codec's render layer.  The banner prevents the ghost-success
bug where rename overrides apply to canonical but vanish from
rendered output.

---

## Backup-side limitations

The backup concern is architecturally simpler — connection happens
via SSH (Netmiko) / NETCONF / REST with vendor-specific paging
controls.  Operator-visible failure modes:

* **`422 Unknown type_key(s)`** — `POST /api/v1/backups` validates
  every device's `type_key` against the loaded definitions; unknown
  keys reject with a 422 listing both the offenders and the loaded
  set.
* **`type_key` filename grammar** — definition load-time validator
  in [`netconfig/definitions/schema.py`](../netconfig/definitions/schema.py)
  rejects any `type_key` containing `_` or `.`.  The file-store
  filename grammar is `{type_key}_{safe_host}_{timestamp}.{ext}`
  and underscores or dots inside `type_key` make round-trip
  parsing ambiguous.
* **Connection failures** — surfaced on the per-device row of the
  backup-job result with the exception class name and message.
  Mocking is at one factory: `get_collector` (CLAUDE.md hard rule).
* **Probe non-match** — backup-side code does not auto-detect
  vendors; the operator declares `type_key` per device.  Migration
  has its own auto-detect probe (see
  [`migration_detect.py`](../netconfig/services/migration_detect.py)).
* **Cisco paging** — Cisco devices use SPACE-injection via
  `connection.cisco_more_paging: true` in the YAML definition.
  CLAUDE.md hard rule: never replace this with `terminal length 0`.

---

## Round-trip vs. cross-vendor

Two distinct fidelity surfaces, often confused:

* **Round-trip** — `parse(render(parse(raw))) == parse(raw)` for the
  **same** vendor codec.  The cert harness's primary invariant.
  Per-codec status in
  [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md).
* **Cross-vendor / cross-mesh** — every-source by every-target pass
  through the canonical bridge.  The audit matrix lives at
  [`../tests/fixtures/real/CROSS_MESH_RESULTS.md`](../tests/fixtures/real/CROSS_MESH_RESULTS.md)
  (Phase 1: mechanical drift) and
  [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  (Phase 4: classified into ALIGNED / CODEC_BUG /
  EXPECTED_LOSSY / EXPECTED_UNSUPPORTED / METHODOLOGY_ISSUE_under /
  METHODOLOGY_ISSUE_over / STRUCTURAL_ONLY / TRIVIAL_EMPTY).

A codec can be round-trip clean and still drop fields cross-vendor
(`/snmp/v3-user` is valid SNMPv3 on Cisco CLI source, but the
NETCONF target codec doesn't implement render).  Both numbers
matter; the matrix is honest about both.

---

## Cross-paradigm exceptions

* **`cisco_iosxe` (NETCONF) is a Phase 0.5 stub.**  The render path
  emits ONLY `openconfig-interfaces`.  Its capability matrix
  declares the gap — every non-interface canonical surface is
  `unsupported`.  Operators who need full NETCONF output should use
  the CLI sibling (`cisco_iosxe_cli`) which renders complete config
  text.
* **OPNsense SNMPv3 is Tier 3.**  OPNsense stores SNMPv3 in raw
  `snmpd.conf` snippets, not its config.xml schema; the codec
  declares `/snmp/v3-user` unsupported and lists `"snmpv3"` in
  `unsupported_rename_categories`.
* **MikroTik does not accept foreign hashes.**  RouterOS rehashes
  the supplied password itself, so `_user_secrets._TARGET_ACCEPTS`
  permits only `plaintext` for `mikrotik_routeros`.  Cross-vendor
  hashes always trigger a review comment.
* **Aruba AOS-S as DHCP target.**  AOS-S is a DHCP relay platform
  (`ip helper-address`) — it is not a DHCP server.  Source DHCP
  pools surface as a comment block, not as `dhcp-server pool`
  syntax.

---

## What is auto-tested

The cross-mesh fidelity audit harness
([`tools/run_full_mesh.py`](../tools/run_full_mesh.py),
[`tools/run_phase4_reconciliation.py`](../tools/run_phase4_reconciliation.py))
runs every `(source codec, target codec, fixture)` triple and
classifies per-canonical-field drift.  Outputs commit as
`tests/fixtures/real/CROSS_MESH_RESULTS.md` and
`tests/fixtures/real/PHASE4_RECONCILIATION.md`.  Per-vendor
investigation reports (`phase4_findings_<vendor>.md`) carry the
triage decisions.

The unit-tier real-capture harness
([`tests/unit/migration/test_real_captures.py`](../tests/unit/migration/test_real_captures.py))
asserts three invariants per fixture: parse doesn't crash, parse
populates at least one canonical field, and (for bidirectional
codecs) `canonical(parse(render(parse(raw))))` matches
`canonical(parse(raw))`.

For the live numbers on either matrix, consult the markdown files
named above.  This document deliberately omits hard-coded counts
(per CLAUDE.md hard rule on prose-rot).

---

## What this document is NOT

* It is **not** a roadmap.  See
  [`../translator-plans.txt`](../translator-plans.txt).
* It is **not** a contributor guide.  See
  [`../CLAUDE.md`](../CLAUDE.md).
* It is **not** a security model.  See
  [`../SECURITY.md`](../SECURITY.md).
* It is **not** a per-fixture certification matrix.  See
  [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md).

---

## Reporting issues / feature requests

Bugs and feature requests welcome via the project's issue tracker.
For codec authoring, start at
[`../netconfig/migration/codecs/README.md`](../netconfig/migration/codecs/README.md).

When reporting a translation bug, include:

1. Source codec + target codec.
2. The shortest source snippet that reproduces.
3. Expected vs. actual rendered output.
4. Any review comments / Tier-3 banner contents the UI showed.

---

## See also

- [`../README.md`](../README.md) — quickstart
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — internal four-layer design
- [`../CLAUDE.md`](../CLAUDE.md) — contributor directives
- [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md) — per-codec certification state (live)
- [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md) — cross-mesh audit matrix (live)
- [`./glossary.md`](./glossary.md) — project vocabulary (Tier 1/2/3, TRIVIAL_EMPTY, ship-before-wire, etc.)
