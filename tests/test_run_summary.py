import esper
import pygame

from src import main
from src.components import (
    InputAction,
    Item,
    ItemType,
    PlayerTag,
    Position,
    RunStats,
    SpellType,
    Stats,
    UIState,
)
from src.ecs_helpers import get_singleton
from src.input_handlers import handle_game_over_input
from src.states import DisplayMode, GameState, PendingTransition
from src.systems import cast_spell, deal_damage
from src.ui_systems import MenuSystem
from tests.headless_runner import HeadlessRunner


def _run_stats() -> RunStats:
    return get_singleton(RunStats)


# --- counters increment at their source -----------------------------------------


def test_killing_an_enemy_increments_enemies_defeated():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)
    esper.component_for_entity(enemy, Stats).hp = 0

    runner.tick(1)  # DeathSystem reaps the enemy

    assert _run_stats().enemies_defeated == 1


def test_casting_a_spell_counts_per_spell_type():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 3)

    cast_spell(spell_id='test_bolt', target_x=0, target_y=0)
    cast_spell(spell_id='test_bolt', target_x=0, target_y=0)

    assert _run_stats().spells_cast[SpellType('test_bolt')] == 2


def test_damage_to_an_enemy_counts_but_damage_to_the_player_does_not():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)

    deal_damage(enemy, 7, 'zap', (255, 255, 255))
    assert _run_stats().damage_dealt == 7

    deal_damage(runner.player, 5, 'ow', (255, 255, 255))
    assert _run_stats().damage_dealt == 7  # the player taking damage is not the player dealing it


def test_picking_up_gold_increments_gold_collected():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(Position(px, py - 1), Item(type=ItemType('gold'), count=25))

    runner.simulate_key(pygame.K_UP)  # step onto the gold

    assert _run_stats().gold_collected == 25


def test_picking_up_an_ingredient_counts_per_type():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(Position(px, py - 1), Item(type=ItemType('reagent_a'), count=3))

    runner.simulate_key(pygame.K_UP)  # step onto the reagent

    assert _run_stats().ingredients_collected[ItemType('reagent_a')] == 3


def test_discovering_a_recipe_increments_spells_discovered():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 1)
    runner.give_item('reagent_b', 1)
    ui_state = get_singleton(UIState)
    ui_state.selected_for_crafting = {ItemType('reagent_a'): 1, ItemType('reagent_b'): 1}
    runner.game_state.display_mode = DisplayMode.COMBINING

    runner.simulate_key(pygame.K_RETURN)  # combine -> discover test_bolt

    assert _run_stats().spells_discovered == 1


# --- return to title --------------------------------------------------------------


def test_return_to_title_clears_the_world_and_boots_the_menu():
    runner = HeadlessRunner(use_random_map=False)

    main.apply_pending_transition(PendingTransition.RETURN_TO_TITLE, runner.game_state, runner.asset_loader)

    assert not esper.get_components(PlayerTag)
    assert get_singleton(GameState).display_mode == DisplayMode.MENU


def test_game_over_confirm_returns_to_town_and_cancel_quits_to_title():
    # Confirm starts the next run (which begins in the town); Cancel/Menu bails to the title.
    assert handle_game_over_input(InputAction.CONFIRM) == PendingTransition.NEW_GAME
    assert handle_game_over_input(InputAction.CANCEL) == PendingTransition.RETURN_TO_TITLE
    assert handle_game_over_input(InputAction.OPEN_MENU) == PendingTransition.RETURN_TO_TITLE


# --- rendering --------------------------------------------------------------------


def test_game_over_lines_list_the_stats_and_run_breakdown():
    runner = HeadlessRunner(use_random_map=False)
    _run_stats().spells_cast[SpellType('test_bolt')] = 2
    menu = MenuSystem(runner.surface, runner.asset_loader)

    lines = menu._game_over_lines(runner.game_state, _run_stats())
    text = '\n'.join(''.join(seg for seg, _ in row) for row in lines)
    assert 'Floor reached' in text
    assert 'Spells discovered' in text
    assert 'TEST_BOLT x2' in text  # the per-spell breakdown line
