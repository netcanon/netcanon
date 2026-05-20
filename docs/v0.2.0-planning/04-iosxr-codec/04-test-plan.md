# 04 — Test plan

> Test surfaces for the proposed `cisco_iosxr` codec.  Mirrors
> `tests/unit/migration/test_cisco_iosxe_cli.py` structure (870 lines
> for IOS-XE).  Real-capture coverage uses the existing harness in
> `tests/unit/migration/test_real_captures.py` — requires a single
> mapping-row addition that is **easy to miss**.

## Fixture-directory wiring requirement (DO NOT FORGET)

`tests/unit/migration/test_real_captures.py:80` declares
`_DIR_TO_CODEC_NAME`, the mapping from `tests/fixtures/real/<dir>/`
to registered codec name.  T4 must add a new row:

```python
_DIR_TO_CODEC_NAME: dict[str, str] = {
    "cisco_iosxe":  "cisco_iosxe_cli",
    "aruba_aoss":   "aruba_aoss",
    "fortigate":    "fortigate_cli",
    "opnsense":     "opnsense",
    "mikrotik":     "mikrotik_routeros",
    "arista_eos":   "arista_eos",
    "junos":        "juniper_junos",
    "cisco_iosxr":  "cisco_iosxr",          # ← NEW row
}
```

There's a guard test
(`test_every_fixture_dir_has_codec_mapping`) that fails loud if you
forget — but it only fires once you've dropped a fixture file into
`tests/fixtures/real/cisco_iosxr/`.  Add the row in the same PR as
the first fixture.

The directory name uses the codec key directly (`cisco_iosxr`)
rather than a short form like `iosxr`, matching the established
convention for `cisco_iosxe`.

---

## File structure

Create `tests/unit/migration/test_cisco_iosxr.py` modeled on
`test_cisco_iosxe_cli.py`.  Sections:

```
test_cisco_iosxr.py
├── _MINIMAL_CLI / _SAMPLE_PE1 / _SAMPLE_BORDER01 / etc. fixtures (text blobs)
├── TestR3Fields          # ClassVar metadata checks
├── TestProbe             # auto-detection
├── TestParseCLI          # parse — basic
├── TestParseInterfaces   # parse — 4-segment ports / Bundle-Ether / MgmtEth
├── TestParseVRF          # parse — top-level vrf stanza + RT imports/exports
├── TestParseStaticRoutes # parse — router static block walker
├── TestParseUsers        # parse — username + group + secret
├── TestParseLAGs         # parse — Bundle-Ether + bundle id N mode M
├── TestParseSubinterfaces # parse — encapsulation dot1q + VLAN synthesis
├── TestTier3Detection    # parse — dropped_tier3_sections population
├── TestRender            # render — every supported canonical surface
├── TestRoundTrip         # render(parse(X)) → parse → equality
├── TestCrossVendor       # IOS-XE → IOS-XR + IOS-XR → IOS-XE
├── TestPortNames         # classify + format symmetry
└── TestCapabilityMatrix  # supported/lossy/unsupported declarations
```

---

## Per-section test inventory + counts

### Phase 1 (~25-30 tests)

| Test class | Sample tests | Count |
|---|---|---|
| `TestR3Fields` | `test_direction_is_parse_only`, `test_certainty_is_experimental`, `test_canonical_model`, `test_input_format`, `test_vendor_id`, `test_device_classes` | 6 |
| `TestProbe` | `test_probe_banner_only`, `test_probe_4segment_port`, `test_probe_bundle_ether`, `test_probe_mgmt_eth`, `test_probe_rejects_iosxe`, `test_probe_rejects_xml`, `test_probe_route_policy_grammar` | 7 |
| `TestParseCLI` | `test_minimal_cli`, `test_hostname`, `test_domain`, `test_empty_input_raises`, `test_xml_input_raises` | 5 |
| `TestParseInterfaces` | `test_4segment_physical`, `test_bundle_ether`, `test_loopback`, `test_mgmt_eth`, `test_shutdown`, `test_mtu`, `test_description`, `test_ipv4_address`, `test_no_ip_keyword` (positive: IPv4 NOT mis-parsed as `ip address`) | 9 |
| `TestParseStaticRoutes` | `test_router_static_basic`, `test_router_static_iface_plus_nh`, `test_router_static_vrf_block` (lossy — VRF drop documented) | 3 |

### Phase 2 (~30-40 tests)

