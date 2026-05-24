import time

import esper
import tcod

from src.components import Modal
from src.constants import SCREEN_HEIGHT, SCREEN_WIDTH, TICKS_PER_SECOND
from src.data_loaders import AssetLoader, get_game_configs
from src.entities import (
    create_configuration,
    create_game_state,
    create_keybindings,
    create_message_log,
    create_player,
    create_ui_state,
)
from src.input_handlers import (
    handle_casting_input,
    handle_combining_input,
    handle_exploring_input,
    handle_menu_input,
    handle_modal_input,
    handle_settings_input,
    handle_targeting_input,
)
from src.procgen import generate_dungeon
from src.states import DisplayMode, GameState
from src.systems import (
    ActionSystem,
    AISystem,
    DeathSystem,
    FOVSystem,
    RenderSystem,
    StatusSystem,
)
from src.ui_systems import HUDSystem, MenuSystem, ModalSystem, TargetingOverlaySystem


def init_game_world(asset_loader: AssetLoader):
    # Load Configs (memoized)
    configs = get_game_configs(asset_loader)

    # State
    create_game_state(floor=1)
    create_message_log()
    create_configuration(configs)
    create_ui_state()
    create_keybindings()

    # Generate Dungeon & Spawns
    game_map, player_start = generate_dungeon(
        max_rooms=30,
        room_min_size=6,
        room_max_size=10,
        max_items_per_room=2,
        tiles_config=configs['tiles'],
    )
    esper.create_entity(game_map)

    # ECS Entities
    player = create_player(player_start.x, player_start.y, configs['characters'])
    return player


def add_logic_systems():
    # Order matters: Death -> Action -> AI -> FOV
    esper.add_processor(DeathSystem())
    esper.add_processor(ActionSystem())
    esper.add_processor(StatusSystem())
    esper.add_processor(AISystem())
    esper.add_processor(FOVSystem())


def add_render_systems(root_console, asset_loader, player):
    esper.add_processor(RenderSystem(root_console, asset_loader))
    esper.add_processor(MenuSystem(root_console, player))
    esper.add_processor(HUDSystem(root_console, player))
    esper.add_processor(ModalSystem(root_console))
    esper.add_processor(TargetingOverlaySystem(root_console))


def dispatch_input(event: tcod.event.Event, game_state: GameState):
    if game_state.display_mode == DisplayMode.EXPLORING:
        game_state.display_mode = handle_exploring_input(event)
    elif game_state.display_mode == DisplayMode.MENU:
        game_state.display_mode = handle_menu_input(event)
    elif game_state.display_mode == DisplayMode.COMBINING:
        game_state.display_mode = handle_combining_input(event)
    elif game_state.display_mode == DisplayMode.CASTING:
        game_state.display_mode = handle_casting_input(event)
    elif game_state.display_mode == DisplayMode.TARGETING:
        game_state.display_mode = handle_targeting_input(event)
    elif game_state.display_mode == DisplayMode.SETTINGS:
        game_state.display_mode = handle_settings_input(event)


def main():
    # Asset Loader
    asset_loader = AssetLoader()

    # Load Configs (memoized) to register sprites/chars
    get_game_configs(asset_loader)

    # BUILD the master tileset
    tileset = asset_loader.build_tileset()

    player = init_game_world(asset_loader)

    with tcod.context.new(
        columns=SCREEN_WIDTH,
        rows=SCREEN_HEIGHT,
        width=SCREEN_WIDTH * 20,
        height=SCREEN_HEIGHT * 20,
        tileset=tileset,
        title='WizardLike',
        vsync=True,
    ) as context:
        root_console = tcod.console.Console(SCREEN_WIDTH, SCREEN_HEIGHT)

        add_logic_systems()
        add_render_systems(root_console, asset_loader, player)

        tick_rate = 1 / TICKS_PER_SECOND

        while True:
            frame_start = time.perf_counter()

            # Fetch fresh game state
            game_state = esper.get_component(GameState)[0][1]

            # Update time_paused based on mode or modals
            has_modal = bool(esper.get_component(Modal))
            game_state.time_paused = (game_state.display_mode != DisplayMode.EXPLORING) or has_modal

            root_console.clear()

            # Run all processors
            esper.process()

            context.present(root_console)

            for event in tcod.event.get():
                if isinstance(event, tcod.event.Quit):
                    raise SystemExit()

                # Prioritize Modal Input
                if has_modal:
                    handle_modal_input(event)
                    continue

                old_mode = game_state.display_mode
                dispatch_input(event, game_state)

                # If the state changed, break the event loop to redraw immediately
                if game_state.display_mode != old_mode:
                    break

            # Precise timing
            elapsed = time.perf_counter() - frame_start
            remaining = tick_rate - elapsed
            if remaining > 0:
                time.sleep(remaining)


if __name__ == '__main__':
    main()
