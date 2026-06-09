"""handle_menu_input's CONFIRM dispatch: each menu option -> the screen (DisplayMode) or
world command (PendingTransition) it resolves to.

The option list depends on whether a run is in progress (is_game_active): the title
menu before a player exists, the pause menu after. The CONTINUE/LOAD options are gated
on a save file existing, so has_save is stubbed to drive both sides of that branch.
"""

import esper
import pytest

from src import persistence
from src.components import InputAction, PlayerTag, UIState
from src.entities import create_game_state, create_ui_state
from src.input_handlers import handle_menu_input
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    DisplayMode,
    MenuOption,
    PendingTransition,
)

# (game_active, option, has_save, expected_result)
MENU_CONFIRM_CASES = [
    # Pause menu -- a run is in progress.
    (True, MenuOption.RESUME, False, DisplayMode.EXPLORING),
    (True, MenuOption.SAVE, False, PendingTransition.SAVE),
    (True, MenuOption.SETTINGS, False, DisplayMode.SETTINGS),
    (True, MenuOption.QUIT, False, PendingTransition.EXIT),
    (True, MenuOption.LOAD, True, PendingTransition.LOAD_SAVE),
    (True, MenuOption.LOAD, False, DisplayMode.MENU),  # no save -> stays on the menu
    # Title menu -- no run yet.
    (False, MenuOption.NEW_GAME, False, PendingTransition.NEW_GAME),
    (False, MenuOption.CONTINUE, True, PendingTransition.LOAD_SAVE),
    (False, MenuOption.CONTINUE, False, DisplayMode.MENU),  # no save -> stays on the menu
    (False, MenuOption.QUIT, False, PendingTransition.EXIT),
]


@pytest.mark.parametrize(('game_active', 'option', 'has_save', 'expected'), MENU_CONFIRM_CASES)
def test_menu_confirm_routes_each_option(game_active, option, has_save, expected, monkeypatch):
    esper.clear_database()
    create_game_state(floor=1)
    create_ui_state()
    if game_active:
        esper.create_entity(PlayerTag())
    monkeypatch.setattr(persistence, 'has_save', lambda: has_save)

    options = PAUSE_MENU_OPTIONS if game_active else TITLE_MENU_OPTIONS
    esper.get_component(UIState)[0][1].main_menu_cursor = options.index(option)

    assert handle_menu_input(InputAction.CONFIRM) == expected
