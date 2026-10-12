"""What one request may make, and for how long (``netcanon.migration.limits``).

A few bytes of a config can stand for a great deal -- a range is
thousands of entries, ``all`` is 4,094, two honest counts multiply --
so the size of a text bounds neither the memory a request takes nor
its time.  The product counts what a request makes, at the places
where a few bytes become many entries, and refuses past a limit in a
sentence that names what was large, how large, and the limit.  One
deadline for the request is looked at in every parser's loop over the
lines of a config.

Four kinds of test, after what this project has learned more than
once -- a guard that walks the list it guards agrees with the list:

* **the mechanism**: counting, the deadline, the words of a refusal;
* **each limit, and the texts that were measured**: one text under a
  limit is translated as it is with no limit at all; one text over it
  is refused BEFORE what it asks for is made (the refusal says so, and
  the bytes held while it was reached are counted), in a sentence that
  names the kind;
* **completeness by experiment**: every codec's parse stops at a
  deadline it has passed; every line of every committed capture is
  walked by a loop that looks at the clock; a tree whose entries no
  expander counted is still held to the limits;
* **completeness by reading the code**: every loop over the lines of a
  config looks at the deadline; every place a module under ``codecs/``
  turns two numbers into a run of entries is in a table with its
  answer; no broad handler can turn a refusal into another error.

The refusal as each surface gives it -- the job, the HTTP answer, the
sanitiser, the command line, the pages -- is read in
``tests/integration/test_config_limits_api.py``, ``tests/unit/test_cli.py``,
``tests/desktop/`` and ``tests/e2e/test_config_limits_e2e.py``.
"""

from __future__ import annotations

import ast
import copy
import random
import threading
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from netcanon.migration import limits as L
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from netcanon.migration.canonical.transforms import project_switchport_to_vlan, project_vlan_to_switchport
from netcanon.migration.codecs._helpers import joined_ids_length
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import Refusal
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures"
PACKAGE = REPO / "netcanon"

#: Limits small enough that a few hundred bytes pass them.
TINY = replace(
    L.STANDARD, name="tiny", vlan_ids=5_000, memberships=2_000, ports=100,
    copies=500, words=2_000, text=50_000,
)
#: No limit on what is made, and a deadline nobody reaches.
UNCOUNTED = replace(L.UNLIMITED, name="uncounted", seconds=3600.0)


def _peak(work: Callable[[], object]) -> int:
    """The most bytes held at once while *work* ran."""
    tracemalloc.start()
    try:
        work()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _refused(codec: str, text: str, limits: L.Limits | str | None = None) -> L.LimitExceeded:
    with L.limits_scope(limits), pytest.raises(L.LimitExceeded) as caught:
        get_codec(codec).parse(text)
    return caught.value


def _plan(source: str, target: str, text: str, limits: L.Limits | str | None = None):
    with L.limits_scope(limits):
        return run_plan_with_overrides(get_codec(source), get_codec(target), text, port_rename_map={})


# ---------------------------------------------------------------------------
# Texts
# ---------------------------------------------------------------------------


def aoss_ranges(count: int, span: int = 1001) -> str:
    """One AOS-S line of *count* port ranges of *span* ports each."""
    ranges = ",".join(f"{1 + n * span}-{(n + 1) * span}" for n in range(count))
    return f'hostname "T"\nvlan 10\n   name "V10"\n   tagged {ranges}\n   exit\n'


def eos_trunks(count: int, allowed: str = "2-4000", declared: int = 10) -> str:
    """*count* Arista trunks that each allow *allowed*."""
    out = ["hostname T", "!"]
    for vid in range(10, 10 + declared):
        out += [f"vlan {vid}", f"   name V{vid}", "!"]
    for port in range(1, count + 1):
        out += [f"interface Ethernet{port}", "   switchport mode trunk",
                f"   switchport trunk allowed vlan {allowed}", "!"]
    return "\n".join(out) + "\nend\n"


def nxos_trunks(count: int, allowed: str, declared: int) -> str:
    """*count* NX-OS trunks that each allow *allowed*, and *declared* VLANs."""
    out = ["hostname T", ""]
    for vid in range(2, 2 + declared):
        out += [f"vlan {vid}", f"  name V{vid}"]
    for port in range(count):
        out += [f"interface Ethernet{port // 48 + 1}/{port % 48 + 1}", "  switchport",
                "  switchport mode trunk", f"  switchport trunk allowed vlan {allowed}"]
    return "\n".join(out) + "\n"


def iosxe_stanzas(count: int) -> str:
    """*count* interface stanzas of one line each: eighteen bytes an interface."""
    return "hostname T\n!\n" + "".join(f"interface Gi{n}\n" for n in range(count)) + "end\n"


def junos_one_unit(count: int) -> str:
    """*count* addresses on one Junos IRB unit."""
    return "set system host-name T\n" + "".join(
        f"set interfaces irb unit 100 family inet address "
        f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}/32\n" for n in range(1, count + 1)
    )


def junos_range(members: int, addresses: int) -> str:
    """A Junos interface-range of *members* with *addresses* on it."""
    return "set system host-name T\n" + "".join(
        f"set interfaces interface-range R member ge-0/0/{n}\n" for n in range(members)
    ) + "".join(
        f"set interfaces interface-range R unit 0 family inet address 10.{n >> 8}.{n & 255}.1/24\n"
        for n in range(1, addresses + 1)
    )


def junos_blocks(depth: int, leaves: int) -> str:
    """Block-form Junos: *leaves* statements under a path *depth* words long."""
    path = " ".join(f"w{n}" for n in range(depth))
    return "system {\n    host-name T;\n}\n" + path + " {\n" + "".join(
        f"    leaf{n} v{n};\n" for n in range(leaves)
    ) + "}\n"


def vyos_set_lines(count: int, depth: int) -> str:
    """*count* VyOS set lines, each *depth* words deep."""
    return "set system host-name T\n" + "".join(
        "set " + " ".join(f"a{n}x{level}" for level in range(depth)) + "\n" for n in range(count)
    )


# ---------------------------------------------------------------------------
# 1. The numbers
# ---------------------------------------------------------------------------


class TestTheNumbers:
    def test_the_four_sets_are_as_decided(self) -> None:
        """``docs/CAPABILITIES.md`` and ``SECURITY.md`` print these, and
        ``tests/unit/test_limits_docs_truth.py`` holds them to it.  A
        number changes here, in the module and in the documents, with
        the measurement that says why."""
        kinds = ("vlan_ids", "memberships", "ports", "interfaces", "copies", "words", "text", "seconds")
        assert {name: tuple(getattr(limits, kind) for kind in kinds) for name, limits in L.PROFILES.items()} == {
            "small": (1_048_576, 50_000, 2_048, 2_500, 10_000, 250_000, 8_000_000, 20.0),
            "standard": (16_777_216, 1_000_000, 8_192, 50_000, 100_000, 4_000_000, 64_000_000, 120.0),
            "large": (67_108_864, 4_000_000, 32_768, 200_000, 400_000, 16_000_000, 256_000_000, 600.0),
            "unlimited": (None,) * 8,
        }
        assert kinds == tuple(L.KINDS)

    def test_a_name_nobody_knows_is_not_no_limit(self) -> None:
        assert L.resolve("unlimitted") is L.STANDARD
        assert L.resolve(None) is L.STANDARD
        assert L.resolve("") is L.STANDARD
        assert L.resolve(" Large ") is L.LARGE
        assert L.resolve(TINY) is TINY

    def test_the_line_a_server_logs_names_every_limit(self) -> None:
        for limits in (L.SMALL, L.STANDARD, L.LARGE):
            said = L.describe(limits)
            assert said.startswith(limits.name + " (")
            for kind in L.KINDS:
                assert f"{kind} {int(getattr(limits, kind)):,}" in said
        assert "no config size limit" in L.describe(L.UNLIMITED)


# ---------------------------------------------------------------------------
# 2. Counting
# ---------------------------------------------------------------------------


