import esper
import tcod

from components import Inventory, Item, KnownRecipes, MessageLog, Modal, Position, SpellInventory, SpellType
from map_objects import Map
from procgen import transition_to_next_floor
from states import MAIN_MENU_OPTIONS, DisplayMode, GameState, MenuOption
from systems import move_entity


def handle_exploring_input(event, player):
    game_state = esper.get_component(GameState)[0][1]

    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.EXPLORING

    dx, dy = 0, 0
    if event.sym == tcod.event.KeySym.UP:
        dy = -1
    elif event.sym == tcod.event.KeySym.DOWN:
        dy = 1
    elif event.sym == tcod.event.KeySym.LEFT:
        dx = -1
    elif event.sym == tcod.event.KeySym.RIGHT:
        dx = 1
    elif event.sym == tcod.event.KeySym.c:
        return DisplayMode.MENU
    elif event.sym == tcod.event.KeySym.PAGEUP:
        log = esper.get_component(MessageLog)[0][1]
        log.scroll_index += 1
    elif event.sym == tcod.event.KeySym.PAGEDOWN:
        log = esper.get_component(MessageLog)[0][1]
        log.scroll_index -= 1

    if dx != 0 or dy != 0:
        move_entity(player, dx, dy)
        player_pos = esper.component_for_entity(player, Position)
        player_inv = esper.component_for_entity(player, Inventory)
        log = esper.get_component(MessageLog)[0][1]

        # Pickup Logic
        for ent, (pos, item) in esper.get_components(Position, Item):
            if pos.x == player_pos.x and pos.y == player_pos.y:
                player_inv.items[item.type] = player_inv.items.get(item.type, 0) + 1
                log.add_simple_message(f'Picked up {item.type.name}!', color=(200, 200, 200))
                esper.delete_entity(ent)

        # Check for exit
        maps = esper.get_component(Map)
        if maps:
            game_map = maps[0][1]
            if game_map.tiles[player_pos.x][player_pos.y].is_exit:
                if game_state.floor >= 3:
                    log.add_simple_message('Level Complete!', color=(255, 255, 0))
                    raise SystemExit()
                else:
                    esper.create_entity(
                        Modal(message='You descend deeper into the dungeon...', on_close=transition_to_next_floor)
                    )

    return DisplayMode.EXPLORING


def handle_modal_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return

    modals = esper.get_component(Modal)
    if modals:
        ent, modal = modals[0]
        if modal.on_close:
            modal.on_close()
        esper.delete_entity(ent)


def handle_menu_input(event, menu_system):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.MENU

    if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.c:
        return DisplayMode.EXPLORING

    elif event.sym == tcod.event.KeySym.UP:
        menu_system.main_menu_cursor = (menu_system.main_menu_cursor - 1) % len(MAIN_MENU_OPTIONS)

    elif event.sym == tcod.event.KeySym.DOWN:
        menu_system.main_menu_cursor = (menu_system.main_menu_cursor + 1) % len(MAIN_MENU_OPTIONS)

    elif event.sym == tcod.event.KeySym.RETURN:
        selection = MAIN_MENU_OPTIONS[menu_system.main_menu_cursor]
        if selection == MenuOption.COMBINE:
            return DisplayMode.COMBINING
        elif selection == MenuOption.QUIT:
            raise SystemExit()

    return DisplayMode.MENU


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

                    log = esper.get_component(MessageLog)[0][1]
                    log.add_message(
                        [
                            ('SUCCESS: Crafted ', (255, 255, 255)),
                            (stype.name, (0, 255, 255)),
                            (f'! (+{charges} charges)', (255, 255, 255)),
                        ]
                    )
                    match_found = True
                    return DisplayMode.EXPLORING

        if not match_found:
            log = esper.get_component(MessageLog)[0][1]
            log.add_simple_message('The combination fizzles...', color=(255, 0, 0))
            menu_system.selected_for_crafting = {}

    return DisplayMode.COMBINING
