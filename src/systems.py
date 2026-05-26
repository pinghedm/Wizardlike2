import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import esper
import numpy as np
import tcod
import tcod.map
import tcod.path
from tcod import libtcodpy

from src.components import (
    AI,
    Actor,
    Configuration,
    Effect,
    EffectType,
    Enemy,
    FieldOfView,
    FleeTag,
    MessageLog,
    Modal,
    PatrolTag,
    PlayerTag,
    Point,
    Position,
    Renderable,
    SpellConfig,
    SpellInventory,
    SpellType,
    Stats,
    StatusEffects,
    StatusType,
)
from src.constants import STATUS_PULSE_INTERVAL
from src.map_objects import Map
from src.states import DisplayMode, GameState

if TYPE_CHECKING:
    from src.data_loaders import AssetLoader


def get_singleton(component_type):
    """Return the single instance of a singleton component, or None if absent."""
    components = esper.get_component(component_type)
    return components[0][1] if components else None


def is_game_active() -> bool:
    """True when a run is in progress (a player entity exists).

    Used to decide between the title menu and the in-game pause menu.
    """
    return bool(esper.get_components(PlayerTag))


def get_display_name(entity: int) -> str:
    """Human-facing name for an entity, taken from its Renderable sprite id."""
    if esper.has_component(entity, Renderable):
        return esper.component_for_entity(entity, Renderable).sprite_id
    return 'enemy'


def deal_damage(target_ent: int, amount: int, message: str, color: tuple[int, int, int]):
    """Apply damage to a target's Stats and log a message."""
    stats = esper.component_for_entity(target_ent, Stats)
    stats.hp -= amount
    log = get_singleton(MessageLog)
    if log:
        log.add_simple_message(message, color=color)


class DeathSystem(esper.Processor):
    """Handles death for all entities with Stats."""

    def process(self):
        log = get_singleton(MessageLog)

        for ent, stats in esper.get_component(Stats):
            if stats.hp <= 0:
                if esper.has_component(ent, PlayerTag):
                    if not esper.get_component(Modal):
                        esper.create_entity(
                            Modal(
                                message='You have died! Press Enter to quit.',
                                on_close=lambda: sys.exit(),
                            )
                        )
                else:
                    if log:
                        log.add_simple_message(f'The {get_display_name(ent)} dies!', color=(255, 255, 0))
                    esper.delete_entity(ent)


class ActionSystem(esper.Processor):
    """Manages cooldowns for all actors."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused:
            return

        for _ent, actor in esper.get_component(Actor):
            if actor.cooldown > 0:
                actor.cooldown -= 1


def _apply_status_pulse(ent: int, status_type: StatusType, power: int, log: MessageLog | None):
    """Apply one pulse of a recurring status effect (poison damage / regen heal)."""
    stats = esper.component_for_entity(ent, Stats)
    name = 'You' if esper.has_component(ent, PlayerTag) else f'The {get_display_name(ent)}'

    if status_type == StatusType.POISON:
        stats.hp -= power
        if log:
            log.add_simple_message(f'{name} took {power} poison damage!', color=(50, 200, 50))
    elif status_type == StatusType.REGEN:
        stats.hp = min(stats.max_hp, stats.hp + power)
        if log:
            log.add_simple_message(f'{name} regained {power} HP.', color=(0, 255, 0))


class StatusSystem(esper.Processor):
    """Ages active status effects and applies recurring ones each pulse."""

    def process(self):
        game_state = esper.get_component(GameState)[0][1]
        if game_state.time_paused:
            return

        log = get_singleton(MessageLog)
        for ent, status in esper.get_component(StatusEffects):
            for status_type in list(status.active.keys()):
                effect = status.active[status_type]
                # Recurring effects carry power; they pulse on the global cadence.
                if effect.power and effect.duration % STATUS_PULSE_INTERVAL == 0:
                    _apply_status_pulse(ent, status_type, effect.power, log)
                effect.duration -= 1
                if effect.duration <= 0:
                    del status.active[status_type]


def _ai_target(ent: int) -> Point | None:
    """The tile an AI entity is currently pathing toward, by behavior tag."""
    if esper.has_component(ent, PatrolTag):
        patrol = esper.component_for_entity(ent, PatrolTag)
        return patrol.path[patrol.index]
    return esper.component_for_entity(ent, AI).last_known_player_position


def _compute_path(ent: int, target: Point | None, pathfinding_context: dict) -> list | None:
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
    if isinstance(path, np.ndarray):
        path = path.tolist()

    # tcod's Dijkstra path excludes the goal; add it back if reachable.
    if path and (path[0][0] != target.x or path[0][1] != target.y):
        path.insert(0, [target.x, target.y])

    return path


def _remember_player_if_seen(ent: int):
    """Update an entity's last-known player position when the player is in its FOV."""
    fov = esper.component_for_entity(ent, FieldOfView)
    player_pos = esper.get_components(Position, PlayerTag)[0][1][0]
    if player_pos.point in fov.visible_tiles:
        esper.component_for_entity(ent, AI).last_known_player_position = player_pos.point


