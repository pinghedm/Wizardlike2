import esper
import tcod

from components import Inventory, KnownRecipes, MessageLog, Modal, SpellInventory, Stats
from states import MAIN_MENU_OPTIONS, DisplayMode, GameState


class MenuSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, player: int, spells_config: list):
        self.console = console
        self.player = player
        self.spells_config = spells_config
        self.main_menu_cursor = 0
        self.menu_cursor = 0
        self.selected_for_crafting = {}

    def process(self):
        game_state = esper.get_component(GameState)[0][1]

        if game_state.display_mode == DisplayMode.MENU:
            self.render_main_menu()
        elif game_state.display_mode == DisplayMode.COMBINING:
            self.render_combining_menu()

    def render_main_menu(self):
        self.console.clear(bg=(0, 0, 0))
        self.console.draw_frame(0, 0, self.console.width, self.console.height, title='Main Menu', fg=(255, 255, 255))

        for i, option in enumerate(MAIN_MENU_OPTIONS):
            color = (255, 255, 0) if i == self.main_menu_cursor else (255, 255, 255)
            self.console.print(
                self.console.width // 2 - 5,
                self.console.height // 2 - 1 + i,
                f'{"> " if i == self.main_menu_cursor else "  "}{option}',
                fg=color,
            )

    def render_combining_menu(self):
        self.console.clear(bg=(0, 0, 0))
        self.console.draw_frame(
            0, 0, self.console.width, self.console.height, title='Combine Items', fg=(255, 255, 255)
        )

        self.console.print(2, 2, 'SPELL COMBINING', fg=(255, 255, 0))
        player_inv = esper.component_for_entity(self.player, Inventory)
        inv_list = sorted(player_inv.items.keys())

        for i, itype in enumerate(inv_list):
            color = (255, 255, 255) if i == self.menu_cursor else (100, 100, 100)
            count = player_inv.items[itype]
            selected = self.selected_for_crafting.get(itype, 0)
            self.console.print(
                2,
                4 + (i * 2),
                f'{"> " if i == self.menu_cursor else "  "}{itype.name}: {count} (Selected: {selected})',
                fg=color,
            )

        self.console.print(
            2, self.console.height - 2, 'Arrows: Move | L/R: Select | Enter: Combine | C: Close', fg=(200, 200, 200)
        )

        player_recipes = esper.component_for_entity(self.player, KnownRecipes)
        player_spell_inv = esper.component_for_entity(self.player, SpellInventory)

        self.console.print(40, 2, 'SPELLBOOK', fg=(0, 255, 255))
        y_offset = 4

        self.console.print(40, y_offset, 'Charges', fg=(0, 200, 200))
        y_offset += 1
        for stype, charges in sorted(player_spell_inv.spells.items(), key=lambda x: x[0].name):
            self.console.print(40, y_offset, f'- {stype.name}: {charges}')
            y_offset += 1

        y_offset += 1
        self.console.print(40, y_offset, 'Known Recipes', fg=(0, 200, 200))
        y_offset += 1
        for stype in sorted(player_recipes.recipes.keys(), key=lambda x: x.name):
            self.console.print(40, y_offset, f'{stype.name}:', fg=(255, 255, 255))
            y_offset += 1
            for recipe in sorted(player_recipes.recipes[stype]):
                recipe_str = ' + '.join(itype.name for itype in recipe)
                self.console.print(42, y_offset, f'* {recipe_str}')
                y_offset += 1


class ModalSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console):
        self.console = console

    def process(self):
        for _ent, modal in esper.get_component(Modal):
            # Center the modal based on its own dimensions
            x = (self.console.width - modal.width) // 2
            y = (self.console.height - modal.height) // 2

            self.console.draw_frame(
                x=x, y=y, width=modal.width, height=modal.height, title='Message', fg=(255, 255, 255), bg=(0, 0, 0)
            )

            # Message
            self.console.print_box(
                x=x + 2,
                y=y + 2,
                width=modal.width - 4,
                height=modal.height - 4,
                string=modal.message,
                fg=(255, 255, 255),
            )

            self.console.print(
                x + modal.width // 2 - 10, y + modal.height - 2, 'Press any key to close', fg=(200, 200, 200)
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

        if game_state.display_mode != DisplayMode.EXPLORING:
            return

        self.render_hp_bar()
        self.render_floor_info(game_state.floor)
        self.render_message_log()

    def render_hp_bar(self):
        stats = esper.component_for_entity(self.player, Stats)
        hp_text = f'HP: {stats.hp}/{stats.max_hp}'
        self.console.print(self.HP_BAR_X, self.HP_BAR_Y, hp_text, fg=(255, 255, 255))

        start_x = self.HP_BAR_X + len(hp_text) + 1
        ratio = stats.hp / stats.max_hp
        filled_width = int(ratio * self.HP_BAR_WIDTH)

        self.console.draw_rect(start_x, self.HP_BAR_Y, self.HP_BAR_WIDTH, 1, ch=ord('\u2588'), fg=(50, 0, 0))
        if filled_width > 0:
            self.console.draw_rect(start_x, self.HP_BAR_Y, filled_width, 1, ch=ord('\u2588'), fg=(255, 0, 0))

    def render_floor_info(self, floor: int):
        self.console.print(
            self.FLOOR_TEXT_X,
            self.FLOOR_TEXT_Y,
            f'Floor: {floor}',
            fg=(255, 255, 255),
        )

    def render_message_log(self):
        logs = esper.get_component(MessageLog)
        if not logs:
            return

        _ent, log = logs[0]

        # Draw frame
        self.console.draw_frame(
            x=self.MSG_BOX_X,
            y=self.MSG_BOX_Y,
            width=self.MSG_BOX_WIDTH,
            height=self.MSG_BOX_HEIGHT,
            title='Messages',
            fg=(255, 255, 255),
            bg=(0, 0, 0),
        )

        usable_width = self.MSG_BOX_WIDTH - 4
        all_lines = []
        for msg in log.messages:
            all_lines.extend(self.wrap_message(msg, usable_width))

        visible_height = self.MSG_BOX_HEIGHT - 2

        # Clamp scroll index
        max_scroll = max(0, len(all_lines) - visible_height)
        log.scroll_index = max(0, min(log.scroll_index, max_scroll))

        # Determine slice to show
        # scroll_index = 0 means bottom, scroll_index = max_scroll means top
        end_idx = len(all_lines) - log.scroll_index
        start_idx = max(0, end_idx - visible_height)
        visible_lines = all_lines[start_idx:end_idx]

        for i, line in enumerate(visible_lines):
            msg_x = self.MSG_BOX_X + 2
            msg_y = self.MSG_BOX_Y + 1 + i
            for text, color in line:
                self.console.print(x=msg_x, y=msg_y, string=text, fg=color)
                msg_x += len(text)

    def wrap_message(self, segments, width):
        """Wrap a segmented message into multiple lines."""
        lines = []
        current_line = []
        current_line_len = 0

        for text, color in segments:
            words = text.split(' ')
            for i, word in enumerate(words):
                # Add space back if not the first word in the segment
                full_word = word + (' ' if i < len(words) - 1 else '')
                if not full_word:
                    continue

                if current_line_len + len(full_word) > width:
                    if current_line:
                        lines.append(current_line)
                    current_line = []
                    current_line_len = 0

                # Check if we should trim leading space on new line
                if current_line_len == 0 and full_word.startswith(' '):
                    full_word = full_word[1:]

                if full_word:
                    current_line.append((full_word, color))
                    current_line_len += len(full_word)

        if current_line:
            lines.append(current_line)
        return lines
