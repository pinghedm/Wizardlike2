import esper

from components import Inventory, KnownRecipes, PlayerTag, Position, Renderable, SpellInventory, Stats
from states import GameState


def create_game_state(floor=1):
    """Create the singleton GameState entity."""
    return esper.create_entity(GameState(floor=floor))


def create_player(x, y, characters_config):
    """Factory function for the player entity."""
    # The ID 'player' is registered in AssetLoader (either as a sprite or char '@')
    sprite_id = 'player'

    return esper.create_entity(
        Position(x, y),
        Renderable(sprite_id=sprite_id, color=(255, 255, 255)),
        Stats(hp=100, max_hp=100),
        Inventory(),
        KnownRecipes(),
        SpellInventory(),
        PlayerTag(),
    )
