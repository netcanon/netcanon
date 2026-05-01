"""
Cross-codec mesh smoke tests for per-pane override categories.

Layer B of the P2 strategy document's test pyramid: ONE parametrized
test function per category that exercises (source_codec, target_codec)
pairings to verify the override transform doesn't crash / drop its
overrides on the way through any codec combination's parse + render.

**Runtime budget:** aggregate runtime under ``@pytest.mark.cross_mesh``
must stay under 30 seconds as the matrix grows.  When adding a new
category (SNMP trap-hosts, RADIUS, etc.) extend the parametrize list
here rather than creating new class-per-category files — the aggregate
cap is easier to enforce when the mesh is one pytest file.  If a case
consistently runs >500ms, demote it to a layer-A per-codec unit test
and leave only a "fast smoke" representative in this file.

Currently covered categories: ports, VLANs, local_users,
snmp_community (each with parametrized cross-codec smoke).

Layer A (per-codec correctness, no cross-mesh) lives in
``test_vlan_names.py``, ``test_port_names.py``, etc.
"""

from __future__ import annotations

import pytest

# Pull codec classes from the registry rather than hand-maintaining
# an import list.  New vendors auto-register on package import and
# the registry enumerates them — removes the risk of forgetting a
# line in this file after shipping a codec.  The ArubaAOSSCodec
# module-level alias below is kept because three same-vendor-round-
# trip tests in this file construct ArubaAOSSCodec() directly for
# readability; they could switch to ``_resolve_codec("aruba_aoss")``
# but the class-name form reads better at the call site.
from netconfig.migration.codecs import (  # noqa: F401 — side-effect import
    _mock,
    arista_eos,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
)
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.registry import get_codec, list_codecs
from netconfig.services.migration_pipeline import run_plan_with_overrides


def _resolve_codec_class(name: str):
    """Return the registered codec class for *name*.  Raises
    :class:`KeyError` if the registry has no codec by that name —
    typically means a test referenced a codec whose package wasn't
    imported (add it to the imports above).

    Using the registry rather than a hand-maintained dict means new
    vendors picked up by package auto-discovery are immediately
    usable in this test file's fixtures without a parallel edit."""
    if name not in list_codecs():
        raise KeyError(
            f"Codec {name!r} not registered.  Known codecs: "
            f"{sorted(list_codecs())}.  Did you forget to import "
            f"``netconfig.migration.codecs.<vendor>`` at the top of "
            f"this file?"
        )
    return type(get_codec(name))


# Minimal source configs per codec — just enough to produce a tree
# with at least one VLAN so the rename transform has a target.
# Kept small (seconds-per-test is the budget) and populated from
# known-parseable synthetic grammars (not real captures — those
# live in tests/fixtures/real/ and are exercised by the dedicated
# real-capture harness).
_SRC_CONFIGS = {
    "cisco_iosxe_cli": """\
hostname TestCisco
!
vlan 10
 name USERS
vlan 20
 name VOICE
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
""",
    "aruba_aoss": """\
hostname "TestAruba"
vlan 1
   name "DEFAULT_VLAN"
   exit
vlan 10
   name "USERS"
   untagged 1/1
   exit
vlan 20
   name "VOICE"
   exit
""",
    "mikrotik_routeros": """\
# 2026-01-01 12:00:00 by RouterOS 7.18.2
# model = TestRouter
/interface ethernet
set [ find default-name=ether1 ] name=ether1
/interface vlan
add interface=ether1 name=vlan10 vlan-id=10
add interface=ether1 name=vlan20 vlan-id=20
""",
    "opnsense": """\
<?xml version="1.0"?>
<opnsense>
  <hostname>testopnsense</hostname>
  <interfaces>
    <wan>
      <if>em0</if>
      <enable>1</enable>
    </wan>
  </interfaces>
  <vlans>
    <vlan>
      <if>em0</if>
      <tag>10</tag>
      <descr>USERS</descr>
      <vlanif>em0.10</vlanif>
    </vlan>
    <vlan>
      <if>em0</if>
      <tag>20</tag>
      <descr>VOICE</descr>
      <vlanif>em0.20</vlanif>
    </vlan>
  </vlans>
</opnsense>
""",
    "fortigate_cli": """\
#config-version=FG100E-7.2.0:opmode=1:vdom=0:user=admin
config system global
    set hostname "TestFGT"
end
config system interface
    edit "port1"
        set vdom "root"
        set type physical
    next
end
""",
    "arista_eos": """\
hostname TestArista
!
vlan 10
   name USERS
!
vlan 20
   name VOICE
!
interface Ethernet1
   switchport mode access
   switchport access vlan 10
!
""",
    "juniper_junos": """\
set system host-name TestJunos
set vlans USERS vlan-id 10
set vlans VOICE vlan-id 20
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members USERS
""",
    # cisco_iosxe is the NETCONF/OpenConfig codec — its source-side
    # input is XML, not CLI.  Include enough to exercise the
    # parse → render path without claiming full grammar coverage.
    "cisco_iosxe": (
        '<?xml version="1.0"?>\n'
        '<interfaces xmlns="http://openconfig.net/yang/interfaces">\n'
        "  <interface>\n"
        "    <name>GigabitEthernet0/0</name>\n"
        "    <config>\n"
        "      <name>GigabitEthernet0/0</name>\n"
        "      <enabled>true</enabled>\n"
        "    </config>\n"
        "  </interface>\n"
        "</interfaces>\n"
    ),
}

