import pytest
import tcod.console

from src.components import Effect, EffectType, ItemType
from src.ui_helpers import (
    center_origin,
    compute_visible_slice,
    format_recipe,
    format_spell_effects,
    wrap_message,
)

WHITE = (255, 255, 255)
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def test_format_recipe_collapses_duplicates():
    combo = (ItemType('reagent_a'), ItemType('reagent_a'), ItemType('reagent_b'))
    # Duplicates collapse to 'Nx', singletons stay bare, ingredients ordered by name.
    assert format_recipe(combo) == '2x REAGENT_A, REAGENT_B'


def test_format_spell_effects_converts_ticks_to_seconds():
    effects = [Effect(EffectType.DAMAGE, power=12), Effect(EffectType.SLOW, duration=90)]
    assert format_spell_effects(effects) == 'Damage 12, Slow 3s'


# (total_lines, scroll_index, visible_height) -> (clamped_index, start_idx, end_idx)
VISIBLE_SLICE_CASES = [
    # empty log: nothing to show
    ('empty', (0, 0, 3), (0, 0, 0)),
    # fewer lines than the window: show them all, start clamped to 0
    ('fits_in_view', (2, 0, 3), (0, 0, 2)),
    # scrolled to bottom (index 0) with overflow: show the newest `visible_height`
    ('bottom_shows_newest', (10, 0, 3), (0, 7, 10)),
    # mid-scroll: window shifts up by scroll_index
    ('mid_scroll_shifts_window', (10, 2, 3), (2, 5, 8)),
    # scroll past the top: index clamps to max_scroll, window pinned to the top
    ('overscroll_clamps_to_top', (10, 999, 3), (7, 0, 3)),
]


@pytest.mark.parametrize(
    'total, scroll, height, expected',
    [(t, s, h, exp) for _id, (t, s, h), exp in VISIBLE_SLICE_CASES],
    ids=[c[0] for c in VISIBLE_SLICE_CASES],
)
def test_compute_visible_slice(total, scroll, height, expected):
    assert compute_visible_slice(total, scroll, height) == expected


def test_wrap_message_breaks_at_width():
    lines = wrap_message([('aaa bbb ccc', WHITE)], width=3)
    assert len(lines) == 3


def test_wrap_message_preserves_per_segment_color():
    lines = wrap_message([('hi ', RED), ('there', BLUE)], width=80)
    # Whole message fits on one line; both colored segments are kept intact.
    assert lines == [[('hi ', RED), ('there', BLUE)]]


def test_wrap_message_trims_leading_space_on_wrapped_line():
    lines = wrap_message([('aaaa', WHITE), (' bb', WHITE)], width=4)
    # The space that would lead the wrapped line is dropped.
    assert lines == [[('aaaa', WHITE)], [('bb', WHITE)]]


def test_center_origin_returns_top_left_of_centered_box():
    console = tcod.console.Console(80, 50)
    assert center_origin(console, 20, 10) == (30, 20)
