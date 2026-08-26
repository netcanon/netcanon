# VyOS → Arista EOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__arista_eos.yaml`.

**Source of every number here:** the committed corpus of 13 VyOS fixtures,
round-tripped by hand — `vyos.parse()` → `arista_eos.render()` →
`arista_eos.parse()` — and cross-checked against the audit's own
`actual_disposition()` resolution so this file and the drift ratchet agree by
construction. Per-key `preserved / drifted / trivially-empty` cell counts come
from the audit resolver; the record-level counts are from the hand round-trip.
No claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures + 1 synthetic kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the committed fixtures, and hand round-trips of those
> fixtures. Where a disposition rests on a declaration rather than on an
> observed round-trip, the YAML says so in as many words.

## Device-class framing

`vyos` in this corpus is a **Linux-based software router** — a lab/edge or
virtual box. Its interface names are the Linux kernel's: `eth0`…`eth5`, `lo`,
`dum0` (dummy), `bond0`, and dot1q sub-interfaces spelled `eth1.100`. It
carries DHCP-client WAN ports, IPv6-only lab links, a handful of static
routes, SNMP, and local users whose passwords are bare `$6$` SHA-512 crypt
strings out of `/etc/shadow`. `arista_eos` is a **DC leaf/spine** whose
interface vocabulary is `Ethernet<N>` / `Loopback<N>` / `Vlan<N>` /
`Management<N>` / `Port-Channel<N>`.

The shared surface is therefore the **routed edge**: hostname, DNS/NTP,
interface addressing and admin state, static routes, SNMP, VRF identity, and
local-user identity. There is no campus L2 surface on either side of this pair
— the `vyos` codec declares `/vlans/vlan/id` *unsupported*, so it never emits a
VLAN record at all.

## The structural finding: bare interfaces are elided, not translated

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **46** |
| records elided by the render | **10** |
| records synthesised by the render | **1** (`Port-Channel0`) |
| cells where the interface **name set** differs | **6** |
| elided records that carried any content | **0** |

That last row is the one that decides half this file. Every one of the ten
dropped records was **bare** — no description, no IPv4 or IPv6 address, no
MTU, admin-up, no VRF, no LAG membership, no VRRP group. Nothing an operator
configured was lost with them.

### Per-cell interface inventory

| fixture cell | src | tgt | records elided |
|---|---|---|---|
| `houdev_vyos_dhcpv6_pd_client.conf` | 2 | 2 | — |
| `metasploit-vyos-config.conf` | 3 | 1 | `eth1`, `lo` |
| `pc5-round1-border.conf` | 2 | 2 | — |
| `pc5-round1-core.conf` | 3 | 3 | — |
| `pc5-round3b-routera.conf` | 4 | 4 | — |
| `pc5-round3b-routerb.conf` | 3 | 3 | — |
| `pc5-round3b-routerd.conf` | 4 | 4 | — |
| `pc5-round3b-routere.conf` | 8 | 8 | — |
| `scottlaird-vyos-parser.conf` | 7 | 2 | `eth2`, `eth3`, `eth4`, `eth5`, `lo` |
| `vyos_forum_snmpv3_user_eq13.conf` | 2 | 1 | `lo` |
| `wcni-kind-gw0.conf` | 3 | 2 | `lo` |
| `wcni-kind-gw1.conf` | 3 | 2 | `lo` |
| `kitchen_sink.conf` (synthetic) | 11 | 12 | — (`Port-Channel0` added) |
| **total** | **55** | **46** | **10** |

### The mechanism

`netcanon/migration/codecs/arista_eos/render.py` (the *empty-stub elision
policy*, ~lines 473–540) skips a canonical interface unless one of three
things is true: it carries renderable content, its name matches
`_IS_ARISTA_PHYSICAL_PORT_RE` (line 82 — `Ethernet<N>` / `Loopback<N>` /
`Vlan<N>` / `Management<N>` / `Port-Channel<N>` / `Vxlan<N>`), or it is
referenced by a VRF binding or a VLAN member list.

