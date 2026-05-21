import esper
import tcod

from components import Modal
from constants import SCREEN_HEIGHT, SCREEN_WIDTH
from data_loaders import AssetLoader, get_game_configs
from entities import create_game_state, create_message_log, create_player
from input_handlers import handle_combining_input, handle_exploring_input, handle_menu_input, handle_modal_input
from procgen import generate_dungeon
from states import DisplayMode, GameState
from systems import RenderSystem
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

        # Add Rendering Processors
        render_system = RenderSystem(root_console, asset_loader)
        esper.add_processor(render_system)

        menu_system = MenuSystem(root_console, player, configs['spells'])
        esper.add_processor(menu_system)

        hud_system = HUDSystem(root_console, player)
        esper.add_processor(hud_system)

        modal_system = ModalSystem(root_console)
        esper.add_processor(modal_system)

        while True:
            root_console.clear()

            # Run all processors
            esper.process()

            context.present(root_console)

            # Fetch fresh game state
            game_state = esper.get_component(GameState)[0][1]

            for event in tcod.event.wait():
                if isinstance(event, tcod.event.Quit):
                    raise SystemExit()

                # Prioritize Modal Input
                if esper.get_component(Modal):
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


if __name__ == '__main__':
    main()
