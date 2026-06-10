from collections import Counter
from collections.abc import Sequence

import esper

from src import persistence
from src.components import (
    Inventory,
    ItemType,
    KnownRecipes,
    Message,
    RunStats,
    Settings,
    Shopkeeper,
    SpellInventory,
    SpellType,
    UIState,
)
from src.constants import (
    UI_CYAN_DARK,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_RED,
    UI_SKY,
    UI_WHITE,
    UI_YELLOW,
)
from src.ecs_helpers import get_singleton, try_get_singleton
from src.input_handlers import (
    QUICK_CAST_FACE_BUTTONS,
    available_spells,
    connected_controller_name,
    controller_binding_label,
)
from src.layout import LayoutProcessor
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    CraftingView,
    DisplayMode,
    GameState,
    MenuOption,
)
from src.systems import (
    can_craft_known_spell,
    get_spell_config,
    is_game_active,
    is_reagent,
)
from src.ui_helpers import (
    draw_centered_frame,
    draw_scroll_indicators,
    format_recipe,
    format_spell_effects,
    scroll_window,
    wrap_message,
)


def _quick_cast_label(slot: int, has_controller: bool) -> str:
    """The quick-cast prefix for a spell row: its number key, plus the controller face
    button (when a pad is connected) for the first four slots; blank past slot 9."""
    if slot >= 9:
        return '   '
    if has_controller and slot < len(QUICK_CAST_FACE_BUTTONS):
        return f'{slot + 1}/{QUICK_CAST_FACE_BUTTONS[slot].name}) '
    return f'{slot + 1}) '


