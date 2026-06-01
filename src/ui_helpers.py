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

    tcod deprecated draw_frame's built-in `title` (its style is hard-coded), so we
    draw a plain frame and print the title over the top border ourselves, as the
    tcod docs recommend.
    """
    console.draw_frame(x, y, width, height, fg=fg, bg=bg)
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
