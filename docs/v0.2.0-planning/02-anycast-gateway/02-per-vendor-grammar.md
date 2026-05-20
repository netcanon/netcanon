# 02 — Per-vendor grammar

Vendor-specific syntax for the anycast-gateway primitive with
field mapping tables and edge-case notes. Citations are real
fixtures from `tests/fixtures/real/` or upstream documentation
URLs.

---

## Juniper Junos

### Grammar

```text
# Per-IRB virtual-gateway-address (the per-IP companion):
set interfaces irb unit <vid> family inet address <X>/<M> virtual-gateway-address <Y>
set interfaces irb unit <vid> family inet6 address <X>/<M> virtual-gateway-address <Y>

# Per-IRB virtual-gateway MAC override (the per-unit override):
set interfaces irb unit <vid> virtual-gateway-v4-mac <MAC>
set interfaces irb unit <vid> virtual-gateway-v6-mac <MAC>

# Optional proxy-ARP / ND advertisement for the anycast IP:
set interfaces irb unit <vid> proxy-macip-advertisement
```

### Source citation

`tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set`
lines 95-128 exercise the full surface across 7 IRB units (2021,
2022, 2023, 2024, 2025, 2031, with 2022/2023/2024/2025 also
carrying `proxy-macip-advertisement`). Extract from the fixture
(line numbers preserved):

```text
95: set interfaces irb unit 2021 family inet address 10.221.0.5/16 virtual-gateway-address 10.221.0.1
96: set interfaces irb unit 2021 family inet6 address fd20:2021::5/64 virtual-gateway-address fd20:2021::1
97: set interfaces irb unit 2021 family inet6 address fe80:2021::1/64
98: set interfaces irb unit 2021 virtual-gateway-v4-mac 02:00:21:00:00:01
99: set interfaces irb unit 2021 virtual-gateway-v6-mac 02:00:21:06:00:01
100: set interfaces irb unit 2022 proxy-macip-advertisement
101: set interfaces irb unit 2022 family inet address 10.222.0.5/16 virtual-gateway-address 10.222.0.1
102: set interfaces irb unit 2022 family inet6 address fd20:2022::5/64 virtual-gateway-address fd20:2022::1
```

Note line 97: the `fe80::/10` link-local address is on its OWN line
with **no** `virtual-gateway-address` clause. The codec must NOT
attach the anycast to the link-local.

Upstream reference (Junos OS documentation, free under Juniper's
EVPN configuration guide CC license excerpt):
[EVPN-VXLAN with Anycast Gateway](https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-default-gateway.html).

### Field mapping table

| Junos source | Canonical destination | Notes |
|---|---|---|
| `set interfaces irb unit <vid> family inet address <X>/<M> virtual-gateway-address <Y>` | On `CanonicalIPv4Address` (folded onto the matching `CanonicalVlan.ipv4_addresses[i]` via the IRB→VLAN fold): `ip="<X>"`, `prefix_length=M`, `virtual_gateway_address="<Y>"` | Both halves on one line; both halves must land on the SAME canonical record |
| `set interfaces irb unit <vid> family inet6 address <X>/<M> virtual-gateway-address <Y>` | On `CanonicalIPv6Address`: `ip="<X>"`, `prefix_length=M`, `virtual_gateway_address="<Y>"`, `scope="global"` | The `fe80::/10` link-local sibling lives on a separate record with `virtual_gateway_address=""` |
| `set interfaces irb unit <vid> virtual-gateway-v4-mac <MAC>` | On every `CanonicalIPv4Address` for that IRB: `virtual_gateway_mac="<MAC>"` | One MAC override per unit covers every v4 address on that unit |
| `set interfaces irb unit <vid> virtual-gateway-v6-mac <MAC>` | On every `CanonicalIPv6Address` for that IRB with `scope="global"`: `virtual_gateway_mac="<MAC>"` | Link-local addresses NOT touched |
| `set interfaces irb unit <vid> proxy-macip-advertisement` | Tier-3 (parse-and-ignore; see § "Junos edge cases") | Routing-protocol property; not modelled |

### Junos edge cases

1. **Per-unit MAC override applies to ALL addresses on that unit.**
   The QFX10K2 fixture has a single v4 address per unit and a
   single global-scope v6 address per unit, so the override unambiguously
   maps to "this address's MAC". A future Junos source could
   have multiple v4 addresses per unit; the spec is that the
   single `virtual-gateway-v4-mac` applies to all of them. Parser
   must propagate to every IPv4 record on the unit, not just the
   first.

