import time

import esper
import tcod

from components import Modal
from constants import SCREEN_HEIGHT, SCREEN_WIDTH, TICKS_PER_SECOND
from data_loaders import AssetLoader, get_game_configs
from entities import create_game_state, create_message_log, create_player
from input_handlers import handle_combining_input, handle_exploring_input, handle_menu_input, handle_modal_input
from procgen import generate_dungeon
from states import DisplayMode, GameState
from systems import ActionSystem, AISystem, DeathSystem, FOVSystem, RenderSystem
from ui_systems import HUDSystem, MenuSystem, ModalSystem


def main():
    # Asset Loader
    asset_loader = AssetLoader()

    # Load Configs (memoized)
    configs = get_game_configs(asset_loader)

    # State
    create_game_state(floor=1)
    create_message_log()

    # BUILD the master tileset
    tileset = asset_loader.build_tileset()

    # Generate Dungeon & Spawns
    game_map, player_start = generate_dungeon(
        max_rooms=30,
        room_min_size=6,
        room_max_size=10,
        max_items_per_room=2,
        ingredients_config=configs['ingredients'],
        tiles_config=configs['tiles'],
    )
    esper.create_entity(game_map)

    # ECS Entities
    player = create_player(player_start.x, player_start.y, configs['characters'])

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

        # Add Processors
        # Order matters: Death -> Action -> AI -> FOV -> Render -> UI
        esper.add_processor(DeathSystem())
        esper.add_processor(ActionSystem())
        esper.add_processor(AISystem())
        esper.add_processor(FOVSystem())
        esper.add_processor(RenderSystem(root_console, asset_loader))

        menu_system = MenuSystem(root_console, player, configs['spells'])
        esper.add_processor(menu_system)

        esper.add_processor(HUDSystem(root_console, player))
        esper.add_processor(ModalSystem(root_console))

        tick_rate = 1 / TICKS_PER_SECOND

        while True:
            frame_start = time.perf_counter()

            root_console.clear()

            # Fetch fresh game state
            game_state = esper.get_component(GameState)[0][1]

            # Update time_paused based on mode or modals
            has_modal = bool(esper.get_component(Modal))
            game_state.time_paused = (game_state.display_mode != DisplayMode.EXPLORING) or has_modal

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
                if game_state.display_mode == DisplayMode.EXPLORING:
                    game_state.display_mode = handle_exploring_input(event, player)
                elif game_state.display_mode == DisplayMode.MENU:
                    game_state.display_mode = handle_menu_input(event, menu_system)
                elif game_state.display_mode == DisplayMode.COMBINING:
                    game_state.display_mode = handle_combining_input(event, player, menu_system, configs['spells'])

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
