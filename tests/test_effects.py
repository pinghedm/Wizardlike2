import esper

from src.components import (
    CastVisual,
    DamageModifier,
    Effect,
    EffectType,
    FloatingNumber,
    MessageLog,
    Particle,
    Point,
    Position,
    Projectile,
    ScreenFlash,
    Stats,
    StatusEffects,
    StatusType,
)
from src.constants import STATUS_PULSE_INTERVAL, UI_GREEN, UI_GREEN_BRIGHT, UI_ORANGE, UI_RED
from src.ecs_helpers import get_singleton
from src.systems import (
    EFFECT_COLORS,
    PROJECTILE_GLYPHS,
    StatusSystem,
    apply_effect,
    cast_spell,
    deal_damage,
    get_spell_config,
    spawn_particle_burst,
    trigger_screen_flash,
)
from src.systems.crafting import _apply_reaction_multiplier
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


def test_cast_spell_launches_projectile_styled_by_first_effect_not_an_instant_burst():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 1)
    px, py = runner.player_pos
    tx, ty = px + 2, py

    cast_spell(spell_id='test_bolt', target_x=tx, target_y=ty)

    # The impact burst now waits for the projectile to land, so nothing flashes yet.
    assert not esper.get_component(CastVisual)
    projectiles = esper.get_component(Projectile)
    assert len(projectiles) == 1
    proj = projectiles[0][1]
    assert proj.start == Point(px, py)
    assert proj.target == Point(tx, ty)
    # Glyph and color derive from the spell's own first effect, not hardcoded values.
    first_effect = get_spell_config('test_bolt')['effects'][0].type
    assert proj.glyph == PROJECTILE_GLYPHS[first_effect]
    assert proj.color == EFFECT_COLORS[first_effect]


def test_projectile_arrives_and_spawns_the_impact_burst():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 1)
    px, py = runner.player_pos
    tx, ty = px + 2, py
    cast_spell(spell_id='test_bolt', target_x=tx, target_y=ty)

    overlay = EffectOverlaySystem(runner.layout)
    # progress climbs SPEED/distance (0.5/2) per frame, so it lands on the 4th.
    for _ in range(4):
        overlay.process()

    assert not esper.get_component(Projectile)
    visuals = esper.get_component(CastVisual)
    assert len(visuals) == 1
    assert visuals[0][1].center == Point(tx, ty)


def test_projectile_is_frozen_while_the_game_is_paused():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_bolt', 1)
    px, py = runner.player_pos
    cast_spell(spell_id='test_bolt', target_x=px + 2, target_y=py)
    runner.game_state.time_paused = True

    overlay = EffectOverlaySystem(runner.layout)
    for _ in range(10):
        overlay.process()

    # Still in flight, no impact: a menu pauses the projectile like everything else.
    assert esper.get_component(Projectile)
    assert esper.get_component(Projectile)[0][1].progress == 0.0
    assert not esper.get_component(CastVisual)


def test_particle_does_not_age_while_the_game_is_paused():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(
        Particle(x=float(px), y=float(py), vx=0.0, vy=0.0, glyph='*', color=UI_ORANGE, ticks=1, max_ticks=1)
    )
    runner.game_state.time_paused = True

    EffectOverlaySystem(runner.layout).process()

    assert esper.get_component(Particle)


def test_particle_ages_out():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(
        Particle(x=float(px), y=float(py), vx=0.0, vy=0.0, glyph='*', color=UI_ORANGE, ticks=1, max_ticks=1)
    )

    EffectOverlaySystem(runner.layout).process()

    assert not esper.get_component(Particle)


def test_burst_spawns_the_requested_particle_count():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos

    spawn_particle_burst(center=Point(px, py), color=UI_ORANGE, count=5)

    assert len(esper.get_component(Particle)) == 5


def test_damaging_an_enemy_sprays_particles_but_a_player_hit_does_not():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos

    apply_effect(runner.player, Effect(EffectType.DAMAGE, power=3))
    assert not esper.get_component(Particle)  # player hit relies on the screen flash

    enemy = runner.spawn_enemy(px + 2, py)
    apply_effect(enemy, Effect(EffectType.DAMAGE, power=3))
    assert len(esper.get_component(Particle)) == Particle.HIT_COUNT


def _floating_numbers():
    return [number for _ent, number in esper.get_component(FloatingNumber)]


def test_a_player_hit_floats_a_red_damage_number():
    runner = HeadlessRunner(use_random_map=False)
    apply_effect(runner.player, Effect(EffectType.DAMAGE, power=3))
    numbers = _floating_numbers()
    assert len(numbers) == 1
    assert numbers[0].text == '3'
    assert numbers[0].color == UI_RED


