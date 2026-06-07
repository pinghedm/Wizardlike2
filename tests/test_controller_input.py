import esper
import pytest
import tcod.event
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src.components import InputAction, Keybindings, Point, Settings, UIState
from src.input_handlers import (
    TRIGGER_ENGAGE,
    ControllerInput,
    resolve_action,
    try_capture_remap_axis,
)
from src.states import DisplayMode
from tests.headless_runner import HeadlessRunner

STICK_ENGAGE = ControllerInput.STICK_ENGAGE
REPEAT = ControllerInput.REPEAT_INTERVAL


def _key(sym: tcod.event.KeySym) -> tcod.event.KeyDown:
    return tcod.event.KeyDown(scancode=0, sym=sym, mod=tcod.event.Modifier.NONE, repeat=False)


def _button(button: ControllerButton, pressed: bool = True) -> tcod.event.ControllerButton:
    return tcod.event.ControllerButton(which=0, button=button, pressed=pressed)


def _axis(axis: ControllerAxis, value: int) -> tcod.event.ControllerAxis:
    return tcod.event.ControllerAxis(which=0, axis=axis, value=value)


def _kb() -> Keybindings:
    # bindings={} leaves the keyboard map empty; the controller map gets its defaults.
    return Keybindings(bindings={})


# --- resolve_action ---------------------------------------------------------


@pytest.mark.parametrize(
    ('button', 'action'),
    [
        (ControllerButton.A, InputAction.CONFIRM),
        (ControllerButton.B, InputAction.CANCEL),
        (ControllerButton.X, InputAction.OPEN_CASTING),
        (ControllerButton.Y, InputAction.OPEN_CRAFTING),
        (ControllerButton.RIGHTSHOULDER, InputAction.CYCLE_TAB),
    ],
)
def test_controller_button_resolves_to_its_bound_action(button, action):
    assert resolve_action(_button(button), _kb()) == action


def test_dpad_button_does_not_resolve_here():
    # The d-pad is handled by ControllerInput (so it can repeat), not resolve_action.
    assert resolve_action(_button(ControllerButton.DPAD_UP), _kb()) is None


def test_controller_button_release_resolves_to_nothing():
    assert resolve_action(_button(ControllerButton.A, pressed=False), _kb()) is None


def test_unbound_controller_button_resolves_to_nothing():
    assert resolve_action(_button(ControllerButton.GUIDE), _kb()) is None


def test_start_button_resolves_to_cancel():
    # START is a fixed escape button, resolved outside the rebindable bindings.
    assert resolve_action(_button(ControllerButton.START), _kb()) == InputAction.CANCEL


def test_rebound_controller_button_resolves_to_its_action():
    kb = Keybindings(bindings={}, controller={InputAction.CONFIRM: ControllerButton.X})
    assert resolve_action(_button(ControllerButton.X), kb) == InputAction.CONFIRM


def test_keypress_resolves_through_the_keymap():
    kb = Keybindings(bindings={InputAction.MOVE_UP: tcod.event.KeySym.UP})
    assert resolve_action(_key(tcod.event.KeySym.UP), kb) == InputAction.MOVE_UP


def test_unbound_key_resolves_to_nothing():
    kb = Keybindings(bindings={InputAction.MOVE_UP: tcod.event.KeySym.UP})
    assert resolve_action(_key(tcod.event.KeySym.Z), kb) is None


@pytest.mark.parametrize(
    ('sym', 'action'),
    [
        (tcod.event.KeySym.N1, InputAction.QUICK_CAST_1),
        (tcod.event.KeySym.N5, InputAction.QUICK_CAST_5),
        (tcod.event.KeySym.N9, InputAction.QUICK_CAST_9),
    ],
)
def test_number_key_resolves_to_quick_cast(sym, action):
    # Quick-cast keys are fixed; they resolve even with an empty rebindable keymap.
    assert resolve_action(_key(sym), _kb()) == action


# --- ControllerInput: stick + triggers + d-pad, with repeat -----------------


