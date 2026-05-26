import esper
import tcod.console
import tcod.event

from src.components import (
    AI,
    Actor,
    ChaseTag,
    Enemy,
    FieldOfView,
    Inventory,
    ItemType,
    MessageLog,
    Point,
    Position,
    Renderable,
    SpellInventory,
    SpellType,
    Stats,
    StatusEffects,
)
from src.constants import SCREEN_HEIGHT, SCREEN_WIDTH
from src.data_loaders import AssetLoader, get_game_configs
from src.main import add_logic_systems, dispatch_input, init_game_world, update_pause_state
from src.map_objects import Map, Tile
from src.states import DisplayMode, GameState
from src.ui_systems import HUDSystem, MenuSystem, ModalSystem, TargetingOverlaySystem


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

        # A real console for snapshot tests. The UI render processors are
        # instantiated but deliberately NOT registered with esper, so the
        # normal tick()/esper.process() path is unaffected.
        self.console = tcod.console.Console(SCREEN_WIDTH, SCREEN_HEIGHT)
        self._ui_systems = [
            MenuSystem(self.console),
            HUDSystem(self.console),
            ModalSystem(self.console),
            TargetingOverlaySystem(self.console),
        ]

    def _inject_clean_room(self, width: int = 20, height: int = 20):
        """Replace the procedurally generated map with a simple open room."""
        # 1. Total Reset
        esper.clear_database()

        # 2. Re-init baseline state (Log, Config, UI, etc)
        from src.entities import (
            create_configuration,
            create_game_state,
            create_keybindings,
            create_message_log,
            create_player,
            create_ui_state,
        )

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
        game_state = esper.get_component(GameState)[0][1]
        for _ in range(count):
            update_pause_state(game_state)
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
        update_pause_state(game_state)

    @property
    def player_pos(self) -> Point:
        pos = esper.component_for_entity(self.player, Position)
        return Point(pos.x, pos.y)

    @property
    def game_state(self) -> GameState:
        return esper.get_component(GameState)[0][1]

    @property
    def display_mode(self) -> DisplayMode:
        return self.game_state.display_mode

    def spawn_enemy(self, x: int, y: int, hp: int = 30, damage: int = 10, speed: int = 100) -> int:
        """Create an enemy entity at (x, y) mirroring procgen spawning."""
        return esper.create_entity(
            Position(x, y),
            Renderable(sprite_id='test_enemy', color=(0, 255, 0)),
            Actor(speed=speed),
            AI(),
            ChaseTag(),
            Enemy(attack_damage=damage, bump_damage=damage // 2),
            Stats(hp=hp, max_hp=hp),
            StatusEffects(),
            FieldOfView(radius=8),
        )

    def give_spell(self, spell_id: str, charges: int):
        """Grant the player charges of a spell."""
        spell_inv = esper.component_for_entity(self.player, SpellInventory)
        spell_inv.spells[SpellType(spell_id)] = charges

    def give_item(self, item_id: str, count: int):
        """Add ingredient items to the player's inventory."""
        inv = esper.component_for_entity(self.player, Inventory)
        inv.items[ItemType(item_id)] = inv.items.get(ItemType(item_id), 0) + count

    def get_log_messages(self) -> list[str]:
        """Return all log lines as plain concatenated strings."""
        log = esper.get_component(MessageLog)[0][1]
        return [''.join(seg[0] for seg in msg) for msg in log.messages]

    def render_ui(self):
        """Clear the console and run the UI render processors once.

        Does not advance game logic, so snapshots reflect the current ECS
        state regardless of pause state.
        """
        self.console.clear()
        for system in self._ui_systems:
            system.process()

    def get_console_text(self) -> list[str]:
        """Render the UI and return the console as one string per row.

        Empty cells read back as spaces (console.clear() fills with ' ').
        """
        self.render_ui()
        return [''.join(chr(c) for c in row) for row in self.console.ch]

    def get_console_fg(self, x: int, y: int) -> tuple[int, int, int]:
        """Render the UI and return the foreground RGB at cell (x, y)."""
        self.render_ui()
        return tuple(int(c) for c in self.console.fg[y, x])

    def get_console_bg(self, x: int, y: int) -> tuple[int, int, int]:
        """Render the UI and return the background RGB at cell (x, y)."""
        self.render_ui()
        return tuple(int(c) for c in self.console.bg[y, x])

    def entity_at(self, x: int, y: int) -> int | None:
        """Return the first entity with a Position at (x, y), or None."""
        for ent, pos in esper.get_component(Position):
            if pos.x == x and pos.y == y:
                return ent
        return None
