"""MenuSystem renders pixel-native, so its screens can't be read back as console text. Instead
each screen's drawn rows come from a pure content method (`_*_rows` / `_*_lines`), and these tests
assert on those rows' text and colors. A couple of pixel smokes confirm the render path draws."""

import esper
import pygame
import pytest

from src import persistence
from src.components import (
    Inventory,
    ItemType,
    KnownRecipes,
    Settings,
    Shopkeeper,
    ShopOffer,
    ShopOfferKind,
    SpellInventory,
    SpellType,
    UIState,
)
from src.constants import UI_GRAY, UI_GRAY_DARK, UI_WHITE, UI_YELLOW
from src.ecs_helpers import try_get_singleton
from src.entities import create_game_state, create_ui_state
from src.input_handlers import available_spells
from src.states import PAUSE_MENU_OPTIONS, TITLE_MENU_OPTIONS, DisplayMode, MenuOption
from src.ui_systems import MenuSystem
from tests.headless_runner import HeadlessRunner

SENTINEL = (255, 0, 255)


def _menu(runner: HeadlessRunner) -> MenuSystem:
    return MenuSystem(runner.surface, runner.asset_loader)


def _ui_state(runner: HeadlessRunner) -> UIState:
    return esper.get_component(UIState)[0][1]


def _texts(rows) -> list[str]:
    return [''.join(text for text, _ in row) for row in rows]


def _find(rows, needle):
    for row in rows:
        if needle in ''.join(text for text, _ in row):
            return row
    raise AssertionError(f'{needle!r} not found in {_texts(rows)}')


def _color(row):
    return row[0][1]


# --- main / pause menu ------------------------------------------------------


def test_title_menu_lists_the_title_options():
    runner = HeadlessRunner(use_random_map=False)
    esper.clear_database()  # strip to the startup title state (no player)
    create_game_state()
    create_ui_state()

    texts = _texts(_menu(runner)._main_menu_rows())
    for option in TITLE_MENU_OPTIONS:
        assert any(str(option) in t for t in texts)


def test_pause_menu_lists_the_pause_options():
    runner = HeadlessRunner(use_random_map=False)  # a player exists -> pause menu
    texts = _texts(_menu(runner)._main_menu_rows())
    for option in PAUSE_MENU_OPTIONS:
        assert any(str(option) in t for t in texts)


@pytest.mark.parametrize('cursor', range(len(PAUSE_MENU_OPTIONS)))
def test_pause_menu_highlights_the_selected_option(cursor):
    runner = HeadlessRunner(use_random_map=False)
    _ui_state(runner).main_menu_cursor = cursor
    can_load = persistence.has_save()

    rows = _menu(runner)._main_menu_rows()
    for i, option in enumerate(PAUSE_MENU_OPTIONS):
        row = _find(rows, str(option))
        if option in (MenuOption.CONTINUE, MenuOption.LOAD) and not can_load:
            expected = UI_GRAY_DARK
        else:
            expected = UI_YELLOW if i == cursor else UI_WHITE
        assert _color(row) == expected


def test_main_menu_render_draws_to_the_surface():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.MENU
    runner.surface.fill(SENTINEL)

    _menu(runner).process()

    drawn = any(
        tuple(runner.surface.get_at((x, y)))[:3] != SENTINEL for x in range(700, 900, 20) for y in range(400, 600, 20)
    )
    assert drawn  # the panel + options actually blit somewhere near center


# --- crafting ---------------------------------------------------------------


def test_experiment_view_lists_inventory_with_selection_counts():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 2)
    runner.give_item('reagent_b', 1)
    ui = _ui_state(runner)
    ui.crafting_cursor = 0
    ui.selected_for_crafting = {ItemType('reagent_a'): 1}

    rows, _up, _down = _menu(runner)._experiment_rows(ui, try_get_singleton(Inventory), 17)
    texts = _texts(rows)
    assert any('REAGENT_A: 2 (Selected: 1)' in t for t in texts)
    assert any('REAGENT_B: 1 (Selected: 0)' in t for t in texts)


def test_experiment_view_highlights_the_cursor_row():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_item('reagent_a', 1)  # sorts before reagent_b
    runner.give_item('reagent_b', 1)
    _ui_state(runner).crafting_cursor = 0

    rows, _up, _down = _menu(runner)._experiment_rows(_ui_state(runner), try_get_singleton(Inventory), 17)
    assert _color(_find(rows, 'REAGENT_A')) == UI_WHITE  # selected
    assert _color(_find(rows, 'REAGENT_B')) == UI_GRAY_DARK


def test_spellbook_lists_a_known_recipe():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {(ItemType('reagent_a'), ItemType('reagent_b'))}
    runner.give_spell('test_bolt', 2)

    rows, _up, _down = _menu(runner)._spellbook_list_rows(
        _ui_state(runner), recipes, try_get_singleton(SpellInventory), 18
    )
    assert any('TEST_BOLT' in t for t in _texts(rows))