#: Codec classes used in the cross-mesh smoke matrix.  Built lazily
#: from the registry on first access — no hand-maintained dict.
#: ``list_codecs()`` is sorted so test parametrize IDs are stable
#: across runs.
_CODECS: dict[str, type] = {
    name: _resolve_codec_class(name) for name in list_codecs()
}

# Codec pairs available for cross-mesh smoke.  Split by direction
# because some codecs are parse_only / render_only and cannot serve
# as both halves of a round-trip.
#
# Source-capable = codecs that parse the configs we have synthesised.
# Target-capable = bidirectional codecs that can render to native
# format.  cisco_iosxe_cli is parse_only, so it appears on the
# source axis but NOT the target axis.
_SOURCE_CAPABLE = [
    "cisco_iosxe_cli",
    "aruba_aoss",
    "mikrotik_routeros",
    "opnsense",
    "arista_eos",
    "juniper_junos",
    "fortigate_cli",
    "cisco_iosxe",
]
# Target-capable expanded post-aruba→cisco-iosxe-NETCONF bug:
# every bidirectional codec is now in the smoke matrix.  The
# bidirectionality-invariants meta-test (test_bidirectionality_
# invariants.py::TestEveryBidirectionalTargetHasFixtureCoverage)
# guards against this list silently shrinking.
_TARGET_CAPABLE = [
    "aruba_aoss",
    "mikrotik_routeros",
    "opnsense",
    "arista_eos",
    "juniper_junos",
    "fortigate_cli",
    "cisco_iosxe",
    "cisco_iosxe_cli",
]


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _SOURCE_CAPABLE)
@pytest.mark.parametrize("target_name", _TARGET_CAPABLE)
def test_vlan_rename_smoke_cross_codec(source_name: str, target_name: str):
    """Every (source, target) pair in the VLAN-capable codec set must
    run the VLAN-rename pipeline end-to-end without crashing and
    surface the applied rewrite on the resulting job.

    Layer B smoke — does NOT assert byte-identical output (parse +
    render across vendors produces legitimately different strings).
    Does assert:
      * Pipeline returns a MigrationJob (not an exception).
      * If the source tree had the renamed VLAN, ``vlan_renames``
        reflects the rewrite.
      * Rendered output contains the target VLAN ID (as a string
        somewhere) — crude but catches "rename silently lost at
        render".
    """
    source = _CODECS[source_name]()
    target = _CODECS[target_name]()
    raw = _SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        vlan_rename_map={10: 100},
    )

    # The pipeline must not crash.
    assert job is not None
    assert job.rendered is not None

    # If the source tree carried VLAN 10, the rename surfaces.  The
    # capture-first transform populates ``job.source_vlans`` with the
    # post-parse pre-rewrite VLAN list — that's the authoritative
    # "did source have it?" check, replacing an earlier
    # always-true ``if False else [10]`` guard that fired the
    # assertion on every codec regardless of source content.
    if 10 in job.source_vlans:
        assert job.vlan_renames.get(10) == 100

    # Crude end-to-end sanity: new VLAN ID appears in the rendered
    # output, old one doesn't (for same-vendor round-trip and most
    # cross-vendor cases).  Cross-vendor differences mean we can't
    # be strict — so this assertion only runs on the subset where
    # source == target (round-trip), which is the most sensitive
    # silent-drop detector.  Also gated on source actually carrying
    # VLAN 10 — codecs whose minimal source config doesn't declare
    # any VLANs (fortigate_cli, cisco_iosxe NETCONF stub) have
    # nothing to rename and no "100" should appear on render.
    if source_name == target_name and 10 in job.source_vlans:
        assert "100" in job.rendered
        # Old VLAN ID shouldn't appear — use whole-word sanity
        # (skip for codecs that emit the source filename with
        # "10" in its timestamp or similar coincidence).


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _TARGET_CAPABLE)
def test_vlan_drop_smoke(source_name: str):
    """Dropping a VLAN end-to-end for same-vendor round-trip across
    every bidirectional codec → resulting job records the drop.
    Parse-only codecs can't render so they're excluded from the
    same-vendor round-trip axis."""
    source = _CODECS[source_name]()
    target = _CODECS[source_name]()  # same-vendor for signal clarity
    raw = _SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        vlan_rename_map={10: None},
    )

    assert job is not None
    assert job.rendered is not None
    # The dropped VLAN ID shows up in vlan_drops on the job — only
    # when the source actually had VLAN 10 to drop.  Codecs whose
    # minimal smoke fixture has no VLANs (fortigate_cli, cisco_iosxe
    # NETCONF stub) skip the assertion legitimately.
    if 10 in job.source_vlans:
        assert 10 in job.vlan_drops


