# VyOS → OPNsense: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/vyos__opnsense.yaml`.

**Source of every number here:** per-key dispositions were resolved through the
audit's own `actual_disposition()` and the Phase-4 reconciler's structural
collapse, so this file and the ratchet agree by construction. Every loss
recorded below was additionally re-derived by hand — `vyos.parse()` →
`opnsense.render()` → `opnsense.parse()` over each of the 13 committed
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **13** (12 real captures under `tests/fixtures/real/vyos/`
  plus `tests/fixtures/synthetic/vyos/kitchen_sink.conf`)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, and hand round-trips of the committed
> fixtures. Where a disposition rests on a declaration rather than an observed
> round-trip, the YAML says so explicitly.

## Device-class framing

`vyos` in this corpus is a **Linux software router / edge gateway**: lab and
CI gateways (`wcni-kind-gw0/1`), a five-router routed lab (`pc5-round1-*`,
`pc5-round3b-*`), a DHCPv6-PD client edge, and a forum SNMPv3 capture. It
parses a curly-brace `config.boot`; set-form input is normalised through
`_setform_to_brace` first. `opnsense` is a **BSD firewall** whose entire
model is `config.xml`.

The shared surface is therefore the **routed/managed edge** — the interface
inventory with its addressing, MTU, admin state and description; local user
identity; SNMP v1/v2c; hostname/domain/DNS. What does not cross is everything
that is *router* rather than *firewall*: the static-route table, VRFs, VXLAN,
and the NTP client — plus SNMPv3, which OPNsense keeps outside `config.xml`
entirely.

This is the last blind codec pair in the mesh audit.

## The structural finding — the interface inventory is fully preserved

A mechanical "is the target side empty?" triage pass reports `interfaces` on
this pair as a **total drop**. It is not, and the difference matters for every
`interfaces[].*` key below.

| measurement | value |
|---|---|
| source interface records, all 13 cells | **55** |
| records after parse → render → re-parse | **55** |
| cells where the interface name set differs | **0** |

VyOS `ethN`, dot1q sub-interfaces (`eth1.100`, `eth1.200`), `lo`, bonds and
bridge members all survive the OPNsense `config.xml` render with their names
intact.

The consequence is the useful one: **every interface key on this pair stands on
its own measurement.** None of the nine audited `interfaces[].*` keys is
dragged down by a vanishing parent, and none of them drifts — there is no
correlated drift anywhere in the interface block.

Reproduce:

```
py - <<'PY'
import sys; sys.path.insert(0, '.')
from netcanon.migration.codecs import opnsense, vyos
from netcanon.migration.codecs.registry import get_codec
from pathlib import Path
S, T = get_codec('vyos'), get_codec('opnsense')
cells = sorted(Path('tests/fixtures/real/vyos').glob('*.conf'))
cells.append(Path('tests/fixtures/synthetic/vyos/kitchen_sink.conf'))
n = m = 0
for f in cells:
    s = S.parse(f.read_text(encoding='utf-8')); t = T.parse(T.render(s))
    n += len(s.interfaces); m += len(t.interfaces)
    assert [i.name for i in s.interfaces] == [i.name for i in t.interfaces], f
print(n, '->', m)   # 55 -> 55
PY
```

## Per-field measurement (13 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 13 | 0 | 0 |
| domain | 1 | 0 | 12 |
| dns_servers | 1 | 0 | 12 |
| ntp_servers | 0 | **12** | 1 |
| timezone | 0 | 0 | 13 |
| syslog_servers | 0 | 0 | 13 |
| interfaces | 11 | 2 | 0 |
| vlans | 0 | 0 | 13 |
| static_routes | 0 | **4** | 9 |
| dhcp_servers | 0 | 0 | 13 |
| snmp | 2 | 2 | 9 |
| lags | 1 | 0 | 12 |
| local_users | 1 | **12** | 0 |
| radius_servers | 0 | 0 | 13 |
| vxlan_vnis | 0 | **3** | 10 |
| evpn_type5_routes | 0 | 0 | 13 |
| routing_instances | 0 | **1** | 12 |
| raw_sections | 0 | 0 | 13 |
| apply_groups | 0 | 0 | 13 |
| group_content | 0 | 0 | 13 |
| anycast_gateway_mac | 0 | 0 | 13 |

