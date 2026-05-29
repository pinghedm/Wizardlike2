import math

import esper
import tcod

from src import persistence
from src.components import (
    Actor,
    Enemy,
    Inventory,
    Item,
    Keybindings,
    KnownRecipes,
    MessageLog,
    Modal,
    PlayerTag,
    Position,
    SpellInventory,
    StatusEffects,
    StatusType,
    TargetingReticle,
    UIState,
)
from src.constants import MAX_FLOORS
from src.map_objects import Map
from src.procgen import transition_to_next_floor
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    DisplayMode,
    GameState,
    MenuOption,
)
from src.systems import (
    cast_spell,
    deal_damage,
    get_display_name,
    get_spell_config,
    is_game_active,
    match_recipe,
    move_entity,
)


def handle_modal_input(event):
    # Only Enter dismisses a modal, so an arrow key can't accidentally confirm a
    # descent or blow past the death screen.
    if not isinstance(event, tcod.event.KeyDown) or event.sym != tcod.event.KeySym.RETURN:
        return

    modals = esper.get_component(Modal)
    if modals:
        ent, modal = modals[0]
        if modal.on_close:
            modal.on_close()
        esper.delete_entity(ent)


def _player_is_slowed(player: int) -> bool:
    """True if the player currently has an active SLOW status."""
    if not esper.has_component(player, StatusEffects):
        return False
    return StatusType.SLOW in esper.component_for_entity(player, StatusEffects).active


