import esper

from src.components import (
    CastVisual,
    Effect,
    EffectType,
    MessageLog,
    Point,
    ScreenFlash,
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
    get_singleton,
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
    apply_effect(runner.player, Effect(EffectType.DAMAGE, power=3), get_singleton(MessageLog))
    assert _flash() is not None and _flash().color == UI_RED


def test_apply_effect_poison_flashes_green_for_player():
    runner = HeadlessRunner(use_random_map=False)
    apply_effect(runner.player, Effect(EffectType.POISON, duration=60, power=2), get_singleton(MessageLog))
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

    EffectOverlaySystem(runner.layout).process()  # draws this frame, then ticks to 0

    assert not esper.get_component(ScreenFlash)


def test_effect_overlay_ages_out_cast_visual():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(CastVisual(center=Point(px, py), radius=0, color=UI_ORANGE, ticks=1, max_ticks=1))

    EffectOverlaySystem(runner.layout).process()

    assert not esper.get_component(CastVisual)
