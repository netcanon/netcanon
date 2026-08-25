# FortiGate FortiOS CLI -> Cisco NX-OS: measured canonical surface

Source of truth for this note is **this repository**, not a vendor page:

* `netcanon/migration/codecs/fortigate_cli/codec.py` and
  `netcanon/migration/codecs/cisco_nxos/codec.py` — each codec's
  `CapabilityMatrix` (`supported` / `lossy` / `unsupported` xpaths),
* the render / re-parse code that produces the observed behaviour
  (`netcanon/migration/codecs/cisco_nxos/render.py`,
  `netcanon/migration/codecs/cisco_nxos/parse.py`), and
* a full in-process `tools/run_full_mesh.py` pass over the committed fixture
  corpus, filtered to the `(fortigate_cli, cisco_nxos)` cells.

Retrieved: 2026-08-20.

The pair is a firewall-to-switch demotion: a FortiGate edge/branch appliance
replaced by (or folded into) a Nexus 9000 doing pure L2/L3. The FortiGate
codec declares `device_classes = [firewall]`, NX-OS `[switch, router]`, so the
shared canonical surface is deliberately narrow — system services, interface
identity + addressing, VLANs and static routes. FortiGate's product surface
(policy, NAT, VIP, VPN, IPsec, UTM, VDOMs) is Tier 3 and never enters
canonical at all, so it is invisible to this measurement rather than
"preserved".

## Corpus

4 fixture cells; **0 render errors, 0 re-parse errors**.

| cell |
|---|
| `tests/fixtures/real/fortigate/kevinguenay_fgt_70g_branch.conf` |
| `tests/fixtures/real/fortigate/kevinguenay_fgt_vm_hub.conf` |
| `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf` |
| `tests/fixtures/synthetic/fortigate_cli/kitchen_sink.conf` |

## Per-field measurement (4 cells)

`trivial` = both sides carried no data on the field, so the cell could not
test any disposition.

| field | preserved | drifted | trivial | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 4 | 0 | 0 | — |
| `domain` | 1 | 0 | 3 | — |
| `dns_servers` | 4 | 0 | 0 | — |
| `ntp_servers` | 1 | 0 | 3 | — |
| `timezone` | 0 | 0 | 4 | — (never populated) |
| `syslog_servers` | 0 | 0 | 4 | — (never populated) |
| `interfaces` | 0 | 4 | 0 | `interface_type`, `lag_member_of`, `dhcp_client_v6`, `name` |
| `vlans` | 3 | 0 | 1 | — |
| `static_routes` | 1 | 2 | 1 | `interface`, `metric` |
| `dhcp_servers` | 0 | 4 | 0 | whole record — all pools dropped |
| `snmp` | 1 | 1 | 2 | `v3_users` |
| `lags` | 0 | 4 | 0 | whole record on 3 cells, `name` on 1 |
| `local_users` | 0 | 4 | 0 | whole record — every account dropped |
| `radius_servers` | 0 | 2 | 2 | whole record — all servers dropped |
| `vxlan_vnis` | 0 | 0 | 4 | — (never populated) |
| `evpn_type5_routes` | 0 | 0 | 4 | — (never populated) |
| `routing_instances` | 0 | 0 | 4 | — (never populated) |
| `raw_sections` | 0 | 0 | 4 | — (never populated) |
| `apply_groups` | 0 | 0 | 4 | — (Junos-only) |
| `group_content` | 0 | 0 | 4 | — (Junos-only) |
| `anycast_gateway_mac` | 0 | 0 | 4 | — (never populated) |

## Sub-field drift — the authoritative list

These are the ONLY sub-fields that drift anywhere in the pair. Every other
sub-field of the same parent is preserved on every cell where it carries
data, which is why the expectation YAML omits the parent key for
`interfaces` / `vlans` / `static_routes` / `snmp` and declares `good` per
sub-field.