def test_spellbook_dims_an_unaffordable_spell_then_brightens_it():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {(ItemType('reagent_a'), ItemType('reagent_b'))}
    menu = _menu(runner)

    rows, _u, _d = menu._spellbook_list_rows(_ui_state(runner), recipes, try_get_singleton(SpellInventory), 18)
    assert _color(_find(rows, 'TEST_BOLT')) == UI_GRAY  # selected but unaffordable

    runner.give_item('reagent_a', 1)
    runner.give_item('reagent_b', 1)
    rows, _u, _d = menu._spellbook_list_rows(_ui_state(runner), recipes, try_get_singleton(SpellInventory), 18)
    assert _color(_find(rows, 'TEST_BOLT')) == UI_YELLOW


def test_spell_detail_shows_name_description_stats_and_recipe():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_bolt')] = {(ItemType('reagent_a'), ItemType('reagent_b'))}

    lines = _menu(runner)._spell_detail_lines(SpellType('test_bolt'), recipes, try_get_singleton(Inventory), 1000)
    text = '\n'.join(_texts(lines))
    assert 'Test Bolt' in text  # display name
    assert 'zaps and slows' in text  # description
    assert 'Radius 0' in text
    assert 'Damage 12' in text
    assert 'REAGENT_A, REAGENT_B' in text  # recipe, comma-joined


def test_spell_detail_collapses_duplicate_ingredients():
    runner = HeadlessRunner(use_random_map=False)
    recipes = esper.component_for_entity(runner.player, KnownRecipes)
    recipes.recipes[SpellType('test_blast')] = {(ItemType('reagent_a'), ItemType('reagent_a'))}

    lines = _menu(runner)._spell_detail_lines(SpellType('test_blast'), recipes, try_get_singleton(Inventory), 1000)
    assert '2x REAGENT_A' in '\n'.join(_texts(lines))


# --- casting picker ---------------------------------------------------------


def _casting_rows(runner, visible=6):
    return _menu(runner)._casting_rows(_ui_state(runner), try_get_singleton(SpellInventory), False, visible)


def test_casting_menu_lists_a_spell_with_metadata():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 2)  # fixtures: radius 0

    text = '\n'.join(_texts(_casting_rows(runner)[0]))
    assert 'TEST_BOLT: 2 charges' in text
    assert '(Radius: 0)' in text


def test_casting_menu_windows_a_long_list():
    runner = HeadlessRunner(use_random_map=False)
    for sid in ('test_bolt', 'test_blast', 'test_rare', 'test_shove', 'test_soak', 'test_zap', 'test_quench'):
        runner.give_spell(sid, 1)
    available = available_spells()
    _ui_state(runner).casting_cursor = len(available) - 1  # scrolled to the last spell

    rows, up, _down = _casting_rows(runner)
    text = '\n'.join(_texts(rows))
    assert available[-1].name in text  # the cursor row stays in view
    assert available[0].name not in text  # the top scrolled off
    assert up  # ...and the up-arrow shows there's more above


def test_casting_menu_lists_the_basic_attack_when_nothing_is_discovered():
    runner = HeadlessRunner(use_random_map=False)
    assert any('TEST_WAND: 2 charges' in t for t in _texts(_casting_rows(runner)[0]))


def test_casting_menu_reports_empty_when_even_the_basic_is_spent():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_wand')] = 0
    assert any('No spells with charges!' in t for t in _texts(_casting_rows(runner)[0]))


def test_casting_menu_ignores_zero_charge_spells():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_bolt')] = 0

    text = '\n'.join(_texts(_casting_rows(runner)[0]))
    assert 'TEST_BOLT' not in text  # a depleted spell drops out
    assert 'TEST_WAND' in text  # the basic attack remains


# --- shop -------------------------------------------------------------------


def _ingredient_offer(label: str, price: int, item: str = 'reagent_a') -> ShopOffer:
    return ShopOffer(kind=ShopOfferKind.INGREDIENT, price=price, label=label, purchaseable=ItemType(item), amount=1)


def test_shop_lists_offers():
    runner = HeadlessRunner(use_random_map=False)
    offers = [_ingredient_offer('Reagent A', 5), _ingredient_offer('Reagent B', 8)]
    rows, _u, _d = _menu(runner)._shop_rows(_ui_state(runner), offers, 50, 9)
    texts = _texts(rows)
    assert any('Reagent A' in t for t in texts)
    assert any('Reagent B' in t for t in texts)


def test_shop_says_sold_out_with_no_offers():
    runner = HeadlessRunner(use_random_map=False)
    rows, _u, _d = _menu(runner)._shop_rows(_ui_state(runner), [], 10, 9)
    assert any('Sold out.' in t for t in _texts(rows))


