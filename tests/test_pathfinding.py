import numpy as np

from src.pathfinding import Dijkstra


def _walkable(width: int, height: int) -> np.ndarray:
    return np.ones((width, height), dtype=bool)


# --- get_path ordering: goal-side first, goal excluded, start last ---


def test_straight_corridor_path_is_ordered_from_goal_to_start_excluding_goal():
    pf = Dijkstra(_walkable(8, 3))
    pf.set_goal(0, 1)

    # start five tiles east of the goal: near-goal tile first, own tile last, goal absent.
    assert pf.get_path(5, 1) == [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]


def test_next_step_toward_goal_is_the_second_to_last_entry():
    pf = Dijkstra(_walkable(8, 3))
    pf.set_goal(0, 1)
    path = pf.get_path(5, 1)

    # path[-2] is the tile an entity at (5, 1) should step to — one closer to the goal.
    assert path[-2] == (4, 1)


def test_path_from_adjacent_tile_is_just_the_start():
    pf = Dijkstra(_walkable(7, 7))
    pf.set_goal(3, 3)

    # Adjacent to the goal: only the start tile, so len == 1 (an entity here holds position).
    assert pf.get_path(3, 4) == [(3, 4)]


def test_path_from_the_goal_is_empty():
    pf = Dijkstra(_walkable(7, 7))
    pf.set_goal(3, 3)

    assert pf.get_path(3, 3) == []


def test_open_room_path_cuts_the_diagonal():
    pf = Dijkstra(_walkable(7, 7))
    pf.set_goal(3, 3)

    assert pf.get_path(0, 0) == [(2, 2), (1, 1), (0, 0)]


def test_unreachable_start_yields_no_path():
    walkable = _walkable(5, 5)
    walkable[1, 0] = walkable[0, 1] = walkable[1, 1] = False  # wall off the (0, 0) corner
    pf = Dijkstra(walkable)
    pf.set_goal(4, 4)

    assert pf.get_path(0, 0) == []
