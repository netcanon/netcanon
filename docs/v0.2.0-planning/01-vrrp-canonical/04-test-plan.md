# 04 — Test plan

Per-codec parse / render / round-trip tests, cross-vendor migration
tests, and real-fixture round-trip verification.

The test-shape template is `TestPerUnitVlanTagging` in
[`tests/unit/migration/test_juniper_junos.py`](../../../tests/unit/migration/test_juniper_junos.py)
(line 144 / `TestParseVlans` cluster). Each test class groups tests
by parse-or-render-or-round-trip + the canonical surface being
exercised.

---

## Test file structure

```
tests/
├── unit/
│   ├── canonical/
│   │   └── test_intent_vrrp.py            NEW — model validation
│   └── migration/
│       ├── test_cisco_iosxe_cli_vrrp.py   NEW
│       ├── test_arista_eos_vrrp.py        NEW
│       ├── test_juniper_junos_vrrp.py     NEW
│       ├── test_aruba_aoss_vrrp.py        NEW
│       ├── test_fortigate_cli_vrrp.py     NEW
│       ├── test_mikrotik_routeros_vrrp.py NEW
│       ├── test_opnsense_vrrp.py          NEW
│       ├── test_cross_vendor_vrrp.py      NEW — V→V matrix
│       └── test_real_fixtures_vrrp.py     NEW — real-capture round-trip
└── fixtures/
    └── synthetic/
        └── _vrrp/                          NEW — per-codec synthetic captures
            ├── cisco_iosxe_basic_vrrp.txt
            ├── cisco_iosxe_vrrp_with_track.txt
            ├── arista_eos_classic_vrrp.txt
            ├── arista_eos_varp_only.txt
            ├── junos_vrrp_classic.set
            ├── junos_anycast_v4_v6.set
            ├── aruba_aoss_basic_vrrp.txt
            ├── fortigate_basic_vrrp.conf
            ├── mikrotik_basic_vrrp.rsc
            └── opnsense_carp_v4.xml
```

Existing test files (`test_cisco_iosxe_cli.py`,
`test_arista_eos.py`, etc.) gain new test classes appended at
their tail rather than being modified mid-file — keeps the diff
clean and reviewable.

---

## A. Schema validation tests

**File:** `tests/unit/canonical/test_intent_vrrp.py` (new).

```python
# Shape sketch — tests are written against the as-yet-unlanded
# CanonicalVRRPGroup model.

import pytest
from pydantic import ValidationError

from netcanon.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalVRRPGroup,
)


class TestCanonicalVRRPGroupValidation:
    def test_defaults_are_sensible(self):
        g = CanonicalVRRPGroup(group_id=10)
        assert g.mode == "vrrp"
        assert g.priority == 100
        assert g.preempt is True
        assert g.advertisement_interval == 1
        assert g.virtual_ips == []
        assert g.virtual_ipv6s == []

    def test_group_id_range_enforced(self):
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=0)
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=256)

    def test_priority_range_enforced(self):
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=10, priority=0)
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=10, priority=255)

    def test_mode_accepts_known_values(self):
        for mode in ("vrrp", "anycast", "carp"):
            g = CanonicalVRRPGroup(group_id=10, mode=mode)
            assert g.mode == mode

    def test_interface_carries_list_default_empty(self):
        i = CanonicalInterface(name="Eth1")
        assert i.vrrp_groups == []
```

**5 tests.**

---

## B. Per-codec unit tests

For each codec: ~10 tests covering parse, render, round-trip, and
edge cases. Below the cisco_iosxe_cli case shows the template;
others follow the same shape.

### B.1. cisco_iosxe_cli

**File:** `tests/unit/migration/test_cisco_iosxe_cli_vrrp.py` (new).

