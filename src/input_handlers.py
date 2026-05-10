import esper
import tcod
from components import Inventory, Item, KnownRecipes, Position, SpellInventory, SpellType
from states import DisplayMode

def handle_exploring_input(event, player, game_map, movement_system):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.EXPLORING

    dx, dy = 0, 0
    if event.sym == tcod.event.KeySym.UP: dy = -1
    elif event.sym == tcod.event.KeySym.DOWN: dy = 1
    elif event.sym == tcod.event.KeySym.LEFT: dx = -1
    elif event.sym == tcod.event.KeySym.RIGHT: dx = 1
    elif event.sym == tcod.event.KeySym.c:
        return DisplayMode.COMBINING

    if dx != 0 or dy != 0:
        movement_system.move_entity(player, dx, dy)
        player_pos = esper.component_for_entity(player, Position)
        player_inv = esper.component_for_entity(player, Inventory)
        
        # Pickup Logic
        for ent, (pos, item) in esper.get_components(Position, Item):
            if pos.x == player_pos.x and pos.y == player_pos.y:
                player_inv.items[item.type] = player_inv.items.get(item.type, 0) + 1
                print(f'Picked up {item.type.name}!')
                esper.delete_entity(ent)

        # Check for exit
        if game_map.tiles[player_pos.x][player_pos.y].is_exit:
            print('Level Complete!')
            raise SystemExit()

    return DisplayMode.EXPLORING

def handle_combining_input(event, player, menu_system, spells_config):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.COMBINING

    player_inv = esper.component_for_entity(player, Inventory)
    inv_list = sorted(player_inv.items.keys())
    
    if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.c:
        return DisplayMode.EXPLORING
    
    elif event.sym == tcod.event.KeySym.UP:
        if inv_list:
            menu_system.menu_cursor = (menu_system.menu_cursor - 1) % len(inv_list)
    
    elif event.sym == tcod.event.KeySym.DOWN:
        if inv_list:
            menu_system.menu_cursor = (menu_system.menu_cursor + 1) % len(inv_list)
    
    elif event.sym == tcod.event.KeySym.RIGHT:
        if inv_list:
            itype = inv_list[menu_system.menu_cursor]
            if menu_system.selected_for_crafting.get(itype, 0) < player_inv.items[itype]:
                menu_system.selected_for_crafting[itype] = menu_system.selected_for_crafting.get(itype, 0) + 1
    
    elif event.sym == tcod.event.KeySym.LEFT:
        if inv_list:
            itype = inv_list[menu_system.menu_cursor]
            if menu_system.selected_for_crafting.get(itype, 0) > 0:
                menu_system.selected_for_crafting[itype] -= 1
    
    elif event.sym == tcod.event.KeySym.RETURN:
        # Try Combining
        flat_selection = []
        for itype, count in menu_system.selected_for_crafting.items():
            flat_selection.extend([itype] * count)
        flat_selection = tuple(sorted(flat_selection))
        
        if not flat_selection:
            return DisplayMode.COMBINING

        match_found = False
        for s_conf in spells_config:
            for r_data in s_conf['recipes']:
                if r_data['ingredients'] == flat_selection:
                    stype = SpellType(s_conf['id'])
                    player_recipes = esper.component_for_entity(player, KnownRecipes)
                    player_spell_inv = esper.component_for_entity(player, SpellInventory)
                    
                    # Record the recipe discovery
                    if stype not in player_recipes.recipes:
                        player_recipes.recipes[stype] = set()
                    player_recipes.recipes[stype].add(flat_selection)
                    
                    # Grant charges
                    charges = r_data['charges']
                    player_spell_inv.spells[stype] = player_spell_inv.spells.get(stype, 0) + charges
                    
                    # Consume ingredients
                    for itype, count in menu_system.selected_for_crafting.items():
                        player_inv.items[itype] -= count
                    
                    print(f'SUCCESS: Crafted {stype.name}! (+{charges} charges)')
                    match_found = True
                    return DisplayMode.EXPLORING
        
        if not match_found:
            print('The combination fizzles...')
            menu_system.selected_for_crafting = {}

    return DisplayMode.COMBINING
