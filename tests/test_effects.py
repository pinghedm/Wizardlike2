import esper

from src.components import (
    CastVisual,
    Effect,
    EffectType,
    Point,
    Position,
    ScreenFlash,
    Stats,
    StatusEffects,
    StatusType,
)
from src.constants import STATUS_PULSE_INTERVAL, UI_GREEN, UI_ORANGE, UI_RED
from src.systems import (
    EFFECT_COLORS,
    StatusSystem,
    apply_effect,
    cast_spell,
    deal_damage,
    get_spell_config,
    trigger_screen_flash,
)
from src.ui_systems import EffectOverlaySystem
from tests.headless_runner import HeadlessRunner


def _flash():
    flashes = esper.get_component(ScreenFlash)
    return flashes[0][1] if flashes else None


def test_deal_damage_flashes_red_for_player():
    runner = HeadlessRunner(use_random_map=False)
    deal_damage(target_ent=runner.player, amount=1, message='ow', color=UI_RED)
    assert _flash() is not None and _flash().color == UI_RED


def test_deal_damage_does_not_flash_for_enemy():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)
    deal_damage(target_ent=enemy, amount=1, message='ow', color=UI_RED)
    assert not esper.get_component(ScreenFlash)


def test_screen_flash_replaces_previous_so_only_one_exists():
    runner = HeadlessRunner(use_random_map=False)
    trigger_screen_flash(ent=runner.player, color=UI_RED)
    trigger_screen_flash(ent=runner.player, color=UI_GREEN)
    flashes = esper.get_component(ScreenFlash)
    assert len(flashes) == 1
    assert flashes[0][1].color == UI_GREEN


def test_apply_effect_damage_flashes_red_for_player():
    runner = HeadlessRunner(use_random_map=False)
    apply_effect(runner.player, Effect(EffectType.DAMAGE, power=3))
    assert _flash() is not None and _flash().color == UI_RED


def test_apply_effect_poison_flashes_green_for_player():
    runner = HeadlessRunner(use_random_map=False)
    apply_effect(runner.player, Effect(EffectType.POISON, duration=60, power=2))
    assert _flash() is not None and _flash().color == UI_GREEN


def test_poison_pulse_flashes_green_for_player():
    runner = HeadlessRunner(use_random_map=False)
    status = esper.component_for_entity(runner.player, StatusEffects)
    # duration is a multiple of the pulse interval so a pulse fires this tick.
    status.active[StatusType.POISON] = Effect(EffectType.POISON, duration=STATUS_PULSE_INTERVAL, power=2)

    StatusSystem().process()

    assert _flash() is not None and _flash().color == UI_GREEN


def test_cast_spell_creates_burst_at_target_colored_by_first_effect():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 1)
    px, py = runner.player_pos
    tx, ty = px + 2, py

    cast_spell(spell_id='test_bolt', target_x=tx, target_y=ty)

    visuals = esper.get_component(CastVisual)
    assert len(visuals) == 1
    visual = visuals[0][1]
    assert visual.center == Point(tx, ty)
    # Color is derived from the spell's own first effect, not a hardcoded value.
    expected = EFFECT_COLORS[get_spell_config('test_bolt')['effects'][0].type]
    assert visual.color == expected


def test_effect_overlay_ages_out_screen_flash():
    runner = HeadlessRunner(use_random_map=False)
    esper.create_entity(ScreenFlash(color=UI_RED, ticks=1, max_ticks=1))

    # draws this frame, then ticks to 0
    EffectOverlaySystem(runner.layout).process()

    assert not esper.get_component(ScreenFlash)


def test_effect_overlay_ages_out_cast_visual():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(CastVisual(center=Point(px, py), radius=0, color=UI_ORANGE, ticks=1, max_ticks=1))

    EffectOverlaySystem(runner.layout).process()

    assert not esper.get_component(CastVisual)


def test_stun_makes_an_enemy_forfeit_its_turn_until_it_expires():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    # adjacent, so an unimpeded enemy would melee
    enemy = runner.spawn_enemy(px + 1, py)
    player_stats = esper.component_for_entity(runner.player, Stats)
    apply_effect(enemy, Effect(EffectType.STUN, duration=STATUS_PULSE_INTERVAL))

    hp_before = player_stats.hp
    runner.tick(1)
    assert player_stats.hp == hp_before  # stunned: the attack never lands

    del esper.component_for_entity(enemy, StatusEffects).active[StatusType.STUN]
    runner.tick(1)
    assert player_stats.hp < hp_before  # turn restored once the stun is gone