```python
class TestParseVrrp:
    def test_basic_vrrp_group(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            " vrrp 10 ip 192.168.1.254\n"
            " vrrp 10 priority 110\n"
            "!\n"
        )
        intent = parse_intent(raw)
        iface = intent.interfaces[0]
        assert len(iface.vrrp_groups) == 1
        g = iface.vrrp_groups[0]
        assert g.group_id == 10
        assert g.virtual_ips == ["192.168.1.254"]
        assert g.priority == 110
        assert g.preempt is True
        assert g.mode == "vrrp"

    def test_secondary_virtual_ip(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " vrrp 10 ip 10.1.10.254\n"
            " vrrp 10 ip 10.1.10.253 secondary\n"
            "!\n"
        )
        intent = parse_intent(raw)
        g = intent.interfaces[0].vrrp_groups[0]
        assert g.virtual_ips == ["10.1.10.254", "10.1.10.253"]

    def test_multiple_groups_same_interface(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " vrrp 10 ip 192.168.1.254\n"
            " vrrp 20 ip 192.168.2.254\n"
            "!\n"
        )
        intent = parse_intent(raw)
        gids = [g.group_id for g in intent.interfaces[0].vrrp_groups]
        assert gids == [10, 20]

    def test_no_preempt(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " vrrp 10 ip 192.168.1.254\n"
            " no vrrp 10 preempt\n"
            "!\n"
        )
        intent = parse_intent(raw)
        assert intent.interfaces[0].vrrp_groups[0].preempt is False

    def test_ipv6_virtual(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " vrrp 10 ip 192.168.1.254\n"
            " vrrp 10 ipv6 fe80::1\n"
            "!\n"
        )
        intent = parse_intent(raw)
        g = intent.interfaces[0].vrrp_groups[0]
        assert g.virtual_ipv6s == ["fe80::1"]

    def test_track_with_decrement(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " vrrp 10 ip 192.168.1.254\n"
            " vrrp 10 track 1 decrement 20\n"
            "!\n"
        )
        intent = parse_intent(raw)
        assert intent.interfaces[0].vrrp_groups[0].track_interfaces == ["1"]

    def test_authentication_md5(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " vrrp 10 ip 192.168.1.254\n"
            " vrrp 10 authentication md5 key-string SECRET\n"
            "!\n"
        )
        intent = parse_intent(raw)
        assert intent.interfaces[0].vrrp_groups[0].authentication == "md5:SECRET"


class TestRenderVrrp:
    def test_basic_render(self):
        intent = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="GigabitEthernet0/2",
                ipv4_addresses=[CanonicalIPv4Address(ip="192.168.1.1", prefix_length=24)],
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10,
                    virtual_ips=["192.168.1.254"],
                    priority=110,
                )],
            ),
        ])
        out = render_intent(intent)
        assert "vrrp 10 ip 192.168.1.254" in out
        assert "vrrp 10 priority 110" in out
        assert "vrrp 10 preempt" in out

    def test_render_anycast_emits_review_comment(self):
        intent = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="Vlan10",
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=10, mode="anycast",
                    virtual_ips=["10.1.10.254"],
                )],
            ),
        ])
        out = render_intent(intent)
        assert "review:" in out and "anycast" in out


class TestRoundTripVrrp:
    def test_round_trip_basic(self):
        raw = (
            "interface GigabitEthernet0/2\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            " vrrp 12 ip 192.168.1.254\n"
            " vrrp 12 priority 110\n"
            "!\n"
        )
        intent = parse_intent(raw)
        out = render_intent(intent)
        intent2 = parse_intent(out)
        assert intent2.interfaces[0].vrrp_groups[0].group_id == 12
        assert intent2.interfaces[0].vrrp_groups[0].priority == 110
```

**~12 tests** for cisco_iosxe_cli (parse: 7, render: 2, round-trip: 3).

### B.2. arista_eos

`test_arista_eos_vrrp.py`. Adds VARP-specific tests beyond the cisco
template:

```python
class TestParseVarp:
    def test_ip_address_virtual_becomes_anycast_group(self):
        raw = (
            "interface Vlan10\n"
            "   ip address 10.1.10.2/24\n"
            "   ip address virtual 10.1.10.1/24\n"
            "!\n"
            "ip virtual-router mac-address 00:1c:73:00:dc:01\n"
        )
        intent = parse_intent(raw)
        g = intent.interfaces[0].vrrp_groups[0]
        assert g.mode == "anycast"
        assert g.virtual_ips == ["10.1.10.1"]
        assert g.virtual_mac == "00:1c:73:00:dc:01"

    def test_global_varp_mac_cascades(self):
        # Two Vlans, one global mac → both get it.
        ...

    def test_classic_vrrp_and_varp_coexist(self):
        # Same interface, two records.
        ...
```

**~14 tests** (classic + VARP + global mac + co-existence + round-trip).

### B.3. juniper_junos

`test_juniper_junos_vrrp.py`. Covers:

* classic `vrrp-group` (parse, render, round-trip)
* anycast `virtual-gateway-address` v4 + v6
* `virtual-gateway-v4-mac` capture and emit
* bracket-list virtual-addresses
* multi-IP per group

**~16 tests.**

### B.4. aruba_aoss

`test_aruba_aoss_vrrp.py`. Covers:

* basic `ip vrrp vrid N` block parse + render
* nested `exit` markers handled
* top-level `router vrrp` enabler emit
* track-id resolution
* single-virtual-ip Lossy behaviour on multi-IP canonical

**~10 tests.**

### B.5. fortigate_cli

`test_fortigate_cli_vrrp.py`. Covers:

* `config vrrp / edit N` sub-block parse
* multi-group per system interface
* preempt enable/disable
* `set vrip6` IPv6
* render emits with proper indentation

