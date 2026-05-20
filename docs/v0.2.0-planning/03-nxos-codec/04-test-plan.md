# 04 — Test plan

Unit + integration + cross-vendor test surface for the NX-OS codec,
broken out per implementation phase.

Test infrastructure:
* Live test module: `tests/unit/migration/test_cisco_nxos.py`
* Real-capture fixtures: `tests/fixtures/real/nx_os/<fixture>.txt`
* Synthetic fixtures: `tests/fixtures/nxos/<fixture>.txt`
* Cross-vendor migration tests: extend
  `tests/integration/migration/test_cross_vendor.py` (or sibling
  module if cross-vendor lives elsewhere — see § 6).

> **CRITICAL infrastructure step** (often missed):
> `tests/unit/migration/test_real_captures.py` has a hard-coded
> dispatch table at lines 80-88 (`_DIR_TO_CODEC_NAME`).  When the
> Phase 1 PR introduces the `tests/fixtures/real/nx_os/` directory,
> the **same PR** MUST add the row:
>
> ```python
> _DIR_TO_CODEC_NAME: dict[str, str] = {
>     ...
>     "nx_os":        "cisco_nxos",
> }
> ```
>
> Without this, `test_every_fixture_dir_has_codec_mapping` fails
> with `KeyError: 'nx_os'` and the codec can't be tested against
> real captures at all.  Reviewer's checklist: confirm this row
> exists.

---

## 1. Test module scaffold (`test_cisco_nxos.py`)

Mirror `tests/unit/migration/test_cisco_iosxe_cli.py` shape.
Estimated test-class layout across the full 4-phase ship:

### Phase 1 classes

```python
class TestR3Fields:
    """codec metadata (direction / certainty / canonical_model / input_format)"""

class TestRegistry:
    """codec is registered with the right name; get_codec resolves"""

class TestProbe:
    """probe ladder — primary banner + secondary structural"""
    def test_probe_primary_command_banner(self): ...
    def test_probe_primary_with_structural(self): ...
    def test_probe_secondary_feature_block(self): ...
    def test_probe_secondary_vdc(self): ...
    def test_probe_secondary_nve1(self): ...
    def test_probe_rejects_iosxe_banner(self): ...
    def test_probe_rejects_xml(self): ...
    def test_probe_rejects_json(self): ...
    def test_probe_rejects_aruba_banner(self): ...

class TestParseHostname:
    """`hostname X` round-trip"""

class TestParseVersion:
    """version 9.2(3) → source_version"""

class TestParseVDCBlock:
    """vdc <name> id 1 / limit-resource ... preserved in raw_sections"""

class TestParseVlanTopLevel:
    """`vlan 1`, `vlan 1,10,2000`, `vlan 10-20` all parse correctly"""
    def test_single_id(self): ...
    def test_comma_list(self): ...
    def test_range(self): ...
    def test_mixed_comma_range(self): ...
    def test_vlan_name_sub_line(self): ...

class TestParseVrfContext:
    """`vrf context X` and its rd / RT / l3-vni sub-lines"""
    def test_vrf_management_minimal(self): ...
    def test_vrf_tenant_with_rd_auto(self): ...
    def test_vrf_l3vni_binding(self): ...
    def test_vrf_rt_import_export(self): ...
    def test_vrf_rt_both_evpn(self): ...

class TestParseInterfaceBasics:
    """interface Ethernet1/N / Vlan<N> / loopback / mgmt0 / port-channel"""
    def test_ethernet_routed(self): ...
    def test_ethernet_l2_default(self): ...
    def test_ethernet_with_description(self): ...
    def test_ethernet_with_mtu(self): ...
    def test_loopback(self): ...
    def test_mgmt0_classifies_as_mgmt(self): ...
    def test_vlan_svi(self): ...
    def test_port_channel(self): ...
    def test_shutdown_disables(self): ...
    def test_no_shutdown_enables(self): ...
    def test_ip_address_cidr_form(self): ...
    def test_ipv6_address(self): ...
    def test_vrf_member_binds(self): ...
    def test_empty_interface_preserved(self): ...

class TestParseLocalUsers:
    """username X password 5 <hash> role <r>"""

class TestParseStaticRoutesTopLevel:
    """ip route DEST/N GW"""

class TestRenderHostname:
    """basic hostname-only render"""

class TestRenderVDCBlock:
    """vdc block emitted before features"""

class TestRenderFeatureBlock:
    """feature lines derived from canonical tree presence"""
    def test_no_features_when_empty_tree(self): ...
    def test_interface_vlan_when_svi_present(self): ...
    def test_lacp_when_lag_present(self): ...

class TestRoundTripPhase1:
    """parse(render(tree)) == tree for Phase 1 supported subset"""

class TestParseCLIErrors:
    """ParseError on empty / XML / JSON / wrong vendor input"""
```

