"""Pixel-native pygame drawing helpers

The UI draws whole strings and rects directly onto the window Surface. These are the
small shared primitives (text, multi-color lines, bars); layout and composition live
in each UI processor.
"""

import pygame

from src.components import Message
from src.constants import RGB, UI_BLACK, UI_WHITE

# Vertical stride between text rows in a panel, and the inner padding from its border to content.
LINE_H = 22
PANEL_PAD = 12


def blit_text(surface: pygame.Surface, font: pygame.font.Font, text: str, x: int, y: int, fg: RGB) -> int:
    """Blit `text` at (x, y) and return its pixel width, so callers can chain segments."""
    glyph = font.render(text, True, fg)
    surface.blit(glyph, (x, y))
    return glyph.get_width()


def blit_text_right(surface: pygame.Surface, font: pygame.font.Font, text: str, right: int, y: int, fg: RGB) -> None:
    """Blit `text` so its right edge lands at pixel x=`right` — for right-aligned value columns."""
    surface.blit(font.render(text, True, fg), (right - font.size(text)[0], y))


def blit_segments(surface: pygame.Surface, font: pygame.font.Font, segments: Message, x: int, y: int) -> None:
    """Blit a Message (a list of (text, color) segments) left-to-right on one line."""
    cursor_x = x
    for text, color in segments:
        cursor_x += blit_text(surface, font, text, cursor_x, y, color)


def bar(surface: pygame.Surface, x: int, y: int, width: int, height: int, ratio: float, fill: RGB, track: RGB) -> None:
    """A horizontal bar: the full-width `track`, then a `fill` covering `ratio` (0..1) of it."""
    pygame.draw.rect(surface, track, (x, y, width, height))
    filled = int(max(0.0, min(1.0, ratio)) * width)
    if filled > 0:
        pygame.draw.rect(surface, fill, (x, y, filled, height))


# Reusable overlay surfaces for fill_alpha, keyed by size. AoE shading / cast bursts call it once
# per tile, so a per-call allocation would churn radius**2 surfaces a frame; we fill and reblit one.
_alpha_overlays: dict[tuple[int, int], pygame.Surface] = {}


def fill_alpha(surface: pygame.Surface, x: int, y: int, width: int, height: int, color: RGB, alpha: float) -> None:
    """Blit a translucent `color` rect (alpha 0..1) over the surface — for AoE shading, cast
    bursts, and the damage flash, which tint what's already drawn rather than covering it."""
    overlay = _alpha_overlays.get((width, height))
    if overlay is None:
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        _alpha_overlays[(width, height)] = overlay
    overlay.fill((color[0], color[1], color[2], max(0, min(255, int(alpha * 255)))))
    surface.blit(overlay, (x, y))


def panel_height(body_rows: int) -> int:
    """The pixel height of a `panel` with `body_rows` content rows: the title line plus that many
    rows, framed by the top/bottom padding."""
    return PANEL_PAD + LINE_H + body_rows * LINE_H + PANEL_PAD


def panel(surface: pygame.Surface, font: pygame.font.Font, width: int, height: int, title: str) -> pygame.Rect:
    """Draw a filled, bordered box `width` x `height` pixels, centered on the surface, with a
    centered `title` near the top. Returns the inner content rect (below the title, inset by the
    padding); callers lay out rows at `content.y + row * LINE_H` and columns at `content.x + dx`."""
    sw, sh = surface.get_size()
    x, y = (sw - width) // 2, (sh - height) // 2
    pygame.draw.rect(surface, UI_BLACK, (x, y, width, height))
    pygame.draw.rect(surface, UI_WHITE, (x, y, width, height), width=1)
    if title:
        blit_text(surface, font, title, x + (width - font.size(title)[0]) // 2, y + PANEL_PAD, UI_WHITE)
    top = y + PANEL_PAD + LINE_H
    return pygame.Rect(x + PANEL_PAD, top, width - 2 * PANEL_PAD, y + height - PANEL_PAD - top)


def scroll_arrows(surface: pygame.Surface, x: int, top_y: int, bottom_y: int, up: bool, down: bool, color: RGB) -> None:
    """Little triangles marking that a list scrolls further up/down (the font has no ▲▼ glyph)."""
    if up:
        pygame.draw.polygon(surface, color, [(x, top_y + 8), (x + 10, top_y + 8), (x + 5, top_y)])
    if down:
        pygame.draw.polygon(surface, color, [(x, bottom_y), (x + 10, bottom_y), (x + 5, bottom_y + 8)])
