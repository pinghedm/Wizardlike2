"""Visual snapshot tests for the UI render processors in src/ui_systems.py.

These drive each processor into its rendering branches via HeadlessRunner's
console snapshot helpers (get_console_text / get_console_fg / get_console_bg)
and assert on the resulting text and highlight colors.
"""

import esper
import pytest

from src import persistence
from src.components import (
    InputAction,
    ItemType,
    KnownRecipes,
    MessageLog,
    Modal,
    SpellInventory,
    SpellType,
    Stats,
    TargetingReticle,
    UIState,
)
from src.constants import (
    UI_BLACK,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_MAROON,
    UI_RED,
    UI_RED_DARK,
    UI_WHITE,
    UI_YELLOW,
)
from src.entities import create_game_state, create_ui_state
from src.input_handlers import available_spells
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    CraftingView,
    DisplayMode,
    MenuOption,
)
from src.ui_helpers import blend

from .headless_runner import HeadlessRunner


def _full_text(runner: HeadlessRunner) -> str:
    return '\n'.join(runner.get_console_text())


def _find_text(runner: HeadlessRunner, needle: str) -> tuple[int, int]:
    """Return the (x, y) of the first occurrence of needle in the console."""
    for y, row in enumerate(runner.get_console_text()):
        x = row.find(needle)
        if x != -1:
            return x, y
    raise AssertionError(f'{needle!r} not found on console')


def _ui_state(runner: HeadlessRunner) -> UIState:
    return esper.get_component(UIState)[0][1]


# --- MenuSystem.render_main_menu --------------------------------------------


def test_title_menu_shows_title_and_options():
    # Build a runner for the console/UI processors, then strip the world down to
    # the startup title state (no player) to exercise the title menu branch.
    runner = HeadlessRunner(use_random_map=False)
    esper.clear_database()
    create_game_state()
    create_ui_state()
    runner.game_state.display_mode = DisplayMode.MENU

    text = _full_text(runner)
    assert 'WizardLike' in text
    for option in TITLE_MENU_OPTIONS:
        assert str(option) in text


def test_pause_menu_shows_title_and_options():
    # A player exists -> in-game pause menu.
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.MENU

    text = _full_text(runner)
    assert 'Paused' in text
    for option in PAUSE_MENU_OPTIONS:
        assert str(option) in text


@pytest.mark.parametrize('cursor', range(len(PAUSE_MENU_OPTIONS)))
def test_pause_menu_highlights_selected_option(cursor):
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.MENU
    _ui_state(runner).main_menu_cursor = cursor

    can_load = persistence.has_save()

    for i, option in enumerate(PAUSE_MENU_OPTIONS):
        x, y = _find_text(runner, str(option))
        if option in (MenuOption.CONTINUE, MenuOption.LOAD) and not can_load:
            expected = UI_GRAY_DARK
        else:
            expected = UI_YELLOW if i == cursor else UI_WHITE
        assert runner.get_console_fg(x, y) == expected


# --- MenuSystem.render_combining_menu ---------------------------------------


def test_experiment_view_shows_inventory_selection():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 2)
    runner.give_item('reagent_b', 1)
    ui = _ui_state(runner)
    ui.crafting_cursor = 0
    ui.selected_for_crafting = {ItemType('reagent_a'): 1}
    runner.game_state.display_mode = DisplayMode.COMBINING  # defaults to the Experiment view

    text = _full_text(runner)
    assert 'Experiment' in text  # active tab label
    assert 'REAGENT_A: 2 (Selected: 1)' in text
    assert 'REAGENT_B: 1 (Selected: 0)' in text


def test_spellbook_view_shows_recipe_and_stats():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {(ItemType('reagent_a'), ItemType('reagent_b'))}
    runner.give_spell('test_bolt', 2)
    _ui_state(runner).crafting_view = CraftingView.SPELLBOOK
    runner.game_state.display_mode = DisplayMode.COMBINING

    text = _full_text(runner)
    assert 'TEST_BOLT' in text  # list entry (enum name)
    assert 'Test Bolt' in text  # detail header (display name)
    assert 'zaps and slows' in text  # description
    assert 'Radius 0' in text
    assert 'Damage 12' in text
    assert 'REAGENT_A, REAGENT_B' in text  # recipe, comma-joined


def test_spellbook_collapses_duplicate_ingredients():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_blast')] = {(ItemType('reagent_a'), ItemType('reagent_a'))}
    _ui_state(runner).crafting_view = CraftingView.SPELLBOOK
    runner.game_state.display_mode = DisplayMode.COMBINING

    assert '2x REAGENT_A' in _full_text(runner)