| Test class | Sample tests | Count |
|---|---|---|
| `TestParseVRF` | `test_vrf_basic`, `test_vrf_rt_imports_block`, `test_vrf_rt_exports_block`, `test_vrf_iface_binding`, `test_vrf_mgmt_promotion` (kind="mgmt" cascade) | 5 |
| `TestParseUsers` | `test_username_with_group_password`, `test_username_with_secret`, `test_username_multiple_groups`, `test_root_lr_privilege_15` | 4 |
| `TestParseLAGs` | `test_bundle_declaration`, `test_member_bundle_id`, `test_mode_active_passive_static`, `test_lag_member_iface_link` | 4 |
| `TestParseSubinterfaces` | `test_subif_with_dot1q`, `test_subif_synth_vlan`, `test_subif_vrf_binding` | 3 |
| `TestRender` | `test_render_minimal`, `test_render_hostname`, `test_render_4segment_iface`, `test_render_bundle_ether`, `test_render_vrf_stanza`, `test_render_vrf_rt_imports_block`, `test_render_static_routes`, `test_render_users`, `test_render_subinterface_encapsulation` | 9 |
| `TestRoundTrip` | `test_round_trip_minimal`, `test_round_trip_vrf`, `test_round_trip_lag`, `test_round_trip_with_subinterface`, `test_round_trip_static_routes_per_vrf_drop` (documents the VRF-static loss) | 5 |
| `TestPortNames` | `test_classify_4segment`, `test_classify_3segment_legacy`, `test_classify_bundle_ether`, `test_classify_mgmt_eth`, `test_classify_loopback`, `test_classify_unknown`, `test_format_physical`, `test_format_bundle_ether`, `test_format_loopback`, `test_format_mgmt`, `test_round_trip_classify_format` | 11 |
| `TestCapabilityMatrix` | `test_supported_paths`, `test_lossy_paths_per_vrf_static`, `test_unsupported_paths_route_policy`, `test_unsupported_paths_vxlan` | 4 |

### Phase 3 (~10-15 tests)

| Test class | Sample tests | Count |
|---|---|---|
| `TestTier3Detection` | `test_detect_router_bgp`, `test_detect_router_ospf`, `test_detect_route_policy`, `test_detect_prefix_set`, `test_detect_mpls_ldp`, `test_detect_call_home`, `test_no_detect_when_absent` | 7 |
| `TestParseRouterBGP` (Phase 3 minimal harvest) | `test_parse_bgp_asn`, `test_parse_bgp_router_id`, `test_parse_vrf_rd_under_bgp` (backfill to CanonicalRoutingInstance) | 3 |

### Phase 4 (real-capture parametric tests)

These come automatically from `test_real_captures.py`'s parametric
collection — no new file needed.  They run:

1. `test_real_capture_parses_cleanly[cisco_iosxr::<filename>]` —
   for each fixture in `tests/fixtures/real/cisco_iosxr/`.
2. `test_real_capture_parse_is_deterministic[cisco_iosxr::...]` — same.
3. `test_real_capture_round_trips_stable[cisco_iosxr::...]` —
   only after direction flips to bidirectional in Phase 2.

Expected fixture count: 7 batfish snapshots + ≥2 additional sources
= 9+ files.  Tests-per-fixture = 3 → 27+ real-capture test invocations.

### Total test count by phase

| Phase | Unit tests | Real-capture parametric | Cumulative |
|---|---|---|---|
| 1 | ~30 | 14 (7 fixtures × 2 tests; round-trip skipped while parse_only) | 44 |
| 2 | ~70 | 21 (7 × 3 once direction=bidirectional) | 91 |
| 3 | ~85 | 21 (same fixtures, broader coverage) | 106 |
| 4 | ~95 | 27+ (9+ fixtures × 3) | 122+ |

This puts T4 around the same test density as Junos (Junos has
~110 unit tests in `test_juniper_junos.py`).

---

## Cross-vendor migration tests

The most interesting T4 tests exercise the **XR ↔ XE** translation
since `cisco_xr_ios_vpnv4/configs/` includes both XR PE configs AND
IOS-XE CE configs (CE1-CE4 are IOS classic on IOSv 15.7).  This is
a real-world migration pattern: enterprise CE upgrade from IOS-XE
to IOS-XR on a service provider's PE handoff.

### Suggested test cases

