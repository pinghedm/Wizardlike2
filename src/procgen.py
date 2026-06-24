import random

import esper

from src.audio import SoundId, play_sfx
from src.components import (
    AI,
    NPC,
    Actor,
    ChaseTag,
    Configuration,
    Enemy,
    EnemyConfig,
    FieldOfView,
    FleeTag,
    Guardian,
    GuardTag,
    Item,
    ItemType,
    Loot,
    MessageLog,
    NPCConfig,
    PatrolTag,
    Point,
    Position,
    Renderable,
    Shopkeeper,
    Stats,
    StatusEffects,
    TileConfig,
)
from src.constants import (
    MAP_HEIGHT,
    MAP_WIDTH,
    MAX_ITEMS_PER_ROOM,
    MAX_ROOMS,
    ROOM_MAX_SIZE,
    ROOM_MIN_SIZE,
    SHOP_FLOOR_INTERVAL,
    UI_BLACK,
    UI_WHITE,
    to_rgb,
)
from src.ecs_helpers import get_player, get_singleton, mark_fov_dirty, spawn_item_entity
from src.map_objects import Map, Tile
from src.shop import build_shop_offers
from src.states import GameState
from src.systems import refill_basic_spells


def is_shop_floor(floor: int) -> bool:
    """Whether `floor` is a safe shop floor rather than a combat level."""
    return floor % SHOP_FLOOR_INTERVAL == 0


def _delete_all(*component_types: type[object]):
    """Immediately delete every entity carrying any of the given component types.

    immediate=True so the world is left clean synchronously; esper's default deferred
    delete would leave stale entities visible to get_component until the next process()
    tick — and a floor rebuild queries the world before then.
    """
    for component_type in component_types:
        for ent, _ in esper.get_component(component_type):
            esper.delete_entity(ent, immediate=True)


