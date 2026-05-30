"""Low-level ECS helpers shared across systems without coupling them.

`get_singleton` and the floor-pickup factory live here, below `systems.py`, so both
`systems.py` and `procgen.py` can use them without an import cycle (procgen already
imports from systems). Depends only on `esper` + `components`.
"""

import esper

from src.components import Configuration, Item, ItemType, Position, Renderable


def get_singleton(component_type):
    """Return the single instance of a singleton component, or None if absent."""
    components = esper.get_component(component_type)
    return components[0][1] if components else None


def spawn_item_entity(itype: ItemType, x: int, y: int, count: int = 1) -> int:
    """Create a floor pickup entity of `count` of `itype` at (x, y)."""
    configs = get_singleton(Configuration)
    item_config = configs.ingredients.get(itype.value, {}) if configs else {}
    color = tuple(item_config.get('color', (255, 255, 255)))
    return esper.create_entity(
        Position(x, y),
        Renderable(sprite_id=itype.value, color=color),
        Item(itype, count),
    )