VyOS names match **none** of those shapes. `eth1` is not `Ethernet1`; `lo` is
not `Loopback0`. So a VyOS interface stub that carries nothing is treated
exactly like the OPNsense `igc0` leak the policy was written to stop, and is
dropped. `lo` is elided on five cells for precisely this reason — and survives
on `kitchen_sink.conf`, where it carries `10.255.0.1/32` and a `/128`, as
`interface lo`.

**The mechanism is a name-shape mismatch, not a capacity limit.** The EOS
render never attempts to map `eth1` → `Ethernet1` or `lo` → `Loopback0`; the
foreign name is carried through verbatim when a stanza is emitted at all.

### Contrast with the two sibling Arista-target pairs

- `aruba_aoscx__arista_eos` — inventory shrinks 9 → 5 on the representative
  cell for the *same* elision reason (AOS-CX enumerates every default-config
  campus port). Same mechanism, much wider blast radius.
- `cisco_iosxr__arista_eos` — inventory fully preserved, 156 → 156, because
  IOS-XR fixtures rarely carry content-free ports.

This pair sits between them, and closer to the IOS-XR end than the cell counts
suggest: 6 of 13 cells lose a record, but zero configured attributes go with
them.

## Per-field measurement

Cell counts as resolved by the audit (`preserved / drifted / trivially
empty`, 13 cells):

| key | pres. | drift | trivial |
|---|---|---|---|
| `hostname` | 13 | 0 | 0 |
| `domain` | 1 | 0 | 12 |
| `dns_servers` | 1 | 0 | 12 |
| `ntp_servers` | 11 | 1 | 1 |
| `interfaces[].name` | 7 | 6 | 0 |
| `interfaces[].description` | 3 | 6 | 4 |
| `interfaces[].enabled` | 7 | 6 | 0 |
| `interfaces[].mtu` | 0 | 6 | 7 |
| `interfaces[].ipv6_addresses` | 4 | 6 | 3 |
| `interfaces[].ipv4_addresses` | 3 | 6 | 4 |
| `interfaces[].interface_type` | 0 | 6 | 7 |
| `interfaces[].lag_member_of` | 0 | 6 | 7 |
| `interfaces[].vrrp_groups` | 0 | 6 | 7 |
| `static_routes` | 4 | 0 | 9 |
| `snmp.community` / `.location` / `.contact` / `.trap_hosts` | 4 | 0 | 9 |
| `snmp.v3_users` | 2 | 2 | 9 |
| `lags` | 0 | 1 | 12 |
| `local_users[].name` / `.role` | 13 | 0 | 0 |
| `local_users[].hashed_password` | 0 | 12 | 1 |
| `vxlan_vnis[].vni` / `.vlan_id` | 3 | 0 | 10 |
| `routing_instances[].name` | 1 | 0 | 12 |

Trivially empty on all 13 cells: `timezone`, `syslog_servers`, every
`vlans[].*` key, `dhcp_servers`, `radius_servers`,
`vxlan_vnis[].mcast_group`, `evpn_type5_routes`,
`routing_instances[].description`, `raw_sections`, `apply_groups`,
`group_content`, `anycast_gateway_mac`.

### Why the `interfaces[].*` sub-keys all read "6 drifted"

Six cells change their interface **record set**. When a list changes length the
comparator reports the *whole record* as drifted and stops diffing sub-fields,
so every `interfaces[].*` key inherits that one signal on those six cells. It
is **one** structural loss, claimed once — by `interfaces[].name` — and it is
correlated drift, not six independent findings.

Measured on the records that actually survive, across all 13 cells:

| sub-field | populated records | drifting records |
|---|---|---|
| `description` | 15 | **0** |
| `enabled` (`False`) | 2 | **0** |
| `mtu` | 1 | **0** |
| `ipv4_addresses` | 21 | **0** |
| `ipv6_addresses` | 20 | **0** |
| `interface_type` | **0** | 0 |
| `vrrp_groups` | **0** | 0 |
| `lag_member_of` | 2 | 2 (name-translated — see below) |
| `dhcp_client` (not an audited key) | 3 | 2 surviving + 1 elided |
| `dhcp_client_v6` (not an audited key) | 1 | 1 |

