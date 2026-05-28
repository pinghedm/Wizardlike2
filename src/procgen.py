import random

import esper

from src.components import (
    AI,
    Actor,
    ChaseTag,
    Configuration,
    Enemy,
    FieldOfView,
    FleeTag,
    Item,
    ItemType,
    MessageLog,
    PatrolTag,
    PlayerTag,
    Point,
    Position,
    Renderable,
    Stats,
    StatusEffects,
)
from src.constants import MAP_HEIGHT, MAP_WIDTH
from src.map_objects import Map, Tile
from src.states import GameState
from src.systems import get_singleton


def transition_to_next_floor():
    # 1. Increment Floor
    game_state = esper.get_component(GameState)[0][1]
    game_state.floor += 1

    # 2. Calculate floor-dependent parameters
    max_rooms = 30 + (game_state.floor // 2)
    max_items = 2 + (game_state.floor // 5)

    # 3. Clear existing non-persistent entities (Items/Enemies).
    # immediate=True so the floor is rebuilt to a clean state synchronously; esper's
    # default deferred delete would leave stale entities visible to get_component until
    # the next process() tick.
    for ent, _ in esper.get_component(Item):
        esper.delete_entity(ent, immediate=True)
    for ent, _ in esper.get_component(Enemy):
        esper.delete_entity(ent, immediate=True)

    # 4. Generate new map
    new_map, player_start = generate_dungeon(
        max_rooms=max_rooms,
        room_min_size=6,
        room_max_size=10,
        max_items_per_room=max_items,
    )

    # 5. Replace the Map entity. immediate=True so the stale map is gone before
    # anything queries the singleton Map again (see note above).
    for ent, _old_map in esper.get_component(Map):
        esper.delete_entity(ent, immediate=True)
    esper.create_entity(new_map)

    # 6. Update Player Position
    for ent, _ in esper.get_component(PlayerTag):
        pos = esper.component_for_entity(ent, Position)
        pos.x = player_start.x
        pos.y = player_start.y
        if esper.has_component(ent, FieldOfView):
            esper.component_for_entity(ent, FieldOfView).dirty = True


class RectangularRoom:
    def __init__(self, x: int, y: int, width: int, height: int, dungeon: Map):
        self.x1 = x
        self.y1 = y
        self.x2 = x + width
        self.y2 = y + height
        self.items: dict[Point, list[ItemType]] = {}
        self.dungeon = dungeon

    @property
    def center(self) -> Point:
        center_x = int((self.x1 + self.x2) / 2)
        center_y = int((self.y1 + self.y2) / 2)
        return Point(center_x, center_y)

    def intersects(self, other: RectangularRoom) -> bool:
        return self.x1 <= other.x2 and self.x2 >= other.x1 and self.y1 <= other.y2 and self.y2 >= other.y1

    def spawn_entities(self, rooms: list[RectangularRoom], spawn_enemies: bool = True):
        """Create ECS entities for all items and enemies in this room."""
        configs = esper.get_component(Configuration)[0][1]

        # Items
        for p, item_list in self.items.items():
            for itype in item_list:
                item_config = configs.ingredients.get(itype.value, {})
                sprite_id = itype.value
                color = tuple(item_config.get('color', (255, 255, 255)))

                esper.create_entity(
                    Position(p.x, p.y),
                    Renderable(sprite_id=sprite_id, color=color),
                    Item(itype),
                )

        # Enemies
        if spawn_enemies:
            game_state = esper.get_component(GameState)[0][1]
            floor = game_state.floor

            # Filter enemies valid for current floor
            available_enemies = [e for e in configs.enemies.values() if e['floors'][0] <= floor <= e['floors'][1]]
            if not available_enemies:
                return

            enemy_cfg = random.choice(available_enemies)

            # Re-roll until we find a non-exit tile
            for _ in range(20):
                x = random.randint(self.x1 + 1, self.x2 - 1)
                y = random.randint(self.y1 + 1, self.y2 - 1)
                if not self.dungeon.tiles[x][y].is_exit:
                    break
            else:
                return

            # Map the behavior string to a behavior tag component.
            behavior_name = enemy_cfg['behavior'].upper()
            if behavior_name == 'PATROL':
                waypoints = [self.center, random.choice([r for r in rooms if r is not self] or [self]).center]
                behavior_tag = PatrolTag(path=waypoints)
            elif behavior_name == 'FLEE':
                behavior_tag = FleeTag()
            else:
                behavior_tag = ChaseTag()

            esper.create_entity(
                Position(x, y),
                Renderable(sprite_id=enemy_cfg['id'], color=tuple(enemy_cfg['color'])),
                Actor(speed=enemy_cfg['speed']),
                AI(),
                behavior_tag,
                Enemy(
                    attack_damage=enemy_cfg['damage'],
                    bump_damage=enemy_cfg['damage'] // 2,
                    ability=enemy_cfg.get('ability'),
                ),
                Stats(hp=enemy_cfg['hp'], max_hp=enemy_cfg['hp']),
                StatusEffects(),
                FieldOfView(radius=8),
            )


def tunnel_between(start: Point, end: Point):
    x1, y1 = start
    x2, y2 = end
    if random.random() < 0.5:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            yield Point(x, y1)
        for y in range(min(y1, y2), max(y1, y2) + 1):
            yield Point(x2, y)
    else:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            yield Point(x1, y)
        for x in range(min(x1, x2), max(x1, x2) + 1):
            yield Point(x, y2)


def generate_dungeon(
    max_rooms: int,
    room_min_size: int,
    room_max_size: int,
    max_items_per_room: int,
) -> tuple[Map, Point]:
    # Retrieve current floor from GameState
    try:
        game_state = esper.get_component(GameState)[0][1]
        floor_number = game_state.floor
    except IndexError, KeyError:
        floor_number = 1

    # 1. Select tiles for this floor based on depth. Tiles live on the
    # Configuration singleton (created at startup), so query it directly rather
    # than threading the config through every call site.
    tiles_config = get_singleton(Configuration).tiles
    available_tiles = [t for t in tiles_config if t['depth'][0] <= floor_number <= t['depth'][1]]

    wall_cfg = random.choice([t for t in available_tiles if t['type'] == 'wall'])
    floor_cfg = random.choice([t for t in available_tiles if t['type'] == 'floor'])
    exit_cfg = random.choice([t for t in available_tiles if t['type'] == 'exit'])

    def make_tile(cfg, walkable, transparent, is_exit=False):
        return Tile(
            walkable=walkable,
            transparent=transparent,
            sprite_id=cfg['id'],
            fg=tuple(cfg.get('fg', (255, 255, 255))),
            bg=tuple(cfg.get('bg', (0, 0, 0))),
            is_exit=is_exit,
        )

    wall_tile = make_tile(wall_cfg, False, False)
    floor_tile = make_tile(floor_cfg, True, True)
    exit_tile = make_tile(exit_cfg, True, True, is_exit=True)

    dungeon = Map(MAP_WIDTH, MAP_HEIGHT, wall_tile)
    rooms: list[RectangularRoom] = []
    player_start = Point(MAP_WIDTH // 2, MAP_HEIGHT // 2)

    item_types = list(ItemType)

    for _ in range(max_rooms):
        w = random.randint(room_min_size, room_max_size)
        h = random.randint(room_min_size, room_max_size)
        x = random.randint(0, dungeon.width - w - 1)
        y = random.randint(0, dungeon.height - h - 1)

        new_room = RectangularRoom(x, y, w, h, dungeon)
        if any(new_room.intersects(other) for other in rooms):
            continue

        # Dig room
        for rx in range(new_room.x1 + 1, new_room.x2):
            for ry in range(new_room.y1 + 1, new_room.y2):
                dungeon.set_tile(rx, ry, floor_tile)

        if not rooms:
            player_start = new_room.center
        else:
            for p in tunnel_between(rooms[-1].center, new_room.center):
                dungeon.set_tile(p.x, p.y, floor_tile)

            # Populate room item data
            num_items = random.randint(0, max_items_per_room)
            for _ in range(num_items):
                ix = random.randint(new_room.x1 + 1, new_room.x2 - 1)
                iy = random.randint(new_room.y1 + 1, new_room.y2 - 1)
                p = Point(ix, iy)
                if p not in new_room.items:
                    new_room.items[p] = []
                new_room.items[p].append(random.choice(item_types))

        rooms.append(new_room)

    # Spawn all items/enemies
    for i, room in enumerate(rooms):
        # Don't spawn enemies in the player's starting room (the first room)
        room.spawn_entities(rooms, spawn_enemies=(i > 0))

    # Place exit
    if rooms:
        exit_p = rooms[-1].center
        dungeon.set_tile(exit_p.x, exit_p.y, exit_tile)

    # Announce floor entry
    logs = esper.get_component(MessageLog)
    if logs:
        log = logs[0][1]
        log.add_simple_message(f'Entered level {floor_number}', color=(255, 255, 255))
    return dungeon, player_start
