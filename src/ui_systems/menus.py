from collections import Counter
from collections.abc import Sequence

import esper
import pygame

from src import persistence
from src.components import (
    Inventory,
    ItemType,
    KnownRecipes,
    Message,
    RunStats,
    Settings,
    Shopkeeper,
    ShopOffer,
    SpellInventory,
    SpellType,
    UIState,
)
from src.constants import (
    UI_CYAN_DARK,
    UI_FONT_PX,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_PERIWINKLE,
    UI_RED,
    UI_SKY,
    UI_WHITE,
    UI_YELLOW,
)
from src.data_loaders import AssetLoader
from src.ecs_helpers import get_singleton, try_get_singleton
from src.input_handlers import (
    QUICK_CAST_FACE_BUTTONS,
    available_spells,
    connected_controller_name,
    controller_binding_label,
)
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    CraftingView,
    DisplayMode,
    GameState,
    MenuOption,
    SettingsPref,
)
from src.systems import (
    can_craft_known_spell,
    get_spell_config,
    is_game_active,
    is_reagent,
    spell_rank,
)
from src.ui_draw import blit_text, cell, panel, scroll_arrows
from src.ui_helpers import format_recipe, format_spell_effects, scroll_window, wrap_message

# A drawn row: its segments (each a (text, color)) and whether the list scrolls past it above/below.
ScrolledRows = tuple[list[Message], bool, bool]


def _quick_cast_label(slot: int, has_controller: bool) -> str:
    """The quick-cast prefix for a spell row: its number key, plus the controller face
    button (when a pad is connected) for the first four slots; blank past slot 9."""
    if slot >= 9:
        return '   '
    if has_controller and slot < len(QUICK_CAST_FACE_BUTTONS):
        return f'{slot + 1}/{QUICK_CAST_FACE_BUTTONS[slot].name}) '
    return f'{slot + 1}) '


