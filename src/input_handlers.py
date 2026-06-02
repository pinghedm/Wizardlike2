import math

import esper
import tcod
from tcod.sdl.joystick import ControllerAxis, ControllerButton

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
    PlayerTag,
    Position,
    RunStats,
    Shopkeeper,
    SpellInventory,
    StatusEffects,
    StatusType,
    TargetingReticle,
    UIState,
)
from src.constants import MAX_FLOORS
from src.ecs_helpers import try_get_singleton
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
    get_display_name,
    get_spell_config,
    is_game_active,
    is_reagent,
    match_recipe,
    move_entity,
)

# Controller buttons mapped to the logical actions the keyboard also binds. The
# d-pad moves; A/B confirm/cancel; X/Y open casting/crafting; both shoulders cycle
# tabs; Start cancels (pause / back out).
CONTROLLER_ACTIONS: dict[ControllerButton, InputAction] = {
    ControllerButton.DPAD_UP: InputAction.MOVE_UP,
    ControllerButton.DPAD_DOWN: InputAction.MOVE_DOWN,
    ControllerButton.DPAD_LEFT: InputAction.MOVE_LEFT,
    ControllerButton.DPAD_RIGHT: InputAction.MOVE_RIGHT,
    ControllerButton.A: InputAction.CONFIRM,
    ControllerButton.B: InputAction.CANCEL,
    ControllerButton.X: InputAction.OPEN_CASTING,
    ControllerButton.Y: InputAction.OPEN_CRAFTING,
    ControllerButton.LEFTSHOULDER: InputAction.CYCLE_TAB,
    ControllerButton.RIGHTSHOULDER: InputAction.CYCLE_TAB,
    ControllerButton.START: InputAction.CANCEL,
}

# How a movement action displaces the cursor / player on each axis.
MOVE_DELTAS: dict[InputAction, tuple[int, int]] = {
    InputAction.MOVE_UP: (0, -1),
    InputAction.MOVE_DOWN: (0, 1),
    InputAction.MOVE_LEFT: (-1, 0),
    InputAction.MOVE_RIGHT: (1, 0),
}


def resolve_action(event: tcod.event.Event, keybindings: Keybindings) -> InputAction | None:
    """Map a raw input event to the logical action it triggers, or None.

    Keyboard presses resolve through the (remappable) keymap; controller button
    presses resolve through a parallel fixed map. Button releases, axis motion,
    unbound keys, and unmapped buttons all yield None. This is the single point
    where both input devices become the InputActions the handlers speak.
    """
    if isinstance(event, tcod.event.KeyDown):
        for action, sym in keybindings.bindings.items():
            if sym == event.sym:
                return action
        return None
    if isinstance(event, tcod.event.ControllerButton):
        return CONTROLLER_ACTIONS.get(event.button) if event.pressed else None
    return None


def try_capture_remap(event: tcod.event.Event) -> bool:
    """Bind the next raw keypress to a pending Settings remap, if one is waiting.

    Returns True when the event was consumed as a remap. This bypasses
    resolve_action on purpose: the captured key may currently be bound to another
    action, and we want the literal key, not its current meaning.
    """
    ui_state = esper.get_component(UIState)[0][1]
    if ui_state.remapping_action is None or not isinstance(event, tcod.event.KeyDown):
        return False
    keybindings = esper.get_component(Keybindings)[0][1]
    keybindings.bindings[ui_state.remapping_action] = event.sym
    ui_state.remapping_action = None
    return True