class TestCounting:
    def test_a_charge_refuses_before_and_says_what(self) -> None:
        with L.limits_scope(TINY), L.metered("parse", "cisco_nxos"):
            L.charge("vlan_ids", 3_999, "2-4000")
            with pytest.raises(L.LimitExceeded) as caught:
                L.charge("vlan_ids", 3_999, "2-4001")
        exc = caught.value
        assert (exc.kind, exc.asked, exc.cap, exc.exact, exc.stage, exc.codec, exc.lists) == (
            "vlan_ids", 7_998, 5_000, False, "parse", "cisco_nxos", 2,
        )
        said = str(exc)
        assert said.startswith("reading the config as cisco_nxos would make 7,998 or more VLAN ids")
        assert "the limit is 5,000" in said
        assert "(counted over 2 lists and ranges; the last one read: 2-4001)" in said

    def test_a_count_of_something_made_is_exact(self) -> None:
        with L.limits_scope(TINY), L.metered("render", "juniper_junos") as meter:
            meter.settle("text", 50_000)
            with pytest.raises(L.LimitExceeded) as caught:
                meter.settle("text", 50_001)
        assert caught.value.exact is True
        assert str(caught.value).startswith(
            "writing the config for juniper_junos makes 50,001 characters of rendered config; the limit is 50,000."
        )

    def test_counts_per_stage_deadline_per_scope(self) -> None:
        with L.limits_scope(TINY):
            with L.metered("parse", "a") as first:
                L.charge("vlan_ids", 4_000)
            with L.metered("parse", "a") as second:
                L.charge("vlan_ids", 4_000)  # a second parse starts from nothing
            assert first is not second
            assert first.deadline == second.deadline  # ...on the same clock

    def test_an_inner_stage_counts_on_the_outer_one(self) -> None:
        with L.limits_scope(TINY), L.metered("parse", "outer") as outer:
            L.charge("vlan_ids", 3_000)
            with L.metered("render", "inner") as inner, pytest.raises(L.LimitExceeded) as caught:
                assert inner is outer
                L.charge("vlan_ids", 3_000)
        assert (caught.value.asked, caught.value.stage, caught.value.codec) == (6_000, "parse", "outer")

    def test_the_same_names_again_are_not_more_ports(self) -> None:
        with L.limits_scope(TINY), L.metered("parse", "aruba_aoss"):
            for _ in range(400):
                L.distinct("ports", [str(n) for n in range(1, 49)])
            with pytest.raises(L.LimitExceeded) as caught:
                L.distinct("ports", [str(n) for n in range(100, 200)])
        assert (caught.value.kind, caught.value.asked) == ("ports", 148)

    def test_outside_a_stage_a_charge_stands_alone(self) -> None:
        L.charge("memberships", L.STANDARD.memberships)  # no meter: nothing adds up
        L.charge("memberships", L.STANDARD.memberships)
        with pytest.raises(L.LimitExceeded) as caught:
            L.charge("memberships", L.STANDARD.memberships + 1)
        assert (caught.value.stage, caught.value.profile) == ("", "standard")
        assert str(caught.value).startswith("this request would make 1,000,001 or more port memberships")
        with L.limits_scope(TINY), pytest.raises(L.LimitExceeded):
            L.distinct("ports", [str(n) for n in range(101)])

    def test_with_no_scope_a_parse_runs_under_standard(self) -> None:
        text = aoss_ranges(12)
        with pytest.raises(L.LimitExceeded) as caught:
            get_codec("aruba_aoss").parse(text)
        assert (caught.value.profile, caught.value.kind) == ("standard", "ports")
        with L.limits_scope(L.UNLIMITED):
            assert len(get_codec("aruba_aoss").parse(text).vlans[0].tagged_ports) == 12 * 1001

    def test_two_requests_at_once_keep_their_own_counts(self) -> None:
        """The request path runs each handler on a worker thread.  A
        scope and a meter belong to that thread: one request's counts
        are not another's, and neither are its limits."""
        text = nxos_trunks(8, "2-4000", 3)  # 31,992 ids
        results: dict[str, object] = {}
        gate = threading.Barrier(2)

        def request(name: str, limits: L.Limits) -> None:
            gate.wait()
            try:
                with L.limits_scope(limits):
                    for _ in range(20):
                        tree = get_codec("cisco_nxos").parse(text)
                results[name] = sum(len(port.trunk_allowed_vlans) for port in tree.interfaces)
            except L.LimitExceeded as exc:
                results[name] = exc

        threads = [
            threading.Thread(target=request, args=("roomy", replace(TINY, name="roomy", vlan_ids=40_000))),
            threading.Thread(target=request, args=("tight", TINY)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results["roomy"] == 8 * 3999  # twenty parses of 31,992 never added up
        tight = results["tight"]
        assert isinstance(tight, L.LimitExceeded) and tight.profile == "tiny"


# ---------------------------------------------------------------------------
# 3. The words of a refusal
# ---------------------------------------------------------------------------


def _refusal(limits: L.Limits, kind: str, surface: str = "server") -> L.LimitExceeded:
    with L.limits_scope(limits, surface=surface), L.metered("parse", "cisco_nxos") as meter, \
            pytest.raises(L.LimitExceeded) as caught:
        if kind == "seconds":
            meter.deadline = time.monotonic() - 1.0
            meter.check_clock()
        else:
            L.charge(kind, int(getattr(limits, kind)) + 1, "as-written")
    return caught.value


class TestTheWordsOfARefusal:
    @pytest.mark.parametrize("kind", [kind for kind in L.KINDS if kind != "seconds"])
    def test_it_names_what_how_large_and_the_limit(self, kind: str) -> None:
        exc = _refusal(L.STANDARD, kind)
        cap = int(getattr(L.STANDARD, kind))
        said = str(exc)
        assert L.KINDS[kind][0] in said
        assert f"would make {cap + 1:,} or more" in said
        assert f"the limit is {cap:,}" in said
        assert "as-written" in said

    @pytest.mark.parametrize("kind", list(L.KINDS))
    def test_a_server_names_each_platforms_setting(self, kind: str) -> None:
        said = str(_refusal(L.STANDARD, kind))
        assert "This server runs with the 'standard' config size limit." in said
        assert "NETCANON_CONFIG_LIMITS=large (or unlimited)" in said
        assert "Preferences... -> Config size limit" in said
        large = str(_refusal(L.LARGE, kind))
        assert "NETCANON_CONFIG_LIMITS=unlimited in" in large and "(or unlimited)" not in large

    @pytest.mark.parametrize("kind", list(L.KINDS))
    def test_small_never_names_a_setting(self, kind: str) -> None:
        """A visitor to the public demo cannot set an environment
        variable.  The refusal says whose limit it is and what a
        Netcanon of one's own allows -- the standard number for the
        kind that was over."""
        exc = _refusal(L.SMALL, kind)
        said = str(exc)
        for word in ("NETCANON_", "environment", "Preferences", "--limits", "restart"):
            assert word not in said, said
        assert "the one the public demo uses" in said
        allowed = L.STANDARD.seconds if kind == "seconds" else getattr(L.STANDARD, kind)
        tail = " seconds by default." if kind == "seconds" else " by default."
        assert f"A Netcanon you run yourself allows {int(allowed):,}{tail}" in said
        assert exc.profile == "small"

    def test_on_the_command_line_it_names_the_option(self) -> None:
        said = str(_refusal(L.STANDARD, "ports", surface="cli"))
        assert "This run used the 'standard' config size limit." in said
        assert "pass --limits large (or unlimited)." in said
        assert "restart" not in said and "Preferences" not in said

    def test_limits_a_caller_made_name_no_setting(self) -> None:
        assert str(_refusal(TINY, "ports")).endswith("These limits were set by the caller.")

    def test_a_words_refusal_names_the_set_form(self) -> None:
        """A Junos config pasted as ``display set`` is not converted,
        so it is not counted in words at all: the refusal says so."""
        for limits in (L.SMALL, L.STANDARD):
            assert str(_refusal(limits, "words")).endswith(
                "The same config as set commands (`show configuration | display set`) is not counted in words."
            )
        assert "display set" not in str(_refusal(L.STANDARD, "ports"))

    def test_out_of_time_says_when(self) -> None:
        during = _refusal(replace(L.STANDARD, seconds=30.0), "seconds")
        assert str(during).startswith(
            "the request passed the 30 seconds it may take while reading the config as cisco_nxos, and was stopped."
        )
        assert (during.kind, during.cap, during.exact) == ("seconds", 30.0, True) and during.asked >= 30.0
        with L.limits_scope(replace(L.STANDARD, seconds=30.0)), L.metered("render", "vyos") as meter, \
                pytest.raises(L.LimitExceeded) as caught:
            meter.deadline = time.monotonic() - 1.0
            meter.check_clock(starting=True)
        assert "before writing the config for vyos began" in str(caught.value)

    def test_a_quote_from_the_config_is_cut_short(self) -> None:
        with L.limits_scope(TINY), L.metered("parse", "x"), pytest.raises(L.LimitExceeded) as caught:
            L.charge("ports", 101, "p" * 500)
        assert caught.value.where == "p" * 80

    @pytest.mark.parametrize("kind", list(L.KINDS))
    def test_as_data_it_is_what_a_job_carries(self, kind: str) -> None:
        exc = _refusal(L.SMALL, kind)
        refusal = Refusal(**exc.as_dict())
        assert (refusal.limit, refusal.profile, refusal.stage, refusal.codec) == (kind, "small", "parse", "cisco_nxos")
        assert refusal.how_to_raise == exc.hint and refusal.what == exc.what
        assert refusal.exact is (kind == "seconds")


# ---------------------------------------------------------------------------
# 4. Every expander counts BEFORE it makes
# ---------------------------------------------------------------------------

#: codec -> stanzas whose few bytes ask for more ids than ``TINY`` allows.
WIDE: dict[str, list[str]] = {
    "cisco_iosxe_cli": [
        "interface Gi1/0/{n}\n switchport mode trunk\n switchport trunk allowed vlan 2-4000\n!\n",
        "interface Gi1/0/{n}\n switchport mode trunk\n switchport trunk allowed vlan all\n!\n",
        "interface Gi1/0/{n}\n switchport mode trunk\n switchport trunk allowed vlan except 7\n!\n",
        "interface Gi1/0/{n}\n switchport mode trunk\n switchport trunk allowed vlan 10\n"
        " switchport trunk allowed vlan add 100-3000\n!\n",
    ],
    "cisco_nxos": [
        "interface Ethernet1/{n}\n  switchport\n  switchport mode trunk\n  switchport trunk allowed vlan 1-4093\n",
        "vlan 1-4094\n",
    ],
    "arista_eos": [
        "interface Ethernet{n}\n   switchport mode trunk\n   switchport trunk allowed vlan 2-4000\n!\n",
        "interface Ethernet{n}\n   switchport mode trunk\n   switchport trunk allowed vlan all\n!\n",
    ],
    "dell_os10": [
        "interface ethernet1/1/{n}\n switchport mode trunk\n switchport trunk allowed vlan 2-4000\n!\n",
    ],
    "aruba_aoscx": [
        "interface 1/1/{n}\n    no routing\n    vlan trunk native 1\n    vlan trunk allowed 2-4000\n",
    ],
    "juniper_junos": [
        "set interfaces xe-0/0/{n} unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces xe-0/0/{n} unit 0 family ethernet-switching vlan members 2-4000\n",
        "set interfaces xe-0/0/{n} unit 0 family ethernet-switching interface-mode trunk\n"
        "set interfaces xe-0/0/{n} unit 0 family ethernet-switching vlan members all\n",
        "set interfaces xe-0/0/{n} unit 0 family ethernet-switching interface-mode access\n"
        "set interfaces xe-0/0/{n} unit 0 family ethernet-switching vlan members 2-4000\n",
    ],
}


def _wide(codec: str, stanza: str, ports: int = 5) -> str:
    head = "set system host-name T\n" if codec == "juniper_junos" else "hostname T\n"
    return head + "".join(stanza.format(n=n) for n in range(1, ports + 1))


class TestEveryExpanderCountsFirst:
    @pytest.mark.parametrize(("codec", "stanza"), [(codec, stanza) for codec in WIDE for stanza in WIDE[codec]])
    def test_a_wide_list_is_refused_before_it_is_made(self, codec: str, stanza: str) -> None:
        """Five ports that each ask for about four thousand ids, under
        a limit of five thousand.  ``exact`` is the mark of a count
        made on something finished: a refusal that came from there
        came AFTER the entries were made.  A parser whose expander
        does not count is still refused -- by the count of the
        finished tree -- and fails here."""
        exc = _refused(codec, _wide(codec, stanza), TINY)
        assert exc.kind == "vlan_ids"
        assert exc.exact is False, "counted only after the tree was built"
        assert exc.asked <= 2 * 4094 + 5_000, "the count ran on past the limit"

    @pytest.mark.parametrize(("codec", "stanza"), [(codec, stanza) for codec in WIDE for stanza in WIDE[codec]])
    def test_and_the_same_stanza_once_is_read(self, codec: str, stanza: str) -> None:
        """One port of each is under a limit of two such lists (NX-OS
        reads a ``vlan`` line of ranges twice, and counts both): the
        text is the parser's own grammar, and is read."""
        with L.limits_scope(replace(TINY, vlan_ids=9_000)):
            tree = get_codec(codec).parse(_wide(codec, stanza, ports=1))
        made = sum(len(port.trunk_allowed_vlans) for port in tree.interfaces) + len(tree.vlans)
        assert made >= 1

    def test_an_aoss_line_stops_at_the_range_over(self) -> None:
        exc = _refused("aruba_aoss", aoss_ranges(800))
        assert (exc.kind, exc.exact, exc.asked, exc.cap) == ("ports", False, 9 * 1001, 8_192)
        assert "different ports named by port ranges" in str(exc)
        assert "(counted over 9 ranges; the last one read: 8009-9009)" in str(exc)

    def test_aoss_repeated_ranges_are_memberships(self) -> None:
        """The ports ``1-48`` tagged in 60 VLANs are 48 ports and 2,880
        memberships: it is the memberships that are over."""
        text = 'hostname "T"\n' + "".join(f"vlan {vid}\n   tagged 1-48\n   exit\n" for vid in range(2, 62))
        exc = _refused("aruba_aoss", text, TINY)
        assert (exc.kind, exc.exact) == ("memberships", False)
        with L.limits_scope(replace(TINY, memberships=3_000)):
            assert len(get_codec("aruba_aoss").parse(text).vlans) == 60

    def test_a_product_is_counted_before_one_stamp(self) -> None:
        """Forty trunks that allow every VLAN and sixty VLANs: no
        range anywhere in the text.  The product is refused before
        the first membership is stamped: no VLAN has a port."""
        text = nxos_trunks(40, "all", 60)
        seen: list[int] = []
        real = L._Meter.charge

        def watching(self, kind, n, where="", what=""):
            if kind == "memberships":
                seen.append(n)
            real(self, kind, n, where, what)

        limits = replace(TINY, vlan_ids=None)
        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(L._Meter, "charge", watching)
            exc = _refused("cisco_nxos", text, limits)
        assert (exc.kind, exc.asked, exc.exact) == ("memberships", 40 * 60, False)
        assert "(at: 40 trunks that allow every VLAN x 60 VLANs)" in str(exc)
        assert seen == [2_400], "the product was not counted whole, once"

    def test_the_projection_counts_what_it_stamps(self) -> None:
        """What is charged is what is then stamped, for a tree with
        every kind of port: an upper bound that is exact when no list
        names a VLAN twice."""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=vid) for vid in (1, 10, 20, 30)],
            interfaces=[
                CanonicalInterface(name="a", switchport_mode="access", access_vlan=10),
                CanonicalInterface(name="b", switchport_mode="trunk", trunk_allowed_vlans=[10, 20],
                                   trunk_native_vlan=30),
                CanonicalInterface(name="c", switchport_mode="trunk", trunk_allowed_vlans=list(range(1, 4095))),
                CanonicalInterface(name="d", switchport_mode="trunk", trunk_allowed_vlans=list(range(2, 4095))),
                CanonicalInterface(name="e"),
            ],
        )
        with L.limits_scope(UNCOUNTED), L.metered("parse", "x") as meter:
            project_switchport_to_vlan(tree, keep={1, 10, 20, 30})
            charged = meter.counts["memberships"]
        stamped = sum(len(vlan.tagged_ports) + len(vlan.untagged_ports) for vlan in tree.vlans)
        assert charged == stamped == 1 + 3 + 4 + 3

    def test_an_interface_range_is_counted_first(self) -> None:
        exc = _refused("juniper_junos", junos_range(30, 30), TINY)
        assert (exc.kind, exc.asked, exc.exact) == ("copies", 900, False)
        assert "(at: interface-range R)" in str(exc)
        with L.limits_scope(TINY):
            tree = get_codec("juniper_junos").parse(junos_range(20, 20))
        assert sum(len(port.ipv4_addresses) for port in tree.interfaces) == 400

    def test_block_form_junos_is_counted_in_words(self) -> None:
        """The handler round the conversion turned any error into
        advice to run ``display set``: a refusal has to pass it."""
        text = junos_blocks(400, 40)  # 16,080 words
        assert _plan("juniper_junos", "arista_eos", text).refusal is None
        job = _plan("juniper_junos", "arista_eos", text, TINY)
        assert job.status.value == "failed" and job.refusal is not None
        assert (job.refusal.limit, job.refusal.exact, job.refusal.stage) == ("words", False, "parse")
        assert "conversion failed" not in job.error
        assert job.error.startswith("refused: reading the config as juniper_junos would make ")

    def test_a_block_form_list_is_counted_in_words(self) -> None:
        path = " ".join(f"w{n}" for n in range(100))
        text = "system {\n    host-name T;\n}\n" + path + " {\n    key [ " + " ".join(
            f"v{n}" for n in range(40)) + " ];\n}\n"
        exc = _refused("juniper_junos", text, TINY)
        assert (exc.kind, exc.exact, exc.asked) == ("words", False, 3 + 40 * 102)

    def test_vyos_set_lines_are_counted_before_written(self) -> None:
        exc = _refused("vyos", vyos_set_lines(40, 40), TINY)
        assert (exc.kind, exc.exact) == ("text", False)
        assert "characters of nested blocks written out from set lines" in str(exc)

    def test_a_vyos_line_too_deep_is_a_parse_failure(self) -> None:
        """It was an unexpected error: the walk that writes the blocks
        ran out of stack past about a thousand levels."""
        text = "set system host-name T\nset " + " ".join(f"a{level}" for level in range(1200)) + "\n"
        job = _plan("vyos", "vyos", text)
        assert job.status.value == "failed" and job.refusal is None
        assert job.error.startswith("parse failed: vyos: a set line is nested 1200 levels deep")
        deep = "set system host-name T\nset " + " ".join(f"a{level}" for level in range(64)) + "\n"
        assert _plan("vyos", "vyos", deep).status.value != "failed"


