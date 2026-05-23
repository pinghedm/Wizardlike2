from typing import TYPE_CHECKING

import esper
import numpy as np
import tcod
import tcod.map
import tcod.path
from tcod import libtcodpy

from components import (
    AI,
    Actor,
    BehaviorType,
    Configuration,
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
)
from map_objects import Map
from states import DisplayMode, GameState

if TYPE_CHECKING:
    from data_loaders import AssetLoader


class DeathSystem(esper.Processor):
    """Checks for player death."""

    def process(self):
        for _ent, (stats, _tag) in esper.get_components(Stats, PlayerTag):
            if stats.hp <= 0:
                if not esper.get_component(Modal):
                    esper.create_entity(
                        Modal(
                            message='You have died! Press Enter to quit.',
                            on_close=lambda: exit(),
                        )
                    )


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

        # Get player position
        player_entities = esper.get_components(Position, PlayerTag)
        if not player_entities:
            return
        _player_ent, (player_pos, _tag) = player_entities[0]

        # 1. Update FOV/Detection and targets
        targets_to_compute = set()
        active_enemies = []

        for ent, (pos, actor, ai, enemy, fov) in esper.get_components(Position, Actor, AI, Enemy, FieldOfView):
            if actor.cooldown > 0:
                continue

            # Can I see the player?
            if player_pos.point in fov.visible_tiles:
                ai.last_known_player_position = player_pos.point

            if ai.behavior == BehaviorType.CHASE and ai.last_known_player_position:
                targets_to_compute.add(ai.last_known_player_position)
                active_enemies.append((ent, pos, actor, ai, enemy))

        if not active_enemies:
            return

        # 2. Compute Dijkstra pathfinders for all unique targets
        # cost grid: 1 for walkable, 0 for blocked
        cost = game_map.walkable.astype(np.int32)
        dijkstra_pfs = {}

        for target in targets_to_compute:
            # Dijkstra pathfinder from target
            pf = tcod.path.Dijkstra(cost, diagonal=1.41)
            pf.set_goal(target.x, target.y)
            dijkstra_pfs[target] = pf

        # 3. Move enemies
        for ent, pos, actor, ai, enemy in active_enemies:
            target = ai.last_known_player_position
            pf = dijkstra_pfs[target]

            # Distance check
            dx = target.x - pos.x
            dy = target.y - pos.y
            dist_sq = dx**2 + dy**2

            if dist_sq <= 2:  # Adjacent (including diagonal)
                if target == player_pos.point:
                    # Attack player
                    player_entities = esper.get_components(Stats, PlayerTag)
                    if player_entities:
                        _player_ent, (player_stats, _tag) = player_entities[0]
                        player_stats.hp -= enemy.attack_damage
                        logs = esper.get_component(MessageLog)
                        if logs:
                            logs[0][1].add_simple_message('The enemy hits you!', color=(255, 0, 0))
                    actor.cooldown = actor.speed
                else:
                    # Reached last known but no player
                    ai.last_known_player_position = None
                continue

            # Move towards target using Dijkstra pathfinder
            path = pf.get_path(pos.x, pos.y)

            if len(path) > 1:
                # Next step is the second to last element in the reversed path
                move_x, move_y = path[-2]
                dx, dy = move_x - pos.x, move_y - pos.y

                # Manual collision check to prevent enemies overlapping
                occupied = False
                for other_ent, (other_pos, _actor) in esper.get_components(Position, Actor):
                    if other_ent != ent and other_pos.x == move_x and other_pos.y == move_y:
                        occupied = True
                        break
                if not occupied and player_pos.x == move_x and player_pos.y == move_y:
                    occupied = True

                if not occupied:
                    move_entity(ent, dx, dy)

                actor.cooldown = actor.speed
            else:
                # Path blocked or reached
                if target != player_pos.point:
                    ai.last_known_player_position = None
                actor.cooldown = 10  # Try again soon


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

        if game_state.display_mode not in [DisplayMode.EXPLORING, DisplayMode.CASTING, DisplayMode.TARGETING]:
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
                            logs[0][1].add_simple_message('You bump into an enemy and take damage!', color=(255, 0, 0))

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


def cast_spell(spell_id: str, target_x: int, target_y: int):
    log = esper.get_component(MessageLog)[0][1]

    # Query for player
    player_ents = esper.get_components(SpellInventory, PlayerTag)
    if not player_ents:
        return
    _player, (player_spell_inv, _tag) = player_ents[0]

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

    radius = s_conf.get('radius', 0)

    # Find all entities in impact zone
    targets = []
    for ent, (pos, _stats) in esper.get_components(Position, Stats):
        if abs(pos.x - target_x) <= radius and abs(pos.y - target_y) <= radius:
            targets.append(ent)

    if not targets:
        log.add_simple_message('The spell hits nothing.', color=(150, 150, 150))
        return

    for target in targets:
        stats = esper.component_for_entity(target, Stats)
        is_player = esper.has_component(target, PlayerTag)
        target_name = 'You' if is_player else 'The enemy'

        for effect in s_conf['effects']:
            etype = effect['type']

            if etype == 'damage':
                power = effect['power']
                stats.hp -= power
                log.add_simple_message(f'{target_name} took {power} damage!', color=(255, 100, 0))

            elif etype == 'heal':
                power = effect['power']
                stats.hp = min(stats.max_hp, stats.hp + power)
                log.add_simple_message(f'{target_name} healed for {power} HP!', color=(0, 255, 0))
