"""Target-profile provenance — the guards that keep a profile describing hardware.

Background.  A registry audit in 2026-10 found a third of the shipped
profiles carrying a port name or count the device does not have.  A
profile's port ids are offered to the operator as override choices and
written verbatim into the generated config, so each one was a path to a
config naming a port that does not exist.  The largest single cause was a
written rule telling authors to derive ids from ``format_port_identity`` —
profiles ended up describing the formatter instead of the device.  The
rest were vendor documents misread, or a sibling model's facts filed under
the wrong model.

Provenance fields on
:class:`~netcanon.migration.target_profiles.TargetProfile` now carry what
the audit established, and this module makes each of them a checked claim
rather than a label:

* ``evidence: capture`` — re-proven here on every run: the cited fixture
  must identify itself as THIS model, be a capture of the profile's own
  vendor, and contain every profile port id as a hardware port.  This is
  the test that would have caught the 2930F (``1/A1`` on a switch with no
  module slot) and the C9300-24UX (``GigabitEthernet`` on a
  ``TenGigabitEthernet`` box) before they shipped.
* ``evidence: vendor-doc`` / ``inferred`` — the graded sets are pinned, so
  a grade cannot quietly disappear; ``inferred`` must carry a ``caveat``.
* ``deployment_state`` — required of every stack-capable profile, because a
  port's name is a function of the model AND how it is deployed.

What the capture check does NOT prove, so nobody over-reads it:

* It is one-directional.  A profile that OMITS ports the capture has still
  passes; the exact lists in ``test_target_profile_shipped.py`` cover that.
* On a platform that lists absent hardware in its config (a Catalyst 9300
  prints every network module's interfaces whichever is fitted) it proves a
  module port's NAME exists, not that the module is installed.

Schema tests live in ``test_target_profile_schema.py``; exact per-profile
port lists in ``test_target_profile_shipped.py``.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.target_profiles import (
    TargetProfile,
    load_profile_file,
    load_profiles_dir,
)
from netcanon.services.migration_detect import detect_codec
from tests.fixtures.target_profiles import (
    UNVERIFIED_PROFILE_KEY,
    UNVERIFIED_PROFILE_YAML,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")

#: Canonical interface types that are not hardware ports.  A capture's
#: SVIs, LAGs, loopbacks, bridges and tunnels are real names in the
#: config, but a profile that lists one as a port is wrong.
_NOT_A_PORT = frozenset({
    "ianaift:l3ipvlan",
    "ianaift:l2vlan",
    "ianaift:ieee8023adLag",
    "ianaift:softwareLoopback",
    "ianaift:bridge",
    "ianaift:tunnel",
})


def _all_port_ids(profile: TargetProfile) -> list[str]:
    """Every id the profile can offer: chassis ports plus every module's."""
    ids = [p.id for p in profile.ports]
    for module in profile.modules.values():
        ids.extend(p.id for p in module.ports)
    return ids


def _vendor_of(codec_name: str) -> str:
    # ``_CAPS`` is the class-level capability matrix; there is no public
    # accessor for a codec's vendor id (``api/routes/ui.py`` reads it the
    # same way).
    return get_codec(codec_name)._CAPS.vendor_id