# ---------------------------------------------------------------------------
# 5. An interface is counted where it is made
# ---------------------------------------------------------------------------

#: One stanza that makes one interface, for each codec that reads lines.
ONE_INTERFACE = {
    "arista_eos": "interface Ethernet{n}\n!\n",
    "aruba_aoscx": "interface 1/1/{n}\n    no shutdown\n",
    "aruba_aoss": "interface {n}\n   exit\n",
    "cisco_iosxe_cli": "interface Gi{n}\n",
    "cisco_iosxr": "interface GigabitEthernet0/0/0/{n}\n!\n",
    "cisco_nxos": "interface Ethernet1/{n}\n",
    "dell_os10": "interface ethernet1/1/{n}\n no shutdown\n!\n",
    "fortigate_cli": '    edit "port{n}"\n        set vdom "root"\n    next\n',
    "juniper_junos": "set interfaces ge-0/0/{n} mtu 9000\n",
    "mikrotik_routeros": "set [ find default-name=ether{n} ] name=ether{n}\n",
    "vyos": "    ethernet eth{n} {{\n    }}\n",
}
_AROUND = {
    "fortigate_cli": ("config system interface\n", "end\n"),
    "juniper_junos": ("set system host-name T\n", ""),
    "mikrotik_routeros": ("/interface ethernet\n", ""),
    "vyos": ("interfaces {\n", "}\n"),
}


