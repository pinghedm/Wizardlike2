import esper

from components import (
    Actor,
    Configuration,
    FieldOfView,
    Inventory,
    KnownRecipes,
    MessageLog,
    PlayerTag,
    Position,
    Renderable,
    SpellInventory,
    Stats,
    UIState,
)
from states import GameState


def create_game_state(floor=1):
    """Create the singleton GameState entity."""
    return esper.create_entity(GameState(floor=floor))


def create_message_log():
    """Create the singleton MessageLog entity."""
    return esper.create_entity(MessageLog())


def create_configuration(configs):
    """Create the singleton Configuration entity."""
    return esper.create_entity(
        Configuration(
            ingredients=configs['ingredients'],
            spells=configs['spells'],
            characters=configs['characters'],
            tiles=configs['tiles'],
        )
    )


def create_ui_state():
    """Create the singleton UIState entity."""
    return esper.create_entity(UIState())


def create_player(x, y, characters_config):
    """Factory function for the player entity."""
    # The ID 'player' is registered in AssetLoader (either as a sprite or char '@')
    sprite_id = 'player'

    return esper.create_entity(
        Position(x, y),
        Actor(speed=0),
        FieldOfView(radius=8),
        Renderable(sprite_id=sprite_id, color=(255, 255, 255)),
        Stats(hp=100, max_hp=100),
        Inventory(),
        KnownRecipes(),
        SpellInventory(),
        PlayerTag(),
    )