```python
class TestCrossVendor:
    def test_iosxe_to_iosxr(self):
        """Parse an IOS-XE config, render through IOS-XR codec.

        Verifies that:
        - Hostname survives.
        - GigabitEthernet0/0 (IOS-XE 2-segment) renders as
          GigabitEthernet0/0/0/0 (XR 4-segment).
        - `ip address X Y` (IOS-XE) renders as `ipv4 address X Y` (XR).
        - `vrf forwarding mgmt` (IOS-XE) renders as `vrf mgmt` (XR).
        - `Port-channel<N>` renders as `Bundle-Ether<N>`.
        """
        xe = CiscoIOSXECLICodec()
        xr = CiscoIOSXRCodec()
        tree = xe.parse(_IOSXE_SAMPLE)
        out = xr.render(tree)
        # Assertions on output shape (regex matching).
        assert re.search(r"^hostname Router$", out, re.MULTILINE)
        assert re.search(r"^interface GigabitEthernet0/\d+/\d+/\d+$",
                         out, re.MULTILINE)
        assert "ipv4 address " in out and "ip address " not in out

    def test_iosxr_to_iosxe(self):
        """Reverse direction — XR source rendered as IOS-XE."""
        ...

    def test_iosxr_to_junos(self):
        """The other natural SP migration — XR → Junos MX.

        Verifies the canonical pivot succeeds (no parse errors;
        non-trivial canonical extraction; Junos render emits set-form
        with VRF + interface IP + LAG content).
        """
        ...

    def test_xrxe_vpnv4_interop_round_trip(self):
        """Specifically uses cisco_xr_ios_vpnv4/PE1 (XR) + CE1 (XE)
        configs from the seed corpus.  Parses both, confirms each
        codec succeeds on its respective input, and confirms that
        cross-vendor renders preserve the VRF + RT + interface IP
        relationship.
        """
        ...

    def test_iosxr_to_iosxr_round_trip(self):
        """Same-vendor round-trip.  Strictest test — should preserve
        every canonical field bit-for-bit (modulo list ordering)."""
        ...
```

---

## Real-capture harness — three layers

The existing `test_real_captures.py` provides three parametric
tests per fixture (line 195-345 for the implementations):

### Layer 1 — Parse must not raise

```python
def test_real_capture_parses_cleanly(codec_key, path, ...):
    """Every committed real capture must parse without raising and
    produce a non-trivial CanonicalIntent."""
```

For T4, this fires once for each of the 7 batfish fixtures (and any
follow-on additions).  Whitelist via `_KNOWN_UNSUPPORTED` is allowed
but discouraged — Phase 1 ship gate is zero whitelist.

### Layer 2 — Parse must be deterministic

```python
def test_real_capture_parse_is_deterministic(codec_key, path):
    """Parsing the same input twice must produce structurally-
    identical trees."""
```

Catches set ordering / dict ordering / time-dependent logic.  Same
guarantees as the other codecs.

### Layer 3 — Round-trip stability (Phase 2+)

```python
def test_real_capture_round_trips_stable(codec_key, path):
    """parse(render(parse(raw))) == parse(raw) — semantic equality
    after sorting list fields by their natural keys."""
```

Only fires once `direction != "parse_only"`.  This is the **gate**
for declaring `certainty="certified"` at Phase 4 end.

---

## Probe ranking tests

Add tests in `tests/unit/migration/test_codec_probe.py` (existing
file; convention is one parametric test per probe rank case).

### Cases

```python
class TestIOSXRProbe:
    def test_xr_banner_beats_iosxe(self):
        """`!! IOS XR Configuration 6.6.2` MUST rank XR higher
        than IOS-XE even if IOS-XE structural markers (`hostname`,
        `interface`, `!`) are also present."""
        prefix = "!! IOS XR Configuration 6.6.2\nhostname X\ninterface ..."
        ranking = rank_codecs(prefix)
        assert ranking[0][0] == "cisco_iosxr"
        assert ranking[0][1] >= 95

    def test_4segment_iface_alone_ranks_xr_above_iosxe(self):
        prefix = (
            "hostname X\n"
            "interface GigabitEthernet0/0/0/0\n"
            " ipv4 address 10.0.0.1 255.255.255.0\n"
            "!"
        )
        ranking = rank_codecs(prefix)
        # cisco_iosxr expected ≥ cisco_iosxe_cli for this input.
        xr_rank = next((s for n, s, _ in ranking if n == "cisco_iosxr"), 0)
        xe_rank = next((s for n, s, _ in ranking if n == "cisco_iosxe_cli"), 0)
        assert xr_rank >= xe_rank

    def test_xml_input_returns_none(self):
        """Probe must reject XML / JSON early."""
        assert CiscoIOSXRCodec.probe("<rpc ...") is None

    def test_aruba_banner_input_returns_none(self):
        """Don't claim Aruba captures."""
        prefix = "; J9999A Switch Configuration\nhostname X\n"
        assert CiscoIOSXRCodec.probe(prefix) is None
```

