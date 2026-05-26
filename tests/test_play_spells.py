import esper
import tcod.event

from src.components import SpellInventory, SpellType, Stats, StatusEffects, StatusType
from src.states import DisplayMode
from src.systems import cast_spell
from tests.headless_runner import HeadlessRunner


def test_full_cast_cycle_applies_fixture_effects():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 1)  # range 8, radius 0, damage 12 + slow 40
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py, hp=30)

    runner.simulate_key(tcod.event.KeySym.s)  # EXPLORING -> CASTING
    assert runner.display_mode == DisplayMode.CASTING

    runner.simulate_key(tcod.event.KeySym.RETURN)  # select test_bolt -> TARGETING
    assert runner.display_mode == DisplayMode.TARGETING

    runner.simulate_key(tcod.event.KeySym.RIGHT)  # walk reticle onto the enemy
    runner.simulate_key(tcod.event.KeySym.RIGHT)
    runner.simulate_key(tcod.event.KeySym.RETURN)  # cast

    assert runner.display_mode == DisplayMode.EXPLORING
    assert esper.component_for_entity(runner.player, SpellInventory).spells[SpellType('test_bolt')] == 0
    assert esper.component_for_entity(enemy, Stats).hp == 30 - 12
    assert esper.component_for_entity(enemy, StatusEffects).active[StatusType.SLOW].duration == 40


def test_spell_radius_hits_only_targets_within_radius():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_blast', 1)  # radius 1, damage 20
    px, py = runner.player_pos
    tx, ty = px + 3, py

    center = runner.spawn_enemy(tx, ty, hp=30)  # on target
    orthogonal = runner.spawn_enemy(tx, ty + 1, hp=30)  # dist^2 = 1 -> inside radius 1
    diagonal = runner.spawn_enemy(tx + 1, ty + 1, hp=30)  # dist^2 = 2 -> outside
    far = runner.spawn_enemy(tx, ty + 2, hp=30)  # dist^2 = 4 -> outside

    cast_spell(spell_id='test_blast', target_x=tx, target_y=ty)

    assert esper.component_for_entity(center, Stats).hp == 30 - 20
    assert esper.component_for_entity(orthogonal, Stats).hp == 30 - 20
    assert esper.component_for_entity(diagonal, Stats).hp == 30
    assert esper.component_for_entity(far, Stats).hp == 30
