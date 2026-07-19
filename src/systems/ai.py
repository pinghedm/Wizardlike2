import esper

from src.components import (
    AI,
    Actor,
    Boss,
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
from src.pathfinding import Dijkstra
from src.states import GameState
from src.systems.combat import apply_effect, deal_damage
from src.systems.movement import get_action_cooldown, move_entity
from src.systems.utils import step_toward
from src.systems.visuals import trigger_projectile

# Memoized Dijkstra maps, keyed by goal tile, so each target's map is built once per AI tick.
type PathContext = dict[Point, Dijkstra]

# Cap on how far the pure-Python Dijkstra floods from a goal. Comfortably larger than the on-screen
# radius (viewport ~40 tiles, player centered), so a chase in view still finds its path, but it keeps
# a fresh flood cheap when the goal churns as the player runs — a foe further than this just idles.
_MAX_PATH_DIST = 45.0


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
        pf = Dijkstra(game_map.walkable, diagonal=1.41)
        pf.set_goal(target.x, target.y, _MAX_PATH_DIST)

    path = pf.get_path(pos.x, pos.y)

    # get_path excludes the goal tile; add it back at the front if reachable.
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


def _use_ability(ent: int, player_ent: int, ability: EnemyAbility, log: MessageLog, label: str = ''):
    action = f'unleashes {label}' if label else 'attacks from afar'
    log.add_simple_message(f'The {get_display_name(ent)} {action}!', color=UI_MAGENTA)
    origin = esper.component_for_entity(ent, Position).point

    # Fly a cosmetic glyph from the enemy to the player, styled like the player's own
    # spell projectiles. Effects below land immediately; the projectile is purely visual.
    if ability.effects:
        player_pos = esper.component_for_entity(player_ent, Position).point
        trigger_projectile(start=origin, target=player_pos, effect_type=ability.effects[0].type, burst_radius=0)

    for effect in ability.effects:
        debug_log(f'  ability effect {effect.type} power={effect.power} dur={effect.duration} -> player {player_ent}')
        apply_effect(player_ent, effect, origin=origin, caster_ent=ent)


def _select_boss_ability(boss: Boss, hp_frac: float, in_range: list[bool]) -> int | None:
    """Index of the boss ability to fire this turn, or None if none is ready. An ability is ready
    when it's in range, off cooldown, and phase-available (`hp_frac <= hp_threshold`). Among those,
    pick the latest-phase one (lowest threshold) so the fight escalates as the boss is worn down."""
    ready = [
        i for i, ba in enumerate(boss.abilities) if in_range[i] and boss.timers[i] == 0 and hp_frac <= ba.hp_threshold
    ]
    if not ready:
        return None
    return min(ready, key=lambda i: boss.abilities[i].hp_threshold)


def _boss_phase_level(boss: Boss, hp_frac: float) -> int:
    """How many phase-gated (threshold < 1.0) abilities the boss's current HP has unlocked."""
    return sum(1 for ba in boss.abilities if ba.hp_threshold < 1.0 and hp_frac <= ba.hp_threshold)


def _use_boss_ability(ent: int, boss: Boss, pos: Position, player_pos: Position, player_ent: int, log: MessageLog):
    """Advance the boss's cooldowns and phase, then fire its best ready ability. Returns whether one
    fired, so the AI dispatch falls through to movement when the boss can't attack this turn."""
    boss.timers = [max(0, t - 1) for t in boss.timers]

    stats = esper.component_for_entity(ent, Stats)
    hp_frac = stats.hp / stats.max_hp if stats.max_hp else 0.0

    level = _boss_phase_level(boss, hp_frac)
    if level > boss.phase:
        boss.phase = level
        log.add_simple_message(f'The {get_display_name(ent)} grows more dangerous!', color=UI_MAGENTA)

    in_range = [_can_use_ability(ent, pos, player_pos, ba.ability) for ba in boss.abilities]
    idx = _select_boss_ability(boss, hp_frac, in_range)
    if idx is None:
        return False
    chosen = boss.abilities[idx]
    _use_ability(ent, player_ent, chosen.ability, log, label=chosen.name)
    boss.timers[idx] = chosen.cooldown
    return True


def _try_ranged_attack(ent: int, enemy: Enemy, pos: Position, player_pos: Position, player_ent: int, log: MessageLog):
    """Fire a ranged attack if one is ready: a boss's phase-gated set, else a plain foe's single
    ability. Returns whether an attack fired (a boss still ticks cooldowns/phases either way)."""
    boss = esper.try_component(ent, Boss)
    if boss is not None:
        return _use_boss_ability(ent, boss, pos, player_pos, player_ent, log)
    if enemy.ability is not None and _can_use_ability(ent, pos, player_pos, enemy.ability):
        _use_ability(ent, player_ent, enemy.ability, log)
        return True
    return False


class AISystem(esper.Processor):
    """Drives tagged AI entities with FOV and Dijkstra pathfinding."""

    # Cap on cached distance fields (each ~ a map-sized array), cleared past this so exploring one
    # floor for a long time can't grow the cache unbounded.
    PATH_CACHE_LIMIT = 64

    def __init__(self) -> None:
        super().__init__()
        # Dijkstra distance fields keyed by (goal, flood bound), reused across frames: the walkable
        # grid is static within a floor, so a repeated goal (a standing player, a patrol waypoint)
        # builds once instead of re-flooding the whole map in pure Python every tick.
        self._path_cache: dict[tuple[Point, float | None], Dijkstra] = {}
        self._cache_map: Map | None = None

    def _field_for(self, game_map: Map, target: Point, max_dist: float | None) -> Dijkstra:
        """The cached (or freshly built) distance field to `target`, flooded out to `max_dist`."""
        key = (target, max_dist)
        pf = self._path_cache.get(key)
        if pf is None:
            if len(self._path_cache) >= self.PATH_CACHE_LIMIT:
                self._path_cache.clear()
            pf = Dijkstra(game_map.walkable, diagonal=1.41)
            pf.set_goal(target.x, target.y, max_dist)
            self._path_cache[key] = pf
        return pf

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused:
            return

        game_map = try_get_singleton(Map)
        if not game_map:
            return
        # A new floor swaps in a different Map (and walkable grid), so the cached fields no longer apply.
        if game_map is not self._cache_map:
            self._path_cache.clear()
            self._cache_map = game_map

        player_ent = get_player()
        if player_ent is None:
            return
        player_pos = esper.component_for_entity(player_ent, Position)

        # 1. Collect unique goals, split by whether the flood should be distance-bounded. Patrol
        # waypoints are far and static (flood the whole map, then cache), while chase and flee goals
        # sit near the player and churn as it moves, so they're bounded to keep a fresh flood cheap.
        patrol_targets: set[Point] = set()
        near_targets: set[Point] = set()
        for ent, _ai in esper.get_component(AI):
            patrol = esper.try_component(ent, PatrolTag)
            if patrol is not None:
                # The current waypoint and the next one, since _process_patrol may advance on arrival
                # within this same tick; both are static, so they build once and then cache.
                patrol_targets.add(patrol.path[patrol.index])
                patrol_targets.add(patrol.path[(patrol.index + 1) % len(patrol.path)])
            else:
                target = _ai_target(ent)
                if target is not None:
                    near_targets.add(target)

        pathfinding_context: PathContext = {}
        for target in patrol_targets:
            pathfinding_context[target] = self._field_for(game_map, target, None)
        for target in near_targets:
            pathfinding_context.setdefault(target, self._field_for(game_map, target, _MAX_PATH_DIST))

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
            elif enemy and _try_ranged_attack(ent, enemy, pos, player_pos, player_ent, get_singleton(MessageLog)):
                debug_log(f'AI {ent} ({get_display_name(ent)}) ranged attack from {(pos.x, pos.y)}')
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
