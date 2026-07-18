import numpy as np

from src.fov import compute_fov


def _open(width: int, height: int) -> np.ndarray:
    return np.ones((width, height), dtype=bool)


def test_the_origin_is_always_visible():
    visible = compute_fov(_open(5, 5), (2, 2), radius=5)
    assert visible[2, 2]


def test_an_open_room_within_radius_is_fully_visible():
    visible = compute_fov(_open(5, 5), (2, 2), radius=5)
    assert visible.all()


def test_tiles_beyond_the_radius_are_dark():
    visible = compute_fov(_open(11, 11), (5, 5), radius=2)
    assert visible[5, 7]  # two tiles away — inside the radius
    assert not visible[5, 8]  # three tiles away — beyond it


def test_a_wall_blocks_sight_of_tiles_directly_behind_it():
    transparent = _open(7, 7)
    transparent[3, :] = False  # an opaque column at x=3
    visible = compute_fov(transparent, (0, 3), radius=6)

    assert visible[1, 3]  # in front of the wall
    assert visible[3, 3]  # the wall itself is lit (light_walls default)
    assert not visible[5, 3]  # directly behind the wall — shadowed


def test_light_walls_false_leaves_opaque_edges_unlit():
    transparent = _open(6, 1)
    transparent[3, 0] = False  # a lone wall east of the origin
    lit = compute_fov(transparent, (0, 0), radius=5, light_walls=True)
    unlit = compute_fov(transparent, (0, 0), radius=5, light_walls=False)

    assert lit[3, 0]  # walls drawn when light_walls is on
    assert not unlit[3, 0]  # and skipped when it's off
    assert not lit[4, 0]  # the tile behind the wall stays dark either way
