"""
Programmatic icon generation for the desktop application.

Icons are generated at runtime using Pillow so no binary assets need to be
committed to the repository.  The icon uses the same colour palette as the
web UI (dark navy background, light-blue "NC" logotype).

Usage::

    from netconfig_desktop.icons import generate_tray_image, write_ico

    # PIL.Image for pystray
    tray_image = generate_tray_image()

    # Write .ico file to disk (required by pywebview for window/taskbar icon)
    ico_path = write_ico(Path(tempfile.gettempdir()) / "netconfig.ico")
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

# Colour constants matching the web UI (base.html)
_BG_DARK_NAVY = (26, 26, 46, 255)
_ACCENT_BLUE = (126, 184, 247, 255)
_TEXT_WHITE = (238, 238, 238, 255)


def _draw_icon(size: int) -> "PIL.Image.Image":  # type: ignore[name-defined]
    """Draw a single-size Netcanon icon.

    Renders a dark-navy rounded rectangle with a bold "NC" monogram in
    light blue.  Falls back to ``ImageFont.load_default()`` if no system
    TrueType font is available.

    Args:
        size: Edge length in pixels (the icon is always square).

    Returns:
        An RGBA ``PIL.Image.Image`` of the requested size.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(1, size // 10)
    radius = max(2, size // 6)
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=radius,
        fill=_BG_DARK_NAVY,
    )

    font_size = max(8, int(size * 0.38))
    font = None
    for face in ("arialbd.ttf", "Arial Bold.ttf", "arial.ttf", "Arial.ttf"):
        try:
            from PIL import ImageFont as _IF

            font = _IF.truetype(face, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        from PIL import ImageFont as _IF

        font = _IF.load_default()

    draw.text(
        (size / 2, size / 2),
        "NC",
        fill=_ACCENT_BLUE,
        font=font,
        anchor="mm",
    )
    return img


def generate_tray_image(size: int = 64) -> "PIL.Image.Image":  # type: ignore[name-defined]
    """Return a ``PIL.Image`` suitable for ``pystray.Icon``.

    Args:
        size: Icon size in pixels (default 64 × 64).

    Returns:
        A square RGBA ``PIL.Image``.
    """
    return _draw_icon(size)


def write_ico(path: Path | None = None) -> Path:
    """Write a multi-resolution ``.ico`` file and return its path.

    The ICO contains images at 16, 32, 48, 128, and 256 pixels — the full
    set required for Windows taskbar, Start Menu, and explorer thumbnails.

    Args:
        path: Destination path for the ``.ico`` file.  If ``None``, a temp
            file under ``%TEMP%`` is used.

    Returns:
        The absolute path to the written ``.ico`` file.
    """
    if path is None:
        path = Path(tempfile.gettempdir()) / "netconfig.ico"

    sizes = [16, 32, 48, 128, 256]
    images = [_draw_icon(s) for s in sizes]

    # PIL saves multi-size ICO by passing a list of sizes.
    images[0].save(
        str(path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    return path
