import random
from dataclasses import dataclass, replace

import esper

from src.components import (
    Effect,
    EffectType,
    ItemType,
    Loot,
    MessageLog,
    Point,
    RunStats,
    Stats,
    StatusEffects,
    StatusType,
)
from src.constants import (
    RGB,
    UI_BLUE,
    UI_CRIMSON,
    UI_GRAY_LIGHT,
    UI_GREEN,
    UI_GREEN_BRIGHT,
    UI_GREEN_MID,
    UI_ORANGE,
    UI_PERIWINKLE,
    UI_RED,
    UI_SKY,
    UI_YELLOW,
)
from src.ecs_helpers import actor_name, get_display_name, get_singleton, get_status, is_player, try_get_singleton
from src.systems.movement import apply_knockback
from src.systems.visuals import EFFECT_COLORS, spray_hit_particles, trigger_screen_flash


@dataclass(frozen=True)
class StatusApplication:
    """How a lingering effect presents when applied: the status it grants, its
    `{name}`-templated log message, and that message's color. `damage_over_time` marks
    harmful pulsing statuses (poison, and future burns) — they flash the screen on apply
    in their EFFECT_COLORS hue so any new DoT slots in without a special case."""

    status: StatusType
    message: str
    color: RGB
    damage_over_time: bool = False


# Lingering effects all apply the same way — stash a copy on the target and log a line —
# so they're data, not branches. Instant effects (damage/heal/drain/knockback) differ and
# stay as explicit cases in apply_effect.
STATUS_APPLY: dict[EffectType, StatusApplication] = {
    EffectType.SLOW: StatusApplication(status=StatusType.SLOW, message='{name} is slowed!', color=UI_PERIWINKLE),
    EffectType.HASTE: StatusApplication(status=StatusType.HASTE, message='{name} speeds up!', color=UI_YELLOW),
    EffectType.STUN: StatusApplication(status=StatusType.STUN, message='{name} is stunned!', color=UI_YELLOW),
    EffectType.SHIELD: StatusApplication(status=StatusType.SHIELD, message='{name} is shielded!', color=UI_SKY),
    EffectType.POISON: StatusApplication(
        status=StatusType.POISON, message='{name} is poisoned!', color=UI_GREEN_MID, damage_over_time=True
    ),
    EffectType.REGEN: StatusApplication(
        status=StatusType.REGEN, message='{name} begins to regenerate!', color=UI_GREEN_BRIGHT
    ),
    EffectType.WET: StatusApplication(status=StatusType.WET, message='{name} is drenched!', color=UI_BLUE),
}


def record_damage_dealt(target_ent: int, amount: int):
    """Tally damage the player caused for the run summary. Enemies only ever damage
    the player, so counting damage to any non-player entity equals player-dealt damage.
    """
    if is_player(target_ent):
        return
    run_stats = try_get_singleton(RunStats)
    if run_stats:
        run_stats.damage_dealt += amount


def mitigate_damage(target_ent: int, amount: int) -> int:
    """Reduce a direct damage hit by the target's active SHIELD power (floored at 0).

    Shields blunt discrete hits — melee, damage spells, drains — not damage-over-time,
    so poison pulses deliberately bypass this."""
    shield = get_status(target_ent, StatusType.SHIELD)
    if shield:
        return max(0, amount - shield.power)
    return amount


def _apply_hp_damage(target_ent: int, amount: int) -> int:
    """Resolve one discrete damage hit: mitigate by shield, subtract HP, tally for the
    run summary, and flash the screen. Returns the mitigated amount actually dealt, so
    callers can tell whether a shield absorbed part of it (`returned < amount`)."""
    mitigated = mitigate_damage(target_ent, amount)
    stats = esper.component_for_entity(target_ent, Stats)
    stats.hp -= mitigated
    record_damage_dealt(target_ent, mitigated)
    trigger_screen_flash(ent=target_ent, color=UI_RED)
    return mitigated