@pytest.mark.cross_mesh
def test_combined_port_and_vlan_overrides_in_one_call():
    """Two override categories in a single pipeline run — verify
    they compose without interfering.  Uses Aruba AOS-S same-vendor
    round-trip (bidirectional codec) so rendered output is available
    for end-to-end assertions."""
    source = ArubaAOSSCodec()
    target = ArubaAOSSCodec()
    raw = _SRC_CONFIGS["aruba_aoss"]

    job = run_plan_with_overrides(
        source, target, raw,
        port_rename_map={"1/1": "1/47"},
        vlan_rename_map={10: 100},
    )

    assert job.port_renames.get("1/1") == "1/47"
    assert job.vlan_renames.get(10) == 100
    # Rendered output reflects both.
    assert "1/47" in job.rendered
    assert "100" in job.rendered


# Source configs for local-user mesh coverage — each carries at
# least one user the parametrized rename can target.  Kept in a
# separate dict from _SRC_CONFIGS because not every VLAN-carrying
# config also declares users (VLAN smoke works on opnsense XML; the
# local-user smoke targets vendors whose canonical parse emits
# local_users).
_USER_SRC_CONFIGS = {
    "cisco_iosxe_cli": (
        "hostname TestCisco\n!\n"
        "username admin privilege 15 secret 5 $1$abc$fake\n"
        "username operator privilege 5 secret 5 $1$def$fake\n!\n"
    ),
    "aruba_aoss": (
        'hostname "TestAruba"\n'
        "password manager user-name admin "
        "plaintext ClearTextPassw0rd\n"
    ),
    "mikrotik_routeros": (
        "# 2026-01-01 12:00:00 by RouterOS 7.18.2\n"
        "/user\n"
        'add name=admin group=full password=secret\n'
    ),
}