def _interfaces(codec: str, count: int) -> str:
    before, after = _AROUND.get(codec, ("", ""))
    return before + "".join(ONE_INTERFACE[codec].format(n=n) for n in range(1, count + 1)) + after


class TestAnInterfaceIsCountedWhereItIsMade:
    """Eighteen bytes of text are five kilobytes of request, and the
    length of the text bounds nothing: 50,000 one-line stanzas are 0.9
    MB.  Every parser makes interface records, in dozens of places;
    the model is the one place they all pass."""

    @pytest.mark.parametrize("codec", sorted(ONE_INTERFACE))
    def test_whichever_parser_makes_it(self, codec: str) -> None:
        limits = replace(TINY, interfaces=50)
        with L.limits_scope(limits):
            assert len(get_codec(codec).parse(_interfaces(codec, 50)).interfaces) == 50
        exc = _refused(codec, _interfaces(codec, 89), limits)
        assert (exc.kind, exc.asked, exc.exact) == ("interfaces", 51, False)
        assert "would make 51 or more interfaces; the limit is 50 (the last one read: " in str(exc)

    def test_every_codec_that_reads_lines_is_among_them(self) -> None:
        """The two that are not read XML, where an interface is an
        element; the count is in the model, so they are held to it by
        the same line of code."""
        assert set(list_public_codecs()) - set(ONE_INTERFACE) == {"cisco_iosxe", "opnsense"}

    def test_a_record_outside_a_stage_counts_nothing(self) -> None:
        with L.limits_scope(replace(TINY, interfaces=3)):
            made = [CanonicalInterface(name=f"p{n}") for n in range(10)]
            copies = [made[0].model_copy(deep=True) for _ in range(10)]
        assert len(made) == len(copies) == 10

    def test_a_copy_is_not_counted(self) -> None:
        with L.limits_scope(replace(TINY, interfaces=3)), L.metered("render", "x") as meter:
            port = CanonicalInterface(name="p1")
            for _ in range(10):
                port.model_copy(deep=True)
                copy.deepcopy(port)
            assert meter.counts["interfaces"] == 1

    def test_a_port_a_render_makes_is_counted(self) -> None:
        """A VLAN-centric source names ports with no stanza; a
        port-centric renderer makes an interface for each."""
        text = 'hostname "T"\nvlan 10\n   tagged ' + ",".join(f"p{n}" for n in range(80)) + "\n   exit\n"
        job = _plan("aruba_aoss", "cisco_iosxe_cli", text, replace(TINY, ports=60, interfaces=70))
        assert job.status.value == "failed"
        assert (job.refusal.limit, job.refusal.stage, job.refusal.exact) == ("ports", "parse", True)
        job = _plan("aruba_aoss", "cisco_iosxe_cli", text, replace(TINY, ports=100, interfaces=70))
        assert job.status.value == "failed"
        assert (job.refusal.limit, job.refusal.stage, job.refusal.codec) == ("interfaces", "render", "cisco_iosxe_cli")
        assert _plan("aruba_aoss", "cisco_iosxe_cli", text, replace(TINY, ports=100, interfaces=80)).refusal is None


# ---------------------------------------------------------------------------
# 6. The count of a finished tree
# ---------------------------------------------------------------------------


