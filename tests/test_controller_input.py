import esper
import pytest
import tcod.event
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src.components import InputAction, Keybindings, Point, UIState
from src.input_handlers import CONTROLLER_ACTIONS, AnalogInput, resolve_action
from src.states import DisplayMode
from tests.headless_runner import HeadlessRunner


def _key(sym: tcod.event.KeySym) -> tcod.event.KeyDown:
    return tcod.event.KeyDown(scancode=0, sym=sym, mod=tcod.event.Modifier.NONE, repeat=False)


def _button(button: ControllerButton, pressed: bool = True) -> tcod.event.ControllerButton:
    return tcod.event.ControllerButton(which=0, button=button, pressed=pressed)


def _axis(axis: ControllerAxis, value: int) -> tcod.event.ControllerAxis:
    return tcod.event.ControllerAxis(which=0, axis=axis, value=value)


@pytest.mark.parametrize(('button', 'action'), list(CONTROLLER_ACTIONS.items()))
def test_controller_button_resolves_to_its_action(button, action):
    assert resolve_action(_button(button), Keybindings(bindings={})) == action


def test_controller_button_release_resolves_to_nothing():
    assert resolve_action(_button(ControllerButton.A, pressed=False), Keybindings(bindings={})) is None


def test_unmapped_controller_button_resolves_to_nothing():
    assert resolve_action(_button(ControllerButton.GUIDE), Keybindings(bindings={})) is None


def test_keypress_resolves_through_the_keymap():
    kb = Keybindings(bindings={InputAction.MOVE_UP: tcod.event.KeySym.UP})
    assert resolve_action(_key(tcod.event.KeySym.UP), kb) == InputAction.MOVE_UP


def test_unbound_key_resolves_to_nothing():
    kb = Keybindings(bindings={InputAction.MOVE_UP: tcod.event.KeySym.UP})
    assert resolve_action(_key(tcod.event.KeySym.Z), kb) is None


def test_remapped_key_resolves_to_its_action():
    # The keyboard resolves through the live keymap, so a remapped key drives its
    # action with no change to the handlers (which only see InputActions).
    kb = Keybindings(bindings={InputAction.MOVE_UP: tcod.event.KeySym.W})
    assert resolve_action(_key(tcod.event.KeySym.W), kb) == InputAction.MOVE_UP


def test_dpad_drives_player_movement():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    runner.simulate_controller_button(ControllerButton.DPAD_RIGHT)
    assert runner.player_pos == Point(px + 1, py)


def test_face_button_opens_crafting_from_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.Y)
    assert runner.display_mode == DisplayMode.COMBINING


def test_cancel_button_opens_the_menu_from_exploring():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.B)
    assert runner.display_mode == DisplayMode.MENU


# --- AnalogInput (left stick + triggers) ------------------------------------


@pytest.mark.parametrize(
    ('axis', 'value', 'expected'),
    [
        (ControllerAxis.LEFTX, AnalogInput.STICK_ENGAGE, InputAction.MOVE_RIGHT),
        (ControllerAxis.LEFTX, -AnalogInput.STICK_ENGAGE, InputAction.MOVE_LEFT),
        (ControllerAxis.LEFTY, AnalogInput.STICK_ENGAGE, InputAction.MOVE_DOWN),
        (ControllerAxis.LEFTY, -AnalogInput.STICK_ENGAGE, InputAction.MOVE_UP),
        (ControllerAxis.TRIGGERRIGHT, AnalogInput.TRIGGER_ENGAGE, InputAction.SCROLL_DOWN),
        (ControllerAxis.TRIGGERLEFT, AnalogInput.TRIGGER_ENGAGE, InputAction.SCROLL_UP),
    ],
)
def test_engaging_an_axis_fires_its_action(axis, value, expected):
    assert AnalogInput().update(_axis(axis, value), now=0.0) == expected


def test_an_axis_below_the_engage_threshold_fires_nothing():
    assert AnalogInput().update(_axis(ControllerAxis.LEFTX, AnalogInput.STICK_ENGAGE - 1), now=0.0) is None


def test_the_dominant_stick_axis_picks_the_direction():
    analog = AnalogInput()
    analog.update(_axis(ControllerAxis.LEFTY, 8000), now=0.0)  # minor, below engage on its own
    # A larger X then dominates, so movement is horizontal, not vertical.
    assert analog.update(_axis(ControllerAxis.LEFTX, 30000), now=0.0) == InputAction.MOVE_RIGHT


def test_an_unhandled_axis_is_ignored():
    assert AnalogInput().update(_axis(ControllerAxis.RIGHTX, 30000), now=0.0) is None


def test_a_held_stick_does_not_refire_until_it_is_due_to_repeat():
    analog = AnalogInput()
    assert analog.update(_axis(ControllerAxis.LEFTX, 30000), now=0.0) == InputAction.MOVE_RIGHT
    # Same direction held: no immediate re-fire, then a repeat once the interval elapses.
    assert analog.tick(now=AnalogInput.REPEAT_INTERVAL / 2) is None
    assert analog.tick(now=AnalogInput.REPEAT_INTERVAL) == InputAction.MOVE_RIGHT


def test_recentering_the_stick_stops_movement():
    analog = AnalogInput()
    analog.update(_axis(ControllerAxis.LEFTX, 30000), now=0.0)
    analog.update(_axis(ControllerAxis.LEFTX, 0), now=0.0)
    assert analog.tick(now=AnalogInput.REPEAT_INTERVAL * 3) is None


def test_button_press_is_recorded_for_the_settings_readout():
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_controller_button(ControllerButton.A)
    ui_state = esper.get_component(UIState)[0][1]
    assert ui_state.last_controller_input == ControllerButton.A.name
