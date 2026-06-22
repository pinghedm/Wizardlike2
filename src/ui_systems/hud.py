import esper

from src.components import (
    Inventory,
    ItemType,
    Message,
    MessageLog,
    Modal,
    Stats,
    StatusType,
)
from src.constants import (
    UI_BLACK,
    UI_GRAY,
    UI_RED,
    UI_RED_DARK,
    UI_SKY,
    UI_WHITE,
    UI_YELLOW,
)
from src.ecs_helpers import get_player, get_player_component, get_singleton, get_status, try_get_singleton
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
    HP_BAR_WIDTH = 20
    # Width of the stats column on the left of the HUD bar; the log fills the rest.
    HUD_STATS_WIDTH = 34

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in WORLD_VIEW_MODES:
            return

        # The HUD bar splits into a stats column and a message log.
        stats_zone, log_zone = self.layout.hud.split_left(self.HUD_STATS_WIDTH)
        self.render_hp_bar(stats_zone)
        self.render_shield(stats_zone)
        self.render_floor_info(stats_zone, game_state.floor)
        self.render_gold(stats_zone)
        self.render_message_log(log_zone)

    def render_hp_bar(self, zone: Rect):
        stats = get_player_component(Stats)
        if stats is None:
            return

        hp_label_start_x, hp_label_y = zone.x + 2, zone.y + 1

        hp_text = f'HP: {stats.hp}/{stats.max_hp}'
        self.console.print(hp_label_start_x, hp_label_y, hp_text, fg=UI_WHITE)

        hp_bar_start_x = hp_label_start_x + len(hp_text) + 1
        ratio = stats.hp / stats.max_hp
        filled_width = int(ratio * self.HP_BAR_WIDTH)

        self.console.draw_rect(hp_bar_start_x, hp_label_y, self.HP_BAR_WIDTH, 1, ch=ord('█'), fg=UI_RED_DARK)
        if filled_width > 0:
            self.console.draw_rect(hp_bar_start_x, hp_label_y, filled_width, 1, ch=ord('█'), fg=UI_RED)

    def render_shield(self, zone: Rect):
        """Show the player's active shield (its remaining damage reduction per hit)."""
        player = get_player()
        shield = get_status(player, StatusType.SHIELD) if player is not None else None
        if shield:
            self.console.print(zone.x + 2, zone.y + 2, f'Shield: {shield.power}', fg=UI_SKY)

    def render_floor_info(self, zone: Rect, floor: int):
        self.console.print(zone.x + 2, zone.y + 3, f'Floor: {floor}', fg=UI_WHITE)

    def render_gold(self, zone: Rect):
        inv = try_get_singleton(Inventory)
        if not inv:
            return
        gold = inv.items.get(ItemType.GOLD, 0)
        self.console.print(zone.x + 14, zone.y + 3, f'Gold: {gold}', fg=UI_YELLOW)

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