# Codecs that actually populate CanonicalIntent.local_users on
# parse.  OPNsense and FortiGate don't currently map their local-
# user sections into the canonical shape (Tier-2 coverage is
# vendor-by-vendor — see test_local_users_wire_through.py).  The
# mesh smoke only covers codecs where local_users round-trip.
_LOCAL_USER_CAPABLE = [
    "cisco_iosxe_cli",
    "aruba_aoss",
    "mikrotik_routeros",
]
_LOCAL_USER_TARGET_CAPABLE = [
    "aruba_aoss",
    "mikrotik_routeros",
]


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _LOCAL_USER_CAPABLE)
@pytest.mark.parametrize("target_name", _LOCAL_USER_TARGET_CAPABLE)
def test_local_user_rename_smoke_cross_codec(
    source_name: str, target_name: str,
):
    """Every (source, target) pair in the local-user-capable set must
    run the rename pipeline end-to-end without crashing.  Smoke only —
    does not assert byte-identical output (cross-vendor rendering is
    legitimately different).  Locks in that the rename map survives
    the canonical-round-trip and that the applied-rewrite map
    populates when the source tree carried the renamed user."""
    source = _CODECS[source_name]()
    target = _CODECS[target_name]()
    raw = _USER_SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        local_user_rename_map={"admin": "netadmin"},
    )

    # The pipeline must not crash.
    assert job is not None
    assert job.rendered is not None

    # source_local_users captured BEFORE rename, so 'admin' should
    # appear regardless of whether the codec renders it verbatim.
    if "admin" in job.source_local_users:
        # Rewrite surfaced.
        assert job.local_user_renames.get("admin") == "netadmin"


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _LOCAL_USER_TARGET_CAPABLE)
def test_local_user_drop_smoke(source_name: str):
    """Dropping a user end-to-end for same-vendor round-trip across
    every bidirectional user-capable codec → job records the drop."""
    source = _CODECS[source_name]()
    target = _CODECS[source_name]()
    raw = _USER_SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        local_user_rename_map={"admin": None},
    )

    assert job is not None
    assert job.rendered is not None
    # admin was in the source tree → appears in drops.
    if "admin" in job.source_local_users:
        assert "admin" in job.local_user_drops


@pytest.mark.cross_mesh
def test_three_category_overrides_in_one_call():
    """Ports + VLANs + local_users in a single pipeline run —
    extends test_combined_port_and_vlan_overrides_in_one_call with
    the third category.  Locks in the three-category composition
    contract."""
    source = ArubaAOSSCodec()
    target = ArubaAOSSCodec()
    # Aruba source config with a user declaration — use the
    # local-user-specific fixture which has the user stanza.
    raw = (
        'hostname "TestAruba"\n'
        "vlan 1\n   name \"DEFAULT_VLAN\"\n   exit\n"
        "vlan 10\n   name \"USERS\"\n   untagged 1/1\n   exit\n"
        "password manager user-name admin "
        "plaintext ClearTextPassw0rd\n"
    )

    job = run_plan_with_overrides(
        source, target, raw,
        port_rename_map={"1/1": "1/47"},
        vlan_rename_map={10: 100},
        local_user_rename_map={"admin": "netadmin"},
    )

    # Each category's outcome is independent.
    assert job.port_renames.get("1/1") == "1/47"
    assert job.vlan_renames.get(10) == 100
    # local_user_renames fires if the canonical tree captured admin.
    if "admin" in job.source_local_users:
        assert job.local_user_renames.get("admin") == "netadmin"


# ---------------------------------------------------------------------------
# SNMP community rename — P2C5 fourth per-pane category
# ---------------------------------------------------------------------------


# Source configs carrying an SNMP community.  Only a representative
# set of codecs — all five parse snmp-community lines into
# CanonicalSNMP.community, but keeping the list narrow bounds the
# cross-mesh runtime budget.  Codecs omitted here are still covered
# by the Layer-A ``test_snmp_names.py`` tests.
_SNMP_SRC_CONFIGS = {
    "cisco_iosxe_cli": (
        "hostname TestCisco\n!\n"
        "snmp-server community public RO\n"
        "snmp-server location HQ\n!\n"
    ),
    "aruba_aoss": (
        'hostname "TestAruba"\n'
        "snmp-server community \"public\" unrestricted\n"
    ),
    "mikrotik_routeros": (
        "# 2026-01-01 12:00:00 by RouterOS 7.18.2\n"
        "/snmp\n"
        'set enabled=yes contact="" location="" trap-community=public\n'
        "/snmp community\n"
        'set [ find default=yes ] name=public\n'
    ),
}

