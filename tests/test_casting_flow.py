"""Post-cast behavior and quick-cast bindings, driven through the real dispatch path."""

import esper
import pytest
import tcod.event

from src.components import Settings, UIState
from src.states import DisplayMode, PostCastBehavior
from tests.headless_runner import HeadlessRunner

SPELL = 'test_bolt'


def _settings() -> Settings:
    return esper.get_component(Settings)[0][1]


def _ui() -> UIState:
    return esper.get_component(UIState)[0][1]


def _enter_targeting(runner: HeadlessRunner):
    """Open the picker and confirm the first (only) spell to reach TARGETING."""
    runner.game_state.display_mode = DisplayMode.CASTING
    runner.simulate_key(tcod.event.KeySym.RETURN)
    assert runner.display_mode == DisplayMode.TARGETING


# (behavior, starting_charges) -> mode after one cast
POST_CAST_CASES = [
    # Stay readied while charges remain.
    ('stay_with_charges', PostCastBehavior.STAY, 3, DisplayMode.TARGETING),
    # Stay, but the cast spent the last charge -> fall back to the picker.
    ('stay_last_charge', PostCastBehavior.STAY, 1, DisplayMode.CASTING),
    ('reselect', PostCastBehavior.RESELECT, 3, DisplayMode.CASTING),
    ('explore', PostCastBehavior.EXPLORE, 3, DisplayMode.EXPLORING),
]


@pytest.mark.parametrize(
    ('behavior', 'charges', 'expected_mode'),
    [(b, c, m) for _id, b, c, m in POST_CAST_CASES],
    ids=[c[0] for c in POST_CAST_CASES],
)
def test_post_cast_behavior_routes_after_cast(behavior, charges, expected_mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, charges)
    _settings().post_cast = behavior

    _enter_targeting(runner)
    runner.simulate_key(tcod.event.KeySym.RETURN)  # confirm the cast

    assert runner.display_mode == expected_mode
    # The cast always spends exactly one charge, whatever happens next.
    assert runner.spell_charges(SPELL) == charges - 1


def test_post_cast_stay_keeps_the_reticle_up():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 2)
    _settings().post_cast = PostCastBehavior.STAY

    _enter_targeting(runner)
    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert runner.display_mode == DisplayMode.TARGETING
    assert _ui().active_targeting_spell_id == SPELL


def test_quick_cast_key_enters_targeting_for_that_slot():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 2)

    runner.simulate_key(tcod.event.KeySym.N1)

    assert runner.display_mode == DisplayMode.TARGETING
    assert _ui().active_targeting_spell_id == SPELL


def test_quick_cast_empty_slot_is_a_noop():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 1)  # only one spell, so slot 2 is empty

    runner.simulate_key(tcod.event.KeySym.N2)

    assert runner.display_mode == DisplayMode.EXPLORING


def test_settings_toggle_cycles_and_persists_post_cast():
    from src import persistence

    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SETTINGS
    _ui().settings_cursor = 0  # the post-cast row
    options = list(PostCastBehavior)
    start = options.index(_settings().post_cast)

    runner.simulate_key(tcod.event.KeySym.RIGHT)  # MOVE_RIGHT advances the toggle

    assert _settings().post_cast == options[(start + 1) % len(options)]
    assert persistence.load_meta()['post_cast'] == _settings().post_cast


def test_settings_confirm_on_keybinding_row_arms_remap():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SETTINGS
    _ui().settings_cursor = 1  # first keybinding row (row 0 is the toggle)
    first_action = next(iter(_settings().keybindings.bindings))

    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert _ui().remapping_action == first_action
