import math
from collections import Counter
from collections.abc import Sequence

import esper
import pygame

from src import persistence
from src.components import (
    EffectType,
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
    RGB,
    UI_BLACK,
    UI_CYAN_DARK,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_PERIWINKLE,
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
    known_spells,
)
from src.render import RenderProcessor
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
    EFFECT_COLORS,
    can_craft_known_spell,
    get_spell_config,
    is_game_active,
    is_reagent,
    spell_rank,
)
from src.ui_draw import LINE_H, blit_text, blit_text_right, fill_alpha, panel, panel_height, scroll_arrows
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


# The spell wheel's wedges are drawn at this supersample factor and downscaled, so their arc
# edges come out smooth (pygame's polygon fill has no anti-aliasing).
WHEEL_SUPERSAMPLE = 3
# Each wedge is at most 1/WHEEL_MIN_SLOTS of the circle; with fewer spells the ring is padded
# with blank slots (so a 3-spell wheel isn't three giant wedges).
WHEEL_MIN_SLOTS = 8
WHEEL_LABEL_PX = 16  # wedge labels use a smaller font than the UI so long spell names fit
WHEEL_BLANK_COLOR: RGB = (34, 34, 40)
WHEEL_DEPLETED_COLOR: RGB = (52, 52, 58)  # a known spell with no charges left
WHEEL_HUB_COLOR: RGB = (28, 28, 34)


def _lighten(color: RGB, t: float) -> RGB:
    """Blend `color` toward white by `t` (0..1) — the selected wedge's brighter highlight."""
    return (
        int(color[0] + (255 - color[0]) * t),
        int(color[1] + (255 - color[1]) * t),
        int(color[2] + (255 - color[2]) * t),
    )


def _contrast_text(bg: RGB) -> RGB:
    """Black or white, whichever reads better on `bg` (so a label never sits white-on-yellow)."""
    luminance = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return UI_BLACK if luminance > 140 else UI_WHITE


def _ring_wedge_points(
    cx: float, cy: float, r_in: float, r_out: float, a0: float, a1: float, steps: int = 20
) -> list[tuple[float, float]]:
    """A ring-sector (donut wedge) polygon: the outer arc from a0 to a1, then the inner arc back."""
    outer = [(cx + r_out * math.cos(a), cy + r_out * math.sin(a)) for a in _arc_angles(a0, a1, steps)]
    inner = [(cx + r_in * math.cos(a), cy + r_in * math.sin(a)) for a in reversed(_arc_angles(a0, a1, steps))]
    return outer + inner


def _arc_angles(a0: float, a1: float, steps: int) -> list[float]:
    return [a0 + (a1 - a0) * k / steps for k in range(steps + 1)]