class TestTheCountOfAFinishedTree:
    """The places that expand a token are a list, and a list cannot
    show that it is complete.  What a finished parse holds is counted
    whoever made it."""

    def test_ports_that_no_range_named(self) -> None:
        text = 'hostname "T"\nvlan 10\n   tagged ' + ",".join(f"p{n}" for n in range(300)) + "\n   exit\n"
        exc = _refused("aruba_aoss", text, TINY)
        assert (exc.kind, exc.asked, exc.exact) == ("ports", 300, True)
        assert str(exc).startswith(
            "reading the config as aruba_aoss makes 300 ports that a VLAN's or a LAG's port list names "
            "and no interface stanza declares; the limit is 100."
        )

    def test_aoss_lists_are_counted_before_sorting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AOS-S port lists are what the rest of its parse sorts,
        copies and mirrors onto the ports.  A list written name by
        name passed no range, so the tree is counted once the stanzas
        are read and before any of that work is done."""
        from netcanon.migration.codecs.aruba_aoss import parse as module

        reached: list[int] = []
        real = module._one_name_per_lag
        monkeypatch.setattr(module, "_one_name_per_lag", lambda intent: reached.append(1) or real(intent))
        text = 'hostname "T"\nvlan 10\n   tagged ' + ",".join(f"p{n}" for n in range(300)) + "\n   exit\n"
        exc = _refused("aruba_aoss", text, TINY)
        assert (exc.kind, exc.exact) == ("ports", True)
        assert not reached, "the lists were worked on before they were counted"
        with L.limits_scope(replace(TINY, ports=300)):
            get_codec("aruba_aoss").parse(text)
        assert reached == [1]

    def test_ids_that_no_range_named(self) -> None:
        """6,000 ids written one by one: no expander counts them, and
        this parser takes no count of its own."""
        text = (
            "hostname T\ninterface Ethernet1/1\n  switchport\n  switchport mode trunk\n"
            "  switchport trunk allowed vlan " + ",".join(str(1 + n % 4000) for n in range(6000)) + "\n"
        )
        exc = _refused("cisco_nxos", text, TINY)
        assert (exc.kind, exc.asked, exc.exact) == ("vlan_ids", 6000, True)
        assert "VLAN ids in the allowed lists of ports" in str(exc)

    def test_a_tree_from_a_parser_that_counts_nothing(self) -> None:
        """A codec nobody taught to count: its ``parse`` returns a
        tree that is over three limits, and the boundary every parse
        crosses refuses it."""
        from netcanon.migration.codecs.base import CodecBase
        from netcanon.models.migration import CapabilityMatrix

        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface.model_construct(name=f"p{n}", trunk_allowed_vlans=list(range(1, 60)))
                for n in range(30)
            ],
            vlans=[CanonicalVlan(id=7, tagged_ports=[f"q{n}" for n in range(130)])],
        )

        class _CountsNothing(CodecBase):
            name = "counts_nothing"

            @property
            def capabilities(self) -> CapabilityMatrix:
                return CapabilityMatrix(adapter=self.name)

            def parse(self, raw: str) -> CanonicalIntent:
                return tree

            def render(self, tree: object) -> str:
                return "x" * 60_000

        codec = _CountsNothing()
        for limits, kind, asked in (
            (replace(TINY, vlan_ids=1_000), "vlan_ids", 30 * 59),
            (replace(TINY, memberships=100), "memberships", 130),
            (TINY, "ports", 130),
            (replace(TINY, ports=None, interfaces=20), "interfaces", 30),
        ):
            with L.limits_scope(limits), pytest.raises(L.LimitExceeded) as caught:
                codec.parse("anything")
            assert (caught.value.kind, caught.value.asked, caught.value.exact) == (kind, asked, True)
        with L.limits_scope(TINY), pytest.raises(L.LimitExceeded) as caught:
            codec.render(tree)
        assert (caught.value.kind, caught.value.asked, caught.value.exact, caught.value.stage) == (
            "text", 60_000, True, "render",
        )
        with L.limits_scope(UNCOUNTED):
            assert codec.parse("anything") is tree and len(codec.render(tree)) == 60_000

    def test_every_parse_and_render_is_wrapped(self) -> None:
        for name in list_public_codecs():
            cls = type(get_codec(name))
            assert getattr(cls.__dict__["parse"], "_nc_parse_wrapped", False), name
            assert getattr(cls.__dict__["render"], "_nc_render_wrapped", False), name


# ---------------------------------------------------------------------------
# 7. The renderers that write every id count the lines first
# ---------------------------------------------------------------------------

_ID_LINE = {
    "cisco_iosxe_cli": " switchport trunk allowed vlan ",
    "arista_eos": "   switchport trunk allowed vlan ",
}


def _charges(kind: str, work: Callable[[], object]) -> list[int]:
    """What *work* charged of *kind*, a number for each charge."""
    seen: list[int] = []
    real = L._Meter.charge

    def watching(self, charged, n, where="", what=""):
        if charged == kind:
            seen.append(n)
        real(self, charged, n, where, what)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(L._Meter, "charge", watching)
        work()
    return seen


class TestTheRenderersCountFirst:
    def test_the_length_of_an_id_list_unwritten(self) -> None:
        rng = random.Random(4094)
        lists = [[], [7], [1, 10, 100, 1000, 9999], list(range(1, 4095)), [4094, 3, 3, 12, 999, 1000]]
        lists += [[rng.randrange(0, 10_000) for _ in range(rng.randrange(1, 60))] for _ in range(300)]
        for ids in lists:
            assert joined_ids_length(ids) == len(",".join(str(vid) for vid in ids)), ids
        # More digits than a VLAN id has: counted as four, never as more than is written.
        assert joined_ids_length([123456, 5]) == 4 + 1 + 1 < len("123456,5")

    @pytest.mark.parametrize("target", sorted(_ID_LINE))
    def test_what_is_counted_is_what_is_then_written(self, target: str) -> None:
        """On every committed capture of a switch codec and on a text
        with wide lists: the one charge made before the output is the
        length of the lines that carry a list -- and so never more
        than the output."""
        texts = [("built", "cisco_nxos", nxos_trunks(30, "2-4000", 4)), ("built", "arista_eos", eos_trunks(9, "all"))]
        for folder in ("cisco_iosxe", "cisco_nxos", "arista_eos", "aruba_aoss", "aruba_aoscx", "junos"):
            for path in sorted((FIXTURES / "real" / folder).glob("*")):
                if path.is_file() and path.suffix not in (".md", ".json", ".yaml"):
                    texts.append((path.name, DIR_TO_CODEC_NAME[folder], path.read_text(encoding="utf-8")))
        seen_lists = 0
        for label, source, text in texts:
            with L.limits_scope(UNCOUNTED):
                tree = get_codec(source).parse(text)
                rendered: list[str] = []
                charged = _charges(
                    "text", lambda tree=tree, rendered=rendered: rendered.append(get_codec(target).render(tree)),
                )
            lines = [line for line in rendered[0].split("\n") if line.startswith(_ID_LINE[target])]
            assert sum(charged) == sum(len(line) + 1 for line in lines), label
            assert len(charged) == (1 if lines else 0), label
            seen_lists += len(lines)
        assert seen_lists > 100, "the captures held too few lists for this to mean anything"

    @pytest.mark.parametrize("target", sorted(_ID_LINE))
    def test_wide_lists_are_refused_before_a_character(self, target: str) -> None:
        """Thirty trunks of 3,999 ids are 570,000 characters of lists.
        Written and then measured that is megabytes held; counted from
        the lengths of the lists it is nothing."""
        limits = replace(TINY, vlan_ids=None, text=400_000)
        with L.limits_scope(UNCOUNTED):
            tree = get_codec("cisco_nxos").parse(nxos_trunks(30, "2-4000", 4))
        caught: list[L.LimitExceeded] = []

        def render() -> None:
            with L.limits_scope(limits), pytest.raises(L.LimitExceeded) as raised:
                get_codec(target).render(tree)
            caught.append(raised.value)

        held = _peak(render)
        exc = caught[0]
        assert (exc.kind, exc.stage, exc.codec, exc.exact) == ("text", "render", target, False)
        assert "(at: the allowed-VLAN lists of 30 ports, written id by id)" in str(exc)
        assert held < 200_000, f"{held:,} bytes were held on the way to a refusal"
        with L.limits_scope(UNCOUNTED):
            written = _peak(lambda: get_codec(target).render(tree))
        assert written > 1_000_000, "writing the lists was expected to hold megabytes"

    def test_junos_counts_the_lines_of_each_port(self) -> None:
        """A wide list is a line or two for Junos.  What is a line
        each is a run of the list: a list of every other id."""
        with L.limits_scope(UNCOUNTED):
            wide = get_codec("arista_eos").parse(eos_trunks(40, "2-4000"))
            odd = get_codec("arista_eos").parse(eos_trunks(6, ",".join(str(vid) for vid in range(1, 4094, 2))))
            written = get_codec("juniper_junos").render(wide)
        assert len(written) < 12_000 and "vlan members 2-4000" in written
        with L.limits_scope(UNCOUNTED):
            rendered: list[str] = []
            charged = _charges("text", lambda: rendered.append(get_codec("juniper_junos").render(odd)))
        members = [line for line in rendered[0].split("\n") if " vlan members " in line]
        assert len(charged) == 6 and sum(charged) == sum(len(line) + 1 for line in members)
        with L.limits_scope(replace(TINY, vlan_ids=None, text=400_000)), pytest.raises(L.LimitExceeded) as caught:
            get_codec("juniper_junos").render(odd)
        assert (caught.value.kind, caught.value.exact, caught.value.stage) == ("text", False, "render")
        assert "'vlan members' lines for one port" in str(caught.value)

    def test_every_output_is_measured_whoever_wrote_it(self) -> None:
        """An output over the limit that nothing counted beforehand is
        refused when it is done: no renderer is outside the limit."""
        text = 'hostname "T"\n' + "".join(f"vlan {vid}\n   tagged 1-48\n   exit\n" for vid in range(2, 400))
        job = _plan("aruba_aoss", "aruba_aoss", text, replace(TINY, memberships=None, text=5_000))
        assert job.status.value == "failed"
        assert (job.refusal.limit, job.refusal.stage, job.refusal.exact) == ("text", "render", True)
        assert job.rendered is None and job.validation is None
        assert job.error.startswith("refused: writing the config for aruba_aoss makes ")


# ---------------------------------------------------------------------------
# 8. Each limit: under it nothing changes, over it the answer is no
# ---------------------------------------------------------------------------

#: Every other VLAN id: a list Junos writes a line an id for.
_ODD_IDS = ",".join(str(vid) for vid in range(1, 4094, 2))

#: kind -> (source, target, a text under the ``small`` limit, one over it,
#: the most bytes that may be held on the way to the refusal).  The
#: ceilings are what the limit itself admits, with room: 1,048,576 ids
#: are 8 MB of list slots however they are counted, and 2,500
#: interfaces are 2,500 interfaces.
EACH_LIMIT: dict[str, tuple[str, str, Callable[[], str], Callable[[], str], int]] = {
    "vlan_ids": ("arista_eos", "cisco_nxos", lambda: eos_trunks(256, "all"), lambda: eos_trunks(257, "all"),
                 20_000_000),
    "memberships": ("cisco_nxos", "aruba_aoss", lambda: nxos_trunks(125, "all", 400),
                    lambda: nxos_trunks(126, "all", 400), 12_000_000),
    "ports": ("aruba_aoss", "aruba_aoss", lambda: aoss_ranges(2), lambda: aoss_ranges(3), 2_000_000),
    "interfaces": ("cisco_iosxe_cli", "juniper_junos", lambda: iosxe_stanzas(2_500), lambda: iosxe_stanzas(2_501),
                   20_000_000),
    "copies": ("juniper_junos", "arista_eos", lambda: junos_range(100, 100), lambda: junos_range(101, 100),
               6_000_000),
    "words": ("juniper_junos", "arista_eos", lambda: junos_blocks(499, 498), lambda: junos_blocks(499, 501),
              60_000_000),
    "text": ("arista_eos", "juniper_junos", lambda: eos_trunks(40, _ODD_IDS), lambda: eos_trunks(60, _ODD_IDS),
             40_000_000),
}


class TestEachLimit:
    def test_there_is_a_text_for_every_kind(self) -> None:
        assert set(EACH_LIMIT) == set(L.KINDS) - {"seconds"}

    @pytest.mark.parametrize("kind", sorted(EACH_LIMIT))
    def test_a_text_under_it_is_translated_as_ever(self, kind: str) -> None:
        source, target, under, _over, _ceiling = EACH_LIMIT[kind]
        text = under()
        limited, free = _plan(source, target, text, "small"), _plan(source, target, text, L.UNLIMITED)
        assert limited.refusal is None and free.refusal is None, limited.error
        assert limited.status == free.status and limited.status.value != "failed", limited.error
        assert limited.rendered == free.rendered
        assert limited.error == free.error and limited.warnings == free.warnings

    @pytest.mark.parametrize("kind", sorted(EACH_LIMIT))
    def test_a_text_over_it_is_refused_unmade(self, kind: str) -> None:
        source, target, _under, over, ceiling = EACH_LIMIT[kind]
        text = over()
        jobs: list = []
        held = _peak(lambda: jobs.append(_plan(source, target, text, "small")))
        job = jobs[0]
        assert job.status.value == "failed" and job.rendered is None and job.validation is None
        assert job.refusal is not None, job.error
        assert (job.refusal.limit, job.refusal.exact, job.refusal.profile) == (kind, False, "small")
        cap = int(getattr(L.SMALL, kind))
        assert job.refusal.cap == cap and cap < job.refusal.asked
        assert job.error.startswith("refused: ") and not job.error.startswith("refused: this request")
        assert job.refusal.what in job.error and f"the limit is {cap:,}" in job.error
        assert f"{int(job.refusal.asked):,} or more" in job.error
        assert "the one the public demo uses" in job.error
        assert held < ceiling, f"{kind}: {held:,} bytes were held on the way to the refusal"


# ---------------------------------------------------------------------------
# 9. The texts that were measured, at the sizes they were measured at
# ---------------------------------------------------------------------------


class TestTheTextsThatWereMeasured:
    """Each of these is small, and each took seconds and hundreds of
    megabytes -- or gigabytes -- before what a config makes was made
    cheaper, and then counted."""

    def test_one_aoss_line_of_800_ranges(self) -> None:
        """Eleven kilobytes that name 800,800 ports: 295 MB to parse.
        Refused at the ninth range, in a megabyte or two."""
        text = aoss_ranges(800)
        assert len(text) < 12_000
        for limits, asked in (("small", 3 * 1001), ("standard", 9 * 1001)):  # 2,048 and 8,192 ports
            jobs: list = []
            started = time.perf_counter()
            held = _peak(
                lambda limits=limits, jobs=jobs: jobs.append(_plan("aruba_aoss", "cisco_iosxe_cli", text, limits)),
            )
            took = time.perf_counter() - started
            job = jobs[0]
            assert job.status.value == "failed" and job.refusal.limit == "ports"
            assert (job.refusal.asked, job.refusal.exact) == (asked, False)
            assert held < 8_000_000, f"{limits}: {held:,} bytes"
            assert took < 5.0, f"{limits}: {took:.1f} s"

    def test_a_thousand_arista_trunks_of_2_to_4000(self) -> None:
        """Ninety kilobytes, four million ids: gigabytes, once.  The
        demo's limits refuse it at the 263rd trunk.  The standard
        ones read it (32 MB of list slots); written id by id it is
        nineteen megabytes, which a limit on the output refuses before
        a character is written -- and Junos and NX-OS write it as a
        range."""
        text = eos_trunks(1000)
        assert len(text) < 100_000
        caught: list[L.LimitExceeded] = []
        held = _peak(lambda: caught.append(_refused("arista_eos", text, "small")))
        assert (caught[0].kind, caught[0].exact, caught[0].lists) == ("vlan_ids", False, 263)
        assert caught[0].asked == 263 * 3999 and held < 24_000_000, f"{held:,} bytes"
        with L.limits_scope("standard"):
            tree = get_codec("arista_eos").parse(text)
        assert sum(len(port.trunk_allowed_vlans) for port in tree.interfaces) == 3_999_000
        tight = replace(L.STANDARD, name="tight", text=L.SMALL.text)
        for target in ("cisco_iosxe_cli", "arista_eos"):
            refusals: list[L.LimitExceeded] = []

            def render(target: str = target, refusals: list[L.LimitExceeded] = refusals) -> None:
                with L.limits_scope(tight), pytest.raises(L.LimitExceeded) as raised:
                    get_codec(target).render(tree)
                refusals.append(raised.value)

            held = _peak(render)
            assert (refusals[0].kind, refusals[0].exact, refusals[0].stage) == ("text", False, "render")
            assert refusals[0].asked > 18_000_000
            assert held < 1_000_000, f"{target}: {held:,} bytes were held on the way to the refusal"
        with L.limits_scope(tight):
            assert len(get_codec("juniper_junos").render(tree)) < 300_000
            assert len(get_codec("cisco_nxos").render(tree)) < 300_000

    def test_a_thousand_trunks_times_a_thousand_vlans(self) -> None:
        """118 KB with no range in it; a million memberships.  That
        is the standard limit exactly, and is read; one trunk more is
        refused, and so is the text itself under the demo's limits --
        before one membership is stamped."""
        text = nxos_trunks(1000, "all", 1000)
        assert len(text) < 130_000
        with L.limits_scope("standard"):
            tree = get_codec("cisco_nxos").parse(text)
        assert sum(len(vlan.tagged_ports) for vlan in tree.vlans) == 1_000_000
        del tree
        over = _refused("cisco_nxos", nxos_trunks(1001, "all", 1000), "standard")
        assert (over.kind, over.asked, over.exact) == ("memberships", 1_001_000, False)
        caught: list[L.LimitExceeded] = []
        tight = replace(L.STANDARD, name="tight", memberships=L.SMALL.memberships)
        held = _peak(lambda: caught.append(_refused("cisco_nxos", text, tight)))
        assert (caught[0].kind, caught[0].asked, caught[0].exact) == ("memberships", 1_000_000, False)
        assert "(at: 1,000 trunks that allow every VLAN x 1,000 VLANs)" in str(caught[0])
        # The lists of ids the ports state are 33 MB; a million memberships more are another 45.
        assert held < 50_000_000, f"{held:,} bytes were held on the way to the refusal"
        # The demo's limits stop sooner still: at the 257th port that says "all".
        small = _refused("cisco_nxos", text, "small")
        assert (small.kind, small.exact, small.lists) == ("vlan_ids", False, 257)

    def test_32000_addresses_on_one_unit_are_quick(self) -> None:
        """Two megabytes that expand to nothing: no limit applies, and
        none is needed while the lines of one record cost their
        number and not its square (twelve seconds, before)."""
        text = junos_one_unit(32_000)
        started = time.perf_counter()
        job = _plan("juniper_junos", "arista_eos", text, "small")
        took = time.perf_counter() - started
        assert job.refusal is None and job.status.value != "failed", job.error
        assert took < 10.0, f"{took:.1f} s"

    def test_fifty_thousand_one_line_interface_stanzas(self) -> None:
        """0.9 MB of text, 240 MB of request: the standard limit is
        exactly this many, and one more is refused."""
        with L.limits_scope("standard"):
            assert len(get_codec("cisco_iosxe_cli").parse(iosxe_stanzas(50_000)).interfaces) == 50_000
        exc = _refused("cisco_iosxe_cli", iosxe_stanzas(50_001), "standard")
        assert (exc.kind, exc.asked, exc.exact) == ("interfaces", 50_001, False)
        assert "(the last one read: Gi50000)" in str(exc)


# ---------------------------------------------------------------------------
# 10. The deadline
# ---------------------------------------------------------------------------


class _Clock:
    """Stands in for ``time`` in the limits module: the first *free*
    looks at it read nought, and every later one a time long past any
    deadline.  Two looks are free on the way into a parse: the scope
    opening, and the stage starting."""

    def __init__(self, free: int = 2) -> None:
        self.looks, self.free = 0, free

    def monotonic(self) -> float:
        self.looks += 1
        return 0.0 if self.looks <= self.free else 1.0e9


def _only_loops_look(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the look at the clock out of ``charge``: what is left to
    stop a parse is its loops."""
    real = L._Meter.charge

    def without_a_look(self, kind, n, where="", what=""):
        deadline, self.deadline = self.deadline, None
        try:
            real(self, kind, n, where, what)
        finally:
            self.deadline = deadline

    monkeypatch.setattr(L._Meter, "charge", without_a_look)


