"""Render the demo whitepaper Markdown into a self-contained, styled HTML page.

Usage::

    python tools/render_whitepaper.py [--in docs/DEMO_WHITEPAPER.md]
                                      [--out frontend/whitepaper.html]
                                      [--values path/to/values.json] [--check]

Dependency-free by design: this script runs at deploy time on the demo host,
and the demo's whole ethos is a tiny, auditable trusted stack -- so it uses
only the Python 3.11+ standard library.  It implements a *focused*
Markdown-to-HTML converter covering exactly the constructs the whitepaper
uses (ATX headings, paragraphs, bold/italic/inline-code, links, flat
unordered/ordered lists, GitHub-style pipe tables, fenced code blocks,
horizontal rules, blockquotes).  It is NOT a general-purpose Markdown engine.

Placeholder substitution: the Markdown may contain ``<UPPER_SNAKE>`` tokens
(e.g. ``<REPO_DEPLOY_URL>``, sha256 digests inside the reproducibility code
block).  ``--values`` supplies a JSON map of token name -> replacement text;
any token left unfilled renders visibly as an amber ``<mark class="ph">``
chip (never silently blanked), and a "template copy" banner is injected at
the top of the page.  ``--check`` re-renders in memory and exits non-zero if
the committed ``--out`` file differs (drift detection for CI).
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Placeholder handling
# ---------------------------------------------------------------------------

# A placeholder token is ASCII UPPER_SNAKE inside literal angle brackets.
_TOKEN_RE = re.compile(r"<([A-Z][A-Z0-9_]*)>")

# Unfilled tokens are swapped for control-char sentinels *before* rendering so
# they survive HTML escaping untouched, then swapped for real <mark> markup in
# a final pass over the rendered body.  \x00/\x01 never occur in the source.
_PH_START, _PH_END = "\x00", "\x01"
_SENTINEL_RE = re.compile("\x00([A-Z][A-Z0-9_]*)\x01")

# Inline-stash sentinels (protect emitted tags from the emphasis regexes).
_STASH_TOKEN_RE = re.compile("\x02(\\d+)\x03")


def fill_placeholders(md: str, values: dict[str, str]) -> tuple[str, set[str]]:
    """Substitute known ``<KEY>`` tokens; sentinel-mark the rest.

    Returns the transformed Markdown and the set of token names that were
    left unfilled.  Unfilled tokens become control-char sentinels which the
    render pipeline later turns into visible ``<mark class="ph">`` chips.
    """
    for key, val in values.items():
        md = md.replace(f"<{key}>", str(val))

    unfilled: set[str] = set()

    def _mark(m: re.Match[str]) -> str:
        unfilled.add(m.group(1))
        return f"{_PH_START}{m.group(1)}{_PH_END}"

    return _TOKEN_RE.sub(_mark, md), unfilled


# ---------------------------------------------------------------------------
# Markdown -> HTML converter
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s*---+\s*$")
_UL_RE = re.compile(r"^\s{0,3}[-*]\s+(.*)$")
_OL_RE = re.compile(r"^\s{0,3}\d+\.\s+(.*)$")
# GitHub table separator row: |---|:---:|---| (leading/trailing pipes optional)
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_STAR_EM_RE = re.compile(r"(?<!\*)\*([^*\s](?:[^*]*[^*\s])?)\*(?!\*)")
_UNDER_EM_RE = re.compile(r"(?<!\w)_([^_]+)_(?!\w)")
_CODE_SPAN_RE = re.compile(r"(`[^`]+`)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _escape(text: str) -> str:
    """HTML-escape & < > (attribute quoting is handled at emit sites)."""
    return html.escape(text, quote=False)


def _emphasis(s: str) -> str:
    """Apply bold then italic markup to already-escaped text."""
    s = _BOLD_RE.sub(r"<strong>\1</strong>", s)
    s = _STAR_EM_RE.sub(r"<em>\1</em>", s)
    return _UNDER_EM_RE.sub(r"<em>\1</em>", s)


def _render_inline(text: str) -> str:
    """Render inline Markdown (code spans, links, bold, italic) to HTML.

    Code spans are extracted first and receive no further formatting; links
    are emitted next and stashed so the emphasis regexes cannot mangle
    underscores or asterisks inside hrefs.
    """
    stash: list[str] = []

    def _keep(rendered: str) -> str:
        stash.append(rendered)
        return f"\x02{len(stash) - 1}\x03"

    out: list[str] = []
    for part in _CODE_SPAN_RE.split(text):
        if part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(_keep(f"<code>{_escape(part[1:-1])}</code>"))
        else:
            out.append(_escape(part))
    s = "".join(out)

    def _link(m: re.Match[str]) -> str:
        label, href = m.group(1), m.group(2)
        href = href.replace('"', "&quot;")
        return _keep(f'<a href="{href}">{_emphasis(label)}</a>')

    s = _LINK_RE.sub(_link, s)
    s = _emphasis(s)

    # Restore stashed spans (looped: link labels may contain code tokens).
    while _STASH_TOKEN_RE.search(s):
        s = _STASH_TOKEN_RE.sub(lambda m: stash[int(m.group(1))], s)
    return s


def _slugify(text: str, used: dict[str, int]) -> str:
    """Derive a unique anchor id from heading text (GitHub-ish slugs)."""
    plain = re.sub(r"[`*_\[\]()]", "", text)
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "section"
    n = used.get(slug, 0)
    used[slug] = n + 1
    return slug if n == 0 else f"{slug}-{n}"


def _is_block_start(line: str) -> bool:
    """True when *line* opens a non-paragraph block (terminates a paragraph)."""
    ls = line.lstrip()
    return bool(
        not line.strip()
        or ls.startswith(("```", ">"))
        or _HEADING_RE.match(line)
        or _HR_RE.match(line)
        or _UL_RE.match(line)
        or _OL_RE.match(line)
    )


def _split_table_row(line: str) -> list[str]:
    """Split a pipe-table row into stripped cell strings."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _render_table(lines: list[str], i: int) -> tuple[str, int]:
    """Render a pipe table starting at ``lines[i]``; return (html, next_i)."""
    header = _split_table_row(lines[i])
    i += 2  # skip header + separator rows
    body_rows: list[list[str]] = []
    while i < len(lines) and "|" in lines[i] and lines[i].strip():
        body_rows.append(_split_table_row(lines[i]))
        i += 1

    parts = ['<div class="table-wrap">\n<table>\n<thead>\n<tr>']
    parts.extend(f"<th>{_render_inline(cell)}</th>" for cell in header)
    parts.append("</tr>\n</thead>\n<tbody>")
    for row in body_rows:
        # Pad short rows so every <tr> has the header's column count.
        row = row + [""] * (len(header) - len(row))
        cells = "".join(f"<td>{_render_inline(c)}</td>" for c in row[: len(header)])
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</tbody>\n</table>\n</div>")
    return "\n".join(parts), i