class AnalogInput:
    """Translates the left stick and triggers into discrete, repeating actions.

    Sticks and triggers stream axis values rather than press events, so this holds
    the latest value per axis and derives one active action: the left stick acts
    as a 4-way pad (dominant axis wins) for movement, and the triggers scroll the
    log (L2 up, R2 down). A high engage threshold with a lower release threshold
    (hysteresis) avoids edge jitter, and a repeat interval makes a held stick or
    trigger step like a held key. Time is injected so repeats stay deterministic.
    """

    STICK_ENGAGE = 16384
    STICK_RELEASE = 11000
    TRIGGER_ENGAGE = 16384
    TRIGGER_RELEASE = 8000
    REPEAT_INTERVAL = 0.12

    def __init__(self):
        self.left_x = 0
        self.left_y = 0
        self.trigger_left = 0
        self.trigger_right = 0
        self.active: InputAction | None = None
        self.next_repeat = 0.0

    def update(self, event: tcod.event.ControllerAxis, now: float) -> InputAction | None:
        """Record an axis value; return an action to fire now if it just engaged."""
        if event.axis == ControllerAxis.LEFTX:
            self.left_x = event.value
        elif event.axis == ControllerAxis.LEFTY:
            self.left_y = event.value
        elif event.axis == ControllerAxis.TRIGGERLEFT:
            self.trigger_left = event.value
        elif event.axis == ControllerAxis.TRIGGERRIGHT:
            self.trigger_right = event.value
        else:
            return None

        desired = self._desired_action()
        if desired == self.active:
            return None
        self.active = desired
        if desired is None:
            return None
        self.next_repeat = now + self.REPEAT_INTERVAL
        return desired

    def tick(self, now: float) -> InputAction | None:
        """Return the held action if it is due to repeat, else None."""
        if self.active is None or now < self.next_repeat:
            return None
        self.next_repeat = now + self.REPEAT_INTERVAL
        return self.active

    def _desired_action(self) -> InputAction | None:
        # Triggers take precedence over the stick; L2 scrolls up, R2 down.
        if self.trigger_right >= self._trigger_threshold(InputAction.SCROLL_DOWN):
            return InputAction.SCROLL_DOWN
        if self.trigger_left >= self._trigger_threshold(InputAction.SCROLL_UP):
            return InputAction.SCROLL_UP

        threshold = self.STICK_RELEASE if self.active in MOVE_DELTAS else self.STICK_ENGAGE
        if max(abs(self.left_x), abs(self.left_y)) < threshold:
            return None
        if abs(self.left_x) >= abs(self.left_y):
            return InputAction.MOVE_RIGHT if self.left_x > 0 else InputAction.MOVE_LEFT
        return InputAction.MOVE_DOWN if self.left_y > 0 else InputAction.MOVE_UP

    def _trigger_threshold(self, action: InputAction) -> int:
        return self.TRIGGER_RELEASE if self.active == action else self.TRIGGER_ENGAGE


def controller_binding_label(action: InputAction) -> str:
    """The controller buttons bound to an action, by enum name ('' if none)."""
    return ' / '.join(button.name for button, bound in CONTROLLER_ACTIONS.items() if bound == action)


def note_controller_button(button: ControllerButton) -> None:
    """Record the last controller button pressed, for the Settings live readout."""
    esper.get_component(UIState)[0][1].last_controller_input = button.name


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


def _player_is_slowed(player: int) -> bool:
    """True if the player currently has an active SLOW status."""
    if not esper.has_component(player, StatusEffects):
        return False
    return StatusType.SLOW in esper.component_for_entity(player, StatusEffects).active


def _adjacent_shopkeeper(player_pos: Position) -> bool:
    """True if a shopkeeper is within one tile of the player (including their tile)."""
    for _ent, (pos, _sk) in esper.get_components(Position, Shopkeeper):
        if max(abs(pos.x - player_pos.x), abs(pos.y - player_pos.y)) <= 1:
            return True
    return False


