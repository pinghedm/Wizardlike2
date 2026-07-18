import esper

from src.components import (
    Effect,
    EffectMultipliers,
    EffectType,
    Enemy,
    Point,
    Position,
    Stats,
    StatusEffects,
    StatusType,
)
from src.procgen import DEPTH_DAMAGE_GROWTH, DEPTH_HP_GROWTH, spawn_enemy
from src.systems.combat import apply_effect
from tests.headless_runner import HeadlessRunner


def _target(runner: HeadlessRunner, x: int, y: int, **multipliers: float) -> int:
    """A plain enemy at (x, y) carrying the given per-EffectType multipliers."""
    enemy = runner.spawn_enemy(x, y, runner.enemy_config())
    esper.add_component(enemy, EffectMultipliers(by_type={EffectType(k): v for k, v in multipliers.items()}))
    return enemy


# --- apply_effect scaling: resist / immune / vulnerable -------------------------


def test_resistance_halves_incoming_damage():
    runner = HeadlessRunner(use_random_map=False)
    enemy = _target(runner, 3, 3, damage=0.5)
    before = esper.component_for_entity(enemy, Stats).hp

    apply_effect(enemy, Effect(type=EffectType.DAMAGE, power=10))

    assert esper.component_for_entity(enemy, Stats).hp == before - 5


def test_immunity_negates_damage_entirely():
    runner = HeadlessRunner(use_random_map=False)
    enemy = _target(runner, 3, 3, damage=0)
    before = esper.component_for_entity(enemy, Stats).hp

    apply_effect(enemy, Effect(type=EffectType.DAMAGE, power=10))

    assert esper.component_for_entity(enemy, Stats).hp == before


def test_vulnerability_increases_damage():
    runner = HeadlessRunner(use_random_map=False)
    enemy = _target(runner, 3, 3, damage=1.5)
    before = esper.component_for_entity(enemy, Stats).hp

    apply_effect(enemy, Effect(type=EffectType.DAMAGE, power=10))

    assert esper.component_for_entity(enemy, Stats).hp == before - 15


def test_immunity_to_a_status_stores_no_status():
    runner = HeadlessRunner(use_random_map=False)
    enemy = _target(runner, 3, 3, stun=0)

    apply_effect(enemy, Effect(type=EffectType.STUN, duration=5))

    assert StatusType.STUN not in esper.component_for_entity(enemy, StatusEffects).active


def test_resistance_shortens_a_status_duration():
    runner = HeadlessRunner(use_random_map=False)
    enemy = _target(runner, 3, 3, slow=0.5)

    apply_effect(enemy, Effect(type=EffectType.SLOW, duration=90))

    assert esper.component_for_entity(enemy, StatusEffects).active[StatusType.SLOW].duration == 45


def test_immunity_blocks_knockback():
    runner = HeadlessRunner(use_random_map=False)
    enemy = _target(runner, 5, 5, knockback=0)

    apply_effect(enemy, Effect(type=EffectType.KNOCKBACK, power=3), origin=Point(4, 5))

    assert esper.component_for_entity(enemy, Position).point == Point(5, 5)  # shrugged off the shove


# --- depth scaling: deeper floors bite harder, bosses are exempt ----------------


def test_enemy_stats_scale_up_with_floor_depth():
    runner = HeadlessRunner(use_random_map=False)
    cfg = runner.enemy_config()  # test_enemy: hp 30, damage 10
    runner.game_state.floor = 6  # depth 5 floors in

    enemy = spawn_enemy(cfg, 3, 3, rooms=[])

    depth = 5
    assert esper.component_for_entity(enemy, Stats).hp == round(30 * (1 + DEPTH_HP_GROWTH * depth))
    assert esper.component_for_entity(enemy, Enemy).attack_damage == round(10 * (1 + DEPTH_DAMAGE_GROWTH * depth))


def test_boss_stats_are_not_depth_scaled():
    runner = HeadlessRunner(use_random_map=False)
    cfg = runner.enemy_config('test_boss')  # hp 100
    runner.game_state.floor = 10

    enemy = spawn_enemy(cfg, 3, 3, rooms=[])

    assert esper.component_for_entity(enemy, Stats).hp == 100  # hand-tuned, never auto-scaled


# --- the data path: an effect_multipliers block loads and attaches --------------


def test_effect_multipliers_load_and_attach_to_the_enemy():
    runner = HeadlessRunner(use_random_map=False)
    config = runner.enemy_config('test_resistant')

    assert config['effect_multipliers'] == {EffectType.DAMAGE: 0.5, EffectType.STUN: 0.0}

    enemy = spawn_enemy(config, 3, 3, rooms=[])
    mods = esper.component_for_entity(enemy, EffectMultipliers)
    assert mods.multiplier(EffectType.DAMAGE) == 0.5
    assert mods.multiplier(EffectType.STUN) == 0.0
    assert mods.multiplier(EffectType.POISON) == 1.0  # unlisted types are normal
