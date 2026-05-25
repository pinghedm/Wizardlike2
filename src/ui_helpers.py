"""Pure presentation helpers for the UI systems.

These functions hold display-formatting math only (no ECS access), which keeps
them straightforward to unit-test independently of the tcod render pass.
"""

import tcod

from src.components import Message
from src.constants import UI_WHITE


def center_origin(console: tcod.console.Console, width: int, height: int) -> tuple[int, int]:
    """Return the top-left (x, y) for a box of the given size centered on the console."""
    return (console.width - width) // 2, (console.height - height) // 2


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
    console.draw_frame(x, y, width, height, title=title, fg=fg, bg=bg)
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