---

## Migration pipeline integration tests

Add to `tests/integration/test_migration_pipeline.py` (if it
exists; otherwise inline in the unit-test file):

```python
def test_full_pipeline_xr_to_xe():
    """End-to-end: source=cisco_iosxr, target=cisco_iosxe_cli,
    plan + validate + transform + render via run_plan."""
    plan = MigrationPlan(
        source_codec="cisco_iosxr",
        target_codec="cisco_iosxe_cli",
        source_text=_XR_SAMPLE,
        transforms=[],
    )
    job = run_plan(plan)
    assert job.status == MigrationJobStatus.completed
    # validation_report.severity should be "warn" — per-VRF static
    # routes lose VRF discriminator + route-policy is unsupported.
```

---

## Capability matrix declaration tests

Mirror `TestCapabilityMatrix` from
`test_cisco_iosxe_cli.py`.  Confirm the proposed declarations in
`06-capabilities-matrix.md` are emitted exactly:

```python
class TestCapabilityMatrix:
    def setup_method(self):
        self.caps = CiscoIOSXRCodec().capabilities

    def test_adapter_name(self):
        assert self.caps.adapter == "cisco_iosxr"

    def test_vendor_id(self):
        assert self.caps.vendor_id == "cisco_iosxr"

    def test_device_classes_include_router(self):
        assert DeviceClass.router in self.caps.device_classes

    def test_route_policy_unsupported(self):
        unsupported_paths = {u.path for u in self.caps.unsupported}
        assert "/policy/route-policy" in unsupported_paths

    def test_per_vrf_static_lossy(self):
        lossy_paths = {l.path for l in self.caps.lossy}
        assert "/routing-instances/instance" in lossy_paths
```

---

## Test data — sample CLI blobs

Inline blobs at top of `test_cisco_iosxr.py`, sized for fast iteration:

```python
_MINIMAL_CLI = """\
!! IOS XR Configuration 6.6.2
!
hostname Router
!
interface Loopback0
 ipv4 address 10.0.0.1 255.255.255.255
!
end
"""

_VRF_CLI = """\
!! IOS XR Configuration 6.6.2
!
hostname PE1
!
vrf customer
 address-family ipv4 unicast
  import route-target
   65001:100
  !
  export route-target
   65001:100
  !
 !
!
interface GigabitEthernet0/0/0/0
 vrf customer
 ipv4 address 10.1.1.1 255.255.255.252
!
end
"""

_BUNDLE_CLI = """\
!! IOS XR Configuration 6.6.2
!
hostname Edge
!
interface Bundle-Ether23
 description To_Core
 ipv4 address 10.0.0.1 255.255.255.252
 bundle minimum-active links 2
!
interface GigabitEthernet0/0/0/0
 bundle id 23 mode active
!
interface GigabitEthernet0/0/0/1
 bundle id 23 mode active
!
end
"""

_ROUTE_POLICY_CLI = """\
!! IOS XR Configuration 6.6.2
!
hostname X
!
prefix-set ALLOW-LIST
  10.0.0.0/8 le 32,
  192.168.0.0/16
end-set
!
route-policy ALLOW-IN
  if destination in ALLOW-LIST then
    pass
  else
    drop
  endif
end-policy
!
interface Loopback0
 ipv4 address 10.255.0.1 255.255.255.255
!
end
"""
```

The full corpus samples (PE1, border01, RR, etc.) live as files
under `tests/fixtures/real/cisco_iosxr/` and are pulled in via the
real-capture harness.

---

## Estimated test LOC

| Phase | Test code LOC | Notes |
|---|---|---|
| 1 | ~400-500 | Bulk of class + section structure lands here; sample CLI blobs add up |
| 2 | ~400-500 | Render + round-trip + cross-vendor + capability matrix tests |
| 3 | ~150-250 | Tier-3 detection + minimal BGP harvest |
| 4 | ~50-100 | Polish + additional fixture-specific assertions |
| **Total** | **~1,200-1,700** | Roughly 60% of production source LOC, matching the Junos / IOS-XE codecs' test-to-prod ratio |
