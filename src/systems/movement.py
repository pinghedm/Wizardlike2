import esper

from src.components import (
    Actor,
    Enemy,
    FieldOfView,
    Point,
    Position,
    StatusType,
)
from src.constants import PLAYER_MOVE_COST
from src.debug import debug_log
from src.ecs_helpers import get_status, is_player, try_get_singleton
from src.map_objects import Map
from src.systems.utils import step_toward


def _destination_blocked(mover: int, x: int, y: int) -> bool:
    """True if an actor already occupying (x, y) blocks the mover.

    The player may step onto a non-blocking enemy (the two overlap); every
    other actor-on-actor collision blocks movement.
    """
    for other_ent, (other_pos, _actor) in esper.get_components(Position, Actor):
        if other_ent == mover or other_pos.x != x or other_pos.y != y:
            continue
        if (
            is_player(mover)
            and esper.has_component(other_ent, Enemy)
            and not esper.component_for_entity(other_ent, Enemy).blocks_movement
        ):
            continue
        return True
    return False


def move_entity(entity: int, dx: int, dy: int):
    """Move an entity by (dx, dy) if the destination is walkable and unblocked.

    Pure movement: combat (e.g. bumping into an enemy) is the caller's concern.
    """
    pos = esper.component_for_entity(entity, Position)
    new_x = pos.x + dx
    new_y = pos.y + dy

    game_map = try_get_singleton(Map)
    if not game_map:
        return

    if not game_map.is_walkable(new_x, new_y):
        return

    # Enemies may not step onto exit tiles.
    if not is_player(entity) and game_map.tiles[new_x][new_y].is_exit:
        return

    if _destination_blocked(entity, new_x, new_y):
        return

    pos.x = new_x
    pos.y = new_y
    debug_log(f'move_entity {entity} -> {(new_x, new_y)} (player={is_player(entity)})')

    if esper.has_component(entity, FieldOfView):
        esper.component_for_entity(entity, FieldOfView).dirty = True

    # Player move consumes a turn at the base player move cost.
    if is_player(entity):
        actor = esper.component_for_entity(entity, Actor)
        actor.cooldown = get_action_cooldown(entity, PLAYER_MOVE_COST)


def apply_knockback(target_ent: int, origin: Point, distance: int):
    """Shove `target_ent` up to `distance` tiles directly away from `origin`.

    Steps one tile at a time along the away-from-origin direction, halting at the
    first wall or occupied tile. A target sitting on the origin has no direction and
    stays put."""
    pos = esper.component_for_entity(target_ent, Position)
    step_x = step_toward(origin.x, pos.x)
    step_y = step_toward(origin.y, pos.y)
    if step_x == 0 and step_y == 0:
        return

    game_map = try_get_singleton(Map)
    if not game_map:
        return

    for _ in range(distance):
        nx, ny = pos.x + step_x, pos.y + step_y
        if not game_map.is_walkable(nx, ny) or _destination_blocked(target_ent, nx, ny):
            break
        pos.x, pos.y = nx, ny

    if esper.has_component(target_ent, FieldOfView):
        esper.component_for_entity(target_ent, FieldOfView).dirty = True


def get_action_cooldown(entity: int, base_speed: int) -> int:
    """Calculate cooldown based on status effects."""
    if get_status(entity, StatusType.SLOW):
        return base_speed * 2
    if get_status(entity, StatusType.HASTE):
        return max(0, base_speed // 2)
    return max(0, base_speed)