**Phase 1 unit test count: ~35**

### Phase 2 classes (added)

```python
class TestParseSwitchportAccess:
    """switchport access vlan N"""

class TestParseSwitchportTrunk:
    """switchport mode trunk + allowed vlan + native"""

class TestParseL2DefaultFlip:
    """bare Ethernet1/N defaults to switchport_mode=access"""
    def test_bare_eth_is_l2(self): ...
    def test_no_switchport_makes_l3(self): ...
    def test_l3_eth_with_ip_has_no_switchport(self): ...

class TestParseLAG:
    """channel-group N mode active|passive|on + port-channelN"""

class TestParseLAGMembers:
    """channel-group sets lag_member_of; port-channelN container synthesised"""

class TestParseHSRP:
    """interface Vlan10 / hsrp 10 / preempt / ip X / priority N"""
    # Gates on T1 — skipif when T1 schema not yet in tree.

class TestParseSNMPv3User:
    """snmp-server user X auth md5 0x<hex> priv 0x<hex> localizedkey ..."""
    def test_v3_user_full(self): ...
    def test_v3_user_with_group(self): ...
    def test_v3_user_with_engine_id(self): ...
    def test_v3_user_aes_128(self): ...                  # 10.x variant
    def test_v3_user_localizedV2key_lossy(self): ...     # 10.x variant

class TestSVIVlanSynthesis:
    """SVI without matching top-level vlan stanza gets one synthesised"""

class TestRenderSwitchport:
    """render emits switchport mode + access / trunk allowed"""

class TestRenderLAG:
    """render emits interface port-channel<N> + per-member channel-group"""

class TestRenderHSRP:
    """render emits hsrp N sub-block (gates on T1)"""

class TestRenderSNMPv3:
    """render emits snmp-server user line with the right hex form"""

class TestRoundTripPhase2:
    """parse(render(tree)) == tree across Phase 2 surface"""

class TestCrossVendorIosxeToNxosL2:
    """Cisco IOS-XE switchport config translates to NX-OS"""
    def test_basic_access(self): ...
    def test_trunk_allowed(self): ...
    def test_lag_translates(self): ...
```

**Phase 2 unit test count: +50 (cumulative 85)**

### Phase 3 classes (added)

```python
class TestParseStaticRoutesPerVrf:
    """ip route inside vrf context block"""
    def test_route_in_vrf_management(self): ...
    def test_ipv6_route_per_vrf(self): ...
    def test_round_trip_vrf_field(self): ...   # exercises the schema extension

class TestParseRouterBgpAsRawSection:
    """`router bgp <asn>` block captured in raw_sections + dropped_tier3"""

class TestParseRouterOspfAsRawSection:
class TestParseRouterEigrpAsRawSection:
class TestParseACLAsRawSection:

class TestTier3DetectionNXOS:
    """detect_tier3_sections_nxos returns the expected headers"""

class TestRenderStaticRouteWithVrf:
    """render emits per-VRF static routes inside vrf context block"""

class TestRenderFeatureBgpAutoEmit:
    """`feature bgp` auto-emitted when raw_sections['router bgp'] populated"""

class TestRoundTripPhase3:
    """Phase 3 round-trip — VRF + per-VRF routes + tier-3 preserve"""

class TestCrossVendorIosxeToNxosVrf:
    """IOS-XE vrf definition → NX-OS vrf context (per-interface)"""
```

**Phase 3 unit test count: +40 (cumulative 125)**

### Phase 4 classes (added)

