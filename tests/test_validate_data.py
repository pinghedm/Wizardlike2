import pytest

from tools.validate_data import validate_modifiers

DAMAGING = [{'type': 'damage', 'power': 5}]
NON_DAMAGING = [{'type': 'heal', 'power': 5}]


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
