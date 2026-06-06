import esper

from src import persistence
from src.components import (
    Actor,
    Enemy,
    InputAction,
    Inventory,
    Item,
    ItemType,
    Keybindings,
    KnownRecipes,
    MessageLog,
    Modal,
    Position,
    RunStats,
    Shopkeeper,
    SpellInventory,
    StatusType,
    TargetingReticle,
    UIState,
)
from src.constants import (
    MAX_FLOORS,
    UI_CYAN,
    UI_GRAY,
    UI_RED,
    UI_SALMON,
    UI_WHITE,
    UI_YELLOW,
)
from src.ecs_helpers import (
    get_display_name,
    get_player,
    get_player_component,
    get_singleton,
    get_status,
    try_get_singleton,
)
from src.input_handlers.controller import move_delta
from src.map_objects import Map
from src.procgen import transition_to_next_floor
from src.shop import purchase_offer
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    CraftingView,
    DisplayMode,
    GameState,
    MenuOption,
)
from src.systems import (
    cast_spell,
    craft_known_spell,
    deal_damage,
    get_spell_config,
    is_game_active,
    is_reagent,
    match_recipe,
    move_entity,
)


def step_cursor(cursor: int, length: int, action: InputAction | None) -> int:
    """New cursor index after an up/down move, wrapping; 0 when the list is empty."""
    if length == 0:
        return 0
    cursor %= length
    if action == InputAction.MOVE_UP:
        return (cursor - 1) % length
    if action == InputAction.MOVE_DOWN:
        return (cursor + 1) % length
    return cursor


def handle_modal_input(action: InputAction | None):
    # Only Confirm dismisses a modal, so a movement input can't accidentally
    # confirm a descent or blow past the death screen.
    if action != InputAction.CONFIRM:
        return

    modals = esper.get_component(Modal)
    if modals:
        ent, modal = modals[0]
        if modal.on_close:
            modal.on_close()
        esper.delete_entity(ent)


def handle_game_over_input(action: InputAction | None):
    """The run-summary screen: Confirm returns to the title menu, nothing else acts."""
    if action == InputAction.CONFIRM:
        return DisplayMode.RETURN_TO_TITLE
    return DisplayMode.GAME_OVER


def _adjacent_shopkeeper(player_pos: Position) -> bool:
    """True if a shopkeeper is within one tile of the player (including their tile)."""
    for _ent, (pos, _sk) in esper.get_components(Position, Shopkeeper):
        if max(abs(pos.x - player_pos.x), abs(pos.y - player_pos.y)) <= 1:
            return True
    return False


def handle_exploring_input(action: InputAction | None):
    game_state = get_singleton(GameState)

    player = get_player()
    if player is None:
        return DisplayMode.EXPLORING
    player_pos = esper.component_for_entity(player, Position)

    if action == InputAction.CANCEL:
        return DisplayMode.MENU
    elif action == InputAction.OPEN_CRAFTING:
        return DisplayMode.COMBINING
    elif action == InputAction.OPEN_CASTING:
        return DisplayMode.CASTING
    elif action == InputAction.CONFIRM and _adjacent_shopkeeper(player_pos):
        return DisplayMode.SHOPPING
    elif action == InputAction.SCROLL_UP:
        get_singleton(MessageLog).scroll_index += 1
    elif action == InputAction.SCROLL_DOWN:
        get_singleton(MessageLog).scroll_index -= 1

    dx, dy = move_delta(action)
    if dx != 0 or dy != 0:
        # Default movement is uncapped (as fast as the player presses). Only a SLOW
        # status throttles it: each move sets a (doubled) cooldown via move_entity,
        # and we ignore further input until it elapses. Without slow, the cooldown
        # is left to decay but never gates input, keeping movement responsive.
        if get_status(player, StatusType.SLOW) and esper.component_for_entity(player, Actor).cooldown > 0:
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
                    color=UI_RED,
                )
                break

        move_entity(player, dx, dy)
        player_pos = esper.component_for_entity(player, Position)
        player_inv = esper.component_for_entity(player, Inventory)
        log = get_singleton(MessageLog)

        # Pickup Logic
        run_stats = try_get_singleton(RunStats)
        for ent, (pos, item) in esper.get_components(Position, Item):
            if pos.x == player_pos.x and pos.y == player_pos.y:
                player_inv.items[item.type] = player_inv.items.get(item.type, 0) + item.count
                log.add_simple_message(f'Picked up {item.count} {item.type.name}!', color=UI_GRAY)
                esper.delete_entity(ent)
                if item.type == ItemType.GOLD:
                    if run_stats:
                        run_stats.gold_collected += item.count
                    persistence.save_meta()
                elif run_stats:
                    run_stats.ingredients_collected[item.type] += item.count

        # Check for exit
        maps = esper.get_component(Map)
        if maps:
            game_map = maps[0][1]
            if game_map.tiles[player_pos.x][player_pos.y].is_exit:
                if game_state.floor >= MAX_FLOORS:
                    log.add_simple_message('Level Complete!', color=UI_YELLOW)
                    if run_stats:
                        run_stats.won = True
                    return DisplayMode.GAME_OVER
                else:
                    esper.create_entity(
                        Modal(
                            message='You descend deeper into the dungeon... (Press Enter)',
                            on_close=transition_to_next_floor,
                        )
                    )

    return DisplayMode.EXPLORING