def handle_exploring_input(event):
    game_state = esper.get_component(GameState)[0][1]
    keybindings = esper.get_component(Keybindings)[0][1]

    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.EXPLORING

    player_entities = esper.get_components(Position, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    player, (player_pos, _tag) = player_entities[0]

    dx, dy = 0, 0
    if event.sym == keybindings.bindings['MOVE_UP']:
        dy = -1
    elif event.sym == keybindings.bindings['MOVE_DOWN']:
        dy = 1
    elif event.sym == keybindings.bindings['MOVE_LEFT']:
        dx = -1
    elif event.sym == keybindings.bindings['MOVE_RIGHT']:
        dx = 1
    elif event.sym == keybindings.bindings['CANCEL']:
        return DisplayMode.MENU
    elif event.sym == keybindings.bindings['OPEN_CRAFTING']:
        return DisplayMode.COMBINING
    elif event.sym == keybindings.bindings['OPEN_CASTING']:
        return DisplayMode.CASTING
    elif event.sym == tcod.event.KeySym.PAGEUP:
        log = esper.get_component(MessageLog)[0][1]
        log.scroll_index += 1
    elif event.sym == tcod.event.KeySym.PAGEDOWN:
        log = esper.get_component(MessageLog)[0][1]
        log.scroll_index -= 1

    if dx != 0 or dy != 0:
        # Default movement is uncapped (as fast as the player presses). Only a SLOW
        # status throttles it: each move sets a (doubled) cooldown via move_entity,
        # and we ignore further input until it elapses. Without slow, the cooldown
        # is left to decay but never gates input, keeping movement responsive.
        if _player_is_slowed(player) and esper.component_for_entity(player, Actor).cooldown > 0:
            return DisplayMode.EXPLORING

        # Bumping an enemy deals bump damage to the player (combat is decoupled from
        # movement). move_entity then walks the player onto a non-blocking enemy, or
        # is stopped by a blocking one.
        target_x, target_y = player_pos.x + dx, player_pos.y + dy
        for ent, (epos, enemy) in esper.get_components(Position, Enemy):
            if epos.x == target_x and epos.y == target_y:
                deal_damage(
                    player,
                    enemy.bump_damage,
                    f'You bump into a {get_display_name(ent)} and take damage!',
                    color=(255, 0, 0),
                )
                break

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
                if game_state.floor >= MAX_FLOORS:
                    log.add_simple_message('Level Complete!', color=(255, 255, 0))
                    raise SystemExit()
                else:
                    esper.create_entity(
                        Modal(
                            message='You descend deeper into the dungeon... (Press Enter)',
                            on_close=transition_to_next_floor,
                        )
                    )

    return DisplayMode.EXPLORING


def handle_settings_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.SETTINGS

    ui_state = esper.get_component(UIState)[0][1]
    kb_ent, keybindings = esper.get_component(Keybindings)[0]

    actions = list(keybindings.bindings.keys())

    if ui_state.remapping_action:
        # We are waiting for a new key
        keybindings.bindings[ui_state.remapping_action] = event.sym
        ui_state.remapping_action = None
        return DisplayMode.SETTINGS

    if event.sym == keybindings.bindings['CANCEL']:
        return DisplayMode.MENU

    elif event.sym == keybindings.bindings['MOVE_UP']:
        ui_state.settings_cursor = (ui_state.settings_cursor - 1) % len(actions)

    elif event.sym == keybindings.bindings['MOVE_DOWN']:
        ui_state.settings_cursor = (ui_state.settings_cursor + 1) % len(actions)

    elif event.sym == keybindings.bindings['CONFIRM']:
        ui_state.remapping_action = actions[ui_state.settings_cursor]

    return DisplayMode.SETTINGS


def handle_menu_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.MENU

    ui_state = esper.get_component(UIState)[0][1]

    # Title menu before a run starts, pause menu once a player exists.
    game_active = is_game_active()
    options = PAUSE_MENU_OPTIONS if game_active else TITLE_MENU_OPTIONS
    ui_state.main_menu_cursor %= len(options)

    if event.sym == tcod.event.KeySym.ESCAPE:
        # Escape resumes an active game; at the title screen there is nothing
        # to resume, so stay on the menu.
        return DisplayMode.EXPLORING if game_active else DisplayMode.MENU

    elif event.sym == tcod.event.KeySym.UP:
        ui_state.main_menu_cursor = (ui_state.main_menu_cursor - 1) % len(options)

    elif event.sym == tcod.event.KeySym.DOWN:
        ui_state.main_menu_cursor = (ui_state.main_menu_cursor + 1) % len(options)

    elif event.sym == tcod.event.KeySym.RETURN:
        selection = options[ui_state.main_menu_cursor]
        if selection == MenuOption.QUIT:
            return DisplayMode.EXITING
        elif selection == MenuOption.RESUME:
            return DisplayMode.EXPLORING
        elif selection == MenuOption.SAVE:
            return DisplayMode.SAVING
        elif selection == MenuOption.SETTINGS:
            return DisplayMode.SETTINGS
        elif selection in (MenuOption.CONTINUE, MenuOption.LOAD):
            if persistence.has_save():
                return DisplayMode.LOADING_SAVE
        elif selection == MenuOption.NEW_GAME:
            return DisplayMode.STARTING_NEW_GAME

    return DisplayMode.MENU


def handle_combining_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.COMBINING

    ui_state = esper.get_component(UIState)[0][1]
    keybindings = esper.get_component(Keybindings)[0][1]

    player_entities = esper.get_components(Inventory, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    player, (player_inv, _tag) = player_entities[0]

    inv_list = sorted(player_inv.items.keys())

    if inv_list:
        ui_state.crafting_cursor %= len(inv_list)
    else:
        ui_state.crafting_cursor = 0

    if event.sym == keybindings.bindings['CANCEL'] or event.sym == keybindings.bindings['OPEN_CRAFTING']:
        return DisplayMode.EXPLORING

    elif event.sym == keybindings.bindings['MOVE_UP']:
        if inv_list:
            ui_state.crafting_cursor = (ui_state.crafting_cursor - 1) % len(inv_list)

    elif event.sym == keybindings.bindings['MOVE_DOWN']:
        if inv_list:
            ui_state.crafting_cursor = (ui_state.crafting_cursor + 1) % len(inv_list)

    elif event.sym == keybindings.bindings['MOVE_RIGHT']:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) < player_inv.items[itype]:
                ui_state.selected_for_crafting[itype] = ui_state.selected_for_crafting.get(itype, 0) + 1

    elif event.sym == keybindings.bindings['MOVE_LEFT']:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) > 0:
                ui_state.selected_for_crafting[itype] -= 1

    elif event.sym == keybindings.bindings['CONFIRM']:
        # Try Combining
        flat_selection = []
        for itype, count in ui_state.selected_for_crafting.items():
            flat_selection.extend([itype] * count)
        flat_selection = tuple(sorted(flat_selection))

        if not flat_selection:
            return DisplayMode.COMBINING

        log = esper.get_component(MessageLog)[0][1]
        result = match_recipe(flat_selection)

        if result is None:
            log.add_simple_message('The combination fizzles...', color=(255, 0, 0))
            ui_state.selected_for_crafting = {}
            return DisplayMode.COMBINING

        stype, charges = result
        player_recipes = esper.component_for_entity(player, KnownRecipes)
        player_spell_inv = esper.component_for_entity(player, SpellInventory)

        # Record the recipe discovery
        if stype not in player_recipes.recipes:
            player_recipes.recipes[stype] = set()
        player_recipes.recipes[stype].add(flat_selection)

        # PERSISTENT META-PROGRESSION: Save grimoire on discovery
        persistence.save_grimoire(player_recipes.recipes)

        # Grant charges
        player_spell_inv.spells[stype] = player_spell_inv.spells.get(stype, 0) + charges

        # Consume ingredients
        for itype, count in ui_state.selected_for_crafting.items():
            player_inv.items[itype] -= count

        log.add_message(
            [
                ('SUCCESS: Crafted ', (255, 255, 255)),
                (stype.name, (0, 255, 255)),
                (f'! (+{charges} charges)', (255, 255, 255)),
            ]
        )
        # Clear selection on success
        ui_state.selected_for_crafting = {}
        return DisplayMode.EXPLORING

    return DisplayMode.COMBINING


