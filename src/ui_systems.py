import math
from collections import Counter

import esper
import tcod

from src import persistence
from src.components import (
    Inventory,
    Keybindings,
    KnownRecipes,
    MessageLog,
    Modal,
    PlayerTag,
    Position,
    SpellInventory,
    Stats,
    TargetingReticle,
    UIState,
)
from src.constants import (
    UI_CYAN,
    UI_CYAN_DARK,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_RED,
    UI_RED_DARK,
    UI_WHITE,
    UI_YELLOW,
)
from src.layout import Layout, Rect
from src.map_objects import Map
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    CraftingView,
    DisplayMode,
    GameState,
    MenuOption,
)
from src.systems import can_craft_known_spell, get_singleton, get_spell_config, is_game_active
from src.ui_helpers import (
    compute_visible_slice,
    draw_centered_frame,
    draw_titled_frame,
    format_recipe,
    format_spell_effects,
    wrap_message,
)


class MenuSystem(esper.Processor):
    def __init__(self, layout: Layout):
        self.layout = layout

    @property
    def console(self) -> tcod.console.Console:
        return self.layout.console

    def process(self):
        game_state = get_singleton(GameState)
        if not game_state:
            return

        if game_state.display_mode == DisplayMode.MENU:
            self.render_main_menu()
        elif game_state.display_mode == DisplayMode.COMBINING:
            self.render_combining_menu()
        elif game_state.display_mode == DisplayMode.CASTING:
            self.render_casting_menu()
        elif game_state.display_mode == DisplayMode.SETTINGS:
            self.render_settings_menu()

    def render_main_menu(self):
        ui_state = get_singleton(UIState)
        if not ui_state:
            return

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
        player_inv = get_singleton(Inventory)
        player_recipes = get_singleton(KnownRecipes)
        player_spell_inv = get_singleton(SpellInventory)

        if not all([ui_state, player_inv, player_recipes, player_spell_inv]):
            return

        width, height = 72, 24
        x, y = draw_centered_frame(self.console, width, height, title='Crafting')

        self._render_crafting_tabs(x + 2, y + 1, ui_state.crafting_view)

        if ui_state.crafting_view == CraftingView.SPELLBOOK:
            self._render_spellbook(x, y, width, ui_state, player_recipes, player_spell_inv, player_inv)
            footer = 'Tab: Experiment | Up/Down: Select | Enter: Craft | Esc: Close'
        else:
            self._render_experiment(x, y, ui_state, player_inv)
            footer = 'Tab: Spellbook | L/R: Select | Enter: Combine | Esc: Close'

        self.console.print(x + 2, y + height - 2, footer, fg=UI_GRAY)

    def _render_crafting_tabs(self, tx, ty, view):
        self.console.print(tx, ty, 'Experiment', fg=UI_YELLOW if view == CraftingView.EXPERIMENT else UI_GRAY_DARK)
        self.console.print(tx + 13, ty, 'Spellbook', fg=UI_YELLOW if view == CraftingView.SPELLBOOK else UI_GRAY_DARK)

    def _render_experiment(self, x, y, ui_state, player_inv):
        self.console.print(x + 2, y + 3, 'Combine ingredients to discover spells:', fg=UI_CYAN)

        inv_list = sorted(player_inv.items.keys())
        if not inv_list:
            self.console.print(x + 2, y + 5, 'No ingredients to combine.', fg=UI_GRAY_DARK)
            return

        for i, itype in enumerate(inv_list):
            selected = i == ui_state.crafting_cursor
            count = player_inv.items[itype]
            chosen = ui_state.selected_for_crafting.get(itype, 0)
            marker = '> ' if selected else '  '
            self.console.print(
                x + 2,
                y + 5 + i,
                f'{marker}{itype.name}: {count} (Selected: {chosen})',
                fg=UI_WHITE if selected else UI_GRAY_DARK,
            )

    def _render_spellbook(self, x, y, width, ui_state, player_recipes, player_spell_inv, player_inv):
        known = sorted(player_recipes.recipes.keys(), key=lambda s: s.name)
        list_x = x + 2
        detail_x = x + 26

        if not known:
            self.console.print(list_x, y + 4, 'No recipes discovered yet.', fg=UI_GRAY)
            self.console.print(list_x, y + 6, 'Find them in the Experiment tab.', fg=UI_GRAY_DARK)
            return

        cursor = ui_state.spellbook_cursor % len(known)
        for i, stype in enumerate(known):
            # Spells with no affordable recipe are dimmed.
            craftable = can_craft_known_spell(stype)
            charges = player_spell_inv.spells.get(stype, 0)
            if i == cursor:
                color = UI_YELLOW if craftable else UI_GRAY
            else:
                color = UI_WHITE if craftable else UI_GRAY_DARK
            marker = '> ' if i == cursor else '  '
            self.console.print(list_x, y + 4 + i, f'{marker}{stype.name} ({charges})', fg=color)

        self._render_spell_detail(detail_x, y + 4, width - 28, known[cursor], player_recipes, player_inv)

    def _render_spell_detail(self, dx, dy, detail_width, stype, player_recipes, player_inv):
        s_conf = get_spell_config(stype.value)
        if not s_conf:
            return

        row = dy
        self.console.print(dx, row, s_conf.get('name', stype.name), fg=UI_CYAN)
        row += 1

        description = s_conf.get('description')
        if description:
            for line in wrap_message([(description, UI_GRAY)], detail_width):
                self._print_segments(dx, row, line)
                row += 1
        row += 1

        self.console.print(dx, row, f'Range {s_conf.get("range", 0)}   Radius {s_conf.get("radius", 0)}', fg=UI_WHITE)
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
                self._print_segments(dx, row, line)
                row += 1

    def _print_segments(self, x, y, segments):
        cx = x
        for text, color in segments:
            self.console.print(cx, y, text, fg=color)
            cx += len(text)

    def render_casting_menu(self):
        ui_state = get_singleton(UIState)
        player_spell_inv = get_singleton(SpellInventory)
        if not ui_state or not player_spell_inv:
            return

        width = 50
        height = 15
        x, y = draw_centered_frame(self.console, width, height, title='Select Spell to Cast')

        available_spells = sorted(
            [s for s in player_spell_inv.spells if player_spell_inv.spells[s] > 0],
            key=lambda x: x.name,
        )

        if not available_spells:
            self.console.print(
                x + width // 2 - 10,
                y + height // 2,
                'No spells with charges!',
                fg=UI_RED,
            )
        else:
            for i, stype in enumerate(available_spells):
                color = UI_YELLOW if i == ui_state.casting_cursor else UI_WHITE
                charges = player_spell_inv.spells[stype]

                # Metadata for range/radius
                s_conf = get_spell_config(stype.value) or {}
                info = f' (Range: {s_conf.get("range", 0)}, Radius: {s_conf.get("radius", 0)})'

                self.console.print(
                    x + 2,
                    y + 2 + (i * 2),
                    f'{"> " if i == ui_state.casting_cursor else "  "}{stype.name}: {charges} charges{info}',
                    fg=color,
                )

        self.console.print(
            x + 2,
            y + height - 2,
            'Arrows: Select | Enter: Target | S/Esc: Cancel',
            fg=UI_GRAY,
        )

    def render_settings_menu(self):
        ui_state = get_singleton(UIState)
        keybindings = get_singleton(Keybindings)
        if not ui_state or not keybindings:
            return

        actions = list(keybindings.bindings.keys())

        width = 40
        height = 15
        x, y = draw_centered_frame(self.console, width, height, title='Settings')

        for i, action in enumerate(actions):
            color = UI_YELLOW if i == ui_state.settings_cursor else UI_WHITE
            key_name = keybindings.bindings[action].name

            text = f'{"> " if i == ui_state.settings_cursor else "  "}{action}: '
            if ui_state.remapping_action == action:
                text += '[Press any key...]'
            else:
                text += f'[{key_name}]'

            self.console.print(x + 2, y + 2 + i, text, fg=color)

        self.console.print(
            x + 2,
            y + height - 2,
            'Arrows: Select | Enter: Remap | Esc: Back',
            fg=UI_GRAY,
        )


