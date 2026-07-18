import pygame
import pygame._sdl2.controller as game_controller

from src import persistence
from src.components import (
    QUICK_CAST_ACTIONS,
    ControllerAxis,
    ControllerBinding,
    ControllerButton,
    InputAction,
    Keybindings,
    Settings,
    UIState,
)
from src.ecs_helpers import get_singleton

# Movement is fixed to the d-pad (and left stick); it is not rebindable.
DPAD_MOVES: dict[ControllerButton, InputAction] = {
    ControllerButton.DPAD_UP: InputAction.MOVE_UP,
    ControllerButton.DPAD_DOWN: InputAction.MOVE_DOWN,
    ControllerButton.DPAD_LEFT: InputAction.MOVE_LEFT,
    ControllerButton.DPAD_RIGHT: InputAction.MOVE_RIGHT,
}

# START is the fixed pause-menu button (B is cancel/back, and never opens the menu);
# like movement, it is not rebindable.
FIXED_BUTTONS: dict[ControllerButton, InputAction] = {ControllerButton.START: InputAction.OPEN_MENU}

# Quick-cast is fixed (not rebindable), like movement, so it never enters the remap list.
# Keyboard: number keys 1-9 map to spell slots 1-9 (pygame key codes).
QUICK_CAST_KEYS: dict[int, InputAction] = dict(
    zip(
        (
            pygame.K_1,
            pygame.K_2,
            pygame.K_3,
            pygame.K_4,
            pygame.K_5,
            pygame.K_6,
            pygame.K_7,
            pygame.K_8,
            pygame.K_9,
        ),
        QUICK_CAST_ACTIONS,
        strict=True,
    )
)

# Controller: hold this shoulder as a modifier, then tap a face button for slots 1-4.
# Buttons in slot order (counter-clockwise from A), so slot index -> button is positional.
QUICK_CAST_MODIFIER = ControllerButton.LEFTSHOULDER
QUICK_CAST_FACE_BUTTONS = (
    ControllerButton.A,
    ControllerButton.X,
    ControllerButton.Y,
    ControllerButton.B,
)
QUICK_CAST_FACE: dict[ControllerButton, InputAction] = dict(
    zip(QUICK_CAST_FACE_BUTTONS, QUICK_CAST_ACTIONS, strict=False)
)

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


def resolve_action(event: pygame.event.Event, keybindings: Keybindings) -> InputAction | None:
    """Map a raw keyboard / controller-button pygame event to its action, or None.

    Key presses resolve through the (remappable) keymap, then the fixed quick-cast
    number keys; controller buttons through the (remappable) controller bindings. The
    d-pad and triggers resolve to nothing here: movement is fixed and triggers arrive
    as axes, so both are handled by ControllerInput (which lets them repeat). The
    controller quick-cast modifier is also handled there (it is stateful).
    """
    if event.type == pygame.KEYDOWN:
        for action, key in keybindings.bindings.items():
            if key == event.key:
                return action
        return QUICK_CAST_KEYS.get(event.key)
    if event.type == pygame.CONTROLLERBUTTONDOWN:
        button = ControllerButton(event.button)
        if button in DPAD_MOVES:
            return None
        if button in FIXED_BUTTONS:
            return FIXED_BUTTONS[button]
        return action_for_control(button, keybindings)
    return None


def try_capture_remap(event: pygame.event.Event) -> bool:
    """Bind the next keypress / controller button to a pending Settings remap.

    Returns True when the event was consumed. A key rebinds the keyboard binding;
    a controller button rebinds the controller binding. Movement actions and the
    d-pad are skipped (movement is fixed); trigger rebinds go through
    try_capture_remap_axis since triggers arrive as axis events.
    """
    ui_state = get_singleton(UIState)
    action = ui_state.remapping_action
    if action is None:
        return False
    keybindings = get_singleton(Settings).keybindings
    if event.type == pygame.KEYDOWN:
        keybindings.bindings[action] = event.key
        ui_state.remapping_action = None
        persistence.save_meta()
        return True
    if event.type == pygame.CONTROLLERBUTTONDOWN:
        button = ControllerButton(event.button)
        # The d-pad, START, and the quick-cast modifier are fixed; they can't be bound.
        reserved = button in DPAD_MOVES or button in FIXED_BUTTONS or button == QUICK_CAST_MODIFIER
        if action in MOVE_DELTAS or reserved:
            return False
        keybindings.controller[action] = button
        ui_state.remapping_action = None
        persistence.save_meta()
        return True
    return False


def try_capture_remap_axis(event: pygame.event.Event) -> bool:
    """Bind a pulled trigger to a pending Settings remap. Returns True if consumed.

    Only the triggers are bindable this way; the stick stays fixed to movement.
    """
    ui_state = get_singleton(UIState)
    action = ui_state.remapping_action
    if action is None or action in MOVE_DELTAS:
        return False
    axis = ControllerAxis(event.axis)
    if axis not in (ControllerAxis.TRIGGERLEFT, ControllerAxis.TRIGGERRIGHT) or event.value < TRIGGER_ENGAGE:
        return False
    get_singleton(Settings).keybindings.controller[action] = axis
    ui_state.remapping_action = None
    persistence.save_meta()
    return True


