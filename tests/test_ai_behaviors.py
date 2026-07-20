import esper

from src.components import AI, Actor, FieldOfView, PatrolTag, Point, Position
from src.map_objects import Map
from src.pathfinding import Dijkstra
from src.procgen import RectangularRoom
from src.systems.ai import (
    _MAX_FRESH_PATROL_FLOODS_PER_TICK,
    _MAX_PATH_DIST,
    AISystem,
    _process_chase,
    _process_flee,
    _process_guard,
    _process_patrol,
    _remember_player_if_seen,
)
from tests.headless_runner import HeadlessRunner


def _pin_target(enemy: int, target: Point):
    """Set an enemy's flee/chase target without depending on FOV or tick ordering."""
    fov = esper.component_for_entity(enemy, FieldOfView)
    fov.visible_tiles = set()
    fov.dirty = False
    esper.component_for_entity(enemy, AI).last_known_player_position = target


def _patrol_rooms() -> list[RectangularRoom]:
    """Two rooms whose centres define a fixed patrol path (3, 3) -> (3, 8).

    With exactly two rooms the 'other' waypoint is chosen deterministically, so
    procgen builds PatrolTag(path=[(3, 3), (3, 8)]).
    """
    game_map = esper.get_component(Map)[0][1]
    return [RectangularRoom(2, 2, 2, 2, game_map), RectangularRoom(2, 7, 2, 2, game_map)]


# --- _process_chase ------------------------------------------------------------


def test_chase_steps_toward_the_players_last_known_position():
    runner = HeadlessRunner(use_random_map=False)  # open 20x20 room, player at centre
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px, py - 5)  # default CHASE behavior
    _pin_target(enemy, Point(px, py))
    pos = esper.component_for_entity(enemy, Position)

    _process_chase(enemy, pos, {})

    assert (pos.x, pos.y) == (px, py - 4)  # one step straight toward the player


# --- _process_patrol -----------------------------------------------------------


def test_patrol_steps_toward_its_current_waypoint():
    runner = HeadlessRunner(use_random_map=False)
    # Spawn off the first waypoint (3, 3) so the patrol walks toward it without advancing.
    enemy = runner.spawn_enemy(5, 3, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=_patrol_rooms())
    pos = esper.component_for_entity(enemy, Position)

    _process_patrol(enemy, pos, {})

    assert esper.component_for_entity(enemy, PatrolTag).index == 0  # not yet arrived
    assert (pos.x, pos.y) == (4, 3)  # one step toward waypoint (3, 3)


def test_patrol_advances_to_the_next_waypoint_upon_arrival():
    runner = HeadlessRunner(use_random_map=False)
    # Spawn on the first waypoint (3, 3), so the patrol advances to (3, 8) before moving.
    enemy = runner.spawn_enemy(3, 3, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=_patrol_rooms())
    pos = esper.component_for_entity(enemy, Position)

    _process_patrol(enemy, pos, {})

    assert esper.component_for_entity(enemy, PatrolTag).index == 1
    assert (pos.x, pos.y) == (3, 4)  # then stepped toward the new waypoint (3, 8)


def test_patrol_advances_when_blocked_from_its_waypoint():
    runner = HeadlessRunner(use_random_map=False)
    # Heading from (5, 3) toward waypoint (3, 3), the next step is (4, 3) — block it.
    enemy = runner.spawn_enemy(5, 3, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=_patrol_rooms())
    esper.create_entity(Position(4, 3), Actor())
    pos = esper.component_for_entity(enemy, Position)

    _process_patrol(enemy, pos, {})

    assert (pos.x, pos.y) == (5, 3)  # couldn't step past the blocker
    assert esper.component_for_entity(enemy, PatrolTag).index == 1  # gave up, retargets


def test_patrol_reaches_a_waypoint_beyond_the_chase_flood_bound():
    """Regression: patrol goals must flood the whole map. Chase/flee goals are distance-bounded for
    perf (so a fresh flood stays cheap as the player runs), but a patrol's waypoint can sit far
    across the map — bounding it too stranded every patrol, unable to path to its next stop."""
    runner = HeadlessRunner(use_random_map=False)
    # Swap the little room for a long open map, then put a waypoint past the chase bound.
    floor = esper.get_component(Map)[0][1].tiles[0][0]  # a walkable floor tile
    for ent, _map in esper.get_component(Map):
        esper.delete_entity(ent, immediate=True)
    far = int(_MAX_PATH_DIST) + 10
    esper.create_entity(Map(far + 5, 8, floor))
    player_pos = esper.component_for_entity(runner.player, Position)
    player_pos.x, player_pos.y = 10, 4  # keep the player in bounds of the reshaped map

    game_map = esper.get_component(Map)[0][1]
    # Room centres (4, 4) and (far + 1, 4): patrol path [(4, 4), (far + 1, 4)], > _MAX_PATH_DIST apart.
    rooms = [RectangularRoom(3, 3, 2, 2, game_map), RectangularRoom(far, 3, 2, 2, game_map)]
    enemy = runner.spawn_enemy(4, 4, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=rooms)
    pos = esper.component_for_entity(enemy, Position)

    AISystem().process()  # the real path: builds the patrol goal's field unbounded

    assert pos.x > 4  # stepped toward the far waypoint instead of stalling


# --- _process_flee -------------------------------------------------------------


def test_flee_moves_the_enemy_away_from_the_player():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px - 2, py, {**runner.enemy_config(), 'behavior': 'FLEE'})
    _pin_target(enemy, Point(px, py))
    pos = esper.component_for_entity(enemy, Position)
    before = max(abs(px - pos.x), abs(py - pos.y))

    _process_flee(enemy, pos, {})

    after = max(abs(px - pos.x), abs(py - pos.y))
    assert after > before  # stepped farther from the player


