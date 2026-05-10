import esper
import tcod
from components import ItemType, SpellType
from data_loaders import (AssetLoader, load_characters_config,
                          load_ingredients_config, load_spells_config,
                          load_tiles_config)
from entities import create_game_state, create_player
from input_handlers import handle_combining_input, handle_exploring_input
from procgen import generate_dungeon
from states import DisplayMode, GameState
from systems import MovementSystem, RenderSystem
from ui_systems import HUDSystem, MenuSystem


def main():
    # Constants
    SCREEN_WIDTH, SCREEN_HEIGHT = 80, 50
    MAP_WIDTH, MAP_HEIGHT = 80, 45

    # Asset Loader
    asset_loader = AssetLoader()

    # Load Configs
    ingredients_config = load_ingredients_config(asset_loader)
    spells_config = load_spells_config(asset_loader)
    characters_config = load_characters_config(asset_loader)
    tiles_config = load_tiles_config(asset_loader)

    # State
    create_game_state(floor=1)

    # BUILD the master tileset
    tileset = asset_loader.build_tileset()

    # Generate Dungeon & Spawns
    game_map, player_start = generate_dungeon(MAP_WIDTH, MAP_HEIGHT, 30, 6, 10, 2, ingredients_config, tiles_config)

    # ECS Entities
    player = create_player(player_start.x, player_start.y, characters_config)

    # Systems
    movement_system = MovementSystem(game_map)

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
        render_system = RenderSystem(root_console, game_map, asset_loader)
        esper.add_processor(render_system)

        menu_system = MenuSystem(root_console, player, spells_config)
        esper.add_processor(menu_system)

        hud_system = HUDSystem(root_console, player)
        esper.add_processor(hud_system)

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

                old_mode = game_state.display_mode
                if game_state.display_mode == DisplayMode.EXPLORING:
                    game_state.display_mode = handle_exploring_input(event, player, game_map, movement_system)
                elif game_state.display_mode == DisplayMode.COMBINING:
                    game_state.display_mode = handle_combining_input(event, player, menu_system, spells_config)

                # If the state changed, break the event loop to redraw immediately
                if game_state.display_mode != old_mode:
                    break



if __name__ == '__main__':
    main()