The two `enabled: False` records (`kitchen_sink.conf` `eth3` and `eth1.200`)
both render `shutdown` and re-parse admin-down, so the field is exercised, not
merely untested.

`interface_type` is populated on **zero** of 55 records: the VyOS parser emits
no IANA type hint at all (it declares `/interfaces/interface/config/type`
lossy in its own right). Both codecs declare that path lossy, and on this pair
neither declaration ever bites, because there is nothing to carry.

## Five findings worth carrying forward

### 1. Every VyOS user password is re-emitted under EOS's *cleartext* tag

This is the most consequential finding on the pair, and it is a clean
mechanical chain, not an inference.

VyOS stores a local user's password as a **bare** `$6$` SHA-512 crypt string
with no vendor or algorithm tag. `classify_hash()`
(`netcanon/migration/_user_secrets.py`, lines 111–147) resolves a tag from a
`vendor:alg:payload` prefix, an `alg:payload` prefix, or a bare leading Cisco
digit. A bare `$6$…` matches none of those, so it falls through the final
branch — *"No algorithm tag — treat as literal plaintext password"* — and
returns `("plaintext", "$6$…")`.

`_ARISTA_SECRET_TYPE` (`arista_eos/render.py`, line 68) maps `plaintext → "0"`.
The render therefore emits:

```
username <name> privilege 15 role admin secret 0 <the $6$ crypt string>
```

`secret 0` is EOS's **cleartext** marker. Re-parsing that line yields a
canonical `hashed_password` of `arista:0:<the same $6$ string>`.

Measured: **16 of 16** local-user records that carry a password, across 12 of
13 cells, take this path. Not one exception. The seventeenth user
(`houdev_vyos_dhcpv6_pd_client.conf` / `netadmin`) has no password in the
source and renders `nopassword`.

Two distinct consequences, both worth stating:

- **The credential does not migrate as a credential.** EOS has a `sha512`
  secret tag available in the very same dispatch table; the untagged VyOS
  payload never reaches it. The digest is offered to the target as a literal
  password string.
- **The digest lands in the rendered config in cleartext-marked position.**
  A `$6$` digest is operator-traceable material; a rendered artefact that
  labels it `secret 0` invites it into places a hash would not normally go.

Both matrices declare `/local-users/user/hashed-password` **supported**. The
measurement disagrees with both declarations on every populated record. That
gap between declaration and behaviour is exactly what this expectation file
exists to record; closing it belongs to a codec change, not to this file.

Set every migrated account's password on the target before cutover.

### 2. IPv4 DHCP-client is dropped silently; IPv6 is not

`has_renderable_attr` in the elision policy tests `iface.dhcp_client_v6` but
**not** `iface.dhcp_client`. Three consequences, all measured:

- `houdev_vyos_dhcpv6_pd_client.conf` / `eth0` — carries both. It survives (it
  has a description), and the render emits
  `! review: dhcp_client_v6=dhcpv6 has no Arista EOS equivalent`. The IPv4
  DHCP client gets **no** review comment and no `ip address dhcp` line. Round
  trip: `dhcp_client True → False`, `dhcp_client_v6 'dhcpv6' → ''`.
- `kitchen_sink.conf` / `eth2` — IPv4 DHCP only, plus a description. Survives
  as a description-only stanza; `dhcp_client True → False`, silently.
- `scottlaird-vyos-parser.conf` / `eth5` — IPv4 DHCP and **nothing else**. Not
  renderable, not Arista-named, not referenced: the whole port is elided. A
  DHCP WAN port disappears without a trace in the render.

Neither `dhcp_client` nor `dhcp_client_v6` is an audited canonical key, so no
disposition in the YAML covers this. It is recorded here because it is a real
loss the per-key mesh is structurally blind to.

### 3. `bond0` → `Port-Channel0` splits the bundle across two records

One cell (`kitchen_sink.conf`) carries a LAG. The round trip:

