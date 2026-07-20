"""HUDSystem draws pixel-native into the window Surface, so these sample pixels rather
than reading console text. Bar colors and the log frame are what's meaningfully testable;
the label/log *text* content isn't (glyphs can't be read back), and its wrapping/slicing
logic is covered by test_ui_helpers.py.
"""

import esper
import pygame

from src.components import Boss, MessageLog, Position, Renderable, Stats
from src.constants import UI_GRAY_DARK, UI_RED, UI_RED_DARK, WINDOW_HEIGHT, WINDOW_WIDTH
from src.render import HUD_PX, map_viewport_rect
from src.states import DisplayMode
from src.ui_systems import HUDSystem
from tests.headless_runner import HeadlessRunner

SENTINEL = (255, 0, 255)  # a fill no HUD element uses, so undrawn pixels read back as this
HUD_TOP = WINDOW_HEIGHT - HUD_PX
# The HP bar sits at HUD row 0: label at PAD, bar at PAD + LABEL_W, BAR_Y_OFFSET down and BAR_H tall.
BAR_X = HUDSystem.PAD + HUDSystem.LABEL_W
BAR_MID_Y = HUD_TOP + HUDSystem.PAD + HUDSystem.BAR_Y_OFFSET + HUDSystem.BAR_H // 2


def _draw_hud(runner: HeadlessRunner, mode: DisplayMode = DisplayMode.EXPLORING) -> pygame.Surface:
    surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    surface.fill(SENTINEL)
    runner.game_state.display_mode = mode
    HUDSystem(surface, runner.asset_loader).process()
    return surface


def _px(surface: pygame.Surface, x: int, y: int) -> tuple[int, int, int]:
    return tuple(surface.get_at((x, y)))[:3]


def test_hud_not_rendered_in_menu_mode():
    runner = HeadlessRunner(use_random_map=False)
    surface = _draw_hud(runner, DisplayMode.MENU)
    assert _px(surface, BAR_X + 2, BAR_MID_Y) == SENTINEL  # nothing drawn


def test_hp_bar_full_is_all_red():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp, stats.max_hp = 100, 100

    surface = _draw_hud(runner)
    assert _px(surface, BAR_X + 2, BAR_MID_Y) == UI_RED
    assert _px(surface, BAR_X + HUDSystem.BAR_W - 2, BAR_MID_Y) == UI_RED  # full: red end to end


def test_hp_bar_partial_splits_filled_and_track():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp, stats.max_hp = 10, 100  # ratio 0.1

    surface = _draw_hud(runner)
    assert _px(surface, BAR_X + 2, BAR_MID_Y) == UI_RED  # filled head
    assert _px(surface, BAR_X + HUDSystem.BAR_W - 2, BAR_MID_Y) == UI_RED_DARK  # empty tail is the track


def test_hp_bar_zero_is_all_track():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp, stats.max_hp = 0, 100

    surface = _draw_hud(runner)
    assert _px(surface, BAR_X + 2, BAR_MID_Y) == UI_RED_DARK


def test_message_log_frame_is_drawn():
    runner = HeadlessRunner(use_random_map=False)
    esper.get_component(MessageLog)[0][1].add_simple_message('hello')

    surface = _draw_hud(runner)
    # The log panel's 1px border is drawn in UI_GRAY_DARK at the top-left of the log column.
    assert _px(surface, HUDSystem.STATS_W, HUD_TOP + HUDSystem.LINE_H) == UI_GRAY_DARK


def test_message_log_wrap_cache_reused_until_a_message_arrives():
    # The log's per-word wrap is cached across frames and rebuilt only when the message count
    # (or width) changes, so a fresh message must show up on the next pass -- not a stale cache.
    runner = HeadlessRunner(use_random_map=False)
    log = esper.get_component(MessageLog)[0][1]
    log.add_simple_message('first')
    surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    runner.game_state.display_mode = DisplayMode.EXPLORING
    hud = HUDSystem(surface, runner.asset_loader)

    hud.process()
    sig_after_first = hud._log_sig
    hud.process()
    assert hud._log_sig == sig_after_first  # no change -> cache reused, not rebuilt

    log.add_simple_message('second')
    hud.process()
    assert hud._log_sig != sig_after_first  # new message invalidates the cache
    assert len(hud._log_lines) == 2  # both messages now wrapped in


# --- boss HP bar (centered across the top of the map viewport) ----------------


def _spawn_boss(hp: int, max_hp: int, discovered: bool) -> int:
    return esper.create_entity(
        Boss(abilities=[], discovered=discovered),
        Stats(hp=hp, max_hp=max_hp),
        Renderable(sprite_id='Overlord'),
        Position(4, 4),
    )


def _boss_bar_probe(surface: pygame.Surface) -> tuple[int, int, int]:
    """(left-fill x, right-tail x, mid y) of the boss bar drawn for this surface."""
    vx, _vy, vw, _vh = map_viewport_rect(surface)
    bar_w = min(HUDSystem.BOSS_BAR_W, max(0, vw - 8))
    bar_x = vx + (vw - bar_w) // 2
    y = HUDSystem.PAD + HUDSystem.LINE_H + HUDSystem.BAR_H // 2
    return bar_x + 2, bar_x + bar_w - 2, y


def test_boss_bar_full_hp_is_all_red():
    runner = HeadlessRunner(use_random_map=False)
    _spawn_boss(100, 100, discovered=True)

    surface = _draw_hud(runner)
    left_x, right_x, y = _boss_bar_probe(surface)
    assert _px(surface, left_x, y) == UI_RED
    assert _px(surface, right_x, y) == UI_RED  # full: red end to end


def test_boss_bar_partial_hp_splits_fill_and_track():
    runner = HeadlessRunner(use_random_map=False)
    _spawn_boss(10, 100, discovered=True)  # ratio 0.1

    surface = _draw_hud(runner)
    left_x, right_x, y = _boss_bar_probe(surface)
    assert _px(surface, left_x, y) == UI_RED  # filled head
    assert _px(surface, right_x, y) == UI_RED_DARK  # empty tail is the track


def test_boss_bar_hidden_until_discovered():
    runner = HeadlessRunner(use_random_map=False)
    _spawn_boss(100, 100, discovered=False)

    surface = _draw_hud(runner)
    left_x, _right_x, y = _boss_bar_probe(surface)
    assert _px(surface, left_x, y) == SENTINEL  # undiscovered boss draws no bar
