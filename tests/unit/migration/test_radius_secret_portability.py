"""Defect D3 — a RADIUS shared secret must not cross a vendor boundary
in a form only its source device can read.

The Hard Rules already name this failure twice, for local-user password
hashes (#460-#462) and SNMPv3 USM keys (#463-#472).  RADIUS shared
secrets were the third credential class and had no gate at all: every
render path wrote ``server.key`` verbatim into the target's key slot.

Measured before the fix, from a FortiGate source carrying
``set secret ENC <blob>``:

* ``arista_eos``, ``cisco_iosxe_cli``, ``aruba_aoss``,
  ``mikrotik_routeros`` and ``opnsense`` — five of the six render paths
  — emitted the ``fortios:ENC <blob>`` string into a field their vendor
  reads as the LITERAL shared secret.  The result commits cleanly and
  authenticates nobody, and anything that later strips the envelope
  turns the blob into the password.
* ``fortigate_cli`` ran the same failure backwards: it split the
  canonical value on ``":"`` and stamped ``ENC`` onto whatever came
  back, so a *plaintext* secret from Aruba or OPNsense was written as
  ``set secret ENC <plaintext>`` — asserting a provenance it never had.

Policy now lives in :mod:`netcanon.migration._radius_secrets`.

⚠ The parametrised target list below is the point of this module.  A new
codec that renders ``radius_servers`` must be added to
``_RENDERING_TARGETS``; ``test_every_radius_rendering_codec_is_covered``
fails if one is missing, because the equivalent gap on the password
surface (four render paths silently skipping the gate until #461) is
the single most repeated defect shape in this project.
"""

from __future__ import annotations

import pytest

from netcanon.migration._radius_secrets import (
    _KNOWN_ENVELOPES,
    classify_radius_secret,
    radius_secret_is_migratable,
)
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRADIUSServer,
)
from netcanon.migration.codecs.registry import (
    get_codec,
    list_public_codecs,
)

pytestmark = pytest.mark.unit


#: Every codec whose render path emits a RADIUS server record.
_RENDERING_TARGETS = (
    "arista_eos",
    "aruba_aoss",
    "cisco_iosxe_cli",
    "fortigate_cli",
    "mikrotik_routeros",
    "opnsense",
)

#: A distinctive body so a leak is unambiguous in the rendered text.
#: Not a real secret — the point is that it must NOT appear.
_BLOB_BODY = "EncryptedBlobBodyMarker=="
_FORTI_SECRET = f"fortios:ENC {_BLOB_BODY}"
_PLAIN_SECRET = "PlaintextSharedSecretMarker"


def _tree(key: str, source_vendor: str) -> CanonicalIntent:
    return CanonicalIntent(
        source_vendor=source_vendor,
        radius_servers=[
            CanonicalRADIUSServer(host="10.0.0.1", key=key),
        ],
    )


# ---------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------


class TestClassification:
    def test_empty_is_empty(self) -> None:
        assert classify_radius_secret("") == ""

    def test_fortios_envelope_is_encrypted(self) -> None:
        assert classify_radius_secret(_FORTI_SECRET) == "encrypted"

    def test_bare_value_is_plaintext(self) -> None:
        assert classify_radius_secret(_PLAIN_SECRET) == "plaintext"

    def test_a_colon_in_a_secret_is_content_not_structure(self) -> None:
        """A plaintext secret may legitimately contain a colon.

        Refusing every such value would be the false-positive blast
        #460 warns about.  ``aruba_aoss`` applies no envelope, so
        provenance says this is what the operator typed.
        """
        assert (
            classify_radius_secret("my:secret", "aruba_aoss") == "plaintext"
        )

    def test_unregistered_envelope_from_unvouched_source_is_unknown(
        self,
    ) -> None:
        """Never let an unrecognised secret classify as plaintext."""
        assert classify_radius_secret("newvendor:Payload") == "unknown"

    def test_unknown_is_refused_everywhere(self) -> None:
        for target in _RENDERING_TARGETS:
            assert not radius_secret_is_migratable(
                "newvendor:Payload", "", target,
            ), target

    def test_unknown_target_is_refused(self) -> None:
        """A codec not considered in the policy must not inherit permission."""
        assert not radius_secret_is_migratable(
            _PLAIN_SECRET, "aruba_aoss", "some_future_codec",
        )


# ---------------------------------------------------------------------------
# The render paths — the actual defect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target_name", _RENDERING_TARGETS)
def test_foreign_encrypted_secret_never_reaches_the_wire(
    target_name: str,
) -> None:
    """The FortiGate blob must not appear in any OTHER vendor's output."""
    if target_name == "fortigate_cli":
        pytest.skip("same-vendor round-trip is covered separately")

    rendered = get_codec(target_name).render(
        _tree(_FORTI_SECRET, "fortigate_cli")
    )

    assert _BLOB_BODY not in rendered, (
        f"{target_name} leaked the source device's encrypted RADIUS "
        f"secret into its own key slot"
    )
    assert "fortios:" not in rendered, (
        f"{target_name} leaked the canonical envelope marker"
    )