def _process_chase(ent: int, pos: Position, pathfinding_context: dict):
    _remember_player_if_seen(ent)
    target = esper.component_for_entity(ent, AI).last_known_player_position
    path = _compute_path(ent, target, pathfinding_context)
    if path and len(path) > 1:
        move_x, move_y = path[-2]
        move_entity(ent, move_x - pos.x, move_y - pos.y)


def _process_patrol(ent: int, pos: Position, pathfinding_context: dict):
    patrol = esper.component_for_entity(ent, PatrolTag)
    target = patrol.path[patrol.index]
    if pos.x == target.x and pos.y == target.y:
        patrol.index = (patrol.index + 1) % len(patrol.path)
        target = patrol.path[patrol.index]

    path = _compute_path(ent, target, pathfinding_context)
    if path and len(path) > 1:
        move_x, move_y = path[-2]
        if get_singleton(Map).is_walkable(move_x, move_y):
            move_entity(ent, move_x - pos.x, move_y - pos.y)


def _process_flee(ent: int, pos: Position, pathfinding_context: dict):
    _remember_player_if_seen(ent)
    target = esper.component_for_entity(ent, AI).last_known_player_position
    path = _compute_path(ent, target, pathfinding_context)
    if path and len(path) > 1:
        move_x, move_y = path[0]
        # Step directly away from the next tile toward the player.
        target_x = pos.x + (1 if pos.x - move_x >= 0 else -1)
        target_y = pos.y + (1 if pos.y - move_y >= 0 else -1)
        if get_singleton(Map).is_walkable(target_x, target_y):
            move_entity(ent, target_x - pos.x, target_y - pos.y)


