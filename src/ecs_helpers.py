"""Low-level ECS helpers shared across systems without coupling them.

`get_singleton` and the floor-pickup factory live here, below the `systems` package, so
both `systems` and `procgen.py` can use them without an import cycle (procgen already
imports from systems). Depends only on `esper` + `components`.
"""

import esper

from src.components import Configuration, Item, ItemType, PlayerTag, Position, Renderable
from src.constants import UI_WHITE, to_rgb


def get_singleton[T](component_type: type[T]) -> T:
    """Return the single instance of a startup singleton, raising if absent.

    For components that exist for the whole app lifetime (GameState, UIState). Use
    `try_get_singleton` for components that may legitimately be absent (e.g. Map and
    the rest of the game world before a dungeon is generated / at the title screen)."""
    components = esper.get_component(component_type)
    if not components:
        raise RuntimeError(f'singleton {component_type.__name__} not found')
    return components[0][1]


def try_get_singleton[T](component_type: type[T]) -> T | None:
    """Return the single instance of a singleton component, or None if absent."""
    components = esper.get_component(component_type)
    return components[0][1] if components else None


def get_display_name(entity: int) -> str:
    """Human-facing name for an entity, taken from its Renderable sprite id."""
    if esper.has_component(entity, Renderable):
        return esper.component_for_entity(entity, Renderable).sprite_id
    return 'enemy'


def actor_name(entity: int) -> str:
    """Subject form for log messages: 'You' for the player, 'The <name>' otherwise."""
    if esper.has_component(entity, PlayerTag):
        return 'You'
    return f'The {get_display_name(entity)}'


def spawn_item_entity(itype: ItemType, x: int, y: int, count: int = 1) -> int:
    """Create a floor pickup entity of `count` of `itype` at (x, y)."""
    configs = get_singleton(Configuration)
    item_config = configs.ingredients.get(itype)
    color = to_rgb(item_config['color']) if item_config else UI_WHITE
    return esper.create_entity(
        Position(x, y),
        Renderable(sprite_id=itype.value, color=color),
        Item(itype, count),
    )
