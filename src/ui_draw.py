"""Pixel-native pygame drawing helpers

The UI draws whole strings and rects directly onto the window Surface. These are the
small shared primitives (text, multi-color lines, bars); layout and composition live
in each UI processor.
"""

import pygame

from src.components import Message
from src.constants import RGB, UI_BLACK, UI_WHITE

# A menu lays out on a logical character grid; these convert a (col, row) cell to pixels. The
# text itself is proportional, so columns are approximate gutters, not hard cell boundaries.
MENU_COL_W = 11
MENU_ROW_H = 22


def blit_text(surface: pygame.Surface, font: pygame.font.Font, text: str, x: int, y: int, fg: RGB) -> int:
    """Blit `text` at (x, y) and return its pixel width, so callers can chain segments."""
    glyph = font.render(text, True, fg)
    surface.blit(glyph, (x, y))
    return glyph.get_width()


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


def fill_alpha(surface: pygame.Surface, x: int, y: int, width: int, height: int, color: RGB, alpha: float) -> None:
    """Blit a translucent `color` rect (alpha 0..1) over the surface — for AoE shading, cast
    bursts, and the damage flash, which tint what's already drawn rather than covering it."""
    overlay = pygame.Surface((width, height), pygame.SRCALPHA)
    overlay.fill((color[0], color[1], color[2], max(0, min(255, int(alpha * 255)))))
    surface.blit(overlay, (x, y))


def panel(surface: pygame.Surface, font: pygame.font.Font, cols: int, rows: int, title: str) -> tuple[int, int]:
    """Draw a filled, bordered menu box `cols` x `rows` grid cells, centered on the surface, with
    a centered `title` near the top. Returns the pixel origin of its top-left cell, so callers
    place content with `cell(origin, col, row)`."""
    width, height = cols * MENU_COL_W, rows * MENU_ROW_H
    sw, sh = surface.get_size()
    x, y = (sw - width) // 2, (sh - height) // 2
    pygame.draw.rect(surface, UI_BLACK, (x, y, width, height))
    pygame.draw.rect(surface, UI_WHITE, (x, y, width, height), width=1)
    if title:
        blit_text(surface, font, title, x + (width - font.size(title)[0]) // 2, y + 2, UI_WHITE)
    return x, y


def cell(origin: tuple[int, int], col: int, row: int) -> tuple[int, int]:
    """The pixel position of grid cell (col, row) within a panel whose top-left is `origin`."""
    return origin[0] + col * MENU_COL_W, origin[1] + row * MENU_ROW_H


def scroll_arrows(surface: pygame.Surface, x: int, top_y: int, bottom_y: int, up: bool, down: bool, color: RGB) -> None:
    """Little triangles marking that a list scrolls further up/down (the font has no ▲▼ glyph)."""
    if up:
        pygame.draw.polygon(surface, color, [(x, top_y + 8), (x + 10, top_y + 8), (x + 5, top_y)])
    if down:
        pygame.draw.polygon(surface, color, [(x, bottom_y), (x + 10, bottom_y), (x + 5, bottom_y + 8)])
