"""
Focused unit tests for the VyOS codec (``vyos``) — Phases 1-5.

Covers the curly-brace ``config.boot`` grammar: probe (config-version
trailer + structural fallback + the Junos non-collision the codec is
careful about), the brace-stack parser (hostname / ethernet+loopback+dummy
interfaces / addresses (IPv4+IPv6 / dhcp) / description / disable / mtu /
``vif`` VLAN sub-interfaces / static routes; Phase 2 local users + NTP +
bonding LAGs; Phase 3 ``service snmp`` + VRF routing-instances + the
per-interface ``vrf`` binding; Phase 5 ``interfaces vxlan`` netdevs +
block-form NTP servers), port-name classification, the canonical
round-trip, and the capability-matrix declarations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.juniper_junos import JunosCodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.codecs.vyos import port_names
from netcanon.migration.codecs.vyos.codec import VyOSCodec
from netcanon.migration.codecs.vyos.parse import _setform_to_brace

pytestmark = pytest.mark.unit


_SAMPLE = """\
interfaces {
    ethernet eth0 {
        address "192.0.2.1/30"
        description "uplink"
        mtu 1500
    }
    ethernet eth1 {
        address dhcp
        vif 100 {
            address "10.0.100.1/24"
        }
    }
    loopback lo {
        address "192.0.2.255/32"
        address "2001:db8::1/128"
    }
    dummy dum0 {
        disable
    }
}
protocols {
    static {
        route 0.0.0.0/0 {
            next-hop 192.0.2.2 {
                distance 1
            }
        }
        route6 ::/0 {
            next-hop 2001:db8::2 {
            }
        }
    }
}
system {
    host-name vyos-sample
}
// vyos-config-version: "system@27:interfaces@29"
"""

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "vyos" / "kitchen_sink.conf"
)


@pytest.fixture
def codec() -> VyOSCodec:
    return VyOSCodec()


def test_registered() -> None:
    c = get_codec("vyos")
    assert isinstance(c, VyOSCodec)
    assert c.input_format == "cli-vyos"
    assert c.direction == "bidirectional"
    assert c.certainty == "certified"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def test_probe_detects_config_version() -> None:
    score = VyOSCodec.probe(_SAMPLE)
    assert score is not None and score[0] == 99


def test_probe_structural_fallback_without_trailer() -> None:
    raw = (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        address 10.0.0.1/24\n"
        "        disable\n"
        "    }\n"
        "}\n"
        "system {\n"
        "    host-name r1\n"
        "}\n"
    )
    score = VyOSCodec.probe(raw)
    assert score is not None and score[0] == 90


def test_probe_rejects_junos_set_form() -> None:
    raw = (
        "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
        "set system host-name r1\n"
    )
    assert VyOSCodec.probe(raw) is None


def test_probe_rejects_junos_curly_form() -> None:
    """A Junos `show configuration` capture is curly-brace too, but its
    leaves end in `;` — the veto must reject it (VyOS has no `;`)."""
    raw = (
        "interfaces {\n"
        "    ge-0/0/0 {\n"
        "        unit 0 {\n"
        "            family inet {\n"
        "                address 10.0.0.1/24;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert VyOSCodec.probe(raw) is None


def test_junos_probe_does_not_steal_vyos() -> None:
    assert JunosCodec.probe(_SAMPLE) is None


# ---------------------------------------------------------------------------
# set-form input (`show configuration commands`)
# ---------------------------------------------------------------------------

#: The set-form translation of ``_SAMPLE`` (Phase-1 surfaces) — proves the
#: set-form front-end reproduces the curly-brace parse exactly.
_SAMPLE_SETFORM = """\
set interfaces ethernet eth0 address '192.0.2.1/30'
set interfaces ethernet eth0 description 'uplink'
set interfaces ethernet eth0 mtu 1500
set interfaces ethernet eth1 address dhcp
set interfaces ethernet eth1 vif 100 address '10.0.100.1/24'
set interfaces loopback lo address '192.0.2.255/32'
set interfaces loopback lo address '2001:db8::1/128'
set interfaces dummy dum0 disable
set protocols static route 0.0.0.0/0 next-hop 192.0.2.2 distance 1
set protocols static route6 ::/0 next-hop 2001:db8::2
set system host-name vyos-sample
"""

#: A richer set-form sample exercising Phase 2/3/5 surfaces + Tier-3 blocks.
_SETFORM_RICH = """\
set system host-name vyos-set
set interfaces ethernet eth0 address '10.0.0.1/24'
set interfaces ethernet eth0 vrf RED
set interfaces bonding bond0 mode '802.3ad'
set interfaces bonding bond0 member interface eth1
set interfaces vxlan vxlan0 vni 5000
set interfaces vxlan vxlan0 source-address 10.0.0.1
set interfaces vxlan vxlan0 group 239.1.1.1
set protocols static route 0.0.0.0/0 next-hop 10.0.0.254
set service snmp community FAKEPUB authorization ro
set service snmp location 'rack 4'
set service snmp v3 user monitor group ro_group
set service snmp v3 user monitor auth type sha
set service snmp v3 user monitor auth encrypted-password fakeauthhash
set system login user vyos authentication encrypted-password '$6$FAKE$hash'
set system ntp server 0.pool.ntp.org
set vrf name RED table 100
set firewall name FOO rule 10 action drop
set nat source rule 100 outbound-interface eth0
"""


def test_probe_detects_vyos_set_form() -> None:
    score = VyOSCodec.probe(_SETFORM_RICH)
    assert score is not None and score[0] >= 80
    assert "set-form" in score[1]


def test_setform_probe_beats_junos() -> None:
    """A VyOS set-form capture must out-score the ``juniper_junos`` probe
    so the detector resolves it to ``vyos`` — VyOS set-form is distinct
    from Junos set-form (Linux netdev names, ``set service``, ``set vrf
    name``)."""
    vy = VyOSCodec.probe(_SETFORM_RICH)
    jn = JunosCodec.probe(_SETFORM_RICH)
    assert vy is not None
    assert jn is None or vy[0] > jn[0]


def test_setform_idempotent_on_curly() -> None:
    """Converting already-curly-brace input is a no-op (the normaliser is
    safe to call unconditionally ahead of the brace-stack walker)."""
    assert _setform_to_brace(_SAMPLE) == _SAMPLE


def test_setform_equivalent_to_curly(codec: VyOSCodec) -> None:
    """The set-form front-end reproduces the curly-brace parse exactly."""
    assert (
        _normalise(codec.parse(_SAMPLE_SETFORM))
        == _normalise(codec.parse(_SAMPLE))
    )


def test_setform_parses_all_surfaces(codec: VyOSCodec) -> None:
    intent = codec.parse(_SETFORM_RICH)
    assert intent.hostname == "vyos-set"
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    assert eth0.ipv4_addresses[0].ip == "10.0.0.1"
    assert eth0.vrf == "RED"
    bond0 = next(lag for lag in intent.lags if lag.name == "bond0")
    assert bond0.members == ["eth1"] and bond0.mode == "active"
    assert intent.snmp is not None
    assert intent.snmp.community == "FAKEPUB"
    assert intent.snmp.v3_users[0].name == "monitor"
    assert intent.snmp.v3_users[0].auth_protocol == "sha"
    assert intent.local_users[0].name == "vyos"
    assert intent.ntp_servers == ["0.pool.ntp.org"]
    assert any(r.destination == "0.0.0.0/0" for r in intent.static_routes)
    assert intent.vxlan_vnis[0].vni == 5000
    assert intent.vxlan_vnis[0].source_interface == "10.0.0.1"


def test_setform_vrf_bigram(codec: VyOSCodec) -> None:
    """`set vrf name X` materialises an instance; `set interfaces … vrf X`
    only binds — the ``vrf name`` bigram disambiguates container vs leaf."""
    intent = codec.parse(_SETFORM_RICH)
    assert [ri.name for ri in intent.routing_instances] == ["RED"]
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    assert eth0.vrf == "RED"


def test_setform_phantom_instance_guard(codec: VyOSCodec) -> None:
    """A per-interface `set … vrf UNDECLARED` with no `set vrf name` must
    NOT conjure a routing-instance (the phantom-instance guard holds for
    set-form input too)."""
    raw = (
        "set interfaces ethernet eth0 address 10.0.0.1/24\n"
        "set interfaces ethernet eth0 vrf UNDECLARED\n"
    )
    intent = codec.parse(raw)
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    assert eth0.vrf == "UNDECLARED"
    assert intent.routing_instances == []


def test_setform_tier3_surfaced(codec: VyOSCodec) -> None:
    """Tier-3 blocks in set-form (`set firewall` / `set nat`) still feed
    the dropped-sections banner (the curly normalisation runs first)."""
    intent = codec.parse(_SETFORM_RICH)
    assert "firewall" in intent.dropped_tier3_sections
    assert "nat" in intent.dropped_tier3_sections


def test_setform_render_is_curly(codec: VyOSCodec) -> None:
    """Render always emits curly-brace config.boot regardless of input
    grammar (set-form is input-only); the result round-trips."""
    out = codec.render(codec.parse(_SAMPLE_SETFORM))
    assert "interfaces {" in out
    assert "    ethernet eth0 {" in out
    assert not any(ln.lstrip().startswith("set ") for ln in out.splitlines())
    assert (
        _normalise(codec.parse(out))
        == _normalise(codec.parse(_SAMPLE_SETFORM))
    )


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def test_parse_hostname(codec: VyOSCodec) -> None:
    assert codec.parse(_SAMPLE).hostname == "vyos-sample"


def test_parse_ethernet_l3(codec: VyOSCodec) -> None:
    intent = codec.parse(_SAMPLE)
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    assert eth0.ipv4_addresses[0].ip == "192.0.2.1"
    assert eth0.ipv4_addresses[0].prefix_length == 30
    assert eth0.description == "uplink"
    assert eth0.mtu == 1500
    assert eth0.enabled is True  # VyOS interfaces default UP


def test_parse_dhcp_address(codec: VyOSCodec) -> None:
    eth1 = next(i for i in codec.parse(_SAMPLE).interfaces if i.name == "eth1")
    assert eth1.dhcp_client is True


def test_parse_vif_subinterface(codec: VyOSCodec) -> None:
    """`ethernet eth1 { vif 100 { ... } }` → an `eth1.100` interface."""
    intent = codec.parse(_SAMPLE)
    vif = next((i for i in intent.interfaces if i.name == "eth1.100"), None)
    assert vif is not None
    assert vif.ipv4_addresses[0].ip == "10.0.100.1"


def test_parse_loopback_dual_stack(codec: VyOSCodec) -> None:
    lo = next(i for i in codec.parse(_SAMPLE).interfaces if i.name == "lo")
    assert lo.ipv4_addresses[0].ip == "192.0.2.255"
    assert lo.ipv6_addresses[0].ip == "2001:db8::1"


def test_parse_disable_sets_admin_down(codec: VyOSCodec) -> None:
    dum0 = next(i for i in codec.parse(_SAMPLE).interfaces if i.name == "dum0")
    assert dum0.enabled is False


def test_parse_static_routes(codec: VyOSCodec) -> None:
    routes = {r.destination: r for r in codec.parse(_SAMPLE).static_routes}
    assert routes["0.0.0.0/0"].gateway == "192.0.2.2"
    assert routes["0.0.0.0/0"].metric == 1
    assert routes["::/0"].gateway == "2001:db8::2"


def test_unquoted_values_tolerated(codec: VyOSCodec) -> None:
    """Older VyOS (1.3 / 1.4-rolling) leaves values bare — the parser
    must accept both quoted and unquoted forms."""
    raw = (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        address 10.0.0.1/24\n"
        "        description bare-desc\n"
        "    }\n"
        "}\n"
        "// vyos-config-version: \"x@1\"\n"
    )
    eth0 = next(i for i in codec.parse(raw).interfaces if i.name == "eth0")
    assert eth0.ipv4_addresses[0].ip == "10.0.0.1"
    assert eth0.description == "bare-desc"


# ---------------------------------------------------------------------------
# Phase 2 — local users / NTP / bonding LAGs
# ---------------------------------------------------------------------------

_P2 = """\
interfaces {
    bonding bond0 {
        address "10.0.0.1/24"
        mode 802.3ad
        member {
            interface eth1 {
            }
            interface eth2 {
            }
        }
    }
    ethernet eth3 {
        bond-group bond1
    }
    bonding bond1 {
        mode 802.3ad
    }
}
system {
    host-name r1
    login {
        user vyos {
            authentication {
                encrypted-password $6$FAKEhash
            }
        }
    }
    ntp {
        server 0.pool.ntp.org
        server 1.pool.ntp.org
    }
}
// vyos-config-version: "system@27"
"""


def test_parse_local_users(codec: VyOSCodec) -> None:
    users = {u.name: u for u in codec.parse(_P2).local_users}
    assert "vyos" in users
    assert users["vyos"].hashed_password == "$6$FAKEhash"
    assert users["vyos"].privilege_level == 15  # VyOS login users = admin


def test_parse_ntp_servers(codec: VyOSCodec) -> None:
    assert codec.parse(_P2).ntp_servers == [
        "0.pool.ntp.org", "1.pool.ntp.org",
    ]


def test_parse_bonding_member_interface_form(codec: VyOSCodec) -> None:
    """1.4-style ``bonding bondN { member { interface ethN { } } }``."""
    intent = codec.parse(_P2)
    bond0 = next(l for l in intent.lags if l.name == "bond0")
    assert sorted(bond0.members) == ["eth1", "eth2"]
    assert bond0.mode == "active"  # 802.3ad -> LACP
    eth1 = next(i for i in intent.interfaces if i.name == "eth1")
    assert eth1.lag_member_of == "bond0"


def test_parse_bonding_legacy_bond_group_form(codec: VyOSCodec) -> None:
    """Legacy 1.2-style ``ethernet ethN { bond-group bondN }``."""
    intent = codec.parse(_P2)
    bond1 = next(l for l in intent.lags if l.name == "bond1")
    assert "eth3" in bond1.members
    eth3 = next(i for i in intent.interfaces if i.name == "eth3")
    assert eth3.lag_member_of == "bond1"


def test_render_bonding_grammar(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_P2))
    assert "    bonding bond0 {" in out
    assert "        mode 802.3ad" in out
    assert "        member {" in out
    assert "            interface eth1 {" in out


def test_render_login_and_ntp(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_P2))
    assert "    login {" in out
    assert "        user vyos {" in out
    assert "encrypted-password $6$FAKEhash" in out
    assert "    ntp {" in out
    assert "        server 0.pool.ntp.org" in out


def test_round_trip_p2(codec: VyOSCodec) -> None:
    once = codec.parse(_P2)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


# ---------------------------------------------------------------------------
# Phase 3 — SNMP (service snmp) + VRF (routing instances + per-iface)
# ---------------------------------------------------------------------------

_P3 = """\
interfaces {
    ethernet eth0 {
        address "10.0.0.1/24"
        vrf "RED"
    }
    ethernet eth1 {
        address "10.0.1.1/24"
        vrf "BLUE"
    }
}
service {
    snmp {
        community FAKEPUB {
            authorization ro
        }
        contact "netops@example.com"
        location "rack 4"
        v3 {
            engineid 0xDEADBEEF01
            user monitor {
                group readers
                auth {
                    encrypted-password $6$FAKEauth
                    type sha
                }
                privacy {
                    encrypted-password $6$FAKEpriv
                    type aes
                }
            }
        }
    }
}
system {
    host-name r1
}
vrf {
    name RED {
        table 100
    }
    name BLUE {
        table 200
    }
}
// vyos-config-version: "system@27"
"""


def test_parse_snmp_community_location_contact(codec: VyOSCodec) -> None:
    snmp = codec.parse(_P3).snmp
    assert snmp is not None
    assert snmp.community == "FAKEPUB"
    assert snmp.location == "rack 4"
    assert snmp.contact == "netops@example.com"


def test_parse_snmp_v3_user(codec: VyOSCodec) -> None:
    snmp = codec.parse(_P3).snmp
    user = next(u for u in snmp.v3_users if u.name == "monitor")
    assert user.group == "readers"
    assert user.auth_protocol == "sha"
    assert user.auth_passphrase == "$6$FAKEauth"
    assert user.priv_protocol == "aes"
    assert user.priv_passphrase == "$6$FAKEpriv"
    assert user.engine_id == "0xDEADBEEF01"


def test_parse_vrf_instances(codec: VyOSCodec) -> None:
    names = {ri.name for ri in codec.parse(_P3).routing_instances}
    assert names == {"RED", "BLUE"}


def test_parse_iface_vrf_binding(codec: VyOSCodec) -> None:
    intent = codec.parse(_P3)
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    eth1 = next(i for i in intent.interfaces if i.name == "eth1")
    assert eth0.vrf == "RED"
    assert eth1.vrf == "BLUE"


def test_iface_vrf_does_not_conjure_instance(codec: VyOSCodec) -> None:
    """Phantom-instance guard: an interface bound to a VRF that was
    never declared with `vrf name <X>` must NOT materialise an instance."""
    raw = (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        address 10.0.0.1/24\n"
        "        vrf UNDECLARED\n"
        "    }\n"
        "}\n"
        "// vyos-config-version: \"x@1\"\n"
    )
    intent = codec.parse(raw)
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    assert eth0.vrf == "UNDECLARED"
    assert intent.routing_instances == []  # no phantom instance


def test_render_snmp(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_P3))
    assert "service {" in out
    assert "    snmp {" in out
    assert "        community FAKEPUB {" in out
    assert "            authorization ro" in out
    assert '        contact "netops@example.com"' in out
    assert '        location "rack 4"' in out
    assert "        v3 {" in out
    assert "            engineid 0xDEADBEEF01" in out
    assert "            user monitor {" in out
    assert "                    type sha" in out
    assert "                    type aes" in out


def test_render_vrf(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_P3))
    assert "vrf {" in out
    assert "    name BLUE {" in out
    assert "    name RED {" in out
    assert "        table 100" in out  # synthesised id (BLUE, sort-index 0)
    assert '        vrf "RED"' in out  # per-interface binding leaf


def test_round_trip_p3(codec: VyOSCodec) -> None:
    once = codec.parse(_P3)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


# ---------------------------------------------------------------------------
# Phase 5 — VXLAN (interfaces vxlan vxlanN)
# ---------------------------------------------------------------------------

_P5 = """\
interfaces {
    ethernet eth0 {
        address "10.0.0.1/24"
    }
    vxlan vxlan0 {
        vni 5000
        source-address 10.0.0.1
        group 239.1.1.1
        port 4789
    }
    vxlan vxlan1 {
        vni 10100
        source-interface eth0
        remote 198.51.100.9
        remote 198.51.100.10
    }
}
system {
    host-name r1
}
// vyos-config-version: "system@27"
"""


def test_parse_vxlan_vni_source_group(codec: VyOSCodec) -> None:
    vx = {v.vni: v for v in codec.parse(_P5).vxlan_vnis}
    assert set(vx) == {5000, 10100}
    assert vx[5000].source_interface == "10.0.0.1"
    assert vx[5000].mcast_group == "239.1.1.1"
    assert vx[5000].udp_port == 4789


def test_parse_vxlan_remote_flood_list(codec: VyOSCodec) -> None:
    vx = {v.vni: v for v in codec.parse(_P5).vxlan_vnis}
    assert vx[10100].flood_list == ["198.51.100.9", "198.51.100.10"]
    assert vx[10100].source_interface == "eth0"


def test_parse_vxlan_synthesises_vlan_id(codec: VyOSCodec) -> None:
    """CanonicalVxlan.vlan_id is required but a VyOS vxlan netdev has no
    VLAN — it is synthesised deterministically from the VNI."""
    vx = {v.vni: v for v in codec.parse(_P5).vxlan_vnis}
    assert vx[5000].vlan_id == ((5000 - 1) % 4094) + 1   # = 906
    assert vx[10100].vlan_id == ((10100 - 1) % 4094) + 1  # = 1912
    assert all(1 <= v.vlan_id <= 4094 for v in vx.values())


def test_vxlan_not_materialised_as_interface(codec: VyOSCodec) -> None:
    """A `vxlan vxlanN` netdev becomes a CanonicalVxlan, NOT a
    CanonicalInterface."""
    intent = codec.parse(_P5)
    assert not any(i.name.startswith("vxlan") for i in intent.interfaces)
    assert len(intent.vxlan_vnis) == 2


def test_render_vxlan(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_P5))
    assert "    vxlan vxlan0 {" in out
    assert "        vni 5000" in out
    assert "        source-address 10.0.0.1" in out   # IPv4 → source-address
    assert "        group 239.1.1.1" in out
    assert "        source-interface eth0" in out      # name → source-interface
    assert "        remote 198.51.100.9" in out
    assert "        port 4789" in out


def test_round_trip_p5(codec: VyOSCodec) -> None:
    once = codec.parse(_P5)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_parse_ntp_block_form(codec: VyOSCodec) -> None:
    """VyOS 1.4-rolling (mid-2023+) writes NTP servers as blocks
    (`server <host> { }`); the codec captures both that and the older
    bare-leaf form."""
    raw = (
        "system {\n"
        "    host-name r1\n"
        "    ntp {\n"
        "        server 0.pool.ntp.org {\n"
        "        }\n"
        "        server 1.pool.ntp.org {\n"
        "        }\n"
        "    }\n"
        "}\n"
        "// vyos-config-version: \"x@1\"\n"
    )
    assert codec.parse(raw).ntp_servers == ["0.pool.ntp.org", "1.pool.ntp.org"]


# ---------------------------------------------------------------------------
# Port names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("eth0", "physical"),
    ("eth0.100", "physical"),
    ("bond0", "lag"),
    ("dum0", "loopback"),
    ("lo", "loopback"),
    ("vxlan0", "vtep"),
])
def test_port_name_classify(name: str, kind: str) -> None:
    assert port_names.classify_port_name(name).kind == kind


@pytest.mark.parametrize("name", ["eth0", "bond0", "lo", "vxlan0"])
def test_port_name_round_trip(name: str) -> None:
    ident = port_names.classify_port_name(name)
    assert port_names.format_port_identity(ident) == name


# ---------------------------------------------------------------------------
# Round-trip (sorted compare, mirroring the harness normalisation)
# ---------------------------------------------------------------------------

def _normalise(intent):
    return {
        "hostname": intent.hostname,
        "interfaces": sorted(
            (
                i.name, i.enabled, i.mtu, i.description,
                i.dhcp_client, i.dhcp_client_v6, i.lag_member_of, i.vrf,
                tuple((a.ip, a.prefix_length) for a in i.ipv4_addresses),
                tuple((a.ip, a.prefix_length) for a in i.ipv6_addresses),
            )
            for i in intent.interfaces
        ),
        "routes": sorted(
            (r.destination, r.gateway, r.metric)
            for r in intent.static_routes
        ),
        "users": sorted(
            (u.name, u.hashed_password, u.privilege_level)
            for u in intent.local_users
        ),
        "ntp": list(intent.ntp_servers),
        "lags": sorted(
            (lag.name, tuple(sorted(lag.members)), lag.mode)
            for lag in intent.lags
        ),
        "snmp": None if intent.snmp is None else (
            intent.snmp.community,
            intent.snmp.location,
            intent.snmp.contact,
            tuple(sorted(
                (u.name, u.group, u.auth_protocol, u.auth_passphrase,
                 u.priv_protocol, u.priv_passphrase, u.engine_id)
                for u in intent.snmp.v3_users
            )),
        ),
        "vrf": sorted(
            (ri.name, ri.instance_type) for ri in intent.routing_instances
        ),
        "vxlan": sorted(
            (v.vni, v.vlan_id, v.mcast_group, tuple(v.flood_list),
             v.source_interface, v.udp_port)
            for v in intent.vxlan_vnis
        ),
    }


def test_round_trip_sample(codec: VyOSCodec) -> None:
    once = codec.parse(_SAMPLE)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_round_trip_kitchen_sink(codec: VyOSCodec) -> None:
    raw = _FIXTURE.read_text(encoding="utf-8")
    once = codec.parse(raw)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_render_emits_config_version_trailer(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_SAMPLE))
    assert "vyos-config-version" in out
    assert VyOSCodec.probe(out) is not None


def test_render_vif_nested_under_parent(codec: VyOSCodec) -> None:
    """A vif renders nested inside its parent ethernet block."""
    out = codec.render(codec.parse(_SAMPLE))
    assert "    ethernet eth1 {" in out
    assert "        vif 100 {" in out


# ---------------------------------------------------------------------------
# Capability matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/system/hostname",
    "/interfaces/interface/ipv4/address/ip",
    "/interfaces/interface/ipv6/address/ip",
    "/interfaces/interface/config/mtu",
    "/interfaces/interface/dhcp-client-v6",
    "/routing/static-route",
    # Phase 2
    "/local-users/user/name",
    "/local-users/user/hashed-password",
    "/system/ntp-server",
    "/lags/lag/name",
    "/lags/lag/members",
    "/interfaces/interface/lag-member-of",
    # Phase 3
    "/snmp/community",
    "/snmp/location",
    "/snmp/contact",
    "/snmp/v3-user",
    "/routing-instances/instance/name",
    "/interfaces/interface/config/vrf",
    # Phase 5
    "/vxlan-vnis/vni",
    "/vxlan-vnis/mcast-group",
    "/vxlan-vnis/flood-list",
    "/vxlan-vnis/udp-port",
])
def test_matrix_supported(codec: VyOSCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "supported"


@pytest.mark.parametrize("path", [
    "/interfaces/interface/config/type",
    "/system/raw-sections/version-banner",
    # Phase 2
    "/local-users/user/privilege-level",
    "/lags/lag/mode",
    # Phase 3
    "/snmp/v3-user/auth-passphrase",
    "/snmp/v3-user/engine-id",
    "/routing-instances/instance/table",
    # Phase 5
    "/vxlan-vnis/source-interface",
    "/vxlan-vnis/vlan-id",
])
def test_matrix_lossy(codec: VyOSCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "lossy"


@pytest.mark.parametrize("path", [
    "/vlans/vlan/id",
    "/routing/static-route/vrf",
    "/vxlan-vnis/l2vni-route-target",
    "/routing-protocols/bgp",
    "/nat",
    "/firewall",
])
def test_matrix_unsupported(codec: VyOSCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "unsupported"