class AISystem(esper.Processor):
    """Drives tagged AI entities with FOV and Dijkstra pathfinding."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused or game_state.display_mode != DisplayMode.EXPLORING:
            return

        game_map = get_singleton(Map)
        if not game_map:
            return

        player_ents = esper.get_components(Position, PlayerTag)
        if not player_ents:
            return
        player_ent, (player_pos, _tag) = player_ents[0]

        # 1. Collect unique targets so each goal's Dijkstra map is built once.
        targets_to_compute: set[Point] = set()
        for ent, _ai in esper.get_component(AI):
            target = _ai_target(ent)
            if target:
                targets_to_compute.add(target)

        cost = game_map.walkable.astype(np.int32)
        pathfinding_context = {}
        for target in targets_to_compute:
            pf = tcod.path.Dijkstra(cost, diagonal=1.41)
            pf.set_goal(target.x, target.y)
            pathfinding_context[target] = pf

        # 2. Dispatch behavior by tag.
        for ent, (pos, _ai) in esper.get_components(Position, AI):
            actor = esper.component_for_entity(ent, Actor) if esper.has_component(ent, Actor) else None
            if actor and actor.cooldown > 0:
                continue

            # Attack the player if adjacent (any behavior), otherwise move.
            if esper.has_component(ent, Enemy) and abs(player_pos.x - pos.x) <= 1 and abs(player_pos.y - pos.y) <= 1:
                enemy = esper.component_for_entity(ent, Enemy)
                deal_damage(
                    player_ent,
                    enemy.attack_damage,
                    f'The {get_display_name(ent)} hits you!',
                    color=(255, 0, 0),
                )
            elif esper.has_component(ent, PatrolTag):
                _process_patrol(ent, pos, pathfinding_context)
            elif esper.has_component(ent, FleeTag):
                _process_flee(ent, pos, pathfinding_context)
            else:
                _process_chase(ent, pos, pathfinding_context)

            if actor:
                actor.cooldown = get_cooldown(ent, actor.speed)


class FOVSystem(esper.Processor):
    def process(self):
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        for _ent, (pos, fov) in esper.get_components(Position, FieldOfView):
            if fov.dirty:
                fov.visible_tiles = set()
                # compute_fov expects [height, width] or [width, height] depending on order
                # With 'F' order (column-major), it matches our [x][y] structure
                fov_map = tcod.map.compute_fov(
                    transparency=game_map.transparent,
                    pov=(pos.x, pos.y),
                    radius=fov.radius,
                    light_walls=True,
                    algorithm=libtcodpy.FOV_BASIC,
                )

                # Update visible tiles and explored map
                for x in range(game_map.width):
                    for y in range(game_map.height):
                        if fov_map[x, y]:
                            fov.visible_tiles.add(Point(x, y))
                            # Only update explored for player FOV
                            if esper.has_component(_ent, PlayerTag):
                                game_map.explored[x, y] = True

                fov.dirty = False


class RenderSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, asset_loader: AssetLoader):
        self.console = console
        self.asset_loader = asset_loader

    def process(self):
        game_state = get_singleton(GameState)
        if not game_state:
            return

        if game_state.display_mode not in [
            DisplayMode.EXPLORING,
            DisplayMode.CASTING,
            DisplayMode.COMBINING,
            DisplayMode.TARGETING,
        ]:
            return

        # 1. Get the Map and Player FOV
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        player_fov = None
        for _ent, (fov, _tag) in esper.get_components(FieldOfView, PlayerTag):
            player_fov = fov
            break

        # 2. Render the map
        for x in range(game_map.width):
            for y in range(game_map.height):
                is_visible = player_fov is not None and Point(x, y) in player_fov.visible_tiles
                is_explored = game_map.explored[x, y]

                if not is_visible and not is_explored:
                    continue

                tile = game_map.tiles[x][y]
                codepoint = self.asset_loader.get_codepoint(tile.sprite_id)
                fg = tile.fg
                bg = tile.bg

                if not is_visible:
                    # Dim the colors for explored but not visible tiles
                    fg = tuple(int(c * 0.3) for c in fg)
                    bg = tuple(int(c * 0.3) for c in bg)

                self.console.print(x=x, y=y, string=chr(codepoint), fg=fg, bg=bg)

        # 3. Render all entities with Position and Renderable components that are visible
        for _ent, (pos, rend) in esper.get_components(Position, Renderable):
            if player_fov is not None and pos.point not in player_fov.visible_tiles:
                continue

            codepoint = self.asset_loader.get_codepoint(rend.sprite_id)
            self.console.print(x=pos.x, y=pos.y, string=chr(codepoint), fg=rend.color)


def _destination_blocked(mover: int, x: int, y: int) -> bool:
    """True if an actor already occupying (x, y) blocks the mover.

    The player may step onto a non-blocking enemy (the two overlap); every
    other actor-on-actor collision blocks movement.
    """
    for other_ent, (other_pos, _actor) in esper.get_components(Position, Actor):
        if other_ent == mover or other_pos.x != x or other_pos.y != y:
            continue
        if (
            esper.has_component(mover, PlayerTag)
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

    game_map = get_singleton(Map)
    if not game_map:
        return

    if not game_map.is_walkable(new_x, new_y):
        return

    # Enemies may not step onto exit tiles.
    if not esper.has_component(entity, PlayerTag) and game_map.tiles[new_x][new_y].is_exit:
        return

    if _destination_blocked(entity, new_x, new_y):
        return

    pos.x = new_x
    pos.y = new_y

    if esper.has_component(entity, FieldOfView):
        esper.component_for_entity(entity, FieldOfView).dirty = True

    # Player move consumes a turn (base move cost of 10).
    if esper.has_component(entity, PlayerTag):
        actor = esper.component_for_entity(entity, Actor)
        actor.cooldown = get_cooldown(entity, 10)


def get_cooldown(entity: int, base_speed: int) -> int:
    """Calculate cooldown based on status effects."""
    if esper.has_component(entity, StatusEffects):
        active = esper.component_for_entity(entity, StatusEffects).active
        if StatusType.SLOW in active:
            return base_speed * 2
        if StatusType.HASTE in active:
            return max(0, base_speed // 2)
    return max(0, base_speed)


def apply_effect(target_ent: int, effect: Effect, log: MessageLog):
    """Apply a single spell effect to a target entity.

    Instant effects (damage/heal) resolve immediately; lingering ones store a
    copy of the effect on the target's StatusEffects for StatusSystem to age.
    """
    stats = esper.component_for_entity(target_ent, Stats)
    status = esper.component_for_entity(target_ent, StatusEffects)
    is_player = esper.has_component(target_ent, PlayerTag)

    if is_player:
        target_name = 'You'
    else:
        target_name = f'The {get_display_name(target_ent)}'

    if effect.type == EffectType.DAMAGE:
        stats.hp -= effect.power
        log.add_simple_message(f'{target_name} took {effect.power} damage!', color=(255, 100, 0))

    elif effect.type == EffectType.HEAL:
        stats.hp = min(stats.max_hp, stats.hp + effect.power)
        log.add_simple_message(f'{target_name} healed for {effect.power} HP!', color=(0, 255, 0))

    elif effect.type == EffectType.SLOW:
        status.active[StatusType.SLOW] = replace(effect)
        log.add_simple_message(f'{target_name} is slowed!', color=(100, 100, 255))

    elif effect.type == EffectType.HASTE:
        status.active[StatusType.HASTE] = replace(effect)
        log.add_simple_message(f'{target_name} speeds up!', color=(255, 255, 0))

    elif effect.type == EffectType.POISON:
        status.active[StatusType.POISON] = replace(effect)
        log.add_simple_message(f'{target_name} is poisoned!', color=(50, 200, 50))

    elif effect.type == EffectType.REGEN:
        status.active[StatusType.REGEN] = replace(effect)
        log.add_simple_message(f'{target_name} begins to regenerate!', color=(0, 255, 0))


def get_spell_config(spell_id: str) -> SpellConfig | None:
    """Look up a spell's config by id via the Configuration index (O(1))."""
    configs = get_singleton(Configuration)
    if configs is None:
        return None
    return configs.spells_by_id.get(spell_id)


