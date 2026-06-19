"""Post-cast behavior, quick-cast bindings, and cycle targeting, via the dispatch path."""

from dataclasses import replace

import esper
import pytest
import tcod.event

from src.components import (
    Actor,
    Effect,
    EffectType,
    FieldOfView,
    InputAction,
    Inventory,
    ItemType,
    Modal,
    Point,
    Settings,
    SpellInventory,
    SpellType,
    Stats,
    StatusEffects,
    StatusType,
    TargetingReticle,
    UIState,
)
from src.ecs_helpers import spawn_item_entity
from src.input_handlers import (
    available_spells,
    handle_casting_input,
    handle_settings_input,
    handle_targeting_input,
)
from src.input_handlers.handlers import _cycle_post_cast, _step_target
from src.map_objects import Map
from src.procgen import transition_to_next_floor
from src.states import DisplayMode, PostCastBehavior
from tests.headless_runner import HeadlessRunner

SPELL = 'test_bolt'
BASIC = 'test_wand'  # the always-castable basic attack in the fixtures
GOLD = ItemType('gold')


def _slot_key(spell_id: str) -> tcod.event.KeySym:
    """The quick-cast number key (N1..) for a spell's slot in the available-spells list."""
    slot = available_spells().index(SpellType(spell_id))
    return getattr(tcod.event.KeySym, f'N{slot + 1}')


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


def _enter_targeting(runner: HeadlessRunner, spell_id: str = SPELL):
    """Lock targeting onto a freshly spawned, visible enemy by selecting `spell_id`'s slot in
    the picker (the only way to aim now)."""
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))
    runner.game_state.display_mode = DisplayMode.CASTING
    _ui().casting_cursor = available_spells().index(SpellType(spell_id))
    runner.simulate_key(tcod.event.KeySym.RETURN)
    assert runner.display_mode == DisplayMode.TARGETING


# (behavior, starting_charges) -> mode after one cast of the aimed (non-basic) bolt.
POST_CAST_CASES = [
    # Stay readied while charges remain.
    ('stay_with_charges', PostCastBehavior.STAY, 3, DisplayMode.TARGETING),
    # Stay, but the cast spent the bolt's last charge -> drop to the picker to ready another.
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


def test_basic_spell_is_the_only_option_when_nothing_is_discovered():
    # With no crafted spells, the basic attack is the player's only castable spell.
    HeadlessRunner(use_random_map=False)
    assert available_spells() == [SpellType(BASIC)]


def test_basic_spell_starts_stocked_to_its_per_floor_capacity():
    runner = HeadlessRunner(use_random_map=False)
    assert runner.spell_charges(BASIC) == 2  # the fixture wand's capacity


def test_basic_spell_depletes_when_cast_then_refills_on_the_next_floor():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))

    runner.simulate_key(_slot_key(BASIC))
    runner.simulate_key(tcod.event.KeySym.RETURN)  # spend one charge
    assert runner.spell_charges(BASIC) == 1

    transition_to_next_floor()

    assert runner.spell_charges(BASIC) == 2  # back to full on the new floor


def test_post_cast_stay_keeps_aiming_a_basic_spell_while_charges_remain():
    # The basic spell behaves like any charged spell under STAY: with charges left, the reticle
    # stays up to fire again.
    runner = HeadlessRunner(use_random_map=False)
    _settings().post_cast = PostCastBehavior.STAY

    _enter_targeting(runner, BASIC)
    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert runner.display_mode == DisplayMode.TARGETING
    assert _ui().active_targeting_spell_id == BASIC


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

    runner.simulate_key(_slot_key(SPELL))

    assert runner.display_mode == DisplayMode.TARGETING
    assert _ui().active_targeting_spell_id == SPELL


def test_quick_cast_empty_slot_is_a_noop():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 1)  # available is [basic, bolt], so slot 3 is empty

    runner.simulate_key(tcod.event.KeySym.N3)

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


@pytest.mark.parametrize(
    ('action', 'expected'),
    [
        (InputAction.MOVE_LEFT, PostCastBehavior.EXPLORE),  # STAY -> previous, wrapping
        (InputAction.CYCLE_TAB, PostCastBehavior.STAY),  # an unrelated action leaves it put
    ],
)
def test_settings_toggle_left_and_noop(action, expected):
    HeadlessRunner(use_random_map=False)
    _settings().post_cast = PostCastBehavior.STAY
    _cycle_post_cast(_settings(), action)
    assert _settings().post_cast == expected


def test_settings_arrow_moves_the_cursor_between_rows():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SETTINGS
    _ui().settings_cursor = 0
    handle_settings_input(InputAction.MOVE_DOWN)
    assert _ui().settings_cursor == 1


def test_settings_keybinding_row_ignores_unrelated_actions():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SETTINGS
    _ui().settings_cursor = 1  # a keybinding row
    assert handle_settings_input(InputAction.CYCLE_TAB) == DisplayMode.SETTINGS
    assert _ui().remapping_action is None


# --- picker / targeting guard paths -----------------------------------------


@pytest.mark.parametrize(
    ('targets', 'current', 'step', 'expected'),
    [
        ([], 5, 1, None),  # no targets -> None
        ([7, 8], 99, 1, 7),  # the current target is gone -> first
        ([7, 8, 9], 8, 1, 9),  # next
        ([7, 8, 9], 9, 1, 7),  # next wraps
        ([7, 8, 9], 8, -1, 7),  # previous
    ],
)
def test_step_target(targets, current, step, expected):
    assert _step_target(targets, current, step) == expected


