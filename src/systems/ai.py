import esper
import numpy as np
import tcod
import tcod.path

from src.components import (
    AI,
    Actor,
    Enemy,
    EnemyAbility,
    FieldOfView,
    FleeTag,
    GuardTag,
    MessageLog,
    PatrolTag,
    Point,
    Position,
    Stats,
    StatusType,
)
from src.constants import UI_MAGENTA, UI_RED
from src.debug import debug_log
from src.ecs_helpers import (
    chebyshev_distance,
    get_display_name,
    get_player,
    get_player_component,
    get_singleton,
    get_status,
    try_get_singleton,
)
from src.map_objects import Map
from src.states import GameState
from src.systems.combat import apply_effect, deal_damage
from src.systems.movement import get_action_cooldown, move_entity
from src.systems.utils import step_toward

# Memoized Dijkstra maps, keyed by goal tile, so each target's map is built once per AI tick.
type PathContext = dict[Point, tcod.path.Dijkstra]


def _ai_target(ent: int) -> Point | None:
    """The tile an AI entity is currently pathing toward, by behavior tag."""
    if esper.has_component(ent, PatrolTag):
        patrol = esper.component_for_entity(ent, PatrolTag)
        return patrol.path[patrol.index]
    return esper.component_for_entity(ent, AI).last_known_player_position


def _compute_path(ent: int, target: Point | None, pathfinding_context: PathContext) -> list[tuple[int, int]] | None:
    """Dijkstra path from the entity to target, reusing a precomputed map if available."""
    if not target:
        return None
    pos = esper.component_for_entity(ent, Position)

    pf = pathfinding_context.get(target)
    if not pf:
        game_map = get_singleton(Map)
        cost = game_map.walkable.astype(np.int32)
        pf = tcod.path.Dijkstra(cost, diagonal=1.41)
        pf.set_goal(target.x, target.y)

    path = pf.get_path(pos.x, pos.y)

    # tcod's Dijkstra path excludes the goal; add it back if reachable.
    if path and (path[0][0] != target.x or path[0][1] != target.y):
        path.insert(0, (target.x, target.y))

    return path


def _remember_player_if_seen(ent: int):
    """Update an entity's last-known player position when the player is in its FOV."""
    fov = esper.component_for_entity(ent, FieldOfView)
    player_pos = get_player_component(Position)
    if player_pos is not None and player_pos.point in fov.visible_tiles:
        esper.component_for_entity(ent, AI).last_known_player_position = player_pos.point


def _process_chase(ent: int, pos: Position, pathfinding_context: PathContext):
    _remember_player_if_seen(ent)
    target = esper.component_for_entity(ent, AI).last_known_player_position
    path = _compute_path(ent, target, pathfinding_context)
    if path and len(path) > 1:
        move_x, move_y = path[-2]
        move_entity(ent, move_x - pos.x, move_y - pos.y)


def _process_patrol(ent: int, pos: Position, pathfinding_context: PathContext):
    patrol = esper.component_for_entity(ent, PatrolTag)
    if pos.point == patrol.path[patrol.index]:
        patrol.index = (patrol.index + 1) % len(patrol.path)
    target = patrol.path[patrol.index]

    before = (pos.x, pos.y)
    path = _compute_path(ent, target, pathfinding_context)
    if path and len(path) > 1:
        move_x, move_y = path[-2]
        move_entity(ent, move_x - pos.x, move_y - pos.y)

    # Couldn't progress toward this waypoint (unreachable, or blocked by the exit
    # tile / a guardian) — give up on it and head for the next one.
    if (pos.x, pos.y) == before:
        patrol.index = (patrol.index + 1) % len(patrol.path)


def _process_guard(ent: int, pos: Position, pathfinding_context: PathContext):
    """Hold position. Guards never move; the AISystem still handles their melee
    and ranged attacks before reaching this movement branch."""
    pass