def test_shop_dims_an_unaffordable_offer():
    runner = HeadlessRunner(use_random_map=False)
    offers = [_ingredient_offer('Cheap', 5), _ingredient_offer('Pricey', 10)]
    _ui_state(runner).shop_cursor = 0  # 'Cheap' selected and affordable

    rows, _u, _d = _menu(runner)._shop_rows(_ui_state(runner), offers, 6, 9)
    assert _color(_find(rows, 'Cheap')) == UI_YELLOW
    assert _color(_find(rows, 'Pricey')) == UI_GRAY_DARK


def test_shop_marks_the_selected_row_and_its_running_total():
    runner = HeadlessRunner(use_random_map=False)
    offers = [_ingredient_offer('Reagent A', 5), _ingredient_offer('Reagent B', 8)]
    ui = _ui_state(runner)
    ui.shop_cursor = 1
    ui.shop_quantity = 3

    rows, _u, _d = _menu(runner)._shop_rows(ui, offers, 100, 9)
    assert 'x3 (24 G)' in '\n'.join(_texts(rows))  # 8 * 3
    assert _color(_find(rows, 'Reagent B')) == UI_YELLOW
    assert _color(_find(rows, 'Reagent A')) == UI_WHITE


def test_shop_windows_a_long_stock_list():
    runner = HeadlessRunner(use_random_map=False)
    offers = [_ingredient_offer(f'Item {i:02d}', 1) for i in range(20)]
    _ui_state(runner).shop_cursor = 19  # scrolled to the bottom

    rows, _u, _d = _menu(runner)._shop_rows(_ui_state(runner), offers, 100, 9)
    text = '\n'.join(_texts(rows))
    assert 'Item 19' in text
    assert 'Item 00' not in text


def test_shop_draws_nothing_without_a_shopkeeper():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.display_mode = DisplayMode.SHOPPING  # no Shopkeeper entity
    runner.surface.fill(SENTINEL)

    _menu(runner).process()
    assert tuple(runner.surface.get_at((800, 500)))[:3] == SENTINEL  # render returned early


# --- settings ---------------------------------------------------------------


def _bindings(runner, has_controller):
    settings = try_get_singleton(Settings)
    return _menu(runner)._settings_binding_rows(_ui_state(runner), settings, has_controller)


def test_settings_shows_keyboard_bindings(mocker):
    mocker.patch('src.ui_systems.menus.connected_controller_name', return_value=None)
    runner = HeadlessRunner(use_random_map=False)

    rows = _bindings(runner, has_controller=False)
    assert _find(rows, 'MOVE_UP')[1][0] == 'UP'  # the key column
    assert _find(rows, 'OPEN_CRAFTING')[1][0] == 'C'


def test_settings_shows_the_controller_column_when_connected(mocker):
    mocker.patch('src.ui_systems.menus.connected_controller_name', return_value='Test Pad')
    runner = HeadlessRunner(use_random_map=False)

    rows = _bindings(runner, has_controller=True)
    assert 'D-Pad' in _find(rows, 'MOVE_UP')[2][0]  # movement is the fixed control
    assert _find(rows, 'CONFIRM')[2][0] == 'A'  # a rebindable action's bound button


def test_settings_shows_the_remapping_prompt(mocker):
    mocker.patch('src.ui_systems.menus.connected_controller_name', return_value=None)
    runner = HeadlessRunner(use_random_map=False)
    from src.components import InputAction

    _ui_state(runner).remapping_action = InputAction.MOVE_UP

    rows = _bindings(runner, has_controller=False)
    assert 'Press any key or button...' in _find(rows, 'MOVE_UP')[1][0]


def test_settings_pref_row_shows_the_toggle_value():
    runner = HeadlessRunner(use_random_map=False)
    settings = try_get_singleton(Settings)
    settings.muted = True

    rows = _menu(runner)._settings_pref_rows(_ui_state(runner), settings)
    muted_row = _find(rows, 'Muted')
    assert '< ON >' in ''.join(t for t, _ in muted_row)


def test_pygame_menu_renders_without_error():
    # A blanket smoke: driving each menu mode's render path doesn't raise.
    runner = HeadlessRunner(use_random_map=False)
    esper.create_entity(Shopkeeper(offers=[_ingredient_offer('X', 1)]))
    for mode in (
        DisplayMode.MENU,
        DisplayMode.COMBINING,
        DisplayMode.CASTING,
        DisplayMode.SHOPPING,
        DisplayMode.SETTINGS,
        DisplayMode.GAME_OVER,
    ):
        runner.game_state.display_mode = mode
        runner.surface.fill(SENTINEL)
        _menu(runner).process()
    assert isinstance(runner.surface, pygame.Surface)
