import tcod
import tcod.sdl.joystick
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src import persistence
from src.components import (
    QUICK_CAST_ACTIONS,
    ControllerBinding,
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
# Keyboard: number keys 1-9 map to spell slots 1-9.
QUICK_CAST_KEYS: dict[tcod.event.KeySym, InputAction] = dict(
    zip(
        (
            tcod.event.KeySym.N1,
            tcod.event.KeySym.N2,
            tcod.event.KeySym.N3,
            tcod.event.KeySym.N4,
            tcod.event.KeySym.N5,
            tcod.event.KeySym.N6,
            tcod.event.KeySym.N7,
            tcod.event.KeySym.N8,
            tcod.event.KeySym.N9,
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


def resolve_action(event: tcod.event.Event, keybindings: Keybindings) -> InputAction | None:
    """Map a raw keyboard / controller-button event to its action, or None.

    Keyboard presses resolve through the (remappable) keymap, then the fixed
    quick-cast number keys; controller buttons through the (remappable) controller
    bindings. The d-pad and triggers resolve to nothing here: movement is fixed and
    triggers arrive as axes, so both are handled by ControllerInput (which lets them
    repeat). The controller quick-cast modifier is also handled there (it is stateful).
    """
    if isinstance(event, tcod.event.KeyDown):
        for action, sym in keybindings.bindings.items():
            if sym == event.sym:
                return action
        return QUICK_CAST_KEYS.get(event.sym)
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
    ui_state = get_singleton(UIState)
    action = ui_state.remapping_action
    if action is None:
        return False
    keybindings = get_singleton(Settings).keybindings
    if isinstance(event, tcod.event.KeyDown):
        keybindings.bindings[action] = event.sym
        ui_state.remapping_action = None
        persistence.save_meta()
        return True
    if isinstance(event, tcod.event.ControllerButton) and event.pressed:
        # The d-pad, START, and the quick-cast modifier are fixed; they can't be bound.
        reserved = event.button in DPAD_MOVES or event.button in FIXED_BUTTONS or event.button == QUICK_CAST_MODIFIER
        if action in MOVE_DELTAS or reserved:
            return False
        keybindings.controller[action] = event.button
        ui_state.remapping_action = None
        persistence.save_meta()
        return True
    return False


def try_capture_remap_axis(event: tcod.event.ControllerAxis) -> bool:
    """Bind a pulled trigger to a pending Settings remap. Returns True if consumed.

    Only the triggers are bindable this way; the stick stays fixed to movement.
    """
    ui_state = get_singleton(UIState)
    action = ui_state.remapping_action
    if action is None or action in MOVE_DELTAS:
        return False
    if event.axis not in (ControllerAxis.TRIGGERLEFT, ControllerAxis.TRIGGERRIGHT) or event.value < TRIGGER_ENGAGE:
        return False
    get_singleton(Settings).keybindings.controller[action] = event.axis
    ui_state.remapping_action = None
    persistence.save_meta()
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
        self.quick_cast_held = False  # the quick-cast shoulder modifier is down

    def on_button(self, button: ControllerButton, pressed: bool, now: float) -> InputAction | None:
        """Handle a d-pad button (movement). Other buttons are handled elsewhere."""
        if button not in DPAD_MOVES:
            return None
        if pressed:
            self.dpad.add(button)
        else:
            self.dpad.discard(button)
        return self._engage_movement(now)

    def resolve_button(self, event: tcod.event.ControllerButton, keybindings: Keybindings) -> InputAction | None:
        """Resolve a non-d-pad controller button, honoring the quick-cast shoulder modifier.

        Holding the modifier turns the face buttons into quick-cast slots; otherwise the
        button resolves normally (its bound action / a fixed button). The modifier is
        stateful, which is why these buttons route through here rather than resolve_action.
        """
        if event.button == QUICK_CAST_MODIFIER:
            self.quick_cast_held = event.pressed
            return None
        if not event.pressed:
            return None
        if self.quick_cast_held and event.button in QUICK_CAST_FACE:
            return QUICK_CAST_FACE[event.button]
        return resolve_action(event, keybindings)

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
