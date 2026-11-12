"""
``ArubaAOSSCodec`` — 4th real codec, Session C of vendor-config-research.

See package ``__init__`` for scope and structural-quirks notes.

Module layout (post-split per the codecs/README.md split-codec
convention):

* ``codec.py`` (this file) — the ``ArubaAOSSCodec`` class with
  metadata (capabilities / classvars / probe / iter_xpaths /
  port-name delegates).  ``parse()`` and ``render()`` are two-line
  delegators to the corresponding functions in the sibling modules.
* ``parse.py`` — line-walker + per-stanza dispatchers that consume
  AOS-S ``show running-config`` text and produce :class:`CanonicalIntent`.
* ``render.py`` — canonical tree to AOS-S CLI text.
* ``port_names.py`` — cross-vendor port-name identity bridge
  (shared with the rename-modal orchestrator).
* ``_svi_absorption.py`` — single source of truth for the
  ``absorbs_svi_into_vlan`` capability flag.

Test-import symbols (``_format_port_list``, ``_parse_port_list``)
are re-exported here so ``tests/unit/migration/test_aruba_aoss.py``
doesn't need updating for the split.  Their canonical homes are
:mod:`.parse` and :mod:`.render`; this module's re-exports are
purely for backwards compatibility.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ..._bonds import active_backup_warnings
from ...canonical.intent import CanonicalIntent
from .._input_shape import detect_input_shape
from ..base import CodecBase
from ..registry import register
from . import port_names as _port_names
from ._svi_absorption import ABSORBS_SVI_INTO_VLAN
from .accounts import account_warnings
from .parse import _parse_port_list, parse_intent, without_banner_bodies
from .render import (
    _format_port_list,
    loopback_warnings,
    pool_warnings,
    render_intent,
    vlan_interface_warnings,
)

# Re-export the internal helpers that tests pin against the codec's
# structural contract (see module docstring).
__all__ = [
    "ArubaAOSSCodec",
    "_format_port_list",
    "_parse_port_list",
]


#: Every walkable path this codec writes nothing for -- a record it has
#: no form for, or a field of a record declared unsupported -- by the
#: reason.  ``CapabilityMatrix.classify`` is an exact-string match and an
#: undeclared path is ``supported``, so a record declared unsupported
#: left each field under it reported as translated.  Spread into
#: ``_CAPS.unsupported``; ``tests/unit/migration/
#: test_a_supported_path_is_written.py`` holds the matrix to the render.
_NOT_RENDERED: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "No tunnel is written (`/interfaces/interface/tunnel-type` is "
        "unsupported), so neither is either end of one: its source and "
        "its destination.",
        (
            "/interfaces/interface/tunnel-source-address",
            "/interfaces/interface/tunnel-source-interface",
            "/interfaces/interface/tunnel-destination",
        ),
    ),
    (
        "No IPv4 virtual gateway is written "
        "(`ipv4/address/virtual-gateway-address` is unsupported), so "
        "neither is the MAC that goes with one.",
        ("/interfaces/interface/ipv4/address/virtual-gateway-mac",),
    ),
    (
        "No IPv6 virtual gateway is written "
        "(`ipv6/address/virtual-gateway-address` is unsupported), so "
        "neither is the MAC that goes with one.",
        ("/interfaces/interface/ipv6/address/virtual-gateway-mac",),
    ),
    (
        "No VRF is written (`/routing-instances/instance` is unsupported), "
        "so no field of one is: its name, description, route "
        "distinguisher, route targets and L3 VNI go with it.",
        (
            "/routing-instances/instance/name",
            "/routing-instances/instance/description",
            "/routing-instances/instance/route-distinguisher",
            "/routing-instances/instance/rt-imports",
            "/routing-instances/instance/rt-exports",
            "/routing-instances/instance/l3-vni",
        ),
    ),
    (
        "No VXLAN VNI is written (`/vxlan-vnis/vni` is unsupported), so "
        "neither is its VLAN, its multicast group or its flood list.",
        (
            "/vxlan-vnis/vlan-id",
            "/vxlan-vnis/mcast-group",
            "/vxlan-vnis/flood-list",
        ),
    ),
    (
        "No EVPN Type-5 route is written: the codec has no form for one.",
        ("/evpn-type5-routes/route",),
    ),
)


#: Every walkable path this codec writes only in some cases, or a record
#: it writes without the field, by the reason.  Spread into
#: ``_CAPS.lossy`` (severity ``warn``: the job says so and stays
#: ``completed``); ``tests/unit/migration/
#: test_a_supported_path_is_written.py`` holds the matrix to the render.
_DROPPED: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "AOS-S has no sub-interface (`/interfaces/interface/dot1q-vlan`): "
        "a port's own address is written on the port, and its "
        "sub-interfaces as VLANs of the switch, so that nothing is beside "
        "it.",
        ("/interfaces/interface/address-beside-sub-interfaces",),
    ),
    (
        "AOS-S spells a DHCP client `ip address dhcp-bootp` in a VLAN, "
        "which this codec neither reads nor writes: the interface is "
        "written without a DHCP client.",
        ("/interfaces/interface/dhcp-client",),
    ),
    (
        "AOS-S sets the frame size of a VLAN (`jumbo`) or of the whole "
        "switch, not of a port: an interface's MTU is not written.",
        ("/interfaces/interface/config/mtu",),
    ),
    (
        "AOS-S has no VRF.  A management port that lands on `oobm` is "
        "written in the out-of-band context, which HPE documents as a "
        "management plane apart from the data plane, so the port stays "
        "apart as its management VRF kept it; any other interface is "
        "written without its VRF.",
        ("/interfaces/interface/config/vrf",),
    ),
    (
        "AOS-S writes IETF VRRP only, and only in a VLAN: a group of "
        "another protocol (HSRP, CARP) is not written, and a `; review:` "
        "line in the VLAN says so; a group on an interface that is not a "
        "VLAN's is not written, and nothing says so.",
        ("/interfaces/interface/vrrp-groups/group",),
    ),
    (
        "The codec writes no tracked interface for a VRRP group: the "
        "interfaces it tracks are dropped.",
        ("/interfaces/interface/vrrp-groups/group/track-interfaces",),
    ),
    (
        "The codec writes no virtual MAC for a VRRP group: a MAC the source "
        "set is dropped, and the group uses its platform's own.",
        ("/interfaces/interface/vrrp-groups/group/virtual-mac",),
    ),
)


@register
class ArubaAOSSCodec(CodecBase):
    """Codec for Aruba AOS-S ``show running-config`` text.

    Declares ``device_classes=[switch, router]`` — AOS-S ships
    primarily as L2 access switches but L3 features (routed ports,
    static routes) are in scope here.
    """

    name: ClassVar[str] = "aruba_aoss"
    version_hint: ClassVar[str | None] = "16.x"
    input_format: ClassVar[str] = "cli-aruba-aoss"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    #: AOS-S absorbs the SVI's L3 state into the VLAN stanza itself.
    #: Full explanation + list of participating code paths lives in
    #: :mod:`._svi_absorption`; the value is imported from there so
    #: the rule has a single source of truth.
    absorbs_svi_into_vlan: ClassVar[bool] = ABSORBS_SVI_INTO_VLAN
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from an Aruba AOS-S "
        "(ProCurve / ArubaOS-Switch 16.x) device.  NOT the same as "
        "AOS-CX — CX uses a different codec."
    )
    sample_input: ClassVar[str] = (
        '; J9729A Configuration Editor; Created on release #WC.16.11\n'
        'hostname "sw-edge-01"\n'
        'snmp-server community "public" Operator\n'
        'vlan 1\n'
        '   name "DEFAULT_VLAN"\n'
        '   untagged 1-24\n'
        '   no ip address\n'
        '   exit\n'
        'vlan 10\n'
        '   name "USERS"\n'
        '   untagged 1-24\n'
        '   tagged 25-26\n'
        '   ip address 192.168.10.1/24\n'
        '   exit\n'
        'interface 1\n'
        '   name "Desk 1"\n'
        '   enable\n'
        '   exit\n'
        'ip default-gateway 192.168.10.254\n'
    )
    output_extension: ClassVar[str] = "cfg"

    #: AOS-S prints one port in either case (``trk1`` beside ``Trk1``,
    #: ``1/a1`` for ``1/A1``).
    #: See ``CodecBase.port_names_case_sensitive``.
    port_names_case_sensitive: ClassVar[bool] = False

    #: See ``CodecBase.vlans_have_only_a_name``.
    vlans_have_only_a_name: ClassVar[bool] = True

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="aruba_aoss",
        vendor_id="aruba_aoss",
        version_range="16.x",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
            # SVI / management L3 on the VLAN record itself — AOS-S models the
            # SVI as a property of the VLAN (no sibling interface) and renders
            # it straight off this surface, so it round-trips (unlike the
            # router/firewall codecs that drop it; blind-audit 3ec11f3 T0-2).
            "/vlans/vlan/ipv4/address/ip",
            # Per-interface switchport view — AOS-S models L2 membership
            # VLAN-centrically (``vlan N / tagged|untagged <ports>``), but
            # parse populates the transposed per-interface switchport_mode /
            # access_vlan / trunk_* fields too (kept in sync via the VLAN
            # projection), and the membership round-trips.  Declared
            # ``supported`` so the canonical walker's switchport xpaths
            # classify correctly.
            "/interfaces/interface/switchport-mode",
            "/interfaces/interface/access-vlan",
            "/interfaces/interface/trunk-allowed-vlans",
            "/interfaces/interface/trunk-native-vlan",
            "/routing/static-route",
            "/routing/static-route/gateway",      # audit e5b77d7 — next-hop round-trips
            # ``distance <N>`` on every route form the render writes,
            # read back by the parser (AOS-Switch takes 1 to 255,
            # default 1: Aruba Central, "Configuring Routing").
            "/routing/static-route/metric",
            # The switch's own DHCP server: a ``dhcp-server pool`` stanza
            # for each pool, ``dhcp-server`` in the VLAN that serves it,
            # ``dhcp-server enable`` last (:mod:`.dhcp_pools`).  What AOS-S
            # cannot be given as the tree has it is a review line and a
            # warning of the job.
            "/dhcp-servers/pool",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            # Wave B (v0.2.0) — classic VRRP wire-up.  AOS-S nests
            # ``ip vrrp vrid N`` inside ``vlan N`` stanzas; canonical
            # attaches the group to the synthesised Vlan<N>
            # CanonicalInterface (see _svi_absorption.py).  Anycast
            # / HSRP / CARP paths remain unsupported below — AOS-S
            # has no native grammar for those.
            # /interfaces/interface/vrrp-groups/group: written only in some cases, see _DROPPED.
        ],
        lossy=[
            LossyPath(
                path="/local-users/user/role",
                reason=(
                    "A local user's role is a name of the platform that defines"
                    " it.  AOS-S has two accounts, `manager` and `operator`, "
                    "and chooses between them by the privilege level (15 is "
                    "`manager`) from any source; a role the source names is not"
                    " carried."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/local-users/user/privilege-level",
                reason=(
                    "AOS-S has two accounts, one manager and one operator, "
                    "and no numeric privilege: privilege 15 is the manager "
                    "account and any other level the operator account.  Of "
                    "several users of one role the first AOS-S can take is "
                    "written and each other is a `review:` comment (a second "
                    "`password <role>` line would replace the first); an "
                    "operator account is written only beside a manager "
                    "account, since an operator password alone gives manager "
                    "access (HPE Access Security Guide, AOS-S 16.x)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/lags/lag/mode",
                reason=(
                    "AOS-S trunk LACP does not preserve the active/passive "
                    "distinction on re-parse; a `passive` bundle re-parses as "
                    "`active` (audit bb47f21 T0-1, verified by round-trip "
                    "probe)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/mode",
                reason=(
                    "AOS-S renders only IETF VRRP; a cross-family source mode "
                    "(HSRP / CARP) is not written (see /interfaces/interface/"
                    "vrrp-groups/group) -- the redundancy has to be "
                    "made again on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/advertisement-interval",
                reason=(
                    "AOS-S VRRP has no per-group advertisement-interval stanza; "
                    "the group renders but the election timer is dropped (the "
                    "target falls back to its 1s default)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/authentication",
                reason=(
                    "AOS-S VRRP renders only the plaintext-password auth "
                    "scheme; an md5 / carp-key source scheme surfaces a review "
                    "comment rather than the secret."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-ipv6s",
                reason=(
                    "AOS-S VRRP has only an IPv4 virtual-ip-address grammar; "
                    "IPv6 virtual addresses (VRRPv3) are dropped on render."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/description",
                reason=(
                    "AOS-S VRRP stanzas carry no description / name field; the "
                    "group renders but the operator description is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/secondary-ip",
                reason=(
                    "VLAN-SVI mount: AOS-S renders the SVI L3 from the VLAN "
                    "record as co-equal `ip address X/N` lines (no secondary-IP "
                    "grammar), so the is_secondary flag drops while the address "
                    "value round-trips. Declared lossy "
                    "(blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/description",
                reason=(
                    "Render emits the VLAN name but not a separate "
                    "description line.  Where the VLAN's name is only the "
                    "name of an interface of the config, or empty, its "
                    "description is written as its name (_vlan_labels: an "
                    "OPNsense <descr>, a RouterOS comment, a FortiOS "
                    "alias); any other "
                    "description drops on render (silent-loss guard, "
                    "Bucket-C stage 2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/auth-passphrase",
                reason=(
                    "`snmpv3 user \"<n>\" auth <proto> \"<value>\"` takes the "
                    "operator's passphrase and AOS-S derives the localised USM "
                    "key from it, so a value that is already another agent's "
                    "key cannot be re-derived: the render refuses it (review "
                    "comment, no `snmpv3 user` line, and the `snmpv3 group` "
                    "binding drops with it) rather than deriving a key from a "
                    "key.  A source passphrase is portable and is emitted "
                    "unchanged."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/priv-passphrase",
                reason=(
                    "Same as the auth key: the privacy value is refused with "
                    "the user unless it is a portable passphrase or came from "
                    "AOS-S itself -- re-key the v3 user on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/engine-id",
                reason=(
                    "The SNMPv3 USM user round-trips but a per-user "
                    "engineID is not emitted on render (engineIDs are "
                    "device-assigned / global), so the canonical engine_id "
                    "drops (silent-loss guard, Bucket-C stage 2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/auth-protocol",
                reason=(
                    "AOS-S emits the auth protocol verbatim but its parser "
                    "accepts only md5 / sha / sha256; sha224 / sha384 / sha512 "
                    "render an unreadable clause that drops the auth config on "
                    "re-parse.  Declared lossy so the loss is not reported as "
                    "severity:ok (#23)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/priv-protocol",
                reason=(
                    "AOS-S privacy emits aes128 as bare `aes`, losing the "
                    "key-length designation, and has no representation for "
                    "aes192 / aes256; the privacy config round-trips lossily. "
                    "Declared lossy so validate_against surfaces it (#23)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing/static-route/description",
                reason=(
                    "Render emits destination, next hop and distance only; "
                    "the static-route name / description is dropped (run3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing/static-route/interface",
                reason=(
                    "AOS-S takes an address, a VLAN (``vlan <id>``) or the "
                    "discard (``blackhole``, written for ``Null0``) as a "
                    "next hop and nothing else.  A route out any other "
                    "interface -- a routed port, a LAG, a tunnel -- is "
                    "left out under a ``; review:`` line, and an interface "
                    "named beside a gateway is not written.  Error-level: "
                    "the job is partial for any route that names an "
                    "interface, the ones written as ``vlan`` or "
                    "``blackhole`` included, since the matrix cannot tell "
                    "them apart."
                ),
                severity="error",
            ),
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "AOS-S does not declare IANA ifType; the codec "
                    "infers type from interface-name shape (bare "
                    "number -> ethernet, 'Trk' -> port-channel, "
                    "'Vlan' -> l3ipvlan, 'loopback<N>' -> "
                    "softwareLoopback)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/dhcp-client-v6",
                reason=(
                    "AOS-S has no native IPv6 DHCPv6 / SLAAC client "
                    "configuration on routed interfaces — the canonical "
                    "dhcp_client_v6 field drops on render to AOS-S."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/tunnel-type",
                reason=(
                    "AOS-S is a campus L2/L3 codec with no GRE / IPIP "
                    "tunnel grammar; tunnel_type is not surfaced on "
                    "render."
                ),
                severity="warn",
            ),
            # Wave B (v0.2.0) — VRRP virtual_ips lossy.  AOS-S
            # ``virtual-ip-address`` accepts ONE address per vrid;
            # cross-vendor migration FROM Cisco IOS-XE or Junos
            # sources with multi-IP groups drops secondary virtuals
            # with a review comment.  See render.py inside the VRRP
            # emission block for the per-group comment form.
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-ips",
                reason=(
                    "AOS-S 'virtual-ip-address' accepts only ONE "
                    "address per vrid; cross-vendor migration from "
                    "Cisco IOS-XE secondaries or Junos virtual-"
                    "address lists drops the tail with a review "
                    "comment."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/dot1q-vlan",
                reason=(
                    "AOS-S routes on a VLAN and has no form for a routed "
                    "sub-interface (Cisco `encapsulation dot1Q N`, Junos "
                    "`unit N vlan-id`, a FortiOS or RouterOS VLAN interface "
                    "on a port).  One is written as VLAN <tag>, tagged on its "
                    "port, with its addresses -- and a VLAN of AOS-S is the "
                    "switch's, not the port's.  It is refused under a "
                    "`; review:` line where it has two tags, takes its port's "
                    "untagged frames, is disabled, carries VLAN 1, carries a "
                    "VLAN the config also has as a network of its own or as "
                    "another sub-interface, or rides on no port; one in a VRF "
                    "is written without it, as every interface is.  Its name "
                    "and description are not written.  "
                    "Error-level: the job is partial for any sub-interface, "
                    "the ones written as a VLAN included, since the matrix "
                    "cannot tell them apart."
                ),
                severity="error",
            ),
            # -- Paths written only in some cases (see _DROPPED). --
            *(
                LossyPath(path=path, reason=reason, severity="warn")
                for reason, paths in _DROPPED
                for path in paths
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/config/ip-mtu",
                reason=(
                    "AOS-S has no per-interface MTU of any kind: its IP MTU is "
                    "the global `jumbo ip-mtu`. An interface's IP MTU (IOS-XE "
                    "or AOS-CX `ip mtu`, IOS XR `ipv4 mtu`, Junos `family inet "
                    "mtu`) is not in the output."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/config/ip-mtu-beside-mtu",
                reason=(
                    "AOS-S has no per-interface MTU of any kind: its IP MTU is "
                    "the global `jumbo ip-mtu`. An interface's IP MTU (IOS-XE "
                    "or AOS-CX `ip mtu`, IOS XR `ipv4 mtu`, Junos `family inet "
                    "mtu`) is not in the output."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/dot1q-native",
                reason=(
                    "Which routed sub-interface takes the untagged frames of "
                    "its port (IOS-XE `encapsulation dot1Q N native`, Junos "
                    "`native-vlan-id N` with the unit of that `vlan-id`): "
                    "AOS-S writes a routed sub-interface as a VLAN tagged on "
                    "its port (see `/interfaces/interface/dot1q-vlan`), and "
                    "has no form for one that also takes the port's untagged "
                    "frames.  Such a sub-interface is left out under a "
                    "`; review:` line."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/dot1q-inner-vlan",
                reason=(
                    "The inner 802.1Q tag of a Q-in-Q sub-interface (Cisco "
                    "`encapsulation dot1Q N second-dot1q M`, Junos `vlan-tags "
                    "outer N inner M`) has no form on AOS-S, whose VLAN is "
                    "one tag.  Such a sub-interface is left out under a "
                    "`; review:` line."
                ),
            ),
            UnsupportedPath(
                path="/routing-instances/instance/instance-type",
                reason=(
                    "AOS-S renders no VRF / routing-instance (see "
                    "/routing-instances/instance), so the mac-vrf vs vrf "
                    "instance-type discriminator is dropped (audit e5b77d7, PR-2c)."
                ),
            ),
            UnsupportedPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-address",
                reason=(
                    "VLAN-SVI mount: AOS-S is a campus L2/L3 codec with no "
                    "anycast-gateway / VARP grammar (cf. the interface-mount "
                    "twin + system-wide /anycast-gateway-mac, both "
                    "unsupported), so an anycast virtual-gateway IP on a VLAN "
                    "SVI cannot be modelled at all. Declared unsupported "
                    "(blind-audit f92e97a T0-2)."
                ),
            ),
            UnsupportedPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-mac",
                reason=(
                    "VLAN-SVI mount: AOS-S has no anycast-gateway MAC grammar "
                    "(see the unsupported /anycast-gateway-mac), so a per-"
                    "address virtual-gateway MAC on a VLAN SVI is dropped. "
                    "Declared unsupported (blind-audit f92e97a T0-2)."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/voice-vlan",
                reason=(
                    "AOS-S models voice via LLDP-MED device profiles, not a "
                    "per-port voice-VLAN binding; this codec drops it on "
                    "render (blind-audit 65f9c01 #11)."
                ),
            ),
            # ── Tier-1/2 surfaces this codec drops on render — declared so the
            #    live validation report flags the loss instead of reporting
            #    `severity: ok` (2026-06 adversarial review #9). ──
            UnsupportedPath(
                path="/system/domain",
                reason="Render emits no system domain-name; intent.domain is dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/timezone",
                reason="Render emits no clock/timezone stanza; intent.timezone is dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/syslog-server",
                reason="Render emits no logging/syslog config; intent.syslog_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/routing-instances/instance",
                reason="Render emits no VRF/routing-instance construct; "
                "intent.routing_instances are dropped on migration.",
            ),
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "AOS-S access-lists are Tier 3 (informational) "
                    "and not yet auto-rendered."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason="VXLAN not modelled — AOS-S is a campus L2/L3 codec.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason="VXLAN not modelled (see /vxlan-vnis/vni).",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/udp-port",
                reason="VXLAN not modelled (see /vxlan-vnis/vni).",
            ),
            # -- Ship-before-wire (v0.2.0) -- anycast / per-VRF static routes --
            # VRRP itself moved to ``supported`` above when Wave B
            # wire-up landed.  Anycast / virtual-gateway-address
            # paths remain unsupported because AOS-S is a campus
            # L2/L3 codec with no anycast-gateway grammar.
            UnsupportedPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-address",
                reason=(
                    "Anycast-gateway virtual IPv4 companion parses-and-"
                    "ignores in v1.  Schema exists on "
                    "CanonicalIPv4Address; wire-up scheduled for v0.2.0 "
                    "Wave C (see docs/v0.2.0-planning/02-anycast-gateway/)."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason=(
                    "IPv6 anycast-gateway virtual IP companion parses-"
                    "and-ignores in v1.  Schema exists on "
                    "CanonicalIPv6Address; wire-up scheduled for v0.2.0 "
                    "Wave C."
                ),
            ),
            UnsupportedPath(
                path="/anycast-gateway-mac",
                reason=(
                    "System-wide anycast-gateway MAC parses-and-ignores "
                    "in v1.  Schema exists on CanonicalIntent; wire-up "
                    "scheduled for v0.2.0 Wave C."
                ),
            ),
            UnsupportedPath(
                path="/routing/static-route/vrf",
                reason=(
                    "AOS-S has no VRF (HPE's routing guide names none): "
                    "a route in a VRF is left out under a ``; review:`` "
                    "line.  It was written into the switch's one table, "
                    "where it routed traffic the source routed in "
                    "another."
                ),
            ),
            # -- Paths this codec writes nothing for (see _NOT_RENDERED). --
            *(
                UnsupportedPath(path=path, reason=reason)
                for reason, paths in _NOT_RENDERED
                for path in paths
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse / Render — delegate to sibling modules
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        from ..._tier3_detection import detect_tier3_sections_aoss

        intent = parse_intent(raw)
        # Aruba AOS-S uses Cisco-derived ACL grammar (`access-list extended`,
        # `policy-map`, etc.), so the IOS-XE CLI detector's patterns, and
        # its own contexts (`stacking`, `vsf`, `oobm`).  Notification-only.
        # The parser's own rows (a port's VLAN line that names a VLAN no
        # stanza declares) follow.  Read from the text the parser read:
        # a banner's lines are text, not stanzas.
        intent.dropped_tier3_sections = [
            *detect_tier3_sections_aoss(without_banner_bodies(raw)),
            *intent.dropped_tier3_sections,
        ]
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    def render_warnings(self, tree: Any) -> list[str]:
        """A warning for each local user AOS-S is not given for a reason
        of its own: it holds one manager and one operator account
        (:mod:`.accounts`); and one for each review line of the output's
        DHCP server: a pool not written, a range or a lease written
        otherwise than the source states it, an option AOS-S is not
        given, a pool no VLAN of the output serves
        (:mod:`.dhcp_pools`); and one for each sub-interface written as
        the VLAN of its tag and each interface that stands for a VLAN
        and is left out under a review line (:mod:`.vlan_interfaces`);
        and one for each loopback refused because the tree holds it
        down, and each loopback address written as a host address it
        was not, since an AOS-S loopback takes no mask; and one for
        each active-backup LAG, written as a static ``trunk``
        (:mod:`netcanon.migration._bonds`)."""
        return [
            *account_warnings(getattr(tree, "local_users", None) or []),
            *pool_warnings(tree),
            *vlan_interface_warnings(tree),
            *loopback_warnings(tree),
            *active_backup_warnings(getattr(tree, "lags", None) or []),
        ]

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` — these methods
    # delegate so the codec class stays focused on parse/render while
    # the pure port-name translation primitives remain importable
    # independently by the orchestrator.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect AOS-S running-config by its unique structural cues.

        Key discriminators vs. Cisco IOS CLI:
          * ``;`` banner comment (IOS uses ``!``)
          * ``interface <N>`` with a bare number, no ``Ethernet``/``Gig`` prefix
          * ``vlan <N>`` ... ``untagged <range>`` inside the stanza
          * ``routing`` keyword on a port (not ``no switchport``)
        """
        # XML / JSON shape — shared helper tolerates leading shell-echo
        # / banner framing so real captures don't bypass the guard.
        if detect_input_shape(raw_prefix) is not None:
            return None

        # Unique banner.  Three observed shapes:
        #   ``; J9850A Configuration Editor`` — older J-prefix part
        #     numbers (J9729A, J9850A, etc.)
        #   ``; JL260A Configuration Editor`` — newer JL-prefix part
        #     numbers (JL256A, JL260A — both 2930F)
        #   ``; hpStack_WC Configuration Editor`` — stacking banner
        #     (any stacked or VSF-enabled unit, including a one-member
        #     stack)
        # All three are unambiguously Aruba/HPE.  Match anywhere in
        # the input (not just first line) because operators sometimes
        # include the prompt-echo + ``show running-config`` command
        # before the actual config — the banner shows up a few lines
        # in.
        if re.search(
            r"^;\s*(J[A-Z]?\d+[A-Z]*|hpStack_\w+)\s+Configuration",
            raw_prefix, re.MULTILINE,
        ):
            return (98, "AOS-S ProCurve / Aruba configuration banner present")

        # Structural: vlan stanzas with inline untagged/tagged.
        has_vlan_with_untagged = bool(re.search(
            r"^vlan\s+\d+[\s\S]{0,400}?^\s+untagged\s+\d",
            raw_prefix, re.MULTILINE,
        ))
        has_iface_bare_num = bool(re.search(
            r"^interface\s+[A-Z]?\d+(/\d+)?\s*$",
            raw_prefix, re.MULTILINE,
        ))
        has_routing_keyword = bool(re.search(
            r"^[^\S\n]+routing\s*$", raw_prefix, re.MULTILINE,
        ))
        has_aos_comment = bool(re.search(
            r"^;", raw_prefix, re.MULTILINE,
        ))

        strong_hits = sum((
            has_vlan_with_untagged,
            has_iface_bare_num,
            has_routing_keyword,
        ))
        if strong_hits >= 2 and has_aos_comment:
            return (95, f"{strong_hits} AOS-S structural markers + ';' comment")
        if strong_hits >= 2:
            return (88, f"{strong_hits} AOS-S structural markers present")
        if has_vlan_with_untagged:
            return (78, "VLAN stanza with inline 'untagged' port list")
        if has_iface_bare_num and has_aos_comment:
            return (70, "'interface <N>' shape + ';' comment prefix")
        return None
