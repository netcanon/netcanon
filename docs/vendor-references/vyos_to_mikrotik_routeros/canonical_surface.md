# VyOS → MikroTik RouterOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__mikrotik_routeros.yaml`.

**Source of every number here:** the committed corpus round-tripped by hand —
`vyos.parse()` → `mikrotik_routeros.render()` → `mikrotik_routeros.parse()` on
each of the 13 fixtures — cross-checked against this wave's resolved
disposition table, which was built by resolving every key through the audit's
own `actual_disposition()`, so this file and the ratchet agree by
construction. No number below is inferred from a drift shape; each was
re-derived from the render text and the re-parsed tree.

- Fixture cells: **13** (12 real captures under `tests/fixtures/real/vyos/`
  plus the synthetic `tests/fixtures/synthetic/vyos/kitchen_sink.conf`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the committed fixtures, and hand round-trips of each. Where a
> disposition rests on a declaration rather than an observed round-trip, the
> YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is a **Linux-based software router / edge gateway**:
kernel-style port names (`eth0`, `dum0`, `lo`), dot-notation 802.1Q
sub-interfaces (`eth1.100`), `bond0` LACP bundles, a single VRF, and a
Kubernetes-lab / homelab flavour of edge routing. `mikrotik_routeros` is a
**small-to-mid ISP / prosumer edge box** whose config is an `/export` command
stream.

The two device classes overlap almost exactly on the routed edge — interface
naming, IPv4/IPv6 addressing, static routes, LACP bundles, DNS, NTP, SNMP and
local accounts all cross intact. What does not cross is the VRF construct, the
VXLAN overlay, the system domain-name, and — most consequentially — the
credential on every migrated account.

## The structural finding: the two big record lists hold

The two record lists that carry this pair are **fully preserved**:

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| interface records after parse → render → re-parse | **55** |
| cells where the interface name set differs | **0** |
| source local-user records, all 13 cells | **17** |
| local-user records after the round-trip | **17** |
| user accounts that vanish | **0** |

The consequence is the useful one: **every interface and local-user loss on
this pair is a genuine per-attribute loss** that stands on its own
measurement. Nothing in either block is correlated drift, and every sub-field
that survives is recorded `good` rather than dragged down by a vanishing
parent.

Two record lists *do* vanish wholesale — `vxlan_vnis` (3 records across 3
cells) and `routing_instances` (1 record on 1 cell) — and each is recorded
once, on its identity key, exactly as the reconciler's structural collapse
expects.

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 0 | 1 | 12 |
| dns_servers | 1 | 0 | 12 |
| ntp_servers | 11 | 1 | 1 |
| interfaces[].name | 13 | 0 | 0 |
| interfaces[].enabled | 12 | 1 | 0 |
| interfaces[].description | 6 | 1 | 6 |
| interfaces[].ipv4_addresses | 9 | 0 | 4 |
| interfaces[].ipv6_addresses | 5 | 0 | 8 |
| interfaces[].mtu | 1 | 0 | 12 |
| interfaces[].lag_member_of | 1 | 0 | 12 |
| interfaces[].interface_type | 0 | 6 | 7 |
| static_routes | 4 | 0 | 9 |
| snmp.community / location / contact / trap_hosts | 4 | 0 | 9 |
| snmp.v3_users | 2 | 2 | 9 |
| lags | 1 | 0 | 12 |
| local_users[].name / role | 13 | 0 | 0 |
| local_users[].hashed_password | 0 | 12 | 1 |
| vxlan_vnis | 0 | 3 | 10 |
| routing_instances | 0 | 1 | 12 |

Two rows in that table are "preserved" only in the vacuous sense and are
called out rather than left to imply coverage: `snmp.trap_hosts` is empty on
**both** sides of all 4 SNMP cells (no committed VyOS fixture configures a
trap destination), and the single non-drifting `local_users[].hashed_password`
cell is an account that carries no password in the source at all.

Fields trivially empty on all 13 cells: `timezone`, `syslog_servers`,
`interfaces[].vrrp_groups`, all six `vlans[].*` keys, `dhcp_servers`,
`radius_servers`, `evpn_type5_routes`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

### Per-record detail behind the interface drift

55 interface records across the 13 cells:

| sub-field | populated on source | drifting records | shape |
|---|---|---|---|
| `interface_type` | **0** | 7 | empty → a type the target *invents* |
| `description` | 15 | 1 | value → empty |
| `enabled` | 53 | 1 | `False` → `True` (fails **open**) |
| `mtu` | 1 | 0 | — |
| `ipv4_addresses` | 21 | 0 | — |
| `ipv6_addresses` | 20 | 0 | — |
| `lag_member_of` | 2 | 0 | — |
| `vrrp_groups` | 0 | 0 | — |

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for RouterOS to lose:

`/vlans/vlan/id` (which is the VLAN record's identity — vyos mints no
`vlans[]` record at all) · `/interfaces/interface/vrrp-groups/group/*` ·
`/dhcp-servers/pool` · `/radius-servers/server/host` ·
`/radius-servers/server/key` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}`

These are recorded `not_applicable`, not `unsupported`, and the distinction is
operational: for several of them **mikrotik_routeros declares the field
supported or lossy** — `/vlans/vlan/id` supported, the whole
`/interfaces/interface/vrrp-groups/group` subtree supported,
`/dhcp-servers/pool/lease-time` lossy (i.e. RouterOS renders pools, losing only
the lease time). Re-authoring those on the target will stick, and a migration
report should say so rather than implying RouterOS cannot hold them.

Four fields are **symmetric** gaps — *both* matrices declare the same path
unsupported, so re-authoring on the target will not stick either. Those are
recorded `unsupported`: `/system/timezone`, `/system/syslog-server`,
`/anycast-gateway-mac`, and (target-only, but a hard drop) `/system/domain`.

`evpn_type5_routes`, `raw_sections`, `apply_groups` and `group_content` are
declared by **neither** codec and emitted by the source on **zero** cells;
they are recorded `not_applicable` on that measurement, not on a declaration.

## Four findings worth carrying forward

### 1. Credential material lands in RouterOS's *cleartext* password field

This is the most serious finding on the pair and it has two halves. Both were
measured; neither is inferred.

**Half one — the credential does not migrate.** `local_users[].hashed_password`
drifts on **16 of 17 user records across 12 of 13 cells**: every VyOS account
whose `encrypted-password` is a crypt string comes back with
`hashed_password` empty. The RouterOS parser is explicit about why
(`codecs/mikrotik_routeros/parse.py:1204` — `/export` omits hashes), so no
round-trip can recover it. The one non-drifting record is an account that
carries no password in the source at all.

**Half two — and the hash is written out anyway.** The RouterOS renderer has a
deliberate guard against exactly this (`codecs/mikrotik_routeros/render.py`,
`is_migratable(...)` gating plus a `# password manager … -- review:` comment
for unmigratable hashes), and on this pair **the guard never fires**. The
central classifier `classify_hash()` in `netcanon/migration/_user_secrets.py`
recognises *tagged* forms — `arista:sha512:…`, `cisco:type9:…`, the bare-digit
Cisco `5 …` form — and falls through to `("plaintext", <input>)` for anything
without a tag. VyOS emits the **bare** crypt string, so it classifies as
`plaintext`, `is_migratable(..., "mikrotik_routeros")` returns `True`, and the
renderer emits the crypt string as the value of RouterOS's `password=`
attribute — which RouterOS treats as the literal plaintext password and
re-hashes.

