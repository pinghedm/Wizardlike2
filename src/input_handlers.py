import math

import esper
import tcod

from components import (
    Configuration,
    Inventory,
    Item,
    KnownRecipes,
    MessageLog,
    Modal,
    PlayerTag,
    Position,
    SpellInventory,
    SpellType,
    TargetingReticle,
    UIState,
)
from map_objects import Map
from procgen import transition_to_next_floor
from states import MAIN_MENU_OPTIONS, DisplayMode, GameState, MenuOption
from systems import cast_spell, move_entity


def handle_exploring_input(event):
    game_state = esper.get_component(GameState)[0][1]

    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.EXPLORING

    player_entities = esper.get_components(Position, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    player, (player_pos, _tag) = player_entities[0]

    dx, dy = 0, 0
    if event.sym == tcod.event.KeySym.UP:
        dy = -1
    elif event.sym == tcod.event.KeySym.DOWN:
        dy = 1
    elif event.sym == tcod.event.KeySym.LEFT:
        dx = -1
    elif event.sym == tcod.event.KeySym.RIGHT:
        dx = 1
    elif event.sym == tcod.event.KeySym.ESCAPE:
        return DisplayMode.MENU
    elif event.sym == tcod.event.KeySym.c:
        return DisplayMode.COMBINING
    elif event.sym == tcod.event.KeySym.s:
        return DisplayMode.CASTING
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
                        Modal(
                            message='You descend deeper into the dungeon...',
                            on_close=transition_to_next_floor,
                        )
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


def handle_menu_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.MENU

    ui_state = esper.get_component(UIState)[0][1]

    if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.c:
        return DisplayMode.EXPLORING

    elif event.sym == tcod.event.KeySym.UP:
        ui_state.main_menu_cursor = (ui_state.main_menu_cursor - 1) % len(MAIN_MENU_OPTIONS)

    elif event.sym == tcod.event.KeySym.DOWN:
        ui_state.main_menu_cursor = (ui_state.main_menu_cursor + 1) % len(MAIN_MENU_OPTIONS)

    elif event.sym == tcod.event.KeySym.RETURN:
        selection = MAIN_MENU_OPTIONS[ui_state.main_menu_cursor]
        if selection == MenuOption.QUIT:
            raise SystemExit()

    return DisplayMode.MENU


def handle_combining_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.COMBINING

    ui_state = esper.get_component(UIState)[0][1]

    player_entities = esper.get_components(Inventory, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    player, (player_inv, _tag) = player_entities[0]

    inv_list = sorted(player_inv.items.keys())

    if inv_list:
        ui_state.crafting_cursor %= len(inv_list)
    else:
        ui_state.crafting_cursor = 0

    if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.c:
        return DisplayMode.EXPLORING

    elif event.sym == tcod.event.KeySym.UP:
        if inv_list:
            ui_state.crafting_cursor = (ui_state.crafting_cursor - 1) % len(inv_list)

    elif event.sym == tcod.event.KeySym.DOWN:
        if inv_list:
            ui_state.crafting_cursor = (ui_state.crafting_cursor + 1) % len(inv_list)

    elif event.sym == tcod.event.KeySym.RIGHT:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) < player_inv.items[itype]:
                ui_state.selected_for_crafting[itype] = ui_state.selected_for_crafting.get(itype, 0) + 1

    elif event.sym == tcod.event.KeySym.LEFT:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) > 0:
                ui_state.selected_for_crafting[itype] -= 1

    elif event.sym == tcod.event.KeySym.RETURN:
        # Try Combining
        flat_selection = []
        for itype, count in ui_state.selected_for_crafting.items():
            flat_selection.extend([itype] * count)
        flat_selection = tuple(sorted(flat_selection))

        if not flat_selection:
            return DisplayMode.COMBINING

        configs = esper.get_component(Configuration)[0][1]
        spells_config = configs.spells

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
                    for itype, count in ui_state.selected_for_crafting.items():
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
                    # Clear selection on success
                    ui_state.selected_for_crafting = {}
                    return DisplayMode.EXPLORING

        if not match_found:
            log = esper.get_component(MessageLog)[0][1]
            log.add_simple_message('The combination fizzles...', color=(255, 0, 0))
            ui_state.selected_for_crafting = {}

    return DisplayMode.COMBINING