def test_casting_quick_cast_with_no_charged_spell_keeps_the_picker():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, SpellInventory).spells.clear()  # spend everything, basic included
    runner.game_state.display_mode = DisplayMode.CASTING
    assert handle_casting_input(InputAction.QUICK_CAST_1) == DisplayMode.CASTING


def test_casting_movement_stays_in_the_picker():
    HeadlessRunner(use_random_map=False)
    assert handle_casting_input(InputAction.MOVE_UP) == DisplayMode.CASTING


def test_targeting_move_is_swallowed_while_slowed_on_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(TargetingReticle(x=px, y=py, radius=0))
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.SLOW] = Effect(type=EffectType.SLOW)
    esper.component_for_entity(runner.player, Actor).cooldown = 5
    assert handle_targeting_input(InputAction.MOVE_UP) == DisplayMode.TARGETING
    assert runner.player_pos == Point(px, py)


def test_targeting_ignores_unrelated_actions():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(TargetingReticle(x=px, y=py, radius=0))
    assert handle_targeting_input(InputAction.OPEN_CRAFTING) == DisplayMode.TARGETING


def test_targeting_move_picks_up_items():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(TargetingReticle(x=px, y=py, radius=0))
    spawn_item_entity(GOLD, px + 1, py, count=5)

    assert handle_targeting_input(InputAction.MOVE_RIGHT) == DisplayMode.TARGETING  # still aiming
    assert esper.component_for_entity(runner.player, Inventory).items.get(GOLD, 0) == 5


def test_targeting_move_onto_the_exit_descends():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    game_map = esper.get_component(Map)[0][1]
    game_map.set_tile(px + 1, py, replace(game_map.tiles[px + 1][py], is_exit=True))
    esper.create_entity(TargetingReticle(x=px, y=py, radius=0))

    result = handle_targeting_input(InputAction.MOVE_RIGHT)

    assert result == DisplayMode.EXPLORING  # left targeting
    assert runner.player_pos == Point(px + 1, py)  # stepped onto the exit
    assert esper.get_component(Modal)  # the descend prompt opened


# --- cycle targeting --------------------------------------------------------


def test_cycle_locks_nearest_visible_enemy():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    near = _guardian(runner, px + 1, py)
    _guardian(runner, px + 4, py)
    _freeze_fov(runner, Point(px + 1, py), Point(px + 4, py))

    runner.simulate_key(_slot_key(SPELL))

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
    runner.simulate_key(_slot_key(SPELL))

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
    runner.simulate_key(_slot_key(SPELL))
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
    runner.simulate_key(_slot_key(SPELL))
    hp_before = esper.component_for_entity(enemy, Stats).hp

    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert runner.spell_charges(SPELL) == 2
    assert esper.component_for_entity(enemy, Stats).hp < hp_before


def test_cycle_with_no_visible_enemy_does_not_enter_targeting():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 1)

    runner.simulate_key(_slot_key(SPELL))  # nothing to lock onto

    assert runner.display_mode == DisplayMode.EXPLORING
    assert not esper.get_component(TargetingReticle)
    assert runner.spell_charges(SPELL) == 1  # no charge wasted


def test_cycle_exits_when_last_target_leaves_view():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 3)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))
    runner.simulate_key(_slot_key(SPELL))
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
    runner.simulate_key(_slot_key(SPELL))
    assert esper.get_component(TargetingReticle)[0][1].target_ent == near

    # The locked enemy leaves view; the system re-locks to the remaining one.
    _freeze_fov(runner, Point(px + 2, py))
    runner.tick(1)

    reticle = esper.get_component(TargetingReticle)[0][1]
    assert runner.display_mode == DisplayMode.TARGETING
    assert reticle.target_ent == other


def test_quick_cast_while_aiming_swaps_to_the_other_spell():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 2)
    runner.give_spell('test_blast', 2)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))

    runner.simulate_key(_slot_key(SPELL))
    assert _ui().active_targeting_spell_id == SPELL

    runner.simulate_key(_slot_key('test_blast'))  # swap, still aiming

    assert runner.display_mode == DisplayMode.TARGETING
    assert _ui().active_targeting_spell_id == 'test_blast'


def test_confirm_with_no_locked_target_waits_in_targeting_without_spending():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell(SPELL, 2)
    px, py = runner.player_pos
    _guardian(runner, px + 1, py)
    _freeze_fov(runner, Point(px + 1, py))
    runner.simulate_key(_slot_key(SPELL))
    # The enemy leaves view, so the next refresh finds nothing to lock onto.
    _freeze_fov(runner)

    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert runner.display_mode == DisplayMode.TARGETING
    assert runner.spell_charges(SPELL) == 2  # no charge spent without a target


def test_self_cast_spell_skips_targeting_and_heals_caster():
    # A target: self spell resolves on the caster with no targeting step.
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_heal', 2)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp = 50

    runner.simulate_key(_slot_key('test_heal'))

    assert runner.display_mode == DisplayMode.EXPLORING
    assert not esper.get_component(TargetingReticle)
    assert runner.spell_charges('test_heal') == 1
    assert stats.hp > 50