def transition_to_next_floor():
    # 1. Increment Floor
    game_state = get_singleton(GameState)
    game_state.floor += 1
    play_sfx(SoundId.DESCEND)

    # 2. Calculate floor-dependent parameters. Deeper floors are bigger and richer: one
    # more room attempt every 2 floors, and the per-room item cap rises by 1 every 5 floors.
    max_rooms = MAX_ROOMS + (game_state.floor // 2)
    max_items = MAX_ITEMS_PER_ROOM + (game_state.floor // 5)

    # 3. Clear existing non-persistent entities (Items/Enemies/Shopkeeper/NPCs).
    _delete_all(Item, Enemy, Shopkeeper, NPC)

    # 4. Generate the new floor (a shop floor on every third level).
    if is_shop_floor(game_state.floor):
        new_map, player_start = generate_shop_floor()
    else:
        new_map, player_start = generate_dungeon(
            max_rooms=max_rooms,
            room_min_size=ROOM_MIN_SIZE,
            room_max_size=ROOM_MAX_SIZE,
            max_items_per_room=max_items,
        )

    # 5. Replace the Map entity.
    _delete_all(Map)
    esper.create_entity(new_map)

    # 6. Update Player Position
    player = get_player()
    if player is not None:
        pos = esper.component_for_entity(player, Position)
        pos.x = player_start.x
        pos.y = player_start.y
        mark_fov_dirty(player)

    # 7. Replenish the always-known basic attacks for the new floor.
    refill_basic_spells()


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
                spawn_item_entity(itype, p.x, p.y)

        # Enemies
        if spawn_enemies:
            game_state = get_singleton(GameState)
            floor = game_state.floor

            # Filter enemies valid for current floor. Guardians are reserved for the
            # floor exit (spawned by generate_dungeon), so exclude them here.
            available_enemies = [
                e
                for e in configs.enemies.values()
                if not e.get('guardian') and e['floors'][0] <= floor <= e['floors'][1]
            ]
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

            spawn_enemy(enemy_cfg, x, y, rooms, home_room=self)


def spawn_enemy(
    enemy_cfg: EnemyConfig,
    x: int,
    y: int,
    rooms: list[RectangularRoom],
    home_room: RectangularRoom | None = None,
) -> int:
    """Create an enemy entity at (x, y), mapping the behavior string to a tag."""
    behavior_name = enemy_cfg['behavior'].upper()
    if behavior_name == 'PATROL':
        anchor = home_room or rooms[0]
        others = [r for r in rooms if r is not anchor] or [anchor]
        behavior_tag = PatrolTag(path=[anchor.center, random.choice(others).center])
    elif behavior_name == 'FLEE':
        behavior_tag = FleeTag()
    elif behavior_name == 'GUARD':
        behavior_tag = GuardTag()
    else:
        behavior_tag = ChaseTag()

    components: list[object] = [
        Position(x, y),
        Renderable(sprite_id=enemy_cfg['id'], color=to_rgb(enemy_cfg['color'])),
        Actor(speed=enemy_cfg['speed']),
        AI(),
        behavior_tag,
        Enemy(
            attack_damage=enemy_cfg['damage'],
            bump_damage=enemy_cfg['damage'] // 2,
            blocks_movement=enemy_cfg.get('blocks_movement', False),
            ability=enemy_cfg.get('ability'),
            xp_reward=enemy_cfg['xp'],
        ),
        Stats(hp=enemy_cfg['hp'], max_hp=enemy_cfg['hp']),
        StatusEffects(),
        FieldOfView(radius=8),
    ]
    drops = enemy_cfg.get('drops')
    if drops:
        components.append(Loot(drops=drops))
    if enemy_cfg.get('guardian'):
        components.append(Guardian())
    return esper.create_entity(*components)


def spawn_npc(npc_cfg: NPCConfig, x: int, y: int) -> int:
    """Create a non-hostile story NPC at (x, y). Press Confirm while adjacent to read it."""
    return esper.create_entity(
        Position(x, y),
        Renderable(sprite_id=npc_cfg['id'], color=to_rgb(npc_cfg.get('color') or UI_WHITE)),
        NPC(name=npc_cfg['name'], dialogue=npc_cfg['dialogue']),
    )


def _spawn_floor_npcs(rooms: list[RectangularRoom], floor: int):
    """Place each curated NPC whose `floor` matches in a random non-start room."""
    configs = esper.get_component(Configuration)[0][1]
    candidate_rooms = rooms[1:]
    if not candidate_rooms:
        return
    for npc_cfg in configs.npcs:
        if npc_cfg['floor'] != floor:
            continue
        room = random.choice(candidate_rooms)
        x = random.randint(room.x1 + 1, room.x2 - 1)
        y = random.randint(room.y1 + 1, room.y2 - 1)
        spawn_npc(npc_cfg, x, y)


def spawn_shopkeeper(x: int, y: int) -> int:
    """Create the vendor at (x, y) with freshly rolled stock. Open the shop by
    pressing Confirm while standing next to it."""
    return esper.create_entity(
        Position(x, y),
        Renderable(sprite_id='shopkeeper', color=(255, 215, 0)),
        Shopkeeper(offers=build_shop_offers()),
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


EXIT_MIN_ROOM_DISTANCE = 2

# Gate guardians per floor: a base count, plus one more for every few floors of depth.
GUARDIANS_BASE = 2
FLOORS_PER_EXTRA_GUARDIAN = 5


def _select_exit_room(
    rooms: list[RectangularRoom],
    *,
    player_room_index: int = 0,
    min_distance: int = EXIT_MIN_ROOM_DISTANCE,
) -> RectangularRoom | None:
    """Return the room farthest from the player's room that is at least
    ``min_distance`` rooms away, or ``None`` if none qualifies.

    Rooms form a linear connectivity chain (each room tunnels only to the
    previous one), so chain distance is just the difference in list index.
    """
    candidates = [
        (abs(i - player_room_index), room) for i, room in enumerate(rooms) if abs(i - player_room_index) >= min_distance
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def _guardian_count(floor: int) -> int:
    """How many gate guardians seal `floor`: two to start, one more every five floors deep."""
    return GUARDIANS_BASE + floor // FLOORS_PER_EXTRA_GUARDIAN


def _spawn_guardians(dungeon: Map, exit_room: RectangularRoom, rooms: list[RectangularRoom], floor: int):
    """Spawn the floor's gate guardians, which seal the exit until slain. One holds the exit
    room; the rest hide in other rooms, so clearing the seal means exploring the floor."""
    configs = esper.get_component(Configuration)[0][1]
    guardians = [e for e in configs.enemies.values() if e.get('guardian') and e['floors'][0] <= floor <= e['floors'][1]]
    if not guardians:
        return
    guardian_cfg = random.choice(guardians)

    # The exit room hosts one; fill the rest from other rooms (skipping the player's start).
    others = [r for r in rooms if r is not exit_room and r is not rooms[0]]
    random.shuffle(others)
    host_rooms = [exit_room, *others[: _guardian_count(floor) - 1]]

    exit_p = exit_room.center
    for room in host_rooms:
        x = random.randint(room.x1 + 1, room.x2 - 1)
        y = random.randint(room.y1 + 1, room.y2 - 1)
        if (x, y) == (exit_p.x, exit_p.y):  # don't bury the stairs under its guardian
            x = min(x + 1, room.x2 - 1)
        spawn_enemy(guardian_cfg, x, y, rooms)


def _current_floor() -> int:
    return get_singleton(GameState).floor


def _select_floor_tiles(floor_number: int) -> tuple[Tile, Tile, Tile]:
    """Pick (wall, floor, exit) tiles appropriate to `floor_number`'s depth. Tiles
    live on the Configuration singleton, so query it directly rather than threading
    the config through every call site."""
    tiles_config = get_singleton(Configuration).tiles
    available_tiles = [t for t in tiles_config if t['depth'][0] <= floor_number <= t['depth'][1]]

    def make_tile(cfg: TileConfig, walkable: bool, transparent: bool, is_exit: bool = False):
        return Tile(
            walkable=walkable,
            transparent=transparent,
            sprite_id=cfg['id'],
            fg=to_rgb(cfg.get('fg') or UI_WHITE),
            bg=to_rgb(cfg.get('bg') or UI_BLACK),
            is_exit=is_exit,
        )

    wall_tile = make_tile(random.choice([t for t in available_tiles if t['type'] == 'wall']), False, False)
    floor_tile = make_tile(random.choice([t for t in available_tiles if t['type'] == 'floor']), True, True)
    exit_tile = make_tile(random.choice([t for t in available_tiles if t['type'] == 'exit']), True, True, is_exit=True)
    return wall_tile, floor_tile, exit_tile


def _announce_floor(floor_number: int):
    logs = esper.get_component(MessageLog)
    if logs:
        logs[0][1].add_simple_message(f'Entered level {floor_number}', color=(255, 255, 255))


def generate_dungeon(
    max_rooms: int,
    room_min_size: int,
    room_max_size: int,
    max_items_per_room: int,
) -> tuple[Map, Point]:
    floor_number = _current_floor()
    wall_tile, floor_tile, exit_tile = _select_floor_tiles(floor_number)
    item_types = list(ItemType)

    def build_attempt() -> tuple[Map, list[RectangularRoom], Point]:
        """Lay out one candidate dungeon: a chain of connected rooms with items."""
        dungeon = Map(MAP_WIDTH, MAP_HEIGHT, wall_tile)
        rooms: list[RectangularRoom] = []
        player_start = Point(MAP_WIDTH // 2, MAP_HEIGHT // 2)

        for _ in range(max_rooms):
            w = random.randint(room_min_size, room_max_size)
            h = random.randint(room_min_size, room_max_size)
            x = random.randint(0, dungeon.width - w - 1)
            y = random.randint(0, dungeon.height - h - 1)

            new_room = RectangularRoom(x, y, w, h, dungeon)
            if any(new_room.intersects(other) for other in rooms):
                continue

            for rx in range(new_room.x1 + 1, new_room.x2):
                for ry in range(new_room.y1 + 1, new_room.y2):
                    dungeon.set_tile(rx, ry, floor_tile)

            if not rooms:
                player_start = new_room.center
            else:
                for p in tunnel_between(rooms[-1].center, new_room.center):
                    dungeon.set_tile(p.x, p.y, floor_tile)

                num_items = random.randint(0, max_items_per_room)
                for _ in range(num_items):
                    ix = random.randint(new_room.x1 + 1, new_room.x2 - 1)
                    iy = random.randint(new_room.y1 + 1, new_room.y2 - 1)
                    p = Point(ix, iy)
                    new_room.items.setdefault(p, []).append(random.choice(item_types))

            rooms.append(new_room)
        return dungeon, rooms, player_start

    # Retry until the exit can sit at least EXIT_MIN_ROOM_DISTANCE rooms from the
    # player's start; rooms form a linear chain, so this almost always holds on
    # the first attempt.
    dungeon, rooms, player_start = build_attempt()
    for _attempt in range(9):
        if _select_exit_room(rooms) is not None:
            break
        dungeon, rooms, player_start = build_attempt()

    for i, room in enumerate(rooms):
        room.spawn_entities(rooms, spawn_enemies=(i > 0))

    _spawn_floor_npcs(rooms, floor_number)

    exit_room = _select_exit_room(rooms) or (rooms[-1] if rooms else None)
    if exit_room is not None:
        exit_p = exit_room.center
        dungeon.set_tile(exit_p.x, exit_p.y, exit_tile)
        _spawn_guardians(dungeon, exit_room, rooms, floor_number)

    _announce_floor(floor_number)
    return dungeon, player_start


def generate_shop_floor() -> tuple[Map, Point]:
    """A safe single-room shop: the player enters beside the shopkeeper, with an
    exit across the room to descend. No items, enemies, or guardians."""
    floor_number = _current_floor()
    wall_tile, floor_tile, exit_tile = _select_floor_tiles(floor_number)

    dungeon = Map(MAP_WIDTH, MAP_HEIGHT, wall_tile)
    w, h = ROOM_MAX_SIZE, ROOM_MIN_SIZE
    room = RectangularRoom((MAP_WIDTH - w) // 2, (MAP_HEIGHT - h) // 2, w, h, dungeon)
    for rx in range(room.x1 + 1, room.x2):
        for ry in range(room.y1 + 1, room.y2):
            dungeon.set_tile(rx, ry, floor_tile)

    cy = room.center.y
    player_start = Point(room.x1 + 2, cy)
    spawn_shopkeeper(player_start.x + 1, cy)
    dungeon.set_tile(room.x2 - 2, cy, exit_tile)

    _announce_floor(floor_number)
    return dungeon, player_start