| | source | target |
|---|---|---|
| `lags` record count | 1 | 1 |
| LAG name | `bond0` | `Port-Channel0` |
| LAG members | `eth4`, `eth5` | `eth4`, `eth5` |
| LAG mode | `active` | `active` |
| `eth4` / `eth5` `lag_member_of` | `bond0` | `Port-Channel0` |

Members and mode survive intact; the *name* is translated into EOS's native
`Port-Channel<N>` vocabulary. That translation is correct and desirable — and
it has a side effect the record counts hide.

The source `bond0` **interface** record carries the bundle's L3
(`10.50.0.1/24`) and its description (`server lag`). The render emits that as
`interface bond0` — a foreign-named stanza kept alive only because it has
content — and *separately* emits a bare `interface Port-Channel0` plus
`channel-group 0 mode active` under `eth4` and `eth5`.

So after migration the bundle's addressing sits on an interface called
`bond0` that is not the bundle, while the actual `Port-Channel0` comes up with
no address and no description. The interface count goes **up** (11 → 12) while
the configuration gets *less* coherent. Re-home the bundle's L3 onto
`Port-Channel0` by hand.

`interfaces[].lag_member_of` is recorded `good` and `lags` is recorded `lossy`
in the YAML. They are **one** rename, measured at two places; neither is cited
as evidence for the other. The membership relation survives the rename (both
ends move together), which is what the `lag_member_of` key measures. The
identity string of the LAG record does not, which is what `lags` measures.

Standing observation, and it points the *opposite* way from the one recorded
on `cisco_iosxr__arista_eos`: the `arista_eos` matrix declares **nothing**
under `/lags/lag` — not supported, not lossy, not unsupported — while on this
pair it demonstrably renders and re-parses a Port-Channel with its members and
mode. On the IOS-XR pair the same silent matrix accompanied dropping bundles
entirely. An under-declaration is not a prediction in either direction. That
belongs to a codec change, not to this file.

### 4. SNMPv3 survives as a user and dies as a credential

Two cells carry a v3 USM user (`vyos_forum_snmpv3_user_eq13.conf`,
`kitchen_sink.conf`). Both round-trip the user record: name, group, auth
protocol (`sha`) and **both passphrases** come back byte-identical. Two things
change:

- `engine_id` → empty string, on both cells. `arista_eos` declares
  `/snmp/v3-user/engine-id` **lossy** and `docs/CAPABILITIES.md` states the
  reason: engineIDs are device-assigned, and a cross-vendor render may need
  re-keying.
- `priv_protocol` `aes` → `aes128`, on both cells. A normalisation, not a
  weakening: EOS spells the same cipher with its key length.

The passphrases surviving is the trap here. USM keys are engineID-salted
(RFC 3414; the same point is made in-repo at
`docs/vendor-references/arista_eos_to_mikrotik_routeros/snmp_aaa.md` and in
`arista_eos/render.py` line 327, which contrasts RADIUS secrets as *not*
engineID-salted). Carrying the localized key forward while dropping the engine
it was localized against produces a config that looks complete and will not
authenticate. Re-key SNMPv3 users on the target.

### 5. The one `ntp_servers` drift is a source-parser artefact, not a lost server

`houdev_vyos_dhcpv6_pd_client.conf` writes its NTP servers as one-line
empty-body blocks:

```
server         time1.vyos.net { }
```

The VyOS brace parser captures the whole token run, so the canonical value is
`time1.vyos.net { }` — hostname plus a stray brace pair. The EOS render emits
`ntp server time1.vyos.net { }` verbatim; the EOS parser reads only the first
token after `ntp server`, so the round trip returns the clean
`time1.vyos.net`.

All three hostnames are present on both sides, in order. The canonical string
is not preserved, so the audit records a drift and the YAML declares
`ntp_servers` lossy — but the delta is punctuation the *source* parser
attached, and the round trip removes it. Nothing an operator configured went
missing. On the other 11 populated cells the lists are identical.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for EOS to lose:

