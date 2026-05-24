import esper
import tcod.event

from src.components import Inventory, ItemType, KnownRecipes, SpellInventory, SpellType
from src.states import DisplayMode
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
