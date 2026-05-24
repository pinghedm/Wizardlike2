import esper
import tcod

from src.components import (
    Configuration,
    CraftingModal,
    Inventory,
    KnownRecipes,
    MessageLog,
    PlayerTag,
    SpellInventory,
    SpellType,
    UIState,
)


def handle_crafting_modal_input(event: tcod.event.KeyDown):
    if not isinstance(event, tcod.event.KeyDown):
        return

    modals = esper.get_component(CraftingModal)
    if not modals:
        return

    ent, modal = modals[0]
    ui_state = esper.get_component(UIState)[0][1]

    player_entities = esper.get_components(Inventory, PlayerTag)
    if not player_entities:
        return
    player, (player_inv, _tag) = player_entities[0]

    inv_list = sorted(player_inv.items.keys())

    if event.sym == tcod.event.KeySym.ESCAPE:
        ui_state.selected_for_crafting = {}
        esper.delete_entity(ent)
        return

    if not inv_list:
        return

    if event.sym == tcod.event.KeySym.UP:
        modal.cursor = (modal.cursor - 1) % len(inv_list)

    elif event.sym == tcod.event.KeySym.DOWN:
        modal.cursor = (modal.cursor + 1) % len(inv_list)

    elif event.sym == tcod.event.KeySym.RIGHT:
        itype = inv_list[modal.cursor]
        if ui_state.selected_for_crafting.get(itype, 0) < player_inv.items[itype]:
            ui_state.selected_for_crafting[itype] = ui_state.selected_for_crafting.get(itype, 0) + 1

    elif event.sym == tcod.event.KeySym.LEFT:
        itype = inv_list[modal.cursor]
        if ui_state.selected_for_crafting.get(itype, 0) > 0:
            ui_state.selected_for_crafting[itype] -= 1

    elif event.sym == tcod.event.KeySym.RETURN:
        # Try Combining
        flat_selection = []
        for itype, count in ui_state.selected_for_crafting.items():
            flat_selection.extend([itype] * count)
        flat_selection = tuple(sorted(flat_selection))

        if not flat_selection:
            return

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
                    esper.delete_entity(ent)
                    return

        if not match_found:
            log = esper.get_component(MessageLog)[0][1]
            log.add_simple_message('The combination fizzles...', color=(255, 0, 0))
            ui_state.selected_for_crafting = {}