```python
class TestParseVxLAN:
    """vlan/vn-segment + interface nve1 + member vni + evpn block"""
    def test_vlan_vn_segment_binding(self): ...
    def test_nve1_source_interface(self): ...
    def test_nve1_l2vni_member(self): ...
    def test_nve1_l3vni_associate_vrf(self): ...
    def test_nve1_multi_vni(self): ...
    def test_evpn_block_with_rd_auto(self): ...

class TestParseFabricAnycastMac:
    """fabric forwarding anycast-gateway-mac X (gates on T2)"""

class TestParseFabricAnycastModeSvi:
    """per-SVI fabric forwarding mode anycast-gateway (gates on T2)"""

class TestRenderVxLAN:
    """render emits feature nv overlay + interface nve1 block"""
    def test_renders_feature_block(self): ...
    def test_emits_vlan_vn_segment(self): ...
    def test_emits_evpn_block(self): ...
    def test_emits_associate_vrf_for_l3vni(self): ...

class TestRenderAnycastGateway:
    """T2-gated render tests"""

class TestRoundTripPhase4:
    """full EVPN round-trip on L2VNI + L3VNI corpus"""

class TestCrossVendorAristaToNxosVxLAN:
    """Arista vxlan vlan/vni → NX-OS vlan/vn-segment + nve1"""

class TestCrossVendorNxosToJunosVxLAN:
    """NX-OS vlan/vn-segment → Junos vlans X / vxlan vni N"""

class TestCrossVendorIosxeToNxosFull:
    """IOS-XE Catalyst → NX-OS Nexus full migration corpus run"""

class TestPortIdentityVtepKind:
    """kind='vtep' classification + format (new PortKind addition)"""
```

**Phase 4 unit test count: +60 (cumulative 185)**

---

## 2. Real-capture test wiring

`tests/unit/migration/test_real_captures.py` discovers fixtures by
directory.  Each fixture's parse path is exercised by
`test_every_fixture_parses_cleanly` (the hard-gate).

### 2.1 Phase 1 wiring

* Create directory: `tests/fixtures/real/nx_os/`
* Drop in: `nxos_static_route_D1.txt` (bare-bones; ~302 lines)
* Update `_DIR_TO_CODEC_NAME`:
  ```python
  _DIR_TO_CODEC_NAME: dict[str, str] = {
      "cisco_iosxe":  "cisco_iosxe_cli",
      ...
      "nx_os":        "cisco_nxos",     # NEW
  }
  ```
* Add `NOTICE.md`-style attribution entry pointing at
  batfish/lab-validation Apache-2.0.

### 2.2 Phase 2 wiring

* Add `nxos_hsrp_nxos1.txt` (337 lines; HSRP + VLAN + port-channel)
* Add `nxos_hsrp_nxos2.txt` (sibling capture; pair-config validation)

### 2.3 Phase 3 wiring

* Add `nxos_ebgp_loop_d1.txt` (310 lines; BGP raw_section)
* Add `nxos_eigrp_nxos1.txt` (366 lines; EIGRP raw_section + per-interface activation)

### 2.4 Phase 4 wiring

* Add `nxos_evpn_l3vni_NX1.txt` (349 lines; full EVPN L3VNI)
* Add `nxos_evpn_l3vni_NX2.txt` (sibling)
* Add `nxos_evpn_l2vni_NX1.txt` (355 lines; L2VNI variant)
* OPTIONAL Phase 4.5: add 10.3(9) capture (`nxos_n9kv_r1.txt`, 191 lines)
  to clear the certified-tier "≥2 OS versions" bar — this fixture
  exercises 10.x-only features (`feature netconf`, `feature grpc`,
  `feature nxapi`, AES-128 SNMPv3 `localizedV2key`).

### 2.5 RESULTS.md snapshot rows

Each phase landing adds rows to
`tests/fixtures/real/RESULTS.md` showing per-fixture parse
coverage (mirrors existing format).  Sample row shape:

```
| nx_os/nxos_static_route_D1.txt | cisco_nxos | hostname=D1 ifaces=130 vlans=1 routes=1 lags=0 users=1 snmp=yes |
```

---

## 3. Synthetic fixtures (`tests/fixtures/nxos/`)

Hand-authored minimal samples covering each grammar surface in
isolation.  Names mirror the existing iosxe convention.