def test_flee_holds_when_it_has_never_seen_the_player():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(3, 3, {**runner.enemy_config(), 'behavior': 'FLEE'})
    _pin_target(enemy, None)  # no last-known position to flee from
    pos = esper.component_for_entity(enemy, Position)

    _process_flee(enemy, pos, {})

    assert pos.point == Point(3, 3)  # nowhere to run, so it stays put


def test_flee_holds_when_the_escape_tile_is_off_the_map():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(0, 0, {**runner.enemy_config(), 'behavior': 'FLEE'})
    _pin_target(enemy, Point(5, 5))  # player is down-right; the only retreat is off-map
    pos = esper.component_for_entity(enemy, Position)

    _process_flee(enemy, pos, {})

    assert pos.point == Point(0, 0)  # cornered against the bounds


# --- _process_guard ------------------------------------------------------------


def test_guard_holds_its_position():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    guard = runner.spawn_enemy(px, py - 4, runner.enemy_config('test_guardian'))  # GUARD behavior
    pos = esper.component_for_entity(guard, Position)
    start = pos.point

    _process_guard(guard, pos, {})

    assert pos.point == start  # guards never move; their melee is handled by the AISystem


# --- _remember_player_if_seen --------------------------------------------------


def test_remembers_the_players_position_when_in_view():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px, py - 3)
    fov = esper.component_for_entity(enemy, FieldOfView)
    fov.visible_tiles = {Point(px, py)}  # the player is in sight this tick
    fov.dirty = False
    esper.component_for_entity(enemy, AI).last_known_player_position = None

    _remember_player_if_seen(enemy)

    assert esper.component_for_entity(enemy, AI).last_known_player_position == Point(px, py)


# --- AISystem dispatch ---------------------------------------------------------


def test_aisystem_dispatches_each_movement_behavior_by_tag():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    patrol = runner.spawn_enemy(5, 3, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=_patrol_rooms())
    chaser = runner.spawn_enemy(px, py - 5, runner.enemy_config())  # default CHASE
    fleer = runner.spawn_enemy(px - 3, py, {**runner.enemy_config(), 'behavior': 'FLEE'})
    _pin_target(chaser, Point(px, py))
    _pin_target(fleer, Point(px, py))
    patrol_pos = esper.component_for_entity(patrol, Position)
    chaser_pos = esper.component_for_entity(chaser, Position)
    fleer_pos = esper.component_for_entity(fleer, Position)
    flee_before = max(abs(px - fleer_pos.x), abs(py - fleer_pos.y))

    AISystem().process()  # collect targets, build one Dijkstra map each, dispatch by tag

    assert (patrol_pos.x, patrol_pos.y) == (4, 3)  # PATROL stepped toward its waypoint
    assert (chaser_pos.x, chaser_pos.y) == (px, py - 4)  # CHASE stepped toward the player
    assert max(abs(px - fleer_pos.x), abs(py - fleer_pos.y)) > flee_before  # FLEE stepped away


# --- pathfinding caching (perf: avoid re-flooding the same field) ---------------


def _spy_on_floods(monkeypatch) -> list[float | None]:
    """Record the max_dist of every Dijkstra flood as it happens (None == unbounded)."""
    floods: list[float | None] = []
    original = Dijkstra.set_goal

    def spy(self, x, y, max_dist=None):
        floods.append(max_dist)
        original(self, x, y, max_dist)

    monkeypatch.setattr(Dijkstra, 'set_goal', spy)
    return floods


def test_chase_field_is_reused_after_a_one_tile_player_move(monkeypatch):
    # A moving player shifts a chaser's goal one tile per step. Re-flooding every step was the
    # recurring in-combat hitch; a field for a goal within tolerance is reused instead.
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px, py - 6)
    _pin_target(enemy, Point(px, py))
    floods = _spy_on_floods(monkeypatch)

    ai = AISystem()
    ai.process()
    assert len(floods) == 1  # one flood to build the chase field

    _pin_target(enemy, Point(px + 1, py))  # player stepped one tile over
    ai.process()
    assert len(floods) == 1  # cached field is within tolerance, so no fresh flood


def test_patrol_field_builds_are_capped_per_tick(monkeypatch):
    # Every patrol's waypoint field is an unbounded whole-map flood; a floor's worth going cold at
    # once froze the frame. Only a budgeted few are built per tick, and the rest hold.
    runner = HeadlessRunner(use_random_map=False)
    game_map = esper.get_component(Map)[0][1]
    # Two patrols with distinct current waypoints (3, 3) and (10, 3): two cold goals at once.
    rooms_a = [RectangularRoom(2, 2, 2, 2, game_map), RectangularRoom(2, 7, 2, 2, game_map)]
    rooms_b = [RectangularRoom(9, 2, 2, 2, game_map), RectangularRoom(9, 7, 2, 2, game_map)]
    a = runner.spawn_enemy(6, 3, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=rooms_a)
    b = runner.spawn_enemy(13, 3, {**runner.enemy_config(), 'behavior': 'PATROL'}, rooms=rooms_b)
    floods = _spy_on_floods(monkeypatch)

    AISystem().process()

    unbounded = [d for d in floods if d is None]
    assert len(unbounded) == _MAX_FRESH_PATROL_FLOODS_PER_TICK  # only the budget built this tick
    a_pos = esper.component_for_entity(a, Position)
    b_pos = esper.component_for_entity(b, Position)
    moved = [(a_pos.x, a_pos.y) != (6, 3), (b_pos.x, b_pos.y) != (13, 3)]
    assert sum(moved) == 1  # exactly one patrol advanced; the other held for its deferred field