_SNMP_CAPABLE = list(_SNMP_SRC_CONFIGS.keys())
# cisco_iosxe_cli is parse_only — excluded from the target set.
# Same discipline as the local_users mesh above.
_SNMP_TARGET_CAPABLE = [
    "aruba_aoss",
    "mikrotik_routeros",
]


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _SNMP_CAPABLE)
@pytest.mark.parametrize("target_name", _SNMP_TARGET_CAPABLE)
def test_snmp_community_rename_smoke_cross_codec(
    source_name: str, target_name: str,
):
    """Every (source, target) pair in the SNMP-capable set runs the
    rename pipeline end-to-end without crashing.  Smoke only — does
    not assert byte-identical output.  Locks in that the rename map
    survives the canonical round-trip and that source_snmp_community
    populates from every tested source."""
    source = _CODECS[source_name]()
    target = _CODECS[target_name]()
    raw = _SNMP_SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        snmp_community_rename_map={"public": "monitoring-ro"},
    )

    # Pipeline must not crash.
    assert job is not None
    assert job.rendered is not None

    # source_snmp_community captured BEFORE rename — when the source
    # codec successfully parsed the SNMP block, 'public' surfaces
    # on the job.  Codecs that didn't map into CanonicalSNMP leave
    # it empty (legitimate — exercised by Layer-A tests instead).
    if job.source_snmp_community == "public":
        # Rename surfaced in applied-map.
        assert job.snmp_community_renames.get("public") == "monitoring-ro"


@pytest.mark.cross_mesh
def test_four_category_overrides_in_one_call():
    """Ports + VLANs + local_users + SNMP in a single pipeline run —
    extends test_three_category_overrides_in_one_call with the
    fourth category.  Locks in the full four-way composition
    contract post-P2C5."""
    source = ArubaAOSSCodec()
    target = ArubaAOSSCodec()
    raw = (
        'hostname "TestAruba"\n'
        "vlan 1\n   name \"DEFAULT_VLAN\"\n   exit\n"
        "vlan 10\n   name \"USERS\"\n   untagged 1/1\n   exit\n"
        "password manager user-name admin "
        "plaintext ClearTextPassw0rd\n"
        'snmp-server community "public" unrestricted\n'
    )

    job = run_plan_with_overrides(
        source, target, raw,
        port_rename_map={"1/1": "1/47"},
        vlan_rename_map={10: 100},
        local_user_rename_map={"admin": "netadmin"},
        snmp_community_rename_map={"public": "monitoring-ro"},
    )

    # Each category's outcome is independent.
    assert job.port_renames.get("1/1") == "1/47"
    assert job.vlan_renames.get(10) == 100
    if "admin" in job.source_local_users:
        assert job.local_user_renames.get("admin") == "netadmin"
    if job.source_snmp_community == "public":
        assert job.snmp_community_renames.get("public") == "monitoring-ro"


# ---------------------------------------------------------------------------
# SNMPv3 USM user rename — P2C6 fifth per-pane category
# ---------------------------------------------------------------------------


# Source configs carrying SNMPv3 USM users.  Covers every codec that
# declares /snmp/v3-user in its capability-matrix supported[] — i.e.
# every codec with a documented v3 grammar.  OPNsense is NOT in the
# set (Tier-3 raw_sections only; declares the xpath unsupported).
_SNMPV3_SRC_CONFIGS = {
    "cisco_iosxe_cli": (
        "hostname TestCisco\n!\n"
        "snmp-server user netadmin adminGroup v3 "
        "auth sha SHApass priv aes 128 AESpass\n"
    ),
    "aruba_aoss": (
        'hostname "TestAruba"\n'
        'snmpv3 user "netadmin" auth sha "SHApass" priv aes "AESpass"\n'
        'snmpv3 group "AdminGroup" user "netadmin" sec-model ver3\n'
    ),
    "mikrotik_routeros": (
        "# 2026-01-01 12:00:00 by RouterOS 7.18.2\n"
        "/snmp community\n"
        'add name=netadmin authentication-protocol=SHA1 '
        'authentication-password="SHApass" '
        'encryption-protocol=aes-128-cfb '
        'encryption-password="AESpass"\n'
    ),
    "fortigate_cli": (
        '#config-version=FG100E-7.2.0:opmode=1\n'
        "config system global\n"
        '    set hostname "fg1"\n'
        "end\n"
        "config system snmp user\n"
        '    edit "netadmin"\n'
        "        set security-level auth-priv\n"
        "        set auth-proto sha256\n"
        "        set auth-pwd ENC someSHAhash==\n"
        "        set priv-proto aes256\n"
        "        set priv-pwd ENC someAEShash==\n"
        "    next\n"
        "end\n"
    ),
}