def try_capture_remap_event(event: pygame.event.Event) -> bool:
    """Route an event to the matching remap-capture path: triggers (axes) bind via
    try_capture_remap_axis, keys and buttons via try_capture_remap. Returns True when a
    pending Settings remap consumed the event."""
    if event.type == pygame.CONTROLLERAXISMOTION:
        return try_capture_remap_axis(event)
    return try_capture_remap(event)


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
        self.quick_cast_held = False  # the quick-cast shoulder modifier is down

    def handle_event(self, event: pygame.event.Event, now: float, keybindings: Keybindings) -> InputAction | None:
        """Resolve any controller pygame event to an action, or None — the single gamepad
        entry point. Axes drive the stick/triggers, the d-pad drives movement, and other
        buttons resolve through resolve_button (honoring the quick-cast modifier). Noting the
        pressed button for the live readout and Settings remap capture are the caller's job,
        since both happen before an event resolves to an action.
        """
        if event.type == pygame.CONTROLLERAXISMOTION:
            return self.on_axis(event, now, keybindings)
        button = ControllerButton(event.button)
        pressed = event.type == pygame.CONTROLLERBUTTONDOWN
        if button in DPAD_MOVES:
            return self.on_button(button, pressed, now)
        return self.resolve_button(button, pressed, keybindings)

    def on_button(self, button: ControllerButton, pressed: bool, now: float) -> InputAction | None:
        """Handle a d-pad button (movement). Other buttons are handled elsewhere."""
        if button not in DPAD_MOVES:
            return None
        if pressed:
            self.dpad.add(button)
        else:
            self.dpad.discard(button)
        return self._engage_movement(now)

    def resolve_button(self, button: ControllerButton, pressed: bool, keybindings: Keybindings) -> InputAction | None:
        """Resolve a non-d-pad controller button, honoring the quick-cast shoulder modifier.

        Holding the modifier turns the face buttons into quick-cast slots; otherwise the
        button resolves normally (its bound action / a fixed button). The modifier is
        stateful, which is why these buttons route through here rather than resolve_action.
        """
        if button == QUICK_CAST_MODIFIER:
            self.quick_cast_held = pressed
            return None
        if not pressed:
            return None
        if self.quick_cast_held and button in QUICK_CAST_FACE:
            return QUICK_CAST_FACE[button]
        if button in FIXED_BUTTONS:
            return FIXED_BUTTONS[button]
        return action_for_control(button, keybindings)

    def on_axis(self, event: pygame.event.Event, now: float, keybindings: Keybindings) -> InputAction | None:
        """Handle the left stick (movement) and the triggers (their bound action)."""
        axis = ControllerAxis(event.axis)
        value = event.value
        if axis == ControllerAxis.LEFTX:
            self.left_x = value
            return self._engage_movement(now)
        if axis == ControllerAxis.LEFTY:
            self.left_y = value
            return self._engage_movement(now)
        if axis in (ControllerAxis.TRIGGERLEFT, ControllerAxis.TRIGGERRIGHT):
            return self._engage_trigger(axis, value, now, keybindings)
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
        self, axis: ControllerAxis, value: int, now: float, keybindings: Keybindings
    ) -> InputAction | None:
        was_engaged = axis in self.engaged_triggers
        now_engaged = value >= (TRIGGER_RELEASE if was_engaged else TRIGGER_ENGAGE)
        if now_engaged == was_engaged:
            return None
        if not now_engaged:
            self.engaged_triggers.discard(axis)
            if self.repeat_source == axis:
                self.repeat_action = None
                self.repeat_source = None
            return None
        self.engaged_triggers.add(axis)
        action = action_for_control(axis, keybindings)
        if action is None:
            return None
        if action in REPEATING_ACTIONS:
            self.repeat_action = action
            self.repeat_source = axis
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
    """The controller control bound to an action, by enum name. Movement and the fixed
    buttons (e.g. START) are not rebindable."""
    if action in MOVE_DELTAS:
        return 'D-Pad / Stick'
    for button, fixed_action in FIXED_BUTTONS.items():
        if fixed_action == action:
            return button.name
    control = keybindings.controller.get(action)
    # `is not None`, not truthiness: ControllerButton.A == 0, so `if control` is falsy.
    return control.name if control is not None else '-'


def note_controller_button(button: ControllerButton) -> None:
    """Record the last controller button pressed, for the Settings live readout."""
    get_singleton(UIState).last_controller_input = button.name


def connected_controllers() -> list[game_controller.Controller]:
    """Open and return the connected game controllers. The caller must keep the list
    referenced so SDL holds the pads open and keeps delivering their events."""
    game_controller.init()
    return [
        game_controller.Controller(i) for i in range(game_controller.get_count()) if game_controller.is_controller(i)
    ]


def connected_controller_name() -> str | None:
    """Name of the first connected game controller, or None."""
    controllers = connected_controllers()
    return controllers[0].name if controllers else None
