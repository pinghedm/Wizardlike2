"""RenderSystem (the map/entity draw pass) renders into a pygame Surface.

The headless harness wires up the (dormant) UI processors but not RenderSystem, so
this drives it directly against a window-sized Surface. A 20x20 map keeps the camera
clamped to (0, 0), so map tile (x, y) draws into the TILE_PX square at pixel
(x*TILE_PX, y*TILE_PX). Each tile fills that square with its bg color first (then a
centered glyph / sprite on top), so the square's top-left pixel is a reliable read of
the tile's bg. The map draws as one opaque layer (black where a tile is unexplored/skipped),
mirroring the black map background the game clears each frame before RenderSystem runs.
"""

from dataclasses import replace

import esper
import pygame
import pytest

from src.components import Effect, EffectType, Position, StatusEffects, StatusType
from src.constants import TILE_PX, UI_BLACK, WINDOW_HEIGHT, WINDOW_WIDTH
from src.map_objects import Map
from src.states import WORLD_VIEW_MODES, DisplayMode
from src.systems import RenderSystem
from src.systems.processors import STATUS_TINT_PRIORITY
from src.systems.visuals import EFFECT_COLORS
from src.ui_helpers import blend
from tests.headless_runner import HeadlessRunner

# A fill no tile uses, so a tile the renderer skips reads back as this.
SENTINEL = (255, 0, 255)
# A player at (10, 10) with FOV radius 8 sees nearby tiles but not these far ones.
VISIBLE_FLOOR = (10, 15)
UNSEEN_TILE = (2, 2)
UNEXPLORED_CORNER = (0, 0)


def _game_map() -> Map:
    return esper.get_component(Map)[0][1]


def _draw(runner: HeadlessRunner, mode: DisplayMode = DisplayMode.EXPLORING) -> pygame.Surface:
    """Run one RenderSystem pass over a sentinel-filled window Surface."""
    surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    surface.fill(SENTINEL)
    runner.game_state.display_mode = mode
    RenderSystem(surface, runner.asset_loader).process()
    return surface


def _corner(surface: pygame.Surface, x: int, y: int) -> tuple[int, int, int]:
    """The top-left pixel of a map tile's square (camera clamped to (0, 0) here)."""
    return tuple(surface.get_at((x * TILE_PX, y * TILE_PX)))[:3]


def test_render_draws_visible_tiles_and_skips_unseen():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()  # compute the player's FOV

    surface = _draw(runner)

    vx, vy = VISIBLE_FLOOR
    assert _corner(surface, vx, vy) == _game_map().tiles[vx][vy].bg  # visible tile drawn
    assert _corner(surface, *UNEXPLORED_CORNER) == UI_BLACK  # unseen tile skipped -> opaque black layer


def test_render_cache_reflects_terrain_change_on_reprocess():
    # RenderSystem caches the terrain layer and only redraws it when the map changes. A set_tile
    # bumps Map.revision, which must invalidate that cache so the same (persistent) instance shows
    # the new tile on its next pass -- not a stale one.
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    surface.fill(SENTINEL)
    runner.game_state.display_mode = DisplayMode.EXPLORING
    render_system = RenderSystem(surface, runner.asset_loader)
    render_system.process()  # builds the terrain cache

    vx, vy = VISIBLE_FLOOR
    recolored = (7, 9, 11)  # a bg no default tile uses
    game_map.set_tile(vx, vy, replace(game_map.tiles[vx][vy], bg=recolored))
    render_system.process()

    assert _corner(surface, vx, vy) == recolored


def test_render_dims_explored_but_unseen_tiles():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    game_map = _game_map()
    ux, uy = UNSEEN_TILE
    game_map.explored[ux, uy] = True

    surface = _draw(runner)

    full = game_map.tiles[ux][uy].bg
    dimmed = tuple(int(c * 0.3) for c in full)
    assert _corner(surface, ux, uy) == dimmed


@pytest.mark.parametrize('status', STATUS_TINT_PRIORITY)
def test_render_tints_entity_by_active_status(status):
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    esper.component_for_entity(runner.player, StatusEffects).active[status] = Effect(
        type=EffectType(status), duration=5
    )

    surface = _draw(runner)

    assert _corner(surface, px, py) == blend(UI_BLACK, EFFECT_COLORS[EffectType(status)], 0.5)


def test_render_tint_prefers_higher_priority_status_when_stacked():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    active = esper.component_for_entity(runner.player, StatusEffects).active
    # STUN outranks POISON in STATUS_TINT_PRIORITY, so its tint wins over both being active.
    active[StatusType.POISON] = Effect(type=EffectType.POISON, duration=5)
    active[StatusType.STUN] = Effect(type=EffectType.STUN, duration=5)

    surface = _draw(runner)

    assert _corner(surface, px, py) == blend(UI_BLACK, EFFECT_COLORS[EffectType.STUN], 0.5)


def test_render_leaves_unstatused_entity_untinted():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)

    surface = _draw(runner)

    # No status, so the sprite draws over the tile's own background, not a tint.
    epos = esper.component_for_entity(enemy, Position)
    assert _corner(surface, epos.x, epos.y) == _game_map().tiles[epos.x][epos.y].bg


# The modes that draw the world behind their overlay (the source of truth, so this can't drift).
RENDER_MODES = set(WORLD_VIEW_MODES)


@pytest.mark.parametrize('mode', [m for m in DisplayMode if m not in RENDER_MODES])
def test_render_noops_outside_render_modes(mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()

    surface = _draw(runner, mode)

    px, py = runner.player_pos
    assert _corner(surface, px, py) == SENTINEL


def test_render_noops_without_a_map():
    runner = HeadlessRunner(use_random_map=False)
    runner.tick()
    for ent, _map in esper.get_component(Map):
        esper.delete_entity(ent, immediate=True)

    surface = _draw(runner)

    px, py = runner.player_pos
    assert _corner(surface, px, py) == SENTINEL
