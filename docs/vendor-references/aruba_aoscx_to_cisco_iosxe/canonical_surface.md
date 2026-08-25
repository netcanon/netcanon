# AOS-CX → Cisco IOS-XE (NETCONF/OpenConfig): measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__cisco_iosxe.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`, plus a
direct `cisco_iosxe.parse(cisco_iosxe.render(aruba_aoscx.parse(fixture)))`
round-trip over all seven cells re-run while authoring this file. Per-key
dispositions were resolved through the audit's own `actual_disposition()`
rather than inferred from the drift shape, so this file and the ratchet agree
by construction.

- Fixture cells: **7**
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations and the measured round-trip. Where a disposition rests on a
> declaration rather than an observed round-trip, the YAML says so explicitly.

## Codec-class framing — read this first

`cisco_iosxe` is **not** the Catalyst CLI codec. It is the Phase-0.5
NETCONF/OpenConfig sibling of `cisco_iosxe_cli`, and its `render()` walks
`intent.interfaces` and nothing else. The emitted document is a single
`<interfaces xmlns="http://openconfig.net/yang/interfaces">` tree carrying, per
interface: `name`, `description`, `enabled`, IANA `type`, and the IPv4/IPv6
address augments. There is no `<system>`, no `<vlans>`, no
`<network-instances>`, no SNMP, no AAA subtree in the output at all.

That single fact explains almost every disposition in the YAML, and it means
this pair is **not a device-migration pair**. It is appropriate only where a
downstream consumer needs interface-level data from an ArubaOS-CX box over
OpenConfig and accepts that everything else must be applied separately. For an
actual AOS-CX → Catalyst refresh, route through `cisco_iosxe_cli`, which emits
the full canonical surface.

The AOS-CX corpus itself is DC-oriented: four HPE DCN reference-architecture
leaf/core configs, one CANU/CSM spine carrying IPv6 and VRFs, one SNMPv3
management-plane capture, and the synthetic kitchen sink.

## The structural finding

This pair is the **inverse** of `aruba_aoscx__arista_eos`. There, the interface
inventory shrank and dragged every `interfaces[].*` sub-field down with it.
Here the interface inventory is preserved **exactly**:

| cell | source interfaces | target interfaces |
|---|---|---|
| `aoscx_dcn_arch3_ebgp_leaf1a.cfg` | 9 | 9 |
| `aoscx_dcn_arch3_ibgp_leaf1a.cfg` | 9 | 9 |
| `aoscx_dcn_arch4_core1_1.cfg` | 18 | 18 |
| `aoscx_dcn_arch4_core1_2.cfg` | 42 | 42 |
| `canu_csm17_spine001_ipv6_vrf.cfg` | 22 | 22 |
| `netutils_aoscx_snmpv3_glcx1009.cfg` | 44 | 44 |
| `kitchen_sink.cfg` | 13 | 13 |
| **total** | **157** | **157** |

Not one record is added or dropped, and `name`, `description`, `enabled` and
`interface_type` are byte-identical on all 157. What is lost instead is
**every other canonical collection, in full**.

## Total drops (source records → target records, summed over 7 cells)

| field | source records | target records |
|---|---|---|
| `vlans` | 30 | 0 |
| `lags` | 34 | 0 |
| `local_users` | 7 | 0 |
| `routing_instances` | 6 | 0 |
| `vxlan_vnis` | 4 | 0 |
| `static_routes` | 3 | 0 |
| `snmp` (object) | 4 populated cells | `None` on all 4 |
| `hostname` | 7 populated cells | `''` on all 7 |
| `anycast_gateway_mac` | 5 populated cells | `''` on all 5 |