| Filename | Phase | Tests using it |
|---|---|---|
| `show_run_minimal.txt` | 1 | TestParseHostname, TestParseInterfaceBasics |
| `show_run_vrf.txt` | 1 | TestParseVrfContext |
| `show_run_vlans.txt` | 1 | TestParseVlanTopLevel |
| `show_run_l2_trunk.txt` | 2 | TestParseSwitchportTrunk |
| `show_run_lag.txt` | 2 | TestParseLAG |
| `show_run_hsrp.txt` | 2 | TestParseHSRP |
| `show_run_snmpv3_9x.txt` | 2 | TestParseSNMPv3User |
| `show_run_snmpv3_10x.txt` | 2 | TestParseSNMPv3User (v2key variant) |
| `show_run_static_routes_perVrf.txt` | 3 | TestParseStaticRoutesPerVrf |
| `show_run_bgp_raw.txt` | 3 | TestParseRouterBgpAsRawSection |
| `show_run_vxlan_l2vni.txt` | 4 | TestParseVxLAN (l2 variant) |
| `show_run_vxlan_l3vni.txt` | 4 | TestParseVxLAN (l3 variant) |
| `show_run_anycast.txt` | 4 | TestParseFabricAnycastMac (gates on T2) |

Each fixture is ≤30 lines of NX-OS config (vs 300+ in real
captures) — sharp focus on one surface.

---

## 4. Round-trip parametrised test

Per `02-codec-architecture.md` § 12, a parametrised test exercises
every fixture for the round-trip invariant:

```python
@pytest.mark.parametrize(
    "fixture",
    list((REAL_FIXTURES_ROOT / "nx_os").glob("*.txt"))
    + list((NX_OS_SYNTHETIC_FIXTURES).glob("*.txt")),
    ids=lambda p: p.name,
)
def test_round_trip(fixture):
    raw = fixture.read_text()
    codec = CiscoNXOSCodec()
    tree1 = codec.parse(raw)
    rendered = codec.render(tree1)
    tree2 = codec.parse(rendered)
    assert tree1 == tree2, f"round-trip failed for {fixture.name}"
```

Fixtures known to violate round-trip (e.g. `localizedV2key` →
`localizedkey` normalisation) are listed in
`_KNOWN_ROUNDTRIP_GAPS` with the lossy-declaration justification.

---

## 5. Cross-vendor migration tests

The Netcanon test surface already has cross-vendor pairs:

* `tests/integration/migration/test_cross_vendor*.py` (exact module
  path may vary; the implementor should locate by `find` on
  `_ARISTA_VARP_*` or similar string)

For NX-OS, the priority pairs to land Phase-by-Phase:

### Phase 2 cross-vendor tests

* **IOS-XE Catalyst → NX-OS Nexus** (L2 switching surface)
  * `GigabitEthernet1/0/24 switchport access vlan 10` →
    `Ethernet1/24 switchport access vlan 10`
  * `interface Vlan10 / ip address X Y` → `interface Vlan10 /
    ip address X/N`
  * `interface Port-channel1 / switchport mode trunk` →
    `interface port-channel1 / switchport mode trunk` (lowercase!)

### Phase 3 cross-vendor tests

* **IOS-XE → NX-OS VRF** — exercises the new `vrf` field on
  `CanonicalStaticRoute`:
  * IOS-XE `vrf definition CUSTOMER_A / rd 65000:100 / address-family
    ipv4 / route-target import 65000:100 / route-target export
    65000:100` → NX-OS `vrf context CUSTOMER_A / rd 65000:100 /
    address-family ipv4 unicast / route-target import 65000:100 /
    route-target export 65000:100`
  * `ip route vrf CUSTOMER_A 10.0.0.0 255.255.255.0 10.1.1.1` →
    indented `ip route 10.0.0.0/24 10.1.1.1` inside the VRF block.

### Phase 4 cross-vendor tests

* **Arista EOS → NX-OS** (EVPN-VXLAN)
  * Arista `vlan 10 / name PROD / vxlan vni 5010` + `interface
    Vxlan1 / vxlan source-interface Loopback0 / vxlan vlan 10 vni
    5010` → NX-OS `vlan 10 / name PROD / vn-segment 5010` +
    `interface nve1 / source-interface loopback0 / member vni
    5010`.
* **NX-OS → Junos** (EVPN-VXLAN reverse)
  * NX-OS `vlan 10 / vn-segment 5010` + `nve1 / member vni 5010` →
    Junos `vlans VLAN10 { vlan-id 10 ; vxlan { vni 5010 ; } }`.