def _long_text(codec: str) -> str:
    """A text *codec* reads that is some hundreds of lines, stanzas or
    elements long: its synthetic capture, written several times over
    (for the two XML codecs, one element of it written several hundred
    times -- a document has one root)."""
    (path,) = sorted((FIXTURES / "synthetic" / codec).glob("kitchen_sink.*"))
    text = path.read_text(encoding="utf-8")
    grown = {"opnsense": ("vlans", "vlan"), "cisco_iosxe": ("interfaces", "interface")}.get(codec)
    if grown is None:
        return text * 8
    root = ET.fromstring(text)
    holder = next(el for el in root.iter() if el.tag.rpartition("}")[2] == grown[0])
    child = next(el for el in holder if el.tag.rpartition("}")[2] == grown[1])
    for _ in range(600):
        holder.append(copy.deepcopy(child))
    return ET.tostring(root, encoding="unicode")


class TestTheDeadline:
    @pytest.mark.parametrize("codec", list_public_codecs())
    def test_a_parse_past_its_deadline_is_stopped(
        self, codec: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Time here passes only when the clock is looked at, and the
        deadline passes straight after the parse begins.  A parser
        that reads its text without looking again reads to the end
        and returns, which fails this: for a codec added tomorrow, as
        much as for these."""
        text = _long_text(codec)
        with L.limits_scope(UNCOUNTED):
            get_codec(codec).parse(text)  # the text is read when there is time
        _only_loops_look(monkeypatch)
        monkeypatch.setattr(L, "time", _Clock())
        with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), \
                pytest.raises(L.LimitExceeded) as caught:
            get_codec(codec).parse(text)
        exc = caught.value
        assert (exc.kind, exc.stage, exc.codec, exc.starting) == ("seconds", "parse", codec, False)
        assert str(exc).startswith(
            f"the request passed the 10 seconds it may take while reading the config as {codec}, and was stopped."
        )

    def test_a_spent_request_starts_no_other_stage(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from netcanon.migration.codecs.cisco_iosxe_cli import codec as module

        started: list[int] = []
        real = module.parse_intent
        monkeypatch.setattr(module, "parse_intent", lambda raw: started.append(1) or real(raw))
        clock = _Clock(free=1_000_000)
        monkeypatch.setattr(L, "time", clock)
        codec = get_codec("cisco_iosxe_cli")
        with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)):
            codec.parse("hostname A\n")
            clock.free = 0
            with pytest.raises(L.LimitExceeded) as caught:
                codec.parse("hostname A\n")
            with pytest.raises(L.LimitExceeded) as rendering:
                codec.render(CanonicalIntent())
        assert (caught.value.kind, caught.value.starting) == ("seconds", True)
        assert len(started) == 1, "the second parse was started with the request's time already spent"
        assert "before writing the config for cisco_iosxe_cli began" in str(rendering.value)

    def test_a_spent_request_starts_no_inner_stage(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A codec that parses in order to render starts a stage inside
        a stage.  The outer one looked at the clock when it began; the
        inner one looks again when it does."""
        clock = _Clock(free=1_000_000)
        monkeypatch.setattr(L, "time", clock)
        entered: list[int] = []
        with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), L.metered("render", "outer"):
            with L.metered("parse", "inner"):
                entered.append(1)
            clock.free = 0
            with pytest.raises(L.LimitExceeded) as caught, L.metered("parse", "inner"):
                entered.append(2)
        assert entered == [1], "a stage was started with the request's time already spent"
        assert (caught.value.kind, caught.value.starting) == ("seconds", True)

    def test_a_count_looks_at_the_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A place that makes entries without a loop over lines -- one
        range of thousands, a product -- still looks: every count
        does."""
        clock = _Clock(free=1_000_000)
        monkeypatch.setattr(L, "time", clock)
        with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), L.metered("parse", "x") as meter:
            L.charge("vlan_ids", 1)
            clock.free = 0
            with pytest.raises(L.LimitExceeded) as caught:
                L.charge("vlan_ids", 1)
            assert meter.counts["vlan_ids"] == 2
        assert (caught.value.kind, caught.value.starting) == ("seconds", False)
        assert "while reading the config as x" in str(caught.value)

    def test_time_out_between_stages_is_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clock = _Clock(free=1_000_000)
        monkeypatch.setattr(L, "time", clock)

        def late(tree):
            clock.free = 0
            return tree

        from netcanon.services.migration_pipeline import run_plan

        with L.limits_scope(replace(L.STANDARD, seconds=10.0)):
            job = run_plan(get_codec("cisco_iosxe_cli"), get_codec("juniper_junos"), "hostname A\n", transforms=[late])
        assert job.status.value == "failed" and job.rendered is None
        assert (job.refusal.limit, job.refusal.stage, job.refusal.cap) == ("seconds", "render", 10.0)
        assert job.error.startswith(
            "refused: the request passed the 10 seconds it may take before writing the config for "
            "juniper_junos began, and was stopped."
        )

    def test_a_stage_that_finished_late_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """What the deadline does NOT do, as ``SECURITY.md`` has it: a
        renderer is not looked at while it runs, so a request whose
        time ran out there is not stopped, and its job comes back as
        any other.  This is pinned so that the document cannot say
        more than the code does."""
        from netcanon.migration.codecs.juniper_junos import codec as module

        clock = _Clock(free=1_000_000)
        monkeypatch.setattr(L, "time", clock)
        real = module.render_intent

        def slow(tree):
            clock.free = 0  # the time runs out inside the renderer
            return real(tree)

        monkeypatch.setattr(module, "render_intent", slow)
        with L.limits_scope(replace(L.STANDARD, seconds=10.0)):
            job = run_plan_with_overrides(
                get_codec("cisco_iosxe_cli"), get_codec("juniper_junos"), "hostname A\n", port_rename_map={},
            )
        assert job.refusal is None and job.status.value == "completed"
        assert "host-name A" in job.rendered

    def test_every_line_of_every_capture_is_ticked(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No list of loops: count the steps that went through
        ``ticked`` or ``tick`` while each committed capture was
        parsed.  A parser with a line loop that does not look at the
        clock walks fewer steps than the capture has lines."""
        steps = [0]
        real, real_runs = L._ticking, L._in_runs

        def counting(items, clock):
            for item in real(items, clock):
                steps[0] += 1
                yield item

        def counting_runs(items, clock):
            for run in real_runs(items, clock):
                steps[0] += len(run)
                yield run

        monkeypatch.setattr(L, "_ticking", counting)
        monkeypatch.setattr(L, "_in_runs", counting_runs)
        short, read = [], 0
        for folder, codec in sorted(DIR_TO_CODEC_NAME.items()):
            if codec == "opnsense":  # XML: one call into C reads the text
                continue
            for path in sorted((FIXTURES / "real" / folder).glob("*")):
                if not path.is_file() or path.suffix in (".md", ".json", ".yaml"):
                    continue
                text = path.read_text(encoding="utf-8")
                steps[0] = 0
                with L.limits_scope(UNCOUNTED), L.metered("parse", codec) as meter:
                    get_codec(codec).parse(text)
                    walked = steps[0] + meter._n  # ``tick()`` counts its own calls
                lines = sum(1 for line in text.splitlines() if line.strip())
                read += 1
                if walked < lines:
                    short.append((path.name, lines, walked))
        assert read > 80, "too few captures were read for this to mean anything"
        assert not short, f"captures with lines no ticking loop walked: {short[:5]}"

    def test_a_loop_outside_a_stage_looks_at_the_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reading the device out of a config, and detection, loop over
        lines before any parse: the request's deadline is theirs too."""
        monkeypatch.setattr(L, "time", _Clock(free=1))
        with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), pytest.raises(L.LimitExceeded) as caught:
            for _ in L.ticked(range(1_000)):
                pass
        assert (caught.value.kind, caught.value.stage) == ("seconds", "")
        assert str(caught.value).startswith("the request passed the 10 seconds it may take, and was stopped.")
        # A list is walked a run at a time, and the clock is looked at between runs.
        monkeypatch.setattr(L, "time", _Clock(free=1))
        walked = []
        with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), pytest.raises(L.LimitExceeded):
            for item in L.ticked(list(range(1_000))):
                walked.append(item)
        assert walked == list(range(256))
        with L.limits_scope(UNCOUNTED):
            assert list(L.ticked(list(range(1_000)))) == list(range(1_000))
            assert list(L.ticked(iter(range(1_000)))) == list(range(1_000))
            assert list(L.ticked([])) == [] and list(L.ticked(enumerate("ab"))) == [(0, "a"), (1, "b")]
        items = [1, 2, 3]
        assert L.ticked(items) is items, "with no deadline in force a loop costs nothing"
        with L.limits_scope(L.UNLIMITED):
            assert L.ticked(items) is items

    def test_the_projections_look_at_the_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=vid) for vid in range(2, 600)],
            interfaces=[
                CanonicalInterface(name=f"p{n}", switchport_mode="access", access_vlan=2 + n % 500)
                for n in range(600)
            ],
        )
        _only_loops_look(monkeypatch)
        for work in (lambda: project_switchport_to_vlan(tree, keep=None), lambda: project_vlan_to_switchport(tree)):
            monkeypatch.setattr(L, "time", _Clock())
            with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), \
                    L.metered("parse", "x"), pytest.raises(L.LimitExceeded) as caught:
                work()
            assert caught.value.kind == "seconds"


