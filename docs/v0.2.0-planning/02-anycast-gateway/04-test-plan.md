# 04 — Test plan

Unit + integration + real-capture tests for the anycast-gateway
canonical surface. Test names follow the existing
`tests/unit/migration/test_<vendor>.py` convention.

---

## 1. Schema-level tests (~6 tests)

**File:** `tests/unit/migration/test_anycast_schema.py` (NEW)

| Test | Asserts |
|---|---|
| `test_default_v4_address_empty_anycast` | `CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24).virtual_gateway_address == ""` |
| `test_default_v4_address_empty_mac` | `CanonicalIPv4Address(...).virtual_gateway_mac == ""` |
| `test_default_v6_address_empty_anycast` | `CanonicalIPv6Address(...).virtual_gateway_address == ""` |
| `test_default_intent_empty_system_mac` | `CanonicalIntent().anycast_gateway_mac == ""` |
| `test_is_secondary_default_false` | `CanonicalIPv4Address(...).is_secondary is False` |
| `test_pydantic_round_trip_anycast_fields` | `CanonicalIPv4Address.model_validate(CanonicalIPv4Address(ip="x", prefix_length=24, virtual_gateway_address="y", virtual_gateway_mac="z").model_dump()).virtual_gateway_address == "y"` |

---

## 2. Juniper Junos — parse tests (~6 tests)

**File:** `tests/unit/migration/test_juniper_junos_anycast.py` (NEW;
sibling to existing `test_juniper_junos.py`)

| Test | Source snippet | Assert |
|---|---|---|
| `test_parse_irb_v4_virtual_gateway_address` | `set interfaces irb unit 100 family inet address 10.0.0.5/24 virtual-gateway-address 10.0.0.1` + `set vlans V100 vlan-id 100` + `set vlans V100 l3-interface irb.100` | `intent.vlans[0].ipv4_addresses[0].virtual_gateway_address == "10.0.0.1"` |
| `test_parse_irb_v6_virtual_gateway_address` | `set interfaces irb unit 100 family inet6 address fd00::5/64 virtual-gateway-address fd00::1` (same VLAN binding) | `intent.vlans[0].ipv6_addresses[0].virtual_gateway_address == "fd00::1"` |
| `test_parse_irb_v4_mac_override` | The v4 snippet above + `set interfaces irb unit 100 virtual-gateway-v4-mac 02:00:00:00:00:01` | `intent.vlans[0].ipv4_addresses[0].virtual_gateway_mac == "02:00:00:00:00:01"` |
| `test_parse_irb_v6_mac_override` | The v6 snippet above + `set interfaces irb unit 100 virtual-gateway-v6-mac 02:00:00:06:00:01` | `intent.vlans[0].ipv6_addresses[0].virtual_gateway_mac == "02:00:00:06:00:01"` |
| `test_parse_irb_link_local_no_anycast` | `set interfaces irb unit 100 family inet6 address fe80::1/64` (no virtual-gateway-address) | The link-local address has `virtual_gateway_address == ""` even with an unrelated anycast IP on the same unit |
| `test_parse_irb_mac_before_addresses_order_independent` | MAC line FIRST then address lines | MAC still attaches to the address records |

---

## 3. Juniper Junos — render tests (~6 tests)

**File:** `tests/unit/migration/test_juniper_junos_anycast.py` (same)

| Test | Input canonical | Assert in rendered output |
|---|---|---|
| `test_render_irb_v4_virtual_gateway_address` | `CanonicalVlan(id=100, ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.5", prefix_length=24, virtual_gateway_address="10.0.0.1")])` | Contains `set interfaces irb unit 100 family inet address 10.0.0.5/24 virtual-gateway-address 10.0.0.1` |
| `test_render_irb_v6_virtual_gateway_address` | Mirror v6 input | Contains `... family inet6 address fd00::5/64 virtual-gateway-address fd00::1` |
| `test_render_irb_v4_mac_override` | V4 input above with `virtual_gateway_mac="02:00:00:00:00:01"` | Contains `set interfaces irb unit 100 virtual-gateway-v4-mac 02:00:00:00:00:01` (after the address lines) |
| `test_render_irb_v6_mac_override` | Mirror v6 | Contains `... virtual-gateway-v6-mac 02:00:00:06:00:01` |
| `test_render_no_anycast_no_emit` | Plain IPv4 with no anycast fields | Output does NOT contain `virtual-gateway-address` |
| `test_render_deterministic_order_anycast_then_mac` | Mix of address + MAC fields | The MAC emit lines appear AFTER the address lines (matches the QFX10K2 fixture order) |