### The interface block, per record

| audited sub-field | populated records | drifted | shape |
|---|---|---|---|
| `name` | 55 | **0** | — |
| `enabled` | 55 | **0** | — |
| `description` | 15 | **0** | — |
| `ipv4_addresses` | 21 | **0** | — |
| `ipv6_addresses` | 20 | **0** | — |
| `mtu` | 1 | **0** | — |
| `lag_member_of` | 2 | **0** | — |
| `interface_type` | 0 | — | never emitted by vyos |
| `vrrp_groups` | 0 | — | never emitted by vyos |

The two cells the table above counts as "drifted" on `interfaces` drift on
attributes that are **not** among the audited keys, and they are named here so
nobody mistakes them for one of the nine:

| attribute | records | shape |
|---|---|---|
| `dot1q_vlan` | 2 (`eth1.100`, `eth1.200`, kitchen sink) | value → null |
| `vrf` | 1 (`eth0`, kitchen sink) | `BLUE` → empty |
| `dhcp_client_v6` | 1 (`eth0`, DHCPv6-PD cell) | `dhcpv6` → empty |

opnsense declares `/interfaces/interface/dot1q-vlan` unsupported (routed
sub-interface tagging is not yet wired, ship-before-wire GAP 7), and the `vrf`
emptying is the interface-side face of the whole-VRF drop described below.
Neither is cited as evidence for any audited key.

## Source-side gaps vs target-side drops

`vyos` declares these **unsupported at the exact path**, so as a *source* it
never emits them and there is nothing for OPNsense to lose:

`/vlans/vlan/id` · `/vlans/vlan/ipv4/address/{secondary-ip,virtual-gateway-address,virtual-gateway-mac}` ·
`/dhcp-servers/pool` · `/radius-servers/server/{host,key}` ·
`/interfaces/interface/vrrp-groups/group/*` ·
`/interfaces/interface/{switchport-mode,access-vlan,trunk-allowed-vlans,trunk-native-vlan,voice-vlan}` ·
`/interfaces/interface/dot1q-vlan`

Measured, not merely declared: on all 13 cells the vyos parser emitted **zero**
VLAN records, **zero** DHCP pools, **zero** RADIUS servers, **zero** VRRP
groups, **zero** EVPN type-5 routes, **zero** raw sections, no apply-groups, no
group content, no anycast gateway MAC, no timezone, no syslog servers and no
`interface_type` on any of the 55 interface records.

These are recorded `not_applicable`, not `unsupported`. The distinction is
operational: opnsense declares `/vlans/vlan/id` and `/vlans/vlan/name`
**supported**, and declares `/interfaces/interface/vrrp-groups/group` **lossy**
rather than absent — so re-authoring VLANs and CARP-based first-hop redundancy
on the target will stick. The migration report should say that rather than
implying the firewall cannot hold them.

Three keys are different, because **both** matrices declare them unsupported —
a symmetric gap rather than a target limitation. Those are recorded
`unsupported`:

| key | both declare |
|---|---|
| `timezone` | `/system/timezone` |
| `syslog_servers` | `/system/syslog-server` |
| `anycast_gateway_mac` | `/anycast-gateway-mac` |

`interfaces[].interface_type` is a fourth shape again: vyos declares
`/interfaces/interface/config/type` **lossy** on its own side and opnsense
declares no path for it either way — but vyos emitted the hint on none of the
55 records, so there was never anything to lose. Recorded `not_applicable`.

## Four total drops the firewall cannot express

