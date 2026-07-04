import pytest

from tools.validate_data import validate_modifiers, validate_tiles

DAMAGING = [{'type': 'damage', 'power': 5}]
NON_DAMAGING = [{'type': 'heal', 'power': 5}]


def _tile(**overrides):
    tile = {'id': 't', 'type': 'floor', 'depth': [1, 10]}
    tile.update(overrides)
    return tile


def test_validate_modifiers_accepts_a_vulnerability_and_a_resistance():
    mods = [{'vs_status': 'wet', 'damage_mult': 2.0}, {'vs_status': 'slow', 'damage_mult': 0.5}]
    assert validate_modifiers(mods, DAMAGING, 'Spell "x"') == 0


@pytest.mark.parametrize(
    'modifier',
    [
        {'vs_status': 'wet', 'damage_mult': 1},  # multiplier of 1 is a no-op
        {'vs_status': 'wet', 'damage_mult': 0},  # nulls all damage authored as an effect instead
        {'vs_status': 'wet', 'damage_mult': -2},  # negative would heal
        {'vs_status': 'soggy', 'damage_mult': 2},  # not a real StatusType
        {'vs_status': 'wet'},  # missing damage_mult
        {'damage_mult': 2},  # missing vs_status
        {'vs_status': 'wet', 'damage_mult': 2, 'oops': 1},  # unexpected field
    ],
)
def test_validate_modifiers_rejects_a_bad_modifier(modifier):
    assert validate_modifiers([modifier], DAMAGING, 'Spell "x"') > 0


def test_validate_modifiers_rejects_modifiers_on_a_spell_with_no_damaging_effect():
    mods = [{'vs_status': 'wet', 'damage_mult': 2.0}]
    assert validate_modifiers(mods, NON_DAMAGING, 'Spell "x"') > 0


def test_validate_modifiers_rejects_an_empty_list():
    assert validate_modifiers([], DAMAGING, 'Spell "x"') > 0


# --- validate_tiles ------------------------------------------------------------


@pytest.mark.parametrize(
    'tile',
    [
        _tile(id='floor', type='floor'),
        _tile(id='lava', type='hazard', effects=[{'type': 'damage', 'power': 10}]),
        _tile(id='spikes', type='trap', effects=[{'type': 'damage', 'power': 10}]),
    ],
)
def test_validate_tiles_accepts_a_well_formed_tile(tile):
    assert validate_tiles([tile]) == 0


@pytest.mark.parametrize(
    'tile',
    [
        _tile(id='x', type='hazard', effects=[{'type': 'damage', 'power': 5}], oops=1),  # unknown key
        _tile(id='x', type='hazard', effects=[{'type': 'nonsense', 'power': 5}]),  # invalid effect
        _tile(id='x', type='rubble'),  # not a real TileType
        _tile(id='x', type='floor', effects=[{'type': 'damage', 'power': 5}]),  # effects on a structural tile
        _tile(id='x', type='hazard'),  # hazard with no effect payload
    ],
)
def test_validate_tiles_rejects_a_bad_tile(tile):
    assert validate_tiles([tile]) > 0
