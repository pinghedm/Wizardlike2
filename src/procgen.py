import random

import esper
from components import Item, ItemType, Point, Position, Renderable
from map_objects import Map, Tile
from states import GameState


class RectangularRoom:
    def __init__(self, x: int, y: int, width: int, height: int):
        self.x1 = x
        self.y1 = y
        self.x2 = x + width
        self.y2 = y + height
        self.items: dict[Point, list[ItemType]] = {}

    @property
    def center(self) -> Point:
        center_x = int((self.x1 + self.x2) / 2)
        center_y = int((self.y1 + self.y2) / 2)
        return Point(center_x, center_y)

    def intersects(self, other: 'RectangularRoom') -> bool:
        return (
            self.x1 <= other.x2
            and self.x2 >= other.x1
            and self.y1 <= other.y2
            and self.y2 >= other.y1
        )

    def spawn_items(self, ingredients_config: dict):
        """Create ECS entities for all items in this room."""
        for p, item_list in self.items.items():
            for itype in item_list:
                item_config = ingredients_config.get(itype.value, {})
                # The ID itself is now the sprite_id, as it's registered in AssetLoader
                sprite_id = itype.value
                color = tuple(item_config.get('color', (255, 255, 255)))
                
                esper.create_entity(
                    Position(p.x, p.y),
                    Renderable(sprite_id=sprite_id, color=color),
                    Item(itype),
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
    map_width: int,
    map_height: int,
    max_rooms: int,
    room_min_size: int,
    room_max_size: int,
    max_items_per_room: int,
    ingredients_config: dict,
    tiles_config: list,
) -> tuple[Map, Point]:
    # Retrieve current floor from GameState
    try:
        game_state = esper.get_component(GameState)[0][1]
        floor_number = game_state.floor
    except (IndexError, KeyError):
        floor_number = 1

    # 1. Select tiles for this floor based on depth
    available_tiles = [
        t for t in tiles_config 
        if t['depth'][0] <= floor_number <= t['depth'][1]
    ]
    
    wall_cfg = random.choice([t for t in available_tiles if t['type'] == 'wall'])
    floor_cfg = random.choice([t for t in available_tiles if t['type'] == 'floor'])
    exit_cfg = random.choice([t for t in available_tiles if t['type'] == 'exit'])

    def make_tile(cfg, walkable, transparent, is_exit=False):
        return Tile(
            walkable=walkable,
            transparent=transparent,
            sprite_id=cfg['id'],
            fg=tuple(cfg['fg']),
            bg=tuple(cfg['bg']),
            is_exit=is_exit
        )

    wall_tile = make_tile(wall_cfg, False, False)
    floor_tile = make_tile(floor_cfg, True, True)
    exit_tile = make_tile(exit_cfg, True, True, is_exit=True)

    dungeon = Map(map_width, map_height, wall_tile)
    rooms: list[RectangularRoom] = []
    player_start = Point(map_width // 2, map_height // 2)

    item_types = list(ItemType)

    for _ in range(max_rooms):
        w = random.randint(room_min_size, room_max_size)
        h = random.randint(room_min_size, room_max_size)
        x = random.randint(0, dungeon.width - w - 1)
        y = random.randint(0, dungeon.height - h - 1)

        new_room = RectangularRoom(x, y, w, h)
        if any(new_room.intersects(other) for other in rooms):
            continue

        # Dig room
        for rx in range(new_room.x1 + 1, new_room.x2):
            for ry in range(new_room.y1 + 1, new_room.y2):
                dungeon.tiles[rx][ry] = floor_tile

        if not rooms:
            player_start = new_room.center
        else:
            for p in tunnel_between(rooms[-1].center, new_room.center):
                dungeon.tiles[p.x][p.y] = floor_tile
            
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

    # Spawn all items
    for room in rooms:
        room.spawn_items(ingredients_config)

    # Place exit
    if rooms:
        exit_p = rooms[-1].center
        dungeon.tiles[exit_p.x][exit_p.y] = exit_tile

    return dungeon, player_start
