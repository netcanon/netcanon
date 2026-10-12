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

* **the mechanism**: counting, the deadline, the words of a refusal,
  the turn a request to a server waits for where the limits say
  how many work at once, and the place it is given when it arrives;
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
import contextvars
import copy
import random
import sys
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
from netcanon.migration.codecs._helpers import (
    TRUNK_ALL,
    TRUNK_THAT_STATES_NO_LIST,
    joined_ids_length,
    unstated_trunk_list,
)
from netcanon.migration.codecs.juniper_junos import parse as junos_parse
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


#: codec -> (a trunk that states no allowed list, a declared VLAN), as
#: that platform writes them.  On each of these such a trunk carries
#: every VLAN.
DEFAULT_TRUNK: dict[str, tuple[str, str]] = {
    "cisco_iosxe_cli": ("interface GigabitEthernet1/0/{n}\n switchport mode trunk\n!\n",
                        "vlan {vid}\n name V{vid}\n!\n"),
    "cisco_nxos": ("interface Ethernet{slot}/{port}\n  switchport\n  switchport mode trunk\n",
                   "vlan {vid}\n  name V{vid}\n"),
    "arista_eos": ("interface Ethernet{n}\n   switchport mode trunk\n!\n", "vlan {vid}\n   name V{vid}\n!\n"),
    "aruba_aoscx": ("interface 1/1/{n}\n    no routing\n    vlan trunk native 1\n",
                    "vlan {vid}\n    name V{vid}\n"),
}


