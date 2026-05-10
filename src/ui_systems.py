import esper
import tcod
from components import Inventory, KnownRecipes, SpellInventory, Stats
from states import DisplayMode

class MenuSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, player: int, spells_config: list, game_state: 'GameState'):
        self.console = console
        self.player = player
        self.spells_config = spells_config
        self.game_state = game_state
        self.menu_cursor = 0
        self.selected_for_crafting = {}

    def process(self):
        if self.game_state.display_mode != DisplayMode.COMBINING:
            return

        self.console.clear(bg=(0, 0, 0))
        self.console.draw_frame(0, 0, self.console.width, self.console.height, title='Menu', fg=(255, 255, 255))

        self.console.print(2, 2, 'SPELL COMBINING', fg=(255, 255, 0))
        player_inv = esper.component_for_entity(self.player, Inventory)
        inv_list = sorted(player_inv.items.keys())
        
        for i, itype in enumerate(inv_list):
            color = (255, 255, 255) if i == self.menu_cursor else (100, 100, 100)
            count = player_inv.items[itype]
            selected = self.selected_for_crafting.get(itype, 0)
            self.console.print(
                2, 4 + (i * 2), 
                f'{"> " if i == self.menu_cursor else "  "}{itype.name}: {count} (Selected: {selected})', 
                fg=color
            )
        
        self.console.print(
            2, self.console.height - 2, 
            'Arrows: Move | L/R: Select | Enter: Combine | C: Close', 
            fg=(200, 200, 200)
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

class HUDSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, player: int, game_state: 'GameState'):
        self.console = console
        self.player = player
        self.game_state = game_state

    def process(self):
        if self.game_state.display_mode != DisplayMode.EXPLORING:
            return
        
        stats = esper.component_for_entity(self.player, Stats)
        
        # Render HP Text
        hp_text = f'HP: {stats.hp}/{stats.max_hp}'
        self.console.print(2, self.console.height - 2, hp_text, fg=(255, 255, 255))
        
        # Render HP Bar
        hp_bar_width = 20
        # Position bar dynamically after the text
        start_x = 2 + len(hp_text) + 1
        ratio = stats.hp / stats.max_hp
        filled_width = int(ratio * hp_bar_width)
        
        # Background of bar
        self.console.draw_rect(start_x, self.console.height - 2, hp_bar_width, 1, ch=ord('\u2588'), fg=(50, 0, 0))
        # Filled part
        if filled_width > 0:
            self.console.draw_rect(start_x, self.console.height - 2, filled_width, 1, ch=ord('\u2588'), fg=(255, 0, 0))
        
        # Render Floor
        self.console.print(self.console.width - 15, self.console.height - 2, f'Floor: {self.game_state.floor}', fg=(255, 255, 255))