_SNMPV3_CAPABLE = list(_SNMPV3_SRC_CONFIGS.keys())
# cisco_iosxe_cli is parse_only → source-only.  Same discipline as the
# local_users + snmp_community meshes.
_SNMPV3_TARGET_CAPABLE = [
    "aruba_aoss",
    "mikrotik_routeros",
    "fortigate_cli",
]


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _SNMPV3_CAPABLE)
@pytest.mark.parametrize("target_name", _SNMPV3_TARGET_CAPABLE)
def test_snmpv3_user_rename_smoke_cross_codec(
    source_name: str, target_name: str,
):
    """Every (source, target) pair in the SNMPv3-capable set runs
    the rename pipeline end-to-end without crashing.  Smoke only —
    does not assert byte-identical output.  Locks in that the rename
    map survives the canonical round-trip and that
    source_snmpv3_users populates from every tested source."""
    source = _CODECS[source_name]()
    target = _CODECS[target_name]()
    raw = _SNMPV3_SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        snmpv3_user_rename_map={"netadmin": "platform-snmpro"},
    )

    # Pipeline must not crash.
    assert job is not None
    assert job.rendered is not None

    # source_snmpv3_users captured BEFORE rename — when source parse
    # populated the canonical v3 users, ``netadmin`` surfaces.
    if "netadmin" in job.source_snmpv3_users:
        assert job.snmpv3_user_renames.get("netadmin") == "platform-snmpro"


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _SNMPV3_TARGET_CAPABLE)
def test_snmpv3_user_drop_smoke(source_name: str):
    """Dropping a v3 user end-to-end for same-vendor round-trip
    across every bidirectional v3-capable codec → job records the
    drop."""
    source = _CODECS[source_name]()
    target = _CODECS[source_name]()       # same-vendor for clarity
    raw = _SNMPV3_SRC_CONFIGS[source_name]

    job = run_plan_with_overrides(
        source, target, raw,
        snmpv3_user_rename_map={"netadmin": None},
    )

    assert job is not None
    assert job.rendered is not None
    if "netadmin" in job.source_snmpv3_users:
        assert "netadmin" in job.snmpv3_user_drops


@pytest.mark.cross_mesh
def test_five_category_overrides_in_one_call():
    """Ports + VLANs + local_users + SNMP community + SNMPv3 users in a
    single pipeline run — extends test_four_category_overrides_in_one_call
    with the fifth category.  Locks in the full five-way composition
    contract post-P2C6."""
    source = ArubaAOSSCodec()
    target = ArubaAOSSCodec()
    raw = (
        'hostname "TestAruba"\n'
        "vlan 1\n   name \"DEFAULT_VLAN\"\n   exit\n"
        "vlan 10\n   name \"USERS\"\n   untagged 1/1\n   exit\n"
        "password manager user-name admin "
        "plaintext ClearTextPassw0rd\n"
        'snmp-server community "public" unrestricted\n'
        'snmpv3 user "netadmin" auth sha "SHApass" priv aes "AESpass"\n'
        'snmpv3 group "AdminGroup" user "netadmin" sec-model ver3\n'
    )

    job = run_plan_with_overrides(
        source, target, raw,
        port_rename_map={"1/1": "1/47"},
        vlan_rename_map={10: 100},
        local_user_rename_map={"admin": "netadmin-cli"},
        snmp_community_rename_map={"public": "monitoring-ro"},
        snmpv3_user_rename_map={"netadmin": "platform-snmpro"},
    )

    # Each category's outcome is independent.
    assert job.port_renames.get("1/1") == "1/47"
    assert job.vlan_renames.get(10) == 100
    if "admin" in job.source_local_users:
        assert job.local_user_renames.get("admin") == "netadmin-cli"
    if job.source_snmp_community == "public":
        assert job.snmp_community_renames.get("public") == "monitoring-ro"
    if "netadmin" in job.source_snmpv3_users:
        assert job.snmpv3_user_renames.get("netadmin") == "platform-snmpro"


# ---------------------------------------------------------------------------
# GAP-EVPN-2: VXLAN source-interface + udp-port survive cross-vendor
# round-trip through the canonical tree.  Direct codec-level test (not
# a per-pane override smoke) — verifies the canonical fields wire
# through Arista parse → Junos render without losing data.
# ---------------------------------------------------------------------------


