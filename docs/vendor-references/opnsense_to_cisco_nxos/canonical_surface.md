# OPNsense -> Cisco NX-OS: measured canonical surface

Source: `netcanon/migration/codecs/opnsense/codec.py` and
`netcanon/migration/codecs/cisco_nxos/codec.py` (`CapabilityMatrix`), joined
against a full `tools/run_full_mesh.py` run over the committed corpus.
Retrieved: 2026-08-20

`opnsense` declares the firewall / router device classes; `cisco_nxos`
declares switch / router. The overlap is the ROUTER surface only, so this
pair is narrow by construction: an OPNsense edge box being folded into a
Nexus L3 border-leaf keeps its addressing, routes, VLAN ids, SNMP v1/v2c and
user inventory, and loses everything that is firewall-shaped (DHCP server
pools, RADIUS authentication servers, CARP high-availability semantics,
DHCP / DHCPv6 client uplinks).

8 fixture cells; **0 render errors, 0 re-parse errors**.

## Per-field measurement (8 cells)

| field | preserved | drifted | untested | what drifts |
|---|---:|---:|---:|---|
| `hostname` | 7 | 1 | 0 | empty source name renders as the literal `switch` |
| `domain` | 7 | 0 | 1 | — |
| `dns_servers` | 4 | 0 | 4 | — |
| `ntp_servers` | 0 | 0 | 8 | never populated on the source |
| `timezone` | 0 | 0 | 8 | unsupported both ends |
| `syslog_servers` | 0 | 0 | 8 | never populated on the source |
| `interfaces` | 0 | 8 | 0 | 5 sub-fields — see below; every RECORD survives |
| `vlans` | 2 | 0 | 6 | — |
| `static_routes` | 2 | 1 | 5 | per-route `description` |
| `dhcp_servers` | 0 | 4 | 4 | whole record — every pool dropped |
| `snmp` | 3 | 0 | 5 | — |
| `lags` | 0 | 1 | 7 | `name` (`lagg0` -> `port-channel0`) |
| `local_users` | 0 | 7 | 1 | `privilege_level`; one cell drops 4 of 5 records |
| `radius_servers` | 0 | 1 | 7 | whole record — every server dropped |
| `vxlan_vnis` | 0 | 0 | 8 | never populated on the source |
| `evpn_type5_routes` | 0 | 0 | 8 | never populated on the source |
| `routing_instances` | 0 | 0 | 8 | never populated on the source |
| `raw_sections` | 0 | 0 | 8 | empty on both sides on every cell |
| `apply_groups` | 0 | 0 | 8 | Junos-only |
| `group_content` | 0 | 0 | 8 | Junos-only |
| `anycast_gateway_mac` | 0 | 0 | 8 | never populated on the source |

"untested" = the Phase 1 `trivially_preserved` class: both sides carry no
data, so no disposition could be tested against a real round-trip.

## Sub-field drift aggregate (authoritative — every other sub-field of the
same parent is preserved on every cell)

| sub-field | drifting records | shape of the drift |
|---|---:|---|
| `interfaces[].interface_type` | 30 | `""` -> `ianaift:other` |
| `interfaces[].dhcp_client_v6` | 7 | `dhcp6` / `track6` -> `""` |
| `interfaces[].dhcp_client` | 5 | `true` -> `false` |
| `interfaces[].vrrp_groups` | 4 | `mode: carp` -> `hsrp`; `authentication` and `description` blanked |
| `interfaces[].lag_member_of` | 2 | `lagg0` -> `port-channel0` |
| `lags[].name` | 1 | `lagg0` -> `port-channel0` |
| `local_users[].privilege_level` | 8 | `15` -> `1` |
| `local_users[]` (record) | 1 cell | count drift `5 -> 1` |
| `static_routes[].description` | 1 | operator text -> `""` |
| `dhcp_servers[]` (record) | 4 cells | `all 1 dhcp_servers dropped` |
| `radius_servers[]` (record) | 1 cell | `all 2 radius_servers dropped` |
| `hostname` (scalar) | 1 cell | `""` -> `switch` |

## Notes grounding the dispositions

* **`hostname`** — the NX-OS renderer is `tree.hostname or "switch"`
  (`codecs/cisco_nxos/render.py`). A source with no `<hostname>` therefore
  re-parses as a device literally named `switch`; the other 7 cells carry the
  name through verbatim. This is an invented value, not a lost one, but it
  drifts, so the pair declares it `lossy` rather than `good`.

* **`interfaces[].interface_type`** — `_infer_type()` in
  `codecs/cisco_nxos/parse.py` derives the IANA ifType from the NX-OS
  name prefix and returns `ianaift:other` for anything it does not
  recognise. FreeBSD device names (`em0`, `igc0`, `ixl0`, `lo0`) match no
  prefix, so every interface on every cell lands as `ianaift:other`.
  Cosmetic: it is a derived attribute, and running the ports through the
  orchestrator's rename layer to NX-OS-native names resolves it.

* **`interfaces[].dhcp_client` / `dhcp_client_v6`** — the largest silent
  functional loss on the pair. An OPNsense WAN zone addressed by DHCP
  carries NO static address in canonical (measured: `ipv4_addresses: []`
  with `dhcp_client: true`), and the NX-OS render emits no `ip address
  dhcp`, so the rendered uplink has no addressing at all. The IPv6 side
  loses the acquisition mode as well (`dhcp6` for stateful DHCPv6,
  `track6` for tracking a delegated prefix).