class TargetingOverlaySystem(esper.Processor):
    def __init__(self, layout: Layout):
        self.layout = layout

    @property
    def console(self) -> tcod.console.Console:
        return self.layout.console

    def process(self):
        game_state = get_singleton(GameState)
        if not game_state or game_state.display_mode != DisplayMode.TARGETING:
            return

        reticles = esper.get_component(TargetingReticle)
        if not reticles:
            return

        _ent, reticle = reticles[0]
        player_entities = esper.get_components(Position, PlayerTag)
        if not player_entities:
            return
        _player, (player_pos, _tag) = player_entities[0]

        game_map = get_singleton(Map)
        if not game_map:
            return

        # The overlay highlights tiles, so it shares the map's camera transform:
        # iterate the viewport's screen cells, map each back to its map cell for
        # the distance tests, and paint the screen cell.
        view = self.layout.map_viewport
        cam_x, cam_y = self.layout.camera_offset(player_pos.x, player_pos.y, game_map.width, game_map.height)

        for screen_y in range(view.y, view.y + view.height):
            for screen_x in range(view.x, view.x + view.width):
                map_x = screen_x - view.x + cam_x
                map_y = screen_y - view.y + cam_y
                dist_to_reticle = math.sqrt((map_x - reticle.x) ** 2 + (map_y - reticle.y) ** 2)
                dist_to_player = math.sqrt((map_x - player_pos.x) ** 2 + (map_y - player_pos.y) ** 2)

                if dist_to_reticle <= reticle.radius:
                    self.console.rgb[screen_y, screen_x]['bg'] = (100, 0, 0)
                elif dist_to_player <= reticle.range:
                    self.console.rgb[screen_y, screen_x]['bg'] = (0, 0, 50)

        # Draw yellow reticle X at its on-screen position.
        screen_rx = view.x + reticle.x - cam_x
        screen_ry = view.y + reticle.y - cam_y
        if view.contains(screen_rx, screen_ry):
            self.console.print(screen_rx, screen_ry, 'X', fg=UI_YELLOW)


