"""RenderSystem (the map/entity draw pass) renders into a real console.

The headless harness wires up the UI render processors but not RenderSystem, so
this drives it directly. A 20x20 map in an 80x50 console keeps the camera clamped
to (0, 0); each map tile fills a TILE_SCALE block of cells, so a map cell (x, y) draws
at the block whose top-left is map_to_screen(x, y). The helpers below map a tile to that
block so tests can assert on it. console arrays are indexed [y, x].
"""

import esper
import pytest

from src.components import Effect, EffectType, Position, StatusEffects, StatusType
from src.constants import UI_BLACK
from src.map_objects import Map
from src.states import DisplayMode
from src.systems import RenderSystem
from src.systems.processors import STATUS_TINT_PRIORITY
from src.systems.visuals import EFFECT_COLORS
from src.ui_helpers import blend
from tests.headless_runner import HeadlessRunner

SPACE = ord(' ')
# A player at (10, 10) with FOV radius 8 sees nearby tiles but not these far ones.
VISIBLE_FLOOR = (10, 15)
UNSEEN_TILE = (2, 2)
UNEXPLORED_CORNER = (0, 0)


def _game_map() -> Map:
    return esper.get_component(Map)[0][1]


def _draw(runner: HeadlessRunner, mode: DisplayMode = DisplayMode.EXPLORING):
    """Run one RenderSystem pass over a freshly cleared console."""
    runner.console.clear()
    runner.game_state.display_mode = mode
    RenderSystem(runner.layout, runner.asset_loader).process()


def _origin(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int]:
    """The console cell a map tile's block starts at (camera clamped to (0, 0) here)."""
    return runner.layout.map_to_screen(map_x=x, map_y=y, cam_x=0, cam_y=0)


def _fg(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int, int]:
    sx, sy = _origin(runner, x, y)
    return tuple(int(c) for c in runner.console.fg[sy, sx])


def _bg(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int, int]:
    sx, sy = _origin(runner, x, y)
    return tuple(int(c) for c in runner.console.bg[sy, sx])


def _ch(runner: HeadlessRunner, x: int, y: int) -> int:
    sx, sy = _origin(runner, x, y)
    return runner.console.ch[sy, sx]


def test_render_draws_visible_tiles_and_skips_unseen():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()  # compute the player's FOV

    _draw(runner)

    vx, vy = VISIBLE_FLOOR
    assert _ch(runner, vx, vy) != SPACE
    assert _fg(runner, vx, vy) == _game_map().tiles[vx][vy].fg

    cx, cy = UNEXPLORED_CORNER
    assert _ch(runner, cx, cy) == SPACE


def test_render_dims_explored_but_unseen_tiles():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    ux, uy = UNSEEN_TILE
    game_map.explored[ux, uy] = True

    _draw(runner)

    full = game_map.tiles[ux][uy].fg
    dimmed = tuple(int(c * 0.3) for c in full)
    assert _fg(runner, ux, uy) == dimmed


@pytest.mark.parametrize('status', STATUS_TINT_PRIORITY)
def test_render_tints_entity_by_active_status(status):
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    esper.component_for_entity(runner.player, StatusEffects).active[status] = Effect(
        type=EffectType(status), duration=5
    )

    _draw(runner)

    assert _bg(runner, px, py) == blend(UI_BLACK, EFFECT_COLORS[EffectType(status)], 0.5)


def test_render_tint_prefers_higher_priority_status_when_stacked():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    active = esper.component_for_entity(runner.player, StatusEffects).active
    # STUN outranks POISON in STATUS_TINT_PRIORITY, so its tint wins over both being active.
    active[StatusType.POISON] = Effect(type=EffectType.POISON, duration=5)
    active[StatusType.STUN] = Effect(type=EffectType.STUN, duration=5)

    _draw(runner)

    assert _bg(runner, px, py) == blend(UI_BLACK, EFFECT_COLORS[EffectType.STUN], 0.5)


def test_render_leaves_unstatused_entity_untinted():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)

    _draw(runner)

    # No status, so the glyph draws over the tile's own background, not a tint.
    epos = esper.component_for_entity(enemy, Position)
    assert _ch(runner, epos.x, epos.y) != SPACE
    assert _bg(runner, epos.x, epos.y) == _game_map().tiles[epos.x][epos.y].bg


RENDER_MODES = {
    DisplayMode.EXPLORING,
    DisplayMode.CASTING,
    DisplayMode.COMBINING,
    DisplayMode.TARGETING,
    DisplayMode.SHOPPING,
}


@pytest.mark.parametrize('mode', [m for m in DisplayMode if m not in RENDER_MODES])
def test_render_noops_outside_render_modes(mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()

    _draw(runner, mode)

    px, py = runner.player_pos
    assert _ch(runner, px, py) == SPACE


def test_render_noops_without_a_map():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    for ent, _map in esper.get_component(Map):
        esper.delete_entity(ent, immediate=True)

    _draw(runner)

    px, py = runner.player_pos
    assert _ch(runner, px, py) == SPACE