class MenuSystem(esper.Processor):
    """Draws the full-screen menus (main/pause, crafting, casting, shop, settings, game over)
    pixel-native into the window Surface. Each screen's drawn rows come from a pure content
    method (below the render methods), so their content/colors/windowing stay unit-testable."""

    def __init__(self, surface: pygame.Surface, asset_loader: AssetLoader):
        self.surface = surface
        self.asset_loader = asset_loader

    @property
    def font(self) -> pygame.font.Font:
        return self.asset_loader.font(UI_FONT_PX)

    def process(self):
        mode = get_singleton(GameState).display_mode
        if mode == DisplayMode.MENU:
            self.render_main_menu()
        elif mode == DisplayMode.COMBINING:
            self.render_combining_menu()
        elif mode == DisplayMode.CASTING:
            self.render_casting_menu()
        elif mode == DisplayMode.SHOPPING:
            self.render_shop_menu()
        elif mode == DisplayMode.SETTINGS:
            self.render_settings_menu()
        elif mode == DisplayMode.GAME_OVER:
            self.render_game_over()

    def _row(self, origin: tuple[int, int], col: int, row: int, segments: Message) -> None:
        """Blit a row's segments left-to-right from grid cell (col, row)."""
        x, y = cell(origin, col, row)
        for text, color in segments:
            x += blit_text(self.surface, self.font, text, x, y, color)

    def _scroll(self, origin: tuple[int, int], col: int, first_row: int, last_row: int, up: bool, down: bool) -> None:
        """Draw up/down scroll arrows in `col`, at the first and last drawn row of a list."""
        x, top_y = cell(origin, col, first_row)
        _x, bottom_y = cell(origin, col, last_row)
        scroll_arrows(self.surface, x, top_y, bottom_y, up, down, UI_YELLOW)

    # --- main / pause menu ------------------------------------------------------

    def _main_menu_rows(self) -> list[Message]:
        options = PAUSE_MENU_OPTIONS if is_game_active() else TITLE_MENU_OPTIONS
        cursor = get_singleton(UIState).main_menu_cursor % len(options)
        can_load = persistence.has_save()
        rows: list[Message] = []
        for i, option in enumerate(options):
            color = UI_YELLOW if i == cursor else UI_WHITE
            if option in (MenuOption.CONTINUE, MenuOption.LOAD) and not can_load:
                color = UI_GRAY_DARK
            rows.append([(f'{"> " if i == cursor else "  "}{option}', color)])
        return rows

    def render_main_menu(self):
        title = 'Paused' if is_game_active() else 'WizardLike'
        rows = self._main_menu_rows()
        origin = panel(self.surface, self.font, 24, len(rows) + 4, title)
        for i, row in enumerate(rows):
            self._row(origin, 3, 2 + i, row)

    # --- crafting ---------------------------------------------------------------

    def render_combining_menu(self):
        ui_state = get_singleton(UIState)
        inv = try_get_singleton(Inventory)
        recipes = try_get_singleton(KnownRecipes)
        spell_inv = try_get_singleton(SpellInventory)
        if inv is None or recipes is None or spell_inv is None:
            return

        width, height = 76, 24
        origin = panel(self.surface, self.font, width, height, 'Crafting')
        experiment = ui_state.crafting_view != CraftingView.SPELLBOOK
        self._row(origin, 2, 1, [('Experiment', UI_YELLOW if experiment else UI_GRAY_DARK)])
        self._row(origin, 15, 1, [('Spellbook', UI_GRAY_DARK if experiment else UI_YELLOW)])

        if experiment:
            rows, up, down = self._experiment_rows(ui_state, inv, height - 7)
            for i, row in enumerate(rows):
                self._row(origin, 2, 5 + i, row)
            self._scroll(origin, width - 2, 5, 5 + len(rows) - 1, up, down)
            footer = 'Tab: Spellbook | L/R: Select | Enter: Combine | Esc: Close'
        else:
            rows, up, down = self._spellbook_list_rows(ui_state, recipes, spell_inv, height - 6)
            for i, row in enumerate(rows):
                self._row(origin, 2, 4 + i, row)
            self._scroll(origin, 28, 4, 4 + len(rows) - 1, up, down)
            if recipes.recipes:
                known = sorted(recipes.recipes.keys(), key=lambda s: s.name)
                cursor = ui_state.spellbook_cursor % len(known)
                for i, line in enumerate(self._spell_detail_lines(known[cursor], recipes, inv, width - 32)):
                    self._row(origin, 30, 4 + i, line)
            footer = 'Tab: Experiment | Up/Down: Select | Enter: Craft | Esc: Close'
        self._row(origin, 2, height - 2, [(footer, UI_GRAY)])

    def _experiment_rows(self, ui_state: UIState, inv: Inventory, visible: int) -> ScrolledRows:
        inv_list = sorted(i for i in inv.items if is_reagent(i))
        if not inv_list:
            return [[('No ingredients to combine.', UI_GRAY_DARK)]], False, False
        cursor = ui_state.crafting_cursor % len(inv_list)
        start, end = scroll_window(len(inv_list), cursor, visible)
        rows: list[Message] = []
        for i in range(start, end):
            itype = inv_list[i]
            selected = i == cursor
            chosen = ui_state.selected_for_crafting.get(itype, 0)
            text = f'{"> " if selected else "  "}{itype.name}: {inv.items[itype]} (Selected: {chosen})'
            rows.append([(text, UI_WHITE if selected else UI_GRAY_DARK)])
        return rows, start > 0, end < len(inv_list)

    def _spellbook_list_rows(
        self, ui_state: UIState, recipes: KnownRecipes, spell_inv: SpellInventory, visible: int
    ) -> ScrolledRows:
        known = sorted(recipes.recipes.keys(), key=lambda s: s.name)
        if not known:
            return [[('No recipes discovered yet.', UI_GRAY)]], False, False
        cursor = ui_state.spellbook_cursor % len(known)
        start, end = scroll_window(len(known), cursor, visible)
        rows: list[Message] = []
        for i in range(start, end):
            stype = known[i]
            craftable = can_craft_known_spell(stype)
            if i == cursor:
                color = UI_YELLOW if craftable else UI_GRAY
            else:
                color = UI_WHITE if craftable else UI_GRAY_DARK
            charges = spell_inv.spells.get(stype, 0)
            rows.append([(f'{"> " if i == cursor else "  "}{stype.name} ({charges})', color)])
        return rows, start > 0, end < len(known)

    def _spell_detail_lines(
        self, stype: SpellType, recipes: KnownRecipes, inv: Inventory, detail_cols: int
    ) -> list[Message]:
        s_conf = get_spell_config(stype.value)
        if not s_conf:
            return []
        lines: list[Message] = [[(s_conf.get('name', stype.name), UI_SKY)]]
        description = s_conf.get('description')
        if description:
            lines.extend(wrap_message([(description, UI_GRAY)], detail_cols))
        lines.append([('', UI_WHITE)])
        lines.append([(f'Radius {s_conf.get("radius", 0)}', UI_WHITE)])
        lines.append([(format_spell_effects(s_conf.get('effects', [])), UI_WHITE)])
        mastery_cfg = s_conf.get('mastery')
        if mastery_cfg:
            lines.append([(f'Mastery {spell_rank(stype)}/{mastery_cfg["max_rank"]}', UI_PERIWINKLE)])
        lines.append([('', UI_WHITE)])
        lines.append([('Recipes:', UI_CYAN_DARK)])
        charges_by_combo = {r['ingredients']: r['charges'] for r in s_conf.get('recipes', [])}
        for combo in sorted(recipes.recipes[stype], key=len):
            affordable = all(inv.items.get(itype, 0) >= count for itype, count in Counter(combo).items())
            text = f'{format_recipe(combo)}  (+{charges_by_combo.get(combo, 0)})'
            lines.extend(wrap_message([(text, UI_WHITE if affordable else UI_GRAY_DARK)], detail_cols))
        return lines

    # --- casting picker ---------------------------------------------------------

    def _casting_rows(
        self, ui_state: UIState, spell_inv: SpellInventory, has_controller: bool, visible: int
    ) -> ScrolledRows:
        spells = available_spells()
        if not spells:
            return [[('No spells with charges!', UI_RED)]], False, False
        cursor = ui_state.casting_cursor % len(spells)
        start, end = scroll_window(len(spells), cursor, visible)
        rows: list[Message] = []
        for i in range(start, end):
            stype = spells[i]
            s_conf = get_spell_config(stype.value) or {}
            charges = spell_inv.spells.get(stype, 0)
            marker = f'{"> " if i == cursor else "  "}{_quick_cast_label(i, has_controller)}'
            text = f'{marker}{stype.name}: {charges} charges (Radius: {s_conf.get("radius", 0)})'
            rows.append([(text, UI_YELLOW if i == cursor else UI_WHITE)])
        return rows, start > 0, end < len(spells)

    def render_casting_menu(self):
        spell_inv = try_get_singleton(SpellInventory)
        if spell_inv is None:
            return
        width, height = 68, 16
        origin = panel(self.surface, self.font, width, height, 'Select Spell to Cast')

        has_controller = connected_controller_name() is not None
        rows, up, down = self._casting_rows(get_singleton(UIState), spell_inv, has_controller, (height - 3) // 2)
        for i, row in enumerate(rows):
            self._row(origin, 2, 2 + i * 2, row)  # double-spaced
        self._scroll(origin, width - 2, 2, 2 + (len(rows) - 1) * 2, up, down)

        self._row(
            origin, 2, height - 2, [('Arrows: Select | 1-9: Quick-cast | Enter: Target | S/Esc: Cancel', UI_GRAY)]
        )

    # --- shop -------------------------------------------------------------------

    def _shop_rows(self, ui_state: UIState, offers: Sequence[ShopOffer], gold: int, visible: int) -> ScrolledRows:
        if not offers:
            return [[('Sold out.', UI_GRAY_DARK)]], False, False
        cursor = ui_state.shop_cursor % len(offers)
        start, end = scroll_window(len(offers), cursor, visible)
        rows: list[Message] = []
        for i in range(start, end):
            offer = offers[i]
            selected = i == cursor
            affordable = gold >= offer.price
            color = (UI_YELLOW if selected else UI_WHITE) if affordable else UI_GRAY_DARK
            text = f'{"> " if selected else "  "}{offer.label:<30}{offer.price:>4} G'
            if selected:
                qty = ui_state.shop_quantity
                text += f'   x{qty} ({offer.price * qty} G)'
            rows.append([(text, color)])
        return rows, start > 0, end < len(offers)

    def render_shop_menu(self):
        shopkeepers = esper.get_component(Shopkeeper)
        inv = try_get_singleton(Inventory)
        if not shopkeepers or inv is None:
            return
        offers = shopkeepers[0][1].offers
        gold = inv.items.get(ItemType.GOLD, 0)

        width, height = 58, 14
        origin = panel(self.surface, self.font, width, height, 'Shop')
        self._row(origin, 2, 1, [(f'Gold: {gold}', UI_YELLOW)])

        rows, up, down = self._shop_rows(get_singleton(UIState), offers, gold, height - 5)
        for i, row in enumerate(rows):
            self._row(origin, 2, 3 + i, row)
        self._scroll(origin, width - 2, 3, 3 + len(rows) - 1, up, down)

        self._row(origin, 2, height - 2, [('L/R: Qty | Enter: Buy | Esc: Leave', UI_GRAY)])

    # --- settings ---------------------------------------------------------------

    SETTINGS_ACTION_COL = 2
    SETTINGS_KEY_COL = 20
    SETTINGS_CONTROLLER_COL = 40

    def _settings_pref_rows(self, ui_state: UIState, settings: Settings) -> list[Message]:
        prefs = [
            ('After casting', settings.post_cast.name),
            ('Music volume', f'{round(settings.music_volume * 100)}%'),
            ('Sound volume', f'{round(settings.sfx_volume * 100)}%'),
            ('Muted', 'ON' if settings.muted else 'OFF'),
        ]
        rows: list[Message] = []
        for i, (label, value) in enumerate(prefs):
            color = UI_YELLOW if ui_state.settings_cursor == i else UI_WHITE
            marker = '> ' if ui_state.settings_cursor == i else '  '
            rows.append([(f'{marker}{label}', color), (f'< {value} >', color)])
        return rows

    def _settings_binding_rows(self, ui_state: UIState, settings: Settings, has_controller: bool) -> list[Message]:
        keybindings = settings.keybindings
        rows: list[Message] = []
        for i, action in enumerate(keybindings.bindings):
            selected = ui_state.settings_cursor == i + len(SettingsPref)
            color = UI_YELLOW if selected else UI_WHITE
            marker = '> ' if selected else '  '
            if ui_state.remapping_action == action:
                key_seg = ('Press any key or button...', color)
            else:
                key_seg = (pygame.key.name(keybindings.bindings[action]).upper(), color)
            row: Message = [(f'{marker}{action.name}', color), key_seg]
            if has_controller:
                row.append((controller_binding_label(action, keybindings), color))
            rows.append(row)
        return rows

    def render_settings_menu(self):
        ui_state = get_singleton(UIState)
        settings = try_get_singleton(Settings)
        if settings is None:
            return
        controller_name = connected_controller_name()
        has_controller = controller_name is not None

        actions = list(settings.keybindings.bindings)
        width = 70
        height = len(actions) + len(SettingsPref) + (9 if has_controller else 7)
        origin = panel(self.surface, self.font, width, height, 'Settings')

        self._row(origin, 2, 1, [(f'Controller: {controller_name or "none detected"}', UI_SKY)])
        if has_controller:
            self._row(origin, 2, 2, [(f'Last input: {ui_state.last_controller_input or "-"}', UI_GRAY)])

        first_pref_row = 4 if has_controller else 3
        for i, row in enumerate(self._settings_pref_rows(ui_state, settings)):
            self._row(origin, self.SETTINGS_ACTION_COL, first_pref_row + i, [row[0]])
            self._row(origin, self.SETTINGS_KEY_COL, first_pref_row + i, [row[1]])

        header_row = first_pref_row + len(SettingsPref) + 1
        self._row(origin, self.SETTINGS_ACTION_COL, header_row, [('Action', UI_CYAN_DARK)])
        self._row(origin, self.SETTINGS_KEY_COL, header_row, [('Keyboard', UI_CYAN_DARK)])
        if has_controller:
            self._row(origin, self.SETTINGS_CONTROLLER_COL, header_row, [('Controller', UI_CYAN_DARK)])

        cols = (self.SETTINGS_ACTION_COL, self.SETTINGS_KEY_COL, self.SETTINGS_CONTROLLER_COL)
        for i, row in enumerate(self._settings_binding_rows(ui_state, settings, has_controller)):
            for seg, col in zip(row, cols, strict=False):
                self._row(origin, col, header_row + 1 + i, [seg])

        if has_controller:
            hint = 'Left stick: move    Triggers: scroll log    Start: back'
            self._row(origin, 2, height - 3, [(hint, UI_GRAY_DARK)])
        self._row(origin, 2, height - 2, [('Arrows: Select | L/R: Change | Enter: Remap | Esc: Back', UI_GRAY)])

    # --- game over --------------------------------------------------------------

    def _game_over_lines(self, game_state: GameState, run_stats: RunStats) -> list[Message]:
        spells = sorted(run_stats.spells_cast.items(), key=lambda kv: kv[0].name)
        ingredients = sorted(run_stats.ingredients_collected.items(), key=lambda kv: kv[0].name)
        totals = [
            f'Floor reached:     {game_state.floor}',
            f'Enemies defeated:  {run_stats.enemies_defeated}',
            f'Gold collected:    {run_stats.gold_collected}',
            f'Spells discovered: {run_stats.spells_discovered}',
            f'Damage dealt:      {run_stats.damage_dealt}',
        ]
        lines: list[Message] = [[(t, UI_WHITE)] for t in totals]
        lines.append([('', UI_WHITE)])
        lines.extend(self._count_section_lines('Spells cast:', spells))
        lines.append([('', UI_WHITE)])
        lines.extend(self._count_section_lines('Ingredients collected:', ingredients))
        return lines

    def _count_section_lines(self, label: str, entries: Sequence[tuple[ItemType | SpellType, int]]) -> list[Message]:
        lines: list[Message] = [[(label, UI_SKY)]]
        if not entries:
            return lines + [[('    (none)', UI_GRAY_DARK)]]
        lines.extend([[(f'    {key.name} x{count}', UI_WHITE)] for key, count in entries])
        return lines

    def render_game_over(self):
        game_state = get_singleton(GameState)
        run_stats = try_get_singleton(RunStats)
        if run_stats is None:
            return
        lines = self._game_over_lines(game_state, run_stats)
        width, height = 44, len(lines) + 5
        origin = panel(self.surface, self.font, width, height, 'Victory!' if run_stats.won else 'You Died')
        for i, line in enumerate(lines):
            self._row(origin, 2, 2 + i, line)
        self._row(origin, 2, height - 2, [('Enter: Title', UI_GRAY)])