def test_shield_blunts_direct_hits_but_not_poison_pulses():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    stats = esper.component_for_entity(enemy, Stats)
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.SHIELD] = Effect(
        EffectType.SHIELD, power=5, duration=99
    )

    hp = stats.hp
    apply_effect(enemy, Effect(EffectType.DAMAGE, power=8))
    assert stats.hp == hp - 3  # 8 reduced by the shield's 5

    hp = stats.hp
    apply_effect(enemy, Effect(EffectType.DAMAGE, power=4))
    assert stats.hp == hp  # a hit at or below the shield deals nothing

    hp = stats.hp
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.POISON] = Effect(
        EffectType.POISON, power=4, duration=STATUS_PULSE_INTERVAL
    )
    StatusSystem().process()
    assert stats.hp == hp - 4  # damage-over-time bypasses the shield


def test_drain_damages_the_target_and_heals_the_caster_by_its_lifesteal():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    enemy_stats = esper.component_for_entity(enemy, Stats)
    player_stats = esper.component_for_entity(runner.player, Stats)
    player_stats.hp = 5

    e_before = enemy_stats.hp
    apply_effect(enemy, Effect(EffectType.DRAIN, power=10, lifesteal=4), caster_ent=runner.player)
    assert enemy_stats.hp == e_before - 10
    assert player_stats.hp == 9  # 5 + 4 lifesteal


def test_drain_lifesteal_is_capped_at_the_casters_max_hp():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    player_stats = esper.component_for_entity(runner.player, Stats)
    player_stats.hp = player_stats.max_hp - 1

    apply_effect(enemy, Effect(EffectType.DRAIN, power=10, lifesteal=8), caster_ent=runner.player)
    assert player_stats.hp == player_stats.max_hp


def test_drain_damage_is_mitigated_by_a_shield_on_the_target():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    enemy_stats = esper.component_for_entity(enemy, Stats)
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.SHIELD] = Effect(
        EffectType.SHIELD, power=6, duration=99
    )

    e_before = enemy_stats.hp
    apply_effect(enemy, Effect(EffectType.DRAIN, power=10, lifesteal=4), caster_ent=runner.player)
    assert enemy_stats.hp == e_before - 4  # 10 reduced by the shield's 6


def test_knockback_pushes_the_target_away_from_the_origin():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    # one tile to the +x side of the origin
    enemy = runner.spawn_enemy(px + 1, py)

    apply_effect(enemy, Effect(EffectType.KNOCKBACK, power=2), origin=Point(px, py))

    pos = esper.component_for_entity(enemy, Position)
    # shoved two further tiles directly away
    assert (pos.x, pos.y) == (px + 3, py)


def test_knockback_halts_at_an_occupied_tile():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)
    runner.spawn_enemy(px + 2, py)  # blocks the first step out

    apply_effect(enemy, Effect(EffectType.KNOCKBACK, power=3), origin=Point(px, py))

    pos = esper.component_for_entity(enemy, Position)
    assert (pos.x, pos.y) == (px + 1, py)  # couldn't advance past the blocker


def test_knockback_leaves_a_target_on_the_origin_in_place():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    # sitting exactly on the origin: no direction to fly
    enemy = runner.spawn_enemy(px, py)

    apply_effect(enemy, Effect(EffectType.KNOCKBACK, power=2), origin=Point(px, py))

    pos = esper.component_for_entity(enemy, Position)
    assert (pos.x, pos.y) == (px, py)


def test_casting_knockback_shoves_the_target_away_from_the_caster():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_shove', 1)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 1, py)

    cast_spell(spell_id='test_shove', target_x=px + 1, target_y=py)  # reticle lands on the enemy

    # Pushed away from the caster, not stuck on its tile (the impact center is the victim).
    pos = esper.component_for_entity(enemy, Position)
    assert (pos.x, pos.y) == (px + 3, py)


def test_shield_mitigates_damage_dealt_to_the_player():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    esper.component_for_entity(runner.player, StatusEffects).active[StatusType.SHIELD] = Effect(
        EffectType.SHIELD, power=5, duration=99
    )

    before = stats.hp
    deal_damage(runner.player, 10, 'hit', UI_RED)
    assert before - stats.hp == 5