def handle_settings_input(action: InputAction | None):
    ui_state = get_singleton(UIState)
    keybindings = esper.get_component(Keybindings)[0][1]
    actions = list(keybindings.bindings.keys())

    if action == InputAction.CANCEL:
        return DisplayMode.MENU
    elif action == InputAction.CONFIRM:
        # Arm the remap; try_capture_remap binds the next raw keypress.
        ui_state.remapping_action = actions[ui_state.settings_cursor]
    else:
        ui_state.settings_cursor = step_cursor(ui_state.settings_cursor, len(actions), action)

    return DisplayMode.SETTINGS


def handle_menu_input(action: InputAction | None):
    ui_state = get_singleton(UIState)

    # Title menu before a run starts, pause menu once a player exists.
    game_active = is_game_active()
    options = PAUSE_MENU_OPTIONS if game_active else TITLE_MENU_OPTIONS
    ui_state.main_menu_cursor %= len(options)

    if action == InputAction.CANCEL:
        # Cancel resumes an active game; at the title screen there is nothing
        # to resume, so stay on the menu.
        return DisplayMode.EXPLORING if game_active else DisplayMode.MENU

    elif action == InputAction.CONFIRM:
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

    else:
        ui_state.main_menu_cursor = step_cursor(ui_state.main_menu_cursor, len(options), action)

    return DisplayMode.MENU


def handle_combining_input(action: InputAction | None):
    ui_state = get_singleton(UIState)

    # Cycle between the manual experiment view and the spellbook.
    if action == InputAction.CYCLE_TAB:
        ui_state.crafting_view = (
            CraftingView.SPELLBOOK if ui_state.crafting_view == CraftingView.EXPERIMENT else CraftingView.EXPERIMENT
        )
        return DisplayMode.COMBINING

    # The crafting action or Cancel closes the whole screen from either view.
    if action in (InputAction.CANCEL, InputAction.OPEN_CRAFTING):
        return DisplayMode.EXPLORING

    if ui_state.crafting_view == CraftingView.SPELLBOOK:
        return _handle_spellbook_input(action, ui_state)
    return _handle_experiment_input(action, ui_state)


def _handle_experiment_input(action: InputAction | None, ui_state: UIState):
    """Manual ingredient combining: select reagents and combine to discover recipes."""
    player = get_player()
    if player is None:
        return DisplayMode.EXPLORING
    player_inv = esper.component_for_entity(player, Inventory)

    inv_list = sorted(i for i in player_inv.items if is_reagent(i))
    ui_state.crafting_cursor = step_cursor(ui_state.crafting_cursor, len(inv_list), action)

    if action == InputAction.MOVE_RIGHT:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) < player_inv.items[itype]:
                ui_state.selected_for_crafting[itype] = ui_state.selected_for_crafting.get(itype, 0) + 1

    elif action == InputAction.MOVE_LEFT:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) > 0:
                ui_state.selected_for_crafting[itype] -= 1

    elif action == InputAction.CONFIRM:
        # Try Combining
        flat_selection: list[ItemType] = []
        for itype, count in ui_state.selected_for_crafting.items():
            flat_selection.extend([itype] * count)
        sorted_selection = tuple(sorted(flat_selection))

        if not sorted_selection:
            return DisplayMode.COMBINING

        log = get_singleton(MessageLog)
        result = match_recipe(sorted_selection)

        if result is None:
            log.add_simple_message('The combination fizzles...', color=UI_RED)
            ui_state.selected_for_crafting = {}
            return DisplayMode.COMBINING

        stype, charges = result
        player_recipes = esper.component_for_entity(player, KnownRecipes)
        player_spell_inv = esper.component_for_entity(player, SpellInventory)

        # Record the recipe discovery
        if stype not in player_recipes.recipes:
            player_recipes.recipes[stype] = set()
            run_stats = try_get_singleton(RunStats)
            if run_stats:
                run_stats.spells_discovered += 1
        player_recipes.recipes[stype].add(sorted_selection)

        # PERSISTENT META-PROGRESSION: Save grimoire on discovery
        persistence.save_meta()

        # Grant charges
        player_spell_inv.spells[stype] = player_spell_inv.spells.get(stype, 0) + charges

        # Consume ingredients
        for itype, count in ui_state.selected_for_crafting.items():
            player_inv.items[itype] -= count

        log.add_message(
            [
                ('SUCCESS: Crafted ', UI_WHITE),
                (stype.name, UI_CYAN),
                (f'! (+{charges} charges)', UI_WHITE),
            ]
        )
        # Clear selection on success
        ui_state.selected_for_crafting = {}
        return DisplayMode.EXPLORING

    return DisplayMode.COMBINING


