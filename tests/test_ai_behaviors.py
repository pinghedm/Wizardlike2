import esper

from src.components import AI, Actor, FieldOfView, PatrolTag, Point, Position
from src.map_objects import Map
from src.procgen import RectangularRoom
from src.systems.ai import _process_chase, _process_flee, _process_guard, _process_patrol
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


# --- _process_guard ------------------------------------------------------------


def test_guard_holds_its_position():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    guard = runner.spawn_enemy(px, py - 4, runner.enemy_config('test_guardian'))  # GUARD behavior
    pos = esper.component_for_entity(guard, Position)
    start = pos.point

    _process_guard(guard, pos, {})

    assert pos.point == start  # guards never move; their melee is handled by the AISystem
