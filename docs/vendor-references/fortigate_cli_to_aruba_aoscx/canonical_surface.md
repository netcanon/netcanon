# FortiGate CLI → AOS-CX: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/fortigate_cli__aruba_aoscx.yaml`.

**Source of every number here:** the committed `tools/run_full_mesh.py` run
(`tests/fixtures/real/_cross_mesh_runs/20260825T024200Z.json`), plus a direct
`aruba_aoscx.parse(aruba_aoscx.render(fortigate_cli.parse(raw)))` probe of all
four fixtures for the calls the drift shape alone could not settle. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction.

- Fixture cells: **4**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and the round-trip probe. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## The four cells

| fixture | interfaces | LAGs | users | notes |
|---|---|---|---|---|
| `tests/fixtures/real/fortigate/kevinguenay_fgt_70g_branch.conf` | 21 | 2 | 1 | SD-WAN branch, blackhole routes |
| `tests/fixtures/real/fortigate/kevinguenay_fgt_vm_hub.conf` | 19 | 1 | 1 | VM hub, blackhole routes |
| `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf` | 34 | 2 | 3 | HA pair, RADIUS admins, SNMP traps |
| `tests/fixtures/synthetic/fortigate_cli/kitchen_sink.conf` | 12 | 2 | 3 | the only cell with LACP-named bundles |

## Device-class framing

`fortigate_cli` is a **perimeter / branch NGFW**; `aruba_aoscx` is a **campus
access/aggregation switch**. The shared surface is narrow by construction: L3
interface addressing, VLAN identity, static routes, SNMP scalars and local
admin identity. Everything that makes a FortiGate a FortiGate — firewall
policy, NAT, VPN, UTM, SD-WAN health checks, DHCP service, VDOMs — has no
AOS-CX target at all and is out of canonical scope, so it never appears in the
per-field table below. Treat the FortiGate policy config as documentation, not
as a translatable artefact.

## The structural finding: the inventory does NOT shrink

Worth stating up front because it is the opposite of the other `aruba_aoscx`
pairs: **the interface record count is preserved on every cell** — 21→21,
19→19, 34→34, 12→12, verified by name-for-name comparison in the probe. No
`interfaces[].*` key here inherits a loss from a vanished parent record. Each
one below stands on its own measurement, which is why five of the nine
interface sub-fields are `good`.

What *does* drive the interface-side losses is a single mechanism: the AOS-CX
codec derives interface semantics from the **shape of the interface name**.
Its own matrix says so for `/interfaces/interface/config/type` — `1/1/1` →
`ethernetCsmacd`, `vlan N` → `l3ipvlan`, `lag N` → `ieee8023adLag`,
`loopback N` → software loopback. FortiGate names (`port1`, `wan1`, `agg1`,
`VL_100`, `fortilink`, `LAG_INTERNAL`) match none of those shapes. Three
otherwise-unrelated keys fail for that one reason:

1. **`interfaces[].interface_type`** — of the 85 records that keep their name
   through the round-trip, exactly **one** keeps its IANA ifType (`mgmt`, on
   the FG100E fixture). The other 84 re-parse as `ianaift:other`.
2. **`interfaces[].lag_member_of`** — membership survives only where the
   bundle name ends in digits (see below).
3. **`lags`** — same cause, whole-record consequence.

These are one finding, not three; the YAML says so rather than citing them as
if they corroborated each other.

## Per-field measurement (4 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 4 | 0 | 0 |
| domain | 0 | 1 | 3 |
| dns_servers | 0 | 4 | 0 |
| ntp_servers | 0 | 1 | 3 |
| interfaces (record count) | 4 | 0 | 0 |
| interfaces[].name | 3 | 1 | 0 |
| interfaces[].description / enabled / ipv4_addresses | 4 | 0 | 0 |
| interfaces[].mtu / ipv6_addresses | 1 | 0 | 3 |
| interfaces[].interface_type | 0 | 4 | 0 |
| interfaces[].lag_member_of | 0 | 3 | 1 |
| vlans[].id / name | 3 | 0 | 1 |
| static_routes | 1 | 2 | 1 |
| dhcp_servers | 0 | 4 | 0 |
| snmp.community / location / contact | 2 | 0 | 2 |
| snmp.trap_hosts | 0 | 2 | 2 |
| snmp.v3_users | 1 | 1 | 2 |
| lags | 0 | 4 | 0 |
| local_users[].name / role | 3 | 1 | 0 |
| local_users[].hashed_password | 0 | 4 | 0 |
| radius_servers | 0 | 2 | 2 |

Fields trivially empty on all 4 cells: `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, `vlans[].ipv4_addresses`,
`vlans[].untagged_ports`, `vlans[].tagged_ports`, `vlans[].description`,
`vxlan_vnis[].vni`, `vxlan_vnis[].vlan_id`, `vxlan_vnis[].mcast_group`,
`evpn_type5_routes`, `routing_instances[].name`,
`routing_instances[].description`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

## Source-side gaps vs target-side drops

FortiGate declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for AOS-CX to lose. They are recorded
`not_applicable`:

`/vlans/vlan/tagged-ports` · `/vlans/vlan/untagged-ports` ·
`/vxlan-vnis/vni` · `/vxlan-vnis/source-interface` · `/vxlan-vnis/udp-port` ·
`/routing-instances/instance` · `/anycast-gateway-mac`

AOS-CX declares these unsupported while the FortiGate source **does** populate
them — a real target-side drop, recorded `unsupported`:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/dhcp-servers/pool` · `/snmp/trap-host` · `/radius-servers/server/host` ·
`/radius-servers/server/key`

