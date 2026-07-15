import esper

from src.components import (
    Boss,
    BossAbility,
    Configuration,
    Effect,
    EffectType,
    EnemyAbility,
    FieldOfView,
    Guardian,
    MessageLog,
    Point,
    Position,
    Stats,
)
from src.constants import MAX_FLOORS
from src.ecs_helpers import exit_is_sealed, get_singleton
from src.map_objects import Map
from src.procgen import RectangularRoom, _spawn_boss
from src.systems.ai import _boss_phase_level, _select_boss_ability, _use_boss_ability
from tests.headless_runner import HeadlessRunner


def _boss(*thresholds: float) -> Boss:
    """A boss with one damaging ability per HP-fraction threshold, cooldown 2 each."""
    return Boss(
        abilities=[
            BossAbility(
                ability=EnemyAbility(range=6, effects=[Effect(type=EffectType.DAMAGE, power=5)]),
                hp_threshold=t,
                cooldown=2,
                name=f'ability@{t}',
            )
            for t in thresholds
        ]
    )


def _see_player(enemy: int, player_pos: Point):
    """Force the enemy's FOV to include the player so ability tests don't depend on FOV timing."""
    fov = esper.component_for_entity(enemy, FieldOfView)
    fov.visible_tiles = {player_pos}
    fov.dirty = False


# --- ability selection: phase gate, cooldown, range (pure logic) ---------------


def test_full_hp_boss_uses_only_the_always_available_ability():
    boss = _boss(1.0, 0.5, 0.25)
    assert _select_boss_ability(boss, hp_frac=1.0, in_range=[True, True, True]) == 0


def test_dropping_below_a_threshold_unlocks_that_phase_ability():
    boss = _boss(1.0, 0.5, 0.25)
    # Below 0.5 (but above 0.25) both phase-0 and phase-1 are eligible; the later phase wins.
    assert _select_boss_ability(boss, hp_frac=0.4, in_range=[True, True, True]) == 1
    # Below the deepest threshold the final phase takes over.
    assert _select_boss_ability(boss, hp_frac=0.2, in_range=[True, True, True]) == 2


def test_selection_skips_an_ability_on_cooldown():
    boss = _boss(1.0, 0.5)
    boss.timers[1] = 2  # the unlocked phase-1 ability is cooling down
    assert _select_boss_ability(boss, hp_frac=0.4, in_range=[True, True]) == 0


def test_selection_skips_an_out_of_range_ability():
    boss = _boss(1.0, 0.5)
    assert _select_boss_ability(boss, hp_frac=0.4, in_range=[False, True]) == 1


def test_no_ready_ability_returns_none():
    boss = _boss(1.0, 0.5)
    assert _select_boss_ability(boss, hp_frac=1.0, in_range=[False, False]) is None


def test_phase_level_counts_unlocked_sub_phase_abilities():
    boss = _boss(1.0, 0.66, 0.33)  # only the two thresholds < 1.0 count as phases
    assert _boss_phase_level(boss, hp_frac=1.0) == 0
    assert _boss_phase_level(boss, hp_frac=0.6) == 1
    assert _boss_phase_level(boss, hp_frac=0.3) == 2


# --- firing sets the cooldown so the same ability can't fire back-to-back -------


def test_firing_an_ability_puts_it_on_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 3, py, runner.enemy_config('test_boss'))
    _see_player(enemy, Point(px, py))
    boss = esper.component_for_entity(enemy, Boss)
    log = get_singleton(MessageLog)
    boss_pos, player_pos = Position(px + 3, py), Position(px, py)
    start_hp = esper.component_for_entity(runner.player, Stats).hp

    assert _use_boss_ability(enemy, boss, boss_pos, player_pos, runner.player, log)
    assert esper.component_for_entity(runner.player, Stats).hp < start_hp  # Jab landed
    assert max(boss.timers) > 0  # a cooldown was set

    # Next turn: the only unlocked ability (full HP) is still cooling down, so nothing fires.
    hp_after_first = esper.component_for_entity(runner.player, Stats).hp
    assert not _use_boss_ability(enemy, boss, boss_pos, player_pos, runner.player, log)
    assert esper.component_for_entity(runner.player, Stats).hp == hp_after_first


# --- the boss seals the exit, and dying unseals it ------------------------------


def test_boss_carries_the_guardian_seal_and_dying_lifts_it():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 3, py, runner.enemy_config('test_boss'))

    assert esper.has_component(enemy, Boss)
    assert esper.has_component(enemy, Guardian)  # boss implies the exit-seal
    assert exit_is_sealed()

    esper.component_for_entity(enemy, Stats).hp = 0
    assert not exit_is_sealed()  # slaying the boss opens the stairs


def test_final_floor_spawns_a_boss_in_the_exit_room():
    HeadlessRunner(use_random_map=False)  # builds a clean, unsealed floor
    assert not exit_is_sealed()
    game_map = get_singleton(Map)
    exit_room = RectangularRoom(x=4, y=4, width=6, height=6, dungeon=game_map)

    _spawn_boss(game_map, exit_room, [exit_room], MAX_FLOORS)

    bosses = esper.get_components(Boss, Guardian)
    assert len(bosses) == 1
    assert exit_is_sealed()


# --- the data path: an abilities block parses into BossAbility objects ----------


def test_boss_abilities_load_as_bossability_objects():
    HeadlessRunner(use_random_map=False)  # builds Configuration from fixtures
    config = esper.get_component(Configuration)[0][1].enemies['test_boss']

    abilities = config['abilities']
    assert [type(a) for a in abilities] == [BossAbility, BossAbility]
    assert abilities[0].name == 'Jab'
    assert abilities[0].hp_threshold == 1.0
    assert abilities[1].ability.effects[0].type == EffectType.DAMAGE