def handle_exploring_input(action: InputAction | None):
    game_state = esper.get_component(GameState)[0][1]

    player_entities = esper.get_components(Position, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    player, (player_pos, _tag) = player_entities[0]

    if action == InputAction.CANCEL:
        return DisplayMode.MENU
    elif action == InputAction.OPEN_CRAFTING:
        return DisplayMode.COMBINING
    elif action == InputAction.OPEN_CASTING:
        return DisplayMode.CASTING
    elif action == InputAction.CONFIRM and _adjacent_shopkeeper(player_pos):
        return DisplayMode.SHOPPING
    elif action == InputAction.SCROLL_UP:
        esper.get_component(MessageLog)[0][1].scroll_index += 1
    elif action == InputAction.SCROLL_DOWN:
        esper.get_component(MessageLog)[0][1].scroll_index -= 1

    dx, dy = MOVE_DELTAS.get(action, (0, 0))
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
        run_stats = try_get_singleton(RunStats)
        for ent, (pos, item) in esper.get_components(Position, Item):
            if pos.x == player_pos.x and pos.y == player_pos.y:
                player_inv.items[item.type] = player_inv.items.get(item.type, 0) + item.count
                log.add_simple_message(f'Picked up {item.count} {item.type.name}!', color=(200, 200, 200))
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
                    log.add_simple_message('Level Complete!', color=(255, 255, 0))
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
    ui_state = esper.get_component(UIState)[0][1]
    keybindings = esper.get_component(Keybindings)[0][1]
    actions = list(keybindings.bindings.keys())

    if action == InputAction.CANCEL:
        return DisplayMode.MENU
    elif action == InputAction.MOVE_UP:
        ui_state.settings_cursor = (ui_state.settings_cursor - 1) % len(actions)
    elif action == InputAction.MOVE_DOWN:
        ui_state.settings_cursor = (ui_state.settings_cursor + 1) % len(actions)
    elif action == InputAction.CONFIRM:
        # Arm the remap; try_capture_remap binds the next raw keypress.
        ui_state.remapping_action = actions[ui_state.settings_cursor]

    return DisplayMode.SETTINGS


def handle_menu_input(action: InputAction | None):
    ui_state = esper.get_component(UIState)[0][1]

    # Title menu before a run starts, pause menu once a player exists.
    game_active = is_game_active()
    options = PAUSE_MENU_OPTIONS if game_active else TITLE_MENU_OPTIONS
    ui_state.main_menu_cursor %= len(options)

    if action == InputAction.CANCEL:
        # Cancel resumes an active game; at the title screen there is nothing
        # to resume, so stay on the menu.
        return DisplayMode.EXPLORING if game_active else DisplayMode.MENU

    elif action == InputAction.MOVE_UP:
        ui_state.main_menu_cursor = (ui_state.main_menu_cursor - 1) % len(options)

    elif action == InputAction.MOVE_DOWN:
        ui_state.main_menu_cursor = (ui_state.main_menu_cursor + 1) % len(options)

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

    return DisplayMode.MENU


def handle_combining_input(action: InputAction | None):
    ui_state = esper.get_component(UIState)[0][1]

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
    player_entities = esper.get_components(Inventory, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    player, (player_inv, _tag) = player_entities[0]

    inv_list = sorted(i for i in player_inv.items if is_reagent(i))

    if inv_list:
        ui_state.crafting_cursor %= len(inv_list)
    else:
        ui_state.crafting_cursor = 0

    if action == InputAction.MOVE_UP:
        if inv_list:
            ui_state.crafting_cursor = (ui_state.crafting_cursor - 1) % len(inv_list)

    elif action == InputAction.MOVE_DOWN:
        if inv_list:
            ui_state.crafting_cursor = (ui_state.crafting_cursor + 1) % len(inv_list)

    elif action == InputAction.MOVE_RIGHT:
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

        log = esper.get_component(MessageLog)[0][1]
        result = match_recipe(sorted_selection)

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
                ('SUCCESS: Crafted ', (255, 255, 255)),
                (stype.name, (0, 255, 255)),
                (f'! (+{charges} charges)', (255, 255, 255)),
            ]
        )
        # Clear selection on success
        ui_state.selected_for_crafting = {}
        return DisplayMode.EXPLORING

    return DisplayMode.COMBINING


