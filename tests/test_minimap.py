"""The corner minimap and full-screen map render pixel-native into the window Surface (a
downscaled image of the explored open space), so these sample pixels. They aren't wired into
the harness tick loop, so the tests drive them directly.
"""

import esper
import pygame

from src.components import Guardian, Position, Stats
from src.constants import UI_GRAY_DARK, UI_GREEN_BRIGHT, UI_ORANGE, UI_YELLOW
from src.map_objects import Map
from src.render import minimap_rect
from src.states import DisplayMode
from src.ui_systems.minimap import MapViewSystem, MinimapSystem
from tests.headless_runner import HeadlessRunner

SENTINEL = (255, 0, 255)


def _game_map() -> Map:
    return esper.get_component(Map)[0][1]


def _px(surface: pygame.Surface, x: int, y: int) -> tuple[int, int, int]:
    return tuple(surface.get_at((x, y)))[:3]


def _draw_corner(runner: HeadlessRunner, mode: DisplayMode = DisplayMode.EXPLORING) -> pygame.Surface:
    runner.surface.fill(SENTINEL)
    runner.game_state.display_mode = mode
    MinimapSystem(runner.surface, runner.asset_loader).process()
    return runner.surface


def _player_marker(runner: HeadlessRunner, rect: pygame.Rect) -> tuple[int, int]:
    game_map = _game_map()
    px, py = runner.player_pos
    size = max(3, rect.width // 60)
    return (
        rect.x + px * rect.width // game_map.width + size // 2,
        rect.y + py * rect.height // game_map.height + size // 2,
    )


# --- corner minimap ---------------------------------------------------------


def test_corner_minimap_lights_explored_open_space():
    runner = HeadlessRunner(use_random_map=False)  # an all-floor room
    runner.tick()
    _game_map().explored[:, :] = True

    surface = _draw_corner(runner)
    rect = minimap_rect(runner.surface, _game_map().width, _game_map().height)
    # The explored floor renders as lit (translucent gray) pixels across the panel.
    assert any(
        _px(surface, x, y)[0] > 40
        for x in range(rect.x + 3, rect.right - 3, 8)
        for y in range(rect.y + 3, rect.bottom - 3, 8)
    )


def test_corner_minimap_marks_the_player():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = True

    surface = _draw_corner(runner)
    rect = minimap_rect(runner.surface, _game_map().width, _game_map().height)
    assert _px(surface, *_player_marker(runner, rect)) == UI_GREEN_BRIGHT


def test_corner_minimap_blank_before_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = False

    surface = _draw_corner(runner)
    rect = minimap_rect(runner.surface, _game_map().width, _game_map().height)
    # Nothing explored: only the dimmed backdrop shows (the magenta sentinel, so g~0 — a lit gray
    # path would raise g), plus the player marker.
    assert _px(surface, rect.x + 3, rect.y + 3)[1] < 20  # no lit path here
    assert _px(surface, *_player_marker(runner, rect)) == UI_GREEN_BRIGHT


def test_corner_minimap_fades_the_dungeon_behind_it():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = False  # no paths, so the faded backdrop is what shows
    runner.surface.fill((200, 100, 50))  # stand in for the world drawn behind the panel

    runner.game_state.display_mode = DisplayMode.EXPLORING
    MinimapSystem(runner.surface, runner.asset_loader).process()

    rect = minimap_rect(runner.surface, _game_map().width, _game_map().height)
    r, _g, _b = _px(runner.surface, rect.x + 5, rect.y + 5)  # inside the panel, off the border/player
    assert 100 < r < 190  # the bright backdrop is dimmed toward black, not opaque, not untouched


def test_corner_minimap_hidden_outside_world_view():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = True

    surface = _draw_corner(runner, DisplayMode.SETTINGS)
    rect = minimap_rect(runner.surface, _game_map().width, _game_map().height)
    assert _px(surface, rect.x + 5, rect.y + 5) == SENTINEL  # not a world view, so not drawn


def _marker_px(rect: pygame.Rect, game_map: Map, tile: tuple[int, int]) -> tuple[int, int]:
    """A pixel inside the marker square drawn for map `tile` (mirrors _draw_markers' `at`)."""
    tx, ty = tile
    return rect.x + tx * rect.width // game_map.width + 1, rect.y + ty * rect.height // game_map.height + 1


def test_corner_minimap_marks_a_living_guardian():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    game_map.explored[:, :] = True
    esper.create_entity(Guardian(), Stats(hp=10, max_hp=10), Position(1, 1))  # far from the centered player

    surface = _draw_corner(runner)
    rect = minimap_rect(runner.surface, game_map.width, game_map.height)
    assert _px(surface, *_marker_px(rect, game_map, (1, 1))) == UI_ORANGE


def test_corner_minimap_marks_a_sealed_exit_dim_and_a_cleared_exit_bright():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    game_map.explored[:, :] = True
    exit_tile = (game_map.width - 2, game_map.height - 2)
    game_map.exit_pos = exit_tile

    # No guardians: exit is cleared, so its marker is bright yellow.
    surface = _draw_corner(runner)
    rect = minimap_rect(runner.surface, game_map.width, game_map.height)
    assert _px(surface, *_marker_px(rect, game_map, exit_tile)) == UI_YELLOW

    # A living guardian seals the exit, dimming its marker.
    esper.create_entity(Guardian(), Stats(hp=10, max_hp=10), Position(1, 1))
    surface = _draw_corner(runner)
    assert _px(surface, *_marker_px(rect, game_map, exit_tile)) == UI_GRAY_DARK


# --- full-screen map (DisplayMode.MAP_VIEW) ---------------------------------


def test_map_key_toggles_the_full_screen_map():
    runner = HeadlessRunner(use_random_map=False)

    runner.simulate_key(pygame.K_m)
    assert runner.display_mode == DisplayMode.MAP_VIEW

    runner.simulate_key(pygame.K_m)
    assert runner.display_mode == DisplayMode.EXPLORING


def test_map_view_renders_across_the_full_screen():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = True
    runner.surface.fill(SENTINEL)
    runner.game_state.display_mode = DisplayMode.MAP_VIEW

    MapViewSystem(runner.surface, runner.asset_loader).process()

    w, h = runner.surface.get_size()
    assert any(_px(runner.surface, x, h // 2)[0] > 100 for x in range(w // 4, 3 * w // 4, 20))  # lit paths across


def test_map_view_not_drawn_while_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    runner.surface.fill(SENTINEL)
    runner.game_state.display_mode = DisplayMode.EXPLORING

    MapViewSystem(runner.surface, runner.asset_loader).process()
    assert _px(runner.surface, 800, 500) == SENTINEL
