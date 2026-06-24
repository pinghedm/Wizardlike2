"""Arcane momentum (combo): casting and slaying build stacks that amplify damage and enrich
loot; the meter bleeds after a lull and shatters when the player is hit. test_wand carries
momentum_damage_per_stack 0.5 (fixtures); MAX_STACKS/DECAY_TICKS/STACKS_PER_BONUS_DROP are the
Momentum component's ClassVars.
"""

import esper

from src.components import Momentum, Stats
from src.systems import build_momentum, cast_spell, deal_damage, reset_momentum
from src.systems.momentum import MomentumSystem
from tests.headless_runner import HeadlessRunner


def _momentum(runner) -> Momentum:
    return esper.component_for_entity(runner.player, Momentum)


def test_casting_builds_a_stack():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_wand', 3)
    px, py = runner.player_pos

    cast_spell('test_wand', px + 2, py)

    assert _momentum(runner).stacks == 1


def test_slaying_an_enemy_builds_a_stack():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)
    esper.component_for_entity(enemy, Stats).hp = 0

    runner.tick(1)  # DeathSystem credits the kill

    assert _momentum(runner).stacks == 1


def test_stacks_are_capped_at_max():
    runner = HeadlessRunner(use_random_map=False)
    build_momentum(Momentum.MAX_STACKS + 5)
    assert _momentum(runner).stacks == Momentum.MAX_STACKS


def test_momentum_amplifies_damage():
    # test_blast carries momentum scaling but no mastery, so the boost is momentum alone.
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    runner.give_spell('test_blast', 5)

    enemy = runner.spawn_enemy(px + 2, py)
    base_hp = esper.component_for_entity(enemy, Stats).hp
    cast_spell('test_blast', px + 2, py)  # no momentum yet: base power 20
    base_damage = base_hp - esper.component_for_entity(enemy, Stats).hp
    assert base_damage == 20

    reset_momentum()  # the measuring cast itself built a stack; clear it
    build_momentum(2)  # 2 stacks x 0.5/stack -> x2.0 damage
    other = runner.spawn_enemy(px - 2, py)
    other_hp = esper.component_for_entity(other, Stats).hp
    cast_spell('test_blast', px - 2, py)
    boosted = other_hp - esper.component_for_entity(other, Stats).hp
    assert boosted == round(base_damage * 2.0)


def test_taking_a_hit_shatters_momentum():
    runner = HeadlessRunner(use_random_map=False)
    build_momentum(5)

    deal_damage(runner.player, 3, 'ouch', (255, 0, 0))

    assert _momentum(runner).stacks == 0


def test_momentum_decays_after_a_lull():
    runner = HeadlessRunner(use_random_map=False)
    build_momentum(2)
    momentum = _momentum(runner)
    momentum.decay_ticks = 1  # on the brink of bleeding a stack

    MomentumSystem().process()

    assert momentum.stacks == 1
    assert momentum.decay_ticks == Momentum.DECAY_TICKS  # timer rearms for the next stack


def test_bonus_drops_scale_with_stacks():
    runner = HeadlessRunner(use_random_map=False)
    assert runner
    momentum = Momentum(stacks=2 * Momentum.STACKS_PER_BONUS_DROP)
    assert momentum.bonus_drops == 2


def test_reset_is_a_noop_without_stacks():
    runner = HeadlessRunner(use_random_map=False)
    reset_momentum()  # no stacks, no message, no error
    assert _momentum(runner).stacks == 0
