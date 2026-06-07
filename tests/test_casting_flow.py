"""Post-cast behavior, quick-cast bindings, and cycle targeting, via the dispatch path."""

import esper
import pytest
import tcod.event

from src.components import FieldOfView, Point, Settings, Stats, TargetingReticle, UIState
from src.states import DisplayMode, PostCastBehavior
from tests.headless_runner import HeadlessRunner

SPELL = 'test_bolt'


def _settings() -> Settings:
    return esper.get_component(Settings)[0][1]


def _ui() -> UIState:
    return esper.get_component(UIState)[0][1]


def _freeze_fov(runner: HeadlessRunner, *points: Point):
    """Pin the player's visible tiles and stop FOVSystem recomputing them on tick."""
    fov = esper.component_for_entity(runner.player, FieldOfView)
    fov.visible_tiles = set(points)
    fov.dirty = False


def _guardian(runner: HeadlessRunner, x: int, y: int) -> int:
    """A stationary enemy, so positions stay fixed across any ticks a test drives."""
    return runner.spawn_enemy(x, y, runner.enemy_config('test_guardian'))


def _enter_targeting(runner: HeadlessRunner):
    """Lock targeting onto a freshly spawned, visible enemy (the only way to aim now)."""
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))
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


def test_quick_cast_key_locks_a_visible_enemy_for_that_slot():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 2)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))

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


# --- cycle targeting --------------------------------------------------------


def test_cycle_locks_nearest_visible_enemy():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    near = _guardian(runner, px + 1, py)
    _guardian(runner, px + 4, py)
    _freeze_fov(runner, Point(px + 1, py), Point(px + 4, py))

    runner.simulate_key(tcod.event.KeySym.N1)

    reticle = esper.get_component(TargetingReticle)[0][1]
    assert runner.display_mode == DisplayMode.TARGETING
    assert reticle.target_ent == near
    assert (reticle.x, reticle.y) == (px + 1, py)


def test_cycle_tabs_to_next_visible_enemy():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    far = _guardian(runner, px + 4, py)
    _freeze_fov(runner, Point(px + 1, py), Point(px + 4, py))
    runner.simulate_key(tcod.event.KeySym.N1)

    runner.simulate_key(tcod.event.KeySym.TAB)  # cycle to the next target (distance order)

    reticle = esper.get_component(TargetingReticle)[0][1]
    assert reticle.target_ent == far
    assert (reticle.x, reticle.y) == (px + 4, py)


def test_can_walk_while_targeting():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    _guardian(runner, px + 2, py)
    _freeze_fov(runner, Point(px + 2, py))
    runner.simulate_key(tcod.event.KeySym.N1)
    assert runner.display_mode == DisplayMode.TARGETING

    runner.simulate_key(tcod.event.KeySym.DOWN)  # arrows walk the caster while aiming

    assert runner.player_pos == Point(px, py + 1)
    assert runner.display_mode == DisplayMode.TARGETING


def test_cycle_cast_damages_locked_enemy():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    enemy = _guardian(runner, px + 2, py)
    _freeze_fov(runner, Point(px + 2, py))
    runner.simulate_key(tcod.event.KeySym.N1)
    hp_before = esper.component_for_entity(enemy, Stats).hp

    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert runner.spell_charges(SPELL) == 2
    assert esper.component_for_entity(enemy, Stats).hp < hp_before


def test_cycle_with_no_visible_enemy_does_not_enter_targeting():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 1)

    runner.simulate_key(tcod.event.KeySym.N1)  # nothing to lock onto

    assert runner.display_mode == DisplayMode.EXPLORING
    assert not esper.get_component(TargetingReticle)
    assert runner.spell_charges(SPELL) == 1  # no charge wasted


def test_cycle_exits_when_last_target_leaves_view():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))
    runner.simulate_key(tcod.event.KeySym.N1)
    assert runner.display_mode == DisplayMode.TARGETING

    # The only target leaves the player's view; the maintenance system drops targeting.
    _freeze_fov(runner)  # nothing visible now
    runner.tick(1)

    assert runner.display_mode == DisplayMode.EXPLORING
    assert not esper.get_component(TargetingReticle)


def test_cycle_relocks_when_target_leaves_but_others_remain():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    near = _guardian(runner, px + 1, py)
    other = _guardian(runner, px + 2, py)
    _freeze_fov(runner, Point(px + 1, py), Point(px + 2, py))
    runner.simulate_key(tcod.event.KeySym.N1)
    assert esper.get_component(TargetingReticle)[0][1].target_ent == near

    # The locked enemy leaves view; the system re-locks to the remaining one.
    _freeze_fov(runner, Point(px + 2, py))
    runner.tick(1)

    reticle = esper.get_component(TargetingReticle)[0][1]
    assert runner.display_mode == DisplayMode.TARGETING
    assert reticle.target_ent == other


def test_self_cast_spell_skips_targeting_and_heals_caster():
    # A target: self spell resolves on the caster with no targeting step.
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_heal', 2)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp = 50

    runner.simulate_key(tcod.event.KeySym.N1)

    assert runner.display_mode == DisplayMode.EXPLORING
    assert not esper.get_component(TargetingReticle)
    assert runner.spell_charges('test_heal') == 1
    assert stats.hp > 50