* **`interfaces[].vrrp_groups`** — the record SURVIVES (group id, virtual
  IP, priority, preempt and advertisement interval all round-trip), so this
  is `lossy`, not `unsupported`. What changes is the protocol: the NX-OS
  codec renders every `CanonicalVRRPGroup` as an `hsrp` block regardless of
  the source mode (declared lossy in its matrix), so `mode: carp` re-parses
  as `mode: hsrp`, and the CARP shared passphrase
  (`authentication: carp-key:<passphrase>`) and the group description are
  blanked. An OPNsense HA pair therefore migrates as an UNAUTHENTICATED
  HSRP group that still looks correct in a diff of virtual IPs.

* **`interfaces[].lag_member_of` / `lags[].name`** — OPNsense LAGs are the
  FreeBSD `lagg(4)` shape and zero-based; the render maps the index straight
  through, so `lagg0` becomes `port-channel0`. Members and LACP mode survive
  intact. The reconciler's LAG-name equivalence
  (`_canonical_lag_name`, which folds `ae1` / `Po1` / `Port-channel1` to a
  common token) does NOT recognise either spelling, so this surfaces as real
  drift. NX-OS numbers port-channels from 1, so the bundle needs renumbering
  as well as renaming before the render will apply.

* **`local_users`** — two separate losses.
  1. `privilege_level` `15 -> 1` on 8 records across 7 cells. The NX-OS
     parser derives the numeric privilege from the NAMED role
     (`network-admin` / `vdc-admin` -> 15, everything else -> 1). OPNsense's
     role string is `admin`, which is not an NX-OS role name, so every
     OPNsense administrator re-parses as an unprivileged account.
  2. Record loss on `opnsense_acl_test_config.xml`: 5 users in, 1 out. The
     four dropped accounts are exactly the ones with an EMPTY
     `hashed_password`. `_render_local_user()` emits them as
     `username <name> role <role>` (no `password` clause), and the NX-OS
     `_USERNAME_RE` only matches lines that carry
     `password <type> <hash>`, so they do not survive the re-parse.
  The password DIGEST itself is preserved verbatim wherever the record
  survives (6 of 8 cells): the OPNsense value has the shape
  `bcrypt:$2y$<rounds>$<digest>` and comes back byte-identical. Note the
  render tags it `password 0 <value>` — type 0 is the NX-OS PLAINTEXT
  marker — so the canonical round-trip is exact while a real Nexus would
  hash the digest STRING as if it were the password rather than accept it
  as a digest. The mesh scores preservation, not target-syntax validity;
  reset these passwords on the target.

* **`dhcp_servers` / `radius_servers`** — both vanish WHOLESALE (`all 1
  dhcp_servers dropped`, `all 2 radius_servers dropped`), which is why both
  are `unsupported` rather than `lossy`: the record does not survive at all.
  Both are declared unsupported in the NX-OS matrix
  (`/dhcp-servers/pool`, `/radius-servers/server/host`,
  `/radius-servers/server/key`). Every LAN pool (range, gateway, DNS,
  lease time, domain) and every AAA server (host, shared secret, auth and
  acct ports) must be re-created on the target by hand or moved to a
  dedicated appliance.

* **`static_routes`** — the OPNsense matrix still declares the whole
  `/routing/static-route` family UNSUPPORTED, but the measurement
  contradicts it: destination and next-hop round-trip on all 3 populated
  cells. The matrix is behind the parser here (the two-block gateway JOIN
  wire-up landed without the declaration being flipped), so this pair is
  authored from the measurement. The one real loss is the per-route
  `description`, which the NX-OS render drops (declared lossy in its
  matrix — it emits destination + next-hop + metric only).

* **`snmp`** — community, location, contact and trap hosts round-trip on all
  3 cells that populate SNMP. `v3_users` is empty on BOTH sides of every
  cell: the OPNsense codec declares `/snmp/v3-user` unsupported (its v3 USM
  store lives in the bsnmpd plugin's own config, not `config.xml`), so the
  field is preserved by absence of data rather than by round-tripping any.
  If that parse side is ever wired up, the NX-OS target declares the v3
  auth and priv key digests and the engine ID lossy, so v3 users would need
  re-keying on the target.

* **`vlans`** — id and name round-trip on both populated cells (5 records
  each). `description`, `tagged_ports`, `untagged_ports` and
  `ipv4_addresses` carry no data on any VLAN record in the corpus.
  `tagged_ports` / `untagged_ports` are declared unsupported on the OPNsense
  source (no per-VLAN port concept), so they are structurally absent;
  `description` and the SVI-on-VLAN `ipv4_addresses` are declared LOSSY on
  the NX-OS target (its render emits the VLAN name but no description line,
  and renders SVI L3 only from a sibling interface stanza), so they are
  declared lossy on the strength of the target's own declaration with the
  measurement stated plainly.

* **Structurally absent on the source** (`ntp_servers`, `syslog_servers`,
  `vxlan_vnis`, `evpn_type5_routes`, `routing_instances`,
  `anycast_gateway_mac`, `interfaces[].switchport_mode` / `access_vlan` /
  `dot1q_vlan` / `trunk_*` / `vrf`, `vlans[].tagged_ports` /
  `untagged_ports`, `static_routes[].interface` / `metric` / `vrf`) — the
  OPNsense matrix declares each unsupported and the measurement agrees (0
  populated records anywhere in the corpus). The NX-OS target models most
  of them natively, so closing an OPNsense PARSE gap — not a target
  limitation — is what would move these rows.

* **`timezone` and `interfaces[].voice_vlan`** are the two fields declared
  unsupported on BOTH ends: the source never populates them AND the NX-OS
  render would drop them if it did ("Render emits no clock/timezone
  stanza"; "This codec does not model NX-OS per-port voice VLAN").
