"""RenderSystem (the map/entity draw pass) renders into a real console.

The headless harness wires up the UI render processors but not RenderSystem, so
this drives it directly. A 20x20 map in an 80x50 console keeps the camera clamped
to (0, 0), so a map cell (x, y) draws at console cell (x, y) -- letting tests assert
on specific cells. console arrays are indexed [y, x].
"""

import esper
import pytest

from src.components import Effect, EffectType, Position, StatusEffects, StatusType
from src.constants import UI_BLACK, UI_YELLOW
from src.map_objects import Map
from src.states import DisplayMode
from src.systems import RenderSystem
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


def _fg(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int, int]:
    return tuple(int(c) for c in runner.console.fg[y, x])


def _bg(runner: HeadlessRunner, x: int, y: int) -> tuple[int, int, int]:
    return tuple(int(c) for c in runner.console.bg[y, x])


def test_render_draws_visible_tiles_and_skips_unseen():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()  # compute the player's FOV

    _draw(runner)

    vx, vy = VISIBLE_FLOOR
    assert runner.console.ch[vy, vx] != SPACE
    assert _fg(runner, vx, vy) == _game_map().tiles[vx][vy].fg

    cx, cy = UNEXPLORED_CORNER
    assert runner.console.ch[cy, cx] == SPACE


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


def test_render_highlights_stunned_entity_only():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.STUN] = Effect(
        type=EffectType.STUN, duration=5
    )

    _draw(runner)

    highlight = blend(UI_BLACK, UI_YELLOW, 0.5)
    assert _bg(runner, px, py) == highlight

    epos = esper.component_for_entity(enemy, Position)
    assert runner.console.ch[epos.y, epos.x] != SPACE
    assert _bg(runner, epos.x, epos.y) != highlight


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
    assert runner.console.ch[py, px] == SPACE


def test_render_noops_without_a_map():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    for ent, _map in esper.get_component(Map):
        esper.delete_entity(ent, immediate=True)

    _draw(runner)

    px, py = runner.player_pos
    assert runner.console.ch[py, px] == SPACE
