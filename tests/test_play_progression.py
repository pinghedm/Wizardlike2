import esper
import pytest
import tcod.event

from src.components import Modal, Position, Stats
from src.constants import MAX_FLOORS
from src.map_objects import Map, Tile
from src.systems import get_display_name
from tests.headless_runner import HeadlessRunner


def _make_exit_above_player(runner):
    """Turn the tile directly above the player into an exit tile."""
    px, py = runner.player_pos
    game_map = esper.get_component(Map)[0][1]
    floor = game_map.tiles[px][py - 1]
    game_map.set_tile(
        px,
        py - 1,
        Tile(walkable=True, transparent=True, sprite_id=floor.sprite_id, fg=floor.fg, bg=floor.bg, is_exit=True),
    )


def test_stepping_on_exit_descends_to_next_floor():
    runner = HeadlessRunner(use_random_map=False)

    px, py = runner.player_pos
    _make_exit_above_player(runner)
    enemy = runner.spawn_enemy(px + 3, py)

    runner.simulate_key(tcod.event.KeySym.UP)  # step onto the exit -> spawns the descend modal
    assert esper.get_component(Modal)
    assert runner.game_state.floor == 1

    runner.simulate_key(tcod.event.KeySym.RETURN)  # closing the modal triggers the descent

    assert runner.game_state.floor == 2
    assert not esper.entity_exists(enemy)  # previous floor's enemies are cleared
    new_map = esper.get_component(Map)[0][1]
    player_pos = esper.component_for_entity(runner.player, Position)
    assert new_map.is_walkable(player_pos.x, player_pos.y)


def test_descend_modal_ignores_non_enter_keys():
    runner = HeadlessRunner(use_random_map=False)
    _make_exit_above_player(runner)

    runner.simulate_key(tcod.event.KeySym.UP)  # step onto the exit -> spawns the descend modal
    assert esper.get_component(Modal)

    runner.simulate_key(tcod.event.KeySym.LEFT)  # an arrow must not confirm the descent
    assert esper.get_component(Modal)
    assert runner.game_state.floor == 1

    runner.simulate_key(tcod.event.KeySym.RETURN)
    assert runner.game_state.floor == 2


def test_player_death_spawns_a_modal_that_exits_only_on_enter():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Stats).hp = 0

    runner.tick(1)  # DeathSystem sees hp <= 0 and raises the death modal
    assert esper.get_component(Modal)

    runner.simulate_key(tcod.event.KeySym.LEFT)  # a stray key must not quit the game
    assert esper.get_component(Modal)

    with pytest.raises(SystemExit):  # Enter fires on_close=sys.exit
        runner.simulate_key(tcod.event.KeySym.RETURN)


def test_enemy_death_removes_the_entity_and_logs_a_death_message():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)  # adjacent free tile, away from the player
    name = get_display_name(enemy)
    esper.component_for_entity(enemy, Stats).hp = 0

    runner.tick(1)  # DeathSystem sees hp <= 0 on a non-player entity

    assert not esper.entity_exists(enemy)
    # The message must name the dead enemy, so a player death can't satisfy it.
    assert any(f'The {name} dies!' in line for line in runner.get_log_messages())


def test_reaching_final_floor_exit_wins_instead_of_descending():
    runner = HeadlessRunner(use_random_map=False)
    runner.game_state.floor = MAX_FLOORS
    _make_exit_above_player(runner)

    # On the final floor the exit ends the run rather than spawning a descend modal.
    with pytest.raises(SystemExit):
        runner.simulate_key(tcod.event.KeySym.UP)
    assert not esper.get_component(Modal)
