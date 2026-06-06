"""Pure presentation helpers for the UI systems.

These functions hold display-formatting math only (no ECS access), which keeps
them straightforward to unit-test independently of the tcod render pass.
"""

from collections import Counter

import tcod

from src.components import Effect, EffectType, ItemType, Message
from src.constants import RGB, TICKS_PER_SECOND, UI_WHITE


def format_recipe(combo: tuple[ItemType, ...]) -> str:
    """Render an ingredient combo with counts, e.g. '2x MYSTIC_HERB, ICE_SHARD'.

    Duplicates collapse to an 'Nx' prefix; singletons are shown bare. Ingredients
    are ordered by name so a given combo always reads the same way.
    """
    counts = Counter(combo)
    ordered = sorted(counts.items(), key=lambda c: c[0].name)
    parts = [(f'{n}x {itype.name}' if n > 1 else itype.name) for itype, n in ordered]
    return ', '.join(parts)


def format_spell_effects(effects: list[Effect]) -> str:
    """One-line readout of a spell's effects, e.g. 'Damage 25, Slow 3s'."""
    return ', '.join(_format_effect(effect) for effect in effects)


def _seconds(ticks: int) -> str:
    """Render a tick duration in seconds, dropping trailing zeros (90 -> '3s')."""
    return f'{round(ticks / TICKS_PER_SECOND, 1):g}s'


def _format_effect(effect: Effect) -> str:
    by_type = {
        EffectType.DAMAGE: f'Damage {effect.power}',
        EffectType.HEAL: f'Heal {effect.power}',
        EffectType.POISON: f'Poison {effect.power} over {_seconds(effect.duration)}',
        EffectType.REGEN: f'Regen {effect.power} over {_seconds(effect.duration)}',
        EffectType.SLOW: f'Slow {_seconds(effect.duration)}',
        EffectType.HASTE: f'Haste {_seconds(effect.duration)}',
    }
    return by_type.get(effect.type, effect.type.value)


def blend(base: RGB, color: RGB, alpha: float) -> RGB:
    """Linearly blend `color` over `base` by `alpha` (0 -> base, 1 -> color)."""
    r, g, b = (round(p * (1 - alpha) + q * alpha) for p, q in zip(base, color, strict=True))
    return r, g, b


def center_origin(console: tcod.console.Console, width: int, height: int) -> tuple[int, int]:
    """Return the top-left (x, y) for a box of the given size centered on the console."""
    return (console.width - width) // 2, (console.height - height) // 2


# Block-element glyphs whose filled half/quadrants tile into one continuous border.
# Each fills its cell, so adjacent border cells join seamlessly; box-drawing glyphs
# (─│┌┐) instead leave gaps in fonts that render them at their narrow native width.
_FRAME_TOP, _FRAME_BOTTOM, _FRAME_LEFT, _FRAME_RIGHT = '▀', '▄', '▌', '▐'
_FRAME_TL, _FRAME_TR, _FRAME_BL, _FRAME_BR = '▛', '▜', '▙', '▟'


def _draw_block_frame(
    console: tcod.console.Console,
    x: int,
    y: int,
    width: int,
    height: int,
    fg: tuple[int, int, int],
    bg: tuple[int, int, int] | None,
) -> None:
    """Draw a solid rectangular border from block elements, clearing the interior.

    Block half/quadrant glyphs fill their whole cell, so the border reads as an
    unbroken line in any font — unlike box-drawing glyphs, which the font may render
    too narrow to span the cell (leaving a dashed look).
    """
    console.draw_rect(x, y, width, height, ch=ord(' '), fg=fg, bg=bg)
    right, bottom = x + width - 1, y + height - 1
    for cx in range(x + 1, right):
        console.print(cx, y, _FRAME_TOP, fg=fg, bg=bg)
        console.print(cx, bottom, _FRAME_BOTTOM, fg=fg, bg=bg)
    for cy in range(y + 1, bottom):
        console.print(x, cy, _FRAME_LEFT, fg=fg, bg=bg)
        console.print(right, cy, _FRAME_RIGHT, fg=fg, bg=bg)
    console.print(x, y, _FRAME_TL, fg=fg, bg=bg)
    console.print(right, y, _FRAME_TR, fg=fg, bg=bg)
    console.print(x, bottom, _FRAME_BL, fg=fg, bg=bg)
    console.print(right, bottom, _FRAME_BR, fg=fg, bg=bg)


