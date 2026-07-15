import esper

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
    UI_BLACK,
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
from src.ecs_helpers import (
    get_display_name,
    get_player,
    get_player_component,
    get_singleton,
    get_status,
    try_get_singleton,
)
from src.layout import LayoutProcessor, Rect
from src.states import WORLD_VIEW_MODES, GameState
from src.ui_helpers import compute_visible_slice, draw_centered_frame, draw_titled_frame, wrap_message


class ModalSystem(LayoutProcessor):
    def process(self):
        for _ent, modal in esper.get_component(Modal):
            # Center the modal based on its own dimensions
            x, y = draw_centered_frame(self.console, modal.width, modal.height, title=modal.title)

            # Current page of text
            self.console.print(
                x=x + 2,
                y=y + 2,
                width=modal.width - 4,
                height=modal.height - 4,
                text=modal.pages[modal.page],
                fg=UI_WHITE,
            )

            more = modal.page + 1 < len(modal.pages)
            footer = '(More - Press Enter)' if more else 'Press Enter to close'
            self.console.print(
                x + modal.width // 2 - len(footer) // 2,
                y + modal.height - 2,
                footer,
                fg=UI_GRAY,
            )


class HUDSystem(LayoutProcessor):
    # Stat bars share a width and right-align to the same column, so HP and XP line up.
    BAR_WIDTH = 16
    BAR_RIGHT_MARGIN = 2
    # Width of the stats column on the left of the HUD bar; the log fills the rest.
    HUD_STATS_WIDTH = 34
    # The boss HP bar spans the top of the map viewport, centered and capped at this width.
    BOSS_BAR_WIDTH = 40

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in WORLD_VIEW_MODES:
            return

        # The HUD bar splits into a stats column and a message log.
        stats_zone, log_zone = self.layout.hud.split_left(self.HUD_STATS_WIDTH)
        self.render_hp_bar(stats_zone)
        self.render_xp_bar(stats_zone)
        self.render_shield(stats_zone)
        self.render_momentum(stats_zone)
        self.render_floor_info(stats_zone, game_state.floor)
        self.render_gold(stats_zone)
        self.render_message_log(log_zone)
        self.render_boss_bar(self.layout.map_viewport)

    def _draw_stat_bar(self, zone: Rect, row: int, label: str, ratio: float, fill: RGB, track: RGB):
        """Draw a labeled bar on `row` of the stats column: label at the left, the bar
        right-aligned so every bar shares the same right edge."""
        y = zone.y + row
        self.console.print(zone.x + 2, y, label, fg=UI_WHITE)
        bar_x = zone.x + zone.width - self.BAR_RIGHT_MARGIN - self.BAR_WIDTH
        self.console.draw_rect(bar_x, y, self.BAR_WIDTH, 1, ch=ord('█'), fg=track)
        filled_width = int(ratio * self.BAR_WIDTH)
        if filled_width > 0:
            self.console.draw_rect(bar_x, y, filled_width, 1, ch=ord('█'), fg=fill)

    def render_hp_bar(self, zone: Rect):
        stats = get_player_component(Stats)
        if stats is None:
            return
        self._draw_stat_bar(zone, 1, f'HP: {stats.hp}/{stats.max_hp}', stats.hp / stats.max_hp, UI_RED, UI_RED_DARK)

    def render_boss_bar(self, zone: Rect):
        """Show a living floor boss's HP bar across the top of the map viewport, so the fight's
        progress reads at a glance. Draws nothing when no boss is alive."""
        for ent, (_boss, stats) in esper.get_components(Boss, Stats):
            if stats.hp <= 0:
                continue
            bar_width = min(self.BOSS_BAR_WIDTH, max(0, zone.width - 4))
            if bar_width <= 0:
                return
            bar_x = zone.x + (zone.width - bar_width) // 2
            label = f'{get_display_name(ent)}  {stats.hp}/{stats.max_hp}'
            self.console.print(zone.x + (zone.width - len(label)) // 2, zone.y, label, fg=UI_WHITE)
            self.console.draw_rect(bar_x, zone.y + 1, bar_width, 1, ch=ord('█'), fg=UI_RED_DARK)
            filled = int((stats.hp / stats.max_hp) * bar_width) if stats.max_hp else 0
            if filled > 0:
                self.console.draw_rect(bar_x, zone.y + 1, filled, 1, ch=ord('█'), fg=UI_RED)
            return  # only one boss bar at a time

    def render_xp_bar(self, zone: Rect):
        exp = get_player_component(Experience)
        if exp is None:
            return
        self._draw_stat_bar(zone, 3, f'Lv {exp.level}', exp.xp / exp.next_level_xp, UI_PERIWINKLE, UI_GRAY_DARK)

    def render_shield(self, zone: Rect):
        """Show the player's active shield (its remaining damage reduction per hit)."""
        player = get_player()
        shield = get_status(player, StatusType.SHIELD) if player is not None else None
        if shield:
            self.console.print(zone.x + 2, zone.y + 2, f'Shield: {shield.power}', fg=UI_SKY)

    def render_momentum(self, zone: Rect):
        """A row of pips showing current combo stacks, brightening as the chain grows. Hidden
        when momentum is zero so it reads as a reward that lights up under aggression."""
        momentum = get_player_component(Momentum)
        if momentum is None or momentum.stacks == 0:
            return
        label = f'Combo x{momentum.stacks}'
        self.console.print(zone.x + 2, zone.y + 6, label, fg=UI_ORANGE)
        pips = '●' * momentum.stacks + '·' * (Momentum.MAX_STACKS - momentum.stacks)
        self.console.print(zone.x + 2 + len(label) + 1, zone.y + 6, pips, fg=UI_ORANGE)

    def render_floor_info(self, zone: Rect, floor: int):
        self.console.print(zone.x + 2, zone.y + 5, f'Floor: {floor}', fg=UI_WHITE)

    def render_gold(self, zone: Rect):
        inv = try_get_singleton(Inventory)
        if not inv:
            return
        gold = inv.items.get(ItemType.GOLD, 0)
        self.console.print(zone.x + 14, zone.y + 5, f'Gold: {gold}', fg=UI_YELLOW)

    def render_message_log(self, zone: Rect):
        log = try_get_singleton(MessageLog)
        if not log:
            return

        draw_titled_frame(
            self.console,
            zone.x,
            zone.y,
            zone.width,
            zone.height,
            title='Messages',
            fg=UI_WHITE,
            bg=UI_BLACK,
        )

        usable_width = zone.width - 4
        all_lines: list[Message] = []
        for msg in log.messages:
            all_lines.extend(wrap_message(msg, usable_width))

        visible_height = zone.height - 2

        # Resolve the visible slice and write back the clamped scroll position
        log.scroll_index, start_idx, end_idx = compute_visible_slice(len(all_lines), log.scroll_index, visible_height)
        visible_lines = all_lines[start_idx:end_idx]

        for i, line in enumerate(visible_lines):
            msg_x = zone.x + 2
            msg_y = zone.y + 1 + i
            for text, color in line:
                self.console.print(x=msg_x, y=msg_y, text=text, fg=color)
                msg_x += len(text)
