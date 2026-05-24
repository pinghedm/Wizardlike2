import esper
import pytest
import tcod.event

from src.components import Actor
from tests.headless_runner import HeadlessRunner


@pytest.mark.parametrize(
    'key, dx, dy',
    [
        (tcod.event.KeySym.UP, 0, -1),
        (tcod.event.KeySym.DOWN, 0, 1),
        (tcod.event.KeySym.LEFT, -1, 0),
        (tcod.event.KeySym.RIGHT, 1, 0),
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