def deal_damage(target_ent: int, amount: int, message: str, color: tuple[int, int, int]):
    """Apply damage to a target's Stats and log a message."""
    mitigated = _apply_hp_damage(target_ent, amount)
    log = try_get_singleton(MessageLog)
    if log:
        if mitigated < amount:
            message = f'{message} (shielded)'
        log.add_simple_message(message, color=color)


def roll_loot(loot: Loot) -> tuple[ItemType, int] | None:
    """Pick one drop by relative `chance` weight, then roll its quantity.

    A quantity of 0 means the pick yields nothing, returning None.
    """
    if not loot.drops:
        return None
    drop = random.choices(loot.drops, weights=[d.chance for d in loot.drops])[0]
    count = random.randint(drop.min, drop.max)
    return (drop.type, count) if count > 0 else None


def apply_status_pulse(ent: int, status_type: StatusType, power: int, log: MessageLog | None):
    """Apply one pulse of a recurring status effect (poison damage / regen heal)."""
    stats = esper.component_for_entity(ent, Stats)
    name = actor_name(ent)

    if status_type == StatusType.POISON:
        stats.hp -= power
        record_damage_dealt(ent, power)
        trigger_screen_flash(ent=ent, color=UI_GREEN)
        if log:
            log.add_simple_message(f'{name} took {power} poison damage!', color=UI_GREEN_MID)
    elif status_type == StatusType.REGEN:
        stats.hp = min(stats.max_hp, stats.hp + power)
        if log:
            log.add_simple_message(f'{name} regained {power} HP.', color=UI_GREEN_BRIGHT)


def apply_effect(
    target_ent: int,
    effect: Effect,
    origin: Point | None = None,
    caster_ent: int | None = None,
):
    """Apply a single spell effect to a target entity.

    Instant effects (damage/heal/drain) resolve immediately; lingering ones store a
    copy of the effect on the target's StatusEffects for StatusSystem to age. `origin`
    is the push source for knockback (the target is shoved away from it); `caster_ent`
    is who cast the effect (drain heals them).
    """
    log = get_singleton(MessageLog)
    stats = esper.component_for_entity(target_ent, Stats)
    status = esper.component_for_entity(target_ent, StatusEffects)
    target_name = actor_name(target_ent)

    if effect.type == EffectType.DAMAGE:
        dmg = _apply_hp_damage(target_ent, effect.power)
        spray_hit_particles(target_ent)
        shielded = ' (shielded)' if dmg < effect.power else ''
        log.add_simple_message(f'{target_name} took {dmg} damage!{shielded}', color=UI_ORANGE)

    elif effect.type == EffectType.HEAL:
        stats.hp = min(stats.max_hp, stats.hp + effect.power)
        log.add_simple_message(f'{target_name} healed for {effect.power} HP!', color=UI_GREEN_BRIGHT)

    elif effect.type == EffectType.DRAIN:
        dmg = _apply_hp_damage(target_ent, effect.power)
        spray_hit_particles(target_ent)
        shielded = ' (shielded)' if dmg < effect.power else ''
        log.add_simple_message(f'{target_name} took {dmg} damage!{shielded}', color=UI_CRIMSON)
        if caster_ent is not None and esper.has_component(caster_ent, Stats):
            caster_stats = esper.component_for_entity(caster_ent, Stats)
            before = caster_stats.hp
            caster_stats.hp = min(caster_stats.max_hp, caster_stats.hp + effect.lifesteal)
            healed = caster_stats.hp - before
            log.add_simple_message(
                f'{get_display_name(caster_ent)} drained {healed} HP!',
                color=UI_GREEN_BRIGHT,
            )

    elif effect.type == EffectType.KNOCKBACK:
        if origin is not None:
            apply_knockback(target_ent, origin, effect.power)
        log.add_simple_message(f'{target_name} is knocked back!', color=UI_GRAY_LIGHT)

    elif effect.type in STATUS_APPLY:
        application = STATUS_APPLY[effect.type]
        status.active[application.status] = replace(effect)
        if application.damage_over_time:
            trigger_screen_flash(ent=target_ent, color=EFFECT_COLORS[effect.type])
        log.add_simple_message(application.message.format(name=target_name), color=application.color)
