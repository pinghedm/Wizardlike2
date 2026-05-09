import random
from components import ItemType, Point
from map_objects import Map, Tile

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

def tunnel_between(start: Point, end: Point):
    x1, y1 = start
    x2, y2 = end
    if random.random() < 0.5:
        # Horizontal then vertical
        for x in range(min(x1, x2), max(x1, x2) + 1):
            yield Point(x, y1)
        for y in range(min(y1, y2), max(y1, y2) + 1):
            yield Point(x2, y)
    else:
        # Vertical then horizontal
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
) -> tuple[Map, Point, list[RectangularRoom]]:
    dungeon = Map(map_width, map_height)
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

        # Dig out the room
        for rx in range(new_room.x1 + 1, new_room.x2):
            for ry in range(new_room.y1 + 1, new_room.y2):
                dungeon.tiles[rx][ry] = Tile.floor()

        if not rooms:
            player_start = new_room.center
        else:
            for p in tunnel_between(rooms[-1].center, new_room.center):
                dungeon.tiles[p.x][p.y] = Tile.floor()
            
            # Spawn items
            num_items = random.randint(0, max_items_per_room)
            for _ in range(num_items):
                ix = random.randint(new_room.x1 + 1, new_room.x2 - 1)
                iy = random.randint(new_room.y1 + 1, new_room.y2 - 1)
                p = Point(ix, iy)
                
                if p not in new_room.items:
                    new_room.items[p] = []
                
                new_room.items[p].append(random.choice(item_types))

        rooms.append(new_room)

    # Place exit
    if rooms:
        exit_p = rooms[-1].center
        dungeon.tiles[exit_p.x][exit_p.y] = Tile.exit()

    return dungeon, player_start, rooms
