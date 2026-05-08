"""Aruba AOS-S render: loopback / OOBM / unmigratable-hash paths.

User-reported regression — pasting an Arista config (with
`Loopback0`, `Management1`, and a sha512 user hash) targeting Aruba
silently dropped the loopback and the management interface, and
emitted the sha512 hash as `plaintext "arista:sha512:..."` (which
AOS-S would either reject at deploy or, worse, accept as a literal
plaintext password equal to the hash text — severe security bug).

Vendor-doc grounding (verified):
* AOS-S 16.04+ supports `interface loopback <0-7>` (Aruba Basic
  Operation Guide, "Managing loopback interfaces").  ``lo-0`` is
  reserved for ::1/128, so user-creatable IDs are 1-7.
* AOS-S has a dedicated `oobm` top-level configuration block
  (Aruba MCG, "Out-of-Band Management").  IPv4 `ip address` and
  `ip default-gateway` go inside the block.
* AOS-S accepts `plaintext`, `sha1`, `sha256` hash forms only
  (Aruba ASG 16.11, "Setting passwords and usernames").  sha512
  / Cisco type-5 / type-9 / type-7 / bcrypt / fortios-ENC are
  unmigratable and must surface as comment-form review lines.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLocalUser,
)
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.aruba_aoss.render import _split_aos_hash

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Loopback render
# ---------------------------------------------------------------------------


def test_render_loopback_emits_aos_s_form() -> None:
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="loopback1",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="10.0.255.33", prefix_length=32,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface loopback1" in out
    assert "ip address 10.0.255.33/32" in out
    # Loopback is always-up — no `enable` / `disable` / `routing`
    # lines should leak from the physical-port code path.
    assert "   enable" not in out
    assert "   routing" not in out


def test_render_loopback_with_ipv6() -> None:
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="loopback2",
            ipv6_addresses=[CanonicalIPv6Address(
                ip="2001:db8::1", prefix_length=128, scope="global",
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert "interface loopback2" in out
    assert "ipv6 address 2001:db8::1/128" in out


# ---------------------------------------------------------------------------
# OOBM render
# ---------------------------------------------------------------------------


def test_render_oobm_emits_top_level_block_with_ipv4() -> None:
    """OOBM is NOT a regular `interface oobm` stanza — it's a
    dedicated top-level configuration block."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="oobm",
            ipv4_addresses=[CanonicalIPv4Address(
                ip="192.168.100.62", prefix_length=24,
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    # The dedicated top-level block opens with bare `oobm`, not
    # `interface oobm`.
    assert "oobm\n" in out
    assert "interface oobm" not in out
    assert "ip address 192.168.100.62/24" in out


def test_render_oobm_ipv6_emits_review_comment() -> None:
    """The `oobm ipv6 default-gateway` form is doc-verified, but
    `ipv6 address` inside the oobm context is NOT documented for
    AOS-S as of this writing.  The renderer emits a comment-form
    line flagging the field for operator review rather than
    guessing the syntax."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="oobm",
            ipv6_addresses=[CanonicalIPv6Address(
                ip="fc00:192:168:100::62", prefix_length=64,
                scope="global",
            )],
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    # The IPv6 address is in the output, but as a comment marker.
    assert "; ipv6 address fc00:192:168:100::62/64" in out
    # No bare `ipv6 address` line that AOS-S would reject.
    assert "\n   ipv6 address fc00:192:168:100::62/64\n" not in out


# ---------------------------------------------------------------------------
# Unmigratable hash forms
# ---------------------------------------------------------------------------


def test_split_aos_hash_native_sha1() -> None:
    alg, val = _split_aos_hash("sha1:abc123")
    assert alg == "sha1"
    assert val == "abc123"


def test_split_aos_hash_native_sha256() -> None:
    alg, val = _split_aos_hash("sha256:def456")
    assert alg == "sha256"
    assert val == "def456"


def test_split_aos_hash_arista_sha512_unmigratable() -> None:
    """`arista:sha512:$6$...` from Arista source — AOS-S can't
    consume sha512.  Must surface as the unmigratable sentinel."""
    alg, val = _split_aos_hash("arista:sha512:$6$salt$hash")
    assert alg == "__unmigratable__"
    assert val == "sha512"


def test_split_aos_hash_cisco_type_9_unmigratable() -> None:
    alg, val = _split_aos_hash("9 $9$cisco$scrypt$hash")
    assert alg == "__unmigratable__"
    assert val == "9"


def test_split_aos_hash_bcrypt_unmigratable() -> None:
    alg, val = _split_aos_hash("bcrypt:$2y$10$opnsense$hash")
    assert alg == "__unmigratable__"
    assert val == "bcrypt"


def test_render_user_with_sha512_emits_comment_review() -> None:
    """User from Arista with sha512 hash must NOT emit
    `password manager user-name "X" plaintext "arista:sha512:..."`
    (security bug: AOS-S would accept the prefixed string as the
    literal plaintext password).  Render emits a comment-form
    review line instead, with the hash format name in plain text
    so the operator knows what to reset from."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="aaa",
            privilege_level=15,
            hashed_password="arista:sha512:$6$1b/rOJXKhrCHmRXC$fakeHash",
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    # Comment marker (leading ";") so the line is inert.
    assert '; password manager user-name "aaa"' in out
    # Carries the source hash format name so operator knows what
    # they're resetting from.
    assert "sha512" in out
    assert "review" in out
    # The original hash MUST NOT leak into rendered output.
    assert "$6$" not in out
    assert "fakeHash" not in out


def test_render_user_with_sha256_emits_native_form() -> None:
    """sha256 IS supported by AOS-S — must emit the native form,
    not the unmigratable comment."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="ops",
            privilege_level=15,
            hashed_password=(
                "sha256:abc123abc123abc123abc123abc123abc123abc123"
                "abc123abc123abc1"
            ),
        )],
    )
    out = ArubaAOSSCodec().render(intent)
    assert 'password manager user-name "ops" sha256 ' in out
    # Not a comment.
    assert '; password manager user-name "ops"' not in out


# ---------------------------------------------------------------------------
# End-to-end: arista source → aruba target
# ---------------------------------------------------------------------------


def test_arista_to_aruba_loopback_management_user_round_trip() -> None:
    """User-reported regression case: Arista A-EOS1 config with
    Loopback0, Management1 (IPv4 + IPv6), and a sha512 user hash
    must render to AOS-S with all three carrying their semantic
    forward, not silently dropped."""
    from netcanon.migration.canonical.port_names import (
        translate_port_names,
    )
    from netcanon.migration.codecs.arista_eos.codec import (
        AristaEOSCodec,
    )
    from netcanon.migration.codecs.arista_eos.parse import (
        parse_intent as arista_parse,
    )

    src_text = (
        "hostname EOS1\n"
        "!\n"
        "username aaa privilege 15 secret sha512 "
        "$6$1b/rOJXKhrCHmRXC$fakeHashForTesting\n"
        "!\n"
        "interface Ethernet1\n"
        "   no switchport\n"
        "   ip address 10.0.0.7/31\n"
        "!\n"
        "interface Loopback0\n"
        "   ip address 10.0.255.33/32\n"
        "!\n"
        "interface Management1\n"
        "   ip address 192.168.100.62/24\n"
        "   ipv6 address fc00:192:168:100::62/64\n"
        "!\n"
        "ip route 0.0.0.0/0 192.168.100.1\n"
        "end\n"
    )
    intent = arista_parse(src_text)
    src_codec = AristaEOSCodec()
    tgt_codec = ArubaAOSSCodec()
    translate_port_names(intent, src_codec, tgt_codec, rename_map=None)
    out = tgt_codec.render(intent)

    # Loopback survives.
    assert "interface loopback1" in out
    assert "ip address 10.0.255.33/32" in out

    # Management1 → top-level oobm block.
    assert "oobm\n" in out
    assert "ip address 192.168.100.62/24" in out

    # Ethernet1 still maps to physical port 1.
    assert "interface 1" in out
    assert "ip address 10.0.0.7/31" in out

    # sha512 hash → comment-form review line, no leak of $6$ hash.
    assert '; password manager user-name "aaa"' in out
    assert "sha512" in out
    assert "$6$" not in out

    # Default route → ip default-gateway.
    assert "ip default-gateway 192.168.100.1" in out
