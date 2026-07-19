import esper
import pygame

from src.components import (
    Boss,
    Experience,
    Inventory,
    ItemType,
    Message,
    MessageLog,
    Modal,
    Momentum,
    Stats,
    StatusType,
)
from src.constants import (
    RGB,
    UI_FONT_PX,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_ORANGE,
    UI_PERIWINKLE,
    UI_RED,
    UI_RED_DARK,
    UI_SKY,
    UI_WHITE,
    UI_YELLOW,
)
from src.data_loaders import AssetLoader
from src.ecs_helpers import (
    get_display_name,
    get_player,
    get_player_component,
    get_singleton,
    get_status,
    try_get_singleton,
)
from src.render import hud_rect, map_viewport_rect
from src.states import WORLD_VIEW_MODES, GameState
from src.ui_draw import MENU_COL_W, MENU_ROW_H, bar, blit_segments, blit_text, cell, panel
from src.ui_helpers import compute_visible_slice, wrap_message


class ModalSystem(esper.Processor):
    """Draws an open Modal (NPC dialogue / notices): a centered box with the current page's
    wrapped text and a footer, pixel-native into the window Surface."""

    def __init__(self, surface: pygame.Surface, asset_loader: AssetLoader):
        self.surface = surface
        self.asset_loader = asset_loader

    @property
    def font(self) -> pygame.font.Font:
        return self.asset_loader.font(UI_FONT_PX)

    def process(self):
        for _ent, modal in esper.get_component(Modal):
            origin = panel(self.surface, self.font, modal.width, modal.height, modal.title)
            for i, line in enumerate(wrap_message([(modal.pages[modal.page], UI_WHITE)], modal.width - 4)):
                cx, cy = cell(origin, 2, 2 + i)
                blit_segments(self.surface, self.font, line, cx, cy + MENU_ROW_H // 2)  # extra top padding

            more = modal.page + 1 < len(modal.pages)
            footer = '(More - Press Enter)' if more else 'Press Enter to close'
            footer_x = origin[0] + (modal.width * MENU_COL_W - self.font.size(footer)[0]) // 2
            blit_text(self.surface, self.font, footer, footer_x, origin[1] + (modal.height - 2) * MENU_ROW_H, UI_GRAY)


class HUDSystem(esper.Processor):
    """Draws the bottom HUD bar (stats + message log) and a discovered boss's HP bar,
    pixel-native into the window Surface."""

    LINE_H = 22
    PAD = 10
    # Width of the stats column on the left of the HUD bar; the log fills the rest.
    STATS_W = 380
    BAR_W = 150
    BAR_H = 14
    # x-offset of a stat bar from its label — wider than the widest label ('HP: 300/300' ~137px)
    # so the numbers never run into the bar.
    LABEL_W = 150
    # y-offset of the bar within its row, centering it in the font's ascent (16px) so it lines up
    # with the digits (which sit in the ascent), not the full 20px em-box.
    BAR_Y_OFFSET = 1
    MSG_TEXT_PAD = 5  # breathing room between the message-log frame's top border and the first line
    BOSS_BAR_W = 360  # boss HP bar, centered across the top of the map viewport

    def __init__(self, surface: pygame.Surface, asset_loader: AssetLoader):
        self.surface = surface
        self.asset_loader = asset_loader

    @property
    def font(self) -> pygame.font.Font:
        return self.asset_loader.font(UI_FONT_PX)

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in WORLD_VIEW_MODES:
            return
        hud = hud_rect(self.surface)
        self._render_stats(hud, game_state.floor)
        self._render_message_log(hud)
        self._render_boss_bar()

    def _row_y(self, hud: pygame.Rect, row: int) -> int:
        return hud.y + self.PAD + row * self.LINE_H

    def _stat_bar(self, x: int, y: int, label: str, ratio: float, fill: RGB, track: RGB) -> None:
        blit_text(self.surface, self.font, label, x, y, UI_WHITE)
        bar(self.surface, x + self.LABEL_W, y + self.BAR_Y_OFFSET, self.BAR_W, self.BAR_H, ratio, fill, track)

    def _render_stats(self, hud: pygame.Rect, floor: int) -> None:
        x = hud.x + self.PAD
        stats = get_player_component(Stats)
        if stats is not None:
            ratio = stats.hp / stats.max_hp if stats.max_hp else 0.0
            self._stat_bar(x, self._row_y(hud, 0), f'HP: {stats.hp}/{stats.max_hp}', ratio, UI_RED, UI_RED_DARK)

        exp = get_player_component(Experience)
        if exp is not None:
            ratio = exp.xp / exp.next_level_xp if exp.next_level_xp else 0.0
            self._stat_bar(x, self._row_y(hud, 1), f'Lv {exp.level}', ratio, UI_PERIWINKLE, UI_GRAY_DARK)

        blit_text(self.surface, self.font, f'Floor: {floor}', x, self._row_y(hud, 2), UI_WHITE)
        inv = try_get_singleton(Inventory)
        if inv is not None:
            gold_text = f'Gold: {inv.items.get(ItemType.GOLD, 0)}'
            blit_text(self.surface, self.font, gold_text, x + self.LABEL_W, self._row_y(hud, 2), UI_YELLOW)

        player = get_player()
        shield = get_status(player, StatusType.SHIELD) if player is not None else None
        if shield:
            blit_text(self.surface, self.font, f'Shield: {shield.power}', x, self._row_y(hud, 3), UI_SKY)

        momentum = get_player_component(Momentum)
        if momentum is not None and momentum.stacks > 0:
            combo = f'Combo x{momentum.stacks}'
            blit_text(self.surface, self.font, combo, x + self.LABEL_W, self._row_y(hud, 3), UI_ORANGE)

    def _render_message_log(self, hud: pygame.Rect) -> None:
        log = try_get_singleton(MessageLog)
        if log is None:
            return
        log_x = hud.x + self.STATS_W
        log_w = hud.width - self.STATS_W - self.PAD
        pygame.draw.rect(
            self.surface, UI_GRAY_DARK, (log_x, hud.y + self.LINE_H, log_w, hud.height - self.LINE_H - 2), width=1
        )
        blit_text(self.surface, self.font, 'Messages', log_x + self.PAD, hud.y, UI_WHITE)

        # Wrap by an approximate character budget (the font isn't monospace, so estimate off 'M').
        char_px = max(1, self.font.size('M')[0])
        usable_chars = max(1, (log_w - 2 * self.PAD) // char_px)
        all_lines: list[Message] = []
        for msg in log.messages:
            all_lines.extend(wrap_message(msg, usable_chars))

        text_top = hud.y + self.LINE_H + self.MSG_TEXT_PAD
        visible_rows = max(1, (hud.height - self.LINE_H - self.MSG_TEXT_PAD - self.PAD) // self.LINE_H)
        log.scroll_index, start_idx, end_idx = compute_visible_slice(len(all_lines), log.scroll_index, visible_rows)
        for i, line in enumerate(all_lines[start_idx:end_idx]):
            blit_segments(self.surface, self.font, line, log_x + self.PAD, text_top + i * self.LINE_H)

    def _render_boss_bar(self) -> None:
        """A living, discovered boss's HP bar, centered across the top of the map viewport."""
        for ent, (boss, stats) in esper.get_components(Boss, Stats):
            if stats.hp <= 0 or not boss.discovered:
                continue
            vx, _vy, vw, _vh = map_viewport_rect(self.surface)
            bar_w = min(self.BOSS_BAR_W, max(0, vw - 8))
            if bar_w <= 0:
                return
            bar_x = vx + (vw - bar_w) // 2
            label = f'{get_display_name(ent)}  {stats.hp}/{stats.max_hp}'
            label_w = self.font.size(label)[0]
            blit_text(self.surface, self.font, label, vx + (vw - label_w) // 2, self.PAD, UI_WHITE)
            ratio = stats.hp / stats.max_hp if stats.max_hp else 0.0
            bar(self.surface, bar_x, self.PAD + self.LINE_H, bar_w, self.BAR_H, ratio, UI_RED, UI_RED_DARK)
            return  # only one boss bar at a time
