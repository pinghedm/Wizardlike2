import esper
import pytest

from src.components import Effect, EffectType, Stats, StatusEffects, StatusType
from src.constants import STATUS_PULSE_INTERVAL
from src.systems import apply_effect, get_action_cooldown
from tests.headless_runner import HeadlessRunner

# --- apply_effect: lingering effects are stored as their own copy --------------


def test_apply_poison_stores_a_copy_carrying_power_and_duration():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    source = Effect(type=EffectType.POISON, power=4, duration=90)

    apply_effect(enemy, source)
    stored = esper.component_for_entity(enemy, StatusEffects).active[StatusType.POISON]

    assert stored.power == 4
    assert stored.duration == 90
    assert stored is not source  # a copy, so ticking it never mutates the spell config


# --- StatusSystem: recurring effects pulse on the global cadence ---------------


def test_poison_pulses_damage_once_per_interval_until_it_expires():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    # Two intervals' worth of duration -> exactly two damage pulses (at d=60 and d=30).
    duration = 2 * STATUS_PULSE_INTERVAL
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.POISON] = Effect(
        type=EffectType.POISON, power=4, duration=duration
    )

    runner.tick(duration)

    assert esper.component_for_entity(enemy, Stats).hp == 30 - 2 * 4
    assert StatusType.POISON not in esper.component_for_entity(enemy, StatusEffects).active


def test_regen_pulses_healing_capped_at_max_hp():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos, {**runner.enemy_config(), 'hp': 10})
    esper.component_for_entity(enemy, Stats).max_hp = 20
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.REGEN] = Effect(
        type=EffectType.REGEN, power=100, duration=STATUS_PULSE_INTERVAL
    )

    runner.tick(STATUS_PULSE_INTERVAL)

    assert esper.component_for_entity(enemy, Stats).hp == 20  # one big pulse, clamped


@pytest.mark.parametrize('status_type', [StatusType.SLOW, StatusType.HASTE, StatusType.STUN])
def test_marker_status_ages_without_dealing_damage(status_type):
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    hp = esper.component_for_entity(enemy, Stats).hp
    esper.component_for_entity(enemy, StatusEffects).active[status_type] = Effect(
        type=EffectType(status_type.value), duration=STATUS_PULSE_INTERVAL
    )

    runner.tick(STATUS_PULSE_INTERVAL)

    assert esper.component_for_entity(enemy, Stats).hp == hp  # power 0 -> no pulse
    assert status_type not in esper.component_for_entity(enemy, StatusEffects).active


# --- get_action_cooldown: markers gate action speed ----------------------------


def test_slow_doubles_and_haste_halves_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    active = esper.component_for_entity(enemy, StatusEffects).active

    assert get_action_cooldown(enemy, 10) == 10  # baseline, no status

    active[StatusType.SLOW] = Effect(type=EffectType.SLOW, duration=99)
    assert get_action_cooldown(enemy, 10) == 20

    del active[StatusType.SLOW]
    active[StatusType.HASTE] = Effect(type=EffectType.HASTE, duration=99)
    assert get_action_cooldown(enemy, 10) == 5