Each was verified by round-trip, and each is recorded `unsupported` rather than
`lossy`, because a vanished record is not lossy (#436): `lossy` warns and stays
compatible, which would badly understate losing a router's whole routing table.
**These are four separate mechanisms with four separate measurements — none is
cited as corroboration for another.**

| key | measured | target declaration |
|---|---|---|
| `ntp_servers` | **37 servers over 12 cells → 0** | `/system/ntp-server` unsupported: "Render emits no `<system><timeservers>`" |
| `static_routes` | **7 routes over 4 cells → 0** | `/routing/static-route` unsupported: parse harvests routes, but the `config.xml` renderer emits no `<staticroutes>` block |
| `vxlan_vnis[].vni` | **3 VNIs over 3 cells → 0** | `/vxlan-vnis/vni` unsupported: "VXLAN not modelled — OPNsense is a firewall codec" |
| `routing_instances[].name` | **1 VRF (`BLUE`) over 1 cell → 0** | `/routing-instances/instance` unsupported: "Render emits no VRF/routing-instance construct" |

`static_routes` is the one that will hurt most in practice. The OPNsense parser
*does* harvest routes (the `<gateways>` default route plus
`<staticroutes>/<route>` entries, resolving named gateways to their IP), so the
asymmetry is purely on the render side — the reverse pair does not lose them.
Re-enter the routing table on the target before cutover.

`vxlan_vnis[].vlan_id` and `vxlan_vnis[].mcast_group` are recorded **`good`**,
and `routing_instances[].description` likewise. That is deliberate. Those keys
measure what happens to the *value* when the record survives; the record
disappearing is one loss, already claimed once by the sibling that carries it
(`vxlan_vnis[].vni`, `routing_instances[].name`). Recording the same
disappearance three more times would double-count a single mechanism, and the
per-pair ratchet would reject it as unevidenced.

## SNMP: v1/v2c crosses, v3 does not

4 of 13 cells populate an SNMP block. On every one of them the community
string, location and contact round-trip unchanged — `ro`, `public`,
`FAKEPUBLIC`, `HOME`, `rack 4 / row B`, `netops@example.com`. Both matrices
declare `/snmp/community`, `/snmp/location` and `/snmp/contact` supported.

`snmp.v3_users` is the loss: **2 USM users over 2 cells → 0** (`vyos` on the
forum capture, `snmpv3admin` on the kitchen sink). opnsense declares
`/snmp/v3-user` unsupported and states exactly why — OPNsense's SNMPv3 user
store lives in the bsnmpd / net-snmp plugin's own `snmpd.conf` `createUser`
lines, not in the `config.xml` this codec reads and writes. The users vanish, so
this is `unsupported`, not `lossy`. SNMPv3 keys would have needed re-keying on
the target regardless; the *user list* needing re-creation is the part worth
writing down.

`snmp.trap_hosts` is recorded `good` with a caveat stated plainly in the YAML:
zero drift measured, but trap-hosts are **empty on all four cells**, and vyos
declares no `/snmp/trap-host` path at all. opnsense declares it supported. So
that `good` reflects a preserved-and-empty SNMP block, not an exercised
round-trip.

## LAGs cross intact — the one place this pair beats the mesh average

One cell populates `lags`: `bond0`, LACP mode `active`, members `eth4`/`eth5`.
It round-trips **complete** — name, mode and both members — and the two
`interfaces[].lag_member_of` pointers on `eth4` and `eth5` survive with it.
Both are recorded `good`.

One caveat that is declared rather than observed: opnsense declares
`/lags/lag/mode` **lossy**, because OPNsense's `lagg` uses a single `lacp`
proto with no active/passive distinction, so a `passive` bundle re-parses as
`active`. The corpus's only bundle is already `active`, so the declared loss
cannot fire here. A passive-LACP source would hit it.

## Credential material — a real defect on this pair

**No hash body is reproduced in this file or in the expectation YAML.** Only
the crypt-scheme marker, the scheme tag and record counts are described. The
`$6$`/`$2y$` strings below are scheme markers, not values.

### What is measured

17 local-user records across all 13 cells. Names and roles are preserved on
**every** record — zero drift on either. `hashed_password` drifts on **16 of
17** records across 12 of 13 cells; the 17th carries no password material at
all. Every source secret in this corpus is `$6$` (SHA-512 crypt), and vyos
emits it **untagged** — a bare crypt string with no `alg:` prefix.

After the round-trip the canonical value is the *same body verbatim* with a
`bcrypt:` scheme tag prepended. The body length is byte-identical on all 16
records (asserted, not eyeballed). So the credential material is carried, and
the algorithm label attached to it is **false**.

### Why the guard did not fire

`netcanon/migration/_user_secrets.py::classify_hash()` recognises three tagged
shapes — `vendor:alg:payload`, `alg:payload`, and the bare leading-digit Cisco
form (`5 $1$…`) — and treats **anything else as a literal plaintext password**,
returning `("plaintext", <input>)`. `is_migratable()` then short-circuits,
because plaintext is always migratable.

An untagged `$6$` hash therefore reaches the opnsense render's guard classified
as plaintext, and the render writes it verbatim into `<password>` as though the
operator had typed it. On the kitchen sink that produces **2 `<password>`
elements holding `$6$` values and 0 review comments**.

This is precisely the outcome `netcanon/migration/codecs/opnsense/render.py`
says the review-line path exists to prevent — its own comment calls it "a
broken hash literal masquerading as bcrypt". The policy plainly intends to
block it: `sha512` is listed in `_UNIVERSALLY_UNMIGRATABLE` and is absent from
`_TARGET_ACCEPTS["opnsense"] = {plaintext, bcrypt}`. Tag the identical hash
`sha512:` and `is_migratable()` correctly returns `False`. **The bypass is
purely the untagged input shape**, which is the shape vyos produces.

Reproduce, with entirely synthetic material:

```
py - <<'PY'
import sys; sys.path.insert(0, '.')
from netcanon.migration._user_secrets import classify_hash, is_migratable
h = '$6$' + 'A' * 8 + '$' + 'B' * 86          # invented, not from any fixture
print(classify_hash(h)[0], is_migratable(h, 'opnsense'))   # plaintext True
print(classify_hash('sha512:' + h)[0],
      is_migratable('sha512:' + h, 'opnsense'))            # sha512 False
PY
```

### Operational consequence

OPNsense's `<password>` element is consumed by PHP `password_verify()`, which
expects bcrypt. A `$6$` value sitting there is not a working credential, so the
migrated account cannot authenticate — and the source hash literal is now
written into the target config in a place where the policy intended a review
comment instead. Set every migrated password on the target before cutover, and
treat the rendered `config.xml` as containing source credential material until
you have.

The key is recorded **`lossy`**, not `unsupported`: nothing vanishes. The
account, its name and its role all survive, and the target models the concept —
opnsense declares `/local-users/user/{name,role,hashed-password}` supported.
Under #436 that is the definition of lossy. The severity lives in the `reason`
text, not in an inflated disposition.

`local_users[].name` and `local_users[].role` are recorded `good`, and
deliberately so: they measure what happens to the value when the record
survives, and the answer is nothing. Zero drift on 17 of 17 records.

## The VyOS quote-rewrite does not apply to this pair

Worth stating because it bites the reverse direction: the **vyos render**
replaces embedded double-quotes in free text with apostrophes, because VyOS
rejects embedded quotes in value strings even when escaped
(`vyos.dev/T1246`, implemented at `netcanon/migration/codecs/vyos/render.py`).
On a pair where vyos is the *target*, a `description` can come back with
altered punctuation — the text survives, its punctuation does not.

Here vyos is the **source**, so its render is never invoked. Measured
accordingly: all 15 populated `interfaces[].description` records round-trip
byte-identical. opnsense's own `/interfaces/interface/config/description` lossy
declaration is about *other* targets truncating long text (Cisco 240 chars,
Juniper 900); OPNsense imposes no length limit and nothing truncated here.
`interfaces[].description` is `good` on measurement, not on charity.
