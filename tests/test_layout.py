"""Unit tests for the pure layout geometry in src/layout.py."""

import pytest
import tcod.console

from src.layout import Layout, Rect


def _layout(width: int, height: int) -> Layout:
    return Layout(tcod.console.Console(width, height))


# --- Rect -------------------------------------------------------------------


@pytest.mark.parametrize(
    'x, y, inside',
    [
        (2, 3, True),  # top-left corner is inside
        (5, 7, True),  # bottom-right-most cell is inside (exclusive bounds)
        (6, 3, False),  # one past the right edge
        (1, 3, False),  # one before the left edge
        (2, 8, False),  # one past the bottom edge
    ],
)
def test_rect_contains(x, y, inside):
    rect = Rect(2, 3, 4, 5)  # covers x in [2, 6), y in [3, 8)
    assert rect.contains(x, y) is inside


def test_rect_centered():
    # A 24x6 box centered in an 80x50 area.
    assert Rect(0, 0, 80, 50).centered(24, 6) == (28, 22)


def test_rect_centered_offset_from_rect_origin():
    # Centering happens within the rect, not the whole screen.
    assert Rect(10, 20, 40, 10).centered(10, 4) == (25, 23)


def test_split_left_partitions_the_rect():
    left, right = Rect(0, 45, 80, 5).split_left(34)
    assert left == Rect(0, 45, 34, 5)
    assert right == Rect(34, 45, 46, 5)


def test_split_left_clamps_to_width():
    # Asking for more than the rect's width yields the whole rect and an empty remainder.
    left, right = Rect(0, 0, 80, 5).split_left(100)
    assert left == Rect(0, 0, 80, 5)
    assert right.width == 0


# --- Layout panels ----------------------------------------------------------


@pytest.mark.parametrize('width, height', [(80, 50), (100, 40), (120, 80)])
def test_panels_partition_the_console(width, height):
    layout = _layout(width, height)
    viewport, hud = layout.map_viewport, layout.hud

    # HUD is a full-width bar pinned to the bottom; the viewport fills the rest,
    # and together they exactly tile the console with no overlap or gap.
    assert hud == Rect(0, height - Layout.HUD_HEIGHT, width, Layout.HUD_HEIGHT)
    assert viewport == Rect(0, 0, width, height - Layout.HUD_HEIGHT)
    assert viewport.height + hud.height == height
    assert layout.modal_area == Rect(0, 0, width, height)


def test_hud_height_clamps_to_a_tiny_console():
    layout = _layout(20, 3)
    assert layout.hud.height == 3
    assert layout.map_viewport.height == 0


# --- camera_offset ----------------------------------------------------------


def test_camera_centers_player_in_a_large_map():
    layout = _layout(80, 50)  # viewport 80x43 -> 40x21 tiles (each a 2x2 block)
    # player minus half the visible tiles: (100-20, 100-10)
    assert layout.camera_offset(100, 100, 200, 200) == (80, 90)


def test_camera_clamps_to_top_left_corner():
    layout = _layout(80, 50)
    assert layout.camera_offset(0, 0, 200, 200) == (0, 0)


def test_camera_clamps_to_bottom_right_corner():
    layout = _layout(80, 50)  # 40x21 visible tiles; max offsets (160, 179)
    assert layout.camera_offset(199, 199, 200, 200) == (160, 179)


@pytest.mark.parametrize('player_x, player_y', [(0, 0), (10, 10), (19, 19)])
def test_camera_stays_put_when_map_fits_viewport(player_x, player_y):
    layout = _layout(80, 50)
    assert layout.camera_offset(player_x, player_y, 20, 20) == (0, 0)


# --- minimap_rect -----------------------------------------------------------


@pytest.mark.parametrize('width, height', [(80, 50), (100, 60), (40, 30)])
def test_minimap_hugs_the_top_right_inside_the_viewport(width, height):
    layout = _layout(width, height)
    view = layout.map_viewport

    mm = layout.minimap_rect(140, 90)

    assert mm.y == view.y  # pinned to the top
    assert mm.x + mm.width == view.x + view.width  # flush to the right edge
    assert view.contains(mm.x, mm.y)
    assert view.contains(mm.x + mm.width - 1, mm.y + mm.height - 1)  # fits within the viewport
