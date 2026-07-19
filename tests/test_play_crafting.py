import esper
import pygame
import pytest

from src.components import InputAction, Inventory, ItemType, KnownRecipes, RunStats, SpellInventory, SpellType, UIState
from src.ecs_helpers import get_singleton
from src.input_handlers.handlers import _combine_selection, _handle_experiment_input, _handle_spellbook_input
from src.states import CraftingView, DisplayMode
from src.systems import discover_and_craft, match_recipe
from tests.headless_runner import HeadlessRunner

REAGENT = 'reagent_a'


def make_ingredients_type(*items):
    """Build the sorted tuple[ItemType] selection that match_recipe expects."""
    return tuple(sorted(ItemType(i) for i in items))


def test_match_recipe_recognizes_fixture_recipe():
    HeadlessRunner(use_random_map=False)
    # fixtures/spells.yaml: reagent_a + reagent_b -> test_bolt (3 charges)
    assert match_recipe(make_ingredients_type('reagent_a', 'reagent_b')) == (SpellType('test_bolt'), 3)


def test_match_recipe_ignores_selection_order():
    HeadlessRunner(use_random_map=False)
    forward = match_recipe(make_ingredients_type('reagent_a', 'reagent_b'))
    reversed_ = match_recipe(make_ingredients_type('reagent_b', 'reagent_a'))
    assert forward == reversed_ == (SpellType('test_bolt'), 3)


def test_match_recipe_returns_none_for_unknown_combo():
    HeadlessRunner(use_random_map=False)
    assert match_recipe(make_ingredients_type('reagent_c', 'reagent_c')) is None


def test_combining_ingredients_creates_spell():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 2)  # fixtures: reagent_a + reagent_a -> test_blast (5 charges)

    runner.simulate_key(pygame.K_c)  # EXPLORING -> COMBINING
    assert runner.display_mode == DisplayMode.COMBINING
    runner.simulate_key(pygame.K_RIGHT)  # add 1st reagent_a
    runner.simulate_key(pygame.K_RIGHT)  # add 2nd reagent_a
    runner.simulate_key(pygame.K_RETURN)  # combine

    assert runner.display_mode == DisplayMode.EXPLORING
    assert esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_blast')] == 5
    assert SpellType('test_blast') in esper.component_for_entity(runner.player, KnownRecipes).recipes
    assert esper.component_for_entity(runner.player, Inventory).items[ItemType('reagent_a')] == 0


def test_left_removes_a_selected_reagent_from_the_mix():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 2)
    ui_state = esper.get_component(UIState)[0][1]

    runner.simulate_key(pygame.K_c)  # -> COMBINING
    runner.simulate_key(pygame.K_RIGHT)  # add 1st
    runner.simulate_key(pygame.K_RIGHT)  # add 2nd
    assert ui_state.selected_for_crafting[ItemType('reagent_a')] == 2

    runner.simulate_key(pygame.K_LEFT)  # remove one back

    assert ui_state.selected_for_crafting[ItemType('reagent_a')] == 1


def test_recrafting_a_known_spell_adds_charges_without_recounting_the_discovery():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 4)  # enough for two test_blast crafts (reagent_a x2 each)
    discovered_before = get_singleton(RunStats).spells_discovered

    discover_and_craft(make_ingredients_type('reagent_a', 'reagent_a'))  # first time: a discovery
    discover_and_craft(make_ingredients_type('reagent_a', 'reagent_a'))  # already known: just charges

    spell_inv = esper.component_for_entity(runner.player, SpellInventory)
    assert spell_inv.spells[SpellType('test_blast')] == 10  # 5 + 5 charges
    assert get_singleton(RunStats).spells_discovered == discovered_before + 1  # counted once


