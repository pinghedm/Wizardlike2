import esper
import tcod.event

from src.components import Enemy, Item, Point, Position
from src.data_loaders import AssetLoader, get_game_configs
from src.main import add_logic_systems, dispatch_input, init_game_world
from src.map_objects import Map, Tile
from src.states import GameState


class HeadlessRunner:
    def __init__(self, use_random_map: bool = False):
        self.asset_loader = AssetLoader()
        # Pre-load configs to register sprites
        get_game_configs(self.asset_loader)
        # Build tileset
        self.asset_loader.build_tileset()

        if not use_random_map:
            self._inject_clean_room()
        else:
            esper.clear_database()
            self.player = init_game_world(self.asset_loader)
            add_logic_systems()

    def _inject_clean_room(self, width: int = 20, height: int = 20):
        """Replace the procedurally generated map with a simple open room."""
        # 1. Total Reset
        esper.clear_database()
        
        # 2. Re-init baseline state (Log, Config, UI, etc)
        from src.entities import create_configuration, create_game_state, create_keybindings, create_message_log, create_player, create_ui_state
        configs = get_game_configs(self.asset_loader)
        
        create_game_state(floor=1)
        create_message_log()
        create_configuration(configs)
        create_ui_state()
        create_keybindings()

        # 3. Create a basic floor tile
        floor_cfg = next(t for t in configs['tiles'] if t['type'] == 'floor')
        floor_tile = Tile(
            walkable=True,
            transparent=True,
            sprite_id=floor_cfg['id'],
            fg=tuple(floor_cfg.get('fg', (255, 255, 255))),
            bg=tuple(floor_cfg.get('bg', (0, 0, 0))),
        )

        # 4. Create the map and fill with floor
        clean_map = Map(width, height, floor_tile)
        esper.create_entity(clean_map)

        # 5. Create player at center
        self.player = create_player(width // 2, height // 2, configs['characters'])
        
        # 6. Finally, add systems
        add_logic_systems()

    def tick(self, count: int = 1):
        """Simulate a number of game ticks."""
        for _ in range(count):
            esper.process()

    def simulate_key(self, sym: tcod.event.KeySym):
        """Simulate a key press and dispatch it to the current input handler."""
        event = tcod.event.KeyDown(
            scancode=0,
            sym=sym,
            mod=tcod.event.Modifier.NONE,
            repeat=False,
        )
        game_state = esper.get_component(GameState)[0][1]
        dispatch_input(event, game_state)

    @property
    def player_pos(self) -> Point:
        pos = esper.component_for_entity(self.player, Position)
        return Point(pos.x, pos.y)