* **NX-OS → Arista** (full DC vendor swap, L2VNI + L3VNI fabric)

### Cross-vendor test count

~15 cross-vendor tests across Phases 2-4.

---

## 6. Pipeline integration tests

Beyond unit tests, the pipeline orchestrator
(`netcanon.services.migration_pipeline`) needs at least one
test per phase that exercises the full plan path:

```python
class TestPipelineWithNXOSCodec:
    def test_phase1_minimal_pipeline(self):
        """source: NX-OS, target: NX-OS, no transforms, basic plan"""

    def test_phase2_iosxe_to_nxos(self):
        """source: IOS-XE Catalyst capture, target: NX-OS, switchport
        migration"""

    def test_phase3_per_vrf_static_route_round_trip(self):
        """NX-OS source → NX-OS target with the new VRF field"""

    def test_phase4_arista_to_nxos_evpn(self):
        """Full Arista EVPN-VXLAN fabric → NX-OS render"""
```

---

## 7. Estimated test counts (cumulative)

| Test category | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| Unit tests in `test_cisco_nxos.py` | 35 | 85 | 125 | 185 |
| Real-capture fixtures wired | 1 | 3 | 5 | 8 |
| Synthetic fixtures | 3 | 7 | 9 | 12 |
| Cross-vendor tests | 0 | 4 | 8 | 15 |
| Pipeline integration tests | 1 | 2 | 3 | 4 |
| Round-trip parametrised cases | 4 (3 synth + 1 real) | 10 | 14 | 22 |
| **Total per-phase** | **44** | **111** | **164** | **246** |

LOC budget per phase test code: ~250 / 450 / 400 / 700 (cumulative
1,800-2,400 LOC of tests).

---

## 8. Test marker conventions

Mirror the existing codecs:

```python
pytestmark = pytest.mark.unit
```

For long-running cross-vendor round-trip tests:
```python
@pytest.mark.slow
```

For T1 / T2 gated tests:
```python
pytest.importorskip("netcanon.migration.canonical.vrrp")    # T1 schema
pytest.importorskip("netcanon.migration.canonical.anycast") # T2 schema
```

— OR use a feature-flag fixture:
```python
@pytest.fixture
def t1_landed() -> bool:
    """True when T1's CanonicalVRRPGroup is in the canonical tree."""
    from netcanon.migration.canonical import intent
    return hasattr(intent, "CanonicalVRRPGroup")
```

---

## 9. Test data attribution

Every batfish-sourced fixture must reference Apache-2.0 attribution
in the per-fixture test docstring + add a row to
`tests/fixtures/real/NOTICE.md`:

```
nx_os/nxos_hsrp_nxos1.txt — batfish/lab-validation
  snapshots/nxos_hsrp/configs/nxos1/show_running-config.txt
  License: Apache-2.0
  Sanitisation: none (lab capture; no real IPs / hostnames)
```

---

## 10. Critical wiring checklist (for the implementor)

When the Phase 1 PR opens, the reviewer should verify each of:

* [ ] `netcanon/migration/codecs/cisco_nxos/__init__.py` re-exports
  `CiscoNXOSCodec`
* [ ] `netcanon/migration/codecs/__init__.py` imports the new
  module so registration fires
* [ ] `netcanon/migration/codecs/base.py` `INPUT_FORMATS` adds
  `"cli-nxos"`
* [ ] `tests/unit/migration/test_real_captures.py` line 80-88 dict
  has `"nx_os": "cisco_nxos"` entry
* [ ] `tests/fixtures/real/nx_os/` directory exists with ≥1
  fixture (Apache-2.0 attributed in NOTICE.md)
* [ ] `definitions/vendors.yaml` has `cisco_nxos` row
* [ ] `docs/CAPABILITIES.md` has NX-OS column
* [ ] `netcanon/migration/_tier3_detection.py` exports
  `detect_tier3_sections_nxos`
* [ ] codec's `probe()` returns 98 on the seed-corpus banner;
  returns `None` on IOS-XE / Aruba / XML / JSON inputs
* [ ] `test_every_fixture_dir_has_codec_mapping` passes
* [ ] `test_every_fixture_parses_cleanly[nx_os/...]` passes
* [ ] Round-trip test passes for at least one fixture

Without all of these, the codec is half-wired and risks shipping
test gaps that future PRs trip over.
