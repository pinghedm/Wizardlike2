import esper
import pygame

from src.components import (
    Configuration,
    ControllerButton,
    EnemyConfig,
    Inventory,
    ItemType,
    MessageLog,
    Point,
    Position,
    SpellInventory,
    SpellType,
)
from src.constants import WINDOW_HEIGHT, WINDOW_WIDTH
from src.data_loaders import AssetLoader, get_game_configs
from src.input_handlers import ControllerInput
from src.main import (
    add_logic_systems,
    apply_pending_transition,
    dispatch_input,
    init_game_world,
    update_pause_state,
)
from src.map_objects import Map, Tile
from src.procgen import spawn_enemy
from src.states import DisplayMode, GameState
from src.systems import refill_basic_spells


def _reset_processors():
    """Drop all registered processors.

    Production registers processors once at startup and lets them survive
    clear_database(); each HeadlessRunner instead rebuilds the world from scratch
    and re-runs add_logic_systems(), so without this the pipeline accumulates a
    duplicate set per runner and systems run multiple times per tick."""
    esper._processors.clear()
    esper._processors_dict.clear()


class HeadlessRunner:
    def __init__(self, use_random_map: bool = False):
        self.asset_loader = AssetLoader()
        # Pre-load configs to register sprites
        get_game_configs(self.asset_loader)

        if not use_random_map:
            self._inject_clean_room()
        else:
            esper.clear_database()
            _reset_processors()
            self.player = init_game_world(self.asset_loader)
            add_logic_systems()

        # A window-sized pygame Surface the render/UI tests draw into (constructed here,
        # not registered with esper).
        self.surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
        self._controller = ControllerInput()

    def _inject_clean_room(self, width: int = 20, height: int = 20):
        """Replace the procedurally generated map with a simple open room."""
        # 1. Total Reset
        esper.clear_database()
        _reset_processors()

        # 2. Re-init baseline state (Log, Config, UI, etc)
        from src.entities import (
            create_configuration,
            create_game_state,
            create_message_log,
            create_meta_save_state,
            create_player,
            create_run_stats,
            create_settings,
            create_ui_state,
        )

        configs = get_game_configs(self.asset_loader)

        create_game_state(floor=1)
        create_message_log()
        create_configuration(configs)
        create_ui_state()
        create_settings()
        create_run_stats()
        create_meta_save_state()

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

        # 5. Create player at center, stocked with the floor's basic attacks
        self.player = create_player(x=width // 2, y=height // 2)
        refill_basic_spells()

        # 6. Finally, add systems
        add_logic_systems()

    def tick(self, count: int = 1):
        """Simulate a number of game ticks."""
        game_state = esper.get_component(GameState)[0][1]
        for _ in range(count):
            update_pause_state(game_state)
            esper.process()

    def simulate_key(self, sym: int):
        """Simulate a key press and dispatch it to the current input handler."""
        event = pygame.event.Event(pygame.KEYDOWN, key=sym)
        game_state = esper.get_component(GameState)[0][1]
        transition = dispatch_input(event, game_state, self._controller, now=0.0)
        apply_pending_transition(transition, game_state, self.asset_loader)
        update_pause_state(esper.get_component(GameState)[0][1])

    def simulate_controller_button(self, button: ControllerButton, pressed: bool = True):
        """Simulate a controller button event through the same single input router the
        game loop uses: the d-pad drives movement, other buttons resolve through the
        controller (honoring the quick-cast modifier), after the Settings remap check."""
        game_state = esper.get_component(GameState)[0][1]
        event_type = pygame.CONTROLLERBUTTONDOWN if pressed else pygame.CONTROLLERBUTTONUP
        event = pygame.event.Event(event_type, button=int(button))
        transition = dispatch_input(event, game_state, self._controller, now=0.0)
        apply_pending_transition(transition, game_state, self.asset_loader)
        update_pause_state(esper.get_component(GameState)[0][1])

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

    def enemy_config(self, enemy_id: str = 'test_enemy') -> EnemyConfig:
        """Return a copy of a loaded enemy fixture config, safe to spread-override."""
        return dict(esper.get_component(Configuration)[0][1].enemies[enemy_id])

    def spawn_enemy(self, x: int, y: int, config: EnemyConfig | None = None, rooms=None) -> int:
        """Create an enemy at (x, y) via procgen's spawn path.

        Defaults to the 'test_enemy' fixture; pass a config (optionally
        spread-overridden, e.g. {**runner.enemy_config(), 'speed': 0}) to
        customize stats, behavior, or ability. Pass `rooms` when spawning a
        PATROL enemy so procgen can build its waypoints from the room centres.
        """
        if config is None:
            config = self.enemy_config()
        return spawn_enemy(config, x, y, rooms=rooms or [])

    def give_spell(self, spell_id: str, charges: int):
        """Grant the player charges of a spell."""
        spell_inv = esper.component_for_entity(self.player, SpellInventory)
        spell_inv.spells[SpellType(spell_id)] = charges

    def spell_charges(self, spell_id: str) -> int:
        """The player's remaining charges of a spell (0 if none)."""
        spell_inv = esper.component_for_entity(self.player, SpellInventory)
        return spell_inv.spells.get(SpellType(spell_id), 0)

    def give_item(self, item_id: str, count: int):
        """Add ingredient items to the player's inventory."""
        inv = esper.component_for_entity(self.player, Inventory)
        inv.items[ItemType(item_id)] += count

    def get_log_messages(self) -> list[str]:
        """Return all log lines as plain concatenated strings."""
        log = esper.get_component(MessageLog)[0][1]
        return [''.join(seg[0] for seg in msg) for msg in log.messages]

    def entity_at(self, x: int, y: int) -> int | None:
        """Return the first entity with a Position at (x, y), or None."""
        for ent, pos in esper.get_component(Position):
            if pos.x == x and pos.y == y:
                return ent
        return None