def handle_casting_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.CASTING

    ui_state = esper.get_component(UIState)[0][1]

    player_entities = esper.get_components(SpellInventory, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    _player, (player_spell_inv, _tag) = player_entities[0]

    # Filter spells to only those with charges
    available_spells = sorted(
        [s for s in player_spell_inv.spells if player_spell_inv.spells[s] > 0],
        key=lambda x: x.name,
    )

    if available_spells:
        ui_state.casting_cursor %= len(available_spells)
    else:
        ui_state.casting_cursor = 0

    if event.sym == tcod.event.KeySym.ESCAPE or event.sym == tcod.event.KeySym.s:
        return DisplayMode.EXPLORING

    elif event.sym == tcod.event.KeySym.UP:
        if available_spells:
            ui_state.casting_cursor = (ui_state.casting_cursor - 1) % len(available_spells)

    elif event.sym == tcod.event.KeySym.DOWN:
        if available_spells:
            ui_state.casting_cursor = (ui_state.casting_cursor + 1) % len(available_spells)

    elif event.sym == tcod.event.KeySym.RETURN:
        if available_spells:
            stype = available_spells[ui_state.casting_cursor]

            configs = esper.get_component(Configuration)[0][1]
            spells_config = configs.spells

            # Find spell config for range/radius
            s_conf = next((s for s in spells_config if s['id'] == stype.value), None)
            if s_conf:
                player_entities = esper.get_components(Position, PlayerTag)
                _player, (player_pos, _tag) = player_entities[0]

                ui_state.active_targeting_spell_id = stype.value

                # Create targeting reticle
                esper.create_entity(
                    TargetingReticle(
                        x=player_pos.x,
                        y=player_pos.y,
                        range=s_conf.get('range', 0),
                        radius=s_conf.get('radius', 0),
                    )
                )
                return DisplayMode.TARGETING

    return DisplayMode.CASTING


def handle_targeting_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.TARGETING

    ui_state = esper.get_component(UIState)[0][1]
    reticles = esper.get_component(TargetingReticle)
    if not reticles:
        return DisplayMode.EXPLORING

    ret_ent, reticle = reticles[0]

    player_entities = esper.get_components(Position, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    _player, (player_pos, _tag) = player_entities[0]

    if event.sym == tcod.event.KeySym.ESCAPE:
        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.CASTING

    dx, dy = 0, 0
    if event.sym == tcod.event.KeySym.UP:
        dy = -1
    elif event.sym == tcod.event.KeySym.DOWN:
        dy = 1
    elif event.sym == tcod.event.KeySym.LEFT:
        dx = -1
    elif event.sym == tcod.event.KeySym.RIGHT:
        dx = 1

    if dx != 0 or dy != 0:
        new_x = reticle.x + dx
        new_y = reticle.y + dy

        # Check for map bounds and walkability
        maps = esper.get_component(Map)
        if maps:
            game_map = maps[0][1]
            if not game_map.is_walkable(new_x, new_y):
                return DisplayMode.TARGETING

        # Clamp to range
        dist = math.sqrt((new_x - player_pos.x) ** 2 + (new_y - player_pos.y) ** 2)
        if dist <= reticle.range:
            reticle.x = new_x
            reticle.y = new_y

    elif event.sym == tcod.event.KeySym.RETURN:
        # EXECUTE SPELL
        cast_spell(
            spell_id=ui_state.active_targeting_spell_id,
            target_x=reticle.x,
            target_y=reticle.y,
        )

        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.EXPLORING

    return DisplayMode.TARGETING