def _process_flee(ent: int, pos: Position, pathfinding_context: PathContext):
    _remember_player_if_seen(ent)
    target = esper.component_for_entity(ent, AI).last_known_player_position
    path = _compute_path(ent, target, pathfinding_context)
    if path and len(path) > 1:
        move_x, move_y = path[0]
        # Step directly away from the next tile toward the player.
        target_x = pos.x + step_toward(move_x, pos.x)
        target_y = pos.y + step_toward(move_y, pos.y)
        if get_singleton(Map).is_walkable(target_x, target_y):
            move_entity(ent, target_x - pos.x, target_y - pos.y)


def _can_use_ability(ent: int, pos: Position, player_pos: Position, ability: EnemyAbility) -> bool:
    """An ability fires when the player is within range and in the enemy's line of sight."""
    if chebyshev_distance(player_pos, pos) > ability.range:
        return False
    if esper.has_component(ent, FieldOfView):
        return player_pos.point in esper.component_for_entity(ent, FieldOfView).visible_tiles
    return True


def _use_ability(ent: int, player_ent: int, ability: EnemyAbility, log: MessageLog):
    log.add_simple_message(f'The {get_display_name(ent)} attacks from afar!', color=UI_MAGENTA)
    origin = esper.component_for_entity(ent, Position).point
    for effect in ability.effects:
        debug_log(f'  ability effect {effect.type} power={effect.power} dur={effect.duration} -> player {player_ent}')
        apply_effect(player_ent, effect, origin=origin, caster_ent=ent)


class AISystem(esper.Processor):
    """Drives tagged AI entities with FOV and Dijkstra pathfinding."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused:
            return

        game_map = try_get_singleton(Map)
        if not game_map:
            return

        player_ent = get_player()
        if player_ent is None:
            return
        player_pos = esper.component_for_entity(player_ent, Position)

        # 1. Collect unique targets so each goal's Dijkstra map is built once.
        targets_to_compute: set[Point] = set()
        for ent, _ai in esper.get_component(AI):
            target = _ai_target(ent)
            if target:
                targets_to_compute.add(target)

        cost = game_map.walkable.astype(np.int32)
        pathfinding_context: PathContext = {}
        for target in targets_to_compute:
            pf = tcod.path.Dijkstra(cost, diagonal=1.41)
            pf.set_goal(target.x, target.y)
            pathfinding_context[target] = pf

        # 2. Dispatch behavior by tag.
        for ent, (pos, _ai) in esper.get_components(Position, AI):
            actor = esper.try_component(ent, Actor)
            if actor and actor.cooldown > 0:
                continue

            # A lethally-hit enemy lingers in queries until DeathSystem's deferred delete is
            # purged next tick; skip it so a slain foe can't get a free retaliation.
            stats = esper.try_component(ent, Stats)
            if stats is not None and stats.hp <= 0:
                continue

            if get_status(ent, StatusType.STUN):
                continue

            enemy = esper.try_component(ent, Enemy)
            adjacent = abs(player_pos.x - pos.x) <= 1 and abs(player_pos.y - pos.y) <= 1

            # Melee if adjacent, else fire a ranged ability if one is in range, else move.
            if enemy and adjacent:
                debug_log(f'AI {ent} ({get_display_name(ent)}) melee at {(pos.x, pos.y)}')
                deal_damage(
                    player_ent,
                    enemy.attack_damage,
                    f'The {get_display_name(ent)} hits you!',
                    color=UI_RED,
                )
            elif enemy and enemy.ability and _can_use_ability(ent, pos, player_pos, enemy.ability):
                debug_log(f'AI {ent} ({get_display_name(ent)}) ability from {(pos.x, pos.y)}')
                _use_ability(ent, player_ent, enemy.ability, get_singleton(MessageLog))
            elif esper.has_component(ent, PatrolTag):
                _process_patrol(ent, pos, pathfinding_context)
            elif esper.has_component(ent, FleeTag):
                _process_flee(ent, pos, pathfinding_context)
            elif esper.has_component(ent, GuardTag):
                _process_guard(ent, pos, pathfinding_context)
            else:
                _process_chase(ent, pos, pathfinding_context)

            if actor:
                actor.cooldown = get_action_cooldown(ent, actor.speed)