---

## 4. Juniper Junos — round-trip tests (~3 tests)

| Test | Input | Procedure | Assert |
|---|---|---|---|
| `test_round_trip_irb_anycast_v4_v6` | Synthetic snippet covering both v4 and v6 anycast on one unit | parse → render → parse | Second parse produces an `intent` equal to the first parse's `intent` |
| `test_round_trip_irb_mac_override` | Synthetic snippet with both per-unit MAC overrides | parse → render → parse | MAC fields preserved end-to-end |
| `test_round_trip_qfx10k2_fixture` | `tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set` | parse → render → parse | Anycast / MAC fields preserved on all 7 IRB units; the 4 IRB units with `proxy-macip-advertisement` still drop that line (Tier-3, not in scope) |

---

## 5. Arista EOS — parse tests (~6 tests)

**File:** `tests/unit/migration/test_arista_eos_anycast.py` (NEW)

| Test | Source snippet | Assert |
|---|---|---|
| `test_parse_vlan_svi_ip_address_virtual` | `interface Vlan10\n   ip address virtual 10.0.0.1/24` | `intent.vlans[0].ipv4_addresses[0].virtual_gateway_address == "10.0.0.1"` (via SVI fold) |
| `test_parse_vlan_svi_ip_address_virtual_secondary` | Same + `   ip address virtual 10.0.100.1/24 secondary` | Second record has `is_secondary == True`, first has `is_secondary == False` |
| `test_parse_top_level_ip_virtual_router_mac` | `ip virtual-router mac-address 00:1c:73:00:dc:01` | `intent.anycast_gateway_mac == "00:1c:73:00:dc:01"` |
| `test_parse_ip_address_virtual_source_nat_is_tier3` | `ip address virtual source-nat vrf X address 10.255.1.4` | `intent.anycast_gateway_mac == ""`; no canonical field set; `dropped_tier3_sections` may flag it |
| `test_parse_ipv6_address_virtual` | `interface Vlan10\n   ipv6 address virtual fd00::1/64` | `intent.vlans[0].ipv6_addresses[0].virtual_gateway_address == "fd00::1"` |
| `test_parse_mac_format_normalisation` | `ip virtual-router mac-address 001c.7300.dc01` (dotted-triplet — Cisco-style) | Normalised to `00:1c:73:00:dc:01` |

---

## 6. Arista EOS — render tests (~6 tests)

| Test | Input | Assert |
|---|---|---|
| `test_render_vlan_svi_ip_address_virtual` | `CanonicalVlan(id=10, ipv4_addresses=[CanonicalIPv4Address(ip="", prefix_length=24, virtual_gateway_address="10.0.0.1")])` | Contains `   ip address virtual 10.0.0.1/24` under `interface Vlan10` |
| `test_render_secondary_trailer` | Address record with `is_secondary=True` | Contains `   ip address virtual ... secondary` |
| `test_render_top_level_ip_virtual_router_mac` | `intent.anycast_gateway_mac = "00:1c:73:00:dc:01"` | Output contains `ip virtual-router mac-address 00:1c:73:00:dc:01` at top level |
| `test_render_no_per_iface_mac_on_eos` | Address with `virtual_gateway_mac="02:00:00:00:00:01"` and no system-wide field | Output contains a comment-form review line (not a per-iface mac emit) — also fills system-wide field with the first observed MAC |
| `test_render_ipv6_virtual` | `CanonicalIPv6Address(ip="", prefix_length=64, virtual_gateway_address="fd00::1")` on VlanN | Contains `ipv6 address virtual fd00::1/64` |
| `test_render_no_anycast_no_emit` | Plain primary | Output does NOT contain `ip address virtual` or `ip virtual-router mac-address` |

---

## 7. Arista EOS — round-trip tests (~3 tests)

| Test | Input | Assert |
|---|---|---|
| `test_round_trip_eos_varp_synthetic` | Synthetic VARP snippet with primary + secondary + system MAC | parse → render → parse: all fields preserved |
| `test_round_trip_batfish_evpn_vlan_based_leaf` | `tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt` | 6 VARP-bearing SVIs preserved (incl. secondary on Vlan110); system-wide MAC preserved; `source-nat` lines stay Tier-3-dropped |
| `test_round_trip_batfish_labval_leaf2a` | `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt` | 8 VARP-bearing SVIs preserved; system-wide MAC preserved |

---

