"""
Unit tests for pure helpers inside ``paramiko_collector``.

We do NOT mock paramiko / SSHClient here (see CLAUDE.md hard rule:
integration tests patch ``netcanon.api.routes.backups.get_collector``
instead).  This file covers the pure-function helpers that have no
I/O dependency — currently ``_strip_command_echo``, which prevents
OPNsense backup files landing on disk with a literal ``cat /conf/
config.xml\\r\\r\\n`` preamble that breaks the migration parser.
"""
from __future__ import annotations

import pytest

from netcanon.collectors.paramiko_collector import _strip_command_echo

pytestmark = pytest.mark.unit


class TestStripCommandEcho:
    """``_strip_command_echo`` drops the echoed command line from the
    head of the paramiko-shell output.  The bug it fixes: OPNsense
    backups were written to disk with a literal
    ``cat /conf/config.xml\\r\\r\\n`` preamble before the ``<?xml``
    prolog, breaking ``ET.fromstring`` in the migration codec with
    ``syntax error: line 1, column 0``."""

    def test_strips_opnsense_command_with_crlf_preamble(self):
        """The canonical failure shape: OPNsense FreeBSD PTY echoes
        the command followed by ``\\r\\r\\n`` noise before the XML
        prolog.  The strip must remove both."""
        buf = (
            "cat /conf/config.xml\r\r\n"
            '<?xml version="1.0"?>\r\r\n'
            "<opnsense>\r\r\n"
            "  <theme>opnsense</theme>\r\r\n"
            "</opnsense>\r\r\n"
        )
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out.startswith('<?xml version="1.0"?>')

    def test_empty_command_returns_buffer_unchanged(self):
        """Defensive: caller passing empty string should no-op,
        not accidentally strip the head of the buffer."""
        buf = "<?xml version=\"1.0\"?>\n<opnsense/>\n"
        assert _strip_command_echo(buf, "") == buf

    def test_empty_buffer_returns_empty(self):
        assert _strip_command_echo("", "any cmd") == ""

    def test_command_not_in_head_returns_buffer_unchanged(self):
        """If the command string doesn't appear in the first 512
        bytes, don't strip — someone else's code path, don't
        trample valid output that happens to mention the command
        deeper in the file."""
        buf = "? some banner\n" + ("x" * 600) + " cat /conf/config.xml later\n"
        assert _strip_command_echo(buf, "cat /conf/config.xml") == buf

    def test_strips_lf_only_preamble(self):
        """Some PTYs emit just ``\\n`` not ``\\r\\r\\n``.  Must
        still strip."""
        buf = "cat /conf/config.xml\n<?xml version=\"1.0\"?>\n<opnsense/>\n"
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out.startswith('<?xml version="1.0"?>')

    def test_strips_with_trailing_whitespace_mix(self):
        """Tabs + spaces + CR + LF after the echo should all be
        absorbed."""
        buf = "cat /conf/config.xml \t\r\n\r\n<?xml?>\n"
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out.startswith("<?xml?>")

    def test_no_whitespace_after_echo_leaves_content_intact(self):
        """Edge case: if the echo is immediately followed by a
        non-whitespace byte (unlikely in practice), the strip
        must stop at the echo boundary — don't eat content."""
        buf = "cat /conf/config.xml<?xml?>\n"
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out.startswith("<?xml?>")

    def test_preserves_trailing_content_verbatim(self):
        """After stripping the head, everything past the whitespace
        run is preserved exactly — no accidental byte drops, no
        re-encoding."""
        body = (
            '<?xml version="1.0"?>\r\r\n<opnsense>\r\r\n'
            "  <system>\r\r\n    <hostname>fw-01</hostname>\r\r\n"
            "  </system>\r\r\n</opnsense>\r\r\n"
        )
        buf = "cat /conf/config.xml\r\r\n" + body
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out == body

    def test_handles_command_with_embedded_spaces(self):
        """Netmiko-style commands with args (e.g. ``show running-
        config | display set``) should also strip cleanly.  The
        helper is grammar-agnostic — substring match wins."""
        buf = (
            "show configuration | display set\r\n"
            "set system host-name sw1\n"
        )
        out = _strip_command_echo(buf, "show configuration | display set")
        assert out == "set system host-name sw1\n"

    def test_none_command_returns_buffer_unchanged(self):
        """_collect_output passes ``None`` when no command should
        be stripped (probe call site, for example).  Helper must
        tolerate head-trim skip while still potentially running
        the tail-prompt strip."""
        buf = "<?xml?>\n"
        # No command to match + no shell-prompt in the buffer →
        # identity.
        assert _strip_command_echo(buf, None) == buf  # type: ignore[arg-type]


class TestStripShellPromptTail:
    """The paramiko-shell buffer also leaks the RETURNING shell
    prompt at the tail — ``root@supergate:~ # `` appears after
    the command output completes.  This breaks OPNsense's XML
    parser a second time (line 4603, column 4 in the user's
    report) at the ``</opnsense>`` close.  The helper also
    strips this residue."""

    def test_strips_opnsense_style_prompt(self):
        """Canonical user-reported tail shape."""
        buf = (
            '<?xml version="1.0"?>\n'
            '<opnsense><system/></opnsense>\n'
            'root@supergate:~ # '
        )
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert "root@supergate" not in out
        assert out.rstrip().endswith("</opnsense>")

    def test_strips_with_short_prompt(self):
        """Generic ``user@host#`` form (root shell, minimal cwd)."""
        buf = "valid output\nroot@fw:~#"
        out = _strip_command_echo(buf, "cat foo")
        assert "root@fw" not in out

    def test_preserves_output_without_prompt(self):
        """No prompt in the buffer → head-strip only, identity on
        tail."""
        buf = "cat /conf/config.xml\n<?xml?>\n<opnsense/>\n"
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out.rstrip() == "<?xml?>\n<opnsense/>".rstrip()

    def test_prompt_mid_file_preserved(self):
        """A prompt-shaped line buried >512 bytes from the end
        must NOT trigger the tail strip (would destroy valid
        content).  The regex is anchored to the end-of-buffer
        window."""
        filler = "x" * 1000
        buf = (
            "cat /conf/config.xml\n"
            f"{filler}\n"
            "root@fake:~# comment inside output\n"
            f"{filler}\n"
            "valid output line\n"
        )
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        # The prompt-shaped line IS within the last 512 bytes? Let's
        # measure: filler is 1000 bytes, separator 2 bytes, prompt
        # ~30 bytes, filler 1000, trailing line ~20 bytes = ~2100
        # bytes after the prompt.  The prompt is >512 bytes from
        # the END so it should NOT be stripped.
        assert "comment inside output" in out
        assert "valid output line" in out

    def test_strips_both_head_and_tail_simultaneously(self):
        """The full user-reported shape: command echo at head,
        shell prompt at tail.  Both must be removed in one call."""
        buf = (
            "cat /conf/config.xml\r\r\n"
            '<?xml version="1.0"?>\n<opnsense/>\n'
            "root@host:~ # "
        )
        out = _strip_command_echo(buf, "cat /conf/config.xml")
        assert out.startswith('<?xml')
        assert "root@host" not in out