Measured across all 13 renders:

| measurement | value |
|---|---|
| `/user add` lines carrying a crypt-shaped `password=` value | **16** |
| `/user add` lines with no `password=` at all | **1** |
| `# password manager … review:` comments emitted | **0** |

Confirming the classifier boundary directly, with a **synthetic** value that
appears in no fixture:

```
classify_hash("$6$" + "A"*8 + "$" + "B"*86)          -> ("plaintext", …)
is_migratable(same, "mikrotik_routeros")             -> True
classify_hash("arista:sha512:" + "B"*86)             -> ("sha512", …)
is_migratable(same, "mikrotik_routeros")             -> False
```

So the tagged path is refused correctly and the untagged path is not. The
operator-facing effect is the one the renderer's own comment warns about:
the account arrives with its password set to the literal text of the source
hash, and no review marker tells anyone that happened.

This belongs to the codec, not to this pair — recorded here because it is what
the measurement shows, and left for a codec change rather than acted on.

`local_users[].hashed_password` is therefore recorded **`unsupported`**, not
`lossy`. The value does not degrade into a weaker form the operator can still
use; it disappears from the canonical tree entirely, and RouterOS has no
grammar a hashed password lands in — `_TARGET_ACCEPTS["mikrotik_routeros"]` is
`frozenset({"plaintext"})`. A vanished value is not lossy (#436), and `lossy` —
which warns but stays compatible — would badly understate this.

Set every migrated account's password on the target before cutover, and treat
the rendered config as containing recoverable credential text.

### 2. A dot-notation sub-interface falls between two render filters

**One mechanism, two keys.** `interfaces[].description` and
`interfaces[].enabled` each drift on exactly one record, both on
`kitchen_sink.conf`, and both for the same reason. Neither is cited as
evidence for the other; each is recorded where it is measured.

The RouterOS renderer excludes an interface from `/interface ethernet` using
the **permissive** `_looks_like_vlan_iface()` (matches `^vlan…` *or* any name
with a dot followed by digits) and includes it in `/interface vlan` using the
**strict** `_is_vlan_name()` (`^vlan\d` only) or
`interface_type == "ianaift:l3ipvlan"`. A VyOS `eth1.100` matches the
permissive exclusion, fails the strict inclusion, and — because vyos populates
`interface_type` on no record at all — fails the type test too. It therefore
gets **no `/interface` stanza of any kind**, surviving only as an
`/ip address add … interface=eth1.100` row.

Verified on the two sub-interface records in the corpus:

| record | source | after round-trip |
|---|---|---|
| `eth1.100` description | `tenant vlan 100` | empty |
| `eth1.200` `enabled` | `False` | **`True`** |

The name and the addressing survive (they ride the `/ip address` row, which is
why `interfaces[].name` is 55/55), but the `comment=` and the `disabled=yes`
are never emitted. The admin-state case is the dangerous direction: a port
that was **administratively down on VyOS comes up enabled on RouterOS**.

Exposure is narrow and easy to state: 2 of 55 interface records in this corpus
are dot-notation sub-interfaces, and both sit on one fixture. Both matrices
declare `/interfaces/interface/config/description` and `/config/enabled`
supported, so this is a real per-attribute loss and not a declared gap.
`mikrotik_routeros` separately declares `/interfaces/interface/dot1q-vlan`
unsupported (ship-before-wire, GAP 7), which is the neighbouring symptom —
the tag itself also drops — but the description and admin-state losses come
from the filter mismatch, not from the dot1q declaration.

**Not the VyOS quote-rewrite.** The VyOS *renderer* replaces embedded double
quotes with apostrophes (vyos.dev/T1246), which alters description punctuation
on pairs where vyos is the **target**. Here vyos is the **source**, so that
path is not involved, and the loss is not punctuation: the description string
is gone in full.

### 3. `interface_type` drift is a target-side *gain*, not a source-side loss

`interfaces[].interface_type` drifts on 6 of 13 cells and 7 of 55 records —
and the direction is the opposite of a loss. **vyos populates
`interface_type` on zero of its 55 records**, so there is nothing to lose. The
RouterOS re-parse *attaches* a type to seven of them:

| records | interface | type after round-trip | why |
|---|---|---|---|
| 6 | `lo` | `ianaift:bridge` | RouterOS has no loopback primitive; the renderer emits the documented empty-bridge idiom (`/interface bridge add name=lo`), and the re-parse types a bridge as a bridge |
| 1 | `bond0` | `ianaift:ieee8023adLag` | rendered under `/interface bonding`, re-parsed as a LAG |

The `bond0` case is simply correct. The `lo` case is a **mislabel with a good
cause**: the loopback-as-empty-bridge render is deliberate and documented in
the codec (without it the loopback's name drops and its IP binds to a phantom
interface), but the canonical type that comes back describes the RouterOS
construct rather than the VyOS one, so a migrated inventory shows the loopback
classified as a bridge.

Both matrices already declare `/interfaces/interface/config/type` lossy —
`mikrotik_routeros` states the mechanism outright ("RouterOS does not expose
IANA ifType; the codec infers it from the interface-name prefix"). Recorded
`lossy`: the interface record, its addressing and its admin state are
untouched, so this is a wrong hint, not lost forwarding state.

### 4. NTP loses two of three servers on one cell — from a source-parse residue

`ntp_servers` round-trips cleanly on 11 of the 12 cells that populate it,
including a five-server cell. On `houdev_vyos_dhcpv6_pd_client.conf` it drops
**3 → 1**, and the mechanism spans both codecs:

- That fixture writes the empty block **inline**: `server  time1.vyos.net { }`
  on one line, where every other fixture uses the multi-line
  `server 0.pool.ntp.org {` / `}` form. The VyOS brace-stack parser handles
  the multi-line form and leaves a literal ` { }` glued to the server name on
  the inline form, so the canonical value is `time1.vyos.net { }`.
- The RouterOS renderer writes that verbatim into a comma-joined
  `servers=` value. An unquoted RouterOS value terminates at whitespace, so
  the re-parse recovers only `time1.vyos.net` and the second and third servers
  are gone.

Both matrices declare `/system/ntp-server` supported, and the concept plainly
crosses on 11 of 12 cells — so `ntp_servers` is recorded `lossy` (partial
record loss inside a concept the target models), not `unsupported`. The
residue is a source-side artifact; the record loss is measured on the target
round-trip. Worth stating both halves rather than blaming one side.

## Credential material

No hash body is reproduced in this file or in the expectation YAML. Only the
crypt-scheme marker (`$6$`), the string length, and the count of affected
records are described; the classifier demonstration above uses a synthetic
`$6$AAAAAAAA$BBB…` value that appears in no fixture. Per `AGENTS.md`, password
hashes are operator-traceable even when they are hashes, and a document that
quotes the value it describes defeats its own redaction.

## Two drift-shape readings that are wrong

**`local_users` is not a total drop.** A mechanical "is the target side empty?"
pass reports the whole `local_users` field as vanishing. It does not: all 17
accounts survive on all 13 cells with their names, and **zero** roles drift.
What empties is one field — the password — and that is recorded once, on
`local_users[].hashed_password`. `local_users[].name` and `local_users[].role`
are `good`, deliberately: they measure what happens to the *value* when the
record survives, and the answer is nothing.

**`snmp` is not unclassifiable.** The SNMP block round-trips on all 4 cells
that carry one; `community`, `location` and `contact` never drift. The only
drift is inside `snmp.v3_users`, on the 2 cells with a USM user, and it is
three declared sub-attributes rather than a vanishing user:

| attribute | source | after round-trip | declared |
|---|---|---|---|
| `group` | `default` / `operators` | empty | `/snmp/v3-user/group` lossy on the target |
| `engine_id` | a hex engine ID | empty | `/snmp/v3-user/engine-id` lossy on the target |
| `priv_protocol` | `aes` | `aes128` | `/snmp/v3-user/priv-protocol` lossy on the target |

The user record itself survives with its name, so `snmp.v3_users` is `lossy`.
Note what was **not** observed: the target matrix warns that RouterOS
substitutes `3des` → `DES`, a strength downgrade. No committed cell uses
`3des`, so that downgrade is declared here, not measured — the only privacy
substitution this corpus exercises is the `aes` → `aes128` normalisation.

## Related drift the audited key set does not cover

Three interface sub-fields drift that are not among the audited canonical
keys, recorded here so the next reader does not re-hunt them:

- `interfaces[].vrf` — `eth0`'s `BLUE` binding empties on `kitchen_sink.conf`.
  This is the same mechanism as the `routing_instances` drop
  (`/routing-instances/instance` unsupported: "Render emits no
  VRF/routing-instance construct"), not an independent loss.
- `interfaces[].dot1q_vlan` — `100` → null on the sub-interface records; the
  target declares `/interfaces/interface/dot1q-vlan` unsupported
  (ship-before-wire, GAP 7).
- `interfaces[].dhcp_client` — **3 records** across 3 cells (`houdev` `eth0`,
  `scottlaird` `eth5`, `kitchen_sink` `eth2`) go `True` → `False`: a port that
  took its address by DHCP arrives with no client configured. `vyos` declares
  `/interfaces/interface/dhcp-client` **supported** and
  `mikrotik_routeros` declares no path for it at all, so this drift is
  undeclared on both sides. Not one of the audited keys, so it is recorded
  here rather than claimed — but it is the kind of thing worth checking on the
  target before cutover.
- `interfaces[].dhcp_client_v6` — 1 record (`houdev` `eth0`, `dhcpv6` → empty).
  The target declares `/interfaces/interface/dhcp-client-v6` **lossy** with the
  cause: RouterOS puts DHCPv6 client config under a separate
  `/ipv6 dhcp-client` section rather than an interface attribute.
- `local_users[].privilege_level` — declared LOSSY by `vyos`, but set on all
  17 records here (level 15) and preserved on every one. The declared
  sub-loss is not exercised by this corpus.

## Matrix under-declarations noticed in passing

Standing observations about the codecs, not pair-specific facts, and left for
a codec change rather than fixed here:

- `mikrotik_routeros` declares **nothing** under `/local-users/*` — neither
  supported, lossy nor unsupported — while demonstrably rendering and
  re-parsing `/user add` lines and dropping the password on every one.
- It likewise declares nothing for `/lags/lag/name` or `/lags/lag/members`
  (only `/lags/lag/mode` lossy) while carrying both intact through the
  round-trip, and nothing for `/interfaces/interface/config/mtu` or
  `/interfaces/interface/lag-member-of`, both of which round-trip cleanly.
