import esper
import tcod.event

from src.components import Enemy, Stats
from tests.headless_runner import HeadlessRunner


def test_bump_into_enemy_deals_damage_and_logs():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px, py - 1)

    runner.simulate_key(tcod.event.KeySym.UP)

    # bump_damage = damage // 2 = 5
    assert esper.component_for_entity(runner.player, Stats).hp == 95
    assert any('bump' in m.lower() for m in runner.get_log_messages())
    # Non-blocking enemy: player walks onto the tile, enemy survives the bump
    assert runner.player_pos == (px, py - 1)
    assert esper.component_for_entity(enemy, Stats).hp == 30


def test_blocking_enemy_prevents_movement():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px, py - 1)
    esper.component_for_entity(enemy, Enemy).blocks_movement = True

    runner.simulate_key(tcod.event.KeySym.UP)

    assert runner.player_pos == (px, py)
    assert esper.component_for_entity(runner.player, Stats).hp < 100


def test_adjacent_enemy_attacks_player():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    runner.spawn_enemy(px + 1, py, {**runner.enemy_config(), 'speed': 0})

    hp_before = esper.component_for_entity(runner.player, Stats).hp
    runner.tick(1)

    assert esper.component_for_entity(runner.player, Stats).hp < hp_before
    assert any('hits you' in m.lower() for m in runner.get_log_messages())


def test_guard_attacks_adjacent_player():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    runner.spawn_enemy(px + 1, py, runner.enemy_config('test_guardian'))

    hp_before = esper.component_for_entity(runner.player, Stats).hp
    runner.tick(1)

    assert esper.component_for_entity(runner.player, Stats).hp < hp_before
    assert any('hits you' in m.lower() for m in runner.get_log_messages())