def _render_list(lines: list[str], i: int, marker_re: re.Pattern[str], tag: str) -> tuple[str, int]:
    """Render a flat list (ul/ol) starting at ``lines[i]``."""
    items: list[str] = []
    while i < len(lines):
        m = marker_re.match(lines[i])
        if not m:
            break
        items.append(f"<li>{_render_inline(m.group(1))}</li>")
        i += 1
    return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>", i


def _render_blocks(lines: list[str], used_slugs: dict[str, int]) -> str:
    """Render a sequence of Markdown lines to block-level HTML."""
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if line.lstrip().startswith("```"):  # fenced code block
            i += 1
            code: list[str] = []
            while i < n and not lines[i].lstrip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # closing fence (harmless past EOF)
            out.append(f"<pre><code>{_escape(chr(10).join(code))}</code></pre>")
            continue

        m = _HEADING_RE.match(line)
        if m:
            level, text = len(m.group(1)), m.group(2)
            slug = _slugify(text, used_slugs)
            out.append(f'<h{level} id="{slug}">{_render_inline(text)}</h{level}>')
            i += 1
            continue

        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if line.lstrip().startswith(">"):  # blockquote (rendered recursively)
            quoted: list[str] = []
            while i < n and lines[i].lstrip().startswith(">"):
                inner = lines[i].lstrip()[1:]
                quoted.append(inner[1:] if inner.startswith(" ") else inner)
                i += 1
            out.append(f"<blockquote>\n{_render_blocks(quoted, used_slugs)}\n</blockquote>")
            continue

        if "|" in line and i + 1 < n and "|" in lines[i + 1] and _TABLE_SEP_RE.match(lines[i + 1]):
            block, i = _render_table(lines, i)
            out.append(block)
            continue

        if _UL_RE.match(line):
            block, i = _render_list(lines, i, _UL_RE, "ul")
            out.append(block)
            continue

        if _OL_RE.match(line):
            block, i = _render_list(lines, i, _OL_RE, "ol")
            out.append(block)
            continue

        para = [line.strip()]  # paragraph: gather until blank line / new block
        i += 1
        while i < n and not _is_block_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_render_inline(' '.join(para))}</p>")

    return "\n".join(out)