## 8. Cisco IOS-XE CLI — parse tests (~5 tests)

**File:** `tests/unit/migration/test_cisco_iosxe_cli_anycast.py` (NEW)

| Test | Source snippet | Assert |
|---|---|---|
| `test_parse_sda_svi_anycast_mode` | `interface Vlan10\n ip address 10.0.0.1 255.255.255.0\n fabric forwarding mode anycast-gateway` | Address record has `ip == "10.0.0.1"` AND `virtual_gateway_address == "10.0.0.1"` (mirror) |
| `test_parse_sda_top_level_mac` | `fabric forwarding anycast-gateway-mac 0001.c73a.0000` | `intent.anycast_gateway_mac == "00:01:c7:3a:00:00"` (normalised) |
| `test_parse_sda_mode_line_order_indep_before` | `fabric forwarding mode anycast-gateway` line BEFORE the `ip address` line | Address still gets `virtual_gateway_address` set |
| `test_parse_sda_mode_line_order_indep_after` | `fabric forwarding mode anycast-gateway` AFTER `ip address` | Same |
| `test_parse_no_mode_line_no_anycast` | `interface Vlan10\n ip address 10.0.0.1 255.255.255.0` (no `fabric forwarding mode`) | `virtual_gateway_address == ""` (regular SVI primary, not anycast) |

---

## 9. Cisco IOS-XE CLI — render tests (~4 tests)

| Test | Input | Assert |
|---|---|---|
| `test_render_sda_svi_anycast` | `CanonicalVlan(id=10, ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24, virtual_gateway_address="10.0.0.1")])` | Output contains `ip address 10.0.0.1 255.255.255.0` AND `fabric forwarding mode anycast-gateway` on the same interface stanza |
| `test_render_sda_top_level_mac_dotted_triplet` | `intent.anycast_gateway_mac = "00:01:c7:3a:00:00"` | Output contains `fabric forwarding anycast-gateway-mac 0001.c73a.0000` |
| `test_render_no_anycast_no_emit` | Plain primary | No `fabric forwarding mode` line emitted |
| `test_render_anycast_only_first_emit_per_iface` | Multiple address records on same SVI all with `virtual_gateway_address` set | Single `fabric forwarding mode anycast-gateway` line emitted (not duplicated per address) |

---

## 10. Cisco IOS-XE CLI — round-trip tests (~2 tests)

| Test | Input | Assert |
|---|---|---|
| `test_round_trip_iosxe_sda_synthetic` | Synthetic SDA-mode snippet | parse → render → parse: anycast intact |
| `test_round_trip_iosxe_no_anycast_unchanged` | Plain SVI primary (no anycast) | parse → render → parse: identical to baseline (no spurious `fabric forwarding mode` emission) |

---

## 11. Cross-vendor migration tests (~15 tests)

**File:** `tests/unit/migration/test_cross_vendor_anycast.py` (NEW)

These tests use the existing migration pipeline
(`netcanon.services.migration_plan.run_plan`) and assert that the
anycast surface survives the canonical bridge.

