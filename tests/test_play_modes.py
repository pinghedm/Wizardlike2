import pytest
import tcod.event

from src.main import update_pause_state
from src.states import DisplayMode
from tests.headless_runner import HeadlessRunner

# Modes reachable from EXPLORING by a single key press, and the key that opens them.
OPENABLE_MODES = [
    (tcod.event.KeySym.c, DisplayMode.COMBINING),
    (tcod.event.KeySym.s, DisplayMode.CASTING),
    (tcod.event.KeySym.ESCAPE, DisplayMode.MENU),
]


# Time keeps running on the live map and while aiming a spell; every other mode pauses it.
REAL_TIME_MODES = {DisplayMode.EXPLORING, DisplayMode.TARGETING}


@pytest.mark.parametrize('mode', list(DisplayMode))
def test_only_real_time_modes_leave_time_unpaused(mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = mode
    update_pause_state(runner.game_state)
    assert runner.game_state.time_paused == (mode not in REAL_TIME_MODES)


@pytest.mark.parametrize('open_key, mode', OPENABLE_MODES)
def test_key_opens_and_recloses_mode(open_key, mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_key(open_key)
    assert runner.display_mode == mode
    runner.simulate_key(open_key)
    assert runner.display_mode == DisplayMode.EXPLORING


@pytest.mark.parametrize('open_key, mode', OPENABLE_MODES)
def test_escape_closes_mode(open_key, mode):
    runner = HeadlessRunner(use_random_map=False)
    runner.simulate_key(open_key)
    assert runner.display_mode == mode
    runner.simulate_key(tcod.event.KeySym.ESCAPE)
    assert runner.display_mode == DisplayMode.EXPLORING