2. **Order independence of MAC and address lines.** The fixture
   shows `family inet address` lines (95-96) BEFORE the
   `virtual-gateway-v4-mac` line (98). A different operator could
   write them in either order. Parser must accumulate MAC into
   `irb_state[vid]["v4_mac"]` (and v6) and stamp every address
   record at materialisation time, not at parse-of-the-address-line
   time.

3. **`proxy-macip-advertisement` is Tier-3.** This is an EVPN
   advertisement-policy property (whether to proxy MAC/IP route
   advertisement on behalf of attached hosts). Out of scope for
   the canonical anycast surface — the existing
   `dropped_tier3_sections` notification handles it.

4. **`fe80::/10` link-local without a virtual companion.** Lines
   like `set interfaces irb unit 2031 family inet6 address
   fe80:2031::1/64` carry no `virtual-gateway-address` and must
   round-trip with `virtual_gateway_address=""`. The parser
   already infers `scope="link-local"` from the fe80::/10 prefix
   (`netcanon/migration/codecs/juniper_junos/parse.py:373-383`);
   the anycast field stays empty.

5. **Block-form input.** Junos's curly-brace block form gets
   auto-converted to set-form on parse
   (`netcanon/migration/codecs/juniper_junos/codec.py` § "Block-form
   to set-form"). The dispatcher handles both shapes uniformly;
   no additional work needed for the anycast surface — once the
   set-form parser matches `family inet address X virtual-gateway-
   address Y`, both shapes work.

6. **Apply-groups inheritance.** Junos's `set groups <G>
   interfaces irb unit <vid> family inet address X
   virtual-gateway-address Y` followed by `set apply-groups <G>`
   must inherit correctly. The existing two-pass GAP-8 dispatch
   (`parse.py` § "_dispatch_groups" + "_dispatch_top") routes
   `set groups <G>` lines through the same `_apply_interfaces`
   dispatcher as top-level lines, so the new anycast handling will
   inherit-correctly for free. Render-side `apply_groups` round-
   trip likewise re-emits the group content verbatim (see
   `render.py` § GAP-9b).

---

## Arista EOS (VARP)

### Grammar

```text
# Per-Vlan-SVI virtual address (the per-IP companion; no per-leaf primary):
interface Vlan<N>
   ip address virtual <X>/<Y>
   ip address virtual <X2>/<Y2> secondary    # optional secondary VARP
   ipv6 address virtual <X>/<Y>              # 4.30+ — IPv6 VARP

# System-wide virtual-router MAC (one for the entire chassis):
ip virtual-router mac-address <MAC>
```

### Source citation

`tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt`
lines 149-201:

```text
149: interface Vlan110
150:    description Tenant_A_OPZone_1
151:    vrf Tenant_A_OPZone
152:    ip address virtual 10.1.10.1/24
153:    ip address virtual 10.1.100.1/24 secondary
154: !
155: interface Vlan111
156:    description Tenant_A_OPZone_2
157:    vrf Tenant_A_OPZone
158:    ip address virtual 10.1.11.1/24
159: !
...
201: ip virtual-router mac-address 00:dc:00:00:00:01
```

Second fixture
(`tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt`)
lines 202-237 carry 8 more VARP-bearing SVIs and the system-wide
MAC at line 286.

Upstream reference: Arista EOS User Manual, "VARP" chapter; also
publicly mirrored at
[`arista.com/en/um-eos/eos-section-43-9-virtual-arp-varp`](https://www.arista.com/en/um-eos/eos-section-43-9-virtual-arp-varp).

### Field mapping table

| EOS source | Canonical destination | Notes |
|---|---|---|
| `interface Vlan<N> / ip address virtual <X>/<Y>` | On the matching `CanonicalVlan(id=N)`: append `CanonicalIPv4Address(ip="", prefix_length=Y, virtual_gateway_address="<X>")` OR (if a primary already exists on the SVI) augment the existing record with `virtual_gateway_address` | EOS VARP has NO per-leaf primary — only the virtual IP. The canonical record carries `ip=""` to express that |
| `interface Vlan<N> / ip address virtual <X>/<Y> secondary` | Same as above, with `is_secondary=True` | Multiple VARP addresses on the same SVI; all but the first carry the `secondary` trailer |
| `interface Vlan<N> / ipv6 address virtual <X>/<Y>` | On the matching `CanonicalVlan(id=N)` or `CanonicalInterface(name="VlanN")`: append `CanonicalIPv6Address(ip="", prefix_length=Y, virtual_gateway_address="<X>", scope="global")` | Mirror v4 shape; appears in EOS 4.30+ |
| `ip virtual-router mac-address <MAC>` | Top-level: `intent.anycast_gateway_mac = "<MAC>"` | One per chassis; per-IP override unsupported on EOS (operator must use `ip virtual-router mac-address <MAC>` system-wide) |

### Arista EOS edge cases

1. **No per-leaf primary.** Unlike Junos (where every leaf has a
   distinct per-leaf primary), EOS VARP has only the virtual
   address. The canonical model expresses this with `ip=""` on
   the address record. Cross-vendor migration from EOS to Junos
   surfaces a review banner: Junos requires a per-leaf primary,
   so the operator must synthesise one (or the migration assumes
   the operator will set per-leaf primaries via per-device
   overlays). The renderer emits a comment-form review line
   `# review: EOS VARP source has no per-leaf primary; set
   manually on each Junos leaf before commit`.

2. **`secondary` trailer.** Multiple `ip address virtual` lines on
   the same SVI are an operator pattern for overlapping subnets
   (per-tenant default gateways). The parser must preserve the
   trailer via `is_secondary=True` on the second+ record; render
   emits the trailer for every record but the first. The current
   EOS parser (line 884: "first address wins") explicitly drops
   the trailer — this work fixes that for VARP. Non-VARP
   secondaries remain dropped (out of scope; an existing
   limitation tracked elsewhere).

3. **System-wide MAC at TOP LEVEL of config.** Line 201 / 286 in
   the fixtures appears after every `interface` stanza but at the
   global level (no indentation). The current top-level dispatcher
   in `arista_eos/parse.py` (`_parse_top_level` or equivalent)
   needs a new branch for `ip virtual-router mac-address`. The
   line is order-independent with respect to interface stanzas;
   parser captures into `intent.anycast_gateway_mac`.

4. **`ip virtual-router mac-address-advertisement-interval`** —
   EOS has a related global knob for VARP-advertisement
   intervals. Out of scope; falls into Tier-3 (informational).

5. **`ip address virtual source-nat vrf <V> address <X>`** — lines
   202-204 / 287-290 in the fixtures are a DISTINCT feature
   (VARP source-NAT for VRF-leaked traffic), NOT the anycast
   gateway. Parser must distinguish: lines with `source-nat` go
   to a separate (Tier-3) handler, NOT into the anycast canonical
   field. Easiest discriminator: the second token after `virtual`
   — if it's `source-nat`, route to Tier-3; otherwise it's the
   anycast address.

6. **`vxlan virtual-router encapsulation mac-address mlag-system-id`**
   (line 270 in the lab-val fixture) — a Vxlan-stanza property
   controlling how anycast MAC is announced over EVPN. Tier-3 /
   parse-and-ignore; not the anycast surface.

7. **SVI-fold interaction.** EOS's parse.py runs
   `project_svi_to_vlan` (line 500). The fold copies
   `iface.ipv4_addresses` onto `vlan.ipv4_addresses`. With the
   schema extension and the transform widening
   (see [`01-canonical-model.md`](01-canonical-model.md) § "Fold
   interaction"), the VARP fields survive the fold for free.

---

## Cisco IOS-XE SD-Access mode

### Grammar

```text
# System-wide anycast-gateway MAC:
fabric forwarding anycast-gateway-mac <MAC>

# Per-SVI anycast trigger (the SVI's existing primary IP becomes the anycast gateway):
interface Vlan<N>
   ip address <X> <MASK>
   fabric forwarding mode anycast-gateway
```

### Source citation

No real-capture fixture in the corpus today (Catalyst-9000 in
SD-Access mode is rare in public configs; see
[`06-fixture-targets.md`](06-fixture-targets.md) for sources).
Reference:
[Cisco SD-Access Fabric Edge Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-3/configuration_guide/sda/b_173_sda_9300_cg.html).
Cisco DevNet Sandbox / Cisco CML pre-built Catalyst-9300 SDA
images are the recommended provenance.

### Field mapping table

| IOS-XE source | Canonical destination | Notes |
|---|---|---|
| `fabric forwarding anycast-gateway-mac <MAC>` | Top-level: `intent.anycast_gateway_mac = "<MAC>"` | One per device; mirrors EOS system-wide field |
| `interface Vlan<N> / fabric forwarding mode anycast-gateway` + `ip address X MASK` | On the matching `CanonicalVlan(id=N)`: augment the existing primary address with `virtual_gateway_address="<X>"` (the same value as `ip`) | NX-OS-shape: primary IP IS the anycast IP. Render-side detects `ip == virtual_gateway_address` and re-emits both lines |

### Cisco IOS-XE edge cases

1. **The `fabric forwarding mode anycast-gateway` line is the
   discriminator.** Without it, the same `ip address X MASK` is
   a regular SVI primary. Parser must look for the
   `fabric forwarding mode anycast-gateway` line on the same SVI
   stanza and, when present, set `virtual_gateway_address = ip`
   on every IPv4 address record for that SVI.

2. **No per-SVI MAC override.** IOS-XE only models the system-wide
   `fabric forwarding anycast-gateway-mac`. Cross-vendor migration
   from Junos (with per-unit MACs) to IOS-XE SD-Access surfaces
   the same review banner described in EOS edge case 1.

3. **SD-Access mode is a chassis-wide mode.** Not every Catalyst-9k
   running IOS-XE is in SD-Access mode. The
   `fabric forwarding mode anycast-gateway` line itself is the
   reliable per-SVI discriminator; no need to also detect
   chassis-wide mode.

4. **CLI vs NETCONF.** The work targets the
   `cisco_iosxe_cli` codec only. The `cisco_iosxe` (NETCONF /
   OpenConfig) codec is a Phase 0.5 stub that only emits
   `openconfig-interfaces`; anycast support there is out of
   scope (declared `unsupported` on its capability matrix
   alongside everything else).

5. **`ip address` order matters in some configs.** Cisco IOS-XE
   accepts `fabric forwarding mode anycast-gateway` either
   before or after `ip address`. The parser must accumulate the
   `fabric_forwarding_anycast` flag per-SVI and apply it to
   every address at stanza-close time, not at line-time.

---

## Cisco NX-OS DAG (Tier-D; depends on NX-OS codec landing)

### Grammar

```text
# System-wide anycast-gateway MAC:
fabric forwarding anycast-gateway-mac <MAC>

# Per-SVI anycast IP (anycast trailer marks the address):
interface Vlan<N>
   ip address <X>/<M> anycast
   fabric forwarding mode anycast-gateway
```

### Source citation

No real-capture fixture today; depends on NX-OS codec landing
([`tests/fixtures/real/WANTED.md`](../../../tests/fixtures/real/WANTED.md)
§ "Tier-D — entirely-new codec opportunities" lists Batfish
`snapshots/nxos_evpn_l3vni/configs/` as the seed corpus).

Upstream reference:
[Cisco NX-OS BGP-EVPN VXLAN configuration guide](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/93x/vxlan-93x/configuration/guide/b-cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-93x.html).

### Field mapping table

| NX-OS source | Canonical destination | Notes |
|---|---|---|
| `fabric forwarding anycast-gateway-mac <MAC>` (system-wide) | Top-level: `intent.anycast_gateway_mac = "<MAC>"` | Vendors agree on grammar with IOS-XE SD-Access |
| `interface Vlan<N> / ip address X/M anycast` + `fabric forwarding mode anycast-gateway` | On the matching `CanonicalVlan(id=N)`: `CanonicalIPv4Address(ip="<X>", prefix_length=M, virtual_gateway_address="<X>")` | The `anycast` trailer marks the primary IP slot AS the anycast gateway; both fields carry the same value (NX-OS shape — see [01-canonical-model.md § "NX-OS shape note"](01-canonical-model.md)) |

### NX-OS edge cases (sketched; final per T3)

1. **The `anycast` trailer is the per-line discriminator.** Unlike
   IOS-XE SD-Access (which requires `fabric forwarding mode
   anycast-gateway` to indicate intent), NX-OS DAG marks each IP
   address directly with the `anycast` trailer.

2. **Per-VLAN `fabric forwarding mode anycast-gateway` is still
   required.** NX-OS commit-time validator rejects `ip address
   X/M anycast` without the per-SVI mode line. Parser doesn't
   need to enforce; just propagate both.

3. **Distributed Anycast Gateway (DAG) vs Centralised Anycast
   Gateway (CAG).** NX-OS supports both. DAG is the one the
   canonical model covers; CAG semantics differ slightly (head-end
   replication; out of scope for v0.2.0). Parser only handles
   the DAG form.

4. **Per-SVI MAC override.** NX-OS does NOT have a per-SVI MAC
   override grammar. System-wide only.

---

## Aruba AOS-CX (Tier-D; depends on AOS-CX codec landing)

### Grammar (sketched)

```text
interface vlan<N>
   ip address <X>/<Y> virtual
   ipv6 address <X>/<Y> virtual
```

### Source citation

No real-capture today; depends on AOS-CX codec (Tier-D in
WANTED.md). Sources:
[`arubanetworks/` GitHub org](https://github.com/arubanetworks),
NAPALM AOS-CX driver.

### Field mapping table

Mirror of Arista EOS VARP shape; the `virtual` trailer marks the
address as the anycast gateway, no per-leaf primary.

| AOS-CX source | Canonical destination |
|---|---|
| `interface vlan<N> / ip address <X>/<Y> virtual` | On the matching `CanonicalVlan(id=N)`: `CanonicalIPv4Address(ip="", prefix_length=Y, virtual_gateway_address="<X>")` |
| `interface vlan<N> / ipv6 address <X>/<Y> virtual` | Same pattern with `CanonicalIPv6Address` |

### AOS-CX edge cases (sketched; final per AOS-CX codec implementor)

1. AOS-CX uses lower-case `vlan<N>` interface names (matches
   Aruba AOS-S convention) — distinct from EOS's `Vlan<N>` and
   Cisco's `Vlan<N>`. Cross-vendor port-rename mesh handles.

2. The `virtual` trailer is the discriminator. Mirror of EOS
   VARP — no system-wide MAC declaration documented in current
   AOS-CX 10.x reference (would need verification once the codec
   lands).

---

## FortiGate (no native anycast — declare `unsupported`)

FortiGate's only L3-hop-redundancy primitive is VRRP
(`config router vrrp / edit N / set vrip X` — feeds into T1).
No native anycast-gateway grammar. The capability matrix declares:

```text
unsupported:
  - /interfaces/interface/ipv4/address/virtual-gateway-address
  - /interfaces/interface/ipv6/address/virtual-gateway-address
  - /system/anycast-gateway-mac
```

Cross-vendor migration from a Junos / EOS source carrying anycast
into a FortiGate target surfaces the standard validation banner
("Anycast gateway not supported on FortiGate; configure VRRP
manually if HA redundancy required").

---

## MikroTik RouterOS (no native anycast — declare `unsupported`)

RouterOS has `/ip vrrp` (the standard VRRP) and `/interface
ethernet switch host` for MAC-table tricks but NO native
anycast-gateway primitive. Same `unsupported` declaration as
FortiGate.

---

## OPNsense (no native anycast — declare `unsupported`)

OPNsense uses CARP (Common Address Redundancy Protocol) for L3 HA
— semantically distinct from anycast (CARP is master/backup with
preempt, no "always present on every leaf" property). No native
anycast-gateway primitive. Same `unsupported` declaration as
FortiGate.

---

## MAC format normalisation

Vendors disagree on MAC string format. The canonical surface
stores in colon-hex (the OUI canonical form); per-vendor
renderers re-emit native.

| Vendor | Native format | Example |
|---|---|---|
| Arista EOS | colon-hex | `00:1c:73:00:dc:01` |
| Juniper Junos | colon-hex | `02:00:21:00:00:01` |
| Cisco IOS-XE / NX-OS | dotted-triplet (lower-case hex) | `0001.c73a.0000` |
| Aruba AOS-CX | colon-hex (verify against AOS-CX 10.x docs) | `00:1c:73:00:dc:01` |

Canonical store: **colon-hex** (matches Arista / Junos native
format). Helper:
`netcanon.migration._mac_format.normalise_to_colon_hex(s)` would
convert any of the three on parse, and per-codec render-side
helpers convert from canonical to native. Same pattern as the
existing
`netcanon/migration/canonical/snmpv3_user_names.py` normalisation.
(Helper module is new; ~30 LOC across parse + render.)

---

## Summary

* **Three vendors with current grammar that needs wiring:** Junos
  (per-IRB-unit), Arista EOS (per-Vlan-SVI VARP), Cisco IOS-XE
  CLI (SD-Access mode).
* **Two Tier-D vendors with grammar awaiting their codec:** Cisco
  NX-OS (DAG), Aruba AOS-CX.
* **Three vendors with no native grammar:** FortiGate, MikroTik,
  OPNsense. Declare `unsupported`.
* **The QFX10K2 fixture is the comprehensive real-capture
  reference** for Junos (7 units, both v4 and v6, per-unit MAC
  overrides on both families).
* **Two Batfish EOS fixtures cover VARP**
  (`batfish_eos_evpn_vlan_based_leaf.txt`,
  `batfish_labval_dc1_leaf2a_eos4230.txt` — 14 total VARP SVIs +
  system-wide MAC).
* **Edge cases that demand explicit parser handling:** Junos
  per-unit MAC override (applies to all addresses on the unit;
  order-independent of address lines); EOS `secondary` trailer
  (must preserve, distinct from `source-nat`); IOS-XE
  `fabric forwarding mode anycast-gateway` SVI discriminator
  (order-independent of `ip address`).
