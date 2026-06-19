"""The corner minimap and the full-screen map render the explored level into a real
console. Like RenderSystem, they aren't wired into the harness tick loop, so these drive
them directly. console arrays are indexed [y, x].
"""

import esper
import tcod.event

from src.constants import UI_BLACK, UI_GRAY, UI_GREEN_BRIGHT
from src.map_objects import Map
from src.states import DisplayMode
from src.ui_helpers import blend
from src.ui_systems.minimap import MapViewSystem, MinimapSystem
from tests.headless_runner import HeadlessRunner

SPACE = ord(' ')


def _game_map() -> Map:
    return esper.get_component(Map)[0][1]


def _fg(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int, int]:
    return tuple(int(c) for c in runner.console.fg[y, x])


def _bg(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int, int]:
    return tuple(int(c) for c in runner.console.bg[y, x])


def _draw_corner(runner: HeadlessRunner, mode: DisplayMode = DisplayMode.EXPLORING):
    runner.console.clear()
    runner.game_state.display_mode = mode
    MinimapSystem(runner.layout).process()


def _panel_fgs(runner: HeadlessRunner, rect) -> list[tuple[int, int, int]]:
    return [_fg(runner, rect.x + ix, rect.y + iy) for iy in range(rect.height) for ix in range(rect.width)]


# --- corner minimap ---------------------------------------------------------


def test_corner_minimap_draws_explored_open_space():
    runner = HeadlessRunner(use_random_map=False)  # an all-floor room
    runner.tick()
    _game_map().explored[:, :] = True

    _draw_corner(runner)

    rect = runner.layout.minimap_rect(_game_map().width, _game_map().height)
    # The explored walkable room renders as lit block glyphs.
    assert UI_GRAY in _panel_fgs(runner, rect)


def test_corner_minimap_marks_the_player():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    game_map.explored[:, :] = True

    _draw_corner(runner)

    rect = runner.layout.minimap_rect(game_map.width, game_map.height)
    px, py = runner.player_pos
    pmx = min(rect.width - 1, px * rect.width // game_map.width)
    pmy = min(rect.height - 1, py * rect.height // game_map.height)
    assert _fg(runner, rect.x + pmx, rect.y + pmy) == UI_GREEN_BRIGHT


def test_corner_minimap_blank_before_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = False

    _draw_corner(runner)

    # Nothing explored yet, so no lit space — only the player marker is colored.
    rect = runner.layout.minimap_rect(_game_map().width, _game_map().height)
    assert UI_GRAY not in _panel_fgs(runner, rect)
    assert UI_GREEN_BRIGHT in _panel_fgs(runner, rect)


def test_corner_minimap_fades_the_dungeon_behind_it():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    game_map.explored[:, :] = False  # no paths, so the faded backdrop is what shows
    rect = runner.layout.minimap_rect(game_map.width, game_map.height)
    bright = (200, 100, 50)
    for y in range(rect.y, rect.y + rect.height):
        for x in range(rect.x, rect.x + rect.width):
            runner.console.rgb[y, x]['bg'] = bright  # stand in for the world drawn behind

    runner.game_state.display_mode = DisplayMode.EXPLORING
    MinimapSystem(runner.layout).process()

    # The panel's top-left (no player/path there) shows the backdrop blended toward black.
    assert _bg(runner, rect.x, rect.y) == blend(bright, UI_BLACK, MinimapSystem.BACKDROP_FADE)


def test_corner_minimap_hidden_outside_world_view():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = True

    _draw_corner(runner, DisplayMode.SETTINGS)

    rect = runner.layout.minimap_rect(_game_map().width, _game_map().height)
    assert runner.console.ch[rect.y, rect.x] == SPACE  # not a world view, so not drawn


# --- full-screen map (DisplayMode.MAP_VIEW) ---------------------------------


def test_map_key_toggles_the_full_screen_map():
    runner = HeadlessRunner(use_random_map=False)

    runner.simulate_key(tcod.event.KeySym.m)
    assert runner.display_mode == DisplayMode.MAP_VIEW

    runner.simulate_key(tcod.event.KeySym.m)
    assert runner.display_mode == DisplayMode.EXPLORING


def test_map_view_renders_across_the_full_screen():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = True
    runner.console.clear()
    runner.game_state.display_mode = DisplayMode.MAP_VIEW

    MapViewSystem(runner.layout).process()

    # The map fills the whole modal area, so the explored room's lit space spans its middle.
    area = runner.layout.modal_area
    assert any(_fg(runner, x, area.height // 2) == UI_GRAY for x in range(1, area.width - 1))


def test_map_view_not_drawn_while_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    _game_map().explored[:, :] = True
    runner.console.clear()
    runner.game_state.display_mode = DisplayMode.EXPLORING

    MapViewSystem(runner.layout).process()

    area = runner.layout.modal_area
    assert runner.console.ch[area.y, area.x] == SPACE
