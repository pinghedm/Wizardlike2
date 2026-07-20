import os
import shutil

import esper
import pygame
import pytest

from src import main, persistence
from src.audio import MusicTrack
from src.components import UIState
from src.constants import SAVE_DIR
from src.data_loaders import AssetLoader
from src.ecs_helpers import get_singleton
from src.states import DisplayMode, GameState, PendingTransition
from src.systems import (
    ActionSystem,
    AISystem,
    DeathSystem,
    FOVSystem,
    RenderSystem,
    StatusSystem,
)
from tests.headless_runner import HeadlessRunner


@pytest.fixture(autouse=True)
def clean_save_dir():
    if os.path.exists(SAVE_DIR):
        shutil.rmtree(SAVE_DIR)
    yield
    if os.path.exists(SAVE_DIR):
        shutil.rmtree(SAVE_DIR)


def test_init_game_world_builds_player_and_map():
    # use_random_map=True is the only path that runs init_game_world end to end.
    runner = HeadlessRunner(use_random_map=True)

    from src.components import Position, Stats
    from src.map_objects import Map

    assert esper.component_for_entity(runner.player, Position) is not None
    assert esper.component_for_entity(runner.player, Stats) is not None
    assert len(esper.get_component(Map)) == 1


def test_init_main_menu_sets_menu_mode_and_ui_state():
    esper.clear_database()
    main.init_main_menu()

    assert get_singleton(GameState).display_mode == DisplayMode.MENU
    assert get_singleton(UIState) is not None


def test_add_logic_systems_registers_processors():
    main.add_logic_systems()
    for processor in (DeathSystem, ActionSystem, StatusSystem, AISystem, FOVSystem):
        assert esper.get_processor(processor) is not None


def test_add_render_systems_registers_the_world_renderer():
    main.add_render_systems(pygame.Surface((320, 200)), AssetLoader())
    assert esper.get_processor(RenderSystem) is not None


# Every display mode maps to the looping track its screen should play.
@pytest.mark.parametrize(
    'mode, track',
    [
        (DisplayMode.MENU, MusicTrack.MENU),
        (DisplayMode.GAME_OVER, MusicTrack.MENU),
        (DisplayMode.SHOPPING, MusicTrack.SHOP),
        (DisplayMode.EXPLORING, MusicTrack.DUNGEON),
        (DisplayMode.TARGETING, MusicTrack.DUNGEON),
        (DisplayMode.COMBINING, MusicTrack.DUNGEON),
    ],
)
def test_track_for_mode_selects_music(mode, track):
    assert main._track_for_mode(mode) == track


# Every display_mode that dispatch_input routes to an input handler. A benign,
# unbound key (F1) hits each handler's fall-through, so this exercises the whole
# routing dimension -- including the SETTINGS branch -- without side effects.
ROUTED_MODES = [
    DisplayMode.EXPLORING,
    DisplayMode.MENU,
    DisplayMode.COMBINING,
    DisplayMode.CASTING,
    DisplayMode.TARGETING,
    DisplayMode.SETTINGS,
]


@pytest.mark.parametrize('mode', ROUTED_MODES)
def test_dispatch_input_routes_every_mode(mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = mode

    runner.simulate_key(pygame.K_F1)

    assert isinstance(runner.display_mode, DisplayMode)


def test_apply_pending_transition_saving_writes_file_and_resets_mode():
    runner = HeadlessRunner(use_random_map=False)

    main.apply_pending_transition(PendingTransition.SAVE, runner.game_state, runner.asset_loader)

    assert os.path.exists(persistence.SAVE_FILE)
    assert get_singleton(GameState).display_mode == DisplayMode.EXPLORING
    assert 'Game saved.' in runner.get_log_messages()


def test_apply_pending_transition_loading_restores_state():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.floor = 7
    persistence.save_game()

    # Mutate live state, then load it back via the transition.
    get_singleton(GameState).floor = 1
    main.apply_pending_transition(PendingTransition.LOAD_SAVE, get_singleton(GameState), runner.asset_loader)

    assert get_singleton(GameState).floor == 7
    assert get_singleton(GameState).display_mode == DisplayMode.EXPLORING


def test_apply_pending_transition_new_game_rebuilds_world():
    runner = HeadlessRunner(use_random_map=False)

    main.apply_pending_transition(PendingTransition.NEW_GAME, runner.game_state, runner.asset_loader)

    from src.components import PlayerTag
    from src.map_objects import Map

    assert len(esper.get_components(PlayerTag)) == 1
    assert len(esper.get_component(Map)) == 1
    assert get_singleton(GameState).display_mode == DisplayMode.EXPLORING


def test_apply_pending_transition_exiting_quits():
    runner = HeadlessRunner(use_random_map=False)

    with pytest.raises(SystemExit):
        main.apply_pending_transition(PendingTransition.EXIT, runner.game_state, runner.asset_loader)