**~11 tests.**

### B.6. mikrotik_routeros

`test_mikrotik_routeros_vrrp.py`. Covers:

* `/interface vrrp add` + `/ip address` cross-section binding
* pseudo-iface naming round-trip
* preemption-mode mapping
* v3-protocol=ipv6 routing to `virtual_ipv6s`

**~9 tests.**

### B.7. opnsense

`test_opnsense_vrrp.py`. Covers:

* CARP `<vip>` parse
* advskew ↔ priority inversion
* CARP password preserved as `carp-key:` opaque
* VRRP-mode `<vip>` parse (no password required)
* logical interface name resolution
* IPv6 VIP parse

**~8 tests.**

---

## C. Cross-vendor migration tests

**File:** `tests/unit/migration/test_cross_vendor_vrrp.py` (new).

The canonical `CanonicalVRRPGroup` is meant to translate cleanly
across compatible vendors. Tests exercise the four most-meaningful
pairs:

### C.1. cisco_iosxe_cli → juniper_junos

```python
def test_iosxe_classic_to_junos_classic():
    iosxe_input = (
        "interface GigabitEthernet0/2\n"
        " ip address 192.168.1.1 255.255.255.0\n"
        " vrrp 10 ip 192.168.1.254\n"
        " vrrp 10 priority 110\n"
        "!\n"
    )
    intent = cisco_iosxe_cli.parse(iosxe_input)
    # Rename the interface to a Junos-shaped name via the existing
    # cross-vendor port-name translator.
    junos_output = juniper_junos.render(intent)
    assert (
        "set interfaces ge-0/0/0 unit 0 family inet address "
        "192.168.1.1/24 vrrp-group 10 virtual-address 192.168.1.254"
        in junos_output
    )
    assert (
        "set interfaces ge-0/0/0 unit 0 family inet address "
        "192.168.1.1/24 vrrp-group 10 priority 110"
        in junos_output
    )
```

### C.2. juniper_junos → arista_eos (anycast)

```python
def test_junos_anycast_to_arista_varp():
    junos_input = (
        "set interfaces irb unit 10 family inet address "
        "10.1.10.5/24 virtual-gateway-address 10.1.10.1\n"
        "set interfaces irb unit 10 virtual-gateway-v4-mac "
        "00:1c:73:00:dc:01\n"
    )
    intent = juniper_junos.parse(junos_input)
    eos_output = arista_eos.render(intent)
    assert "ip address virtual 10.1.10.1/24" in eos_output
    assert (
        "ip virtual-router mac-address 00:1c:73:00:dc:01" in eos_output
    )
```

### C.3. arista_eos → cisco_iosxe_cli (classic only — VARP surfaces Lossy)

```python
def test_eos_varp_to_iosxe_surfaces_review():
    eos_input = (
        "interface Vlan10\n"
        "   ip address 10.1.10.2/24\n"
        "   ip address virtual 10.1.10.1/24\n"
        "!\n"
        "ip virtual-router mac-address 00:1c:73:00:dc:01\n"
    )
    intent = arista_eos.parse(eos_input)
    iosxe_output = cisco_iosxe_cli.render(intent)
    # IOS-XE has no anycast equivalent — review comment must surface.
    assert "review:" in iosxe_output
    assert "anycast" in iosxe_output
```

### C.4. aruba_aoss → fortigate_cli

```python
def test_aruba_vrrp_to_fortigate():
    aruba_input = (
        "router vrrp\n"
        "vlan 10\n"
        "   name Tenant_A\n"
        "   ip address 10.1.10.2/24\n"
        "   ip vrrp vrid 10\n"
        "      virtual-ip-address 10.1.10.254\n"
        "      priority 110\n"
        "      preempt-mode\n"
        "      enable\n"
        "      exit\n"
        "   exit\n"
    )
    intent = aruba_aoss.parse(aruba_input)
    fortigate_output = fortigate_cli.render(intent)
    assert 'config vrrp' in fortigate_output
    assert 'edit 10' in fortigate_output
    assert 'set vrip 10.1.10.254' in fortigate_output
    assert 'set priority 110' in fortigate_output
```

### C.5. opnsense (CARP) → cisco_iosxe_cli (VRRP)

Verify the mode discriminator handles the cross-protocol case
sensibly — CARP password drops to a review comment; group_id and
virtual_ips translate.

### C.6. mikrotik_routeros → arista_eos (classic VRRP)

The pseudo-interface model should resolve cleanly. The Arista
output binds to the actual parent interface.

### C.7. cross_vendor_expectations YAML pairs

Add VRRP-bearing pairs to the existing
`tests/fixtures/cross_vendor_expectations/` per-pair expectation
files (see existing files for shape — listed below):