@pytest.mark.parametrize(
    ('axis', 'value', 'expected'),
    [
        (ControllerAxis.LEFTX, STICK_ENGAGE, InputAction.MOVE_RIGHT),
        (ControllerAxis.LEFTX, -STICK_ENGAGE, InputAction.MOVE_LEFT),
        (ControllerAxis.LEFTY, STICK_ENGAGE, InputAction.MOVE_DOWN),
        (ControllerAxis.LEFTY, -STICK_ENGAGE, InputAction.MOVE_UP),
        (ControllerAxis.TRIGGERRIGHT, TRIGGER_ENGAGE, InputAction.SCROLL_DOWN),
        (ControllerAxis.TRIGGERLEFT, TRIGGER_ENGAGE, InputAction.SCROLL_UP),
    ],
)
def test_engaging_an_axis_fires_its_action(axis, value, expected):
    assert ControllerInput().on_axis(_axis(axis, value), 0.0, _kb()) == expected


def test_an_axis_below_the_engage_threshold_fires_nothing():
    assert ControllerInput().on_axis(_axis(ControllerAxis.LEFTX, STICK_ENGAGE - 1), 0.0, _kb()) is None


def test_the_dominant_stick_axis_picks_the_direction():
    c = ControllerInput()
    c.on_axis(_axis(ControllerAxis.LEFTY, 8000), 0.0, _kb())  # minor, below engage on its own
    assert c.on_axis(_axis(ControllerAxis.LEFTX, 30000), 0.0, _kb()) == InputAction.MOVE_RIGHT


def test_an_unhandled_axis_is_ignored():
    assert ControllerInput().on_axis(_axis(ControllerAxis.RIGHTX, 30000), 0.0, _kb()) is None


@pytest.mark.parametrize(
    ('button', 'expected'),
    [
        (ControllerButton.DPAD_RIGHT, InputAction.MOVE_RIGHT),
        (ControllerButton.DPAD_LEFT, InputAction.MOVE_LEFT),
        (ControllerButton.DPAD_UP, InputAction.MOVE_UP),
        (ControllerButton.DPAD_DOWN, InputAction.MOVE_DOWN),
    ],
)
def test_dpad_button_fires_movement(button, expected):
    assert ControllerInput().on_button(button, pressed=True, now=0.0) == expected


def test_a_held_dpad_does_not_refire_until_due_then_repeats():
    c = ControllerInput()
    assert c.on_button(ControllerButton.DPAD_RIGHT, pressed=True, now=0.0) == InputAction.MOVE_RIGHT
    assert c.tick(REPEAT / 2) is None
    assert c.tick(REPEAT) == InputAction.MOVE_RIGHT


def test_releasing_the_dpad_stops_the_repeat():
    c = ControllerInput()
    c.on_button(ControllerButton.DPAD_RIGHT, pressed=True, now=0.0)
    c.on_button(ControllerButton.DPAD_RIGHT, pressed=False, now=0.0)
    assert c.tick(REPEAT * 3) is None


def test_a_held_trigger_repeats_its_scroll():
    c = ControllerInput()
    assert c.on_axis(_axis(ControllerAxis.TRIGGERRIGHT, TRIGGER_ENGAGE), 0.0, _kb()) == InputAction.SCROLL_DOWN
    assert c.tick(REPEAT) == InputAction.SCROLL_DOWN


def test_releasing_a_trigger_stops_the_repeat():
    c = ControllerInput()
    c.on_axis(_axis(ControllerAxis.TRIGGERRIGHT, TRIGGER_ENGAGE), 0.0, _kb())
    c.on_axis(_axis(ControllerAxis.TRIGGERRIGHT, 0), 0.0, _kb())
    assert c.tick(REPEAT * 3) is None


# --- quick-cast: shoulder modifier + face buttons ---------------------------


@pytest.mark.parametrize(
    ('button', 'action'),
    [
        (ControllerButton.A, InputAction.QUICK_CAST_1),
        (ControllerButton.B, InputAction.QUICK_CAST_2),
        (ControllerButton.X, InputAction.QUICK_CAST_3),
        (ControllerButton.Y, InputAction.QUICK_CAST_4),
    ],
)
def test_held_modifier_turns_face_buttons_into_quick_cast(button, action):
    c = ControllerInput()
    assert c.resolve_button(_button(ControllerButton.LEFTSHOULDER), _kb()) is None  # modifier down
    assert c.resolve_button(_button(button), _kb()) == action


def test_face_button_without_modifier_resolves_normally():
    c = ControllerInput()
    assert c.resolve_button(_button(ControllerButton.A), _kb()) == InputAction.CONFIRM


