import esper
import tcod.event

from src.components import Enemy, Experience, Modal, PlayerTag, Position, RunStats, Stats
from src.constants import MAX_FLOORS
from src.ecs_helpers import get_display_name, get_singleton
from src.map_objects import Map, Tile
from src.states import DisplayMode
from src.systems import cast_spell, grant_xp
from tests.headless_runner import HeadlessRunner


def _player_experience(runner) -> Experience:
    return esper.component_for_entity(runner.player, Experience)


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


def test_player_death_shows_the_game_over_screen_and_enter_returns_to_title():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Stats).hp = 0

    runner.tick(1)  # DeathSystem sees hp <= 0 and ends the run
    assert runner.display_mode == DisplayMode.GAME_OVER
    assert not esper.get_component(Modal)

    runner.simulate_key(tcod.event.KeySym.LEFT)  # a stray key stays on the summary
    assert runner.display_mode == DisplayMode.GAME_OVER

    runner.simulate_key(tcod.event.KeySym.RETURN)  # Confirm carries out the return to the title menu
    assert runner.display_mode == DisplayMode.MENU
    assert not esper.get_components(PlayerTag)


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

    runner.simulate_key(tcod.event.KeySym.UP)  # step onto the final exit -> victory

    assert runner.display_mode == DisplayMode.GAME_OVER
    assert get_singleton(RunStats).won is True
    assert not esper.get_component(Modal)  # no descend modal on the final floor


# --- XP & leveling ----------------------------------------------------------


def test_slaying_an_enemy_grants_its_xp_reward():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)
    reward = esper.component_for_entity(enemy, Enemy).xp_reward
    assert reward > 0  # the fixture enemy must actually be worth something

    esper.component_for_entity(enemy, Stats).hp = 0
    runner.tick(1)  # DeathSystem credits the kill

    exp = _player_experience(runner)
    assert exp.xp == reward
    assert exp.level == 1  # one weak kill isn't enough to level


def test_reaching_the_threshold_levels_up_and_raises_max_hp():
    runner = HeadlessRunner(use_random_map=False)
    exp = _player_experience(runner)
    stats = esper.component_for_entity(runner.player, Stats)
    base_max_hp = stats.max_hp

    grant_xp(exp.next_level_xp)

    assert exp.level == 2
    assert exp.xp == 0  # the threshold is spent on the level
    assert stats.max_hp == base_max_hp + Experience.HP_PER_LEVEL


def test_leveling_up_heals_to_full():
    runner = HeadlessRunner(use_random_map=False)
    exp = _player_experience(runner)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp = 1

    grant_xp(exp.next_level_xp)

    assert stats.hp == stats.max_hp


def test_excess_xp_carries_into_the_new_level():
    runner = HeadlessRunner(use_random_map=False)
    exp = _player_experience(runner)
    overflow = 7

    grant_xp(exp.next_level_xp + overflow)

    assert exp.level == 2
    assert exp.xp == overflow


def test_level_up_threshold_grows_with_level():
    runner = HeadlessRunner(use_random_map=False)
    exp = _player_experience(runner)

    grant_xp(exp.next_level_xp)  # -> level 2; the next level now costs more
    assert exp.level == 2

    grant_xp(Experience.LEVEL_XP)  # a level-1-sized chunk no longer suffices
    assert exp.level == 2
    assert exp.xp == Experience.LEVEL_XP

    grant_xp(Experience.LEVEL_XP)  # topping it up to the larger threshold levels again
    assert exp.level == 3


def test_casting_does_not_grant_xp():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_wand', 3)
    px, py = runner.player_pos

    cast_spell('test_wand', px + 2, py)

    assert _player_experience(runner).xp == 0