def match_recipe(selection: tuple) -> tuple[SpellType, int] | None:
    """Match a sorted ingredient selection to a spell recipe.

    Returns (spell_type, charges) for the first matching recipe, or None.
    """
    configs = esper.get_component(Configuration)[0][1]
    for s_conf in configs.spells:
        for r_data in s_conf['recipes']:
            if r_data['ingredients'] == selection:
                return SpellType(s_conf['id']), r_data['charges']
    return None


def cast_spell(spell_id: str, target_x: int, target_y: int):
    log = esper.get_component(MessageLog)[0][1]

    # Query for player
    player_ents = esper.get_components(SpellInventory, Actor, PlayerTag)
    if not player_ents:
        return
    player, (player_spell_inv, player_actor, _tag) = player_ents[0]

    stype = SpellType(spell_id)

    # Consume charge
    player_spell_inv.spells[stype] -= 1

    # Look up config
    s_conf = get_spell_config(spell_id)
    if not s_conf:
        return

    log.add_simple_message(f'You cast {s_conf["name"]}!', color=(0, 255, 255))

    # Set player cooldown (Base move/cast cost of 10)
    player_actor.cooldown = get_cooldown(player, 10)

    radius = s_conf.get('radius', 0)

    # Find all entities in impact zone using Euclidean distance
    targets = []
    for ent, (pos, _stats) in esper.get_components(Position, Stats):
        if not esper.has_component(ent, StatusEffects):
            continue

        dx = pos.x - target_x
        dy = pos.y - target_y
        if dx**2 + dy**2 <= radius**2:
            targets.append(ent)

    if not targets:
        log.add_simple_message('The spell hits nothing.', color=(150, 150, 150))
        return

    for target in targets:
        for effect in s_conf['effects']:
            apply_effect(target, effect, log)
