import esper
import tcod
from components import Inventory, Item, KnownRecipes, PlayerTag, Position, Renderable, SpellInventory
from data_loaders import load_ingredients_config, load_spells_config
from input_handlers import handle_combining_input, handle_exploring_input
from procgen import generate_dungeon
from states import GameState
from systems import MovementSystem, RenderSystem
from ui_systems import MenuSystem

def main():
    # Constants
    SCREEN_WIDTH, SCREEN_HEIGHT = 80, 50
    MAP_WIDTH, MAP_HEIGHT = 80, 45

    # Load Configs
    ingredients_config = load_ingredients_config()
    spells_config = load_spells_config()

    # Engine Setup
    tileset = tcod.tileset.procedural_block_elements(shape=(16, 16))
    game_map, player_start, rooms = generate_dungeon(
        MAP_WIDTH, MAP_HEIGHT, 30, 6, 10, 2
    )

    # ECS World & Player
    player = esper.create_entity(
        Position(player_start.x, player_start.y),
        Renderable('\u2588', (255, 255, 255)),
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
        tileset=tileset,
        title='WizardLike',
        vsync=True,
    ) as context:
        root_console = tcod.console.Console(SCREEN_WIDTH, SCREEN_HEIGHT)
        
        # Add Rendering Processors
        render_system = RenderSystem(root_console, game_map)
        esper.add_processor(render_system)
        
        menu_system = MenuSystem(root_console, player, spells_config)
        esper.add_processor(menu_system)

        state = GameState.EXPLORING

        while True:
            root_console.clear()
            
            # Sync state to Systems (for rendering)
            render_system.state = state
            menu_system.state = state
            
            # Run all processors
            esper.process()

            context.present(root_console)

            for event in tcod.event.wait():
                if isinstance(event, tcod.event.Quit):
                    raise SystemExit()
                
                old_state = state
                if state == GameState.EXPLORING:
                    state = handle_exploring_input(event, player, game_map, movement_system)
                elif state == GameState.COMBINING:
                    state = handle_combining_input(event, player, menu_system, spells_config)
                
                # If the state changed, break the event loop to redraw immediately
                if state != old_state:
                    break

if __name__ == '__main__':
    main()
