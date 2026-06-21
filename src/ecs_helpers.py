"""Low-level ECS helpers shared across systems without coupling them.

`get_singleton` and the floor-pickup factory live here, below the `systems` package, so
both `systems` and `procgen.py` can use them without an import cycle (procgen already
imports from systems). Depends only on `esper` + `components`.
"""

from abc import ABC, abstractmethod

import esper

from src.components import (
    Configuration,
    Effect,
    FieldOfView,
    Item,
    ItemType,
    PlayerTag,
    Position,
    Renderable,
    StatusEffects,
    StatusType,
)
from src.constants import UI_WHITE, to_rgb


class RuntimeSingleton(ABC):
    """Interface for ECS singletons that wrap unpicklable runtime state (an audio device, a
    window handle, ...) rather than game state.

    Such a service is reached through the world like any other singleton, but it can't ride
    along in a save: `persistence.save_game` skips any component carrying `DO_NOT_PICKLE`, and
    because `clear_database()` (on new game / load / return-to-title) drops it, whoever owns
    the instance calls `reload_after_clear()` to re-register it with the fresh world. The
    re-registration mechanism is the implementer's, so subclasses override it.
    """

    DO_NOT_PICKLE = True

    @abstractmethod
    def reload_after_clear(self) -> None:
        """Re-register this service with the world after a clear_database()."""
        ...


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


def get_player() -> int | None:
    """The player entity, or None if no player exists (e.g. at the title screen)."""
    players = esper.get_component(PlayerTag)
    return players[0][0] if players else None


def get_player_component[T](component_type: type[T]) -> T | None:
    """The player's `component_type`, or None when there's no player / no such component."""
    player = get_player()
    if player is None or not esper.has_component(player, component_type):
        return None
    return esper.component_for_entity(player, component_type)


def is_player(entity: int) -> bool:
    """Whether `entity` is the player (carries the PlayerTag)."""
    return esper.has_component(entity, PlayerTag)


def get_status(entity: int, status_type: StatusType) -> Effect | None:
    """The entity's active effect of `status_type`, or None if it has none."""
    if not esper.has_component(entity, StatusEffects):
        return None
    return esper.component_for_entity(entity, StatusEffects).active.get(status_type)


def mark_fov_dirty(entity: int):
    """Flag an entity's field of view for recompute on the next FOVSystem tick."""
    fov = esper.try_component(entity, FieldOfView)
    if fov:
        fov.dirty = True


def get_display_name(entity: int) -> str:
    """Human-facing name for an entity, taken from its Renderable sprite id."""
    if esper.has_component(entity, Renderable):
        return esper.component_for_entity(entity, Renderable).sprite_id
    return 'enemy'


def actor_name(entity: int) -> str:
    """Subject form for log messages: 'You' for the player, 'The <name>' otherwise."""
    if is_player(entity):
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
