import esper

from src.components import (
    Actor,
    Configuration,
    Effect,
    EffectType,
    EnemyAbility,
    FieldOfView,
    Point,
    Position,
    Stats,
    StatusEffects,
    StatusType,
)
from src.systems import _can_use_ability
from tests.headless_runner import HeadlessRunner


def _ranged(power: int = 7, slow_duration: int = 60, rng: int = 5) -> EnemyAbility:
    return EnemyAbility(
        range=rng,
        effects=[
            Effect(type=EffectType.DAMAGE, power=power),
            Effect(type=EffectType.SLOW, duration=slow_duration),
        ],
    )


def _see_player(enemy: int, player_pos: Point):
    """Force the enemy's FOV to include the player without recomputation, so tests
    isolate ability behavior from FOVSystem's tick ordering."""
    fov = esper.component_for_entity(enemy, FieldOfView)
    fov.visible_tiles = {player_pos}
    fov.dirty = False


# --- the data path: an ability block parses into an EnemyAbility ---------------


def test_enemy_ability_loads_as_enemy_ability_with_effects():
    HeadlessRunner(use_random_map=False)  # builds the Configuration singleton from fixtures
    config = esper.get_component(Configuration)[0][1].enemies['test_caster']

    ability = config['ability']
    assert isinstance(ability, EnemyAbility)
    assert ability.range == 5
    assert [e.type for e in ability.effects] == [EffectType.DAMAGE, EffectType.SLOW]


# --- _can_use_ability: range and line-of-sight gates ---------------------------


def test_ability_blocked_when_player_out_of_range():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 6, py, {**runner.enemy_config(), 'ability': _ranged(rng=5)})
    _see_player(enemy, Point(px, py))

    assert not _can_use_ability(enemy, esper.component_for_entity(enemy, Position), Position(px, py), _ranged(rng=5))


def test_ability_blocked_when_player_not_in_line_of_sight():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 3, py, {**runner.enemy_config(), 'ability': _ranged()})
    fov = esper.component_for_entity(enemy, FieldOfView)
    fov.visible_tiles = set()  # player not visible
    fov.dirty = False

    assert not _can_use_ability(enemy, esper.component_for_entity(enemy, Position), Position(px, py), _ranged())


# --- AISystem integration: a ready, in-range, visible caster fires -------------


def test_ranged_ability_damages_and_slows_player_from_a_distance():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    # in range 5, not adjacent
    enemy = runner.spawn_enemy(px + 3, py, {**runner.enemy_config(), 'ability': _ranged(power=7)})
    _see_player(enemy, Point(px, py))
    start_hp = esper.component_for_entity(runner.player, Stats).hp

    runner.tick(1)

    assert esper.component_for_entity(runner.player, Stats).hp == start_hp - 7
    assert StatusType.SLOW in esper.component_for_entity(runner.player, StatusEffects).active


def test_ability_does_not_fire_while_on_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 3, py, {**runner.enemy_config(), 'ability': _ranged()})
    _see_player(enemy, Point(px, py))
    esper.component_for_entity(enemy, Actor).cooldown = 5
    start_hp = esper.component_for_entity(runner.player, Stats).hp

    runner.tick(1)

    assert esper.component_for_entity(runner.player, Stats).hp == start_hp  # cooldown gated the action
