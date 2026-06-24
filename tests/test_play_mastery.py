"""Spell mastery: casting a spell raises its per-spell rank, which scales its effect power
and grants bonus charges on refill/craft. Tuning is fixture-owned (tests/fixtures/spells.yaml):
test_wand is masterable (casts_per_rank 2, max_rank 3, charge_bonus 1, power +0.5/rank);
test_blast carries no mastery block, so it stays unmasterable.
"""

import esper

from src.components import SpellMastery, SpellType, Stats
from src.systems import (
    cast_spell,
    grant_spell_mastery,
    refill_basic_spells,
    reset_momentum,
    spell_charge_bonus,
    spell_power_mult,
    spell_rank,
)
from tests.headless_runner import HeadlessRunner

WAND = SpellType('test_wand')  # casts_for_rank with casts_per_rank 2: rank1=2, rank2=6, rank3=12
BLAST = SpellType('test_blast')  # no mastery block


def _rank_up_wand(times: int):
    """Drive `times` casts' worth of mastery toward test_wand."""
    for _ in range(times):
        grant_spell_mastery(WAND)


def test_casting_accrues_mastery_and_raises_rank():
    runner = HeadlessRunner(use_random_map=False)
    assert spell_rank(WAND) == 0

    _rank_up_wand(2)  # the rank-1 threshold

    assert spell_rank(WAND) == 1
    assert esper.component_for_entity(runner.player, SpellMastery).casts[WAND] == 2


def test_grant_reports_only_the_cast_that_crosses_a_rank():
    runner = HeadlessRunner(use_random_map=False)
    assert runner  # world built

    assert grant_spell_mastery(WAND) is None  # 1 cast: still rank 0
    assert grant_spell_mastery(WAND) == 1  # 2nd cast crosses into rank 1
    assert grant_spell_mastery(WAND) is None  # 3rd cast: no new rank yet


def test_mastery_scales_spell_damage():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    runner.give_spell('test_wand', 5)

    enemy = runner.spawn_enemy(px + 1, py)
    base_hp = esper.component_for_entity(enemy, Stats).hp
    cast_spell('test_wand', px + 1, py)  # unmastered: base power 4
    base_damage = base_hp - esper.component_for_entity(enemy, Stats).hp
    assert base_damage == 4

    _rank_up_wand(2)  # -> rank 1, power x1.5
    assert spell_power_mult(WAND) == 1.5

    # Isolate mastery from the combo: the prior cast built a stack that would also amplify.
    reset_momentum()
    other = runner.spawn_enemy(px - 1, py)
    other_hp = esper.component_for_entity(other, Stats).hp
    cast_spell('test_wand', px - 1, py)
    mastered_damage = other_hp - esper.component_for_entity(other, Stats).hp
    assert mastered_damage == round(base_damage * 1.5)


def test_mastery_grants_bonus_charges_on_refill():
    runner = HeadlessRunner(use_random_map=False)
    refill_basic_spells()
    base_charges = runner.spell_charges('test_wand')

    _rank_up_wand(2)  # -> rank 1, charge_bonus_per_rank 1
    assert spell_charge_bonus(WAND) == 1

    refill_basic_spells()
    assert runner.spell_charges('test_wand') == base_charges + 1


def test_rank_caps_at_the_spells_max_rank():
    runner = HeadlessRunner(use_random_map=False)
    assert runner

    _rank_up_wand(100)

    assert spell_rank(WAND) == 3  # test_wand's max_rank


def test_a_spell_without_a_mastery_block_never_ranks():
    runner = HeadlessRunner(use_random_map=False)
    assert runner

    assert grant_spell_mastery(BLAST) is None
    assert spell_rank(BLAST) == 0
    assert spell_charge_bonus(BLAST) == 0
    assert spell_power_mult(BLAST) == 1.0
