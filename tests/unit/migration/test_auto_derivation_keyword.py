"""Defect D4 — the `auto` RD / route-target derivation keyword.

`auto` is not a value. It is an instruction to the device: *derive this
yourself*. NX-OS and AOS-CX write it; netcanon carries the literal string on
`CanonicalRoutingInstance`. Because it round-trips perfectly (`auto` in, `auto`
out), the cross-mesh fidelity audit scores it **ALIGNED** — it is invisible to
every existing gate, which is why this went unnoticed.

Scope, and why it is narrow
---------------------------
The original framing was "a derivation keyword crosses vendor boundaries
unadjudicated". Adversarial verification cut that down to **a lexical defect on
exactly two targets**, each closed against a primary source:

* **Junos** — `route-distinguisher` accepts `as-number:number`, `number:id`,
  `ip-address:id`. `auto` is not among them. Separately `vrf-target` *does*
  take a bare `auto`, but as a standalone alternative to
  `target:<community-id>` — so `vrf-target target:auto` was a non-form built by
  substituting the keyword into the community slot.
* **Cisco IOS-XE CLI** — the auto-RD keyword is `rd-auto` (hyphenated,
  17.12.1+), not `rd auto`, and there is no `route-target ... auto` CLI form at
  all.

⚠️ **Arista EOS and Cisco IOS-XR are deliberately untouched**, and the tests
below pin that they still emit `auto`. Whether EOS accepts `rd auto` in
`router bgp / vrf` submode could not be established from a primary source, and
the earlier claim that "EOS rejects `rd auto`" was **refuted** by a
counter-example in this repo's own corpus. Changing behaviour there on an
unverified grammar belief would repeat that mistake. If someone later closes
the question, these assertions are the place to change.

A wider harm narrative was also refuted and must not be reinstated: the claim
that a mismatched auto-RT means "BGP comes up and the VRF imports nothing" does
not hold, because netcanon renders zero BGP neighbours and zero
address-families — the `router bgp` stanza it emits is a bare shell with a
placeholder ASN. The operator must author the overlay themselves, and once they
write the real ASN, `auto` derives correctly.
"""

from __future__ import annotations

import pytest

from netcanon.migration._derived_values import is_derivation_keyword
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRoutingInstance,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


def _tree(rd: str, rts: list[str]) -> CanonicalIntent:
    return CanonicalIntent(
        source_vendor="cisco_nxos",
        routing_instances=[
            CanonicalRoutingInstance(
                name="TENANT-777",
                route_distinguisher=rd,
                rt_imports=list(rts),
                rt_exports=list(rts),
            )
        ],
    )


class TestPredicate:
    def test_auto_is_a_derivation_keyword(self) -> None:
        assert is_derivation_keyword("auto")

    def test_case_and_whitespace_tolerant(self) -> None:
        assert is_derivation_keyword(" AUTO ")

    def test_a_real_rd_is_not(self) -> None:
        assert not is_derivation_keyword("65000:901002")

    def test_empty_is_not(self) -> None:
        assert not is_derivation_keyword("")


class TestJunos:
    def test_rd_auto_is_not_emitted(self) -> None:
        out = get_codec("juniper_junos").render(_tree("auto", []))
        assert "route-distinguisher auto" not in out
        assert "review:" in out

    def test_rt_auto_uses_the_native_bare_form(self) -> None:
        """`vrf-target auto` IS a Junos form — preserving the operator's
        "derive it" intent beats dropping the statement."""
        out = get_codec("juniper_junos").render(_tree("", ["auto"]))
        assert "vrf-target auto" in out
        assert "vrf-target target:auto" not in out

    def test_explicit_values_are_untouched(self) -> None:
        out = get_codec("juniper_junos").render(
            _tree("192.0.2.1:6", ["65000:901002"])
        )
        assert "route-distinguisher 192.0.2.1:6" in out
        assert "vrf-target target:65000:901002" in out

    def test_a_mixed_list_is_handled_element_wise(self) -> None:
        """One committed NX-OS capture really does carry
        `['auto', '65000:901002']` on a single instance."""
        tree = CanonicalIntent(
            source_vendor="cisco_nxos",
            routing_instances=[
                CanonicalRoutingInstance(
                    name="T",
                    rt_imports=["auto", "65000:901002"],
                    rt_exports=["auto", "65000:901002"],
                )
            ],
        )
        out = get_codec("juniper_junos").render(tree)
        assert "vrf-target auto" in out
        assert "vrf-target target:65000:901002" in out
        assert "target:auto" not in out


class TestCiscoIOSXECLI:
    def test_rd_auto_is_not_emitted(self) -> None:
        out = get_codec("cisco_iosxe_cli").render(_tree("auto", []))
        assert " rd auto" not in out
        assert "review:" in out

    def test_the_comment_names_the_native_keyword(self) -> None:
        """`rd-auto` is hyphenated and 17.12.1+; the operator needs both
        facts to act on the note."""
        out = get_codec("cisco_iosxe_cli").render(_tree("auto", []))
        assert "rd-auto" in out
        assert "17.12.1" in out

    def test_rt_auto_is_not_emitted(self) -> None:
        out = get_codec("cisco_iosxe_cli").render(_tree("", ["auto"]))
        assert "route-target import auto" not in out
        assert "route-target export auto" not in out

    def test_explicit_values_are_untouched(self) -> None:
        out = get_codec("cisco_iosxe_cli").render(
            _tree("200:1", ["65000:901002"])
        )
        assert " rd 200:1" in out
        assert "route-target import 65000:901002" in out

    def test_an_all_auto_rt_list_emits_no_empty_address_family(self) -> None:
        """Filtering every RT away must not leave a dangling
        `address-family ipv4` / `exit-address-family` pair."""
        out = get_codec("cisco_iosxe_cli").render(_tree("", ["auto"]))
        assert "address-family ipv4" not in out


class TestDeliberatelyUnchanged:
    """These targets keep emitting `auto`. See the module docstring."""

    @pytest.mark.parametrize("target", ["arista_eos", "cisco_iosxr"])
    def test_unverified_targets_still_emit_auto(self, target: str) -> None:
        out = get_codec(target).render(_tree("auto", ["auto"]))
        assert "auto" in out, (
            f"{target} stopped emitting `auto`. That may be correct, but it "
            f"must be backed by a primary source — the prior claim that EOS "
            f"rejects `rd auto` was refuted by our own corpus."
        )

    def test_same_vendor_round_trip_is_unchanged(self) -> None:
        """NX-OS -> NX-OS must not regress: `auto` is native there."""
        out = get_codec("cisco_nxos").render(_tree("auto", ["auto"]))
        assert "rd auto" in out
        assert "route-target both auto" in out
