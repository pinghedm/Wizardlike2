import math

import esper
import tcod
import tcod.sdl.joystick
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src import persistence
from src.components import (
    Actor,
    ControllerBinding,
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
from src.ecs_helpers import get_display_name, try_get_singleton
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

# Movement is fixed to the d-pad (and left stick); it is not rebindable.
DPAD_MOVES: dict[ControllerButton, InputAction] = {
    ControllerButton.DPAD_UP: InputAction.MOVE_UP,
    ControllerButton.DPAD_DOWN: InputAction.MOVE_DOWN,
    ControllerButton.DPAD_LEFT: InputAction.MOVE_LEFT,
    ControllerButton.DPAD_RIGHT: InputAction.MOVE_RIGHT,
}

# START is a fixed escape/back button; like movement, it is not rebindable.
FIXED_BUTTONS: dict[ControllerButton, InputAction] = {ControllerButton.START: InputAction.CANCEL}

# How a movement action displaces the cursor / player on each axis.
MOVE_DELTAS: dict[InputAction, tuple[int, int]] = {
    InputAction.MOVE_UP: (0, -1),
    InputAction.MOVE_DOWN: (0, 1),
    InputAction.MOVE_LEFT: (-1, 0),
    InputAction.MOVE_RIGHT: (1, 0),
}


def move_delta(action: InputAction | None) -> tuple[int, int]:
    """The (dx, dy) step for a movement action, or (0, 0) for anything that isn't one."""
    if action is None:
        return (0, 0)
    return MOVE_DELTAS.get(action, (0, 0))


# Actions that auto-repeat while their control is held, like a held arrow key.
REPEATING_ACTIONS = set(MOVE_DELTAS) | {InputAction.SCROLL_UP, InputAction.SCROLL_DOWN}

# Analog trigger thresholds: a high value engages, a lower one releases (hysteresis).
TRIGGER_ENGAGE = 16384
TRIGGER_RELEASE = 8000


def action_for_control(control: ControllerBinding, keybindings: Keybindings) -> InputAction | None:
    """The action a controller button/trigger is bound to, or None.

    The type guard matters: ControllerButton and ControllerAxis are both IntEnums,
    so e.g. GUIDE (5) would otherwise compare equal to TRIGGERRIGHT (5).
    """
    for action, bound in keybindings.controller.items():
        if type(bound) is type(control) and bound == control:
            return action
    return None


def resolve_action(event: tcod.event.Event, keybindings: Keybindings) -> InputAction | None:
    """Map a raw keyboard / controller-button event to its action, or None.

    Keyboard presses resolve through the (remappable) keymap, controller buttons
    through the (remappable) controller bindings. The d-pad and triggers resolve
    to nothing here: movement is fixed and triggers arrive as axes, so both are
    handled by ControllerInput (which lets them repeat).
    """
    if isinstance(event, tcod.event.KeyDown):
        for action, sym in keybindings.bindings.items():
            if sym == event.sym:
                return action
        return None
    if isinstance(event, tcod.event.ControllerButton):
        if not event.pressed or event.button in DPAD_MOVES:
            return None
        if event.button in FIXED_BUTTONS:
            return FIXED_BUTTONS[event.button]
        return action_for_control(event.button, keybindings)
    return None


def try_capture_remap(event: tcod.event.Event) -> bool:
    """Bind the next keypress / controller button to a pending Settings remap.

    Returns True when the event was consumed. A key rebinds the keyboard binding;
    a controller button rebinds the controller binding. Movement actions and the
    d-pad are skipped (movement is fixed); trigger rebinds go through
    try_capture_remap_axis since triggers arrive as axis events.
    """
    ui_state = esper.get_component(UIState)[0][1]
    action = ui_state.remapping_action
    if action is None:
        return False
    keybindings = esper.get_component(Keybindings)[0][1]
    if isinstance(event, tcod.event.KeyDown):
        keybindings.bindings[action] = event.sym
        ui_state.remapping_action = None
        return True
    if isinstance(event, tcod.event.ControllerButton) and event.pressed:
        if action in MOVE_DELTAS or event.button in DPAD_MOVES or event.button in FIXED_BUTTONS:
            return False
        keybindings.controller[action] = event.button
        ui_state.remapping_action = None
        return True
    return False


def try_capture_remap_axis(event: tcod.event.ControllerAxis) -> bool:
    """Bind a pulled trigger to a pending Settings remap. Returns True if consumed.

    Only the triggers are bindable this way; the stick stays fixed to movement.
    """
    ui_state = esper.get_component(UIState)[0][1]
    action = ui_state.remapping_action
    if action is None or action in MOVE_DELTAS:
        return False
    if event.axis not in (ControllerAxis.TRIGGERLEFT, ControllerAxis.TRIGGERRIGHT) or event.value < TRIGGER_ENGAGE:
        return False
    esper.get_component(Keybindings)[0][1].controller[action] = event.axis
    ui_state.remapping_action = None
    return True


class ControllerInput:
    """Turns the gamepad's streamed/edge inputs into discrete, repeating actions.

    The d-pad and left stick drive movement (fixed); the triggers resolve through
    the rebindable controller bindings. A control mapped to a repeating action
    (movement, scroll) keeps firing while held, like a held key; a one-shot action
    fires once. A high engage / lower release threshold gives the stick and
    triggers hysteresis. Time is injected so repeats stay deterministic in tests.
    """

    STICK_ENGAGE = 16384
    STICK_RELEASE = 11000
    REPEAT_INTERVAL = 0.12

    def __init__(self):
        self.left_x = 0
        self.left_y = 0
        self.dpad: set[ControllerButton] = set()
        self.engaged_triggers: set[ControllerAxis] = set()
        self.repeat_action: InputAction | None = None
        self.repeat_source: object = None  # 'move', or the ControllerAxis driving a repeat
        self.next_repeat = 0.0

    def on_button(self, button: ControllerButton, pressed: bool, now: float) -> InputAction | None:
        """Handle a d-pad button (movement). Other buttons are handled elsewhere."""
        if button not in DPAD_MOVES:
            return None
        if pressed:
            self.dpad.add(button)
        else:
            self.dpad.discard(button)
        return self._engage_movement(now)

    def on_axis(self, event: tcod.event.ControllerAxis, now: float, keybindings: Keybindings) -> InputAction | None:
        """Handle the left stick (movement) and the triggers (their bound action)."""
        if event.axis == ControllerAxis.LEFTX:
            self.left_x = event.value
            return self._engage_movement(now)
        if event.axis == ControllerAxis.LEFTY:
            self.left_y = event.value
            return self._engage_movement(now)
        if event.axis in (ControllerAxis.TRIGGERLEFT, ControllerAxis.TRIGGERRIGHT):
            return self._engage_trigger(event, now, keybindings)
        return None

    def tick(self, now: float) -> InputAction | None:
        """Return the held action if it is due to repeat, else None."""
        if self.repeat_action is None or now < self.next_repeat:
            return None
        self.next_repeat = now + self.REPEAT_INTERVAL
        return self.repeat_action

    def _engage_movement(self, now: float) -> InputAction | None:
        desired = self._movement_action()
        if desired == self.repeat_action and self.repeat_source == 'move':
            return None
        if desired is None:
            if self.repeat_source == 'move':
                self.repeat_action = None
                self.repeat_source = None
            return None
        self.repeat_action = desired
        self.repeat_source = 'move'
        self.next_repeat = now + self.REPEAT_INTERVAL
        return desired

    def _engage_trigger(
        self, event: tcod.event.ControllerAxis, now: float, keybindings: Keybindings
    ) -> InputAction | None:
        was_engaged = event.axis in self.engaged_triggers
        now_engaged = event.value >= (TRIGGER_RELEASE if was_engaged else TRIGGER_ENGAGE)
        if now_engaged == was_engaged:
            return None
        if not now_engaged:
            self.engaged_triggers.discard(event.axis)
            if self.repeat_source == event.axis:
                self.repeat_action = None
                self.repeat_source = None
            return None
        self.engaged_triggers.add(event.axis)
        action = action_for_control(event.axis, keybindings)
        if action is None:
            return None
        if action in REPEATING_ACTIONS:
            self.repeat_action = action
            self.repeat_source = event.axis
            self.next_repeat = now + self.REPEAT_INTERVAL
        return action

    def _movement_action(self) -> InputAction | None:
        x = (ControllerButton.DPAD_RIGHT in self.dpad) - (ControllerButton.DPAD_LEFT in self.dpad)
        y = (ControllerButton.DPAD_DOWN in self.dpad) - (ControllerButton.DPAD_UP in self.dpad)
        if not x and not y:
            threshold = self.STICK_RELEASE if self.repeat_source == 'move' else self.STICK_ENGAGE
            if max(abs(self.left_x), abs(self.left_y)) < threshold:
                return None
            x, y = self.left_x, self.left_y
        if abs(x) >= abs(y):
            return InputAction.MOVE_RIGHT if x > 0 else InputAction.MOVE_LEFT
        return InputAction.MOVE_DOWN if y > 0 else InputAction.MOVE_UP


def controller_binding_label(action: InputAction, keybindings: Keybindings) -> str:
    """The controller control bound to an action, by enum name. Movement is fixed."""
    if action in MOVE_DELTAS:
        return 'D-Pad / Stick'
    control = keybindings.controller.get(action)
    # `is not None`, not truthiness: ControllerButton.A == 0, so `if control` is falsy.
    return control.name if control is not None else '-'


def note_controller_button(button: ControllerButton) -> None:
    """Record the last controller button pressed, for the Settings live readout."""
    esper.get_component(UIState)[0][1].last_controller_input = button.name


# tcod 21.2.0's get_controllers()/get_joysticks() pass 0-based indices to SDL3
# APIs that expect instance IDs (which start at 1), so they never see a connected
# pad (and get_joysticks even raises). These read the real instance-ID array and
# query/open by ID instead. Remove once tcod fixes the upstream bug.
def _gamepad_instance_ids() -> list[int]:
    tcod.sdl.joystick.init()
    lib, ffi = tcod.sdl.joystick.lib, tcod.sdl.joystick.ffi
    count = ffi.new('int*')
    ids = lib.SDL_GetJoysticks(count)
    try:
        return [ids[i] for i in range(count[0]) if lib.SDL_IsGamepad(ids[i])]
    finally:
        lib.SDL_free(ids)


def connected_controllers() -> list[tcod.sdl.joystick.GameController]:
    """Open and return the connected game controllers. The caller must keep the
    list referenced so SDL holds the pads open and keeps delivering their events."""
    return [tcod.sdl.joystick.GameController._open(jid) for jid in _gamepad_instance_ids()]


def connected_controller_name() -> str | None:
    """Name of the first connected game controller, or None — without opening it."""
    lib, ffi = tcod.sdl.joystick.lib, tcod.sdl.joystick.ffi
    for jid in _gamepad_instance_ids():
        return ffi.string(lib.SDL_GetJoystickNameForID(jid)).decode()
    return None


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

    dx, dy = move_delta(action)
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