def test_an_enemy_hit_floats_an_orange_damage_number():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)
    apply_effect(enemy, Effect(EffectType.DAMAGE, power=5))
    numbers = _floating_numbers()
    assert len(numbers) == 1
    assert numbers[0].text == '5'
    assert numbers[0].color == UI_ORANGE


def test_a_fully_shielded_hit_still_floats_a_zero():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.SHIELD] = Effect(
        EffectType.SHIELD, power=5, duration=99
    )
    apply_effect(enemy, Effect(EffectType.DAMAGE, power=4))  # wholly absorbed
    assert [number.text for number in _floating_numbers()] == ['0']


def test_a_poison_pulse_floats_its_damage_number():
    runner = HeadlessRunner(use_random_map=False)
    status = esper.component_for_entity(runner.player, StatusEffects)
    status.active[StatusType.POISON] = Effect(EffectType.POISON, duration=STATUS_PULSE_INTERVAL, power=2)

    StatusSystem().process()

    assert [number.text for number in _floating_numbers()] == ['2']


def test_a_heal_floats_a_green_plus_number_for_the_amount_restored():
    runner = HeadlessRunner(use_random_map=False)
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp = stats.max_hp - 2  # only 2 HP is missing, so a power-5 heal restores 2

    apply_effect(runner.player, Effect(EffectType.HEAL, power=5))

    numbers = _floating_numbers()
    assert len(numbers) == 1
    assert numbers[0].text == '+2'
    assert numbers[0].color == UI_GREEN_BRIGHT


def test_effect_overlay_rises_and_ages_out_a_floating_number():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(FloatingNumber(x=float(px), y=float(py), text='7', color=UI_RED, ticks=2, max_ticks=2))

    EffectOverlaySystem(runner.layout).process()  # draws, rises, ticks to 1
    risen = _floating_numbers()
    assert len(risen) == 1
    assert risen[0].y < py  # floated upward

    EffectOverlaySystem(runner.layout).process()  # ticks to 0 and is removed
    assert not esper.get_component(FloatingNumber)


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


def _make_wet(ent: int, duration: int = 40):
    esper.component_for_entity(ent, StatusEffects).active[StatusType.WET] = Effect(EffectType.WET, duration=duration)


def test_casting_a_vulnerability_spell_on_a_wet_target_scales_up_the_damage_and_consumes_wet():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_zap', 1)  # 10 damage, x2 vs wet
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)
    enemy_stats = esper.component_for_entity(enemy, Stats)
    _make_wet(enemy)

    before = enemy_stats.hp
    cast_spell(spell_id='test_zap', target_x=px + 2, target_y=py)

    assert before - enemy_stats.hp == 20  # 10 * 2.0
    assert StatusType.WET not in esper.component_for_entity(enemy, StatusEffects).active


def test_casting_a_resistance_spell_on_a_wet_target_scales_down_the_damage():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_quench', 1)  # 10 damage, x0.5 vs wet
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)
    enemy_stats = esper.component_for_entity(enemy, Stats)
    _make_wet(enemy)

    before = enemy_stats.hp
    cast_spell(spell_id='test_quench', target_x=px + 2, target_y=py)

    assert before - enemy_stats.hp == 5  # 10 * 0.5


def test_casting_on_a_dry_target_deals_base_damage_with_no_reaction():
    runner = HeadlessRunner(use_random_map=False)
    runner.give_spell('test_zap', 1)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 2, py)
    enemy_stats = esper.component_for_entity(enemy, Stats)

    before = enemy_stats.hp
    cast_spell(spell_id='test_zap', target_x=px + 2, target_y=py)

    assert before - enemy_stats.hp == 10  # unscaled


def test_reaction_multiplier_matches_a_carried_status_and_consumes_it():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    _make_wet(enemy)

    mult = _apply_reaction_multiplier(enemy, [DamageModifier(StatusType.WET, 2.0)], get_singleton(MessageLog))

    assert mult == 2.0
    assert StatusType.WET not in esper.component_for_entity(enemy, StatusEffects).active


def test_reaction_multiplier_is_one_and_consumes_nothing_when_unmatched():
    runner = HeadlessRunner(use_random_map=False)
    enemy = runner.spawn_enemy(*runner.player_pos)
    esper.component_for_entity(enemy, StatusEffects).active[StatusType.SLOW] = Effect(EffectType.SLOW, duration=40)

    mult = _apply_reaction_multiplier(enemy, [DamageModifier(StatusType.WET, 2.0)], get_singleton(MessageLog))

    assert mult == 1.0
    assert StatusType.SLOW in esper.component_for_entity(enemy, StatusEffects).active
