import math
import random

import esper

from src.components import (
    CastVisual,
    EffectType,
    Particle,
    Point,
    Position,
    Projectile,
    ScreenFlash,
)
from src.constants import (
    UI_BLUE,
    UI_CYAN,
    UI_GREEN,
    UI_ORANGE,
    UI_RED,
    UI_WHITE,
    UI_YELLOW,
)
from src.ecs_helpers import is_player

# Color a cast spell's impact burst by its first effect type.
EFFECT_COLORS: dict[EffectType, tuple[int, int, int]] = {
    EffectType.DAMAGE: UI_ORANGE,
    EffectType.HEAL: UI_GREEN,
    EffectType.REGEN: UI_GREEN,
    EffectType.POISON: UI_GREEN,
    EffectType.SLOW: UI_BLUE,
    EffectType.HASTE: UI_YELLOW,
    EffectType.STUN: UI_YELLOW,
    EffectType.SHIELD: UI_CYAN,
    EffectType.DRAIN: UI_RED,
    EffectType.KNOCKBACK: UI_WHITE,
    EffectType.WET: UI_BLUE,
}

# Glyph a spell's projectile flies as, keyed by its primary effect (color comes from
# EFFECT_COLORS). Anything unmapped falls back to PROJECTILE_GLYPH_DEFAULT.
PROJECTILE_GLYPH_DEFAULT = '*'
PROJECTILE_GLYPHS: dict[EffectType, str] = {
    EffectType.DAMAGE: '*',
    EffectType.HEAL: '+',
    EffectType.REGEN: '+',
    EffectType.POISON: '*',
    EffectType.SLOW: '~',
    EffectType.HASTE: '!',
    EffectType.STUN: '?',
    EffectType.SHIELD: 'O',
    EffectType.DRAIN: '%',
    EffectType.KNOCKBACK: '>',
    EffectType.WET: '~',
}

# Glyphs a particle in a spray can take.
PARTICLE_GLYPHS = ('*', '+', '.')


def trigger_screen_flash(ent: int, color: tuple[int, int, int], ticks: int = ScreenFlash.DURATION):
    """Wash the map viewport with `color` when `ent` is the player.

    The flash is player-only damage feedback, so this no-ops for any other entity
    — damage code can call it unconditionally. A fresh hit replaces any in-flight flash.
    """
    if not is_player(ent):
        return
    for flash_ent, _flash in esper.get_component(ScreenFlash):
        esper.delete_entity(flash_ent, immediate=True)
    esper.create_entity(ScreenFlash(color=color, ticks=ticks, max_ticks=ticks))


def trigger_cast_visual(center: Point, radius: int, color: tuple[int, int, int]):
    """Burst `color` over a spell's impact radius, replacing any in-flight burst."""
    for ent, _visual in esper.get_component(CastVisual):
        esper.delete_entity(ent, immediate=True)
    esper.create_entity(
        CastVisual(
            center=center,
            radius=radius,
            color=color,
            ticks=CastVisual.DURATION,
            max_ticks=CastVisual.DURATION,
        )
    )


def trigger_projectile(start: Point, target: Point, effect_type: EffectType, burst_radius: int):
    """Launch a cosmetic glyph from `start` toward `target`, styled by `effect_type`.

    The projectile spawns the impact burst and a particle spray on arrival (see
    EffectOverlaySystem). Several projectiles may be in flight at once.
    """
    esper.create_entity(
        Projectile(
            start=start,
            target=target,
            glyph=PROJECTILE_GLYPHS.get(effect_type, PROJECTILE_GLYPH_DEFAULT),
            color=EFFECT_COLORS.get(effect_type, UI_ORANGE),
            burst_radius=burst_radius,
        )
    )


def spawn_particle_burst(center: Point, color: tuple[int, int, int], count: int):
    """Spray `count` particles radiating from `center` in random directions."""
    for _ in range(count):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(0.15, 0.45)
        esper.create_entity(
            Particle(
                x=float(center.x),
                y=float(center.y),
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed,
                glyph=random.choice(PARTICLE_GLYPHS),
                color=color,
                ticks=Particle.DURATION,
                max_ticks=Particle.DURATION,
            )
        )


def spray_hit_particles(target_ent: int):
    """Spray a few damage particles at an enemy's tile. No-op for the player, who
    already gets the screen flash, and for anything without a position to spray from."""
    if is_player(target_ent) or not esper.has_component(target_ent, Position):
        return
    spawn_particle_burst(
        center=esper.component_for_entity(target_ent, Position).point,
        color=EFFECT_COLORS[EffectType.DAMAGE],
        count=Particle.HIT_COUNT,
    )