| sub-field | cells | drift |
|---|---|---|
| `interfaces[].interface_type` | all 4 | every record -> `ianaift:other` |
| `interfaces[].lag_member_of` | 3 | `fortilink` / `LAG_INTERNAL` / `lacp trunk` -> `null`; `agg<N>` -> `port-channel<N>` |
| `interfaces[].dhcp_client_v6` | 1 | `dhcp6` -> `""` on `wan1` / `wan2` |
| `interfaces[].name` | 1 | `lacp trunk` -> `lacp` |
| `static_routes[].interface` | 2 | `""` -> `"254"` |
| `static_routes[].metric` | 2 | `254` -> `0` |
| `snmp.v3_users` | 1 | 2 users -> `[]` |
| `lags` (whole record) | 3 | all bundles dropped |
| `lags[].name` | 1 | `agg<N>` -> `port-channel<N>` |
| `local_users` (whole record) | 4 | all accounts dropped (1, 1, 3, 3) |
| `radius_servers` (whole record) | 2 | all servers dropped (1, 2) |
| `dhcp_servers` (whole record) | 4 | all pools dropped (1, 1, 6, 2) |

## Notes grounding the dispositions

### `local_users` and `snmp.v3_users` — one root cause, two vanished tables

The largest operator-visible loss on this pair, and the reason both are
`unsupported` rather than `lossy`: the record does not survive at all.

FortiOS stores every credential as a two-token opaque value —
`ENC <base64-blob>` — which the FortiGate parser carries into canonical with a
vendor tag, shape `fortios:ENC <opaque-blob>`. The NX-OS renderer splices that
value verbatim into grammars that accept a **single** token for the secret:

* `_render_local_user` emits
  `username <name> password 0 fortios:ENC <opaque-blob> role <role>`, while
  `_USERNAME_RE` in `netcanon/migration/codecs/cisco_nxos/parse.py` is
  `^username\s+(\S+)\s+password\s+(\d+)\s+(\S+)\s+role\s+(\S+)`. The space
  inside the credential breaks the match, so the line is not a user on
  re-parse — and would be rejected by a real Nexus for the same reason.
* `_render_snmp` emits
  `snmp-server user <name> auth <proto> ENC <opaque-blob> priv <cipher> ENC <opaque-blob> localizedkey`,
  which the NX-OS `snmp-server user` grammar cannot read either.

Measured: `local_users` goes 1 -> 0, 1 -> 0, 3 -> 0 and 3 -> 0 across the four
cells (every account on every cell). `snmp.v3_users` goes 2 -> 0 on
`kitchen_sink`, the only cell that carries v3 users; `user_contrib_fg100e`
carries none, which is why the field also shows one `preserved` cell.

Note the asymmetry inside SNMP: the v1/v2c surface (`community`, `location`,
`contact`, `trap_hosts`) round-trips on every populated cell. Only the v3 USM
table disappears.

Operator consequence: the migrated NX-OS config contains **no usable local
account and no SNMPv3 user**. Combined with the `radius_servers` drop below,
a device built from this render has no working authentication at all — create
a console/local admin on the target before cutover, and re-key every SNMPv3
user by hand.

Nothing in this note reproduces a credential value; only the
`fortios:ENC <opaque-blob>` shape.

### `radius_servers` — no AAA render at all