@pytest.mark.parametrize("target_name", _RENDERING_TARGETS)
def test_the_server_record_survives_a_refused_secret(
    target_name: str,
) -> None:
    """Refusing the key must not silently delete the server.

    A ``radius-server host <ip>`` with no key is a half-configured
    server the operator can see and finish.  A vanished one is a hole
    in their AAA config that nothing points at.
    """
    if target_name == "fortigate_cli":
        pytest.skip("same-vendor round-trip is covered separately")

    rendered = get_codec(target_name).render(
        _tree(_FORTI_SECRET, "fortigate_cli")
    )

    assert "10.0.0.1" in rendered, (
        f"{target_name} dropped the whole RADIUS server record"
    )
    assert "review:" in rendered, (
        f"{target_name} refused the secret without telling the operator why"
    )


@pytest.mark.parametrize("target_name", _RENDERING_TARGETS)
def test_a_portable_plaintext_secret_still_migrates(
    target_name: str,
) -> None:
    """The gate must not break legitimate migrations.

    Closing a default in the wrong order refuses every real record at
    once — that is a false-positive blast, not a fix (#460).
    """
    rendered = get_codec(target_name).render(
        _tree(_PLAIN_SECRET, "aruba_aoss")
    )
    assert _PLAIN_SECRET in rendered, (
        f"{target_name} refused a portable plaintext shared secret"
    )


def test_fortigate_round_trips_its_own_encrypted_secret() -> None:
    """Same-vendor is the reference path: the blob goes home intact."""
    rendered = get_codec("fortigate_cli").render(
        _tree(_FORTI_SECRET, "fortigate_cli")
    )
    assert f"set secret ENC {_BLOB_BODY}" in rendered
    assert "fortios:" not in rendered, (
        "the internal envelope marker leaked into FortiOS output"
    )


def test_fortigate_does_not_stamp_enc_onto_a_plaintext_secret() -> None:
    """The second face of D3.

    ``set secret ENC <plaintext>`` claims the value is ciphertext under
    this device's key.  It is not, and FortiOS will try to decrypt it.
    """
    rendered = get_codec("fortigate_cli").render(
        _tree(_PLAIN_SECRET, "aruba_aoss")
    )
    assert f"set secret {_PLAIN_SECRET}" in rendered
    assert f"ENC {_PLAIN_SECRET}" not in rendered


# ---------------------------------------------------------------------------
# Guards against the gap re-opening
# ---------------------------------------------------------------------------


def test_every_radius_rendering_codec_is_covered() -> None:
    """Fail when a codec renders RADIUS servers but is not gated here.

    This is the #461 shape: a shared policy only bites a target once
    that target actually calls it, so the roster has to be checked
    rather than assumed.
    """
    # `list_public_codecs` is the registry's own "offered as a target"
    # predicate — the same one the operator dropdown uses.  Scoping to
    # it excludes only the hidden `mock` reference codec, and does so
    # by asking the registry rather than hardcoding a skip, so a codec
    # that later becomes public is covered automatically.
    ungated: list[str] = []
    for name in list_public_codecs():
        codec = get_codec(name)
        try:
            rendered = codec.render(_tree(_FORTI_SECRET, "fortigate_cli"))
        except Exception:
            # A codec that cannot render this tree at all cannot leak.
            continue
        if _BLOB_BODY in rendered and name != "fortigate_cli":
            ungated.append(name)

    assert not ungated, (
        f"these codecs emit a foreign encrypted RADIUS secret: {ungated}. "
        f"Add the _radius_secrets gate to each, and add it to "
        f"_RENDERING_TARGETS in this module."
    )


def test_radius_secret_envelope_registry_is_complete() -> None:
    """Every envelope a parser applies must be registered in the policy.

    An envelope the policy has never heard of classifies as ``unknown``
    and is refused — safe, but it would silently stop a legitimate
    migration.  Registering it is the deliberate act; this test makes
    forgetting loud.
    """
    envelopes_seen: set[str] = set()
    for name in list_public_codecs():
        codec = get_codec(name)
        for fixture_text in _SECRET_BEARING_SNIPPETS.get(name, ()):
            try:
                intent = codec.parse(fixture_text)
            except Exception:
                continue
            for server in intent.radius_servers:
                if ":" in server.key[:16]:
                    envelopes_seen.add(
                        server.key.split(":", 1)[0] + ":"
                    )

    unregistered = envelopes_seen - set(_KNOWN_ENVELOPES)
    assert not unregistered, (
        f"parsers apply RADIUS secret envelopes the policy does not "
        f"know: {sorted(unregistered)}. Register each in "
        f"_KNOWN_ENVELOPES with the kind it denotes."
    )


#: Minimal per-codec snippets that carry a RADIUS secret, used to
#: discover which envelopes parsers actually apply.
_SECRET_BEARING_SNIPPETS: dict[str, tuple[str, ...]] = {
    "fortigate_cli": (
        'config user radius\n'
        '    edit "radius-1"\n'
        '        set server "10.0.0.1"\n'
        '        set secret ENC SomeBlobValue==\n'
        "    next\n"
        "end\n",
    ),
    "aruba_aoss": (
        'radius-server host 10.0.0.1 key "SomeSecret"\n',
    ),
}
