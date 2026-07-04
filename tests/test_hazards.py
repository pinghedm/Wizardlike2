import esper

from src.components import Effect, EffectType, FieldOfView, Point, Position, Stats, StatusEffects, StatusType
from src.constants import TRAP_DETECT_RADIUS
from src.map_objects import Map, Tile
from src.systems import FOVSystem, HazardSystem, apply_effect
from src.systems.movement import apply_knockback
from tests.headless_runner import HeadlessRunner


def _effect_tile(effects: list[Effect], hidden: bool = False) -> Tile:
    """A walkable tile carrying an on-enter payload, built in-test so hazard behavior is
    exercised independently of shipped tiles.yaml values."""
    return Tile(
        walkable=True,
        transparent=True,
        sprite_id='test_floor',
        fg=(255, 255, 255),
        bg=(0, 0, 0),
        effects=tuple(effects),
        hidden=hidden,
    )


def _game_map() -> Map:
    return esper.get_component(Map)[0][1]


# --- HazardSystem: on-enter effects --------------------------------------------


def test_hazard_applies_its_effect_to_an_actor_on_the_cell():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    _game_map().set_tile(px, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=10)]))

    HazardSystem().process()

    assert esper.component_for_entity(runner.player, Stats).hp == 100 - 10


def test_hazard_fires_once_per_entry_not_every_tick_standing():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    _game_map().set_tile(px, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=10)]))

    hazards = HazardSystem()  # one instance keeps its last-cell cache across ticks
    hazards.process()  # enter
    hazards.process()  # still standing
    hazards.process()

    assert esper.component_for_entity(runner.player, Stats).hp == 100 - 10  # a single hit


def test_water_hazard_applies_the_wet_status():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    _game_map().set_tile(px, py, _effect_tile([Effect(type=EffectType.WET, duration=90)]))

    HazardSystem().process()

    assert StatusType.WET in esper.component_for_entity(runner.player, StatusEffects).active


def test_stepping_onto_a_hidden_trap_springs_it_once_then_it_is_inert():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    game_map = _game_map()
    game_map.set_tile(px, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=15)], hidden=True))

    hazards = HazardSystem()
    hazards.process()  # the trap springs

    assert esper.component_for_entity(runner.player, Stats).hp == 100 - 15
    assert any('spring' in msg.lower() for msg in runner.get_log_messages())
    spent = game_map.tiles[px][py]
    assert not spent.effects and not spent.hidden  # spent: now visible and harmless

    hazards.process()  # standing on the spent trap does nothing more
    assert esper.component_for_entity(runner.player, Stats).hp == 100 - 15


def test_a_hazard_is_not_consumed_when_triggered():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    game_map = _game_map()
    game_map.set_tile(px, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=10)]))  # visible hazard

    HazardSystem().process()

    assert game_map.tiles[px][py].effects  # stays armed, unlike a sprung trap


def test_knockback_into_a_chasm_damages_the_shoved_enemy():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    game_map = _game_map()
    enemy = runner.spawn_enemy(px + 1, py)
    game_map.set_tile(px + 2, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=25)]))

    apply_knockback(enemy, origin=Point(px, py), distance=1)
    assert esper.component_for_entity(enemy, Position).point == Point(px + 2, py)  # shoved onto the chasm

    hp_before = esper.component_for_entity(enemy, Stats).hp
    HazardSystem().process()

    assert esper.component_for_entity(enemy, Stats).hp == hp_before - 25


# --- FOVSystem: trap detection-reveal ------------------------------------------


def test_hidden_trap_reveals_when_seen_within_detection_radius():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    game_map = _game_map()
    trap_x = px + TRAP_DETECT_RADIUS  # in line of sight and within detection range
    game_map.set_tile(trap_x, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=15)], hidden=True))

    esper.component_for_entity(runner.player, FieldOfView).dirty = True
    FOVSystem().process()

    assert game_map.revealed[trap_x, py]


def test_hidden_trap_stays_concealed_beyond_detection_radius():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    game_map = _game_map()
    trap_x = px + TRAP_DETECT_RADIUS + 2  # visible (FOV radius 8) but out of detection range
    game_map.set_tile(trap_x, py, _effect_tile([Effect(type=EffectType.DAMAGE, power=15)], hidden=True))

    esper.component_for_entity(runner.player, FieldOfView).dirty = True
    FOVSystem().process()

    assert not game_map.revealed[trap_x, py]


# --- Reveal: lighting up every hidden trap on the floor ------------------------


def test_reveal_all_traps_marks_every_hidden_trap():
    runner = HeadlessRunner()
    game_map = _game_map()
    px, py = runner.player_pos
    far_traps = [(px + 5, py), (px, py + 6)]
    for x, y in far_traps:
        game_map.set_tile(x, y, _effect_tile([Effect(type=EffectType.DAMAGE, power=5)], hidden=True))

    count = game_map.reveal_all_traps()

    assert count == 2
    assert all(game_map.revealed[x, y] for x, y in far_traps)


def test_reveal_effect_lights_up_hidden_traps():
    runner = HeadlessRunner()
    game_map = _game_map()
    px, py = runner.player_pos
    trap = (px + 5, py)  # well outside adjacent detection
    game_map.set_tile(trap[0], trap[1], _effect_tile([Effect(type=EffectType.DAMAGE, power=5)], hidden=True))

    apply_effect(runner.player, Effect(type=EffectType.REVEAL))

    assert game_map.revealed[trap[0], trap[1]]