The NX-OS matrix declares BOTH `/radius-servers/server/host` and
`/radius-servers/server/key` **unsupported** ("Render emits no AAA
radius-server config"). Measured accordingly: "all 1 radius_servers dropped"
on `user_contrib_fg100e` and "all 2 radius_servers dropped" on
`kitchen_sink`. Host, auth/acct ports and the shared secret all go together.
The other two cells carry no RADIUS server.

### `dhcp_servers` — the record cannot be represented

The NX-OS matrix declares `/dhcp-servers/pool` **unsupported** ("Render emits
no DHCP server pool; intent.dhcp_servers are dropped on migration"). Measured
on all four cells: 1, 1, 6 and 2 pools in, zero out. Scope, range, gateway,
lease time and per-pool DNS all vanish together, which is why this is
`unsupported`, not `lossy`. FortiGate branch configs lean on the appliance for
DHCP, so this is usually a service that has to move somewhere else entirely,
not a stanza to re-type.

### `lags` — the bundle exists only if its NAME ends in a digit

Kept as a whole-record disposition because on 3 of 4 cells the record does not
survive at all, and the surviving case is a rename.

NX-OS has no standalone bundle stanza in this renderer: a LAG exists on the
target purely as a `channel-group <N> mode <mode>` line inside each member
interface, and `<N>` is scraped from a **trailing integer** in
`CanonicalInterface.lag_member_of`
(`re.search(r"(\d+)\s*$", iface.lag_member_of)` in `render.py`). So:

* `fortilink`, `LAG_INTERNAL`, `lacp trunk` — no trailing integer, no
  `channel-group` line is emitted, and the bundle plus its whole member list
  disappears (measured "all 2 lags dropped", "all 1 lags dropped", "all 2 lags
  dropped").
* `agg1` / `agg2` on `kitchen_sink` — members emit `channel-group 1 mode
  active` / `channel-group 2 mode passive`, and the NX-OS re-parse synthesises
  `port-channel1` / `port-channel2` with the right members and LACP modes.
  Only the name drifts.

A LAG with no members can never render either, because the bundle has no
carrier of its own (`kevinguenay_fgt_vm_hub`'s `fortilink` has an empty member
list).

`lossy` rather than `unsupported` precisely because of the `agg<N>` case: the
target models link aggregation fully and reproduces it correctly when the name
is number-suffixed. Renaming FortiGate aggregates to `agg<N>` /
`port-channel<N>` before migrating (or via the orchestrator's LAG-rename pane)
converts this loss into a rename.

### `interfaces[].interface_type` — every record collapses to `ianaift:other`

Not confined to one management port the way it is on switch-to-switch pairs:
all 21 / 19 / 33 / 11 interface records drift on the four cells. NX-OS infers
the IANA ifType from the interface NAME prefix (`Ethernet`, `loopback`,
`Vlan`, `port-channel`, `nve`, `mgmt`), and no FortiGate name — `port1`,
`wan1`, `dmz`, `LO_BGP`, `cluster-vlan`, `agg1` — matches any of them, so
every record lands on the catch-all. Source types lost this way include
`ianaift:ethernetCsmacd`, `ianaift:ieee8023adLag` and `ianaift:l3ipvlan`.

Cosmetic in the sense that the interface, its addressing, its description and
its admin state all survive; consequential in the sense that anything
downstream that branches on `interface_type` (LAG detection, SVI detection)
cannot do so on the target until the ports are renamed to NX-OS shapes.

### `interfaces[].name` — a name with a space is truncated

`user_contrib_fg100e` carries an aggregate interface literally named
`lacp trunk`. NX-OS emits `interface lacp trunk` and re-parses the first token
only, yielding `lacp`. FortiOS allows spaces in interface names; NX-OS does
not. Any FortiGate interface whose name contains whitespace loses everything
after the first space, and any config keyed on the full name (including the
matching LAG entry) stops resolving.

### `static_routes[].interface` / `[].metric` — the distance lands in the wrong field

`kevinguenay_fgt_70g_branch` and `kevinguenay_fgt_vm_hub` each carry a
gateway-less static route with `metric=254` (FortiOS `set distance 254`, a
floating/backup route). The NX-OS render emits destination + next-hop +
metric; with an empty gateway the trailing metric token lands in the next-hop
position, and the re-parse reads it back as an outgoing INTERFACE
(`interface: "" -> "254"`) while the metric resets to its default
(`metric: 254 -> 0`).

Operator consequence: a route that was deliberately de-preferenced comes back
at default distance, pointing at a non-existent interface named `254`. Routes
that carry a real next-hop are unaffected — `destination` preserves on every
populated cell and `gateway` preserves wherever it is set.

### `interfaces[].dhcp_client_v6` — IPv6 DHCP client is dropped

`kevinguenay_fgt_70g_branch` has `wan1` and `wan2` on FortiOS
`set ip6-mode dhcp` (canonical `dhcp_client_v6="dhcp6"`); the NX-OS render
carries no IPv6 DHCP-client form and the field comes back empty. The IPv4
`dhcp_client` flag round-trips on all four cells, so this is specifically the
v6 half.

### Fields declared from the matrices because no fixture exercises them

Stated so the basis is explicit rather than implied:

* `timezone` — BOTH matrices declare `/system/timezone` unsupported with the
  same reason ("Render emits no clock/timezone stanza; intent.timezone is
  dropped on migration"). Never populated on this pair.
* `interfaces[].voice_vlan` — declared unsupported by BOTH matrices; the NX-OS
  render drops it (blind-audit `65f9c01` #11).
* `interfaces[].tunnel_type` — NX-OS declares `/interfaces/interface/tunnel-type`
  lossy: `gre` / `ipip` round-trip via `tunnel mode gre ip` / `tunnel mode
  ipip`, while `ipsec` / `vxlan` / `eoip` have no NX-OS interface-encap
  equivalent and drop. Relevant on this pair in principle — FortiGate edges
  terminate IPsec — but no committed fixture populates it.
* `interfaces[].vrrp_groups` — the FortiGate matrix declares
  `/interfaces/interface/vrrp-groups/group` supported; the NX-OS matrix
  declares it lossy, because every `CanonicalVRRPGroup` renders as an `hsrp`
  block regardless of the source `mode`, and the advertisement interval, IPv6
  virtual addresses and group description are dropped with it. No fixture on
  this pair carries a VRRP group.
* `vlans[].description` — declared lossy by both matrices (the NX-OS render
  emits the VLAN name but no separate description line). Not populated here.

### Fields that are `not_applicable` — the SOURCE never populates them

These are source-side absences, not target gaps. The NX-OS target supports
several of them outright, so closing the FortiGate parse side would move the
row to `good` or `lossy` rather than leave it here.

* `syslog_servers` — the FortiGate matrix declares `/system/syslog-server`
  **unsupported**; NX-OS declares it supported.
* `interfaces[].switchport_mode`, `[].access_vlan`, `[].dot1q_vlan`,
  `[].trunk_allowed_vlans`, `[].trunk_native_vlan` — all declared unsupported
  by the FortiGate matrix (it is an L3-only firewall codec; VLAN membership is
  carried by the child interface's parent, not by switchport state). NX-OS
  declares every one of them supported, so the operator must build switchport
  state on the target from scratch.
* `interfaces[].vrf` — the FortiGate matrix declares no
  `/interfaces/interface/config/vrf` path at all; FortiOS `set vrf <id>` is not
  parsed into canonical, so nothing reaches the NX-OS `vrf member` render.
* `vlans[].tagged_ports` / `[].untagged_ports` — declared unsupported by the
  FortiGate matrix, supported by NX-OS.
* `vlans[].ipv4_addresses` — FortiGate mounts a VLAN's L3 addressing on the
  child INTERFACE record (measured: the `cluster-vlan` interface carries the
  address), never on the VLAN record, so the SVI-on-VLAN shape is never
  populated on this direction.
* `static_routes[].description` — not present in the FortiGate matrix at all;
  the FortiOS `set comment` is not parsed into canonical.
* `static_routes[].vrf` — declared unsupported by the FortiGate matrix.
* `vxlan_vnis`, `evpn_type5_routes`, `routing_instances`,
  `anycast_gateway_mac` — declared unsupported by the FortiGate matrix (no
  fabric data plane, no named-VRF model). NX-OS supports all of them; they
  simply receive no source data.
* `raw_sections` — Tier 3 by design, never auto-rendered, and not populated on
  this pair.
* `apply_groups` / `group_content` — Junos-only concepts.

### Declared `good` DESPITE a matrix-declared loss, because nothing drifted

The measurement outranks the matrix here — declaring these lossy would claim a
loss the corpus never exhibits:

* `interfaces[].description` — the FortiGate matrix declares
  `/interfaces/interface/config/description` lossy (the FortiOS 25-character
  alias), but descriptions preserve on all 4 cells.
* `interfaces[].ipv4_addresses` — preserved on all 4 cells, including the
  `/32` loopback and SVI-style addresses.
* `static_routes[].destination` / `[].gateway` — preserved on every populated
  cell; the dotted-mask -> CIDR conversion round-trips.
* `snmp.community` / `.location` / `.contact` / `.trap_hosts` — preserved on
  both populated cells even though the NX-OS matrix declares the v3
  passphrases and engine-id lossy; those declarations bite `v3_users`, not the
  v1/v2c surface.
* `domain` — the FortiGate matrix declares no `/system/domain` path, yet the
  codec populates it and it preserves on the one cell that carries it.
