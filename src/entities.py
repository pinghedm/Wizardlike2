import esper
import tcod

from src.components import (
    Actor,
    Configuration,
    FieldOfView,
    GameConfigs,
    Inventory,
    ItemType,
    Keybindings,
    KnownRecipes,
    MessageLog,
    PlayerTag,
    Position,
    Renderable,
    RunStats,
    SpellInventory,
    Stats,
    StatusEffects,
    UIState,
)
from src.persistence import MetaData
from src.states import GameState


def create_game_state(floor: int = 1):
    """Create the singleton GameState entity."""
    return esper.create_entity(GameState(floor=floor))


def create_message_log():
    """Create the singleton MessageLog entity."""
    return esper.create_entity(MessageLog())


def create_configuration(configs: GameConfigs):
    """Create the singleton Configuration entity."""
    return esper.create_entity(
        Configuration(
            ingredients=configs['ingredients'],
            spells=configs['spells'],
            characters=configs['characters'],
            tiles=configs['tiles'],
            enemies=configs['enemies'],
        )
    )


def create_ui_state():
    """Create the singleton UIState entity."""
    return esper.create_entity(UIState())


def create_run_stats():
    """Create the singleton RunStats entity for a fresh run."""
    return esper.create_entity(RunStats())


def create_keybindings():
    """Create the singleton Keybindings entity."""
    return esper.create_entity(
        Keybindings(
            bindings={
                'MOVE_UP': tcod.event.KeySym.UP,
                'MOVE_DOWN': tcod.event.KeySym.DOWN,
                'MOVE_LEFT': tcod.event.KeySym.LEFT,
                'MOVE_RIGHT': tcod.event.KeySym.RIGHT,
                'OPEN_CRAFTING': tcod.event.KeySym.C,
                'OPEN_CASTING': tcod.event.KeySym.S,
                'CONFIRM': tcod.event.KeySym.RETURN,
                'CANCEL': tcod.event.KeySym.ESCAPE,
                'CYCLE_TAB': tcod.event.KeySym.TAB,
            }
        )
    )


def create_player(x: int, y: int, meta: MetaData | None = None):
    """Factory function for the player entity, seeded with cross-run progression."""
    # The ID 'player' is registered in AssetLoader (either as a sprite or char '@')
    sprite_id = 'player'

    known_recipes = KnownRecipes()
    if meta:
        known_recipes.recipes = meta['recipes']

    inventory = Inventory()
    if meta and meta['gold']:
        inventory.items[ItemType.GOLD] = meta['gold']

    return esper.create_entity(
        Position(x, y),
        Actor(speed=0),
        FieldOfView(radius=8),
        Renderable(sprite_id=sprite_id, color=(255, 255, 255)),
        Stats(hp=100, max_hp=100),
        inventory,
        known_recipes,
        SpellInventory(),
        StatusEffects(),
        PlayerTag(),
    )