class MenuSystem(RenderProcessor):
    """Draws the full-screen menus (main/pause, crafting, casting, shop, settings, game over)
    pixel-native into the window Surface. Each screen's drawn rows come from a pure content
    method (below the render methods), so their content/colors/windowing stay unit-testable."""

    # Panel widths (px). Heights follow from each screen's row count via panel_height().
    MAIN_W = 320
    CRAFT_W = 920
    CAST_W = 780
    SHOP_W = 660
    SETTINGS_W = 840
    GAMEOVER_W = 520

    INDENT = 20  # left indent for the main-menu options
    SCROLL_INSET = 16  # x-offset (from the content's right edge) of a list's scroll arrows

    # Crafting layout: the second tab, the right-hand spell-detail column, and how many list rows fit.
    CRAFT_TAB2_X = 200
    CRAFT_DETAIL_X = 400
    CRAFT_BODY_ROWS = 20

    CAST_VISIBLE = 6  # spell rows shown (double-spaced) in the casting picker
    SHOP_VISIBLE = 8  # offer rows shown in the shop

    # Settings column x-offsets: the keyboard binding, then the controller binding.
    SET_KEY_X = 240
    SET_CTRL_X = 480

    def process(self):
        mode = get_singleton(GameState).display_mode
        if mode == DisplayMode.MENU:
            self.render_main_menu()
        elif mode == DisplayMode.COMBINING:
            self.render_combining_menu()
        elif mode == DisplayMode.CASTING:
            self.render_casting_menu()
        elif mode == DisplayMode.SPELL_WHEEL:
            self.render_spell_wheel()
        elif mode == DisplayMode.SHOPPING:
            self.render_shop_menu()
        elif mode == DisplayMode.SETTINGS:
            self.render_settings_menu()
        elif mode == DisplayMode.GAME_OVER:
            self.render_game_over()

    def _row(self, content: pygame.Rect, x_off: int, row: int, segments: Message) -> None:
        """Blit a row's segments left-to-right from `x_off` pixels into content row `row`."""
        x = content.x + x_off
        y = content.y + row * LINE_H
        for text, color in segments:
            x += blit_text(self.surface, self.font, text, x, y, color)

    def _scroll(self, content: pygame.Rect, x_off: int, first_row: int, last_row: int, up: bool, down: bool) -> None:
        """Draw up/down scroll arrows at `x_off`, spanning the first and last drawn row of a list."""
        x = content.x + x_off
        top_y = content.y + first_row * LINE_H
        bottom_y = content.y + last_row * LINE_H
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
        content = panel(self.surface, self.font, self.MAIN_W, panel_height(len(rows) + 1), title)
        for i, row in enumerate(rows):
            self._row(content, self.INDENT, i + 1, row)

    # --- crafting ---------------------------------------------------------------

    def render_combining_menu(self):
        ui_state = get_singleton(UIState)
        inv = try_get_singleton(Inventory)
        recipes = try_get_singleton(KnownRecipes)
        spell_inv = try_get_singleton(SpellInventory)
        if inv is None or recipes is None or spell_inv is None:
            return

        content = panel(self.surface, self.font, self.CRAFT_W, panel_height(self.CRAFT_BODY_ROWS), 'Crafting')
        experiment = ui_state.crafting_view != CraftingView.SPELLBOOK
        self._row(content, 0, 0, [('Experiment', UI_YELLOW if experiment else UI_GRAY_DARK)])
        self._row(content, self.CRAFT_TAB2_X, 0, [('Spellbook', UI_GRAY_DARK if experiment else UI_YELLOW)])

        footer_row = self.CRAFT_BODY_ROWS - 1
        scroll_x = content.width - self.SCROLL_INSET
        if experiment:
            rows, up, down = self._experiment_rows(ui_state, inv, footer_row - 3)
            for i, row in enumerate(rows):
                self._row(content, 0, 3 + i, row)
            self._scroll(content, scroll_x, 3, 3 + len(rows) - 1, up, down)
            footer = 'Tab: Spellbook | L/R: Select | Enter: Combine | Esc: Close'
        else:
            rows, up, down = self._spellbook_list_rows(ui_state, recipes, spell_inv, footer_row - 2)
            for i, row in enumerate(rows):
                self._row(content, 0, 2 + i, row)
            self._scroll(content, self.CRAFT_DETAIL_X - self.SCROLL_INSET, 2, 2 + len(rows) - 1, up, down)
            if recipes.recipes:
                known = sorted(recipes.recipes.keys(), key=lambda s: s.name)
                cursor = ui_state.spellbook_cursor % len(known)
                detail_px = content.width - self.CRAFT_DETAIL_X
                for i, line in enumerate(self._spell_detail_lines(known[cursor], recipes, inv, detail_px)):
                    self._row(content, self.CRAFT_DETAIL_X, 2 + i, line)
            footer = 'Tab: Experiment | Up/Down: Select | Enter: Craft | Esc: Close'
        self._row(content, 0, footer_row, [(footer, UI_GRAY)])

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
        self, stype: SpellType, recipes: KnownRecipes, inv: Inventory, detail_px: int
    ) -> list[Message]:
        s_conf = get_spell_config(stype.value)
        if not s_conf:
            return []
        lines: list[Message] = [[(s_conf.get('name', stype.name), UI_SKY)]]
        description = s_conf.get('description')
        if description:
            lines.extend(wrap_message([(description, UI_GRAY)], detail_px, self.measure))
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
            lines.extend(wrap_message([(text, UI_WHITE if affordable else UI_GRAY_DARK)], detail_px, self.measure))
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
        body_rows = self.CAST_VISIBLE * 2 + 2
        content = panel(self.surface, self.font, self.CAST_W, panel_height(body_rows), 'Select Spell to Cast')

        has_controller = connected_controller_name() is not None
        rows, up, down = self._casting_rows(get_singleton(UIState), spell_inv, has_controller, self.CAST_VISIBLE)
        for i, row in enumerate(rows):
            self._row(content, 0, i * 2, row)  # double-spaced
        self._scroll(content, content.width - self.SCROLL_INSET, 0, (len(rows) - 1) * 2, up, down)

        self._row(
            content, 0, body_rows - 1, [('Arrows: Select | 1-9: Quick-cast | Enter: Target | S/Esc: Cancel', UI_GRAY)]
        )

    # --- spell wheel ------------------------------------------------------------

    def _spell_color(self, stype: SpellType) -> RGB:
        """A wheel node's color: its spell's primary-effect color (white when it has none)."""
        s_conf = get_spell_config(stype.value)
        if s_conf and s_conf['effects']:
            return EFFECT_COLORS.get(s_conf['effects'][0].type, UI_WHITE)
        return UI_WHITE

    def _wheel_center_lines(self, ui_state: UIState, spell_inv: SpellInventory) -> list[Message]:
        """The wheel's center-hub readout: the selected spell's name and charge count (greyed
        when depleted), or the empty message when the player knows no spells."""
        spells = known_spells()
        if not spells:
            return [[('No spells known!', UI_RED)]]
        stype = spells[ui_state.wheel_cursor % len(spells)]
        charges = spell_inv.spells.get(stype, 0)
        charge_text = f'{charges} charges' if charges > 0 else 'No charges'
        return [
            [(stype.name, UI_YELLOW)],
            [(charge_text, UI_WHITE if charges > 0 else UI_GRAY)],
        ]

    def _blit_centered(self, text: str, cx: int, y: int, color: RGB, font: pygame.font.Font | None = None) -> None:
        font = font or self.font
        blit_text(self.surface, font, text, cx - font.size(text)[0] // 2, y, color)

    def render_spell_wheel(self):
        spell_inv = try_get_singleton(SpellInventory)
        if spell_inv is None:
            return
        ui_state = get_singleton(UIState)
        w, h = self.surface.get_width(), self.surface.get_height()
        cx, cy = w // 2, h // 2
        fill_alpha(self.surface, 0, 0, w, h, UI_BLACK, 0.55)  # dim the live map behind the wheel

        spells = known_spells()
        r_out = int(min(w, h) * 0.34)
        r_in = int(r_out * 0.46)
        if spells:
            cursor = ui_state.wheel_cursor % len(spells)
            self._draw_wheel_ring(spells, cursor, spell_inv, cx, cy, r_in, r_out)
            self._draw_wheel_labels(spells, cursor, spell_inv, cx, cy, r_in, r_out)
            self._draw_spell_detail(spells[cursor], cx, cy, r_out)

        pygame.draw.circle(self.surface, WHEEL_HUB_COLOR, (cx, cy), max(1, r_in - 3))  # center hub
        self._draw_wheel_hub(ui_state, spell_inv, cx, cy)

    def _draw_wheel_ring(
        self, spells: list[SpellType], cursor: int, spell_inv: SpellInventory, cx: int, cy: int, r_in: int, r_out: int
    ) -> None:
        """Draw the ring of spell wedges onto a supersampled layer (smooth arcs), then blit it
        down centered. Each wedge is at most 1/WHEEL_MIN_SLOTS of the circle; slots past the spell
        count are blank, and depleted spells are greyed. The selected wedge is brightened, pushed
        out, and outlined."""
        s = WHEEL_SUPERSAMPLE
        span = (r_out + 18) * 2  # room for the selected wedge's explode + border
        layer = pygame.Surface((span * s, span * s), pygame.SRCALPHA)
        lc = span * s // 2
        slots = max(len(spells), WHEEL_MIN_SLOTS)
        seg = 2 * math.pi / slots
        gap = min(0.04, seg * 0.08)  # a hair of space between wedges
        for i in range(slots):
            mid = -math.pi / 2 + i * seg
            selected = i == cursor
            if i >= len(spells):
                fill, outer = WHEEL_BLANK_COLOR, r_out * s
            elif spell_inv.spells.get(spells[i], 0) <= 0:
                fill = WHEEL_DEPLETED_COLOR
                outer = (r_out + 14 if selected else r_out) * s
            else:
                base = self._spell_color(spells[i])
                fill = _lighten(base, 0.35) if selected else base
                outer = (r_out + 14 if selected else r_out) * s
            pts = _ring_wedge_points(lc, lc, r_in * s, outer, mid - seg / 2 + gap, mid + seg / 2 - gap)
            pygame.draw.polygon(layer, fill, pts)
            if selected and i < len(spells):
                pygame.draw.polygon(layer, UI_WHITE, pts, 4 * s)  # selection border
        scaled = pygame.transform.smoothscale(layer, (span, span))
        self.surface.blit(scaled, (cx - span // 2, cy - span // 2))

    def _draw_wheel_labels(
        self, spells: list[SpellType], cursor: int, spell_inv: SpellInventory, cx: int, cy: int, r_in: int, r_out: int
    ) -> None:
        """Label each wedge with its spell's full name (word-wrapped) and charge count; a depleted
        spell's label is greyed to match its wedge."""
        slots = max(len(spells), WHEEL_MIN_SLOTS)
        seg = 2 * math.pi / slots
        lr = (r_in + r_out) / 2
        font = self.asset_loader.font(WHEEL_LABEL_PX)
        lh = font.get_height()
        for i, stype in enumerate(spells):
            mid = -math.pi / 2 + i * seg
            lx, ly = cx + lr * math.cos(mid), cy + lr * math.sin(mid)
            lines = stype.name.replace('_', ' ').title().split(' ')
            lines.append(f'x{spell_inv.spells.get(stype, 0)}')
            if spell_inv.spells.get(stype, 0) <= 0:
                color = UI_GRAY
            else:
                base = self._spell_color(stype)
                color = _contrast_text(_lighten(base, 0.35) if i == cursor else base)
            top = int(ly - len(lines) * lh / 2)
            for j, text in enumerate(lines):
                self._blit_centered(text, int(lx), top + j * lh, color, font)

    def _draw_spell_detail(self, stype: SpellType, cx: int, cy: int, r_out: int) -> None:
        """The selected spell's stat block (mastery, damage, radius) and description, left-aligned
        to the left of the wheel."""
        s_conf = get_spell_config(stype.value)
        if s_conf is None:
            return
        left = 30
        max_width = cx - r_out - left - 40
        if max_width < 140:
            return  # window too narrow to fit a readable column
        lines: list[Message] = [
            [(stype.name.replace('_', ' ').title(), UI_YELLOW)],
            [(f'Mastery {spell_rank(stype)}', UI_SKY)],
        ]
        damage = next((e.power for e in s_conf['effects'] if e.type == EffectType.DAMAGE), None)
        if damage is not None:
            lines.append([(f'Damage {damage}', UI_WHITE)])
        lines.append([(f'Radius {s_conf.get("radius", 0)}', UI_WHITE)])
        description = s_conf.get('description')
        if description:
            lines.append([('', UI_WHITE)])
            lines.extend(wrap_message([(description, UI_GRAY)], max_width, self.measure))
        top = cy - len(lines) * LINE_H // 2
        for i, line in enumerate(lines):
            x = left
            for text, color in line:
                x += blit_text(self.surface, self.font, text, x, top + i * LINE_H, color)

    def _draw_wheel_hub(self, ui_state: UIState, spell_inv: SpellInventory, cx: int, cy: int) -> None:
        """The center hub: the selected spell's charges/radius readout, plus the controls hint."""
        lines = self._wheel_center_lines(ui_state, spell_inv)
        top = cy - len(lines) * LINE_H // 2
        for i, line in enumerate(lines):
            text, color = line[0]
            self._blit_centered(text, cx, top + i * LINE_H, color)
        h = self.surface.get_height()
        self._blit_centered('Move: Rotate | Enter: Cast | D/Esc: Close', cx, h - LINE_H * 2, UI_GRAY)

    # --- shop -------------------------------------------------------------------

    def _shop_rows(self, ui_state: UIState, offers: Sequence[ShopOffer], gold: int, visible: int) -> ScrolledRows:
        """Each row is a left label segment plus a right-aligned price segment (the render pass
        right-aligns the second segment), so prices line up regardless of label width."""
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
            price = f'{offer.price} G'
            if selected:
                qty = ui_state.shop_quantity
                price += f'   x{qty} ({offer.price * qty} G)'
            rows.append([(f'{"> " if selected else "  "}{offer.label}', color), (price, color)])
        return rows, start > 0, end < len(offers)

    def render_shop_menu(self):
        shopkeepers = esper.get_component(Shopkeeper)
        inv = try_get_singleton(Inventory)
        if not shopkeepers or inv is None:
            return
        offers = shopkeepers[0][1].offers
        gold = inv.items.get(ItemType.GOLD, 0)

        content = panel(self.surface, self.font, self.SHOP_W, panel_height(self.SHOP_VISIBLE + 3), 'Shop')
        self._row(content, 0, 0, [(f'Gold: {gold}', UI_YELLOW)])

        rows, up, down = self._shop_rows(get_singleton(UIState), offers, gold, self.SHOP_VISIBLE)
        for i, row in enumerate(rows):
            self._row(content, 0, 2 + i, [row[0]])
            if len(row) > 1:
                price_text, color = row[1]
                blit_text_right(self.surface, self.font, price_text, content.right, content.y + (2 + i) * LINE_H, color)
        self._scroll(content, content.width - self.SCROLL_INSET, 2, 2 + len(rows) - 1, up, down)

        self._row(content, 0, self.SHOP_VISIBLE + 2, [('L/R: Qty | Enter: Buy | Esc: Leave', UI_GRAY)])

    # --- settings ---------------------------------------------------------------

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
        body_rows = len(actions) + len(SettingsPref) + (7 if has_controller else 5)
        content = panel(self.surface, self.font, self.SETTINGS_W, panel_height(body_rows), 'Settings')

        self._row(content, 0, 0, [(f'Controller: {controller_name or "none detected"}', UI_SKY)])
        if has_controller:
            self._row(content, 0, 1, [(f'Last input: {ui_state.last_controller_input or "-"}', UI_GRAY)])

        first_pref_row = 3 if has_controller else 2
        for i, row in enumerate(self._settings_pref_rows(ui_state, settings)):
            self._row(content, 0, first_pref_row + i, [row[0]])
            self._row(content, self.SET_KEY_X, first_pref_row + i, [row[1]])

        header_row = first_pref_row + len(SettingsPref) + 1
        self._row(content, 0, header_row, [('Action', UI_CYAN_DARK)])
        self._row(content, self.SET_KEY_X, header_row, [('Keyboard', UI_CYAN_DARK)])
        if has_controller:
            self._row(content, self.SET_CTRL_X, header_row, [('Controller', UI_CYAN_DARK)])

        cols = (0, self.SET_KEY_X, self.SET_CTRL_X)
        for i, row in enumerate(self._settings_binding_rows(ui_state, settings, has_controller)):
            for seg, col in zip(row, cols, strict=False):
                self._row(content, col, header_row + 1 + i, [seg])

        footer_row = body_rows - 1
        if has_controller:
            hint = 'Left stick: move    Triggers: scroll log    Start: back'
            self._row(content, 0, footer_row - 1, [(hint, UI_GRAY_DARK)])
        self._row(content, 0, footer_row, [('Arrows: Select | L/R: Change | Enter: Remap | Esc: Back', UI_GRAY)])

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
        content = panel(
            self.surface,
            self.font,
            self.GAMEOVER_W,
            panel_height(len(lines) + 2),
            'Victory!' if run_stats.won else 'You Died',
        )
        for i, line in enumerate(lines):
            self._row(content, 0, i, line)
        self._row(content, 0, len(lines) + 1, [('Enter: Return to town   |   Esc: Title', UI_GRAY)])
