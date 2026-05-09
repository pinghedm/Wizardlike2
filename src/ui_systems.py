import esper
import tcod
from components import Inventory, KnownRecipes, SpellInventory
from states import GameState

class MenuSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, player: int, spells_config: list):
        self.console = console
        self.player = player
        self.spells_config = spells_config
        self.state = GameState.EXPLORING
        self.menu_cursor = 0
        self.selected_for_crafting = {}

    def process(self):
        if self.state != GameState.COMBINING:
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