def render_markdown(md: str) -> str:
    """Convert whitepaper-subset Markdown to body HTML."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return _render_blocks(lines, {})


# ---------------------------------------------------------------------------
# Page shell (doctype + head + inline theme + nav + footer)
# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --nc-indigo: #4f46e5; --nc-indigo-hover: #4338ca; --nc-indigo-fg: #ffffff;
  --nc-amber: #b45309; --nc-amber-bg: #fffbeb; --nc-amber-border: #fcd34d;
  --nc-green: #15803d; --nc-red: #dc2626; --nc-red-hover: #b91c1c;
  --nc-bg: #ffffff; --nc-surface: #f8fafc; --nc-surface-2: #f1f5f9;
  --nc-text: #0f172a; --nc-muted: #64748b; --nc-border: #e2e8f0;
  --nc-radius: 10px; --nc-shadow: 0 1px 3px rgba(15,23,42,.08), 0 1px 2px rgba(15,23,42,.04);
  --nc-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --nc-sans: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --nc-indigo: #818cf8; --nc-indigo-hover: #a5b4fc; --nc-indigo-fg: #1e1b4b;
    --nc-amber: #fbbf24; --nc-amber-bg: #2a2410; --nc-amber-border: #a16207;
    --nc-green: #4ade80; --nc-red: #f87171; --nc-red-hover: #fca5a5;
    --nc-bg: #0f172a; --nc-surface: #1e293b; --nc-surface-2: #334155;
    --nc-text: #e2e8f0; --nc-muted: #94a3b8; --nc-border: #334155;
    --nc-shadow: 0 1px 3px rgba(0,0,0,.4);
  }
}
* { box-sizing: border-box; }
body {
  font-family: var(--nc-sans); color: var(--nc-text); background: var(--nc-bg);
  line-height: 1.6; margin: 0;
}
.topnav {
  background: var(--nc-surface); border-bottom: 1px solid var(--nc-border);
  padding: .75rem 1.25rem;
}
.topnav a { color: var(--nc-indigo); text-decoration: none; font-weight: 600; }
.topnav a:hover { color: var(--nc-indigo-hover); text-decoration: underline; }
.prose { max-width: 760px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
.prose a { color: var(--nc-indigo); }
.prose a:hover { color: var(--nc-indigo-hover); }
h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 2rem 0 .75rem; }
h1 { font-size: 2rem; margin-top: .5rem; }
h2 { font-size: 1.5rem; border-bottom: 1px solid var(--nc-border); padding-bottom: .3rem; }
h3 { font-size: 1.2rem; }
p, ul, ol, blockquote { margin: 0 0 1rem; }
ul, ol { padding-left: 1.5rem; }
li { margin: .25rem 0; }
code {
  font-family: var(--nc-mono); font-size: .9em; background: var(--nc-surface-2);
  padding: .1rem .35rem; border-radius: 6px;
}
pre {
  font-family: var(--nc-mono); font-size: .85rem; background: var(--nc-surface-2);
  border: 1px solid var(--nc-border); border-radius: var(--nc-radius);
  padding: 1rem; overflow-x: auto; margin: 0 0 1rem;
}
pre code { background: transparent; padding: 0; border-radius: 0; font-size: inherit; }
blockquote {
  border-left: 3px solid var(--nc-indigo); padding: .25rem 0 .25rem 1rem;
  color: var(--nc-muted); background: var(--nc-surface);
  border-radius: 0 var(--nc-radius) var(--nc-radius) 0;
}
blockquote p:last-child { margin-bottom: 0; }
hr { border: none; border-top: 1px solid var(--nc-border); margin: 2.5rem 0; }
.table-wrap { overflow-x: auto; margin: 0 0 1rem; }
table { border-collapse: collapse; width: 100%; font-size: .875rem; }
th, td {
  padding: .5rem .75rem; border-bottom: 1px solid var(--nc-border);
  text-align: left; vertical-align: top;
}
th { background: var(--nc-surface-2); font-weight: 600; white-space: nowrap; }
mark.ph {
  background: var(--nc-amber-bg); color: var(--nc-amber);
  border: 1px solid var(--nc-amber-border); border-radius: 4px;
  padding: 0 .3rem; font-family: var(--nc-mono); font-size: .9em;
}
.template-banner {
  max-width: 760px; margin: 1.5rem auto 0; padding: .9rem 1.1rem;
  background: var(--nc-amber-bg); color: var(--nc-amber);
  border: 1px solid var(--nc-amber-border); border-radius: var(--nc-radius);
  box-shadow: var(--nc-shadow); font-size: .95rem;
}
.btn {
  display: inline-block; background: var(--nc-indigo); color: var(--nc-indigo-fg);
  border: none; border-radius: var(--nc-radius); padding: .6rem 1.1rem;
  cursor: pointer; font: inherit; text-decoration: none;
}
.btn:hover { background: var(--nc-indigo-hover); }
.btn-danger { background: var(--nc-red); color: #ffffff; }
.btn-danger:hover { background: var(--nc-red-hover); }
.footer {
  border-top: 1px solid var(--nc-border); color: var(--nc-muted);
  text-align: center; padding: 1.5rem 1.25rem 2.5rem; font-size: .875rem;
}
.footer a { color: var(--nc-indigo); }
"""

