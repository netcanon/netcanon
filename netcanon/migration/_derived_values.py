"""The `auto` derivation keyword, and where it may be re-emitted.

`auto` in an RD or route-target slot is **not a value**. It is an instruction
to the device: *derive this yourself*. NX-OS and AOS-CX both write it, and
netcanon carries the literal string on
``CanonicalRoutingInstance.route_distinguisher`` / ``rt_imports`` /
``rt_exports``.

Because the literal round-trips perfectly (`auto` in, `auto` out), the
cross-mesh fidelity audit scores it **ALIGNED**. It is invisible to every
existing gate — which is why this sat unnoticed.

Why this module is deliberately tiny
------------------------------------
This is NOT a fourth member of the ``_user_secrets`` / ``_usm_keys`` /
``_radius_secrets`` family, and it must not grow into one. Those exist because
a mis-classified token **becomes a credential** on the target; the blast radius
is every account on the box. Here the worst case is a config line the target
rejects. One known literal, one predicate, no envelopes, no classifier.

Scope of the remedy (#482)
--------------------------
Only the two targets where the emitted form is **provably not the vendor's
grammar**, each closed against a primary source:

* **Junos** — the Juniper CLI reference enumerates ``route-distinguisher``'s
  accepted forms as ``as-number:number``, ``number:id``, ``ip-address:id``.
  ``auto`` is not among them. Separately, ``vrf-target`` *does* accept a bare
  ``auto``, but as a **standalone alternative** to ``target:<community-id>`` —
  so netcanon's ``vrf-target target:auto`` was a non-form built by substituting
  the keyword into the community slot.
* **Cisco IOS-XE CLI** — Cisco doc 220801 gives the auto-RD keyword as
  ``rd-auto`` (hyphenated, IOS-XE 17.12.1+), not ``rd auto``; and there is no
  ``route-target … auto`` CLI form at all, the auto-RT being implied by
  ``vnid <n> evpn-instance``.

**Arista EOS and Cisco IOS-XR are deliberately NOT covered.** Whether EOS
accepts ``rd auto`` in ``router bgp / vrf`` submode could not be established
from a primary source (the relevant release notes are login-walled), and the
prior claim that "EOS rejects `rd auto`" was refuted by a counter-example in
this repo's own corpus. Changing their behaviour on an unverified grammar
belief is the exact mistake that review made. They keep emitting ``auto``
until someone closes the question.

Why not resolve `auto` into a real value
----------------------------------------
Considered and rejected. For an NX-OS IP-VRF the RD is
``<BGP router-id>:<internal VRF ID>``, and that second field is the device's
**runtime VRF allocation index** — it appears nowhere in the config text, on
any device. The canonical model also carries no BGP router-id or ASN at all.
Deriving a value would mean fabricating one the operator never wrote, which is
what AGENTS.md's "declare it, don't invent it" forbids.
"""

from __future__ import annotations

#: The one derivation keyword netcanon's parsers place in an RD / RT slot.
#: Compared case-insensitively; both NX-OS and AOS-CX write it lowercase.
AUTO = "auto"


def is_derivation_keyword(value: str) -> bool:
    """True when *value* is the `auto` derivation instruction rather than a
    literal RD / route-target.

    Element-wise by design: ``rt_imports`` / ``rt_exports`` are
    ``list[str]`` and really do arrive mixed — one committed NX-OS capture
    carries ``['auto', '65000:901002']`` on a single instance, a derivation
    instruction and an explicit value in the same list. A whole-list check
    would mis-handle it either way round.
    """
    return value.strip().lower() == AUTO


def review_comment(field: str, target_label: str, native_form: str = "") -> str:
    """One-line note explaining a dropped derivation keyword.

    *field* names the thing that was dropped (e.g. ``"route-distinguisher"``),
    *native_form* optionally names the target's own equivalent so the operator
    knows what to write instead.
    """
    body = (
        f"review: the source device derived its {field} itself (`auto`); "
        f"that keyword is not valid on {target_label}, so no value was "
        f"emitted -- set one explicitly"
    )
    if native_form:
        body += f" -- the equivalent on this platform is `{native_form}`"
    return body