# ---------------------------------------------------------------------------
# 11. Reading the code
# ---------------------------------------------------------------------------

#: Every module that reads the lines of a config.
_READERS = sorted([
    *(PACKAGE / "migration").rglob("*.py"),
    *(PACKAGE / "services").glob("migration_*.py"),
    PACKAGE / "tools" / "sanitize.py",
])
_WRAPPERS = ("enumerate", "iter", "ticked", "list", "reversed")

#: Comprehensions over lines that need not look at the clock, and why.
#: (file, function) -> the reason.
QUICK_FILTERS = {
    ("netcanon/migration/codecs/cisco_iosxe/codec.py", "render"):
        "drops the blank lines of the output it has just written: one test a line",
    ("netcanon/migration/codecs/cisco_iosxe/codec.py", "_render_canonical"):
        "drops the blank lines of the output it has just written: one test a line",
    ("netcanon/migration/codecs/opnsense/render.py", "_pretty_print"):
        "drops the blank lines of the output it has just written: one test a line",
}


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _unwrap(node: ast.AST) -> tuple[ast.AST, bool]:
    """(the iterable inside enumerate / iter / ticked, whether ticked wraps it)"""
    ticked = False
    while (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in _WRAPPERS and node.args):
        ticked = ticked or node.func.id == "ticked"
        node = node.args[0]
    return node, ticked


def _is_splitlines(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "splitlines"


def _loops_that_do_not_look(source: str, rel: str = "") -> list[str]:
    """The loops over the lines of a config in *source* that never
    look at the deadline, as ``file:line``.

    A loop is over the lines when it iterates ``<text>.splitlines()``,
    a name the same function got from one, or a parameter called
    ``lines`` or ``raw_lines``; or, for a ``while``, when its test
    compares something with the length of such a list.  A ``for`` has
    to wrap its iterable in ``ticked(...)``, a ``while`` to call
    ``tick()``, and a comprehension to do the first or be listed in
    ``QUICK_FILTERS``.
    """
    missing = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {arg.arg for arg in [*fn.args.args, *fn.args.kwonlyargs] if arg.arg in ("lines", "raw_lines")}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and _is_splitlines(_unwrap(node.value)[0]):
                names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        lengths = {
            target.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name) and node.value.func.id == "len" and node.value.args
            and isinstance(node.value.args[0], ast.Name) and node.value.args[0].id in names
            for target in node.targets if isinstance(target, ast.Name)
        }

        def over_lines(node: ast.AST, names: set[str] = names) -> bool:
            return _is_splitlines(node) or (isinstance(node, ast.Name) and node.id in names)

        for node in ast.walk(fn):
            if isinstance(node, ast.For):
                inner, ticked = _unwrap(node.iter)
                if over_lines(inner) and not ticked:
                    missing.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.comprehension):
                inner, ticked = _unwrap(node.iter)
                if over_lines(inner) and not ticked and (rel, fn.name) not in QUICK_FILTERS:
                    missing.append(f"{rel}:{node.iter.lineno}")
            elif isinstance(node, ast.While):
                over = any(
                    (isinstance(side, ast.Name) and side.id in lengths)
                    or (isinstance(side, ast.Call) and isinstance(side.func, ast.Name) and side.func.id == "len"
                        and side.args and isinstance(side.args[0], ast.Name) and side.args[0].id in names)
                    for compare in ast.walk(node.test) if isinstance(compare, ast.Compare)
                    for side in [compare.left, *compare.comparators]
                )
                looks = any(
                    isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "tick"
                    for statement in node.body for call in ast.walk(statement)
                )
                if over and not looks:
                    missing.append(f"{rel}:{node.lineno}")
    return sorted(set(missing))