def test_combining_an_unknown_combo_fizzles_and_clears_the_mix():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_c', 2)  # fixtures: reagent_c + reagent_c -> no recipe
    ui_state = esper.get_component(UIState)[0][1]

    runner.simulate_key(pygame.K_c)
    runner.simulate_key(pygame.K_RIGHT)
    runner.simulate_key(pygame.K_RIGHT)
    runner.simulate_key(pygame.K_RETURN)  # combine

    assert runner.display_mode == DisplayMode.COMBINING  # stays open after a fizzle
    assert ui_state.selected_for_crafting == {}  # the mix is reset
    assert any('fizzle' in m for m in runner.get_log_messages())
    assert esper.component_for_entity(runner.player, Inventory).items[ItemType('reagent_c')] == 2  # nothing consumed


def test_tab_toggles_crafting_view():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_key(pygame.K_c)  # -> COMBINING (Experiment by default)
    ui_state = esper.get_component(UIState)[0][1]
    assert ui_state.crafting_view == CraftingView.EXPERIMENT

    runner.simulate_key(pygame.K_TAB)
    assert ui_state.crafting_view == CraftingView.SPELLBOOK
    runner.simulate_key(pygame.K_TAB)
    assert ui_state.crafting_view == CraftingView.EXPERIMENT


def test_spellbook_instant_crafts_known_spell():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {make_ingredients_type('reagent_a', 'reagent_b')}
    runner.give_item('reagent_a', 1)
    runner.give_item('reagent_b', 1)

    runner.simulate_key(pygame.K_c)  # -> COMBINING
    runner.simulate_key(pygame.K_TAB)  # -> Spellbook
    runner.simulate_key(pygame.K_RETURN)  # craft the selected recipe

    assert runner.display_mode == DisplayMode.COMBINING  # stays open to craft more
    assert esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_bolt')] == 3
    inv = esper.component_for_entity(runner.player, Inventory)
    assert inv.items[ItemType('reagent_a')] == 0
    assert inv.items[ItemType('reagent_b')] == 0


def test_spellbook_craft_without_ingredients_does_nothing():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {make_ingredients_type('reagent_a', 'reagent_b')}

    runner.simulate_key(pygame.K_c)
    runner.simulate_key(pygame.K_TAB)
    runner.simulate_key(pygame.K_RETURN)

    assert esper.component_for_entity(runner.player, SpellInventory).spells.get(SpellType('test_bolt'), 0) == 0
    assert any('Not enough ingredients' in m for m in runner.get_log_messages())


# --- experiment / spellbook edge paths ----------------------------------------


@pytest.mark.parametrize('action', [InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT])
def test_experiment_select_is_a_noop_with_an_empty_inventory(action):
    HeadlessRunner(use_random_map=False)  # fresh player holds no reagents
    ui_state = get_singleton(UIState)
    assert _handle_experiment_input(action, ui_state) == DisplayMode.COMBINING
    assert ui_state.selected_for_crafting == {}


def test_experiment_cannot_select_more_than_held():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item(REAGENT, 1)
    ui_state = get_singleton(UIState)
    ui_state.selected_for_crafting = {ItemType(REAGENT): 1}  # already at the held amount

    _handle_experiment_input(InputAction.MOVE_RIGHT, ui_state)

    assert ui_state.selected_for_crafting[ItemType(REAGENT)] == 1


def test_experiment_cannot_deselect_below_zero():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item(REAGENT, 1)
    ui_state = get_singleton(UIState)  # nothing selected yet

    _handle_experiment_input(InputAction.MOVE_LEFT, ui_state)

    assert ui_state.selected_for_crafting.get(ItemType(REAGENT), 0) == 0


def test_combine_with_an_empty_mix_stays_combining():
    HeadlessRunner(use_random_map=False)
    ui_state = get_singleton(UIState)
    ui_state.selected_for_crafting = {}
    assert _combine_selection(ui_state) == DisplayMode.COMBINING


def test_spellbook_confirm_with_no_known_recipes_stays_combining():
    HeadlessRunner(use_random_map=False)  # fresh player knows nothing
    assert _handle_spellbook_input(InputAction.CONFIRM, get_singleton(UIState)) == DisplayMode.COMBINING
