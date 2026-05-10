import esper
import tcod
from components import Inventory, Item, KnownRecipes, PlayerTag, Position, Renderable, SpellInventory, Stats
from data_loaders import load_ingredients_config, load_spells_config
from input_handlers import handle_combining_input, handle_exploring_input
from procgen import generate_dungeon
from states import DisplayMode, GameState
from systems import MovementSystem, RenderSystem
from ui_systems import HUDSystem, MenuSystem

def main():
    # Constants
    SCREEN_WIDTH, SCREEN_HEIGHT = 80, 50
    MAP_WIDTH, MAP_HEIGHT = 80, 45

    # Load Configs
    ingredients_config = load_ingredients_config()
    spells_config = load_spells_config()

    # Engine Setup
    tileset = tcod.tileset.load_tilesheet(
        'data/dejavu10x10_gs_tc.png', 32, 8, tcod.tileset.CHARMAP_TCOD
    )
    tcod.tileset.procedural_block_elements(tileset=tileset)
    game_map, player_start, rooms = generate_dungeon(
        MAP_WIDTH, MAP_HEIGHT, 30, 6, 10, 2
    )

    # State
    game_state = GameState(floor=1)

    # ECS World & Player
    player = esper.create_entity(
        Position(player_start.x, player_start.y),
        Renderable('\u2588', (255, 255, 255)),
        Stats(hp=100, max_hp=100),
        Inventory(),
        KnownRecipes(),
        SpellInventory(),
        PlayerTag(),
    )

    # Spawn Items
    for room in rooms:
        for p, item_list in room.items.items():
            for itype in item_list:
                config = ingredients_config[itype.value]
                esper.create_entity(
                    Position(p.x, p.y),
                    Renderable(config['char'], tuple(config['color'])),
                    Item(itype),
                )

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
        render_system = RenderSystem(root_console, game_map)
        esper.add_processor(render_system)
        
        menu_system = MenuSystem(root_console, player, spells_config, game_state)
        esper.add_processor(menu_system)
        
        hud_system = HUDSystem(root_console, player, game_state)
        esper.add_processor(hud_system)

        while True:
            root_console.clear()
            
            # Sync state
            render_system.state = game_state.display_mode
            
            # Run all processors
            esper.process()

            context.present(root_console)

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
