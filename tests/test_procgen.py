import esper
import pytest

from src.components import FieldOfView, Item, ItemType, Point, Position
from src.procgen import (
    RectangularRoom,
    _guardian_count,
    _select_exit_room,
    transition_to_next_floor,
    tunnel_between,
)
from tests.headless_runner import HeadlessRunner

# --- Pure geometry: deterministic, no randomness ------------------------------


def test_room_center_is_the_geometric_midpoint():
    room = RectangularRoom(x=10, y=20, width=4, height=6, dungeon=None)
    assert room.center == Point(12, 23)


def test_overlapping_rooms_intersect():
    a = RectangularRoom(x=0, y=0, width=5, height=5, dungeon=None)
    b = RectangularRoom(x=3, y=3, width=5, height=5, dungeon=None)
    assert a.intersects(b)
    assert b.intersects(a)


def test_separated_rooms_do_not_intersect():
    a = RectangularRoom(x=0, y=0, width=4, height=4, dungeon=None)
    b = RectangularRoom(x=20, y=20, width=4, height=4, dungeon=None)
    assert not a.intersects(b)
    assert not b.intersects(a)


# --- Exit placement: at least 2 rooms from the player ------------------------


@pytest.mark.parametrize(
    'n_rooms, expected_index',
    [(1, None), (2, None), (3, 2), (5, 4)],
)
def test_select_exit_room_picks_farthest_room_at_least_two_away(n_rooms, expected_index):
    # Rooms form a linear chain, so chain distance from the player (room 0) is the index.
    rooms = [RectangularRoom(i * 10, 0, 4, 4, dungeon=None) for i in range(n_rooms)]
    chosen = _select_exit_room(rooms)
    if expected_index is None:
        assert chosen is None
    else:
        assert chosen is rooms[expected_index]


@pytest.mark.parametrize(
    'floor, expected',
    [(1, 2), (4, 2), (5, 3), (9, 3), (10, 4)],  # base 2, +1 every 5 floors deep
)
def test_guardian_count_grows_with_depth(floor, expected):
    assert _guardian_count(floor) == expected


def _assert_contiguous_path(path, start, end):
    assert path[0] == start
    assert path[-1] == end
    # No teleports: each step moves at most one tile (0 covers the repeated corner).
    for prev, cur in zip(path, path[1:], strict=False):
        assert abs(cur.x - prev.x) + abs(cur.y - prev.y) <= 1


def test_tunnel_horizontal_first_connects_endpoints_contiguously(monkeypatch):
    # random.random() < 0.5 takes the horizontal-then-vertical branch.
    monkeypatch.setattr('random.random', lambda: 0.0)
    start, end = Point(2, 3), Point(18, 11)
    _assert_contiguous_path(list(tunnel_between(start, end)), start, end)


def test_tunnel_vertical_first_connects_endpoints_contiguously(monkeypatch):
    # random.random() >= 0.5 takes the vertical-then-horizontal branch.
    monkeypatch.setattr('random.random', lambda: 0.9)
    start, end = Point(2, 3), Point(18, 11)
    _assert_contiguous_path(list(tunnel_between(start, end)), start, end)


# --- Floor transition: deterministic structural behavior ----------------------


def test_transition_increments_floor():
    runner = HeadlessRunner(use_random_map=True)
    start_floor = runner.game_state.floor

    transition_to_next_floor()

    assert runner.game_state.floor == start_floor + 1


def test_transition_clears_previous_floor_entities():
    runner = HeadlessRunner(use_random_map=True)
    stale_enemy = runner.spawn_enemy(1, 1)
    stale_item = esper.create_entity(Position(1, 2), Item(next(iter(ItemType))))

    transition_to_next_floor()

    assert not esper.entity_exists(stale_enemy)
    assert not esper.entity_exists(stale_item)


def test_transition_marks_player_fov_dirty():
    runner = HeadlessRunner(use_random_map=True)
    esper.component_for_entity(runner.player, FieldOfView).dirty = False

    transition_to_next_floor()

    assert esper.component_for_entity(runner.player, FieldOfView).dirty
