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
    EffectType,
    Enemy,
    FieldOfView,
    MessageLog,
    Modal,
    PlayerTag,
    Point,
    Position,
    Renderable,
    SpellInventory,
    SpellType,
    Stats,
    StatusEffects,
    StatusType,
)
from src.map_objects import Map
from src.states import DisplayMode, GameState

if TYPE_CHECKING:
    from src.data_loaders import AssetLoader


class DeathSystem(esper.Processor):
    """Handles death for all entities with Stats."""

    def process(self):
        log_entities = esper.get_component(MessageLog)
        log = log_entities[0][1] if log_entities else None

        for ent, stats in esper.get_component(Stats):
            if stats.hp <= 0:
                if esper.has_component(ent, PlayerTag):
                    if not esper.get_component(Modal):
                        esper.create_entity(
                            Modal(
                                message='You have died! Press Enter to quit.',
                                on_close=lambda: exit(),
                            )
                        )
                else:
                    if log:
                        name = 'enemy'
                        if esper.has_component(ent, Renderable):
                            name = esper.component_for_entity(ent, Renderable).sprite_id
                        log.add_simple_message(f'The {name} dies!', color=(255, 255, 0))
                    esper.delete_entity(ent)


class ActionSystem(esper.Processor):
    """Manages cooldowns for all actors."""

    def __init__(self):
        self.tick_parity = 0

    def process(self):
        game_state = esper.get_component(GameState)[0][1]
        if game_state.time_paused:
            return

        self.tick_parity = (self.tick_parity + 1) % 2

        for _ent, actor in esper.get_component(Actor):
            if actor.cooldown > 0:
                actor.cooldown -= 1


class StatusSystem(esper.Processor):
    """Manages duration of active status effects."""

    def process(self):
        game_state = esper.get_component(GameState)[0][1]
        if game_state.time_paused:
            return

        for _ent, status in esper.get_component(StatusEffects):
            for effect_type in list(status.active.keys()):
                if status.active[effect_type] > 0:
                    status.active[effect_type] -= 1
                else:
                    del status.active[effect_type]


class AISystem(esper.Processor):
    """Handles basic AI behaviors with FOV and Dijkstra pathfinding."""

    def process(self):
        game_state = esper.get_component(GameState)[0][1]
        if game_state.time_paused or game_state.display_mode != DisplayMode.EXPLORING:
            return

        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        player_ents = esper.get_components(Position, PlayerTag)
        if not player_ents:
            return
        player_ent, (player_pos, _tag) = player_ents[0]
        player_stats = esper.component_for_entity(player_ent, Stats)

        # 1. Collect unique targets to precompute pathfinders
        targets_to_compute = set()
        for ent, ai in esper.get_component(AI):
            target = ai.behavior.get_target(ent)
            if target:
                targets_to_compute.add(target)

        cost = game_map.walkable.astype(np.int32)
        pathfinding_context = {}
        for target in targets_to_compute:
            pf = tcod.path.Dijkstra(cost, diagonal=1.41)
            pf.set_goal(target.x, target.y)
            pathfinding_context[target] = pf

        # 2. Dispatch behavior
        for ent, (pos, ai) in esper.get_components(Position, AI):
            # Cooldown check applies to all actions
            if esper.has_component(ent, Actor):
                actor = esper.component_for_entity(ent, Actor)
                if actor.cooldown > 0:
                    continue

            # Attack if adjacent
            if esper.has_component(ent, Enemy):
                dx = player_pos.x - pos.x
                dy = player_pos.y - pos.y
                if abs(dx) <= 1 and abs(dy) <= 1:
                    enemy = esper.component_for_entity(ent, Enemy)
                    player_stats.hp -= enemy.attack_damage
                    logs = esper.get_component(MessageLog)
                    if logs:
                        name = 'enemy'
                        if esper.has_component(ent, Renderable):
                            name = esper.component_for_entity(ent, Renderable).sprite_id
                        logs[0][1].add_simple_message(f'The {name} hits you!', color=(255, 0, 0))

                    if esper.has_component(ent, Actor):
                        actor = esper.component_for_entity(ent, Actor)
                        actor.cooldown = get_cooldown(ent, actor.speed)
                    continue

            # Move if not attacking
            ai.behavior.update(ent, pathfinding_context)


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
        game_state = esper.get_component(GameState)[0][1]

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