def _handle_spellbook_input(action: InputAction | None, ui_state: UIState):
    """Browse known recipes and instantly re-craft the selected one from stock."""
    player_entities = esper.get_components(KnownRecipes, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    _player, (player_recipes, _tag) = player_entities[0]

    known = sorted(player_recipes.recipes.keys(), key=lambda s: s.name)
    if known:
        ui_state.spellbook_cursor %= len(known)
    else:
        ui_state.spellbook_cursor = 0

    if action == InputAction.MOVE_UP:
        if known:
            ui_state.spellbook_cursor = (ui_state.spellbook_cursor - 1) % len(known)

    elif action == InputAction.MOVE_DOWN:
        if known:
            ui_state.spellbook_cursor = (ui_state.spellbook_cursor + 1) % len(known)

    elif action == InputAction.CONFIRM and known:
        stype = known[ui_state.spellbook_cursor]
        log = esper.get_component(MessageLog)[0][1]
        charges = craft_known_spell(stype)
        s_conf = get_spell_config(stype.value)
        spell_name = s_conf.get('name', stype.name) if s_conf else stype.name

        if charges is None:
            log.add_simple_message(f'Not enough ingredients to craft {spell_name}.', color=(255, 100, 100))
        else:
            log.add_message(
                [
                    ('Crafted ', (255, 255, 255)),
                    (spell_name, (0, 255, 255)),
                    (f'! (+{charges} charges)', (255, 255, 255)),
                ]
            )

    return DisplayMode.COMBINING


def handle_casting_input(action: InputAction | None):
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

    if action in (InputAction.CANCEL, InputAction.OPEN_CASTING):
        return DisplayMode.EXPLORING

    elif action == InputAction.MOVE_UP:
        if available_spells:
            ui_state.casting_cursor = (ui_state.casting_cursor - 1) % len(available_spells)

    elif action == InputAction.MOVE_DOWN:
        if available_spells:
            ui_state.casting_cursor = (ui_state.casting_cursor + 1) % len(available_spells)

    elif action == InputAction.CONFIRM:
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


def handle_targeting_input(action: InputAction | None):
    ui_state = esper.get_component(UIState)[0][1]
    reticles = esper.get_component(TargetingReticle)
    if not reticles:
        return DisplayMode.EXPLORING

    ret_ent, reticle = reticles[0]

    player_entities = esper.get_components(Position, PlayerTag)
    if not player_entities:
        return DisplayMode.EXPLORING
    _player, (player_pos, _tag) = player_entities[0]

    # Cancel or the casting action both back out to the spell picker (the input
    # that opened targeting also closes it).
    if action in (InputAction.CANCEL, InputAction.OPEN_CASTING):
        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.CASTING

    dx, dy = MOVE_DELTAS.get(action, (0, 0))
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
    ui_state = esper.get_component(UIState)[0][1]

    shopkeepers = esper.get_component(Shopkeeper)
    player_entities = esper.get_components(Inventory, PlayerTag)
    if not shopkeepers or not player_entities:
        return DisplayMode.EXPLORING
    offers = shopkeepers[0][1].offers
    _player, (player_inv, _tag) = player_entities[0]

    if action == InputAction.CANCEL:
        return DisplayMode.EXPLORING
    if not offers:
        return DisplayMode.SHOPPING

    ui_state.shop_cursor %= len(offers)
    offer = offers[ui_state.shop_cursor]
    max_qty = max(1, player_inv.items.get(ItemType.GOLD, 0) // offer.price)
    ui_state.shop_quantity = max(1, min(ui_state.shop_quantity, max_qty))

    if action == InputAction.MOVE_UP:
        ui_state.shop_cursor = (ui_state.shop_cursor - 1) % len(offers)
        ui_state.shop_quantity = 1
    elif action == InputAction.MOVE_DOWN:
        ui_state.shop_cursor = (ui_state.shop_cursor + 1) % len(offers)
        ui_state.shop_quantity = 1
    elif action == InputAction.MOVE_LEFT:
        ui_state.shop_quantity = max(1, ui_state.shop_quantity - 1)
    elif action == InputAction.MOVE_RIGHT:
        ui_state.shop_quantity = min(max_qty, ui_state.shop_quantity + 1)
    elif action == InputAction.CONFIRM:
        log = esper.get_component(MessageLog)[0][1]
        quantity = ui_state.shop_quantity
        if purchase_offer(offer, quantity):
            log.add_simple_message(f'Bought {quantity}x {offer.label}.', color=(0, 255, 255))
        else:
            log.add_simple_message('Not enough gold.', color=(255, 100, 100))
        ui_state.shop_quantity = 1

    return DisplayMode.SHOPPING
