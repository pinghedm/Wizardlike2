from dataclasses import replace

import esper
import pygame
import pytest

from src.components import Actor, Effect, EffectType, MessageLog, Point, Position, StatusEffects, StatusType
from src.map_objects import Map
from src.states import DisplayMode
from src.systems.movement import move_entity
from tests.headless_runner import HeadlessRunner


@pytest.mark.parametrize(
    'key, dx, dy',
    [
        (pygame.K_UP, 0, -1),
        (pygame.K_DOWN, 0, 1),
        (pygame.K_LEFT, -1, 0),
        (pygame.K_RIGHT, 1, 0),
    ],
)
def test_player_movement(key, dx, dy):
    runner = HeadlessRunner(use_random_map=False)
    initial_pos = runner.player_pos

    # Simulate pressing the key
    runner.simulate_key(key)

    # Verify position changed correctly
    new_pos = runner.player_pos
    assert new_pos.x == initial_pos.x + dx
    assert new_pos.y == initial_pos.y + dy

    # Verify cooldown was applied
    actor = esper.component_for_entity(runner.player, Actor)
    assert actor.cooldown > 0


@pytest.mark.parametrize(
    'key, delta',
    [(pygame.K_PAGEUP, 1), (pygame.K_PAGEDOWN, -1)],
)
def test_paging_scrolls_the_message_log(key, delta):
    runner = HeadlessRunner(use_random_map=False)
    log = esper.get_component(MessageLog)[0][1]
    before = log.scroll_index

    runner.simulate_key(key)

    assert log.scroll_index == before + delta


def test_walking_into_a_wall_does_not_move_the_player():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    game_map = esper.get_component(Map)[0][1]
    game_map.set_tile(px, py - 1, replace(game_map.tiles[px][py - 1], walkable=False))  # wall to the north

    runner.simulate_key(pygame.K_UP)

    assert runner.player_pos == Point(px, py)


def test_enemy_cannot_step_onto_an_exit_tile():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(5, 5)
    game_map = esper.get_component(Map)[0][1]
    game_map.set_tile(5, 4, replace(game_map.tiles[5][4], is_exit=True))  # exit directly north

    move_entity(enemy, 0, -1)

    assert esper.component_for_entity(enemy, Position).point == Point(5, 5)  # enemies can't take the exit


def test_movement_is_swallowed_while_slowed_and_on_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.SLOW] = Effect(type=EffectType.SLOW)
    esper.component_for_entity(runner.player, Actor).cooldown = 5  # SLOW gates until this elapses
    before = runner.player_pos

    runner.simulate_key(pygame.K_UP)

    assert runner.player_pos == before
    assert runner.display_mode == DisplayMode.EXPLORING


def test_movement_is_swallowed_while_stunned():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.STUN] = Effect(type=EffectType.STUN)
    before = runner.player_pos

    runner.simulate_key(pygame.K_UP)

    assert runner.player_pos == before  # a snare trap's stun roots the player in place