def test_releasing_the_modifier_restores_normal_face_buttons():
    c = ControllerInput()
    c.resolve_button(_button(ControllerButton.LEFTSHOULDER, pressed=True), _kb())
    c.resolve_button(_button(ControllerButton.LEFTSHOULDER, pressed=False), _kb())
    assert c.resolve_button(_button(ControllerButton.A), _kb()) == InputAction.CONFIRM


# --- integration through the dispatch path ----------------------------------


def test_dpad_drives_player_movement():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    runner.simulate_controller_button(ControllerButton.DPAD_RIGHT)
    assert runner.player_pos == Point(px + 1, py)


def test_face_button_opens_crafting_from_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.Y)
    assert runner.display_mode == DisplayMode.COMBINING


def test_controller_quick_cast_enters_targeting_from_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 2)
    runner.simulate_controller_button(ControllerButton.LEFTSHOULDER)  # hold the modifier
    runner.simulate_controller_button(ControllerButton.A)  # slot 1
    assert runner.display_mode == DisplayMode.TARGETING


def test_cancel_button_opens_the_menu_from_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.B)
    assert runner.display_mode == DisplayMode.MENU


def test_start_button_opens_the_menu_from_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.START)
    assert runner.display_mode == DisplayMode.MENU


def test_button_press_is_recorded_for_the_settings_readout():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.A)
    assert esper.get_component(UIState)[0][1].last_controller_input == ControllerButton.A.name


# --- rebinding --------------------------------------------------------------


def test_remapping_binds_a_pressed_controller_button():
    runner = HeadlessRunner(use_random_map=False)
    esper.get_component(UIState)[0][1].remapping_action = InputAction.CONFIRM
    runner.game_state.display_mode = DisplayMode.SETTINGS

    runner.simulate_controller_button(ControllerButton.LEFTSTICK)

    keybindings = esper.get_component(Settings)[0][1].keybindings
    assert keybindings.controller[InputAction.CONFIRM] == ControllerButton.LEFTSTICK
    assert esper.get_component(UIState)[0][1].remapping_action is None


def test_remapping_binds_a_pulled_trigger():
    HeadlessRunner(use_random_map=False)
    esper.get_component(UIState)[0][1].remapping_action = InputAction.OPEN_CASTING

    assert try_capture_remap_axis(_axis(ControllerAxis.TRIGGERRIGHT, TRIGGER_ENGAGE)) is True

    keybindings = esper.get_component(Settings)[0][1].keybindings
    assert keybindings.controller[InputAction.OPEN_CASTING] == ControllerAxis.TRIGGERRIGHT


def test_start_is_not_rebindable():
    runner = HeadlessRunner(use_random_map=False)
    esper.get_component(UIState)[0][1].remapping_action = InputAction.CONFIRM
    runner.game_state.display_mode = DisplayMode.SETTINGS

    runner.simulate_controller_button(ControllerButton.START)  # fixed; can't be bound

    keybindings = esper.get_component(Settings)[0][1].keybindings
    assert keybindings.controller[InputAction.CONFIRM] == ControllerButton.A


def test_quick_cast_modifier_is_not_rebindable():
    runner = HeadlessRunner(use_random_map=False)
    esper.get_component(UIState)[0][1].remapping_action = InputAction.CONFIRM
    runner.game_state.display_mode = DisplayMode.SETTINGS

    runner.simulate_controller_button(ControllerButton.LEFTSHOULDER)  # reserved quick-cast modifier

    keybindings = esper.get_component(Settings)[0][1].keybindings
    assert keybindings.controller[InputAction.CONFIRM] == ControllerButton.A
    assert esper.get_component(UIState)[0][1].remapping_action == InputAction.CONFIRM


def test_movement_controller_binding_is_fixed():
    runner = HeadlessRunner(use_random_map=False)
    esper.get_component(UIState)[0][1].remapping_action = InputAction.MOVE_UP
    runner.game_state.display_mode = DisplayMode.SETTINGS

    runner.simulate_controller_button(ControllerButton.LEFTSTICK)  # not captured for movement

    keybindings = esper.get_component(Settings)[0][1].keybindings
    assert InputAction.MOVE_UP not in keybindings.controller
    assert esper.get_component(UIState)[0][1].remapping_action == InputAction.MOVE_UP
