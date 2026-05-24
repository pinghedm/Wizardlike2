import esper
import tcod
import tcod.event

from src.components import Modal, Position
from src.map_objects import Map, Tile
from src.systems import RenderSystem
from tests.headless_runner import HeadlessRunner


def test_stepping_on_exit_descends_to_next_floor():
    runner = HeadlessRunner(use_random_map=False)
    # transition_to_next_floor pulls the asset_loader off a RenderSystem; register a headless one.
    esper.add_processor(RenderSystem(tcod.console.Console(80, 50), runner.asset_loader))

    px, py = runner.player_pos
    game_map = esper.get_component(Map)[0][1]
    # Turn the tile above the player into an exit (new Tile, so the shared floor tile is untouched).
    floor = game_map.tiles[px][py - 1]
    game_map.tiles[px][py - 1] = Tile(
        walkable=True, transparent=True, sprite_id=floor.sprite_id, fg=floor.fg, bg=floor.bg, is_exit=True
    )
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