#: What a module under ``codecs/`` may turn two numbers into a run of
#: entries with: ``range(...)``, a slice of the shared id tuple, the
#: helper that makes one.  (file, function, the expression) -> its
#: answer.  ``charged`` means the function counts what it is about to
#: make (the test reads that it calls ``charge`` or ``distinct``);
#: anything else says what bounds the run.
RUNS_OF_ENTRIES: dict[tuple[str, str, str], str] = {
    ("_helpers.py", "<module>", "range(4095)"): "the shared tuple itself: 4,095 ints, made once",
    ("_helpers.py", "_entry", "range(entry[2], len(items))"): "walks a list that exists",
    ("_helpers.py", "vlan_id_run", "VLAN_IDS[low:high + 1]"):
        "the expander every caller of it is in this table for",
    ("_helpers.py", "_normalise_mac_to_colon_hex", "range(0, 12, 2)"): "six",
    ("_helpers.py", "_parse_vlan_list", "VLAN_IDS[lo_i:hi_i + 1]"): "charged",
    ("_helpers.py", "merge_trunk_allowed", "vlan_id_run(1, 4094)"): "charged",
    ("_helpers.py", "merge_trunk_allowed", "VLAN_IDS[1:]"): "charged",
    ("arista_eos/parse.py", "_expand_vlan_list", "VLAN_IDS[a_i:b_i + 1]"): "charged",
    ("aruba_aoss/parse.py", "_expand_port_range", "range(num_lo, num_hi + 1)"): "charged",
    ("fortigate_cli/parse.py", "_apply_system_dhcp_server", "range(1, 4)"): "three",
    ("juniper_junos/parse.py", "_resolve_vlan_member_to_vids", "vlan_id_run(lo, hi)"): "charged",
    ("juniper_junos/parse.py", "parse_intent", "vlan_id_run(1, 4094)"): "charged",
    ("juniper_junos/parse.py", "parse_block", "range(push_count)"):
        "pops the words one statement pushed; the words are what is charged",
    ("juniper_junos/render.py", "<module>", "range(1, 4095)"): "a set of every VLAN id, made once",
    ("juniper_junos/render.py", "render_intent", "range(first, last + 1)"): "charged",
}


def _runs_of_entries() -> dict[tuple[str, str, str], bool]:
    """Every such expression in a module under ``codecs/``, and
    whether the function it is in counts (calls ``charge`` or
    ``distinct``)."""
    found: dict[tuple[str, str, str], bool] = {}
    root = PACKAGE / "migration" / "codecs"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner: dict[int, ast.AST] = {}
        for fn in ast.walk(tree):  # outer functions first: the innermost wins
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    owner[id(node)] = fn
        for node in ast.walk(tree):
            run = (
                (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id in ("range", "vlan_id_run"))
                or (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "VLAN_IDS" and isinstance(node.slice, ast.Slice))
            )
            if not run:
                continue
            fn = owner.get(id(node))
            counts = fn is not None and any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id in ("charge", "distinct")
                for call in ast.walk(fn)
            )
            name = fn.name if fn is not None else "<module>"
            found[(path.relative_to(root).as_posix(), name, ast.unparse(node))] = counts
    return found


#: ``except Exception`` handlers that are allowed NOT to name
#: ``LimitExceeded`` before them, and why.  Any other one fails: a
#: broad handler between an expander and its caller turns "too large"
#: into "could not be parsed".  (file, function) -> why it is safe.
BROAD_HANDLERS = {
    ("netcanon/migration/codecs/aruba_aoss/parse.py", "parse_intent"):
        "wraps one mask conversion; nothing in it counts or loops",
    ("netcanon/migration/canonical/port_names.py", "kind_of"): "wraps one classifier call on one name",
    ("netcanon/migration/__init__.py", "*"): "the package's own imports, at start",
    ("netcanon/migration/vendors/__init__.py", "*"): "loads the vendor declarations at start",
    ("netcanon/migration/device_models.py", "*"): "loads the model families at start",
    ("netcanon/migration/target_profiles.py", "*"): "loads the target profiles at start",
    ("netcanon/services/migration_pipeline.py", "reads_as_a_port"): "wraps one classifier call on one name",
    ("netcanon/services/migration_pipeline.py", "_management_form"): "wraps one classifier call on one name",
}
_ROOTS_OF_BROAD_HANDLERS = [
    PACKAGE / "migration", PACKAGE / "services" / "migration_pipeline.py",
    PACKAGE / "services" / "migration_detect.py", PACKAGE / "tools" / "sanitize.py",
    PACKAGE / "api" / "routes" / "migration.py", PACKAGE / "api" / "routes" / "_migration_helpers.py",
    PACKAGE / "api" / "routes" / "sanitize.py", PACKAGE / "cli.py",
]


def _broad_handlers_that_could_swallow(source: str, rel: str) -> list[str]:
    tree = ast.parse(source)
    owner: dict[int, str] = {}
    for fn in ast.walk(tree):  # outer functions first: the innermost wins
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                owner[id(node)] = fn.name
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        named = False
        for handler in node.handlers:
            kinds = ast.unparse(handler.type) if handler.type is not None else "BaseException"
            if "LimitExceeded" in kinds:
                named = True
            elif not named and any(kind in ("Exception", "BaseException") for kind in kinds.strip("()").split(", ")):
                fn = owner.get(id(node), "*")
                if (rel, fn) not in BROAD_HANDLERS and (rel, "*") not in BROAD_HANDLERS:
                    offenders.append(f"{rel}:{handler.lineno} in {fn}")
    return offenders


class TestReadingTheCode:
    def test_every_loop_over_lines_is_ticked(self) -> None:
        missing = [
            where for path in _READERS
            for where in _loops_that_do_not_look(path.read_text(encoding="utf-8"), _rel(path))
        ]
        assert not missing, f"loops over a config's lines that never look at the deadline: {missing}"

    def test_the_rule_reads_every_parser_module(self) -> None:
        """Not ``*/parse.py`` and a few named files: a parser written
        in a module of another name is read as well."""
        read = {_rel(path) for path in _READERS}
        for module in ("codecs/_scanner.py", "codecs/_input_shape.py", "codecs/cisco_iosxe/codec.py",
                       "codecs/aruba_aoss/deployment_detect.py", "codecs/vyos/parse.py", "_tier3_detection.py",
                       "deployment_detect.py", "canonical/transforms.py"):
            assert f"netcanon/migration/{module}" in read, module
        assert len(read) > 90

    def test_the_rule_can_fail(self) -> None:
        """Each kind of loop it is for, unticked, is reported; ticked,
        it is not."""
        looping = {
            "for line in raw.splitlines():\n        use(line)":
                "for line in ticked(raw.splitlines()):\n        use(line)",
            "for n, line in enumerate(raw.splitlines()):\n        use(line)":
                "for n, line in ticked(enumerate(raw.splitlines())):\n        use(line)",
            "rows = raw.splitlines()\n    for line in rows:\n        use(line)":
                "rows = raw.splitlines()\n    for line in ticked(rows):\n        use(line)",
            "for line in lines:\n        use(line)": "for line in ticked(lines):\n        use(line)",
            "i = 0\n    while i < len(lines):\n        i += 1":
                "i = 0\n    while i < len(lines):\n        tick()\n        i += 1",
            "n = len(lines)\n    i = 0\n    while i < n:\n        i += 1":
                "n = len(lines)\n    i = 0\n    while i < n:\n        tick()\n        i += 1",
            "return [use(line) for line in raw.splitlines()]":
                "return [use(line) for line in ticked(raw.splitlines())]",
        }
        for unticked, ticked in looping.items():
            assert _loops_that_do_not_look(f"def parse(raw, lines):\n    {unticked}\n", "x.py"), unticked
            assert not _loops_that_do_not_look(f"def parse(raw, lines):\n    {ticked}\n", "x.py"), ticked

    def test_every_run_of_entries_has_its_answer(self) -> None:
        """A new ``range(...)`` in a parser or a renderer, or a new
        slice of the shared ids, fails here until someone has said
        what bounds it."""
        found = _runs_of_entries()
        assert set(found) == set(RUNS_OF_ENTRIES), (
            f"not in the table: {sorted(set(found) - set(RUNS_OF_ENTRIES))}; "
            f"in the table and gone: {sorted(set(RUNS_OF_ENTRIES) - set(found))}"
        )
        uncounted = [key for key, answer in RUNS_OF_ENTRIES.items() if answer == "charged" and not found[key]]
        assert not uncounted, f"said to be charged, in a function that counts nothing: {uncounted}"
        assert sum(1 for answer in RUNS_OF_ENTRIES.values() if answer == "charged") >= 8

    def test_no_broad_handler_swallows_a_refusal(self) -> None:
        files = [
            path for root in _ROOTS_OF_BROAD_HANDLERS
            for path in ([root] if root.is_file() else sorted(root.rglob("*.py")))
        ]
        assert len(files) > 90
        offenders = [
            where for path in files
            for where in _broad_handlers_that_could_swallow(path.read_text(encoding="utf-8"), _rel(path))
        ]
        assert not offenders, "a broad handler with no `except LimitExceeded` before it: " + ", ".join(offenders)

    def test_the_handler_rule_can_fail(self) -> None:
        swallowing = "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"
        named = (
            "def f():\n    try:\n        g()\n    except LimitExceeded:\n        raise\n"
            "    except Exception:\n        pass\n"
        )
        both = "def f():\n    try:\n        g()\n    except (ValueError, Exception):\n        pass\n"
        bare = "def f():\n    try:\n        g()\n    except:\n        pass\n"
        narrow = "def f():\n    try:\n        g()\n    except ValueError:\n        pass\n"
        assert _broad_handlers_that_could_swallow(swallowing, "x.py") == ["x.py:4 in f"]
        assert _broad_handlers_that_could_swallow(both, "x.py") and _broad_handlers_that_could_swallow(bare, "x.py")
        assert not _broad_handlers_that_could_swallow(named, "x.py")
        assert not _broad_handlers_that_could_swallow(narrow, "x.py")
