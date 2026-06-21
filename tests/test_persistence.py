import esper
import tcod.event
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src import persistence
from src.components import (
    AI,
    ChaseTag,
    FieldOfView,
    InputAction,
    Inventory,
    ItemType,
    KnownRecipes,
    MetaSaveState,
    PlayerTag,
    Position,
    Settings,
    SpellInventory,
    SpellType,
    Stats,
)
from src.ecs_helpers import get_singleton, spawn_item_entity
from src.map_objects import Map
from src.states import DisplayMode, GameState, PostCastBehavior
from tests.headless_runner import HeadlessRunner


def test_meta_round_trips_grimoire_and_gold():
    # 'test_bolt' and 'test_blast' are in fixture spells.yaml
    runner = HeadlessRunner(use_random_map=False)
    recipes = {
        SpellType('test_bolt'): {(ItemType('reagent_a'), ItemType('reagent_b'))},
        SpellType('test_blast'): {(ItemType('reagent_a'), ItemType('reagent_a'))},
    }
    esper.component_for_entity(runner.player, KnownRecipes).recipes = recipes
    esper.component_for_entity(runner.player, Inventory).items[ItemType('gold')] = 17

    persistence.save_meta()
    loaded = persistence.load_meta()

    assert loaded['recipes'] == recipes
    assert loaded['gold'] == 17


def test_meta_round_trips_settings():
    HeadlessRunner(use_random_map=False)
    settings = esper.get_component(Settings)[0][1]
    settings.post_cast = PostCastBehavior.EXPLORE
    settings.keybindings.bindings[InputAction.CONFIRM] = tcod.event.KeySym.SPACE
    settings.keybindings.controller[InputAction.CONFIRM] = ControllerButton.Y

    persistence.save_meta()
    loaded = persistence.load_meta()['keybindings']

    assert persistence.load_meta()['post_cast'] == PostCastBehavior.EXPLORE
    assert loaded.bindings[InputAction.CONFIRM] == tcod.event.KeySym.SPACE
    assert loaded.controller[InputAction.CONFIRM] == ControllerButton.Y
    # An axis binding (the trigger scroll) survives the button/axis-tagged round trip.
    assert loaded.controller[InputAction.SCROLL_UP] == ControllerAxis.TRIGGERLEFT


def test_meta_round_trips_audio_volumes():
    HeadlessRunner(use_random_map=False)
    settings = esper.get_component(Settings)[0][1]
    settings.music_volume = 0.3
    settings.sfx_volume = 0.7
    settings.muted = True

    persistence.save_meta()
    loaded = persistence.load_meta()

    assert loaded['music_volume'] == 0.3
    assert loaded['sfx_volume'] == 0.7
    assert loaded['muted'] is True


def test_load_meta_defaults_when_file_absent():
    meta = persistence.load_meta()
    assert meta['recipes'] == {}
    assert meta['gold'] == 0
    assert meta['post_cast'] == PostCastBehavior.STAY
    assert meta['music_volume'] == 1.0
    assert meta['sfx_volume'] == 1.0
    assert meta['muted'] is False
    # No saved overrides: the empty maps layer over the in-code defaults at create time.
    assert meta['keybindings'].bindings == {}
    assert meta['keybindings'].controller == {}


def test_gold_pickup_defers_meta_write_until_flush():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    spawn_item_entity(ItemType('gold'), px + 1, py, count=5)

    runner.simulate_key(tcod.event.KeySym.RIGHT)

    # The pickup only marks meta dirty; it must not touch the disk mid-step.
    assert get_singleton(MetaSaveState).dirty is True
    assert persistence.load_meta()['gold'] == 0

    # flush_meta (the shutdown hook's job) then writes the pending gold and clears the flag.
    persistence.flush_meta()
    assert persistence.load_meta()['gold'] == 5
    assert get_singleton(MetaSaveState).dirty is False


def test_meta_save_system_flushes_pending_gold_when_paused():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    spawn_item_entity(ItemType('gold'), px + 1, py, count=5)
    runner.simulate_key(tcod.event.KeySym.RIGHT)

    # While exploring (unpaused) the MetaSaveSystem leaves the pending write alone.
    runner.tick()
    assert persistence.load_meta()['gold'] == 0

    # Pausing (a menu/modal) is the safe moment it writes the coalesced pickups.
    runner.game_state.display_mode = DisplayMode.MENU
    runner.tick()
    assert persistence.load_meta()['gold'] == 5
    assert get_singleton(MetaSaveState).dirty is False


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
