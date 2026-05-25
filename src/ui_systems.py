import math

import esper
import tcod

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
from src.states import MAIN_MENU_OPTIONS, DisplayMode, GameState
from src.systems import get_spell_config
from src.ui_helpers import compute_visible_slice, draw_centered_frame, draw_titled_frame, wrap_message


class MenuSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, player: int):
        self.console = console
        self.player = player

    def process(self):
        game_state = esper.get_component(GameState)[0][1]

        if game_state.display_mode == DisplayMode.MENU:
            self.render_main_menu()
        elif game_state.display_mode == DisplayMode.COMBINING:
            self.render_combining_menu()
        elif game_state.display_mode == DisplayMode.CASTING:
            self.render_casting_menu()
        elif game_state.display_mode == DisplayMode.SETTINGS:
            self.render_settings_menu()

    def render_main_menu(self):
        ui_state = esper.get_component(UIState)[0][1]
        draw_titled_frame(
            self.console,
            0,
            0,
            self.console.width,
            self.console.height,
            title='Main Menu',
            fg=UI_WHITE,
        )

        for i, option in enumerate(MAIN_MENU_OPTIONS):
            color = UI_YELLOW if i == ui_state.main_menu_cursor else UI_WHITE
            self.console.print(
                self.console.width // 2 - 5,
                self.console.height // 2 - 1 + i,
                f'{"> " if i == ui_state.main_menu_cursor else "  "}{option}',
                fg=color,
            )

    def render_combining_menu(self):
        ui_state = esper.get_component(UIState)[0][1]
        width = 60
        height = 20
        x, y = draw_centered_frame(self.console, width, height, title='Combine Items')

        self.console.print(x + 2, y + 1, 'SPELL COMBINING', fg=UI_YELLOW)
        player_inv = esper.component_for_entity(self.player, Inventory)
        inv_list = sorted(player_inv.items.keys())

        for i, itype in enumerate(inv_list):
            color = UI_WHITE if i == ui_state.crafting_cursor else UI_GRAY_DARK
            count = player_inv.items[itype]
            selected = ui_state.selected_for_crafting.get(itype, 0)
            self.console.print(
                x + 2,
                y + 3 + i,
                f'{"> " if i == ui_state.crafting_cursor else "  "}{itype.name}: {count} (Selected: {selected})',
                fg=color,
            )

        self.console.print(
            x + 2,
            y + height - 2,
            'Arrows: Move | L/R: Select | Enter: Combine | Esc: Close',
            fg=UI_GRAY,
        )

        player_recipes = esper.component_for_entity(self.player, KnownRecipes)
        player_spell_inv = esper.component_for_entity(self.player, SpellInventory)

        # Spellbook section (rendered to the right of the inventory list)
        self.console.print(x + 35, y + 1, 'SPELLBOOK', fg=UI_CYAN)
        y_offset = 3

        self.console.print(x + 35, y + y_offset, 'Charges', fg=UI_CYAN_DARK)
        y_offset += 1
        for stype, charges in sorted(player_spell_inv.spells.items(), key=lambda x: x[0].name):
            self.console.print(x + 35, y + y_offset, f'- {stype.name}: {charges}')
            y_offset += 1

        y_offset += 1
        self.console.print(x + 35, y + y_offset, 'Known Recipes', fg=UI_CYAN_DARK)
        y_offset += 1
        for stype in sorted(player_recipes.recipes.keys(), key=lambda x: x.name):
            self.console.print(x + 35, y + y_offset, f'{stype.name}:', fg=UI_WHITE)
            y_offset += 1
            for recipe in sorted(player_recipes.recipes[stype]):
                recipe_str = ' + '.join(itype.name for itype in recipe)
                self.console.print(x + 37, y + y_offset, f'* {recipe_str}')
                y_offset += 1

    def render_casting_menu(self):
        ui_state = esper.get_component(UIState)[0][1]

        width = 50
        height = 15
        x, y = draw_centered_frame(self.console, width, height, title='Select Spell to Cast')

        player_spell_inv = esper.component_for_entity(self.player, SpellInventory)
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
        ui_state = esper.get_component(UIState)[0][1]
        keybindings = esper.get_component(Keybindings)[0][1]
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
    def __init__(self, console: tcod.console.Console):
        self.console = console

    def process(self):
        reticles = esper.get_component(TargetingReticle)
        if not reticles:
            return

        _ent, reticle = reticles[0]
        player_entities = esper.get_components(Position, PlayerTag)
        if not player_entities:
            return
        _player, (player_pos, _tag) = player_entities[0]

        # Highlight Range and AOE
        for y in range(self.console.height):
            for x in range(self.console.width):
                dist_to_reticle = math.sqrt((x - reticle.x) ** 2 + (y - reticle.y) ** 2)
                dist_to_player = math.sqrt((x - player_pos.x) ** 2 + (y - player_pos.y) ** 2)

                if dist_to_reticle <= reticle.radius:
                    self.console.rgb[y, x]['bg'] = (100, 0, 0)
                elif dist_to_player <= reticle.range:
                    self.console.rgb[y, x]['bg'] = (0, 0, 50)

        # Draw yellow reticle X
        if 0 <= reticle.x < self.console.width and 0 <= reticle.y < self.console.height:
            self.console.print(reticle.x, reticle.y, 'X', fg=UI_YELLOW)


class ModalSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console):
        self.console = console

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
    # Layout Constants
    MSG_BOX_X = 34
    MSG_BOX_Y = 45
    MSG_BOX_WIDTH = 46
    MSG_BOX_HEIGHT = 5

    HP_BAR_X = 2
    HP_BAR_Y = 46
    HP_BAR_WIDTH = 20

    FLOOR_TEXT_X = 2
    FLOOR_TEXT_Y = 48

    def __init__(self, console: tcod.console.Console, player: int):
        self.console = console
        self.player = player

    def process(self):
        game_state = esper.get_component(GameState)[0][1]

        if game_state.display_mode not in [
            DisplayMode.EXPLORING,
            DisplayMode.CASTING,
            DisplayMode.COMBINING,
            DisplayMode.TARGETING,
        ]:
            return

        self.render_hp_bar()
        self.render_floor_info(game_state.floor)
        self.render_message_log()

    def render_hp_bar(self):
        stats = esper.component_for_entity(self.player, Stats)
        hp_text = f'HP: {stats.hp}/{stats.max_hp}'
        self.console.print(self.HP_BAR_X, self.HP_BAR_Y, hp_text, fg=UI_WHITE)

        start_x = self.HP_BAR_X + len(hp_text) + 1
        ratio = stats.hp / stats.max_hp
        filled_width = int(ratio * self.HP_BAR_WIDTH)

        self.console.draw_rect(
            start_x,
            self.HP_BAR_Y,
            self.HP_BAR_WIDTH,
            1,
            ch=ord('█'),
            fg=UI_RED_DARK,
        )
        if filled_width > 0:
            self.console.draw_rect(
                start_x,
                self.HP_BAR_Y,
                filled_width,
                1,
                ch=ord('█'),
                fg=UI_RED,
            )

    def render_floor_info(self, floor: int):
        self.console.print(
            self.FLOOR_TEXT_X,
            self.FLOOR_TEXT_Y,
            f'Floor: {floor}',
            fg=UI_WHITE,
        )

    def render_message_log(self):
        logs = esper.get_component(MessageLog)
        if not logs:
            return

        _ent, log = logs[0]

        # Draw frame
        draw_titled_frame(
            self.console,
            self.MSG_BOX_X,
            self.MSG_BOX_Y,
            self.MSG_BOX_WIDTH,
            self.MSG_BOX_HEIGHT,
            title='Messages',
            fg=UI_WHITE,
            bg=(0, 0, 0),
        )

        usable_width = self.MSG_BOX_WIDTH - 4
        all_lines = []
        for msg in log.messages:
            all_lines.extend(wrap_message(msg, usable_width))

        visible_height = self.MSG_BOX_HEIGHT - 2

        # Resolve the visible slice and write back the clamped scroll position
        log.scroll_index, start_idx, end_idx = compute_visible_slice(len(all_lines), log.scroll_index, visible_height)
        visible_lines = all_lines[start_idx:end_idx]

        for i, line in enumerate(visible_lines):
            msg_x = self.MSG_BOX_X + 2
            msg_y = self.MSG_BOX_Y + 1 + i
            for text, color in line:
                self.console.print(x=msg_x, y=msg_y, string=text, fg=color)
                msg_x += len(text)
