"""
Reading what a page PAINTED, for E2E tests.

A class name is not a colour, and neither is a computed style.  The
theme's badge backgrounds are translucent tints, so an element's
``background-color`` says what was asked for and not what is on
screen: a tint laid over another tint is darker than either.  A test
that compared two computed colours once passed over a warning chip
whose text had a contrast of 2.7:1.

So a background is read here from a screenshot of the element, and a
token is turned into a colour by painting it on the same ground and
reading that.  Screenshots are decoded with the standard library: the
browser tier installs no imaging package.

Also here: the two helpers for the rename table's override lists,
whose target-port options are filled when a list is first used.
"""

from __future__ import annotations

import struct
import zlib
from collections import Counter

from playwright.sync_api import Locator, Page

RGB = tuple[int, int, int]


def png_pixels(data: bytes) -> tuple[int, int, list[RGB]]:
    """Width, height and pixels of an 8-bit RGB / RGBA PNG that is not
    interlaced -- what a browser screenshot is."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    at = 8
    width = height = channels = 0
    packed: list[bytes] = []
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + length]
        at += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour, _compress, _filter, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError(f"PNG kind not read here: depth {depth}, colour {colour}")
            channels = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            packed.append(body)
        elif kind == b"IEND":
            break
    raw = zlib.decompress(b"".join(packed))
    stride = width * channels
    before = bytearray(stride)
    pixels: list[RGB] = []
    at = 0
    for _row in range(height):
        how = raw[at]
        line = bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = before[i]
            corner = before[i - channels] if i >= channels else 0
            if how == 1:
                line[i] = (line[i] + left) & 255
            elif how == 2:
                line[i] = (line[i] + up) & 255
            elif how == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif how == 4:
                guess = left + up - corner
                by_left, by_up, by_corner = abs(guess - left), abs(guess - up), abs(guess - corner)
                if by_left <= by_up and by_left <= by_corner:
                    nearest = left
                elif by_up <= by_corner:
                    nearest = up
                else:
                    nearest = corner
                line[i] = (line[i] + nearest) & 255
        pixels.extend(
            (line[x * channels], line[x * channels + 1], line[x * channels + 2])
            for x in range(width)
        )
        before = line
    return width, height, pixels


def shot(locator: Locator) -> bytes:
    """A screenshot of *locator*'s box, as a PNG.

    Not ``locator.screenshot()``.  The rename modal is ``position:
    fixed``, and what is above its table scrolls inside it; for an
    element in there the element screenshot returned another part of
    the page whenever the window was scrolled, or the element had
    first to be scrolled into view -- the box was measured in one
    place and captured in another.  Here the element is brought into
    view first, the window is at its top (so the page's coordinates
    are the viewport's, whichever the capture means), two frames are
    let pass, and the viewport is captured, cut to the box."""
    box = locator.evaluate(
        """async (el) => {
            el.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'instant'});
            window.scrollTo(0, 0);
            await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
            const r = el.getBoundingClientRect();
            return {x: r.left, y: r.top, width: r.width, height: r.height};
        }"""
    )
    return locator.page.screenshot(clip=box)


def painted_background(locator: Locator) -> RGB:
    """The colour painted behind *locator*'s content: the commonest
    pixel of a screenshot of its box.  Text and an outline cover the
    smaller part of any element this is used on."""
    _width, _height, pixels = png_pixels(shot(locator))
    return Counter(pixels).most_common(1)[0][0]


def painted_token(page: Page, ground: str, token: str) -> RGB:
    """What ``background: var(<token>)`` paints on the ground the
    element matching *ground* (a CSS selector) is drawn on: a probe is
    put inside it, read, and removed."""
    page.evaluate(
        """([ground, token]) => {
            const probe = document.createElement('div');
            probe.id = 'painted-token-probe';
            probe.style.cssText = 'width:40px;height:16px;background:var(' + token + ')';
            document.querySelector(ground).prepend(probe);
        }""",
        [ground, token],
    )
    try:
        return painted_background(page.locator("#painted-token-probe"))
    finally:
        page.evaluate("document.getElementById('painted-token-probe').remove()")


def ink(locator: Locator) -> RGB:
    """The colour of *locator*'s text.  It must be opaque: then what
    was asked for is what is drawn."""
    red, green, blue, alpha = locator.evaluate(
        """(el) => {
            const canvas = document.createElement('canvas');
            canvas.width = canvas.height = 1;
            const pen = canvas.getContext('2d', {willReadFrequently: true});
            pen.fillStyle = getComputedStyle(el).color;
            pen.fillRect(0, 0, 1, 1);
            return Array.from(pen.getImageData(0, 0, 1, 1).data);
        }"""
    )
    assert alpha == 255, "the text colour is translucent; read it from pixels instead"
    return (red, green, blue)


def token_ink(page: Page, token: str) -> RGB:
    """The colour ``color: var(<token>)`` resolves to on this page."""
    page.evaluate(
        """(token) => {
            const probe = document.createElement('span');
            probe.id = 'token-ink-probe';
            probe.style.color = 'var(' + token + ')';
            document.body.appendChild(probe);
        }""",
        token,
    )
    try:
        return ink(page.locator("#token-ink-probe"))
    finally:
        page.evaluate("document.getElementById('token-ink-probe').remove()")


def _luminance(colour: RGB) -> float:
    def linear(part: int) -> float:
        value = part / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(part) for part in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: RGB, second: RGB) -> float:
    """The WCAG contrast ratio of two colours."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def alike(first: RGB, second: RGB, within: int = 2) -> bool:
    """Two painted colours that differ by no more than rounding."""
    return all(abs(a - b) <= within for a, b in zip(first, second, strict=True))


# ---------------------------------------------------------------------------
# The rename table's override lists
# ---------------------------------------------------------------------------


def override_options(page: Page, source: str) -> list[tuple[str, str]]:
    """``(value, text)`` of every option of *source*'s override list.

    The table makes a row's target-port options when the list is first
    used -- focused, or pressed -- so that two stacks of eight are not
    four hundred lists of four hundred options on every redraw.  This
    uses it the way a keyboard does."""
    override = page.locator(f'[data-testid="migrate-rename-override-{source}"]')
    override.focus()
    return [
        (value, text)
        for value, text in override.locator("option").evaluate_all(
            "els => els.map(e => [e.value, e.textContent])"
        )
    ]


def choose_override(page: Page, source: str, value: str) -> None:
    """Choose *value* in *source*'s override list (see
    :func:`override_options` for why it is focused first)."""
    override = page.locator(f'[data-testid="migrate-rename-override-{source}"]')
    override.focus()
    override.select_option(value=value)
