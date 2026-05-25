from abc import ABC, abstractmethod

import esper
import numpy as np
import tcod
from tcod.path import Dijkstra

from src.components import (
    AI,
    Actor,
    FieldOfView,
    PlayerTag,
    Point,
    Position,
)
from src.map_objects import Map
from src.systems import get_cooldown, move_entity


class AIBehavior(ABC):
    @abstractmethod
    def update(self, ent: int, pathfinding_context: dict[Point, Dijkstra]):
        pass

    @abstractmethod
    def get_target(self, ent: int) -> Point | None:
        pass

    def get_path(self, ent: int, pathfinding_context: dict[Point, Dijkstra]) -> list[tuple[int, int]] | None:
        pos = esper.component_for_entity(ent, Position)
        target = self.get_target(ent)
        if not target:
            return None

        pf = pathfinding_context.get(target)
        if not pf:
            game_map = esper.get_component(Map)[0][1]
            cost = game_map.walkable.astype(np.int32)
            pf = tcod.path.Dijkstra(cost, diagonal=1.41)
            pf.set_goal(target.x, target.y)

        path = pf.get_path(pos.x, pos.y)
        if isinstance(path, np.ndarray):
            path = path.tolist()

        # Dijkstra path from tcod excludes the goal. Add it manually if reachable.
        if path and (path[0][0] != target.x or path[0][1] != target.y):
            path.insert(0, [target.x, target.y])

        return path


class MoveRelativeToPlayerBehavior(AIBehavior):
    def get_target(self, ent: int) -> Point | None:
        ai = esper.component_for_entity(ent, AI)
        return ai.last_known_player_position


class ChaseBehavior(MoveRelativeToPlayerBehavior):
    def update(self, ent: int, pathfinding_context: dict[Point, Dijkstra]):
        pos = esper.component_for_entity(ent, Position)
        actor = esper.component_for_entity(ent, Actor)
        ai = esper.component_for_entity(ent, AI)
        fov = esper.component_for_entity(ent, FieldOfView)
        player_pos = esper.get_components(Position, PlayerTag)[0][1][0]

        if player_pos.point in fov.visible_tiles:
            ai.last_known_player_position = player_pos.point

        path = self.get_path(ent, pathfinding_context)
        if path and len(path) > 1:
            move_x, move_y = path[-2]

            occupied = False
            for other_ent, (other_pos, _actor) in esper.get_components(Position, Actor):
                if other_ent != ent and other_pos.x == move_x and other_pos.y == move_y:
                    occupied = True
                    break

            if not occupied:
                move_entity(ent, move_x - pos.x, move_y - pos.y)

        actor.cooldown = get_cooldown(ent, actor.speed)


class PatrolBehavior(AIBehavior):
    def __init__(self, path: list[Point]):
        self.path = path
        self.index = 0

    def get_target(self, ent: int) -> Point:
        return self.path[self.index]

    def update(self, ent: int, pathfinding_context: dict[Point, Dijkstra]):
        pos = esper.component_for_entity(ent, Position)
        actor = esper.component_for_entity(ent, Actor)

        target = self.get_target(ent)

        if pos.x == target.x and pos.y == target.y:
            self.index = (self.index + 1) % len(self.path)
            target = self.get_target(ent)

        path = self.get_path(ent, pathfinding_context)
        if path and len(path) > 1:
            move_x, move_y = path[-2]
            game_map = esper.get_component(Map)[0][1]
            if game_map.is_walkable(move_x, move_y):
                move_entity(ent, move_x - pos.x, move_y - pos.y)

        actor.cooldown = get_cooldown(ent, actor.speed)


class FleeBehavior(MoveRelativeToPlayerBehavior):
    def update(self, ent: int, pathfinding_context: dict[Point, Dijkstra]):
        pos = esper.component_for_entity(ent, Position)
        actor = esper.component_for_entity(ent, Actor)
        ai = esper.component_for_entity(ent, AI)
        fov = esper.component_for_entity(ent, FieldOfView)
        game_map = esper.get_component(Map)[0][1]
        player_pos = esper.get_components(Position, PlayerTag)[0][1][0]

        if player_pos.point in fov.visible_tiles:
            ai.last_known_player_position = player_pos.point

        path = self.get_path(ent, pathfinding_context)
        if path and len(path) > 1:
            move_x, move_y = path[0]
            dx = pos.x - move_x
            dy = pos.y - move_y

            target_x = pos.x + (1 if dx >= 0 else -1)
            target_y = pos.y + (1 if dy >= 0 else -1)

            if game_map.is_walkable(target_x, target_y):
                move_entity(ent, target_x - pos.x, target_y - pos.y)

        actor.cooldown = get_cooldown(ent, actor.speed)