def _handle_spellbook_input(action: InputAction | None, ui_state: UIState):
    """Browse known recipes and instantly re-craft the selected one from stock."""
    player_recipes = get_player_component(KnownRecipes)
    if player_recipes is None:
        return DisplayMode.EXPLORING

    known = sorted(player_recipes.recipes.keys(), key=lambda s: s.name)
    ui_state.spellbook_cursor = step_cursor(ui_state.spellbook_cursor, len(known), action)

    if action == InputAction.CONFIRM and known:
        stype = known[ui_state.spellbook_cursor]
        log = get_singleton(MessageLog)
        charges = craft_known_spell(stype)
        s_conf = get_spell_config(stype.value)
        spell_name = s_conf.get('name', stype.name) if s_conf else stype.name

        if charges is None:
            log.add_simple_message(f'Not enough ingredients to craft {spell_name}.', color=UI_SALMON)
        else:
            log.add_message(
                [
                    ('Crafted ', UI_WHITE),
                    (spell_name, UI_CYAN),
                    (f'! (+{charges} charges)', UI_WHITE),
                ]
            )

    return DisplayMode.COMBINING


def handle_casting_input(action: InputAction | None):
    ui_state = get_singleton(UIState)

    player_spell_inv = get_player_component(SpellInventory)
    if player_spell_inv is None:
        return DisplayMode.EXPLORING

    # Filter spells to only those with charges
    available_spells = sorted(
        [s for s in player_spell_inv.spells if player_spell_inv.spells[s] > 0],
        key=lambda x: x.name,
    )
    ui_state.casting_cursor = step_cursor(ui_state.casting_cursor, len(available_spells), action)

    if action in (InputAction.CANCEL, InputAction.OPEN_CASTING):
        return DisplayMode.EXPLORING

    elif action == InputAction.CONFIRM:
        if available_spells:
            stype = available_spells[ui_state.casting_cursor]

            # Find spell config for range/radius
            s_conf = get_spell_config(stype.value)
            player_pos = get_player_component(Position)
            if s_conf and player_pos is not None:
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


def handle_targeting_input(action: InputAction | None):
    ui_state = get_singleton(UIState)
    reticles = esper.get_component(TargetingReticle)
    if not reticles:
        return DisplayMode.EXPLORING

    ret_ent, reticle = reticles[0]

    player_pos = get_player_component(Position)
    if player_pos is None:
        return DisplayMode.EXPLORING

    # Cancel or the casting action both back out to the spell picker (the input
    # that opened targeting also closes it).
    if action in (InputAction.CANCEL, InputAction.OPEN_CASTING):
        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.CASTING

    dx, dy = move_delta(action)
    if dx != 0 or dy != 0:
        new_x = reticle.x + dx
        new_y = reticle.y + dy

        # Check for map bounds and walkability
        maps = esper.get_component(Map)
        if maps:
            game_map = maps[0][1]
            if not game_map.is_walkable(new_x, new_y):
                return DisplayMode.TARGETING

        # Clamp to range (squared compare avoids a per-move sqrt).
        rdx = new_x - player_pos.x
        rdy = new_y - player_pos.y
        if rdx * rdx + rdy * rdy <= reticle.range**2:
            reticle.x = new_x
            reticle.y = new_y

    elif action == InputAction.CONFIRM:
        # EXECUTE SPELL
        if ui_state.active_targeting_spell_id is not None:
            cast_spell(
                spell_id=ui_state.active_targeting_spell_id,
                target_x=reticle.x,
                target_y=reticle.y,
            )

        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        # Back to the picker so the player can chain casts; they leave it with
        # Cancel or the casting action.
        return DisplayMode.CASTING

    return DisplayMode.TARGETING


def handle_shop_input(action: InputAction | None):
    ui_state = get_singleton(UIState)

    shopkeepers = esper.get_component(Shopkeeper)
    player_inv = get_player_component(Inventory)
    if not shopkeepers or player_inv is None:
        return DisplayMode.EXPLORING
    offers = shopkeepers[0][1].offers

    if action == InputAction.CANCEL:
        return DisplayMode.EXPLORING
    if not offers:
        return DisplayMode.SHOPPING

    ui_state.shop_cursor %= len(offers)
    offer = offers[ui_state.shop_cursor]
    max_qty = max(1, player_inv.items.get(ItemType.GOLD, 0) // offer.price)
    ui_state.shop_quantity = max(1, min(ui_state.shop_quantity, max_qty))

    if action in (InputAction.MOVE_UP, InputAction.MOVE_DOWN):
        ui_state.shop_cursor = step_cursor(ui_state.shop_cursor, len(offers), action)
        ui_state.shop_quantity = 1
    elif action == InputAction.MOVE_LEFT:
        ui_state.shop_quantity = max(1, ui_state.shop_quantity - 1)
    elif action == InputAction.MOVE_RIGHT:
        ui_state.shop_quantity = min(max_qty, ui_state.shop_quantity + 1)
    elif action == InputAction.CONFIRM:
        log = get_singleton(MessageLog)
        quantity = ui_state.shop_quantity
        if purchase_offer(offer, quantity):
            log.add_simple_message(f'Bought {quantity}x {offer.label}.', color=UI_CYAN)
        else:
            log.add_simple_message('Not enough gold.', color=UI_SALMON)
        ui_state.shop_quantity = 1

    return DisplayMode.SHOPPING