def test_spellbook_dims_unaffordable_spell():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {(ItemType('reagent_a'), ItemType('reagent_b'))}
    _ui_state(runner).crafting_view = CraftingView.SPELLBOOK
    runner.game_state.display_mode = DisplayMode.COMBINING

    # The selected entry is dimmed (gray, not the highlighted yellow) while unaffordable.
    assert runner.get_console_fg(*_find_text(runner, 'TEST_BOLT')) == UI_GRAY

    runner.give_item('reagent_a', 1)
    runner.give_item('reagent_b', 1)
    assert runner.get_console_fg(*_find_text(runner, 'TEST_BOLT')) == UI_YELLOW


def test_combining_menu_highlights_cursor_row():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 1)  # sorts before reagent_b
    runner.give_item('reagent_b', 1)
    _ui_state(runner).crafting_cursor = 0
    runner.game_state.display_mode = DisplayMode.COMBINING

    cursor_x, cursor_y = _find_text(runner, 'REAGENT_A')
    other_x, other_y = _find_text(runner, 'REAGENT_B')
    assert runner.get_console_fg(cursor_x, cursor_y) == UI_WHITE
    assert runner.get_console_fg(other_x, other_y) == UI_GRAY_DARK


# --- MenuSystem.render_casting_menu -----------------------------------------


def test_casting_menu_lists_spell_with_metadata():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 2)  # fixtures: radius 0
    runner.game_state.display_mode = DisplayMode.CASTING

    text = _full_text(runner)
    assert 'TEST_BOLT: 2 charges' in text
    assert '(Radius: 0)' in text


def test_casting_menu_windows_long_list_without_overflow():
    # The casting box fits 6 double-spaced rows; the basic attack plus seven charged fixture
    # spells force it to scroll. With the cursor on the last entry, that entry stays visible,
    # an earlier one scrolls off behind a '▲', and the footer is not pushed out of the box.
    runner = HeadlessRunner(use_random_map=False)
    spell_ids = ['test_bolt', 'test_blast', 'test_rare', 'test_shove', 'test_soak', 'test_zap', 'test_quench']
    for sid in spell_ids:
        runner.give_spell(sid, 1)
    available = available_spells()
    _ui_state(runner).casting_cursor = len(available) - 1  # last spell
    runner.game_state.display_mode = DisplayMode.CASTING

    text = _full_text(runner)
    assert available[-1].name in text  # cursor's spell is visible
    assert available[0].name not in text  # first spell scrolled off the top
    assert '▲' in text  # "more above" indicator
    assert 'Arrows: Select' in text  # footer intact, not overwritten by an overflowing row


def test_casting_menu_lists_the_basic_attack_when_nothing_is_discovered():
    # Before any spell is crafted, the picker still lists the basic attack, stocked to its
    # per-floor capacity.
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.CASTING

    assert 'TEST_WAND: 2 charges' in _full_text(runner)


def test_casting_menu_empty_when_even_the_basic_is_spent():
    # The basic refills each floor but can run dry within one; with nothing left to cast the
    # picker says so rather than rendering an empty box.
    runner = HeadlessRunner(use_random_map=False)
    spell_inv = esper.component_for_entity(runner.player, SpellInventory)
    spell_inv.spells[SpellType('test_wand')] = 0
    runner.game_state.display_mode = DisplayMode.CASTING

    assert 'No spells with charges!' in _full_text(runner)


def test_casting_menu_ignores_zero_charge_spells():
    runner = HeadlessRunner(use_random_map=False)
    spell_inv = esper.component_for_entity(runner.player, SpellInventory)
    spell_inv.spells[SpellType('test_bolt')] = 0
    runner.game_state.display_mode = DisplayMode.CASTING

    text = _full_text(runner)
    assert 'TEST_BOLT' not in text  # a depleted spell drops out of the picker
    assert 'TEST_WAND' in text  # the basic attack remains, always castable


# --- MenuSystem.render_settings_menu ----------------------------------------


def test_settings_menu_shows_keyboard_bindings_without_a_controller(mocker):
    mocker.patch('src.ui_systems.menus.connected_controller_name', return_value=None)
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SETTINGS

    rows = runner.get_console_text()
    assert any('Controller: none detected' in r for r in rows)
    move_up_row = next(r for r in rows if 'MOVE_UP' in r)
    assert 'UP' in move_up_row.split()  # its bound key, as a column of its own
    open_crafting_row = next(r for r in rows if 'OPEN_CRAFTING' in r)
    assert 'C' in open_crafting_row.split()


def test_settings_menu_shows_controller_column_when_connected(mocker):
    mocker.patch('src.ui_systems.menus.connected_controller_name', return_value='Test Pad')
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SETTINGS

    rows = runner.get_console_text()
    assert any('Controller: Test Pad' in r for r in rows)
    # Movement shows the fixed control; a rebindable action shows its bound button.
    assert 'D-Pad' in next(r for r in rows if 'MOVE_UP' in r)
    assert 'A' in next(r for r in rows if 'CONFIRM' in r).split()