_BANNER_HTML = (
    '<div class="template-banner"><strong>Template copy.</strong> '
    "This is the in-repo TEMPLATE copy of the whitepaper. The live demo fills "
    "the reproducibility block (image digests, hashes, deploy date) at deploy "
    "time. The live site may run an older published bundle than the newest "
    "repo commit — the block on the live site describes the running "
    "system.</div>\n"
)

_NAV_HTML = '<nav class="topnav"><a href="/">← Back to the demo</a></nav>\n'

_FOOTER_HTML = (
    '<footer class="footer">netcanon is open source: '
    '<a href="https://github.com/netcanon/netcanon">github.com/netcanon/netcanon</a>'
    "</footer>\n"
)


def build_page(body_html: str, has_unfilled: bool) -> str:
    """Wrap rendered body HTML in the full standalone document shell."""
    banner = _BANNER_HTML if has_unfilled else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>netcanon demo — privacy &amp; ephemerality</title>\n"
        "<style>\n" + _CSS + "</style>\n"
        "</head>\n"
        "<body>\n" + _NAV_HTML + banner
        + '<main class="prose">\n' + body_html + "\n</main>\n"
        + _FOOTER_HTML + "</body>\n"
        "</html>\n"
    )


def render_document(md: str, values: dict[str, str]) -> tuple[str, set[str]]:
    """Full pipeline: placeholders -> Markdown -> page. Returns (html, unfilled)."""
    md, unfilled = fill_placeholders(md, values)
    body = render_markdown(md)
    body = _SENTINEL_RE.sub(lambda m: f'<mark class="ph">&lt;{m.group(1)}&gt;</mark>', body)
    return build_page(body, bool(unfilled)), unfilled


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the demo whitepaper Markdown to standalone HTML (stdlib only).",
    )
    parser.add_argument("--in", dest="src", type=Path, default=Path("docs/DEMO_WHITEPAPER.md"),
                        help="input Markdown file (default: docs/DEMO_WHITEPAPER.md)")
    parser.add_argument("--out", dest="out", type=Path, default=Path("frontend/whitepaper.html"),
                        help="output HTML file (default: frontend/whitepaper.html)")
    parser.add_argument("--values", type=Path, default=None,
                        help="JSON map of placeholder name -> value (fills <NAME> tokens)")
    parser.add_argument("--check", action="store_true",
                        help="render in-memory and exit non-zero if --out differs (drift check)")
    args = parser.parse_args(argv)

    md = args.src.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    if args.values is not None:
        values = json.loads(args.values.read_text(encoding="utf-8"))

    rendered, unfilled = render_document(md, values)

    if unfilled:
        names = ", ".join(sorted(unfilled))
        print(f"note: {len(unfilled)} unfilled placeholder(s) rendered as pending: {names}",
              file=sys.stderr)

    if args.check:
        if not args.out.exists():
            print(f"check FAILED: {args.out} does not exist (run without --check to create it)",
                  file=sys.stderr)
            return 1
        with args.out.open(encoding="utf-8", newline="") as f:
            current = f.read()
        if _normalize_newlines(current) == _normalize_newlines(rendered):
            print(f"check OK: {args.out} is up to date")
            return 0
        diff = difflib.unified_diff(
            _normalize_newlines(current).splitlines(keepends=True),
            _normalize_newlines(rendered).splitlines(keepends=True),
            fromfile=str(args.out),
            tofile="freshly rendered",
        )
        print(f"check FAILED: {args.out} differs from a fresh render of {args.src}:",
              file=sys.stderr)
        for line in list(diff)[:60]:
            sys.stderr.write(line)
        print("\n(re-run without --check to regenerate)", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        f.write(rendered)
    kind = "template copy (banner shown)" if unfilled else "fully filled copy (no banner)"
    print(f"wrote {args.out}: {kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