`timezone` and `syslog_servers` are symmetric: **both** matrices declare the
path unsupported. Those are `unsupported` too, but nothing is being lost in
translation — neither codec ever held the data.

## Five findings worth carrying forward

**1. LAG survival is conditional on a numeric name suffix — proven, not
inferred.** Round-tripping each fixture: `fortilink` (2 members),
`LAG_INTERNAL` (2 members) and `lacp trunk` (4 members) produce **no LAG
construct at all** in the rendered AOS-CX config, and re-parsing yields zero
LAGs and zero interfaces carrying `lag_member_of`. On the kitchen-sink cell,
`agg1` / `agg2` *do* survive — rendered as member-side `lag 1` / `lag 2` lines
— because the trailing digit gives the renderer an id to use. That is why
`lags` is `lossy` and not `unsupported`: a total drop on three cells, a
survival-with-degradation on the fourth. Recording it `unsupported` would
block a migration that demonstrably carries LAGs through.

**2. The surviving LAG arrives static, not LACP.** On the one cell where the
bundles survive, `mode` goes `active` → `static` and `passive` → `static`; the
AOS-CX matrix declares `/lags/lag/mode` lossy for exactly this reason (it emits
`lacp mode` only for a `lag N`-shaped interface present in the source tree).
A static bundle facing an LACP-speaking peer will not form. This is the single
most likely cause of a link-down surprise on cutover.

**3. FortiGate blackhole routes render a distance in the next-hop slot.** Both
drifting static-route cells carry the same shape: `set blackhole enable` with
`set distance 254` and no gateway. The canonical model has no discard/blackhole
discriminator — `gateway` is simply empty — so the render emits
`ip route 10.100.0.0/16 254`, putting the administrative distance where the
next hop belongs. Re-parsing gives `metric=0` and `interface="254"`. Routes
that *do* carry a gateway round-trip exactly
(`ip route 0.0.0.0/0 port1 198.51.100.1`). Re-author discard routes by hand.
Separately, and outside this pair's measurement: on the hub fixture the
FortiGate `config router static` stanza holds five `edit` entries and only the
one with a literal `set dst` reaches the canonical model at all — object-name
destinations (`set dstaddr "RFC1918-GRP"`) do not.

**4. Password-less admin accounts survive the render but not the re-parse.**
On the FG100E fixture the source carries three admins; the rendered AOS-CX
config contains all three `user … group …` lines, but re-parsing recovers only
the one that also carries a password clause. The two RADIUS-backed accounts
(no local secret) are gone from the canonical round-trip. An operator reading
the rendered file sees three accounts; a tool re-reading it sees one. That is
a partial drop, hence `lossy` on `local_users[].name` and `local_users[].role`.

**5. An interface name with a space is truncated at the space.** The FG100E
fixture has an interface literally named `lacp trunk`. The render emits
`interface lacp trunk`; the AOS-CX grammar is single-token, so the re-parse
names it `lacp`. One record on one cell — but rename space-bearing interfaces
before migrating rather than discovering it afterwards.

## Authorization and credential material

`local_users[].role` itself is preserved on every surviving record
(`super_admin`, `prof_admin`, `super_admin_readonly` all round-trip as the
AOS-CX `user <name> group <role>` token). The authorization **level** does
not: the neighbouring `privilege_level` degrades 15 → 1 on three records
across three cells, because AOS-CX maps only the `administrators` group back to
15. This is an independent measurement, not a consequence of finding 4 — it is
observed on records that survive.

`local_users[].hashed_password` drifts on all four cells. The FortiOS secret is
a `fortios:ENC` marker followed by a space and a base64 body; the AOS-CX render
writes it into a single-token `password ciphertext <token>` field, so the
re-parse keeps the marker and the body is gone. Every migrated account arrives
**without a usable credential** — and the FortiOS form is encrypted under the
source device's key, so it would not authenticate on Aruba hardware even if it
survived intact.

`snmp.v3_users` degrades cryptographically rather than vanishing: on the one
cell that populates it, both users survive by name while auth `sha256` /
`sha512` both come back as `sha`, and the privacy protocol (`aes256`) is not
recovered at all. AOS-CX declares `/snmp/v3-user/auth-protocol` and
`/priv-protocol` lossy for exactly this — a silent downgrade to SHA-1 /
AES-128. Re-create SNMPv3 users on the target with the intended algorithms.

No secret value — FortiOS ciphertext body, SNMPv3 passphrase token or SNMP
community string — is reproduced in this file or in the expectation YAML. Per
`AGENTS.md`, encrypted secrets are operator-traceable even when encrypted, and
a document that quotes the value it describes defeats its own redaction.

## Two matrix under-declarations (not fixed here)

Recorded so the next reader does not mistake them for pair-specific facts:

- `fortigate_cli` declares **nothing** for `/system/domain` or
  `/dhcp-servers/pool` — neither supported, lossy nor unsupported — while its
  parser demonstrably populates both (`domain` on one cell, 1–6 DHCP pools on
  every cell). The dispositions here are driven by the AOS-CX side, which does
  declare both unsupported.
- `aruba_aoscx` declares only `/routing/static-route/description` lossy and
  `/routing/static-route/vrf` unsupported. Nothing in its matrix covers the
  gateway-less route shape in finding 3. Both belong in a codec change, not in
  an expectation file.
