"""A path a codec's capability matrix calls ``supported`` is written.

``CapabilityMatrix.classify`` is an exact-string match, and a path no
list names is ``supported``.  So a codec that writes nothing for a field
reported it as translated unless someone had thought to declare it, and
the validation report said nothing of a field the output did not hold:
a DHCP pool's gateway on a codec that writes no DHCP pool, the MAC of a
virtual gateway it writes none of, every field of a VRF on a codec with
no VRF, an HSRP group on a codec that writes VRRP only.  Each codec now
declares what it does not write, by the reason, in two tables of its
``codec.py``: ``_NOT_RENDERED`` (``unsupported``: it has no form for the
path, or the path is a field of a record it declares unsupported) and
``_DROPPED`` (``lossy``, severity ``warn``: it writes the path only in
some cases, or writes the record without the field).

This module holds the matrix to the render.  For every walkable path
(``_WALKABLE``, the walk of the maximal tree) a probe below builds the
smallest tree that holds it, in EOS port names; the port translator
moves it into the target's names, and every public codec renders it and
reads it back with its own parser.  A path the codec classifies
``supported`` has to be in the walk of what was read back.  The tree is
rendered as a port and as a VLAN interface, and stamped as the codec's
own and as another vendor's (a renderer can do more for its own tree),
and a path counts as written if any of the four writes it: the test is
one-sided, and a path that comes back from one tree is not shown to come
back from every tree.

What is read back is compared after the projections that fold one form
of a fact into another (``project_switchport_to_vlan`` and the rest),
and with three equivalences written out in ``_read_back``: an L3 address
a platform keeps on its VLAN (Junos ``irb``) is the interface's address;
a platform with one MTU writes an IP MTU as the MTU; and a VNI floods by
a multicast group or by a list of peers, which are two probes.  The
probes for a VRRP group build a CARP group for OPNsense, which writes
CARP only (its ``_DROPPED`` says so).

A field of a record the codec declares unsupported is unsupported too
(``test_a_field_of_a_record_not_written_is_not_supported``): the record
a path belongs to is typed by hand in ``OWNER``.

**The blind spot.**  The read-back is by the codec's own parser, so a
line written where the device does not take it, and read back from the
same place, passes here.  Two such lines were found by reading the
vendors' documentation, not by this test: FortiOS ``set vrip6`` in the
interface's ``config vrrp`` (Fortinet documents IPv6 VRRP in ``config
ipv6`` / ``config vrrp6``), and Junos ``virtual-inet6-address`` in a
group under an IPv4 address (Juniper documents a ``vrrp-inet6-group``
under a ``family inet6`` address).  Both are declared lossy.  The other
way, a line the parser does not read back fails here though it may be
right; those are pinned in ``KNOWN_OPEN`` with what is wrong, and the
change that mends one empties its pin.  Not reached: a tree no probe
builds (a path written for one shape of a record and not another), and
a renderer that writes a value the parser reads back into the same field
from a line that means something else.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from netcanon.migration._user_secrets import is_migratable
from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalEvpnType5Route,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
    CanonicalVxlan,
)
from netcanon.migration.canonical.port_names import translate_port_names
from netcanon.migration.canonical.transforms import (
    project_svi_to_vlan,
    project_switchport_to_vlan,
    project_vlan_to_switchport,
    synthesize_svis_from_vlan_l3,
)
from netcanon.migration.canonical.xpath_walker import _walk_canonical
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from tests.unit.migration.test_registry_capability_honesty import _WALKABLE

_ETH = "ianaift:ethernetCsmacd"
_CODECS = sorted(list_public_codecs())

#: Synthetic secrets, one of which each codec takes as a local user's
#: password (``is_migratable``).
_HASHES = (
    "zzPlainPass1",
    "$6$fakesalt$" + "a" * 86,
    "$5$fakesalt$" + "a" * 43,
    "$1$fakesalt$" + "a" * 22,
    "$2y$10$" + "a" * 53,
    "$9$fakesaltfake$" + "a" * 43,
)


@dataclass(frozen=True)
class _At:
    """Where a probe's tree is built: for which target, and whether its
    routed interface is a port or a VLAN interface."""

    target: str
    shape: str  # "port" or "svi"


def _a4(ip: str, plen: int = 24, **kw) -> CanonicalIPv4Address:
    return CanonicalIPv4Address(ip=ip, prefix_length=plen, **kw)


def _a6(ip: str, plen: int = 64, **kw) -> CanonicalIPv6Address:
    return CanonicalIPv6Address(ip=ip, prefix_length=plen, **kw)


def _port(name: str = "Ethernet1", **kw) -> CanonicalInterface:
    kw.setdefault("enabled", True)
    kw.setdefault("interface_type", _ETH)
    return CanonicalInterface(name=name, **kw)


def _routed(at: _At, name: str | None = None, **kw) -> CanonicalInterface:
    kw.setdefault("ipv4_addresses", [_a4("10.7.7.1")])
    if name is None:
        name = "Ethernet1" if at.shape == "port" else "Vlan10"
        if at.shape == "svi":
            kw["interface_type"] = ""
    return _port(name, **kw)


def _tree(at: _At, **kw) -> CanonicalIntent:
    kw.setdefault("hostname", "h")
    tree = CanonicalIntent(**kw)
    if at.shape == "svi" and not any(v.id == 10 for v in tree.vlans):
        tree.vlans.append(CanonicalVlan(id=10, name="V10"))
    return tree


def _ri(**kw) -> CanonicalRoutingInstance:
    kw.setdefault("instance_type", "vrf")
    return CanonicalRoutingInstance(name="VRFZ", **kw)


#: probe name -> (the function that builds its tree, the paths it holds).
PROBES: dict[str, tuple[Callable[[_At], CanonicalIntent], tuple[str, ...]]] = {}


def _probe(*paths: str):
    def deco(fn):
        PROBES[fn.__name__] = (fn, paths)
        return fn
    return deco


_I = "/interfaces/interface"
_G = f"{_I}/vrrp-groups/group"


@_probe("/system/hostname", "/system/domain", "/system/dns-server", "/system/ntp-server",
        "/system/timezone", "/system/syslog-server")
def system(at):
    return _tree(at, domain="zz.test", dns_servers=["10.0.0.53"], ntp_servers=["10.0.0.123"],
                 timezone="UTC", syslog_servers=["10.0.5.14"])


@_probe(f"{_I}/name", f"{_I}/config/description", f"{_I}/config/enabled", f"{_I}/config/type",
        f"{_I}/config/mtu", f"{_I}/ipv4/address/ip", f"{_I}/ipv4/address/prefix-length",
        f"{_I}/ipv4/address/secondary-ip")
def l3v4(at):
    return _tree(at, interfaces=[_routed(at, description="zzdesc", mtu=9123, ipv4_addresses=[
        _a4("10.7.7.1"), _a4("10.7.8.1", is_secondary=True)])])


@_probe(f"{_I}/ipv6/address/ip", f"{_I}/ipv6/address/prefix-length", f"{_I}/ipv6/address/scope",
        f"{_I}/ipv6/address/secondary-ip")
def l3v6(at):
    return _tree(at, interfaces=[_routed(at, ipv4_addresses=[], ipv6_addresses=[
        _a6("2001:db8:7::1"), _a6("2001:db8:8::1"), _a6("fe80::7", 64, scope="link-local")])])


@_probe(f"{_I}/config/ip-mtu")
def ip_mtu(at):
    return _tree(at, interfaces=[_routed(at, ip_mtu=1477)])


@_probe(f"{_I}/config/ip-mtu-beside-mtu")
def ip_mtu_beside(at):
    return _tree(at, interfaces=[_routed(at, mtu=9123, ip_mtu=1477)])


@_probe(f"{_I}/config/vrf", "/routing-instances/instance", "/routing-instances/instance/name",
        "/routing-instances/instance/instance-type")
def vrf(at):
    return _tree(at, interfaces=[_routed(at, vrf="VRFZ")], routing_instances=[_ri()])


@_probe("/routing-instances/instance/route-distinguisher", "/routing-instances/instance/rt-imports",
        "/routing-instances/instance/rt-exports", "/routing-instances/instance/description",
        "/routing-instances/instance/l3-vni")
def vrf_full(at):
    return _tree(at, interfaces=[_routed(at, vrf="VRFZ")], routing_instances=[_ri(
        route_distinguisher="65000:77", rt_imports=["65000:78"], rt_exports=["65000:79"],
        description="zzvrfdesc", l3_vni=50077)])


@_probe(f"{_I}/dhcp-client")
def dhcp(at):
    return _tree(at, interfaces=[_routed(at, dhcp_client=True, ipv4_addresses=[])])


@_probe(f"{_I}/dhcp-client-v6")
def dhcp6(at):
    return _tree(at, interfaces=[_routed(at, dhcp_client_v6="dhcp6", ipv4_addresses=[])])


@_probe(f"{_I}/dot1q-vlan")
def dot1q(at):
    return _tree(at, interfaces=[
        _port("Ethernet2"), _routed(at, "Ethernet2.100", dot1q_vlan=100, interface_type="")])


@_probe(f"{_I}/dot1q-inner-vlan")
def qinq(at):
    return _tree(at, interfaces=[_port("Ethernet2"), _routed(
        at, "Ethernet2.100", dot1q_vlan=100, dot1q_inner_vlan=200, interface_type="")])


@_probe(f"{_I}/dot1q-native")
def dot1q_native(at):
    return _tree(at, interfaces=[_port("Ethernet2"), _routed(
        at, "Ethernet2.30", dot1q_vlan=30, dot1q_native=True, interface_type="")])


@_probe(f"{_I}/tunnel-type")
def tunnel(at):
    return _tree(at, interfaces=[_routed(at, "Tunnel0", tunnel_type="gre", interface_type="ianaift:tunnel")])


@_probe(f"{_I}/switchport-mode", f"{_I}/access-vlan", "/vlans/vlan/untagged-ports")
def access(at):
    return _tree(at, interfaces=[_port(switchport_mode="access", access_vlan=10)],
                 vlans=[CanonicalVlan(id=10, name="V10", untagged_ports=["Ethernet1"])])


@_probe(f"{_I}/voice-vlan")
def voice(at):
    return _tree(at, interfaces=[_port(switchport_mode="access", access_vlan=10, voice_vlan=200)],
                 vlans=[CanonicalVlan(id=10, name="V10", untagged_ports=["Ethernet1"]),
                        CanonicalVlan(id=200, name="V200", tagged_ports=["Ethernet1"])])


@_probe(f"{_I}/trunk-allowed-vlans", f"{_I}/trunk-native-vlan", "/vlans/vlan/tagged-ports")
def trunk(at):
    return _tree(at, interfaces=[_port("Ethernet2", switchport_mode="trunk", trunk_allowed_vlans=[10, 20, 99],
                                       trunk_native_vlan=99)],
                 vlans=[CanonicalVlan(id=10, name="V10", tagged_ports=["Ethernet2"]),
                        CanonicalVlan(id=20, name="V20", tagged_ports=["Ethernet2"]),
                        CanonicalVlan(id=99, name="V99", untagged_ports=["Ethernet2"])])


@_probe("/vlans/vlan/id", "/vlans/vlan/name", "/vlans/vlan/description")
def vlan(at):
    return _tree(at, vlans=[CanonicalVlan(id=10, name="zzvlanname", description="zzvlandesc")])


def _svi(at: _At, family: int, **kw) -> CanonicalIntent:
    if family == 4:
        iface = _port("Vlan10", interface_type="", ipv4_addresses=[_a4("10.7.7.1", **kw)])
    else:
        iface = _port("Vlan10", interface_type="", ipv6_addresses=[_a6("2001:db8:7::1", **kw)])
    return _tree(at, interfaces=[iface], vlans=[CanonicalVlan(id=10, name="V10")])


@_probe(f"{_I}/ipv4/address/virtual-gateway-address")
def vgw4(at):
    return _svi(at, 4, virtual_gateway_address="10.7.7.254")


@_probe(f"{_I}/ipv4/address/virtual-gateway-mac")
def vgw4_mac(at):
    return _svi(at, 4, virtual_gateway_address="10.7.7.254", virtual_gateway_mac="00:00:5e:00:01:77")


@_probe(f"{_I}/ipv6/address/virtual-gateway-address")
def vgw6(at):
    return _svi(at, 6, virtual_gateway_address="2001:db8:7::fe")


@_probe(f"{_I}/ipv6/address/virtual-gateway-mac")
def vgw6_mac(at):
    return _svi(at, 6, virtual_gateway_address="2001:db8:7::fe", virtual_gateway_mac="00:00:5e:00:02:77")


@_probe("/anycast-gateway-mac")
def anycast(at):
    tree = _svi(at, 4, virtual_gateway_address="10.7.7.254")
    tree.anycast_gateway_mac = "00:1c:73:00:dc:77"
    return tree


@_probe("/vlans/vlan/ipv4/address/ip", "/vlans/vlan/ipv4/address/secondary-ip")
def vlan_l3(at):
    return _tree(at, vlans=[CanonicalVlan(id=10, name="V10", ipv4_addresses=[
        _a4("10.7.7.1"), _a4("10.7.8.1", is_secondary=True)])])


@_probe("/vlans/vlan/ipv4/address/virtual-gateway-address")
def vlan_vgw(at):
    return _tree(at, vlans=[CanonicalVlan(id=10, name="V10", ipv4_addresses=[
        _a4("10.7.7.1", virtual_gateway_address="10.7.7.254")])])


@_probe("/vlans/vlan/ipv4/address/virtual-gateway-mac")
def vlan_vgw_mac(at):
    return _tree(at, vlans=[CanonicalVlan(id=10, name="V10", ipv4_addresses=[
        _a4("10.7.7.1", virtual_gateway_address="10.7.7.254", virtual_gateway_mac="00:00:5e:00:01:77")])])


def _mode(at: _At) -> str:
    """OPNsense writes CARP groups only (its ``_DROPPED`` says so)."""
    return "carp" if at.target == "opnsense" else "vrrp"


@_probe(_G, f"{_G}/mode", f"{_G}/priority", f"{_G}/preempt", f"{_G}/advertisement-interval",
        f"{_G}/virtual-ips")
def vrrp(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ips=["10.7.7.254", "10.7.7.253"],
                               priority=120, advertisement_interval=3)
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group])])


@_probe(_G, f"{_G}/mode")
def vrrp_hsrp(at):
    """A group of another protocol: an NX-OS or IOS-XE HSRP group."""
    group = CanonicalVRRPGroup(group_id=7, mode="hsrp", virtual_ips=["10.7.7.254"], priority=120)
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group])])


@_probe(_G, f"{_G}/mode")
def vrrp_carp(at):
    group = CanonicalVRRPGroup(group_id=7, mode="carp", virtual_ips=["10.7.7.254"], priority=120)
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group])])


@_probe(f"{_G}/virtual-ipv6s")
def vrrp_v6(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ips=["10.7.7.254"],
                               virtual_ipv6s=["2001:db8:7::fe"], priority=120)
    return _tree(at, interfaces=[_routed(at, ipv6_addresses=[_a6("2001:db8:7::1")], vrrp_groups=[group])])


@_probe(_G, f"{_G}/virtual-ipv6s")
def vrrp_v6_only(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ipv6s=["2001:db8:7::fe"], priority=120)
    return _tree(at, interfaces=[_routed(at, ipv6_addresses=[_a6("2001:db8:7::1")], vrrp_groups=[group])])


@_probe(f"{_G}/virtual-mac")
def vrrp_vmac(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ips=["10.7.7.254"],
                               virtual_mac="00:00:5e:00:01:07")
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group])])


@_probe(f"{_G}/track-interfaces")
def vrrp_track(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ips=["10.7.7.254"],
                               track_interfaces=["Ethernet2"])
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group]),
                                 _routed(at, "Ethernet2", ipv4_addresses=[_a4("10.7.9.1")])])


@_probe(f"{_G}/authentication")
def vrrp_auth(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ips=["10.7.7.254"],
                               authentication="plain:zzauth")
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group])])


@_probe(f"{_G}/description")
def vrrp_desc(at):
    group = CanonicalVRRPGroup(group_id=7, mode=_mode(at), virtual_ips=["10.7.7.254"], description="zzvrrpdesc")
    return _tree(at, interfaces=[_routed(at, vrrp_groups=[group])])


@_probe("/lags/lag/name", "/lags/lag/mode", "/lags/lag/members", f"{_I}/lag-member-of")
def lag(at):
    return _tree(at, interfaces=[_port("Ethernet1", lag_member_of="Port-Channel1"),
                                 _port("Ethernet2", lag_member_of="Port-Channel1"),
                                 _routed(at, "Port-Channel1", interface_type="ianaift:ieee8023adLag")],
                 lags=[CanonicalLAG(name="Port-Channel1", members=["Ethernet1", "Ethernet2"], mode="active")])


@_probe("/local-users/user/name", "/local-users/user/privilege-level", "/local-users/user/role",
        "/local-users/user/hashed-password")
def users(at):
    digest = next((h for h in _HASHES if is_migratable(h, at.target)), _HASHES[0])
    return _tree(at, local_users=[CanonicalLocalUser(name="zzuser", privilege_level=15, role="admin",
                                                     hashed_password=digest)])


@_probe("/radius-servers/server/host", "/radius-servers/server/key")
def radius(at):
    return _tree(at, radius_servers=[CanonicalRADIUSServer(host="10.0.0.1", key="zzradkey1")])


@_probe("/snmp/community", "/snmp/location", "/snmp/contact", "/snmp/trap-host")
def snmp(at):
    return _tree(at, snmp=CanonicalSNMP(community="zzcomm", location="zzloc", contact="zzcontact",
                                        trap_hosts=["10.9.9.9"]))


@_probe("/snmp/v3-user", "/snmp/v3-user/auth-protocol", "/snmp/v3-user/auth-passphrase",
        "/snmp/v3-user/priv-protocol", "/snmp/v3-user/priv-passphrase", "/snmp/v3-user/group",
        "/snmp/v3-user/engine-id")
def snmpv3(at):
    return _tree(at, snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
        name="zzv3", group="zzgroup", auth_protocol="sha", auth_passphrase="zzauthpass1",
        priv_protocol="aes", priv_passphrase="zzprivpass1", engine_id="80000009ff")]))


@_probe("/routing/static-route", "/routing/static-route/gateway", "/routing/static-route/metric",
        "/routing/static-route/description")
def route(at):
    return _tree(at, interfaces=[_routed(at)], static_routes=[CanonicalStaticRoute(
        destination="10.88.0.0/16", gateway="10.7.7.9", metric=200, description="zzroute")])


@_probe("/routing/static-route/interface")
def route_iface(at):
    return _tree(at, interfaces=[_routed(at)], static_routes=[CanonicalStaticRoute(
        destination="10.88.0.0/16", gateway="10.7.7.9", interface="Ethernet1")])


@_probe("/routing/static-route/interface")
def route_iface_only(at):
    """A route out of an interface with no gateway: what a tunnel or a
    point-to-point link is given."""
    return _tree(at, interfaces=[_routed(at), _routed(at, "Tunnel0", tunnel_type="gre",
                                                      interface_type="ianaift:tunnel",
                                                      ipv4_addresses=[_a4("10.9.0.1", 30)])],
                 static_routes=[CanonicalStaticRoute(destination="10.88.0.0/16", interface="Tunnel0")])


@_probe("/routing/static-route/vrf")
def route_vrf(at):
    return _tree(at, interfaces=[_routed(at, vrf="VRFZ")], routing_instances=[_ri()], static_routes=[
        CanonicalStaticRoute(destination="10.88.0.0/16", gateway="10.7.7.9", vrf="VRFZ")])


@_probe("/dhcp-servers/pool", "/dhcp-servers/pool/gateway", "/dhcp-servers/pool/dns-servers",
        "/dhcp-servers/pool/domain-name", "/dhcp-servers/pool/lease-time")
def dhcp_pool(at):
    return _tree(at, interfaces=[_routed(at)], dhcp_servers=[CanonicalDHCPPool(
        network="10.7.7.0/24", interface="Ethernet1" if at.shape == "port" else "Vlan10",
        start_ip="10.7.7.10", end_ip="10.7.7.99", gateway="10.7.7.1",
        dns_servers=["10.7.7.2"], domain_name="zz.example", lease_time=7200)])


def _vxlan(at: _At, **kw) -> CanonicalIntent:
    loopback = _port("Loopback0", interface_type="ianaift:softwareLoopback",
                     ipv4_addresses=[_a4("10.255.0.1", 32)])
    return _tree(at, interfaces=[loopback], vlans=[CanonicalVlan(id=10, name="V10")], vxlan_vnis=[
        CanonicalVxlan(vlan_id=10, vni=10077, source_interface="Loopback0", udp_port=4790, **kw)])


@_probe("/vxlan-vnis/vni", "/vxlan-vnis/vlan-id", "/vxlan-vnis/mcast-group",
        "/vxlan-vnis/source-interface", "/vxlan-vnis/udp-port")
def vxlan(at):
    return _vxlan(at, mcast_group="239.7.7.7")


@_probe("/vxlan-vnis/flood-list")
def vxlan_flood(at):
    """A VNI floods by a multicast group or by a list of peers, not both."""
    return _vxlan(at, flood_list=["10.255.0.9"])


@_probe("/evpn-type5-routes/route")
def evpn5(at):
    return _tree(at, interfaces=[_routed(at, vrf="VRFZ")], routing_instances=[_ri(route_distinguisher="65000:77")],
                 evpn_type5_routes=[CanonicalEvpnType5Route(vrf="VRFZ", prefix="10.88.0.0/16")])


# --- reading back -----------------------------------------------------------


def _read_back(codec, text: str) -> set[str]:
    """The paths of what *codec*'s parser reads from *text*, with the
    equivalences the module docstring names."""
    back = codec.parse(text)
    walked = set(_walk_canonical(back))
    folded = copy.deepcopy(back)
    project_switchport_to_vlan(folded)
    project_vlan_to_switchport(folded)
    project_svi_to_vlan(folded)
    folded.interfaces.extend(synthesize_svis_from_vlan_l3(folded))
    walked |= set(_walk_canonical(folded))
    # An SVI's L3 held on its VLAN (Junos irb) is the interface's L3.
    for path in list(walked):
        if path.startswith("/vlans/vlan/ipv4/address/"):
            walked.add(f"{_I}/ipv4/address/" + path.rsplit("/", 1)[1])
    # A platform with one MTU writes an IP MTU as the MTU.
    if any(i.mtu == 1477 for i in back.interfaces):
        walked.add(f"{_I}/config/ip-mtu")
    return walked


def _written(target: str, probe: str) -> set[str]:
    """Every path any of the four trees of *probe* comes back with from
    *target*.  Fails if no tree renders."""
    codec, eos = get_codec(target), get_codec("arista_eos")
    build = PROBES[probe][0]
    walked: set[str] = set()
    errors: list[str] = []
    rendered = 0
    for shape in ("port", "svi"):
        for stamp in (codec.capabilities.vendor_id, eos.capabilities.vendor_id):
            tree = build(_At(target, shape))
            translate_port_names(tree, eos, codec, strip_unmappable=False)
            tree.source_vendor = stamp
            try:
                text = codec.render(tree)
            except Exception as exc:  # another tree may render; none rendering fails below
                errors.append(f"{shape}/{stamp}: {type(exc).__name__}")
                continue
            rendered += 1
            walked |= _read_back(codec, text)
    assert rendered, f"{target} renders no tree of {probe}: {errors}"
    return walked


def _not_written(target: str, probe: str, classify: Callable[[str], str] | None = None) -> list[str]:
    """The paths of *probe* that *classify* (the target's own matrix by
    default) calls ``supported`` and that do not come back."""
    classify = classify or get_codec(target).capabilities.classify
    paths = [p for p in PROBES[probe][1] if classify(p) == "supported"]
    if not paths:
        return []
    walked = _written(target, probe)
    return [p for p in paths if p not in walked]


#: (codec, path) -> what is wrong.  Each is written by the renderer and
#: not read back by the codec's own parser, so this module cannot see it
#: written; the line itself has not been checked against the vendor.
#: The change that mends the parser empties the pin.  None is open: the
#: four this table held (IOS-XE CLI `ip address dhcp`, FortiOS `set mode
#: dhcp`, a RouterOS `/user` line's `password=`, a RouterOS route whose
#: `gateway=` is an interface name) are read back now.
KNOWN_OPEN: dict[tuple[str, str], str] = {}

#: The probe of each pin that shows it.
_PIN_PROBE: dict[tuple[str, str], str] = {}


@pytest.mark.parametrize("probe", sorted(PROBES))
@pytest.mark.parametrize("target", _CODECS)
def test_a_supported_path_comes_back(target: str, probe: str) -> None:
    missing = [p for p in _not_written(target, probe) if (target, p) not in KNOWN_OPEN]
    assert missing == [], (
        f"{target} classifies {missing} as supported, and a tree of `{probe}` "
        f"rendered by it does not come back with them: declare each in the "
        f"codec's _NOT_RENDERED or _DROPPED, by the reason, or write it"
    )


@pytest.mark.parametrize("pin", sorted(KNOWN_OPEN))
def test_each_pin_is_still_open(pin: tuple[str, str]) -> None:
    """A pin is a path still called supported and still not read back:
    the change that mends it, or declares it, takes the pin out."""
    target, path = pin
    assert get_codec(target).capabilities.classify(path) == "supported", pin
    assert path in _not_written(target, _PIN_PROBE[pin]), pin


def test_every_pin_names_its_probe() -> None:
    assert set(_PIN_PROBE) == set(KNOWN_OPEN)
    for (_target, path), probe in _PIN_PROBE.items():
        assert path in PROBES[probe][1]


# --- the probes reach every walkable path -----------------------------------


def test_the_probes_hold_every_walkable_path() -> None:
    held = {p for _, paths in PROBES.values() for p in paths}
    assert held == set(_WALKABLE), (
        f"walkable and held by no probe: {sorted(set(_WALKABLE) - held)}; "
        f"held and not walkable: {sorted(held - set(_WALKABLE))}"
    )


@pytest.mark.parametrize("probe", sorted(PROBES))
def test_each_probe_holds_its_paths(probe: str) -> None:
    """A probe whose tree does not hold a path cannot show it written."""
    build, paths = PROBES[probe]
    for target in ("arista_eos", "opnsense"):
        walked = set(_walk_canonical(build(_At(target, "port"))))
        assert [p for p in paths if p not in walked] == [], (probe, target)


# --- each check is handed the defect it is for ------------------------------


def test_the_check_sees_a_path_that_is_not_written() -> None:
    """AOS-S writes no DHCP pool: told that every path is supported, the
    check names the pool and its fields."""
    missing = _not_written("aruba_aoss", "dhcp_pool", classify=lambda _p: "supported")
    assert set(missing) == set(PROBES["dhcp_pool"][1])


def test_the_check_does_not_name_a_path_that_is_written() -> None:
    """Told the same, it names nothing of what EOS does write: an
    interface, its addresses and its MTU."""
    assert _not_written("arista_eos", "l3v4", classify=lambda _p: "supported") == []


def test_the_check_asks_nothing_of_a_path_not_called_supported() -> None:
    assert _not_written("aruba_aoss", "dhcp_pool", classify=lambda _p: "unsupported") == []


# --- a field of a record that is not written --------------------------------


#: path, or path prefix ending in ``/``, -> the record it belongs to.
#: The longest match wins.  Typed by hand: a record a codec declares
#: unsupported takes every path that belongs to it.  A value that is not
#: a walkable path is a whole-field marker some codecs declare
#: (``/dhcp_servers``).
OWNER: dict[str, str | None] = {
    f"{_I}/": f"{_I}/name",
    f"{_I}/name": None,
    f"{_I}/ipv4/address/": f"{_I}/ipv4/address/ip",
    f"{_I}/ipv4/address/ip": f"{_I}/name",
    f"{_I}/ipv4/address/virtual-gateway-mac": f"{_I}/ipv4/address/virtual-gateway-address",
    f"{_I}/ipv6/address/": f"{_I}/ipv6/address/ip",
    f"{_I}/ipv6/address/ip": f"{_I}/name",
    f"{_I}/ipv6/address/virtual-gateway-mac": f"{_I}/ipv6/address/virtual-gateway-address",
    f"{_G}/": _G,
    _G: f"{_I}/name",
    f"{_I}/access-vlan": f"{_I}/switchport-mode",
    f"{_I}/voice-vlan": f"{_I}/switchport-mode",
    f"{_I}/trunk-allowed-vlans": f"{_I}/switchport-mode",
    f"{_I}/trunk-native-vlan": f"{_I}/switchport-mode",
    f"{_I}/dot1q-inner-vlan": f"{_I}/dot1q-vlan",
    f"{_I}/dot1q-native": f"{_I}/dot1q-vlan",
    f"{_I}/lag-member-of": "/lags/lag/name",
    f"{_I}/config/vrf": "/routing-instances/instance",
    f"{_I}/config/ip-mtu-beside-mtu": f"{_I}/config/ip-mtu",
    "/vlans/vlan/": "/vlans/vlan/id",
    "/vlans/vlan/id": "/vlans",
    "/vlans/vlan/ipv4/address/": "/vlans/vlan/ipv4/address/ip",
    "/vlans/vlan/ipv4/address/ip": "/vlans/vlan/id",
    "/vlans/vlan/ipv4/address/virtual-gateway-mac": "/vlans/vlan/ipv4/address/virtual-gateway-address",
    "/lags/lag/": "/lags/lag/name",
    "/lags/lag/name": "/lags",
    "/local-users/user/": "/local-users/user/name",
    "/local-users/user/name": "/local_users",
    "/routing-instances/instance/": "/routing-instances/instance",
    "/routing-instances/instance": "/routing_instances",
    "/radius-servers/server/": "/radius-servers/server/host",
    "/radius-servers/server/host": "/radius_servers",
    "/dhcp-servers/pool/": "/dhcp-servers/pool",
    "/dhcp-servers/pool": "/dhcp_servers",
    "/routing/static-route/": "/routing/static-route",
    "/routing/static-route/vrf": "/routing-instances/instance",
    "/routing/static-route": "/static_routes",
    "/evpn-type5-routes/route": "/evpn_type5_routes",
    "/snmp/v3-user/": "/snmp/v3-user",
    "/snmp/": "/snmp",
    "/vxlan-vnis/": "/vxlan-vnis/vni",
    "/vxlan-vnis/vni": "/vxlan_vnis",
}

#: The walkable paths that belong to no record.
_TOP_LEVEL = frozenset({
    "/anycast-gateway-mac", f"{_I}/name", "/system/dns-server", "/system/domain",
    "/system/hostname", "/system/ntp-server", "/system/syslog-server", "/system/timezone",
})

#: (codec, path) -> why the path is written though a record it belongs
#: to is declared unsupported.
OWNER_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("aruba_aoss", f"{_I}/config/vrf"): (
        "AOS-S has no VRF, and writes a management port that lands on `oobm` in "
        "the out-of-band context, which keeps it apart as its management VRF "
        "did (declared lossy)."
    ),
}


def _owner(path: str) -> str | None:
    if path in OWNER:
        found = OWNER[path]
    else:
        prefixes = [k for k in OWNER if k.endswith("/") and path.startswith(k)]
        if not prefixes:
            return None
        found = OWNER[max(prefixes, key=len)]
    return found if found != path else None


def _chain(path: str) -> list[str]:
    out, record = [], _owner(path)
    while record:
        out.append(record)
        record = _owner(record)
    return out


def _fields_of_records_not_written(classify: Callable[[str], str], unsupported: set[str]) -> list[tuple[str, str]]:
    """(path, record) for every walkable path *classify* does not call
    unsupported whose chain holds a record in *unsupported*."""
    found = []
    for path in sorted(_WALKABLE):
        if classify(path) == "unsupported":
            continue
        dead = next((r for r in _chain(path) if r in unsupported), None)
        if dead:
            found.append((path, dead))
    return found


def test_every_walkable_path_belongs_to_a_record_or_is_top_level() -> None:
    assert {p for p in _WALKABLE if not _chain(p)} == set(_TOP_LEVEL)


@pytest.mark.parametrize("target", _CODECS)
def test_a_field_of_a_record_not_written_is_not_supported(target: str) -> None:
    caps = get_codec(target).capabilities
    found = [
        (path, record)
        for path, record in _fields_of_records_not_written(caps.classify, {u.path for u in caps.unsupported})
        if (target, path) not in OWNER_EXCEPTIONS
    ]
    assert found == [], (
        f"{target} declares these records unsupported and the paths that belong "
        f"to them not: {found}"
    )


@pytest.mark.parametrize("exception", sorted(OWNER_EXCEPTIONS))
def test_each_owner_exception_is_still_one(exception: tuple[str, str]) -> None:
    target, path = exception
    caps = get_codec(target).capabilities
    assert caps.classify(path) != "unsupported"
    assert any(r in {u.path for u in caps.unsupported} for r in _chain(path))


def test_the_owner_rule_sees_a_field_of_a_record_not_written() -> None:
    found = _fields_of_records_not_written(
        lambda p: "unsupported" if p == "/dhcp-servers/pool" else "supported", {"/dhcp-servers/pool"},
    )
    assert {path for path, _ in found} == {p for p in _WALKABLE if p.startswith("/dhcp-servers/pool/")}
    assert {record for _, record in found} == {"/dhcp-servers/pool"}
