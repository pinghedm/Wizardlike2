import esper

from src.components import Actor, Effect, EffectType, Experience, SpellMastery, SpellType, StatusEffects, StatusType
from src.constants import LEVEL_CAST_SPEEDUP, MASTERY_CAST_SPEEDUP, MIN_CAST_COST, PLAYER_CAST_COST
from src.systems.crafting import cast_spell, get_cast_cooldown
from src.systems.movement import can_cast
from src.systems.progression import spell_rank
from src.ui_systems.overlays import _cooldown_bar_fill
from tests.headless_runner import HeadlessRunner

# test_blast is unmasterable (no mastery block); test_wand has mastery (casts_per_rank 2).
UNMASTERED = SpellType('test_blast')
MASTERABLE = SpellType('test_wand')


def _slow(runner: HeadlessRunner):
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.SLOW] = Effect(type=EffectType.SLOW)


# --- get_cast_cooldown: base cost, shrinking with level and mastery -------------


def test_a_novice_pays_the_full_base_cast_cost():
    runner = HeadlessRunner(use_random_map=False)
    assert get_cast_cooldown(runner.player, UNMASTERED) == PLAYER_CAST_COST


def test_higher_level_shortens_the_cast_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Experience).level = 5

    assert get_cast_cooldown(runner.player, UNMASTERED) == PLAYER_CAST_COST - LEVEL_CAST_SPEEDUP * 4


def test_mastery_rank_shortens_the_cast_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, SpellMastery).casts[MASTERABLE] = 2  # reaches rank 1
    assert spell_rank(MASTERABLE) == 1

    assert get_cast_cooldown(runner.player, MASTERABLE) == PLAYER_CAST_COST - MASTERY_CAST_SPEEDUP * 1


def test_cast_cooldown_is_floored_so_it_never_hits_zero():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Experience).level = 999  # reduction dwarfs the base

    assert get_cast_cooldown(runner.player, UNMASTERED) == MIN_CAST_COST


def test_slow_doubles_the_cast_cooldown():
    runner = HeadlessRunner(use_random_map=False)
    _slow(runner)

    assert get_cast_cooldown(runner.player, UNMASTERED) == PLAYER_CAST_COST * 2


# --- can_cast: the gate the input handlers apply -------------------------------


def test_can_cast_when_the_cooldown_has_elapsed():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Actor).cast_cooldown = 0
    assert can_cast(runner.player)


def test_cannot_cast_while_the_cooldown_is_running():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Actor).cast_cooldown = 5
    assert not can_cast(runner.player)


def test_cannot_cast_while_stunned():
    runner = HeadlessRunner(use_random_map=False)
    esper.component_for_entity(runner.player, Actor).cast_cooldown = 0
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.STUN] = Effect(type=EffectType.STUN)
    assert not can_cast(runner.player)


# --- end to end: a cast throttles the next until the cooldown decays ------------


def test_casting_blocks_the_next_cast_until_the_cooldown_decays():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_heal', 3)
    px, py = runner.player_pos
    cost = get_cast_cooldown(runner.player, SpellType('test_heal'))

    cast_spell(spell_id='test_heal', target_x=px, target_y=py)

    actor = esper.component_for_entity(runner.player, Actor)
    assert actor.cast_cooldown == cost
    assert actor.cast_cooldown_max == cost  # recorded for the recharge UI
    assert not can_cast(runner.player)

    runner.tick(cost - 1)
    assert not can_cast(runner.player)  # one tick short
    runner.tick(1)
    assert can_cast(runner.player)  # cooldown fully elapsed


# --- the over-the-wizard recharge bar fills left-to-right as it nears ready -----


def test_cooldown_bar_fills_as_the_recharge_completes():
    assert _cooldown_bar_fill(remaining=30, total=30, width=4) == 1  # just cast: a sliver
    assert _cooldown_bar_fill(remaining=15, total=30, width=4) == 2  # half recharged
    assert _cooldown_bar_fill(remaining=2, total=30, width=4) == 4  # almost ready: nearly full


def test_cooldown_bar_is_full_when_ready_or_untimed():
    assert _cooldown_bar_fill(remaining=0, total=30, width=4) == 4  # ready (caller then hides it)
    assert _cooldown_bar_fill(remaining=5, total=0, width=4) == 4  # guards a zero total