def draw_titled_frame(
    console: tcod.console.Console,
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    fg: tuple[int, int, int] = UI_WHITE,
    bg: tuple[int, int, int] | None = None,
) -> None:
    """Draw a framed box with a title centered on its top border.

    The frame is built from block elements (see `_draw_block_frame`) so its border
    stays solid regardless of the font's box-drawing coverage. The title is printed
    over the top border afterwards, interrupting it where the text sits.
    """
    _draw_block_frame(console, x, y, width, height, fg=fg, bg=bg)
    console.print(x=x, y=y, width=width, height=1, text=f' {title} ', fg=fg, alignment=tcod.constants.CENTER)


def draw_centered_frame(
    console: tcod.console.Console,
    width: int,
    height: int,
    title: str,
    fg: tuple[int, int, int] = UI_WHITE,
    bg: tuple[int, int, int] = (0, 0, 0),
) -> tuple[int, int]:
    """Draw a centered frame and return its top-left (x, y) so callers can offset from it."""
    x, y = center_origin(console, width, height)
    draw_titled_frame(console, x, y, width, height, title=title, fg=fg, bg=bg)
    return x, y


def compute_visible_slice(total_lines: int, scroll_index: int, visible_height: int) -> tuple[int, int, int]:
    """Resolve which lines of a scrollable log are visible.

    scroll_index 0 means the bottom (newest); larger values scroll toward the top.
    Returns (clamped_scroll_index, start_idx, end_idx) where [start_idx:end_idx]
    slices the line list; the caller writes the clamped index back to its state.
    """
    max_scroll = max(0, total_lines - visible_height)
    clamped = max(0, min(scroll_index, max_scroll))
    end_idx = total_lines - clamped
    start_idx = max(0, end_idx - visible_height)
    return clamped, start_idx, end_idx


def scroll_window(total: int, cursor: int, visible_height: int) -> tuple[int, int]:
    """Resolve the [start, end) slice of a cursor-driven list that keeps `cursor` in view.

    The window is `visible_height` rows (or the whole list when it fits) and centers on
    the cursor, clamped to the list bounds — so holding a direction scrolls one row at a
    time, the cursor stays visible, and no scroll offset has to be stored anywhere.
    """
    if visible_height <= 0 or total <= visible_height:
        return 0, total
    start = max(0, min(cursor - visible_height // 2, total - visible_height))
    return start, start + visible_height


def draw_scroll_indicators(
    console: tcod.console.Console,
    x: int,
    top_y: int,
    bottom_y: int,
    start: int,
    end: int,
    total: int,
    fg: tuple[int, int, int],
) -> None:
    """Mark a windowed list as scrollable: '▲' at (x, top_y) when items precede the
    window and '▼' at (x, bottom_y) when items follow it. A no-op when nothing is clipped."""
    if start > 0:
        console.print(x, top_y, '▲', fg=fg)
    if end < total:
        console.print(x, bottom_y, '▼', fg=fg)


def wrap_message(segments: Message, width: int) -> list[Message]:
    """Wrap a segmented (multi-color) message into multiple lines of at most `width`."""
    lines: list[Message] = []
    current_line: Message = []
    current_line_len = 0

    for text, color in segments:
        words = text.split(' ')
        for i, word in enumerate(words):
            # Add space back if not the first word in the segment
            full_word = word + (' ' if i < len(words) - 1 else '')
            if not full_word:
                continue

            if current_line_len + len(full_word) > width:
                if current_line:
                    lines.append(current_line)
                current_line = []
                current_line_len = 0

            # Check if we should trim leading space on new line
            if current_line_len == 0 and full_word.startswith(' '):
                full_word = full_word[1:]

            if full_word:
                current_line.append((full_word, color))
                current_line_len += len(full_word)

    if current_line:
        lines.append(current_line)
    return lines