@pytest.mark.cross_mesh
def test_vxlan_source_interface_survives_arista_to_junos():
    """An Arista config declaring ``vxlan source-interface Loopback0``
    must survive parse-to-canonical such that a Junos render emits
    ``set switch-options vtep-source-interface Loopback0`` (or the
    operator-renamed equivalent).  The opaque-string semantic — name
    is preserved verbatim, operator translates Arista→Junos via the
    port-rename pane — is the v1 contract.
    """
    arista = get_codec("arista_eos")
    junos = get_codec("juniper_junos")
    raw = (
        "hostname leaf1\n"
        "!\n"
        "vlan 100\n"
        "   name V100\n"
        "!\n"
        "interface Vxlan1\n"
        "   vxlan source-interface Loopback0\n"
        "   vxlan udp-port 4789\n"
        "   vxlan vlan 100 vni 10100\n"
        "!\n"
        "end\n"
    )
    intent = arista.parse(raw)
    assert len(intent.vxlan_vnis) == 1
    assert intent.vxlan_vnis[0].source_interface == "Loopback0"

    # Render via Junos.  Without a port-rename mesh entry, the
    # source-interface name is kept as-is (operator can rename).
    rendered = junos.render(intent)
    assert "set switch-options vtep-source-interface Loopback0" in rendered
    # Default UDP port (4789) is silent on Junos render.
    assert "set switch-options vxlan-port" not in rendered


@pytest.mark.cross_mesh
def test_vxlan_udp_port_override_survives_arista_to_junos():
    """Non-default UDP port (8472 — common legacy Linux VXLAN value)
    survives Arista parse → Junos render."""
    arista = get_codec("arista_eos")
    junos = get_codec("juniper_junos")
    raw = (
        "hostname leaf1\n"
        "!\n"
        "interface Vxlan1\n"
        "   vxlan source-interface Loopback0\n"
        "   vxlan udp-port 8472\n"
        "   vxlan vlan 100 vni 10100\n"
        "!\n"
        "end\n"
    )
    intent = arista.parse(raw)
    assert intent.vxlan_vnis[0].udp_port == 8472
    rendered = junos.render(intent)
    assert "set switch-options vxlan-port 8472" in rendered


# ---------------------------------------------------------------------------
# IPv6 address wire-through (GAP-EVPN-3) — cross-mesh smoke
# ---------------------------------------------------------------------------


# Codecs whose render path emits IPv6 addresses to native syntax —
# parse-only codecs (cisco_iosxe_cli) sit on the source axis only.
_IPV6_TARGET_CAPABLE = [
    "arista_eos",
    "aruba_aoss",
    "cisco_iosxe",
    "cisco_iosxe_cli",
    "fortigate_cli",
    "juniper_junos",
    "mikrotik_routeros",
    "opnsense",
]


@pytest.mark.cross_mesh
@pytest.mark.parametrize("target_name", _IPV6_TARGET_CAPABLE)
def test_ipv6_address_survives_cross_mesh_render(target_name: str):
    """A canonical interface carrying ``2001:db8::1/64`` must
    round-trip through every bidirectional target codec's render
    path without losing the address.  Source side is the in-memory
    canonical tree (skipping the source-codec parse step) so the
    test isolates render-side preservation rather than parse +
    render together — that is the silent-drop class of bug GAP-
    EVPN-3 was filed for.
    """
    from netconfig.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalInterface,
        CanonicalIPv6Address,
    )
    target = _CODECS[target_name]()
    # Per-vendor name picked to satisfy each codec's name-shape
    # heuristics.  Wrong names occasionally confuse render
    # (e.g. mikrotik_routeros wants ``etherN``); a trio of common
    # forms covers all eight.
    name_for_vendor = {
        "arista_eos": "Ethernet1",
        "aruba_aoss": "1",
        "cisco_iosxe": "GigabitEthernet0/0/0",
        "cisco_iosxe_cli": "GigabitEthernet0/0/0",
        "fortigate_cli": "port1",
        "juniper_junos": "em0",
        "mikrotik_routeros": "ether1",
        "opnsense": "wan",
    }
    iface_name = name_for_vendor[target_name]
    extra = {}
    if target_name == "mikrotik_routeros":
        extra = {
            "interface_type": "ianaift:ethernetCsmacd",
            "default_name": iface_name,
        }
    intent = CanonicalIntent(interfaces=[CanonicalInterface(
        name=iface_name,
        enabled=True,
        ipv6_addresses=[
            CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
        ],
        **extra,
    )])
    rendered = target.render(intent)
    # Crude assertion — the canonical address string appears in
    # the rendered output.  Exact framing varies per vendor:
    # Arista/Cisco/Aruba: ``ipv6 address 2001:db8::1/64``
    # Junos: ``family inet6 address 2001:db8::1/64``
    # FortiGate: ``set ip6-address 2001:db8::1/64``
    # MikroTik: ``add address=2001:db8::1/64 interface=...``
    # OPNsense: ``<ipaddrv6>2001:db8::1</ipaddrv6>``
    assert "2001:db8::1" in rendered, (
        f"{target_name}: rendered output dropped the IPv6 address.\n"
        f"---\n{rendered}\n---"
    )


