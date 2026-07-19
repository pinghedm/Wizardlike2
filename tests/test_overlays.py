"""TargetingOverlaySystem draws pixel-native into the window Surface (the EffectOverlaySystem's
behavior — projectile/particle/flash aging — is covered by test_effects.py). A 20x20 map with the
player centered clamps the camera to (0, 0), so map tile (x, y) is at pixel (x*TILE_PX, y*TILE_PX).
"""

import esper
import pygame

from src.components import TargetingReticle, UIState
from src.constants import TILE_PX, UI_NAVY, UI_YELLOW, WINDOW_HEIGHT, WINDOW_WIDTH
from src.states import DisplayMode
from src.ui_systems import TargetingOverlaySystem
from tests.headless_runner import HeadlessRunner

SENTINEL = (255, 0, 255)  # a fill the overlay never uses, so undrawn pixels read back as this


def _draw_targeting(runner: HeadlessRunner) -> pygame.Surface:
    surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    surface.fill(SENTINEL)
    TargetingOverlaySystem(surface, runner.asset_loader).process()
    return surface


def _px(surface: pygame.Surface, x: int, y: int) -> tuple[int, int, int]:
    return tuple(surface.get_at((x, y)))[:3]


def test_targeting_reticle_outlines_the_target_without_covering_it():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING
    px, py = runner.player_pos
    rx, ry = px + 2, py
    esper.create_entity(TargetingReticle(x=rx, y=ry, radius=1))

    surface = _draw_targeting(runner)
    tx, ty = rx * TILE_PX, ry * TILE_PX
    assert _px(surface, tx, ty) == UI_YELLOW  # the 2px outline is on the tile border
    assert _px(surface, tx + TILE_PX // 2, ty + TILE_PX // 2) == SENTINEL  # interior left uncovered


def test_targeting_reticle_shades_the_aoe_edge_not_the_interior():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING
    px, py = runner.player_pos
    rx, ry = px + 3, py
    esper.create_entity(TargetingReticle(x=rx, y=ry, radius=2))

    surface = _draw_targeting(runner)
    rim_x, rim_y = rx * TILE_PX, (ry + 2) * TILE_PX  # a tile on the radius rim
    int_x, int_y = rx * TILE_PX, ry * TILE_PX  # the target's own tile (interior)
    assert _px(surface, rim_x + 2, rim_y + 2) != SENTINEL  # rim is shaded...
    assert _px(surface, int_x + TILE_PX // 2, int_y + TILE_PX // 2) == SENTINEL  # ...interior isn't


def test_targeting_label_strip_is_drawn_for_the_aimed_spell():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING
    esper.get_component(UIState)[0][1].active_targeting_spell_id = 'test_wand'
    px, py = runner.player_pos
    esper.create_entity(TargetingReticle(x=px + 1, y=py, radius=0))

    surface = _draw_targeting(runner)
    assert _px(surface, 1, 1) == UI_NAVY  # the navy label strip at the top-left of the viewport


def test_targeting_overlay_draws_nothing_without_a_reticle():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING  # in targeting mode, but no reticle exists

    surface = _draw_targeting(runner)
    assert _px(surface, 100, 100) == SENTINEL