def handle_casting_input(event):
    if not isinstance(event, tcod.event.KeyDown):
        return DisplayMode.CASTING

    ui_state = esper.get_component(UIState)[0][1]
    keybindings = esper.get_component(Keybindings)[0][1]

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

    if event.sym == keybindings.bindings['CANCEL'] or event.sym == keybindings.bindings['OPEN_CASTING']:
        return DisplayMode.EXPLORING

    elif event.sym == keybindings.bindings['MOVE_UP']:
        if available_spells:
            ui_state.casting_cursor = (ui_state.casting_cursor - 1) % len(available_spells)

    elif event.sym == keybindings.bindings['MOVE_DOWN']:
        if available_spells:
            ui_state.casting_cursor = (ui_state.casting_cursor + 1) % len(available_spells)

    elif event.sym == keybindings.bindings['CONFIRM']:
        if available_spells:
            stype = available_spells[ui_state.casting_cursor]

            # Find spell config for range/radius
            s_conf = get_spell_config(stype.value)
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
    keybindings = esper.get_component(Keybindings)[0][1]
    reticles = esper.get_component(TargetingReticle)
    if not reticles:
        return DisplayMode.EXPLORING

    ret_ent, reticle = reticles[0]

    player_entities = esper.get_components(Position, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    _player, (player_pos, _tag) = player_entities[0]

    if event.sym == keybindings.bindings['CANCEL']:
        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.CASTING

    dx, dy = 0, 0
    if event.sym == keybindings.bindings['MOVE_UP']:
        dy = -1
    elif event.sym == keybindings.bindings['MOVE_DOWN']:
        dy = 1
    elif event.sym == keybindings.bindings['MOVE_LEFT']:
        dx = -1
    elif event.sym == keybindings.bindings['MOVE_RIGHT']:
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

    elif event.sym == keybindings.bindings['CONFIRM']:
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