def _ports_in_capture(path: Path, vendor: str) -> tuple[set[str], str]:
    """Hardware port names a real capture mentions, and its lower-cased text.

    A running-config names a port in an ``interface`` stanza only when
    the port carries non-default config; an unconfigured access port
    appears solely in a VLAN's membership list (``untagged 1-47``), and
    a LAG member solely under the LAG.  All three are evidence that the
    device has a port of that name.  A LAG's OWN name, an SVI, a
    loopback or a bridge is not — and LAG names also arrive through
    VLAN membership, so they are subtracted after the union.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    candidates = detect_codec(raw)
    assert candidates, f"{path.name}: no codec recognises this capture"
    capture_vendor = _vendor_of(candidates[0].codec)
    assert capture_vendor == vendor, (
        f"{path.name} is a {capture_vendor} capture; the profile citing it "
        f"is filed under {vendor}"
    )
    intent = get_codec(candidates[0].codec).parse(raw)
    names = {iface.name for iface in intent.interfaces}
    for vlan in intent.vlans:
        names.update(vlan.tagged_ports or [])
        names.update(vlan.untagged_ports or [])
    for lag in intent.lags or []:
        names.update(lag.members or [])
    names -= {
        iface.name for iface in intent.interfaces
        if iface.interface_type in _NOT_A_PORT
    }
    names -= {lag.name for lag in intent.lags or []}
    return names, raw.lower()


CAPTURE_GRADED = sorted(
    key for key, p in PROFILES.items() if p.evidence == "capture"
)

#: Profiles whose port names are capture-backed, each with a line that
#: only a capture of THAT MODEL contains (lower-cased).  Grading a profile
#: ``capture`` means saying how its fixture identifies itself: without
#: this, a profile passes against any sibling whose port names happen to
#: be a superset — a 3810M against the 2930M capture, a JL256A against the
#: JL260A one — which is the audit's own failure passing the guard built
#: to stop it.
#:
#: Pinned, so the conformance check cannot pass vacuously and so that
#: DOWNGRADING a profile is a deliberate, reviewed edit.
CAPTURE_MODEL_MARKER = {
    "aruba_aoss/2930F-48G": "module 1 type jl260a",
    "cisco_iosxe/C9300-24UX": "switch 1 provision c9300-24ux",
    "mikrotik_routeros/CRS310-8G+2S+": "# model = crs310-8g+2s+",
}

#: Profiles graded from published sources.  Nothing re-checks the names,
#: so the least this can do is notice a grade — and with it the
#: ``evidence_ref`` and caveat an operator sees — quietly going away
#: (an unknown YAML key such as a misspelt ``evidance:`` is ignored by the
#: loader, not rejected).
EXPECTED_VENDOR_DOC_GRADED = {
    "arista_eos/DCS-7050CX3-32S",
    "arista_eos/DCS-7050SX-64",
    "arista_eos/DCS-7060CX-32S",
    "arista_eos/DCS-7280CR3-32P4",
    "aruba_aoscx/6300M-48G-PoE4-SFP56",
    "aruba_aoss/2930F-24G",
    "aruba_aoss/2930F-24G-PoEP",
    "aruba_aoss/2930F-48G-PoEP",
    "aruba_aoss/3810M-24G-PoEP",
    "aruba_aoss/3810M-48G-PoEP",
    "cisco_iosxe/C9300-24P",
    "cisco_iosxe/C9300-24U",
    "cisco_iosxe/C9300-48P",
    "cisco_iosxe/C9300-48U",
    "cisco_iosxe/C9300-48UXM",
    "juniper_junos/EX4300-48T",
    "juniper_junos/EX4600-40F",
    "juniper_junos/QFX5120-48Y",
}

#: Profiles whose port names cannot be vouched for on the target they
#: are filed under — so they are flagged to the operator rather than
#: quietly offered.  EMPTY today, and meant to be.  The two profiles
#: that used to be here (Netgate SG-1100 / SG-3100, filed under
#: OPNsense) were deleted rather than left flagged: they are pfSense
#: Plus hardware and OPNsense has no image for either board, so no
#: target existed for the names to be right on.
#:
#: Rot-fail by design.  Whoever finds a shipped profile that is wrong
#: without an established replacement flags it (``evidence: inferred``
#: plus a ``caveat``) and adds its key here, rather than swapping one
#: plausible name for another — which is how the registry got into the
#: state the 2026-10 audit found.  Whoever resolves one (re-files it,
#: deletes it, or establishes the names) changes the YAML and this set
#: in the same PR.
KNOWN_DOUBTFUL: set[str] = set()


def _inferred_without_a_caveat(profiles: dict[str, TargetProfile]) -> list[str]:
    """Keys of ``inferred`` profiles that do not tell the operator why."""
    return sorted(
        key for key, profile in profiles.items()
        if profile.evidence == "inferred" and not profile.caveat.strip()
    )


class TestCaptureGradeIsChecked:
    """``evidence: capture`` is proven, not asserted."""

    def test_the_capture_graded_set_is_what_we_expect(self) -> None:
        assert set(CAPTURE_GRADED) == set(CAPTURE_MODEL_MARKER)

    @pytest.mark.parametrize("key", CAPTURE_GRADED)
    def test_cited_capture_is_a_committed_real_fixture(self, key: str) -> None:
        ref = PROFILES[key].evidence_ref
        parts = PurePosixPath(ref).parts
        assert parts[:3] == ("tests", "fixtures", "real") and ".." not in parts, (
            f"{key}: evidence_ref must be a repo-relative path under "
            f"tests/fixtures/real/, got {ref!r}"
        )
        assert (REPO_ROOT / ref).is_file(), f"{key}: {ref} does not exist"

    @pytest.mark.parametrize("key", CAPTURE_GRADED)
    def test_every_profile_port_id_is_in_the_cited_capture(
        self, key: str,
    ) -> None:
        profile = PROFILES[key]
        seen, text = _ports_in_capture(
            REPO_ROOT / profile.evidence_ref, profile.vendor,
        )
        assert CAPTURE_MODEL_MARKER[key] in text, (
            f"{key}: {profile.evidence_ref} does not identify itself as "
            f"this model (no {CAPTURE_MODEL_MARKER[key]!r} line)"
        )
        ids = _all_port_ids(profile)
        assert ids, f"{key}: a capture-graded profile with no ports proves nothing"
        missing = [pid for pid in ids if pid not in seen]
        assert not missing, (
            f"{key} is graded `capture` but {len(missing)} of its port ids "
            f"are not hardware ports in {profile.evidence_ref}: "
            f"{missing[:12]}.  Either the profile is wrong or the grade is — "
            f"a profile describes the hardware, never the formatter."
        )


class TestGradesCarryWhatTheyPromise:
    def test_the_vendor_doc_graded_set_is_what_we_expect(self) -> None:
        graded = {k for k, p in PROFILES.items() if p.evidence == "vendor-doc"}
        assert graded == EXPECTED_VENDOR_DOC_GRADED

    def test_the_inferred_set_is_the_known_doubtful_set(self) -> None:
        inferred = {k for k, p in PROFILES.items() if p.evidence == "inferred"}
        assert inferred == KNOWN_DOUBTFUL

    def test_an_inferred_profile_tells_the_operator_why(self) -> None:
        silent = _inferred_without_a_caveat(PROFILES)
        assert not silent, (
            f"{silent}: `evidence: inferred` without a caveat hides the "
            f"doubt from the one person who needs it"
        )

    def test_the_caveat_check_is_not_vacuous(self) -> None:
        """No shipped profile is graded ``inferred`` today, so the test
        above passes over an empty set.  Prove the check itself on the
        synthetic profile the UI tests use for the amber notice: it must
        pass as written and fail the moment its caveat is removed."""
        fixture = load_profile_file(UNVERIFIED_PROFILE_YAML)
        assert fixture.key == UNVERIFIED_PROFILE_KEY
        assert fixture.evidence == "inferred"
        assert _inferred_without_a_caveat({fixture.key: fixture}) == []
        bare = fixture.model_copy(update={"caveat": "   "})
        assert _inferred_without_a_caveat({bare.key: bare}) == [fixture.key]

    def test_the_synthetic_unverified_profile_is_not_shipped(self) -> None:
        """It lives under ``tests/fixtures/`` and names no real device;
        it must never be offered to an operator."""
        assert UNVERIFIED_PROFILE_KEY not in PROFILES
        shipped = {p.name for p in (LIBRARY_DIR / "target_profiles").glob("*.yaml")}
        assert UNVERIFIED_PROFILE_YAML.name not in shipped

    @pytest.mark.parametrize(
        "key", sorted(EXPECTED_VENDOR_DOC_GRADED | set(CAPTURE_MODEL_MARKER)),
    )
    def test_a_sourced_grade_names_its_source(self, key: str) -> None:
        assert PROFILES[key].evidence_ref.strip(), (
            f"{key}: `evidence: {PROFILES[key].evidence}` must name what "
            f"backs it in evidence_ref"
        )

    @pytest.mark.parametrize(
        "key", sorted(k for k, p in PROFILES.items() if p.stacking),
    )
    def test_a_stack_capable_profile_states_its_deployment(
        self, key: str,
    ) -> None:
        """An Aruba 2930F port is ``24`` standalone and ``1/24`` as a VSF
        member.  A flat port list describes one of those; the profile has
        to say which."""
        assert PROFILES[key].deployment_state.strip(), (
            f"{key}: declares stacking={PROFILES[key].stacking!r} but not "
            f"which deployment state its port ids describe"
        )

    def test_some_profiles_are_stack_capable(self) -> None:
        """Keeps the parametrisation above from going empty unnoticed."""
        assert sum(1 for p in PROFILES.values() if p.stacking) >= 10


class TestHardwareFactsThatWereOnceWrong:
    """Negative pins for the specific errors the audit found."""

    def test_no_2930f_profile_offers_a_letter_slot_port(self) -> None:
        """A 2930F has no module slot; its uplinks continue the access
        numbering (``49-52``).  ``A1`` never applies in any mode."""
        keys = [k for k in PROFILES if "2930F" in k]
        assert len(keys) == 4
        for key in keys:
            lettered = [
                pid for pid in _all_port_ids(PROFILES[key])
                if any(ch.isalpha() for ch in pid)
            ]
            assert not lettered, f"{key}: {lettered}"

    def test_no_profile_offers_a_stacking_module_or_psu_as_an_uplink(
        self,
    ) -> None:
        """JL084A is the 3810M stacking module and JL085A a 250 W power
        supply.  Both were once listed as 40G uplink modules."""
        for key, profile in PROFILES.items():
            assert not {"JL084A", "JL085A"} & set(profile.modules), key

    def test_the_6300m_is_an_aos_cx_profile(self) -> None:
        keys = [k for k in PROFILES if "6300M" in k]
        assert keys, "the 6300M profile is gone"
        for key in keys:
            profile = PROFILES[key]
            assert profile.vendor == "aruba_aoscx", key
            assert "vsx" not in profile.stacking.lower(), key
            # AOS-CX is member/slot/port; there are no letter slots.
            for pid in _all_port_ids(profile):
                assert pid.count("/") == 2 or pid == "mgmt", (key, pid)

    def test_no_arista_qsfp_cage_is_offered_under_a_bare_name(self) -> None:
        """EOS names a multi-lane cage ``Ethernet<port>/<lane>``.  The
        four shipped Arista models' QSFP / OSFP cages are all
        multi-lane, so a 40G-or-faster port never has a bare name."""
        checked = 0
        for key, profile in PROFILES.items():
            if profile.vendor != "arista_eos":
                continue
            for port in profile.ports:
                if port.speed in ("40gig", "100gig", "400gig"):
                    checked += 1
                    assert port.id.endswith("/1"), (key, port.id)
        assert checked >= 100

    def test_no_junos_profile_uses_a_prefix_its_platform_lacks(self) -> None:
        """``xle-`` is the 40G type on QFabric-package QFX3500 / 3600 /
        5100 only; ``me0`` is the EX management port, while QFX and the
        EX4600 use ``em0`` / ``em1``."""
        junos = {k: p for k, p in PROFILES.items() if p.vendor == "juniper_junos"}
        assert len(junos) >= 3
        for key, profile in junos.items():
            ids = _all_port_ids(profile)
            assert not [pid for pid in ids if pid.startswith("xle-")], key
            if "QFX" in key or "EX4600" in key:
                assert "me0" not in ids and "em0" in ids, key

    def test_every_profile_vendor_is_a_real_vendor(self) -> None:
        """A profile filed under a vendor id no codec answers to is
        unreachable from the picker's target-vendor suggestion."""
        vendor_ids = {_vendor_of(name) for name in list_public_codecs()}
        strays = {
            key for key, p in PROFILES.items() if p.vendor not in vendor_ids
        }
        assert not strays, strays
