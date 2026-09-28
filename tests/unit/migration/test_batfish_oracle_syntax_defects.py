"""Target-syntax defects surfaced by the Batfish independent-parser oracle.

Batfish is the only *independent* parser in the test estate — it covers 5 of
the 13 codecs and reads netcanon's rendered output the way a device would,
rather than the way netcanon's own parser does.  The cross-mesh fidelity
harness cannot see this class at all: it scores round-trip *preservation*, so
a render that preserves every canonical field while emitting a line the target
platform rejects is scored ALIGNED.

Full workings in ``docs/reviews/2026-09-22-api-full-mesh/13-batfish-validity.md``
(ranked list in §6).  Two of that list's items are pinned here; the higher-
ranked ones landed earlier (#1 RADIUS secrets, #2 the ``auto`` keyword).

⚠️ Items #3 and #5 of that list are deliberately NOT pinned here: they are
artifacts of the bare mesh path, which skips ``translate_port_names`` by
design.  §3.3 of the report establishes they are absent on the ``/plan`` path.
Do not "fix" them from a bare-render reproduction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "real"

#: Every target whose grammar requires a community (or v3 user) as the
#: trailing argument of a trap-host line.  ``dell_os10`` is in this list
#: even though Batfish does not parse OS10 — it has the same defect and was
#: found by reading the render paths, not by the oracle.
_TRAP_HOST_TARGETS = (
    "arista_eos",
    "cisco_iosxe_cli",
    "cisco_nxos",
    "dell_os10",
)

#: A bare ``snmp-server host <ip>`` with nothing after the address.
_BARE_TRAP_HOST = re.compile(r"^snmp-server\s+host\s+\S+\s*$")


def _tree(community: str) -> CanonicalIntent:
    return CanonicalIntent(
        source_vendor="cisco_nxos",
        hostname="sw1",
        snmp=CanonicalSNMP(
            community=community,
            trap_hosts=["10.1.1.1", "10.1.1.2"],
        ),
    )


class TestTrapHostNeedsACommunity:
    """Oracle item #4 — ``snmp-server host <ip>`` with no community string.

    Two defects in one line.  It is invalid on IOS-XE / EOS / NX-OS / OS10,
    where the community (or v3 user) is a required trailing argument — and it
    silently discarded ``tree.snmp.community``, which the source had
    populated ('secure', 'dummycommunity', 'xxxx' on real captures).

    Measured before the fix: 16 cells across the four targets emitted the
    bare form.  ``aruba_aoss`` and ``fortigate_cli`` already did this
    correctly, including the ``or "public"`` fallback this reuses.
    """

    @pytest.mark.parametrize("target", _TRAP_HOST_TARGETS)
    def test_the_community_is_emitted(self, target: str) -> None:
        out = get_codec(target).render(_tree("secure"))
        hosts = [
            ln.strip()
            for ln in out.splitlines()
            if ln.strip().startswith("snmp-server host ")
        ]
        assert hosts, f"{target}: no trap-host line emitted at all"
        for line in hosts:
            assert "secure" in line, (
                f"{target}: trap host dropped the populated community: "
                f"{line!r}"
            )

    @pytest.mark.parametrize("target", _TRAP_HOST_TARGETS)
    def test_no_bare_trap_host_line_survives(self, target: str) -> None:
        """The invalid form must not appear, with or without a community."""
        for community in ("secure", ""):
            out = get_codec(target).render(_tree(community))
            bare = [
                ln.strip()
                for ln in out.splitlines()
                if _BARE_TRAP_HOST.match(ln.strip())
            ]
            assert not bare, f"{target} (community={community!r}): {bare}"

    @pytest.mark.parametrize("target", _TRAP_HOST_TARGETS)
    def test_a_synthesised_community_is_disclosed(self, target: str) -> None:
        """Falling back to ``public`` keeps the trap target valid, but it is
        config the operator never wrote — so it must be said out loud.

        Dropping the host instead would stop their monitoring silently,
        which is the trade ``fortigate_cli``'s render comment already
        reasons through.
        """
        out = get_codec(target).render(_tree(""))
        assert "public" in out
        assert "review:" in out, (
            f"{target}: synthesised a community without disclosing it"
        )

    @pytest.mark.parametrize("target", _TRAP_HOST_TARGETS)
    def test_no_review_note_when_the_source_had_a_community(
        self, target: str,
    ) -> None:
        """A note that fires every time is noise, not signal."""
        out = get_codec(target).render(_tree("secure"))
        notes = [
            ln for ln in out.splitlines()
            if "review:" in ln and "snmp-server host" in ln
        ]
        assert not notes, f"{target}: spurious review note {notes}"

    @pytest.mark.parametrize("target", _TRAP_HOST_TARGETS)
    def test_the_host_still_round_trips(self, target: str) -> None:
        """#465's lesson: when a render starts emitting more of a line, the
        parser must still read it back in the same change.

        All four ``_SNMP_HOST_RE`` patterns capture only the address and
        ignore the tail, so no parser change was needed — but that is a
        property to pin, not to assume.
        """
        codec = get_codec(target)
        tree = _tree("secure")
        back = codec.parse(codec.render(tree))
        assert back.snmp is not None
        assert sorted(back.snmp.trap_hosts) == ["10.1.1.1", "10.1.1.2"], (
            f"{target}: trap hosts lost on re-parse: {back.snmp.trap_hosts}"
        )


class TestFortiGateUnsetAddressSentinel:
    """Oracle item #6 — ``set ip 0.0.0.0 0.0.0.0`` is "no address".

    It is the default an unconfigured FortiOS interface carries.  Parsing it
    as a real address produced ``ip address 0.0.0.0/0`` on 18 interfaces of
    one capture, in every target render — rejected outright by EOS / NX-OS /
    IOS-XE and meaningless on IOS-XR and Junos.
    """

    _FIXTURE = _CORPUS / "fortigate" / "user_contrib_fg100e_fos7213.conf"

    def test_the_sentinel_is_not_parsed_as_an_address(self) -> None:
        codec = get_codec("fortigate_cli")
        raw = "\n".join([
            "config system interface",
            '    edit "port1"',
            "        set ip 0.0.0.0 0.0.0.0",
            "    next",
            '    edit "port2"',
            "        set ip 10.0.0.1 255.255.255.0",
            "    next",
            "end",
            "",
        ])
        by_name = {i.name: i for i in codec.parse(raw).interfaces}
        assert by_name["port1"].ipv4_addresses == [], (
            "the FortiOS 'no address' sentinel was taken as a real address"
        )
        assert [a.ip for a in by_name["port2"].ipv4_addresses] == ["10.0.0.1"]

    def test_a_default_route_destination_is_untouched(self) -> None:
        """``0.0.0.0/0`` as a route DESTINATION is a real default route.

        The sentinel check is deliberately scoped to interface addresses; if
        it ever leaked into route parsing it would delete every default
        route, which is a far worse bug than the one it fixes.
        """
        codec = get_codec("fortigate_cli")
        raw = "\n".join([
            "config system interface",
            '    edit "port1"',
            "        set ip 0.0.0.0 0.0.0.0",
            "    next",
            "end",
            "config router static",
            "    edit 1",
            "        set dst 0.0.0.0 0.0.0.0",
            "        set gateway 10.0.0.254",
            '        set device "port1"',
            "    next",
            "end",
            "",
        ])
        intent = codec.parse(raw)
        assert not intent.interfaces[0].ipv4_addresses
        assert [r.destination for r in intent.static_routes] == ["0.0.0.0/0"]

    def test_the_real_capture_no_longer_carries_the_sentinel(self) -> None:
        if not self._FIXTURE.is_file():  # pragma: no cover
            pytest.skip("fortigate capture absent")
        intent = get_codec("fortigate_cli").parse(
            self._FIXTURE.read_text(encoding="utf-8", errors="replace")
        )
        offenders = [
            i.name
            for i in intent.interfaces
            for a in i.ipv4_addresses
            if a.ip == "0.0.0.0"
        ]
        assert not offenders, (
            f"{len(offenders)} interface(s) still parse the sentinel as an "
            f"address: {offenders[:8]}"
        )

    @pytest.mark.parametrize(
        "target", ["arista_eos", "cisco_nxos", "cisco_iosxe_cli"],
    )
    def test_no_target_emits_a_zero_interface_address(
        self, target: str,
    ) -> None:
        """The operator-visible property: the invalid line is gone."""
        if not self._FIXTURE.is_file():  # pragma: no cover
            pytest.skip("fortigate capture absent")
        intent = get_codec("fortigate_cli").parse(
            self._FIXTURE.read_text(encoding="utf-8", errors="replace")
        )
        out = get_codec(target).render(intent)
        bad = [
            ln.strip()
            for ln in out.splitlines()
            if re.search(r"(ip address|ipv4 address)\s+0\.0\.0\.0", ln)
        ]
        assert not bad, f"{target} still emits {bad[:4]}"