| Test | Source codec | Target codec | Source snippet | Assert in target output |
|---|---|---|---|---|
| `test_junos_to_eos_v4_anycast` | `juniper_junos` | `arista_eos` | QFX10K2-style unit 100 with virtual-gateway-address | EOS output has `interface Vlan100 / ip address virtual <addr>/<prefix>` |
| `test_junos_to_eos_system_wide_mac_from_per_unit` | `juniper_junos` | `arista_eos` | QFX10K2 fixture with multiple per-unit MACs (DIFFERENT MACs on different units) | EOS system-wide MAC set to FIRST observed; review banner emitted |
| `test_eos_to_junos_v4_anycast` | `arista_eos` | `juniper_junos` | VARP `ip address virtual 10.0.0.1/24` on Vlan10 | Junos output has `set interfaces irb unit 10 family inet address ... virtual-gateway-address 10.0.0.1` |
| `test_eos_to_junos_no_per_leaf_primary_review` | `arista_eos` | `juniper_junos` | VARP with no per-leaf primary | Render emits a comment-form review line stating "EOS VARP source has no per-leaf primary" |
| `test_iosxe_to_eos_anycast` | `cisco_iosxe_cli` | `arista_eos` | SDA-mode SVI | EOS output has `ip address virtual` + system MAC |
| `test_eos_to_iosxe_anycast` | `arista_eos` | `cisco_iosxe_cli` | VARP | IOS-XE output has SDA-mode lines |
| `test_junos_to_iosxe_anycast` | `juniper_junos` | `cisco_iosxe_cli` | QFX10K2 v4 anycast | IOS-XE has `fabric forwarding mode anycast-gateway` and system MAC |
| `test_iosxe_to_junos_anycast` | `cisco_iosxe_cli` | `juniper_junos` | SDA-mode | Junos has `set interfaces irb unit ... virtual-gateway-address ...` |
| `test_eos_to_fortigate_unsupported_banner` | `arista_eos` | `fortigate_cli` | VARP | Validation result is `block` severity; anycast paths in unsupported list |
| `test_eos_to_mikrotik_unsupported_banner` | `arista_eos` | `mikrotik_routeros` | VARP | Same |
| `test_eos_to_opnsense_unsupported_banner` | `arista_eos` | `opnsense` | VARP | Same |
| `test_eos_to_aruba_aoss_unsupported_banner` | `arista_eos` | `aruba_aoss` | VARP | Same |
| `test_junos_v6_to_eos_v6_anycast` | `juniper_junos` | `arista_eos` | IPv6 anycast on irb | EOS output has `ipv6 address virtual fd00::1/64` |
| `test_anycast_mac_format_canonicalisation_iosxe_to_eos` | `cisco_iosxe_cli` | `arista_eos` | Source MAC `0001.c73a.0000` | EOS target re-emits as `00:1c:73:00:dc:01` (colon-hex) — wait, correction: `0001.c73a.0000` → colon-hex `00:01:c7:3a:00:00` |
| `test_secondary_varp_survives_round_trip` | `arista_eos` | `arista_eos` | VARP with secondary trailer | Round-trip via canonical: secondary preserved |

---

## 12. Real-capture round-trip — `test_real_captures.py` extensions (~6 assertions)

**File extension:** `tests/unit/migration/test_real_captures.py`
(existing)

The existing harness asserts (a) parse doesn't crash, (b) parse
populates at least one canonical field, (c) parse(render(parse(raw)))
matches parse(raw) for bidirectional codecs. The new assertions:

| Fixture | New assertion |
|---|---|
| `tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set` | After parse, `len([a for v in intent.vlans for a in v.ipv4_addresses if a.virtual_gateway_address])` should be **7** (one per IRB unit) |
| Same fixture | After parse, `len([a for v in intent.vlans for a in v.ipv6_addresses if a.virtual_gateway_address])` should be **6** (units 2021-2025+2031 with v6 anycast; the link-local-only line on unit 2031 is excluded) |
| Same fixture | After parse, `intent.anycast_gateway_mac == ""` (Junos has no system-wide field) |
| Same fixture | After round-trip, the rendered output contains the substring `virtual-gateway-address 10.221.0.1` (lossless preservation check) |
| `tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt` | After parse, `intent.anycast_gateway_mac == "00:dc:00:00:00:01"` |
| `tests/fixtures/real/arista_eos/batfish_eos_evpn_vlan_based_leaf.txt` | After parse, the SVI for `Vlan110` has 2 IPv4 addresses, the second with `is_secondary=True` |

---

## 13. Determinism tests (~5 tests)

**File:** `tests/unit/migration/test_anycast_determinism.py` (NEW)

| Test | Assert |
|---|---|
| `test_junos_render_deterministic_across_runs` | Render the same canonical tree 10 times; byte-identical output every time |
| `test_eos_render_deterministic_across_runs` | Same for EOS |
| `test_iosxe_render_deterministic_across_runs` | Same for IOS-XE |
| `test_intent_serialisation_deterministic` | `intent.model_dump_json()` byte-identical across runs |
| `test_parse_order_independence_for_per_unit_mac` | Junos source with MAC line BEFORE and AFTER address lines produces the same canonical tree |

---

## 14. Tier-3 detection tests (~3 tests)

**File extension:** `tests/unit/migration/test_tier3_detection.py`
(existing)

The anycast-gateway grammar should NOT trigger any of the existing
Tier-3 patterns (it's a canonical-modelled surface, not a dropped
one). Existing patterns are mostly firewall / NAT / policy.