class ModalSystem(esper.Processor):
    def __init__(self, layout: Layout):
        self.layout = layout

    @property
    def console(self) -> tcod.console.Console:
        return self.layout.console

    def process(self):
        for _ent, modal in esper.get_component(Modal):
            # Center the modal based on its own dimensions
            x, y = draw_centered_frame(self.console, modal.width, modal.height, title='Message')

            # Message
            self.console.print(
                x=x + 2,
                y=y + 2,
                width=modal.width - 4,
                height=modal.height - 4,
                text=modal.message,
                fg=UI_WHITE,
            )

            self.console.print(
                x + modal.width // 2 - 10,
                y + modal.height - 2,
                'Press any key to close',
                fg=UI_GRAY,
            )


class HUDSystem(esper.Processor):
    HP_BAR_WIDTH = 20
    # Width of the stats column on the left of the HUD bar; the log fills the rest.
    HUD_STATS_WIDTH = 34

    def __init__(self, layout: Layout):
        self.layout = layout

    @property
    def console(self) -> tcod.console.Console:
        return self.layout.console

    def process(self):
        game_state = get_singleton(GameState)
        if not game_state:
            return

        if game_state.display_mode not in [
            DisplayMode.EXPLORING,
            DisplayMode.CASTING,
            DisplayMode.COMBINING,
            DisplayMode.TARGETING,
        ]:
            return

        # The HUD bar splits into a stats column and a message log.
        stats_zone, log_zone = self.layout.hud.split_left(self.HUD_STATS_WIDTH)
        self.render_hp_bar(stats_zone)
        self.render_floor_info(stats_zone, game_state.floor)
        self.render_message_log(log_zone)

    def render_hp_bar(self, zone: Rect):
        player_stats = esper.get_components(Stats, PlayerTag)
        if not player_stats:
            return
        _player, (stats, _) = player_stats[0]

        hp_label_start_x, hp_label_y = zone.x + 2, zone.y + 1

        hp_text = f'HP: {stats.hp}/{stats.max_hp}'
        self.console.print(hp_label_start_x, hp_label_y, hp_text, fg=UI_WHITE)

        hp_bar_start_x = hp_label_start_x + len(hp_text) + 1
        ratio = stats.hp / stats.max_hp
        filled_width = int(ratio * self.HP_BAR_WIDTH)

        self.console.draw_rect(hp_bar_start_x, hp_label_y, self.HP_BAR_WIDTH, 1, ch=ord('█'), fg=UI_RED_DARK)
        if filled_width > 0:
            self.console.draw_rect(hp_bar_start_x, hp_label_y, filled_width, 1, ch=ord('█'), fg=UI_RED)

    def render_floor_info(self, zone: Rect, floor: int):
        self.console.print(zone.x + 2, zone.y + 3, f'Floor: {floor}', fg=UI_WHITE)

    def render_message_log(self, zone: Rect):
        log = get_singleton(MessageLog)
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
            bg=(0, 0, 0),
        )

        usable_width = zone.width - 4
        all_lines = []
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
                self.console.print(x=msg_x, y=msg_y, string=text, fg=color)
                msg_x += len(text)