def default_trunks(codec: str, count: int, declared: int = 0) -> str:
    """*count* trunks of *codec* that state no allowed list, and
    *declared* VLANs: some 55 bytes a trunk."""
    trunk, vlan = DEFAULT_TRUNK[codec]
    return "hostname T\n" + "".join(vlan.format(vid=vid) for vid in range(2, 2 + declared)) + "".join(
        trunk.format(n=n, slot=(n - 1) // 48 + 1, port=(n - 1) % 48 + 1) for n in range(1, count + 1)
    )


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

    @pytest.mark.parametrize("kind", list(L.KINDS))
    def test_on_the_command_line_small_names_the_option(self, kind: str) -> None:
        """There is no server at a command line, and whoever is there
        chose the limits: the sentence says what the run used and
        the option that allows more, with the default's number."""
        said = str(_refusal(L.SMALL, kind, surface="cli"))
        assert "This run used the 'small' config size limit, the one the public demo uses." in said
        allowed = f"{int(getattr(L.STANDARD, kind)):,}" + (" seconds" if kind == "seconds" else "")
        assert f"The default, 'standard', allows {allowed}: pass --limits standard." in said
        for word in ("server", "NETCANON_", "environment", "Preferences", "restart", "you run yourself"):
            assert word not in said, said

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
        # No allowed line at all: every VLAN, on this platform and the three below.
        "interface Gi1/0/{n}\n switchport mode trunk\n!\n",
        "interface Gi1/0/{n}\n switchport mode trunk\n switchport trunk allowed vlan remove 7\n!\n",
    ],
    "cisco_nxos": [
        "interface Ethernet1/{n}\n  switchport\n  switchport mode trunk\n  switchport trunk allowed vlan 1-4093\n",
        "vlan 1-4094\n",
        "interface Ethernet1/{n}\n  switchport\n  switchport mode trunk\n",
    ],
    "arista_eos": [
        "interface Ethernet{n}\n   switchport mode trunk\n   switchport trunk allowed vlan 2-4000\n!\n",
        "interface Ethernet{n}\n   switchport mode trunk\n   switchport trunk allowed vlan all\n!\n",
        "interface Ethernet{n}\n   switchport mode trunk\n!\n",
    ],
    "dell_os10": [
        "interface ethernet1/1/{n}\n switchport mode trunk\n switchport trunk allowed vlan 2-4000\n!\n",
    ],
    "aruba_aoscx": [
        "interface 1/1/{n}\n    no routing\n    vlan trunk native 1\n    vlan trunk allowed 2-4000\n",
        "interface 1/1/{n}\n    no routing\n    vlan trunk native 1\n    vlan trunk allowed all\n",
        "interface 1/1/{n}\n    no routing\n    vlan trunk native 1\n",
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
        """One port of each is under a limit of every VLAN there is,
        once: the text is the parser's own grammar, and is read.  A
        parser that reads a list twice and counts both is refused
        here (NX-OS did, for a ``vlan`` line of ranges)."""
        with L.limits_scope(replace(TINY, vlan_ids=4_094)):
            tree = get_codec(codec).parse(_wide(codec, stanza, ports=1))
        made = sum(len(port.trunk_allowed_vlans) for port in tree.interfaces) + len(tree.vlans)
        assert made >= 1

    def test_the_number_a_refusal_prints_is_the_count(self) -> None:
        """``vlan 2-2502`` names 2,501 ids.  Two passes of the NX-OS
        parser read that line, and both expanded it: it was charged
        as 5,002 ids "over 2 lists", so a limit refused half of what
        it says it allows and a refusal printed twice the count."""
        exact = replace(TINY, vlan_ids=2_501)
        with L.limits_scope(exact):
            assert len(get_codec("cisco_nxos").parse("hostname T\nvlan 2-2502\n").vlans) == 2_501
        exc = _refused("cisco_nxos", "hostname T\nvlan 2-2503\n", exact)
        assert (exc.kind, exc.asked, exc.cap, exc.lists, exc.exact) == ("vlan_ids", 2_502, 2_501, 1, False)
        assert str(exc).startswith(
            "reading the config as cisco_nxos would make 2,502 or more VLAN ids that the config's lists "
            "and ranges name; the limit is 2,501 (at: 2-2503)."
        )
        # What is charged for one line is what the line names.
        text = "hostname T\nvlan 2-2502\nvlan 3000\n  vn-segment 13000\nvlan 3001-3001\n  vn-segment 13001\n"
        with L.limits_scope(UNCOUNTED):
            trees: list[CanonicalIntent] = []
            charged = _charges("vlan_ids", lambda: trees.append(get_codec("cisco_nxos").parse(text)))
        assert charged == [2_501, 1]
        # ...and the pass that no longer expands still finds the stanza of one VLAN.
        assert sorted((v.vlan_id, v.vni) for v in trees[0].vxlan_vnis) == [(3000, 13000), (3001, 13001)]

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

    def test_a_words_refusal_quotes_no_value(self) -> None:
        """The sentence says where the statement is and nothing a
        statement holds.  It quoted the last four words: a hash, and
        the community string its block is keyed by -- in a sentence
        an operator is asked to paste into a bug report."""
        leaves = "".join(
            f'        encrypted-password "$6$fake$notARealHash{n}";\n' for n in range(400)
        )
        lists = "".join(
            f"        clients{n} [ 192.0.2.{n % 250} 198.51.100.{n % 250} ];\n" for n in range(400)
        )
        for body in (leaves, lists):
            text = (
                "system {\n    host-name T;\n}\nsnmp {\n    community fakeCommunity {\n" + body + "    }\n}\n"
            )
            exc = _refused("juniper_junos", text, TINY)
            assert exc.kind == "words"
            # The place is the section, and stops at the word that names
            # a secret: the string the block is keyed by is not shown.
            assert exc.where.startswith("snmp community") and "fakeCommunity" not in exc.where
            job = _plan("juniper_junos", "arista_eos", text, TINY)
            said = str(exc) + (job.error or "") + str(job.refusal)
            assert "snmp community" in str(exc)
            for held in ("fakeCommunity", "notARealHash", "192.0.2.", "encrypted-password", "clients"):
                assert held not in said, held

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


class TestATrunkThatStatesNoList:
    """On IOS-XE, NX-OS, EOS and AOS-CX a trunk with no allowed line
    carries every VLAN, and the tree says so with the 4,094 ids: a
    stanza of two lines makes them.  It is counted as the word
    ``all`` is -- before the list is made -- wherever such a list is
    made: for the trunk itself, for the ``add`` or ``remove`` that
    starts from it, and for the record of a stanza that is met again.
    The count of the finished tree would refuse these texts too, when
    the memory was already spent."""

    def test_these_are_the_platforms_it_is_true_of(self) -> None:
        every = {codec for codec, says in TRUNK_THAT_STATES_NO_LIST.items() if says == TRUNK_ALL}
        assert set(DEFAULT_TRUNK) == every
        for codec in set(TRUNK_THAT_STATES_NO_LIST) - every:
            with L.limits_scope(UNCOUNTED):
                assert _charges("vlan_ids", lambda codec=codec: unstated_trunk_list(codec, "x")) == []

    @pytest.mark.parametrize("codec", sorted(DEFAULT_TRUNK))
    def test_each_is_counted_as_every_vlan_once(self, codec: str) -> None:
        with L.limits_scope(UNCOUNTED):
            trees: list[CanonicalIntent] = []
            charged = _charges("vlan_ids", lambda: trees.append(get_codec(codec).parse(default_trunks(codec, 3))))
        assert charged == [4094, 4094, 4094]
        assert [len(port.trunk_allowed_vlans) for port in trees[0].interfaces] == [4094, 4094, 4094]

    @pytest.mark.parametrize("codec", sorted(DEFAULT_TRUNK))
    def test_the_number_a_refusal_prints_is_the_count(self, codec: str) -> None:
        """Five such trunks are 20,470 ids and are read under a limit
        of exactly that; the sixth is refused, for six times 4,094,
        counted over six -- and before its list was made."""
        exact = replace(TINY, vlan_ids=5 * 4094)
        with L.limits_scope(exact):
            tree = get_codec(codec).parse(default_trunks(codec, 5))
        assert sum(len(port.trunk_allowed_vlans) for port in tree.interfaces) == 5 * 4094
        exc = _refused(codec, default_trunks(codec, 6), exact)
        assert (exc.kind, exc.asked, exc.cap, exc.lists, exc.exact) == ("vlan_ids", 6 * 4094, 5 * 4094, 6, False)
        assert str(exc).startswith(
            f"reading the config as {codec} would make 24,564 or more VLAN ids that the config's lists and "
            "ranges name; the limit is 20,470 (counted over 6 lists and ranges; the last one read: a trunk "
            "with no allowed list, which is every VLAN: "
        )

    @pytest.mark.parametrize("codec", sorted(DEFAULT_TRUNK))
    def test_many_are_refused_before_their_lists_are_made(self, codec: str) -> None:
        """Two thousand default trunks are some 110 KB of text and 65
        MB of lists.  Under the demo's limits the 257th is refused:
        what is held on the way is the 2,000 interfaces and 256
        lists, a fifth of what making them all holds."""
        text = default_trunks(codec, 2_000)
        assert len(text) < 130_000
        jobs: list = []
        held = _peak(lambda: jobs.append(_plan(codec, "juniper_junos", text, "small")))
        job = jobs[0]
        assert job.status.value == "failed" and job.rendered is None and job.validation is None
        assert job.refusal is not None, job.error
        assert (job.refusal.limit, job.refusal.exact, job.refusal.profile) == ("vlan_ids", False, "small")
        assert (job.refusal.asked, job.refusal.cap) == (257 * 4094, L.SMALL.vlan_ids)
        assert job.error.startswith(
            f"refused: reading the config as {codec} would make 1,052,158 or more VLAN ids that the "
            "config's lists and ranges name; the limit is 1,048,576 (counted over 257 lists and ranges; "
            "the last one read: a trunk with no allowed list, which is every VLAN: "
        )
        assert "the one the public demo uses" in job.error
        assert held < 20_000_000, f"{held:,} bytes were held on the way to the refusal"
        with L.limits_scope(UNCOUNTED):
            made = _peak(lambda: get_codec(codec).parse(text))
        assert made > 50_000_000, "making every list was expected to hold tens of megabytes"

    @pytest.mark.parametrize("codec", sorted(DEFAULT_TRUNK))
    def test_a_thousand_translate_under_standard(self, codec: str) -> None:
        """A thousand default trunks are four million ids, a quarter
        of what ``standard`` allows: read, and written as each target
        writes every VLAN, exactly as with no limit at all."""
        text = default_trunks(codec, 1_000, declared=10)
        for target in (codec, "juniper_junos", "arista_eos"):
            limited, free = _plan(codec, target, text, "standard"), _plan(codec, target, text, L.UNLIMITED)
            assert limited.refusal is None and free.refusal is None, limited.error
            assert limited.status == free.status and limited.status.value != "failed", limited.error
            assert limited.rendered == free.rendered and limited.warnings == free.warnings
        junos = _plan(codec, "juniper_junos", text, "standard").rendered
        assert junos.count(" vlan members all\n") == 1_000
        # ...and how many the two shipped sets take is what the documents say.
        assert L.SMALL.vlan_ids // 4094 == 256 and L.STANDARD.vlan_ids // 4094 == 4_098

    def test_a_first_add_or_remove_starts_from_every_vlan(self) -> None:
        """``remove 10`` on a trunk with no earlier line is every VLAN
        but 10: the 4,094 it starts from are a copy of the platform's
        list, made from one short line.  The ids the line itself names
        are read once, though two lists are made of them."""
        stanza = (
            "hostname T\ninterface GigabitEthernet1/0/1\n switchport mode trunk\n"
            " switchport trunk allowed vlan {}\n!\n"
        )
        trees: list[CanonicalIntent] = []

        def read(line: str) -> None:
            trees.append(get_codec("cisco_iosxe_cli").parse(stanza.format(line)))

        for line, charged, held in (("remove 10", [4094], 4093), ("add 30", [4094], 4094),
                                    ("add 100-3000", [2901, 4094], 4094), ("remove 100-3000", [2901, 4094], 1193)):
            with L.limits_scope(UNCOUNTED):
                seen = _charges("vlan_ids", lambda line=line: read(line))
            assert seen == charged, line
            assert [len(port.trunk_allowed_vlans) for port in trees[-1].interfaces] == [held], line
        exc = _refused("cisco_iosxe_cli", stanza.format("remove 10"), replace(TINY, vlan_ids=4_000))
        assert (exc.kind, exc.asked, exc.exact) == ("vlan_ids", 4094, False)
        assert "(at: remove on a trunk with no earlier list, which starts from every VLAN)" in str(exc)
        # Where a trunk carries no VLAN until one is named, nothing is started from.
        os10 = "hostname T\ninterface ethernet1/1/1\n switchport mode trunk\n switchport trunk allowed vlan add 30\n!\n"
        with L.limits_scope(UNCOUNTED):
            assert _charges("vlan_ids", lambda: get_codec("dell_os10").parse(os10)) == []

    @pytest.mark.parametrize(("again", "each", "said"), [
        (" switchport mode trunk\n", "a copy for the record of the stanza", "GigabitEthernet1/0/1"),
        (" switchport trunk allowed vlan add 5\n", "the list the line starts from", "add 5"),
        (" switchport mode trunk\n switchport trunk allowed vlan remove 7\n", "the list the line starts from",
         "remove 7"),
    ])
    def test_a_stanza_met_again_is_counted_again(self, again: str, each: str, said: str) -> None:
        """A parser that makes a record a stanza gives each record a
        list of its own.  The stanza of a trunk of every VLAN, met
        again with two short lines, is 4,094 ids more each time."""
        first = "interface GigabitEthernet1/0/1\n switchport mode trunk\n switchport trunk allowed vlan 1-4094\n!\n"
        text = "hostname T\n" + first + ("interface GigabitEthernet1/0/1\n" + again + "!\n") * 4
        with L.limits_scope(UNCOUNTED):
            trees: list[CanonicalIntent] = []
            charged = _charges("vlan_ids", lambda: trees.append(get_codec("cisco_iosxe_cli").parse(text)))
        lists = [port.trunk_allowed_vlans for port in trees[0].interfaces]
        assert len(lists) == 5 and len({id(ids) for ids in lists}) == 5, each
        assert sum(charged) >= sum(len(ids) for ids in lists) > 4 * 4000, each
        assert len(charged) == 5 and charged[0] == 4094
        exc = _refused("cisco_iosxe_cli", text, TINY)
        assert (exc.kind, exc.exact, exc.lists) == ("vlan_ids", False, 2)
        assert f"the last one read: the allowed list of a stanza that is met again: {said})" in str(exc)

    def test_one_record_a_name_copies_nothing(self) -> None:
        """EOS keeps one record a name: its stanza met again adds to
        the one list, and nothing is counted but what the lines name."""
        text = (
            "hostname T\ninterface Ethernet1\n   switchport mode trunk\n   switchport trunk allowed vlan 1-4094\n!\n"
            + "interface Ethernet1\n   switchport trunk allowed vlan remove 7\n!\n" * 4
        )
        with L.limits_scope(UNCOUNTED):
            trees: list[CanonicalIntent] = []
            charged = _charges("vlan_ids", lambda: trees.append(get_codec("arista_eos").parse(text)))
        assert charged == [4094]
        assert [len(port.trunk_allowed_vlans) for port in trees[0].interfaces] == [4093]

    def test_aoscx_says_all_in_a_word(self) -> None:
        text = "hostname T\n" + "".join(
            f"interface 1/1/{n}\n    no routing\n    vlan trunk native 1\n    vlan trunk allowed all\n" for n in (1, 2)
        )
        with L.limits_scope(UNCOUNTED):
            assert _charges("vlan_ids", lambda: get_codec("aruba_aoscx").parse(text)) == [4094, 4094]
        exc = _refused("aruba_aoscx", text, TINY)
        assert (exc.kind, exc.asked, exc.exact) == ("vlan_ids", 2 * 4094, False)
        assert "the last one read: vlan trunk allowed all)" in str(exc)


#: Hierarchical Junos with every kind of statement the converter writes
#: a set command for: a leaf, one that is not in force, a tagged one, a
#: block that is not in force, an empty block, a block whose content is
#: not shown, and a bracketed list that is not in force.
_JUNOS_AS_PRINTED = (
    "system {\n    host-name T;\n}\n"
    "w0 w1 w2 {\n"
    "    inactive: leaf0 v0;\n"
    "    leaf1 v1;\n"
    "    empty-block {\n    }\n"
    "    protect: leaf2 v2;\n"
    "    inactive: sub {\n        leaf3 v3;\n    }\n"
    "    family inet { ... }\n"
    "    inactive: key [ a b c ];\n"
    "}\n"
)


class TestJunosAsPrinted:
    """A hierarchical Junos config is walked into tokens and written out
    as set commands.  The walk looks at the deadline, and every command
    written is counted in words before it is written -- the
    ``deactivate`` line of a statement that is not in force and the
    line that stands for an empty block with the rest."""

    def test_what_is_counted_is_what_is_then_written(self) -> None:
        charged: list[int] = []
        lines: list[str] = []
        with L.limits_scope(UNCOUNTED), L.metered("parse", "juniper_junos"):
            charged += _charges("words", lambda: lines.extend(junos_parse._blockform_convert(_JUNOS_AS_PRINTED)[0]))
        assert [line.split()[0] for line in lines].count("deactivate") == 3
        assert "set w0 w1 w2 empty-block" in lines and "set w0 w1 w2 family inet" in lines
        # A command's words are its path and its value: not the verb.
        assert sum(charged) == sum(len(line.split()) - 1 for line in lines) == 61
        assert len(charged) == len(lines) - 2  # the three values of the list are one count

    def test_statements_not_in_force_are_counted_too(self) -> None:
        """Thirty statements marked ``inactive:`` under a path of a
        hundred words are thirty ``deactivate`` lines and thirty set
        lines, each with the whole path: refused before they are
        written, as the same statements in force are."""
        path = " ".join(f"w{n}" for n in range(100))
        text = "system {\n    host-name T;\n}\n" + path + " {\n" + "".join(
            f"    inactive: leaf{n} v{n};\n" for n in range(30)
        ) + "}\n"
        with L.limits_scope(UNCOUNTED):
            charged = _charges("words", lambda: get_codec("juniper_junos").parse(text))
        assert charged == [3] + [102] * 60
        exc = _refused("juniper_junos", text, TINY)
        assert (exc.kind, exc.exact, exc.stage) == ("words", False, "parse")
        assert exc.asked == 3 + 20 * 102 and exc.asked > TINY.words
        # Stopped at a ``deactivate`` line, the statement is quoted by its
        # name: what follows a leaf's first word is a value.
        exc = _refused("juniper_junos", text, replace(TINY, words=3 + 18 * 102))
        assert (exc.kind, exc.exact, exc.asked) == ("words", False, 3 + 19 * 102)
        assert "(counted over 20 statements; the last one read: w97 w98 w99 leaf9)" in str(exc)
        empty = "system {\n    host-name T;\n}\n" + "".join(path + f" b{n} {{\n}}\n" for n in range(30))
        exc = _refused("juniper_junos", empty, TINY)
        assert (exc.kind, exc.exact, exc.asked) == ("words", False, 3 + 20 * 101)

    @pytest.mark.parametrize("statement", [
        "encrypted-password \"$6$fake$hash\";",
        "inactive: encrypted-password \"$6$fake$hash\";",
        "ssh-rsa \"ssh-rsa AAAAfakekey\";",
        "key [ fakekey1 fakekey2 ];",
    ])
    def test_a_refusal_quotes_a_name_and_no_value(self, statement: str) -> None:
        """The sentence of a refusal is shown, and pasted into a bug
        report.  Stopped at a statement that holds a secret, it
        names the statement: no word of its value, and no word
        after one that names a secret."""
        text = (
            "system {\n    host-name T;\n    login {\n        user alice {\n"
            "            authentication {\n                " + statement + "\n"
            "            }\n        }\n    }\n}\n"
        )
        exc = _refused("juniper_junos", text, replace(TINY, words=3))
        assert (exc.kind, exc.exact) == ("words", False)
        assert "(counted over 2 statements; the last one read: login user alice authentication)" in str(exc)
        assert "fake" not in str(exc) and "fake" not in str(exc.as_dict())
        # Where no word names a secret, a leaf is quoted by its first word.
        exc = _refused("juniper_junos", "system {\n    host-name secret-value;\n}\n", replace(TINY, words=2))
        assert "(at: system host-name)" in str(exc)
        # ...and a bracketed list by the word ahead of the bracket.
        listed = "system {\n    name-server [ 192.0.2.53 192.0.2.54 ];\n}\n"
        exc = _refused("juniper_junos", listed, replace(TINY, words=2))
        assert exc.asked == 6 and "(at: system name-server)" in str(exc)

    def test_every_token_goes_past_the_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No loop over lines reads this form: the text is walked a
        character at a time into tokens, by the judge of its form and
        by the converter.  Each token of both walks is a step that
        looks."""
        steps = [0]
        real = L._ticking

        def counting(items, clock):
            for item in real(items, clock):
                steps[0] += 1
                yield item

        monkeypatch.setattr(L, "_ticking", counting)
        text = "version 21.4R3.15;\n" * 300 + junos_blocks(3, 400)
        with L.limits_scope(UNCOUNTED), L.metered("parse", "juniper_junos"):
            assert junos_parse._looks_like_blockform(text)
            judged = steps[0]
            tokens = junos_parse._tokenise_blockform(text)
        # The form is judged on the 300 statements ahead of the first
        # block: three tokens and the end of a line, each.
        assert judged >= 300 * 4
        assert steps[0] - judged == len(tokens) > 2_000

    def test_the_walk_stops_at_the_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = "version 21.4R3.15;\n" * 300 + junos_blocks(3, 400)
        for walk in (junos_parse._looks_like_blockform, junos_parse._tokenise_blockform):
            monkeypatch.setattr(L, "time", _Clock())
            with L.limits_scope(replace(L.UNLIMITED, name="brief", seconds=10.0)), \
                    L.metered("parse", "juniper_junos"), pytest.raises(L.LimitExceeded) as caught:
                walk(text)
            assert (caught.value.kind, caught.value.stage) == ("seconds", "parse"), walk.__name__


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
        # A list means what it says: a trunk of every VLAN is no line, a
        # trunk of no VLAN the word for it, and on a port that is not a
        # trunk IOS-XE writes every id as its word.
        texts += [
            ("every", "cisco_iosxe_cli", default_trunks("cisco_iosxe_cli", 7)),
            ("none", "juniper_junos", "set system host-name T\n" + "".join(
                f"set interfaces xe-0/0/{n} unit 0 family ethernet-switching interface-mode trunk\n" for n in range(5)
            )),
            ("not a trunk", "cisco_iosxe_cli", "hostname T\n" + "".join(
                f"interface Gi1/0/{n}\n switchport mode access\n switchport trunk allowed vlan {ids}\n!\n"
                for n, ids in enumerate(("all", "10,20", "none"))
            )),
        ]
        words: dict[str, list[str]] = {}
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
            words[label] = [line[len(_ID_LINE[target]):] for line in lines]
        assert seen_lists > 100, "the captures held too few lists for this to mean anything"
        # The built texts wrote what they were built to write.
        assert words["every"] == [] and words["none"] == ["none"] * 5
        assert words["not a trunk"] == (["all", "10,20"] if target == "cisco_iosxe_cli" else [])

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
    ("_helpers.py", "<module>", "VLAN_IDS[1:]"):
        "every VLAN id as one tuple, made once; a list copied from it is counted where it is copied",
    ("_helpers.py", "_entry", "range(entry[2], len(items))"): "walks a list that exists",
    ("_helpers.py", "vlan_id_run", "VLAN_IDS[low:high + 1]"):
        "the expander every caller of it is in this table for",
    ("_helpers.py", "_normalise_mac_to_colon_hex", "range(0, 12, 2)"): "six",
    ("_helpers.py", "_parse_vlan_list", "VLAN_IDS[lo_i:hi_i + 1]"): "charged",
    ("_helpers.py", "unstated_trunk_list", "vlan_id_run(1, 4094)"): "charged",
    ("_helpers.py", "merge_trunk_allowed", "vlan_id_run(1, 4094)"): "charged",
    ("_helpers.py", "merge_trunk_allowed", "VLAN_IDS[1:]"): "charged",
    ("arista_eos/parse.py", "_expand_vlan_list", "VLAN_IDS[a_i:b_i + 1]"): "charged",
    ("aruba_aoscx/parse.py", "_on_line", "vlan_id_run(1, 4094)"): "charged",
    ("aruba_aoss/parse.py", "_expand_port_range", "range(num_lo, num_hi + 1)"): "charged",
    ("fortigate_cli/parse.py", "_apply_system_dhcp_server", "range(1, 4)"): "three",
    ("juniper_junos/parse.py", "_resolve_vlan_member_to_vids", "vlan_id_run(lo, hi)"): "charged",
    ("juniper_junos/parse.py", "read_intent", "vlan_id_run(1, 4094)"): "charged",
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
    ("netcanon/services/migration_pipeline.py", "_the_targets_own"):
        "wraps one classifier call and one formatter call on one name",
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
        assert sum(1 for answer in RUNS_OF_ENTRIES.values() if answer == "charged") >= 10

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


# ---------------------------------------------------------------------------
# 12. Requests at once
# ---------------------------------------------------------------------------


def _until(condition: Callable[[], bool], what: str, seconds: float = 10.0) -> None:
    """Wait for *condition*, which another thread is on its way to
    making true.  The time is how long a FAILURE takes to be reported;
    a test that passes waits for the condition and no longer."""
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.002)


class _Hands:
    """Stands in for ``time`` in the limits module: the time is what
    the test last set it to."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


#: The helper requests a test made, and what lets each of them go.
_MADE: list[tuple[threading.Thread, Callable[[], None]]] = []


@pytest.fixture(autouse=True)
def _one_failure_is_one_failure():
    """Let go of every helper request a test left behind.  A test
    that fails part-way leaves one inside its scope, holding the
    process's turn for as long as it waits to be let go -- and every
    test after it in the process then fails for that, and not for
    anything of its own."""
    yield
    made = _MADE[:]
    del _MADE[:]
    for _thread, let_go in made:
        let_go()
    for thread, _let_go in made:
        if thread.is_alive():
            thread.join(10)


class _Request(threading.Thread):
    """One request to a server under *limits*, on a thread of its own
    as a handler is: it opens the server's scope, says that it is
    inside, and works until it is let go."""

    def __init__(self, limits: L.Limits | str | None, entered: list[_Request] | None = None) -> None:
        super().__init__(daemon=True)
        self.limits, self.entered = limits, entered
        self.inside, self.let_go = threading.Event(), threading.Event()
        _MADE.append((self, self.let_go.set))
        self.refused: L.LimitExceeded | None = None
        self.deadline: float | None = None

    def run(self) -> None:
        try:
            with L.server_scope(self.limits):
                scope = L._SCOPE.get()
                self.deadline = scope.deadline if scope is not None else None
                if self.entered is not None:
                    self.entered.append(self)
                self.inside.set()
                self.let_go.wait(30)
        except L.LimitExceeded as exc:
            self.refused = exc

    def working(self) -> _Request:
        """Start it, and come back when it is inside its scope."""
        self.start()
        assert self.inside.wait(10), "the request never got its turn"
        return self

    def finish(self) -> None:
        self.let_go.set()
        self.join(10)
        assert not self.is_alive()


class _WokenByTheTest:
    """Stands in for the condition a ``_Turns`` waits on: a waiter
    sleeps until the TEST wakes it, by its thread's name, and a call
    to ``notify_all`` is only counted.  With it a test chooses which
    of two waiters looks first."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.asleep: dict[str, threading.Event] = {}
        self.told = 0

    def __enter__(self) -> _WokenByTheTest:
        self._lock.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self._lock.release()

    def wait(self, timeout: float | None = None) -> bool:
        gate = threading.Event()
        self.asleep[threading.current_thread().name] = gate
        self._lock.release()
        try:
            gate.wait(30)
        finally:
            self._lock.acquire()
        return True

    def notify_all(self) -> None:
        self.told += 1

    def wake(self, name: str) -> None:
        self.asleep.pop(name).set()


_BUSY = (
    "the server works on one config at a time, and was busy with another for the 20 seconds this request may "
    "take; this request was not started and its config was not read.  Send it again.  This server runs with "
    "the 'small' config size limit, the one the public demo uses.  A Netcanon you run yourself does not make "
    "one request wait for another by default."
)


class TestRequestsAtOnce:
    """Every limit is for one request, and requests at once add up.
    Under ``small`` a server works on ONE request that reads config
    text at a time: the others wait their turn, inside their own
    deadline."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0)
        yield
        assert L.in_flight() == (0, 0), "a turn was not given back, or a request is still in the line"

    def test_only_small_says_one_at_a_time(self) -> None:
        assert {name: limits.at_once for name, limits in L.PROFILES.items()} == {
            "small": 1, "standard": None, "large": None, "unlimited": None,
        }
        assert L.describe(L.SMALL).endswith(", seconds 20, at_once 1)")
        assert L.describe(L.STANDARD).endswith(", seconds 120, at_once none)")
        # Not something a stage counts: no meter ever charges it.
        assert L.AT_ONCE == "at_once" and L.AT_ONCE not in L.KINDS

    def test_a_limit_at_once_needs_a_deadline(self) -> None:
        """A request waits for its turn inside its deadline.  Limits
        with a line and no deadline could keep one waiting for ever,
        and cannot be made."""
        with pytest.raises(ValueError, match="need seconds"):
            replace(L.SMALL, seconds=None)
        with pytest.raises(ValueError, match="1 or more"):
            replace(L.SMALL, at_once=0)
        assert replace(L.UNLIMITED, name="free").at_once is None

    def test_the_second_waits_and_then_runs(self) -> None:
        """Shown with an event the first request holds: while it is
        inside, the second is in the line and not inside; when the
        first leaves, the second runs."""
        first = _Request("small").working()
        second = _Request("small")
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        assert not second.inside.is_set(), "two requests were at work at once"
        first.finish()
        assert second.inside.wait(10), "the second request never got its turn"
        assert L.in_flight() == (1, 0)
        second.finish()
        assert first.refused is None and second.refused is None

    def test_the_wait_is_time_the_request_has_spent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One deadline a request, counted from when it arrived.  A
        request that stood twelve seconds in the line has eight left
        to work in, and not twenty."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        first = _Request("small").working()
        clock.now = 1_005.0
        second = _Request("small")
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        clock.now = 1_017.0
        first.finish()
        assert second.inside.wait(10)
        assert second.deadline == 1_005.0 + L.SMALL.seconds
        second.finish()

    def test_out_of_time_in_the_line_is_refused_in_words(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A refusal like any other -- with a sentence that says the
        server was busy and to send the same thing again, and that
        does not call the config large or unreadable."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        first = _Request("small").working()
        second = _Request("small")
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        clock.now += L.SMALL.seconds + 0.5
        with L._TURNS._changed:  # a request in the line looks at the clock when it is woken
            L._TURNS._changed.notify_all()
        second.join(10)
        assert not second.is_alive() and not second.inside.is_set()
        exc = second.refused
        assert exc is not None
        assert (exc.kind, exc.asked, exc.cap, exc.exact, exc.profile, exc.waited, exc.stage, exc.codec) == (
            "at_once", 2, 1, True, "small", 20.0, "", "",
        )
        assert str(exc) == _BUSY
        for word in ("parse failed", "would make", "the limit is", "NETCANON_", "environment", "Preferences"):
            assert word not in str(exc), word
        refusal = Refusal(**exc.as_dict())
        assert (refusal.limit, refusal.asked, refusal.cap, refusal.exact, refusal.profile) == (
            "at_once", 2, 1, True, "small",
        )
        assert refusal.what == "requests that read config text, at work at once"
        assert refusal.how_to_raise == exc.hint and _BUSY.endswith(exc.hint)
        # The one who gave up holds nothing, and the one at work was not disturbed.
        assert L.in_flight() == (1, 0)
        first.finish()

    def test_a_request_in_the_line_gives_up_by_itself(self) -> None:
        """No one has to wake it: with nothing changing, a request
        whose time passes in the line is refused when it passes."""
        first = _Request("small").working()
        began = time.monotonic()
        with pytest.raises(L.LimitExceeded) as caught, L.server_scope(replace(L.SMALL, seconds=0.2)):
            raise AssertionError("a second request got in while the first was at work")
        waited = time.monotonic() - began
        assert caught.value.kind == "at_once" and caught.value.waited == 0.2
        assert 0.15 < waited < 5.0, waited
        assert "was busy with another for the 0.2 seconds this request may take" in str(caught.value)
        first.finish()

    def test_whoever_leaves_the_line_tells_the_next(self) -> None:
        """Where two may work at once -- no set that ships says so,
        and a set may -- two places can come free together.  The
        second in the line looks first, finds that it is not first,
        and sleeps again; the first takes ONE place and leaves the
        line.  The second is first now, with a place free, and
        nothing else would wake it before its deadline: whoever
        leaves the line has to.  (With one at work the place that
        came free is taken by whoever leaves the line, so there is
        nothing for the next to be told.)"""
        two = replace(L.SMALL, at_once=2, seconds=30.0)
        turns, told = L._Turns(), _WokenByTheTest()
        turns._changed = told  # type: ignore[assignment]
        far = time.monotonic() + 30.0
        at_work = [turns.take(two, far), turns.take(two, far)]
        got: dict[str, object] = {}

        def ask(name: str) -> None:
            got[name] = turns.take(two, far)

        waiters: dict[str, threading.Thread] = {}
        for name in ("first", "second"):
            waiters[name] = threading.Thread(target=ask, args=(name,), name=name, daemon=True)
            waiters[name].start()
            _until(lambda name=name: name in told.asleep, f"the {name} request asleep in the line")
        assert (turns.working, turns.waiting) == (2, 2)
        for held in at_work:
            assert held is not None
            turns.done(held, None)
        assert turns.working == 0
        told.wake("second")
        _until(lambda: "second" in told.asleep, "the second request asleep again: it is not first")
        assert "second" not in got
        before = told.told
        told.wake("first")
        waiters["first"].join(10)
        assert "first" in got and (turns.working, turns.waiting) == (1, 1)
        assert told.told > before, "the first left the line and told nobody: the second sleeps on, a place free"
        told.wake("second")
        waiters["second"].join(10)
        assert "second" in got and (turns.working, turns.waiting) == (2, 0)

    def test_the_turn_is_given_back_on_every_way_out(self) -> None:
        with pytest.raises(RuntimeError), L.server_scope("small"):
            raise RuntimeError("a fault in the work")
        assert L.in_flight() == (0, 0)
        with pytest.raises(L.LimitExceeded) as caught, L.server_scope("small"):
            get_codec("aruba_aoss").parse(aoss_ranges(12))
        assert caught.value.kind == "ports" and L.in_flight() == (0, 0)
        with pytest.raises(KeyboardInterrupt), L.server_scope("small"):
            raise KeyboardInterrupt
        assert L.in_flight() == (0, 0)
        # A block that is entered and never left, and then dropped.
        scope = L.server_scope("small")
        scope.__enter__()
        assert L.in_flight() == (1, 0)
        del scope
        assert L.in_flight() == (0, 0)
        # The place is there to take: this would be refused in a fifth of a second.
        with L.server_scope(replace(L.SMALL, seconds=0.2)):
            assert L.in_flight() == (1, 0)

    def test_a_scope_inside_a_scope_does_not_wait_for_itself(self) -> None:
        """The pipeline calls codecs, a codec can parse in order to
        render, the path that pairs ports parses more than once: work
        inside a request that opens a scope again is the same request.
        It takes no second turn, and does not wait for its own."""
        brief = replace(L.SMALL, seconds=0.2)
        text = nxos_trunks(2, "2-4000", 3)
        with L.server_scope(brief):
            assert L.in_flight() == (1, 0)
            with L.server_scope(brief):
                assert L.in_flight() == (1, 0), "a turn was taken twice"
                with L.limits_scope("small"):
                    assert len(get_codec("cisco_nxos").parse(text).interfaces) == 2
            assert L.in_flight() == (1, 0), "the inner scope gave the outer one's turn back"
            assert _plan("cisco_nxos", "arista_eos", text, "small").status.value == "completed"
            # Work the request hands to another thread, with its context, is the request too.
            said: list[object] = []

            def elsewhere() -> None:
                with L.server_scope(brief):
                    said.append(L.in_flight())

            worker = threading.Thread(target=contextvars.copy_context().run, args=(elsewhere,))
            worker.start()
            worker.join(10)
            assert said == [(1, 0)]
        assert L.in_flight() == (0, 0)

    def test_a_turn_that_is_over_excuses_nobody(self) -> None:
        """A copy of a request's context can outlive the request.
        What it carries is a turn that was given back: work that runs
        in it later waits like anyone."""
        with L.server_scope("small"):
            kept = contextvars.copy_context()
        first = _Request("small").working()

        def later() -> None:
            with L.server_scope(replace(L.SMALL, seconds=0.2)):
                raise AssertionError("it did not wait for the request at work")

        with pytest.raises(L.LimitExceeded) as caught:
            kept.run(later)
        assert caught.value.kind == "at_once"
        first.finish()

    def test_work_that_opens_no_server_scope_never_waits(self) -> None:
        """The command line, a tool, a library caller, a test: none
        of them is a request to a server.  With the place taken, each
        of these would be refused in a fifth of a second if it
        waited."""
        text = nxos_trunks(2, "2-4000", 3)
        first = _Request("small").working()
        brief = replace(L.SMALL, seconds=0.2)
        for surface in ("server", "cli"):
            with L.limits_scope(brief, surface=surface):
                assert len(get_codec("cisco_nxos").parse(text).interfaces) == 2
        assert len(get_codec("cisco_nxos").parse(text).interfaces) == 2
        assert _plan("cisco_nxos", "arista_eos", text, brief).status.value == "completed"
        assert L.in_flight() == (1, 0)
        first.finish()

    @pytest.mark.parametrize("name", ["standard", "large", "unlimited", None])
    def test_nothing_waits_unless_the_limits_say_so(self, name: str | None) -> None:
        """The default and the two sets above it limit no requests at
        once: three are inside together, with the place of a ``small``
        server taken besides.  They take no turn and stand in no
        line."""
        first = _Request("small").working()
        others = [_Request(name).working() for _ in range(3)]
        assert L.in_flight() == (1, 0)
        for other in others:
            other.finish()
            assert other.refused is None
        first.finish()

    def test_turns_go_in_order_of_arrival_and_the_line_is_short(self) -> None:
        """No more than ``MOST_WAITING`` wait: a request that waits
        holds a thread of the pool the server runs handlers on, and
        its body.  One more is turned away at once, in words, without
        waiting."""
        assert L.MOST_WAITING == 2
        entered: list[_Request] = []
        first = _Request("small", entered).working()
        line = []
        for n in range(L.MOST_WAITING):
            waiter = _Request("small", entered)
            waiter.let_go.set()  # each leaves as soon as it has had its turn
            waiter.start()
            line.append(waiter)
            _until(lambda n=n: L.in_flight() == (1, n + 1), f"request {n + 2} standing in the line")
        began = time.monotonic()
        with pytest.raises(L.LimitExceeded) as caught, L.server_scope("small"):
            raise AssertionError("one more request got in")
        assert time.monotonic() - began < 2.0, "it waited, with the line full"
        exc = caught.value
        assert (exc.kind, exc.asked, exc.cap, exc.waited, exc.exact) == ("at_once", 4, 1, None, True)
        assert str(exc).startswith(
            "the server works on one config at a time, and 2 more were already waiting their turn; this "
            "request was not started and its config was not read.  Send it again.  This server runs with"
        )
        assert L.in_flight() == (1, L.MOST_WAITING)
        first.finish()
        for waiter in line:
            waiter.join(10)
            assert not waiter.is_alive() and waiter.refused is None
        assert entered == [first, *line]

    def test_a_newcomer_goes_to_the_back_of_the_line(self) -> None:
        """Even when there is a place it could take at that instant.
        Two sets of limits are needed to show it (no server has two):
        the first in the line may work one at a time and is waiting;
        the newcomer may work two at a time, and one is at work."""
        two = replace(L.SMALL, name="two", at_once=2)
        entered: list[_Request] = []
        first = _Request(two, entered).working()
        ahead = _Request("small", entered)
        ahead.start()
        _until(lambda: L.in_flight() == (1, 1), "the one-at-a-time request standing in the line")
        newcomer = _Request(two, entered)
        newcomer.start()
        _until(lambda: L.in_flight() == (1, 2), "the newcomer standing behind it")
        assert not newcomer.inside.is_set() and not ahead.inside.is_set()
        first.finish()
        # The head of the line has its turn, and the newcomer, behind
        # it and allowed two at work, comes in beside it.  Neither was
        # let in before the place was free.  Which of the two writes
        # itself down first is theirs to race for once both are in,
        # so that order is not asked: on a slower machine the
        # newcomer sometimes wrote first.
        assert ahead.inside.wait(10), "the head of the line never got its turn"
        assert newcomer.inside.wait(10), "the newcomer never got in behind it"
        assert entered[0] is first and set(entered[1:]) == {ahead, newcomer}
        ahead.finish()
        newcomer.finish()


class TestATurnStaysWithTheAnswer:
    """The work of a request ends when its handler returns; its memory
    does not.  The answer is still to be made into bytes and sent, and
    a job's answer can be tens of megabytes.  A handler opens its scope
    with the request's ``Answer``, and the turn comes back when that
    has gone out."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0)
        yield
        assert L.in_flight() == (0, 0), "a turn was not given back, or a request is still in the line"

    def test_until_it_has_gone_out(self) -> None:
        answer = L.Answer()
        with L.server_scope("small", answer=answer):
            assert L.in_flight() == (1, 0)
        assert L.in_flight() == (1, 0), "the turn came back when the block ended, with the answer still to send"
        second = _Request("small")
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        assert not second.inside.is_set()
        answer.sent()
        assert second.inside.wait(10), "the turn did not come back when the answer went out"
        answer.sent()  # told twice: nothing more is given back
        assert L.in_flight() == (1, 0)
        second.finish()

    def test_an_answer_for_a_request_that_took_no_turn(self) -> None:
        for limits in ("standard", None, "unlimited"):
            answer = L.Answer()
            with L.server_scope(limits, answer=answer):
                assert L.in_flight() == (0, 0)
            answer.sent()
        L.Answer().sent()  # a request that opened no scope at all: every page

    def test_a_refused_request_lends_nothing(self) -> None:
        first = _Request("small").working()
        answer = L.Answer()
        with pytest.raises(L.LimitExceeded), L.server_scope(replace(L.SMALL, seconds=0.2), answer=answer):
            raise AssertionError("it got in")
        assert L.in_flight() == (1, 0)
        answer.sent()
        assert L.in_flight() == (1, 0), "an answer that held no turn gave another request's back"
        first.finish()

    def test_a_fault_in_the_work_still_waits_for_the_answer(self) -> None:
        """A handler that raises is answered too -- with an error --
        and the turn comes back when that has gone out, as the
        application says it has for every request."""
        answer = L.Answer()
        with pytest.raises(RuntimeError), L.server_scope("small", answer=answer):
            raise RuntimeError("a fault in the work")
        assert L.in_flight() == (1, 0)
        answer.sent()
        assert L.in_flight() == (0, 0)

    def test_the_client_left_before_the_work_ended(self) -> None:
        """Nobody waits for the answer any more; the work is still
        using the memory.  The turn stays until the block ends, and is
        then given back at once: there is no answer to lend it to."""
        answer = L.Answer()
        with L.server_scope("small", answer=answer):
            answer.sent()
            assert L.in_flight() == (1, 0), "the turn was given back while its request was still at work"
        assert L.in_flight() == (0, 0)

    def test_the_same_request_at_work_again_keeps_its_turn(self) -> None:
        """Two scopes, one after the other, for one answer: the second
        does not wait for the turn the first one lent.  The lent turn
        would not fall due for half a minute, and the second scope has
        a fifth of a second: it would be refused if it waited."""
        brief = replace(L.SMALL, seconds=0.2)
        answer = L.Answer()
        with L.server_scope(replace(L.SMALL, seconds=30.0), answer=answer):
            pass
        with L.server_scope(brief, answer=answer):
            assert L.in_flight() == (1, 0)
            with L.server_scope(brief, answer=answer):  # and inside itself
                assert L.in_flight() == (1, 0)
        assert L.in_flight() == (1, 0)
        answer.sent()

    def test_an_answer_nobody_reads_does_not_keep_the_turn_for_ever(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A client that does not read its answer would hold a lent
        turn as long as its connection lasts.  Past the request's own
        deadline the turn is taken back for whoever waits -- and the
        late word that the answer went out gives nothing back a second
        time."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        unread = L.Answer()
        with L.server_scope("small", answer=unread):  # arrives at 1,000: its deadline is 1,020
            pass
        clock.now = 1_005.0
        second = _Request("small")  # its own deadline is 1,025
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        clock.now = 1_019.0
        with L._TURNS._changed:
            L._TURNS._changed.notify_all()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        assert not second.inside.is_set(), "the turn was taken back before its holder's time was up"
        clock.now = 1_020.5
        with L._TURNS._changed:
            L._TURNS._changed.notify_all()
        assert second.inside.wait(10), "the turn was never taken back"
        assert L.in_flight() == (1, 0)
        unread.sent()
        assert L.in_flight() == (1, 0), "the late answer gave the second request's turn away"
        second.finish()

    def test_a_request_in_the_line_wakes_when_a_lent_turn_falls_due(self) -> None:
        """Nobody has to wake it: it waits no longer than the lent
        turn has to run, though its own deadline is far off."""
        unread = L.Answer()
        with L.server_scope(replace(L.SMALL, seconds=0.3), answer=unread):
            pass
        began = time.monotonic()
        with L.server_scope(replace(L.SMALL, seconds=30.0)):
            waited = time.monotonic() - began
            assert L.in_flight() == (1, 0)
        assert 0.2 < waited < 10.0, waited
        unread.sent()

    def test_a_turn_that_is_lent_wakes_who_was_already_waiting(self) -> None:
        """The other order, which is the common one: the second
        request arrives while the first is still AT WORK, and so
        goes to sleep until its own deadline -- nothing was lent
        yet for it to count on.  When the first one's block ends
        and its turn is lent to an answer nobody reads, the one
        in the line has to be told: it then waits to the lent
        turn's deadline (a third of a second) and not to its own
        (half a minute)."""
        unread = L.Answer()
        at_work, end_the_work = threading.Event(), threading.Event()

        def first() -> None:
            with L.server_scope(replace(L.SMALL, seconds=0.3), answer=unread):
                at_work.set()
                end_the_work.wait(30)

        holder = threading.Thread(target=first, daemon=True)
        holder.start()
        assert at_work.wait(10)
        second = _Request(replace(L.SMALL, seconds=30.0))
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request in the line, the first still at work")
        end_the_work.set()
        holder.join(10)
        assert second.inside.wait(10), (
            "the request in the line slept on, past the deadline of the turn that was lent"
        )
        assert L.in_flight() == (1, 0)
        second.finish()
        unread.sent()


class TestANewTurnHandsFreedMemoryBack:
    """Freed memory is not memory the system has back: the C library
    keeps what a thread freed for that thread, and a server runs its
    requests on whichever thread is idle.  A request that has taken its
    turn trims first."""

    def test_once_before_the_work_and_only_for_a_turn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[object] = []
        monkeypatch.setattr(L, "_trim", lambda pad: seen.append(("trim", pad, L.in_flight())) or 1)
        with L.server_scope("small"):
            seen.append("work")
            with L.server_scope("small"):  # the same request: no second turn, no second trim
                seen.append("inner work")
            with L.limits_scope("small"):
                pass
        assert seen == [("trim", 0, (1, 0)), "work", "inner work"]
        seen.clear()
        for limits in ("standard", "large", "unlimited", None):
            with L.server_scope(limits):
                pass
        with L.limits_scope("small"), L.limits_scope("small", surface="cli"):
            get_codec("cisco_nxos").parse(nxos_trunks(1, "2-10", 2))
        assert seen == [], "trimmed where no limit says memory is that tight"
        assert L.in_flight() == (0, 0)

    def test_a_request_that_did_not_get_a_turn_trims_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []
        first = _Request("small").working()
        monkeypatch.setattr(L, "_trim", lambda pad: seen.append(pad) or 1)
        with pytest.raises(L.LimitExceeded), L.server_scope(replace(L.SMALL, seconds=0.2)):
            raise AssertionError("it got in")
        assert seen == []
        first.finish()

    def test_where_the_c_library_has_no_such_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows, macOS, a C library without it: nothing is trimmed
        and nothing fails.  On Linux with glibc there is one."""
        found = L._find_trim()
        if not sys.platform.startswith("linux"):
            assert found is None
        else:
            assert found is None or found(0) in (0, 1)
        monkeypatch.setattr(L, "_trim", None)
        with L.server_scope("small"):
            assert L.in_flight() == (1, 0)
        assert L.in_flight() == (0, 0)

    def test_a_trim_that_fails_does_not_keep_the_turn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(pad: int) -> int:
            raise OSError("the C library refused")

        monkeypatch.setattr(L, "_trim", broken)
        with pytest.raises(OSError), L.server_scope("small"):
            raise AssertionError("the block was entered")
        assert L.in_flight() == (0, 0)


# ---------------------------------------------------------------------------
# 13. Out of time after a wait is busy, and says so
# ---------------------------------------------------------------------------

_BUSY_HINT = (
    "This server runs with the 'small' config size limit, the one the public demo uses.  A Netcanon you run "
    "yourself does not make one request wait for another by default."
)


class _Late(threading.Thread):
    """A request under ``small`` that does *work* when the test says
    so, inside its scope; what the work raised is kept."""

    def __init__(self, work: Callable[[], object]) -> None:
        super().__init__(daemon=True)
        self.work = work
        self.inside, self.go = threading.Event(), threading.Event()
        self.refused: L.LimitExceeded | None = None
        self.left = False
        _MADE.append((self, self._leave))

    def _leave(self) -> None:
        """The test is over: go, and do no work."""
        self.left = True
        self.go.set()

    def run(self) -> None:
        try:
            with L.server_scope("small"):
                self.inside.set()
                self.go.wait(30)
                if not self.left:
                    self.work()
        except L.LimitExceeded as exc:
            self.refused = exc


class TestBusyIsSaidAsBusy:
    """A request that stood in the line and THEN ran out of time was
    refused as ``seconds``: "the request passed the 20 seconds it may
    take ... a Netcanon you run yourself allows 120".  Nothing in that
    says the server was busy, or to send it again, and it sends the
    reader to look for something slow in the config.  A refusal for
    time that follows a wait is busy: it says how long the request
    waited, and is filed as ``at_once``."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0)
        yield
        assert L.in_flight() == (0, 0), "a turn was not given back, or a request is still in the line"

    def _waited_then_late(self, monkeypatch: pytest.MonkeyPatch, work: Callable[[], object]) -> L.LimitExceeded:
        """Arrives at 1,002.5 behind a request at work, gets its turn
        at 1,020 -- 17.5 seconds in the line -- and does *work* at
        1,023, half a second past its deadline."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        first = _Request("small").working()
        clock.now = 1_002.5
        second = _Late(work)
        second.start()
        _until(lambda: L.in_flight() == (1, 1), "the second request standing in the line")
        clock.now = 1_020.0
        first.finish()
        assert second.inside.wait(10)
        clock.now = 1_023.0
        second.go.set()
        second.join(10)
        assert not second.is_alive() and second.refused is not None, "it was not refused"
        return second.refused

    def test_it_says_how_long_it_waited_and_to_send_it_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        exc = self._waited_then_late(monkeypatch, lambda: get_codec("cisco_nxos").parse(nxos_trunks(1, "2-10", 2)))
        assert (exc.kind, exc.asked, exc.cap, exc.exact, exc.profile) == ("at_once", 2, 1, True, "small")
        assert (exc.waited, exc.out_of, exc.stage, exc.codec, exc.starting) == (17.5, 20.0, "parse", "cisco_nxos", True)
        assert str(exc) == (
            "the server works on one config at a time, and this request waited 17.5 seconds for its turn; what "
            "was left of the 20 seconds it may take was not enough, and it was stopped before reading the config "
            "as cisco_nxos began.  Send it again.  " + _BUSY_HINT
        )
        for word in ("passed the", "allows 120", "parse failed", "was not started", "NETCANON_", "Preferences"):
            assert word not in str(exc), word
        refusal = Refusal(**exc.as_dict())
        assert (refusal.limit, refusal.asked, refusal.cap, refusal.stage, refusal.codec) == (
            "at_once", 2, 1, "parse", "cisco_nxos",
        )
        assert refusal.how_to_raise == _BUSY_HINT

    def test_and_so_does_a_loop_outside_any_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reading the device out of a config is a loop over its
        lines before any parse: its clock is the scope's."""

        def reads_lines() -> None:
            for _ in L.ticked(["a line"] * 600):
                pass

        exc = self._waited_then_late(monkeypatch, reads_lines)
        assert (exc.kind, exc.waited, exc.out_of, exc.stage) == ("at_once", 17.5, 20.0, "")
        assert str(exc).startswith(
            "the server works on one config at a time, and this request waited 17.5 seconds for its turn; what "
            "was left of the 20 seconds it may take was not enough, and it was stopped.  Send it again."
        )

    def test_and_a_count_made_out_of_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        exc = self._waited_then_late(monkeypatch, lambda: L.metered("render", "juniper_junos").__enter__())
        assert (exc.kind, exc.stage, exc.codec) == ("at_once", "render", "juniper_junos")
        assert "it was stopped before writing the config for juniper_junos began.  Send it again." in str(exc)

    def test_a_request_that_did_not_wait_is_refused_for_time_as_before(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        alone = _Late(lambda: get_codec("cisco_nxos").parse(nxos_trunks(1, "2-10", 2)))
        alone.start()
        assert alone.inside.wait(10)
        clock.now = 1_020.5
        alone.go.set()
        alone.join(10)
        exc = alone.refused
        assert exc is not None
        assert (exc.kind, exc.asked, exc.cap, exc.waited, exc.out_of) == ("seconds", 20.5, 20.0, None, None)
        assert str(exc) == (
            "the request passed the 20 seconds it may take before reading the config as cisco_nxos began, and "
            "was stopped.  This server runs with the 'small' config size limit, the one the public demo uses.  "
            "A Netcanon you run yourself allows 120 seconds by default."
        )

    def test_a_wait_too_short_to_print_is_still_said(self) -> None:
        """Never "waited 0 seconds": a tenth is the least it says."""
        exc = L._out_of_time(L.SMALL, "server", 0.2, 0.004, 2, "parse", "vyos")
        assert exc.kind == "at_once" and "this request waited 0.1 seconds for its turn" in str(exc)
        assert "it was stopped while reading the config as vyos." in str(exc)

    def test_work_that_takes_no_turn_is_never_told_it_was_busy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The command line, a tool, limits with no line: there is
        nobody to have waited behind."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        for scope in (L.limits_scope("small", surface="cli"), L.server_scope("standard"), L.limits_scope("small")):
            clock.now = 1_000.0
            with pytest.raises(L.LimitExceeded) as caught, scope:
                clock.now += 700.0
                get_codec("cisco_nxos").parse(nxos_trunks(1, "2-10", 2))
            assert caught.value.kind == "seconds" and caught.value.waited is None

    def test_a_body_that_did_not_arrive_has_its_own_words(self) -> None:
        exc = L.body_late("small", 20.3)
        assert (exc.kind, exc.asked, exc.cap, exc.stage, exc.profile) == ("seconds", 20.3, 20.0, "body", "small")
        assert str(exc) == (
            "the request passed the 20 seconds it may take while its body was still arriving, and was stopped.  "
            "This server runs with the 'small' config size limit, the one the public demo uses.  A Netcanon you "
            "run yourself allows 120 seconds by default."
        )


# ---------------------------------------------------------------------------
# 14. A place, counted when a request arrives
# ---------------------------------------------------------------------------


class TestAPlaceIsCountedAtArrival:
    """A request holds memory before it can ask for a turn: its body.
    Requests that arrived together added up, however few of them were
    let work.  So a request is counted when its headers arrive -- as
    many places as may work and wait -- and its one deadline runs from
    then."""

    @pytest.fixture(autouse=True)
    def _nothing_is_left_behind(self):
        assert L.in_flight() == (0, 0) and L.places() == 0
        yield
        assert L.in_flight() == (0, 0), "a turn was not given back, or a request is still in the line"
        assert L.places() == 0, "a place was not given back"

    def test_as_many_places_as_may_work_and_wait(self) -> None:
        assert (L.SMALL.at_once, L.MOST_WAITING) == (1, 2)
        arrived = [L.Answer() for _ in range(3)]
        for n, answer in enumerate(arrived, 1):
            answer.arrived("small")
            assert L.places() == n and answer.deadline is not None
        late = L.Answer()
        with pytest.raises(L.LimitExceeded) as caught:
            late.arrived("small")
        exc = caught.value
        assert (exc.kind, exc.asked, exc.cap, exc.exact, exc.waited, exc.out_of) == ("at_once", 4, 1, True, None, None)
        assert str(exc).startswith(
            "the server works on one config at a time, and 2 more were already waiting their turn; this request "
            "was not started and its config was not read.  Send it again."
        )
        assert L.places() == 3 and late.deadline is None
        late.sent()
        assert L.places() == 3, "a request that was refused a place gave another's back"
        # Nothing of the three has asked for a turn yet: they are sending their bodies.
        assert L.in_flight() == (0, 0)
        arrived[1].sent()
        assert L.places() == 2
        late.arrived("small")
        assert L.places() == 3
        for answer in (*arrived, late):
            answer.sent()
            answer.sent()  # told twice: nothing more is given back
        assert L.places() == 0

    @pytest.mark.parametrize("name", ["standard", "large", "unlimited", None])
    def test_nothing_is_counted_unless_the_limits_say_how_many(self, name: str | None) -> None:
        answers = [L.Answer() for _ in range(10)]
        for answer in answers:
            answer.arrived(name)
            assert answer.deadline is None and answer.left() is None
        assert L.places() == 0
        for answer in answers:
            answer.sent()

    def test_the_deadline_is_counted_from_the_arrival(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Seven seconds of a slow body are seven seconds the request
        has spent: its scope ends at 1,020 and not at 1,027 -- and so
        does a second scope of the same request."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        answer = L.Answer()
        answer.arrived("small")
        assert answer.deadline == 1_020.0 and answer.left() == 20.0
        clock.now = 1_007.0
        assert answer.left() == 13.0
        for _ in range(2):
            with L.server_scope("small", answer=answer):
                scope = L._SCOPE.get()
                assert scope is not None and scope.deadline == 1_020.0
            clock.now += 2.0
        answer.sent()
        # One that was not counted has its scope's own deadline, as ever.
        uncounted = L.Answer()
        with L.server_scope("small", answer=uncounted):
            scope = L._SCOPE.get()
            assert scope is not None and scope.deadline == clock.now + 20.0
        uncounted.sent()

    def test_the_place_comes_back_when_the_answer_has_gone(self) -> None:
        answer = L.Answer()
        answer.arrived("small")
        with L.server_scope("small", answer=answer):
            assert (L.places(), L.in_flight()) == (1, (1, 0))
        assert (L.places(), L.in_flight()) == (1, (1, 0)), "the place came back with the answer still to send"
        answer.sent()
        assert (L.places(), L.in_flight()) == (0, (0, 0))

    def test_a_request_that_never_asked_for_a_turn_gives_it_back_too(self) -> None:
        """Refused before any handler ran -- an unknown vendor, a
        body that is not JSON, no key -- or its client left while it
        was still sending."""
        answer = L.Answer()
        answer.arrived("small")
        assert L.places() == 1
        answer.sent()
        assert L.places() == 0

    def test_the_place_stays_while_the_work_goes_on(self) -> None:
        """The client left; the thread works on to the end of its
        block, and the memory is in use until then."""
        answer = L.Answer()
        answer.arrived("small")
        with L.server_scope("small", answer=answer):
            answer.sent()
            assert (L.places(), L.in_flight()) == (1, (1, 0)), "the place came back while its request was at work"
        assert (L.places(), L.in_flight()) == (0, (0, 0))

    @pytest.mark.parametrize("seconds, gets_its_turn", [(30.0, True), (0.3, False)])
    def test_and_while_it_stands_in_the_line(self, seconds: float, gets_its_turn: bool) -> None:
        """Its client left while it waited: the place is kept until
        it has had its turn and its block has ended -- or until it
        gives the line up at its deadline."""
        first = _Request("small").working()
        answer = L.Answer()
        limits = replace(L.SMALL, seconds=seconds)
        answer.arrived(limits)
        refused: list[L.LimitExceeded] = []

        def waits() -> None:
            try:
                with L.server_scope(limits, answer=answer):
                    pass
            except L.LimitExceeded as exc:
                refused.append(exc)

        thread = threading.Thread(target=waits, daemon=True)
        thread.start()
        _until(lambda: L.in_flight() == (1, 1), "the request standing in the line")
        answer.sent()
        assert L.places() == 1, "the place came back while its request stood in the line"
        if gets_its_turn:
            first.finish()
        thread.join(10)
        assert not thread.is_alive() and bool(refused) is not gets_its_turn
        assert L.places() == 0
        first.finish()

    def test_a_turn_taken_back_does_not_take_the_place_with_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An answer nobody reads loses its turn at the deadline, to
        whoever waits.  Its place is the application's to give back,
        when it has let the answer go."""
        clock = _Hands()
        monkeypatch.setattr(L, "time", clock)
        unread = L.Answer()
        unread.arrived("small")
        with L.server_scope("small", answer=unread):
            pass
        clock.now = 1_020.5
        second = _Request("small")  # on a thread of its own: the clock is stopped, and a test must end
        second.start()
        try:
            assert second.inside.wait(10), "the turn was never taken back from an answer nobody read"
            assert (L.places(), L.in_flight()) == (1, (1, 0))
        finally:
            clock.now += 1_000.0  # whatever went wrong, nothing waits on this clock any more
            unread.sent()
            second.finish()
        assert L.places() == 0