```
tests/fixtures/cross_vendor_expectations/
├── cisco_iosxe__juniper_junos.yaml       — add vrrp expectations
├── juniper_junos__cisco_iosxe.yaml       — add vrrp expectations
├── arista_eos__juniper_junos.yaml        — add anycast→varp
├── juniper_junos__arista_eos.yaml        — add varp→anycast
└── arista_eos__cisco_iosxe.yaml          — add classic vrrp + varp-Lossy
```

**~28 cross-vendor tests** across 4 high-value pairs × 7 scenarios
each, with the expectations YAMLs holding the structured assertions.

---

## D. Real-fixture round-trip tests

**File:** `tests/unit/migration/test_real_fixtures_vrrp.py` (new).

```python
def test_batfish_iosxe_basic_vrrp_round_trips_clean():
    """tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt
    must round-trip without data loss after VRRP wire-up.
    """
    raw = Path(
        "tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt"
    ).read_text()
    intent = cisco_iosxe_cli.parse(raw)
    # The fixture has:  vrrp 12 ip 192.168.1.254 / vrrp 12 priority 110
    iface = next(i for i in intent.interfaces if i.name == "GigabitEthernet0/2")
    assert len(iface.vrrp_groups) == 1
    g = iface.vrrp_groups[0]
    assert g.group_id == 12
    assert g.virtual_ips == ["192.168.1.254"]
    assert g.priority == 110

    # Round-trip: render → re-parse → field-equality.
    rendered = cisco_iosxe_cli.render(intent)
    re_parsed = cisco_iosxe_cli.parse(rendered)
    iface2 = next(i for i in re_parsed.interfaces if i.name == "GigabitEthernet0/2")
    assert iface.vrrp_groups == iface2.vrrp_groups
```

For each codec, one real-fixture test (where the fixture exists):

| Codec | Fixture |
|---|---|
| cisco_iosxe_cli | `tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt` (exists) |
| juniper_junos | `tests/fixtures/real/junos/ksator_labmgmt_qfx10k2_junos173.set` (exists — anycast form) |
| arista_eos | `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt` (exists — VARP form) |
| aruba_aoss | new fixture needed — see [`06-fixture-targets.md`](06-fixture-targets.md) |
| fortigate_cli | new fixture needed |
| mikrotik_routeros | new fixture needed |
| opnsense | new fixture needed (CARP HA pair) |
| cisco_iosxe (NETCONF) | n/a — unsupported in v0.2.0 |

**~7 real-fixture tests** (one per bidirectional codec once the
fixtures land in v0.2.0; cisco_iosxe NETCONF stays unsupported).

---

## E. Migration-pipeline integration tests

**File:** add to existing
[`tests/unit/migration/test_pipeline_integration.py`](../../../tests/unit/migration/) or sibling.

* `MigrationJob` for VRRP-bearing source → target completes without
  raising.
* `ValidationReport.lossy_paths` includes
  `/interfaces/interface/vrrp_groups` when target declares it Lossy.
* Cross-vendor port-rename keeps the `vrrp_groups` attached to the
  renamed interface.
* Rename modal's per-pane categories DO NOT include "vrrp" (it's
  not a rename surface — the IPs translate, not the identities).

**~5 pipeline tests.**

---

## F. UI / capability-matrix tests

* `docs/CAPABILITIES.md` row check: every codec's table includes the
  new VRRP row (covered by the existing markdown-render check if any).
* Run-full-mesh field-disposition matrix flips
  `unsupported_in_target=True` for cisco_iosxe NETCONF.

**~3 UI tests.**

---

## Total test count

| Bucket | Count |
|---|---|
| A. Schema validation | 5 |
| B. Per-codec (7 codecs × ~10) | 80 |
| C. Cross-vendor matrix | 28 |
| D. Real-fixture round-trip | 7 |
| E. Pipeline integration | 5 |
| F. UI / capability matrix | 3 |
| **TOTAL** | **128** |

Aligns with the README.md estimate of ~122 (small overshoot from
the cross-vendor matrix coverage).

---

## Anti-patterns to avoid

* **Don't write parse-only tests in isolation.** Each parse test
  should have a round-trip companion that proves the rendered
  output re-parses to an equal intent.
* **Don't assert on exact rendered byte sequences.** The render
  side may add whitespace / ordering changes; tests should match
  against tokens (`in out`) or parse-the-rendered-output for
  equality.
* **Don't mutate canonical intents inside tests.** Build fresh
  via `CanonicalIntent(interfaces=[...])` so failures are
  reproducible from the test source.
* **Don't rely on hash-portability for the `authentication`
  field.** Cross-vendor tests must assert the review comment
  appears, not the rewritten key value.