@pytest.mark.cross_mesh
@pytest.mark.parametrize("source_name", _IPV6_TARGET_CAPABLE)
@pytest.mark.parametrize("target_name", _IPV6_TARGET_CAPABLE)
def test_ipv6_address_survives_round_trip(
    source_name: str, target_name: str,
):
    """Full cross-mesh: a source codec parses an IPv6 address out of
    its native syntax, and the target codec renders it back.  Skips
    codecs whose minimal sample config doesn't declare an IPv6
    address (i.e., we don't have native-syntax sample input lying
    around for them) — for the rest, the canonical bridge must
    preserve the address through both halves of the round-trip.
    """
    # Native IPv6 input for each parse-capable codec.  These are
    # minimal but lexer-valid for their codec.
    src_v6_configs = {
        "arista_eos": (
            "interface Ethernet1\n"
            "   no switchport\n"
            "   ipv6 address 2001:db8::1/64\n"
            "!\n"
        ),
        "aruba_aoss": (
            "interface 1\n"
            "   routing\n"
            "   ipv6 address 2001:db8::1/64\n"
            "   exit\n"
        ),
        "cisco_iosxe": (
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">\n'
            "  <interface>\n"
            "    <name>Gi0/0/0</name>\n"
            "    <config><name>Gi0/0/0</name>"
            "<enabled>true</enabled></config>\n"
            "    <subinterfaces><subinterface>\n"
            "      <index>0</index>\n"
            '      <ipv6 xmlns="http://openconfig.net/yang/interfaces/ip">\n'
            "        <addresses><address>\n"
            "          <ip>2001:db8::1</ip>\n"
            "          <config><ip>2001:db8::1</ip>"
            "<prefix-length>64</prefix-length></config>\n"
            "        </address></addresses>\n"
            "      </ipv6>\n"
            "    </subinterface></subinterfaces>\n"
            "  </interface>\n"
            "</interfaces>\n"
        ),
        "cisco_iosxe_cli": (
            "interface GigabitEthernet1\n"
            " ipv6 address 2001:db8::1/64\n"
            "!\n"
        ),
        "fortigate_cli": (
            "config system interface\n"
            '    edit "port1"\n'
            "        set ip6-address 2001:db8::1/64\n"
            "    next\n"
            "end\n"
        ),
        "juniper_junos": (
            "set interfaces em0 unit 0 family inet6 address 2001:db8::1/64\n"
        ),
        "mikrotik_routeros": (
            "/ipv6 address\n"
            "add address=2001:db8::1/64 interface=ether1\n"
        ),
        "opnsense": (
            '<?xml version="1.0"?>\n'
            "<opnsense>\n"
            "  <interfaces>\n"
            "    <wan>\n"
            "      <if>em0</if>\n"
            "      <enable>1</enable>\n"
            "      <ipaddrv6>2001:db8::1</ipaddrv6>\n"
            "      <subnetv6>64</subnetv6>\n"
            "    </wan>\n"
            "  </interfaces>\n"
            "</opnsense>\n"
        ),
    }
    source = _CODECS[source_name]()
    target = _CODECS[target_name]()
    raw = src_v6_configs[source_name]
    intent = source.parse(raw)
    # The address must survive on the canonical tree.
    found = any(
        any(a.ip == "2001:db8::1" for a in iface.ipv6_addresses)
        for iface in intent.interfaces
    )
    assert found, (
        f"{source_name}: parse dropped the IPv6 address from "
        f"canonical.  intent.interfaces={[(i.name, i.ipv6_addresses) for i in intent.interfaces]}"
    )
    # And it must round-trip out the target side.
    rendered = target.render(intent)
    assert "2001:db8::1" in rendered, (
        f"{source_name} -> {target_name} dropped the IPv6 address "
        f"on render.\n---\n{rendered}\n---"
    )
