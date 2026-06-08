import esper
import tcod.event

from src.components import Inventory, ItemType, KnownRecipes, SpellInventory, SpellType, UIState
from src.states import CraftingView, DisplayMode
from src.systems import match_recipe
from tests.headless_runner import HeadlessRunner


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

    runner.simulate_key(tcod.event.KeySym.c)  # EXPLORING -> COMBINING
    assert runner.display_mode == DisplayMode.COMBINING
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # add 1st reagent_a
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # add 2nd reagent_a
    runner.simulate_key(tcod.event.KeySym.RETURN)  # combine

    assert runner.display_mode == DisplayMode.EXPLORING
    assert esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_blast')] == 5
    assert SpellType('test_blast') in esper.component_for_entity(runner.player, KnownRecipes).recipes
    assert esper.component_for_entity(runner.player, Inventory).items[ItemType('reagent_a')] == 0


def test_left_removes_a_selected_reagent_from_the_mix():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 2)
    ui_state = esper.get_component(UIState)[0][1]

    runner.simulate_key(tcod.event.KeySym.c)  # -> COMBINING
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # add 1st
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # add 2nd
    assert ui_state.selected_for_crafting[ItemType('reagent_a')] == 2

    runner.simulate_key(tcod.event.KeySym.LEFT)  # remove one back

    assert ui_state.selected_for_crafting[ItemType('reagent_a')] == 1


def test_combining_an_unknown_combo_fizzles_and_clears_the_mix():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_c', 2)  # fixtures: reagent_c + reagent_c -> no recipe
    ui_state = esper.get_component(UIState)[0][1]

    runner.simulate_key(tcod.event.KeySym.c)
    runner.simulate_key(tcod.event.KeySym.RIGHT)
    runner.simulate_key(tcod.event.KeySym.RIGHT)
    runner.simulate_key(tcod.event.KeySym.RETURN)  # combine

    assert runner.display_mode == DisplayMode.COMBINING  # stays open after a fizzle
    assert ui_state.selected_for_crafting == {}  # the mix is reset
    assert any('fizzle' in m for m in runner.get_log_messages())
    assert esper.component_for_entity(runner.player, Inventory).items[ItemType('reagent_c')] == 2  # nothing consumed


def test_tab_toggles_crafting_view():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_key(tcod.event.KeySym.c)  # -> COMBINING (Experiment by default)
    ui_state = esper.get_component(UIState)[0][1]
    assert ui_state.crafting_view == CraftingView.EXPERIMENT

    runner.simulate_key(tcod.event.KeySym.TAB)
    assert ui_state.crafting_view == CraftingView.SPELLBOOK
    runner.simulate_key(tcod.event.KeySym.TAB)
    assert ui_state.crafting_view == CraftingView.EXPERIMENT


def test_spellbook_instant_crafts_known_spell():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {make_ingredients_type('reagent_a', 'reagent_b')}
    runner.give_item('reagent_a', 1)
    runner.give_item('reagent_b', 1)

    runner.simulate_key(tcod.event.KeySym.c)  # -> COMBINING
    runner.simulate_key(tcod.event.KeySym.TAB)  # -> Spellbook
    runner.simulate_key(tcod.event.KeySym.RETURN)  # craft the selected recipe

    assert runner.display_mode == DisplayMode.COMBINING  # stays open to craft more
    assert esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_bolt')] == 3
    inv = esper.component_for_entity(runner.player, Inventory)
    assert inv.items[ItemType('reagent_a')] == 0
    assert inv.items[ItemType('reagent_b')] == 0


def test_spellbook_craft_without_ingredients_does_nothing():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {make_ingredients_type('reagent_a', 'reagent_b')}

    runner.simulate_key(tcod.event.KeySym.c)
    runner.simulate_key(tcod.event.KeySym.TAB)
    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert esper.component_for_entity(runner.player, SpellInventory).spells.get(SpellType('test_bolt'), 0) == 0
    assert any('Not enough ingredients' in m for m in runner.get_log_messages())