These are **total** drops, so they are recorded `unsupported` rather than
`lossy`: a vanished record is not lossy (netcanon #436). `lossy` warns and
keeps the pair compatible, which would badly understate a field that never
arrives.

## Per-key measurement (7 cells)

| key | preserved | drifted | trivially empty |
|---|---|---|---|
| `hostname` | 0 | 7 | 0 |
| `interfaces[].name` / `description` / `enabled` / `interface_type` | 7 | 0 | 0 |
| `interfaces[].mtu` | 0 | 7 | 0 |
| `interfaces[].ipv4_addresses` | 2 | 5 | 0 |
| `interfaces[].ipv6_addresses` | 2 | 0 | 5 |
| `interfaces[].lag_member_of` | 0 | 7 | 0 |
| `vlans[]` (all six sub-keys) | 0 | 7 | 0 |
| `static_routes` | 0 | 2 | 5 |
| `snmp.community` | 3 | 1 | 3 |
| `snmp.location` / `snmp.contact` | 1 | 3 | 3 |
| `snmp.trap_hosts` | 4 | 0 | 3 |
| `snmp.v3_users` | 2 | 2 | 3 |
| `lags` | 0 | 7 | 0 |
| `local_users[]` (all three sub-keys) | 0 | 6 | 1 |
| `vxlan_vnis[]` (all three sub-keys) | 0 | 3 | 4 |
| `routing_instances[]` (both sub-keys) | 0 | 3 | 4 |
| `anycast_gateway_mac` | 0 | 5 | 2 |

Trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `dhcp_servers`, `radius_servers`,
`interfaces[].vrrp_groups`, `evpn_type5_routes`, `raw_sections`,
`apply_groups`, `group_content`.

The uneven SNMP row is worth spelling out, since it is the only place where the
same object produces different per-key verdicts. Four cells populate `snmp` at
all. Of those, exactly **one** sets a community string, **three** set a location
and a contact, **two** carry a v3 user, and **none** configures a trap host —
so an empty key measures as preserved even though the object it belongs to is
dropped in full.

## The two genuine partial losses

Only two keys degrade *inside* a record that survives — these are the `lossy`
entries, and they are the ones a reader should not confuse with the total
drops above.

**`interfaces[].mtu`** — 50 interface records across the corpus carry an MTU;
**0** keep it. The `<config>` element the stub emits has no `<mtu>` child at
all, so a 9198-byte jumbo uplink arrives as an interface with no MTU statement.
The record itself is intact.

**`interfaces[].ipv4_addresses`** — 41 addresses in the source, **41 preserved**
by IP and prefix-length. What drops is the anycast companion: 15 of those
addresses carry a `virtual_gateway_address`, and **all 15** come back empty.
Every one of the 15 sits on a synthesised SVI (`vlan 1`, `vlan 101`,
`vlan 102`, `vlan 2`, `vlan 4`, `vlan 6`, `vlan 7`, `vlan 15`, `vlan 69`,
`vlan 400`, `vlan 20`). The address survives; the shared first-hop gateway it
was paired with does not.

## The SVI residue — partial recovery for VLAN L3

The `vlans` collection is empty in the target, but the AOS-CX parser also
synthesises an interface record per SVI, and those **do** survive the
interfaces walk. Across the corpus, 18 VLANs carry an IPv4 address and exactly
those 18 reappear as target interfaces named `vlan <id>`:

- `aoscx_dcn_arch4_core1_1/2.cfg` → `vlan 101`, `vlan 102`, `vlan 4000`
- `canu_csm17_spine001_ipv6_vrf.cfg` → `vlan 1`, `vlan 2`, `vlan 4`, `vlan 6`, `vlan 7`
- `netutils_aoscx_snmpv3_glcx1009.cfg` → `vlan 1`, `vlan 2`, `vlan 15`, `vlan 69`, `vlan 400`
- `kitchen_sink.cfg` → `vlan 10`, `vlan 20`

So an operator can still recover *which VLAN numbers were routed* and *what
address each SVI held* from the interface list. What is unrecoverable is the
VLAN object itself: name (23 of 30 records carried one), description (6),
untagged membership (13), tagged membership (11). The VLANs with no L3 —
`vlan 2701`, `vlan 2707`, `vlan 10` on the CANU spine, `vlan 30` on the kitchen
sink — leave no trace at all.

The target matrix says this in its own words under `/vlans/vlan/id`:
"Synthesised SVI interfaces (`intent.interfaces[name='VlanN']`) DO survive via
the interfaces walk."

## Signal disagreement, resolved by probe

The total-drop classifier reported `snmp` as **partial → lossy**, while the
target matrix declares `/snmp` and all nine of its child paths **unsupported**.
Two signals in conflict, so it was probed rather than argued.

Result: on all four cells that populate SNMP, the re-parsed target intent has
`snmp = None`. There is no partial survival — the object is gone. Example
(`aoscx_dcn_arch4_core1_1.cfg`): the source carries a location and a contact
string and the target carries nothing.

`unsupported` is therefore the honest call for `snmp.community`,
`snmp.location`, `snmp.contact` and `snmp.v3_users`. The classifier's
"partial" verdict is an artefact of `snmp` being a single sub-object rather
than a list, not evidence of survival.

`snmp.trap_hosts` is the one exception and it needs stating plainly: the
audit measures it **preserved on 4 of 4 populated cells**, so the YAML
declares it `good` — but what was measured is an *empty* trap-host list
arriving empty. No committed AOS-CX cell configures a trap host. The `snmp`
object as a whole is dropped and the target declares `/snmp/trap-host`
unsupported, so a populated list would not survive. The `good` is a true
statement about this corpus and a misleading one about this pair; do not read
it as "traps migrate".

## Correlated drift — what does *not* count as corroboration

Three separate clusters here move for one reason each. Citing one member as
evidence for another would be double-counting:

1. **`vlans[].id` / `name` / `ipv4_addresses` / `untagged_ports` /
   `tagged_ports` / `description`** — six keys, one cause: the `vlans`
   collection is never walked by the render. Only `id` and `name` are
   individually declared unsupported by the target matrix; the other four
   vanish with the record.
2. **`vxlan_vnis[].vni` / `vlan_id` / `mcast_group`** — three keys, one cause.
   Note that **no** committed cell sets a multicast group (0 of 4 VNIs), so
   `mcast_group` measures as drifted purely because its parent record
   disappeared, not because a group was observed being lost.
3. **`routing_instances[].name` / `description`** — same shape. **0 of 6** VRFs
   in the corpus carry a description, so again the measured drift is the record
   vanishing.

Likewise, `lags` and `interfaces[].lag_member_of` are **one** finding, not two:
the OpenConfig stub models no link aggregation whatsoever. All 34 LAG records
drop, and all 44 interface records that name a parent LAG come back with
`lag_member_of = None`. Both are recorded `unsupported`.

There is a wrinkle worth knowing at cutover time: because AOS-CX names its
aggregates `lag 1`, `lag 256`, … and the parser materialises them as interface
records of IANA type `ieee8023adLag`, the *interfaces* named `lag N` survive
with their descriptions intact. A reader skimming the target output will see
`lag 256` / `VSX_ISL_LAG` and may conclude the LAG migrated. It did not — the
`lags` collection is empty and no member port is bound to it.

## Where the matrices under-state what happens

Two declarations are narrower than the observed behaviour. Both are codec-level
facts, not pair-specific ones, and are left for a codec change rather than
patched here:

- **`cisco_iosxe` declares `/lags/lag` nothing at all** — not supported, not
  lossy, not unsupported — while dropping all 34 LAG records. Same for
  `/local-users/user`: no declaration, 7 of 7 records dropped.
- **`cisco_iosxe` declares `/interfaces/interface/config/mtu` lossy** with the
  reason "some platform-specific MTU tweaks (IP vs link) are only representable
  in CLI". The measured behaviour is broader: **no** MTU survives, not just the
  IP-vs-link distinction. `lossy` remains the right severity — the interface
  record is intact — but the stated reason understates the scope.

## Where a source-side declaration does *not* fire

`aruba_aoscx` declares `/interfaces/interface/config/type` **lossy**, and the
sibling `aruba_aoss__cisco_iosxe` pair records `interfaces[].interface_type` as
lossy. On this pair it is preserved on **157 of 157** records: both codecs
speak the same `ianaift:` URIs (`ethernetCsmacd`, `ieee8023adLag`,
`softwareLoopback`), so nothing degrades. Declaring it lossy here on the
strength of the source declaration would be an unevidenced over-claim, so the
YAML records `good`.

Similarly, `cisco_iosxe` declares `/interfaces/interface/ipv6/address/scope`
lossy, specifically for link-local re-inference from the `fe80::/10` prefix.
The corpus carries exactly two IPv6 addresses (`2001:db8:100::2/64` on the CANU
spine's `vlan 6`, `2001:db8:20::1/64` on the kitchen sink's `vlan 20`), both
global-scope, and both round-trip with scope intact. The declared loss exists
but is **not exercised** by any committed cell — `interfaces[].ipv6_addresses`
is `good` on measurement, and a link-local-bearing fixture would be needed to
test the declaration.

## Symmetric declared gaps

Seven fields are declared unsupported at the exact path by **both** codecs, and
are empty on all 7 cells:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/system/timezone` · `/system/syslog-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/{host,key}`

Plus the whole `/interfaces/interface/vrrp-groups/group/*` subtree — AOS-CX
expresses first-hop redundancy as VSX active-gateway rather than VRRP, and the
stub parse-and-ignores FHRP entirely.

These are recorded `unsupported` (symmetric gap), not `not_applicable`. The
distinction matters operationally: unlike the AOS-CX → EOS pair, where
re-authoring DNS/NTP/syslog on the target would stick, here the target cannot
hold them either. Nothing on this pair carries system services, in either
direction, today.

`evpn_type5_routes`, `raw_sections`, `apply_groups` and `group_content` are
`not_applicable`: the source never populates them on any cell and declares
nothing unsupported at those paths.

## Credential material

`local_users` drops entirely — 7 of 7 records, on the 6 cells that populate
them — so `name`, `role` and `hashed_password` all go together. Every account
must be re-created downstream; nothing about the identity surface crosses this
pair.

For completeness on the secret itself: AOS-CX stores the user password as a
long ciphertext blob with a fixed three-character prefix (roughly 180
characters on the DCN captures), which is neither a crypt(3) hash nor anything
the OpenConfig render models. Two fixtures carry sanitised placeholders
instead.

Per `AGENTS.md`, no ciphertext, hash or placeholder value is reproduced in this
file or in the expectation YAML — only its shape. A document that quotes the
value it claims to redact defeats its own redaction.