class MenuSystem(LayoutProcessor):
    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode == DisplayMode.MENU:
            self.render_main_menu()
        elif game_state.display_mode == DisplayMode.COMBINING:
            self.render_combining_menu()
        elif game_state.display_mode == DisplayMode.CASTING:
            self.render_casting_menu()
        elif game_state.display_mode == DisplayMode.SHOPPING:
            self.render_shop_menu()
        elif game_state.display_mode == DisplayMode.SETTINGS:
            self.render_settings_menu()
        elif game_state.display_mode == DisplayMode.GAME_OVER:
            self.render_game_over()

    def render_main_menu(self):
        ui_state = get_singleton(UIState)
        game_active = is_game_active()
        options = PAUSE_MENU_OPTIONS if game_active else TITLE_MENU_OPTIONS
        title = 'Paused' if game_active else 'WizardLike'
        cursor = ui_state.main_menu_cursor % len(options)

        x, y = draw_centered_frame(
            self.console,
            24,
            len(options) + 4,
            title=title,
        )

        can_load = persistence.has_save()

        for i, option in enumerate(options):
            color = UI_YELLOW if i == cursor else UI_WHITE
            if option in (MenuOption.CONTINUE, MenuOption.LOAD) and not can_load:
                color = UI_GRAY_DARK

            # Anchor options inside the frame (border at x/y, title on row y).
            self.console.print(
                x + 3,
                y + 2 + i,
                f'{"> " if i == cursor else "  "}{option}',
                fg=color,
            )

    def render_combining_menu(self):
        ui_state = get_singleton(UIState)
        player_inv = try_get_singleton(Inventory)
        player_recipes = try_get_singleton(KnownRecipes)
        player_spell_inv = try_get_singleton(SpellInventory)

        if player_inv is None or player_recipes is None or player_spell_inv is None:
            return

        width, height = 72, 24
        x, y = draw_centered_frame(self.console, width, height, title='Crafting')

        self._render_crafting_tabs(x + 2, y + 1, ui_state.crafting_view)

        if ui_state.crafting_view == CraftingView.SPELLBOOK:
            self._render_spellbook(x, y, width, height, ui_state, player_recipes, player_spell_inv, player_inv)
            footer = 'Tab: Experiment | Up/Down: Select | Enter: Craft | Esc: Close'
        else:
            self._render_experiment(x, y, width, height, ui_state, player_inv)
            footer = 'Tab: Spellbook | L/R: Select | Enter: Combine | Esc: Close'

        self.console.print(x + 2, y + height - 2, footer, fg=UI_GRAY)

    def _render_crafting_tabs(self, tx: int, ty: int, view: CraftingView):
        self.console.print(tx, ty, 'Experiment', fg=UI_YELLOW if view == CraftingView.EXPERIMENT else UI_GRAY_DARK)
        self.console.print(tx + 13, ty, 'Spellbook', fg=UI_YELLOW if view == CraftingView.SPELLBOOK else UI_GRAY_DARK)

    def _render_experiment(self, x: int, y: int, width: int, height: int, ui_state: UIState, player_inv: Inventory):
        self.console.print(x + 2, y + 3, 'Combine ingredients to discover spells:', fg=UI_SKY)

        inv_list = sorted(i for i in player_inv.items if is_reagent(i))
        if not inv_list:
            self.console.print(x + 2, y + 5, 'No ingredients to combine.', fg=UI_GRAY_DARK)
            return

        item_top = y + 5
        cursor = ui_state.crafting_cursor % len(inv_list)
        visible = height - 7  # rows between the list top and the footer
        start, end = scroll_window(len(inv_list), cursor, visible)
        for row_i, itype in enumerate(inv_list[start:end]):
            i = start + row_i
            selected = i == cursor
            count = player_inv.items[itype]
            chosen = ui_state.selected_for_crafting.get(itype, 0)
            marker = '> ' if selected else '  '
            self.console.print(
                x + 2,
                item_top + row_i,
                f'{marker}{itype.name}: {count} (Selected: {chosen})',
                fg=UI_WHITE if selected else UI_GRAY_DARK,
            )
        draw_scroll_indicators(
            self.console, x + width - 2, item_top, item_top + (end - start) - 1, start, end, len(inv_list), UI_YELLOW
        )

    def _render_spellbook(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        ui_state: UIState,
        player_recipes: KnownRecipes,
        player_spell_inv: SpellInventory,
        player_inv: Inventory,
    ):
        known = sorted(player_recipes.recipes.keys(), key=lambda s: s.name)
        list_x = x + 2
        detail_x = x + 26
        list_top = y + 4

        if not known:
            self.console.print(list_x, list_top, 'No recipes discovered yet.', fg=UI_GRAY)
            self.console.print(list_x, y + 6, 'Find them in the Experiment tab.', fg=UI_GRAY_DARK)
            return

        cursor = ui_state.spellbook_cursor % len(known)
        visible = height - 6  # rows between the list top and the footer
        start, end = scroll_window(len(known), cursor, visible)
        for row_i, stype in enumerate(known[start:end]):
            i = start + row_i
            # Spells with no affordable recipe are dimmed.
            craftable = can_craft_known_spell(stype)
            charges = player_spell_inv.spells.get(stype, 0)
            if i == cursor:
                color = UI_YELLOW if craftable else UI_GRAY
            else:
                color = UI_WHITE if craftable else UI_GRAY_DARK
            marker = '> ' if i == cursor else '  '
            self.console.print(list_x, list_top + row_i, f'{marker}{stype.name} ({charges})', fg=color)

        # The indicators sit in the gap column between the list and the detail panel.
        draw_scroll_indicators(
            self.console, detail_x - 2, list_top, list_top + (end - start) - 1, start, end, len(known), UI_YELLOW
        )
        detail_bottom = y + height - 3  # last row above the footer
        self._render_spell_detail(
            detail_x, list_top, width - 28, detail_bottom, known[cursor], player_recipes, player_inv
        )

    def _render_spell_detail(
        self,
        dx: int,
        dy: int,
        detail_width: int,
        bottom: int,
        stype: SpellType,
        player_recipes: KnownRecipes,
        player_inv: Inventory,
    ):
        s_conf = get_spell_config(stype.value)
        if not s_conf:
            return

        row = dy
        self.console.print(dx, row, s_conf.get('name', stype.name), fg=UI_SKY)
        row += 1

        description = s_conf.get('description')
        if description:
            for line in wrap_message([(description, UI_GRAY)], detail_width):
                self._print_segments(dx, row, line)
                row += 1
        row += 1

        self.console.print(dx, row, f'Radius {s_conf.get("radius", 0)}', fg=UI_WHITE)
        row += 1
        self.console.print(dx, row, format_spell_effects(s_conf.get('effects', [])), fg=UI_WHITE)
        row += 2

        self.console.print(dx, row, 'Recipes:', fg=UI_CYAN_DARK)
        row += 1
        charges_by_combo = {r['ingredients']: r['charges'] for r in s_conf.get('recipes', [])}
        for combo in sorted(player_recipes.recipes[stype], key=len):
            affordable = all(player_inv.items.get(itype, 0) >= count for itype, count in Counter(combo).items())
            text = f'{format_recipe(combo)}  (+{charges_by_combo.get(combo, 0)})'
            for line in wrap_message([(text, UI_WHITE if affordable else UI_GRAY_DARK)], detail_width):
                if row > bottom:
                    # A '...' on the last row signals the recipe list ran past the box.
                    self.console.print(dx, bottom, '...', fg=UI_GRAY_DARK)
                    return
                self._print_segments(dx, row, line)
                row += 1

    def _print_segments(self, x: int, y: int, segments: Message):
        cx = x
        for text, color in segments:
            self.console.print(cx, y, text, fg=color)
            cx += len(text)

    def render_casting_menu(self):
        ui_state = get_singleton(UIState)
        player_spell_inv = try_get_singleton(SpellInventory)
        if not player_spell_inv:
            return

        width = 68
        height = 16  # one row of padding between the last (double-spaced) spell and the footer
        x, y = draw_centered_frame(self.console, width, height, title='Select Spell to Cast')

        spells = available_spells()

        if not spells:
            self.console.print(
                x + width // 2 - 10,
                y + height // 2,
                'No spells with charges!',
                fg=UI_RED,
            )
        else:
            has_controller = connected_controller_name() is not None
            content_top = y + 2
            cursor = ui_state.casting_cursor % len(spells)
            visible = (height - 3) // 2  # spell rows are double-spaced above the footer
            start, end = scroll_window(len(spells), cursor, visible)
            for row_i, stype in enumerate(spells[start:end]):
                i = start + row_i
                color = UI_YELLOW if i == cursor else UI_WHITE

                s_conf = get_spell_config(stype.value) or {}
                charges = player_spell_inv.spells.get(stype, 0)
                info = f' (Radius: {s_conf.get("radius", 0)})'

                marker = '> ' if i == cursor else '  '
                text = f'{marker}{_quick_cast_label(i, has_controller)}{stype.name}: {charges} charges{info}'
                self.console.print(x + 2, content_top + (row_i * 2), text, fg=color)
            draw_scroll_indicators(
                self.console,
                x + width - 2,
                content_top,
                content_top + (end - start - 1) * 2,
                start,
                end,
                len(spells),
                UI_YELLOW,
            )

        self.console.print(
            x + 2,
            y + height - 2,
            'Arrows: Select | 1-9: Quick-cast | Enter: Target | S/Esc: Cancel',
            fg=UI_GRAY,
        )

    def render_shop_menu(self):
        ui_state = get_singleton(UIState)
        shopkeepers = esper.get_component(Shopkeeper)
        player_inv = try_get_singleton(Inventory)
        if not shopkeepers or not player_inv:
            return
        offers = shopkeepers[0][1].offers
        gold = player_inv.items.get(ItemType.GOLD, 0)

        width, height = 58, 14
        x, y = draw_centered_frame(self.console, width, height, title='Shop')
        self.console.print(x + 2, y + 1, f'Gold: {gold}', fg=UI_YELLOW)

        if not offers:
            self.console.print(x + 2, y + 3, 'Sold out.', fg=UI_GRAY_DARK)
        else:
            offer_top = y + 3
            cursor = ui_state.shop_cursor % len(offers)
            visible = height - 5  # rows between the offers top and the footer
            start, end = scroll_window(len(offers), cursor, visible)
            for row_i, offer in enumerate(offers[start:end]):
                i = start + row_i
                selected = i == cursor
                affordable = gold >= offer.price
                color = (UI_YELLOW if selected else UI_WHITE) if affordable else UI_GRAY_DARK
                marker = '> ' if selected else '  '
                row_text = f'{marker}{offer.label:<30}{offer.price:>4} G'
                self.console.print(x + 2, offer_top + row_i, row_text, fg=color)
                if selected:
                    qty = ui_state.shop_quantity
                    detail = f'x{qty} ({offer.price * qty} G)'
                    self.console.print(x + 2 + len(row_text) + 2, offer_top + row_i, detail, fg=color)
            draw_scroll_indicators(
                self.console,
                x + width - 2,
                offer_top,
                offer_top + (end - start) - 1,
                start,
                end,
                len(offers),
                UI_YELLOW,
            )

        self.console.print(x + 2, y + height - 2, 'L/R: Qty | Enter: Buy | Esc: Leave', fg=UI_GRAY)

    # Settings table column offsets from the frame's inner-left edge.
    SETTINGS_ACTION_COL = 2
    SETTINGS_KEY_COL = 20
    SETTINGS_CONTROLLER_COL = 40

    def render_settings_menu(self):
        ui_state = get_singleton(UIState)
        settings = try_get_singleton(Settings)
        if not settings:
            return

        keybindings = settings.keybindings
        actions = list(keybindings.bindings.keys())
        controller_name = connected_controller_name()
        has_controller = controller_name is not None

        width = 70
        # +2 rows for the post-cast toggle and the blank line under it.
        height = len(actions) + (10 if has_controller else 8)
        x, y = draw_centered_frame(self.console, width, height, title='Settings')

        self.console.print(x + 2, y + 1, f'Controller: {controller_name or "none detected"}', fg=UI_SKY)
        if has_controller:
            self.console.print(x + 2, y + 2, f'Last input: {ui_state.last_controller_input or "-"}', fg=UI_GRAY)

        # Row 0 of the selectable list: the post-cast behavior toggle.
        toggle_row = y + (4 if has_controller else 3)
        toggle_selected = ui_state.settings_cursor == 0
        toggle_color = UI_YELLOW if toggle_selected else UI_WHITE
        marker = '> ' if toggle_selected else '  '
        self.console.print(x + self.SETTINGS_ACTION_COL, toggle_row, f'{marker}After casting', fg=toggle_color)
        self.console.print(x + self.SETTINGS_KEY_COL, toggle_row, f'< {settings.post_cast.name} >', fg=toggle_color)

        header_row = toggle_row + 2
        self.console.print(x + self.SETTINGS_ACTION_COL, header_row, 'Action', fg=UI_CYAN_DARK)
        self.console.print(x + self.SETTINGS_KEY_COL, header_row, 'Keyboard', fg=UI_CYAN_DARK)
        if has_controller:
            self.console.print(x + self.SETTINGS_CONTROLLER_COL, header_row, 'Controller', fg=UI_CYAN_DARK)

        for i, action in enumerate(actions):
            # Keybindings occupy cursor rows 1.. (row 0 is the toggle above).
            selected = ui_state.settings_cursor == i + 1
            color = UI_YELLOW if selected else UI_WHITE
            row = header_row + 1 + i

            marker = '> ' if selected else '  '
            self.console.print(x + self.SETTINGS_ACTION_COL, row, f'{marker}{action.name}', fg=color)

            if ui_state.remapping_action == action:
                self.console.print(x + self.SETTINGS_KEY_COL, row, 'Press any key or button...', fg=color)
            else:
                self.console.print(x + self.SETTINGS_KEY_COL, row, keybindings.bindings[action].name, fg=color)
                if has_controller:
                    self.console.print(
                        x + self.SETTINGS_CONTROLLER_COL, row, controller_binding_label(action, keybindings), fg=color
                    )

        if has_controller:
            self.console.print(
                x + 2, y + height - 3, 'Left stick: move    Triggers: scroll log    Start: back', fg=UI_GRAY_DARK
            )
        self.console.print(x + 2, y + height - 2, 'Arrows: Select | L/R: Change | Enter: Remap | Esc: Back', fg=UI_GRAY)

    def render_game_over(self):
        game_state = get_singleton(GameState)
        run_stats = try_get_singleton(RunStats)
        if not run_stats:
            return

        spells = sorted(run_stats.spells_cast.items(), key=lambda kv: kv[0].name)
        ingredients = sorted(run_stats.ingredients_collected.items(), key=lambda kv: kv[0].name)
        totals = [
            f'Floor reached:     {game_state.floor}',
            f'Enemies defeated:  {run_stats.enemies_defeated}',
            f'Gold collected:    {run_stats.gold_collected}',
            f'Spells discovered: {run_stats.spells_discovered}',
            f'Damage dealt:      {run_stats.damage_dealt}',
        ]

        # Two label rows + a blank separator each, and at least one row per section.
        body_rows = len(totals) + 2 + max(1, len(spells)) + 2 + max(1, len(ingredients))
        width, height = 44, body_rows + 5
        title = 'Victory!' if run_stats.won else 'You Died'
        x, y = draw_centered_frame(self.console, width, height, title=title)

        row = y + 2
        for line in totals:
            self.console.print(x + 2, row, line, fg=UI_WHITE)
            row += 1

        row = self._render_count_section(x, row + 1, 'Spells cast:', spells)
        self._render_count_section(x, row + 1, 'Ingredients collected:', ingredients)

        self.console.print(x + 2, y + height - 2, 'Enter: Title', fg=UI_GRAY)

    def _render_count_section(
        self, x: int, row: int, label: str, entries: Sequence[tuple[ItemType | SpellType, int]]
    ) -> int:
        """Print a `label` header then one indented `Name xN` line per entry (or
        '(none)' when empty). Returns the next free row."""
        self.console.print(x + 2, row, label, fg=UI_SKY)
        row += 1
        if not entries:
            self.console.print(x + 4, row, '(none)', fg=UI_GRAY_DARK)
            return row + 1
        for key, count in entries:
            self.console.print(x + 4, row, f'{key.name} x{count}', fg=UI_WHITE)
            row += 1
        return row