def test_settings_menu_shows_remapping_prompt(mocker):
    mocker.patch('src.ui_systems.menus.connected_controller_name', return_value=None)
    runner = HeadlessRunner(use_random_map=False)
    _ui_state(runner).remapping_action = InputAction.MOVE_UP
    runner.game_state.display_mode = DisplayMode.SETTINGS

    move_up_row = next(r for r in runner.get_console_text() if 'MOVE_UP' in r)
    assert 'Press any key or button...' in move_up_row


# --- HUDSystem --------------------------------------------------------------


def test_hud_not_rendered_in_menu_mode():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.MENU

    assert 'HP:' not in _full_text(runner)


def test_hp_bar_full_is_all_red():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp, stats.max_hp = 100, 100

    assert 'HP: 100/100' in _full_text(runner)
    # Bar starts just past the text: HP_BAR_X(2) + len(text)(11) + 1 = 14.
    assert runner.get_console_fg(14, 46) == UI_RED


def test_hp_bar_partial_splits_filled_and_empty():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp, stats.max_hp = 10, 100  # ratio 0.1 -> filled_width 2

    text = _full_text(runner)
    assert 'HP: 10/100' in text
    start_x = 2 + len('HP: 10/100') + 1  # = 13
    assert runner.get_console_fg(start_x, 46) == UI_RED
    assert runner.get_console_fg(start_x + 5, 46) == UI_RED_DARK


def test_hp_bar_zero_is_all_empty():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp, stats.max_hp = 0, 100  # filled_width 0 -> guard skips red rect

    text = _full_text(runner)
    assert 'HP: 0/100' in text
    start_x = 2 + len('HP: 0/100') + 1  # = 12
    assert runner.get_console_fg(start_x, 46) == UI_RED_DARK


def test_floor_info_reflects_game_state():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.floor = 7

    assert 'Floor: 7' in _full_text(runner)


def test_message_log_frame_and_wrapping():
    runner = HeadlessRunner(use_random_map=False)
    log = esper.get_component(MessageLog)[0][1]
    # Longer than usable width (MSG_BOX_WIDTH - 4 = 42) so it wraps.
    log.add_simple_message('alpha beta gamma delta epsilon zeta eta theta iota')

    text = _full_text(runner)
    assert 'Messages' in text  # frame title
    assert 'alpha beta' in text
    assert 'iota' in text  # wrapped onto a second line


def test_message_log_scroll_shows_newest_by_default():
    runner = HeadlessRunner(use_random_map=False)
    log = esper.get_component(MessageLog)[0][1]
    for i in range(6):
        log.add_simple_message(f'line{i}')
    log.scroll_index = 0  # 0 = newest at the bottom

    text = _full_text(runner)
    # Visible window is MSG_BOX_HEIGHT - 2 = 3 lines: the three newest.
    assert 'line5' in text
    assert 'line3' in text
    assert 'line0' not in text


# --- ModalSystem ------------------------------------------------------------


def test_modal_renders_message_and_prompt():
    runner = HeadlessRunner(use_random_map=False)
    esper.create_entity(Modal(message='Hello modal'))

    text = _full_text(runner)
    assert 'Hello modal' in text
    assert 'Press any key to close' in text


# --- TargetingOverlaySystem -------------------------------------------------


def test_targeting_overlay_brackets_target_without_covering_it():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING
    px, py = runner.player_pos
    rx, ry = px + 2, py
    esper.create_entity(TargetingReticle(x=rx, y=ry, radius=1))

    rows = runner.get_console_text()
    # The target cell itself is left alone; bright brackets frame it instead.
    assert rows[ry][rx] != 'X'
    assert (rows[ry][rx - 1], rows[ry][rx + 1]) == ('[', ']')
    assert runner.get_console_fg(rx - 1, ry) == UI_YELLOW
    assert runner.get_console_fg(rx + 1, ry) == UI_YELLOW


def test_targeting_overlay_outlines_aoe_edge_not_interior():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING
    px, py = runner.player_pos
    rx, ry = px + 3, py
    esper.create_entity(TargetingReticle(x=rx, y=ry, radius=2))

    edge = blend(UI_BLACK, UI_MAROON, 0.6)
    # An in-range cell on the rim of the radius is shaded...
    assert runner.get_console_bg(rx, ry + 2) == edge
    # ...but the interior (the target's own cell) is not, so the enemy stays visible.
    assert runner.get_console_bg(rx, ry) != edge


def test_targeting_overlay_labels_the_aimed_spell_and_charges():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.TARGETING
    _ui_state(runner).active_targeting_spell_id = 'test_wand'
    px, py = runner.player_pos
    esper.create_entity(TargetingReticle(x=px + 1, y=py, radius=0))

    assert 'Aiming: TEST_WAND (2 charges)' in _full_text(runner)


def test_targeting_overlay_absent_without_reticle():
    runner = HeadlessRunner(use_random_map=False)

    rows = runner.get_console_text()
    assert not any(('[' in row or ']' in row) for row in rows)