`/vlans/vlan/id` · `/dhcp-servers/pool` · `/radius-servers/server/host` ·
`/radius-servers/server/key` · `/anycast-gateway-mac` ·
`/system/syslog-server` · `/routing/static-route/vrf` ·
`/interfaces/interface/vrrp-groups/group` and all seven of its sub-paths ·
`/interfaces/interface/{switchport-mode,access-vlan,dot1q-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}`

These are recorded `not_applicable`, not `unsupported`, and the distinction is
operational: `arista_eos` declares most of them **supported** — DHCP pools,
syslog servers, the anycast gateway MAC, VRF static routes, VLAN id/name, and
the VRRP group. Re-authoring them on the EOS side will stick. A migration
report should say that rather than implying the target cannot hold them.

`timezone` is the one symmetric gap: **both** matrices declare
`/system/timezone` unsupported. That one is `unsupported`.

The six `vlans[].*` entries are grounded in both declaration and measurement:
`vyos` declares the identity leaf `/vlans/vlan/id` unsupported, and the parser
produced **0** VLAN records on all 13 cells. VyOS expresses tagging as a
sub-interface (`eth1.100`), which lands in `interfaces[]` and round-trips
there as `encapsulation dot1q vlan 100`.

Two fields deserve a separate line because the *source* can emit them and this
corpus simply does not:

- `vxlan_vnis[].mcast_group` — `vyos` declares `/vxlan-vnis/mcast-group`
  **supported**; `arista_eos` declares it **lossy** (the multicast underlay is
  not emitted on render). All three committed VNI records carry an empty
  mcast-group, so there is no measurement. A VyOS VXLAN that *did* use a
  multicast underlay would hit the target's declared lossy path.
- `routing_instances[].description` — `vyos` declares no path for it and emits
  none; `arista_eos` declares `/routing-instances/instance/description` lossy
  (no `vrf instance <name> / description` emit path). Same shape: a real
  target-side drop with nothing on this corpus to drop.

Both are recorded `not_applicable` rather than `lossy`, because a loss
declared on zero observations is an over-claim the per-pair ratchet cannot
evidence.

## Two things this pair does *not* lose

Recorded because the drift shape invites the opposite reading.

**`vxlan_vnis` is not a total drop.** The field drifts on 3 of 13 cells, which
a mechanical "did the target side change?" pass reads as the VXLAN surface
collapsing. It does not. `vni` and `vlan_id` — the identity and the binding —
round-trip intact on all three records (`vni=10`/`vlan=10` twice,
`vni=10100`/`vlan=1912` once). What actually changes is two sub-fields that
are not audited keys: `flood_list` empties (`arista_eos` declares
`/vxlan-vnis/flood-list` lossy — the head-end replication list is not
emitted), and on the two `wcni-kind-*` cells `source_interface` goes from
empty to `Loopback0`, which is the render *adding* a VTEP source, not losing
one.

**No local user account vanishes.** 17 accounts in, 17 out, names and roles
identical on all 13 cells — unlike `cisco_iosxr__arista_eos`, where five
type-7 accounts disappear. `local_users[].name` and `local_users[].role` are
`good` here on measurement, and the whole of the credential loss is recorded
once, under `local_users[].hashed_password`.

## Credential material

No hash body, passphrase, community string payload or engineID value is
reproduced in this file or in the expectation YAML. Only the crypt-scheme
marker (`$6$`), the algorithm token the codec resolves (`plaintext`), and the
emitted EOS tag (`secret 0`) are described. Per `AGENTS.md`, password hashes
are operator-traceable even when they are hashes, and a document that quotes
the value it describes defeats its own redaction. The one literal quoted
above — `arista:0:` — is the codec's own re-encoding prefix and contains no
key material.

## A note on the VyOS quote rewrite, which does not apply here

The `vyos` **render** replaces embedded double-quotes in free text with
apostrophes, because the VyOS config parser rejects them even backslash-escaped
(`netcanon/migration/codecs/vyos/render.py`, lines 132–156). That is a
target-side behaviour. On this pair VyOS is the **source**, so no description
is rewritten by it. Measured accordingly: 15 populated interface descriptions,
zero drift. The `interfaces[].description` `good` on this pair is a real
round-trip result, not an untested one.
