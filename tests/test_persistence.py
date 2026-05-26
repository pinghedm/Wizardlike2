import os
import shutil

import esper
import pytest

from src import persistence
from src.components import (
    AI,
    ChaseTag,
    FieldOfView,
    Inventory,
    ItemType,
    KnownRecipes,
    PlayerTag,
    Position,
    SpellInventory,
    SpellType,
    Stats,
)
from src.constants import SAVE_DIR
from src.map_objects import Map
from src.states import GameState
from tests.headless_runner import HeadlessRunner


# Ensure test_save_data is cleaned up
@pytest.fixture(autouse=True)
def clean_save_dir():
    if os.path.exists(SAVE_DIR):
        shutil.rmtree(SAVE_DIR)
    yield
    if os.path.exists(SAVE_DIR):
        shutil.rmtree(SAVE_DIR)


def test_grimoire_serialization():
    # 'test_bolt' and 'test_blast' are in fixture spells.yaml
    recipes = {
        SpellType('test_bolt'): {(ItemType('reagent_a'), ItemType('reagent_b'))},
        SpellType('test_blast'): {(ItemType('reagent_a'), ItemType('reagent_a'))},
    }
    persistence.save_grimoire(recipes)
    loaded = persistence.load_grimoire()
    assert loaded == recipes


def test_world_serialization():
    # Setup
    esper.clear_database()
    esper.create_entity(Position(x=10, y=20))
    esper.create_entity(Stats(hp=50, max_hp=100))

    # Save and wipe
    persistence.save_game()
    esper.clear_database()
    assert len(esper.get_components(Position)) == 0

    # Load
    persistence.load_game()

    # Verify
    assert len(esper.get_components(Position)) == 1
    assert len(esper.get_components(Stats)) == 1

    ents = esper.get_components(Position)
    ent_id = ents[0][0]
    pos = esper.component_for_entity(ent_id, Position)
    assert pos.x == 10
    assert pos.y == 20


def test_save_load_lifecycle():
    # Setup
    esper.clear_database()
    esper.create_entity(
        PlayerTag(),
        Stats(hp=80, max_hp=100),
        Inventory(items={ItemType('reagent_a'): 5}),
        KnownRecipes(recipes={SpellType('test_bolt'): {(ItemType('reagent_a'), ItemType('reagent_b'))}}),
        SpellInventory(spells={SpellType('test_bolt'): 3}),
    )

    # Save and wipe
    persistence.save_game()
    esper.clear_database()
    assert len(esper.get_components(PlayerTag)) == 0

    # Load
    persistence.load_game()

    # Check Player State
    player_ents = esper.get_components(PlayerTag, Stats, Inventory, KnownRecipes, SpellInventory)
    assert len(player_ents) == 1

    _ent, (tag, stats, inv, recipes, spell_inv) = player_ents[0]
    assert stats.hp == 80
    assert inv.items[ItemType('reagent_a')] == 5
    assert SpellType('test_bolt') in recipes.recipes
    assert spell_inv.spells[SpellType('test_bolt')] == 3


def test_full_world_round_trip():
    # A complete live world: map, player (with FOV), an enemy with a behavior tag.
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.floor = 4
    runner.spawn_enemy(3, 3)

    persistence.save_game()
    esper.clear_database()
    assert len(esper.get_component(Map)) == 0

    persistence.load_game()

    # Map survives.
    assert len(esper.get_component(Map)) == 1
    # Player keeps its field of view.
    assert len(esper.get_components(FieldOfView, PlayerTag)) == 1
    # Enemy keeps its AI and behavior tag, so the AISystem still drives it.
    assert len(esper.get_components(AI, ChaseTag)) == 1
    # Game progress (current floor) is restored.
    assert esper.get_component(GameState)[0][1].floor == 4