| Test | Source | Assert |
|---|---|---|
| `test_junos_anycast_not_tier3` | QFX10K2 fixture | `dropped_tier3_sections` does NOT contain `virtual-gateway` / `irb` substrings |
| `test_eos_anycast_not_tier3` | Batfish EVPN leaf fixture | `dropped_tier3_sections` does NOT mention `ip address virtual` |
| `test_eos_anycast_source_nat_still_tier3` | A snippet with `ip address virtual source-nat vrf X address Y` | The SOURCE-NAT line IS flagged Tier-3 (it's a NAT primitive); the regular anycast lines are NOT |

---

## 15. Capability-matrix validation tests (~4 tests)

**File:** `tests/unit/migration/test_capability_matrix_anycast.py`
(NEW)

| Test | Assert |
|---|---|
| `test_supporting_codecs_declare_anycast_supported` | For each of `juniper_junos`, `arista_eos`, `cisco_iosxe_cli`: `capabilities.classify("/interfaces/interface/ipv4/address/virtual-gateway-address") == "supported"` |
| `test_unsupporting_codecs_declare_anycast_unsupported` | For each of `fortigate_cli`, `mikrotik_routeros`, `opnsense`, `aruba_aoss`, `cisco_iosxe`: the same xpath is `"unsupported"` |
| `test_eos_per_iface_mac_lossy` | `arista_eos.capabilities.classify("/interfaces/interface/ipv4/address/virtual-gateway-mac") == "lossy"` |
| `test_iosxe_system_mac_supported` | `cisco_iosxe_cli.capabilities.classify("/system/anycast-gateway-mac") == "supported"` |

---

## 16. Tier-3 rename pane integration (~2 tests)

If the implementation adds the `anycast_gateway` rename pane (sixth
category — sketched in
[`01-canonical-model.md`](01-canonical-model.md) § "How operators
express..."), add:

**File:** `tests/unit/migration/test_run_plan_overrides_anycast.py`
(NEW; sibling to existing `test_run_plan_overrides.py`)

| Test | Assert |
|---|---|
| `test_anycast_gateway_rename_clear_system_mac` | `MigrationPlanRequest(anycast_gateway_rename_map={"00:1c:73:00:dc:01": None})` causes `intent.anycast_gateway_mac` to clear before render |
| `test_anycast_gateway_rename_rewrite_system_mac` | Map rewrites the system MAC end-to-end |

(If the rename pane is deferred to a follow-up, skip these tests.)

---

## Test count summary

| Section | Tests |
|---|---|
| §1 Schema | 6 |
| §2 Junos parse | 6 |
| §3 Junos render | 6 |
| §4 Junos round-trip | 3 |
| §5 EOS parse | 6 |
| §6 EOS render | 6 |
| §7 EOS round-trip | 3 |
| §8 IOS-XE parse | 5 |
| §9 IOS-XE render | 4 |
| §10 IOS-XE round-trip | 2 |
| §11 Cross-vendor | 15 |
| §12 Real-capture extensions | 6 |
| §13 Determinism | 5 |
| §14 Tier-3 detection | 3 |
| §15 Capability matrix | 4 |
| §16 Rename pane (optional) | 2 |
| **Total** | **82** (or 80 without rename pane) |

This matches the ~70 estimate in
[`README.md`](README.md) § "Estimated total LOC + test count"
with some headroom for edge cases discovered during
implementation.

---

## Real-capture round-trip is the single canary metric

The QFX10K2 fixture exercises 7 IRB units × (v4 + v6 anycast) +
per-unit v4-mac + per-unit v6-mac. The strongest single
implementation signal is:

```python
def test_round_trip_qfx10k2_anycast_lossless():
    raw = Path(QFX10K2_PATH).read_text()
    codec = JunosCodec()
    intent_first = codec.parse(raw)
    rendered = codec.render(intent_first)
    intent_second = codec.parse(rendered)
    assert intent_first == intent_second   # pydantic structural equality
```

If this passes, every per-unit address, every per-unit MAC, and
the v4/v6 split all round-trip. If it fails, the failure delta
points to the broken touchpoint.

---

## Test runner integration

The existing real-fixture harness
(`tests/unit/migration/test_real_captures.py`) already runs
parse + parse(render(parse(raw))) for every fixture in
`tests/fixtures/real/<vendor>/`. The new assertions in §12 plug
into that loop via per-fixture-name conditional checks:

```python
def test_real_capture_anycast_invariant(fixture_path):
    # ... existing harness setup ...
    if "qfx10k2" in fixture_path.name:
        assert sum(1 for v in intent.vlans for a in v.ipv4_addresses
                   if a.virtual_gateway_address) == 7
    if "batfish_eos_evpn_vlan_based_leaf" in fixture_path.name:
        assert intent.anycast_gateway_mac == "00:dc:00:00:00:01"
    # ... etc
```

This pattern is already established in the harness for similar
shape-specific invariants on the VRF / VxLAN fixtures.