def move_entity(entity: int, dx: int, dy: int):
    pos = esper.component_for_entity(entity, Position)
    new_x = pos.x + dx
    new_y = pos.y + dy

    maps = esper.get_component(Map)
    if maps:
        game_map = maps[0][1]

        # Check for wall collision
        if not game_map.is_walkable(new_x, new_y):
            return

        # Check for exit tile collision (for enemies)
        if not esper.has_component(entity, PlayerTag):
            if game_map.tiles[new_x][new_y].is_exit:
                return

        # Check for entity collision (with Actors or Player)
        # Check for Actors
        for other_ent, (other_pos, _actor) in esper.get_components(Position, Actor):
            if other_ent != entity and other_pos.x == new_x and other_pos.y == new_y:
                # If player bumps into enemy
                if esper.has_component(entity, PlayerTag) and esper.has_component(other_ent, Enemy):
                    player_entities = esper.get_components(Stats, PlayerTag)
                    if player_entities:
                        _player_ent, (player_stats, _tag) = player_entities[0]
                        enemy = esper.component_for_entity(other_ent, Enemy)
                        player_stats.hp -= enemy.bump_damage
                        logs = esper.get_component(MessageLog)
                        if logs:
                            name = 'enemy'
                            if esper.has_component(other_ent, Renderable):
                                name = esper.component_for_entity(other_ent, Renderable).sprite_id
                            logs[0][1].add_simple_message(
                                f'You bump into a {name} and take damage!',
                                color=(255, 0, 0),
                            )

                    if enemy.blocks_movement:
                        return
                else:
                    # Other entity collisions (enemy into enemy, etc) still block
                    return

        # Check for Player specifically (if an enemy is moving)
        if not esper.has_component(entity, PlayerTag):
            player_entities = esper.get_components(Position, PlayerTag)
            if player_entities:
                _player_ent, (player_pos, _tag) = player_entities[0]
                if player_pos.x == new_x and player_pos.y == new_y:
                    return
        pos.x = new_x
        pos.y = new_y

        # If the entity has a FieldOfView, mark it as dirty
        if esper.has_component(entity, FieldOfView):
            fov = esper.component_for_entity(entity, FieldOfView)
            fov.dirty = True

        # Player cooldown on move (Base move cost of 10)
        if esper.has_component(entity, PlayerTag):
            actor = esper.component_for_entity(entity, Actor)
            actor.cooldown = get_cooldown(entity, 10)


def get_cooldown(entity: int, base_speed: int) -> int:
    """Calculate cooldown based on status effects."""
    if esper.has_component(entity, StatusEffects):
        status = esper.component_for_entity(entity, StatusEffects)
        if StatusType.SLOW in status.active:
            return base_speed * 2
    return max(0, base_speed)


def apply_effect(target_ent: int, effect_data: dict, log: MessageLog):
    """Apply a single spell effect to a target entity."""
    stats = esper.component_for_entity(target_ent, Stats)
    status = esper.component_for_entity(target_ent, StatusEffects)
    is_player = esper.has_component(target_ent, PlayerTag)

    if is_player:
        target_name = 'You'
    else:
        name = 'enemy'
        if esper.has_component(target_ent, Renderable):
            name = esper.component_for_entity(target_ent, Renderable).sprite_id
        target_name = f'The {name}'

    etype = effect_data['type']

    if etype == EffectType.DAMAGE:
        power = effect_data['power']
        stats.hp -= power
        log.add_simple_message(f'{target_name} took {power} damage!', color=(255, 100, 0))

    elif etype == EffectType.HEAL:
        power = effect_data['power']
        stats.hp = min(stats.max_hp, stats.hp + power)
        log.add_simple_message(f'{target_name} healed for {power} HP!', color=(0, 255, 0))

    elif etype == EffectType.SLOW:
        duration = effect_data['duration']
        status.active[StatusType.SLOW] = duration
        log.add_simple_message(f'{target_name} is slowed!', color=(100, 100, 255))


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

    # Query for config
    configs = esper.get_component(Configuration)[0][1]
    spells_config = configs.spells

    # Find config
    s_conf = next((s for s in spells_config if s['id'] == spell_id), None)
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
