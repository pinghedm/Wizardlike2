import math
import random
from dataclasses import replace
from typing import TYPE_CHECKING

import esper
import tcod
import tcod.map
from tcod import libtcodpy

from src.components import (
    STATUS_APPLY,
    Actor,
    CastVisual,
    Effect,
    EffectType,
    Enemy,
    FieldOfView,
    ItemType,
    Loot,
    MessageLog,
    Particle,
    PlayerTag,
    Point,
    Position,
    Projectile,
    Renderable,
    RunStats,
    ScreenFlash,
    Stats,
    StatusEffects,
    StatusType,
)
from src.constants import (
    PLAYER_MOVE_COST,
    STATUS_PULSE_INTERVAL,
    UI_BLACK,
    UI_BLUE,
    UI_CRIMSON,
    UI_CYAN,
    UI_GRAY_LIGHT,
    UI_GREEN,
    UI_GREEN_BRIGHT,
    UI_GREEN_MID,
    UI_ORANGE,
    UI_RED,
    UI_WHITE,
    UI_YELLOW,
    to_rgb,
)
from src.debug import debug_log
from src.ecs_helpers import (
    actor_name,
    get_display_name,
    get_singleton,
    spawn_item_entity,
    try_get_singleton,
)
from src.map_objects import Map
from src.states import DisplayMode, GameState
from src.ui_helpers import blend

if TYPE_CHECKING:
    from src.data_loaders import AssetLoader
    from src.layout import Layout


def is_game_active() -> bool:
    """True when a run is in progress (a player entity exists).

    Used to decide between the title menu and the in-game pause menu.
    """
    return bool(esper.get_component(PlayerTag))


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
    if not esper.has_component(ent, PlayerTag):
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


def record_damage_dealt(target_ent: int, amount: int):
    """Tally damage the player caused for the run summary. Enemies only ever damage
    the player, so counting damage to any non-player entity equals player-dealt damage.
    """
    if esper.has_component(target_ent, PlayerTag):
        return
    run_stats = try_get_singleton(RunStats)
    if run_stats:
        run_stats.damage_dealt += amount


def mitigate_damage(target_ent: int, amount: int) -> int:
    """Reduce a direct damage hit by the target's active SHIELD power (floored at 0).

    Shields blunt discrete hits — melee, damage spells, drains — not damage-over-time,
    so poison pulses deliberately bypass this."""
    if esper.has_component(target_ent, StatusEffects):
        shield = esper.component_for_entity(target_ent, StatusEffects).active.get(StatusType.SHIELD)
        if shield:
            return max(0, amount - shield.power)
    return amount


def is_stunned(ent: int) -> bool:
    """Whether `ent` currently has an active STUN status and so forfeits its turn."""
    return (
        esper.has_component(ent, StatusEffects)
        and StatusType.STUN in esper.component_for_entity(ent, StatusEffects).active
    )


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


class DeathSystem(esper.Processor):
    """Handles death for all entities with Stats."""

    def process(self):
        log = try_get_singleton(MessageLog)

        for ent, stats in esper.get_component(Stats):
            if stats.hp <= 0:
                if esper.has_component(ent, PlayerTag):
                    debug_log(f'DeathSystem: player {ent} died (hp={stats.hp})')
                    get_singleton(GameState).display_mode = DisplayMode.GAME_OVER
                else:
                    debug_log(f'DeathSystem: deleting {ent} ({get_display_name(ent)})')
                    if log:
                        log.add_simple_message(f'The {get_display_name(ent)} dies!', color=UI_YELLOW)
                    run_stats = try_get_singleton(RunStats)
                    if run_stats:
                        run_stats.enemies_defeated += 1
                    self._drop_loot(ent)
                    esper.delete_entity(ent)

    def _drop_loot(self, ent: int):
        """Scatter a slain enemy's rolled loot onto its tile."""
        if not (esper.has_component(ent, Position) and esper.has_component(ent, Loot)):
            return
        drop = roll_loot(esper.component_for_entity(ent, Loot))
        if drop is None:
            return
        pos = esper.component_for_entity(ent, Position)
        itype, count = drop
        spawn_item_entity(itype, pos.x, pos.y, count)


class ActionSystem(esper.Processor):
    """Manages cooldowns for all actors."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused:
            return

        for _ent, actor in esper.get_component(Actor):
            if actor.cooldown > 0:
                actor.cooldown -= 1


def _apply_status_pulse(ent: int, status_type: StatusType, power: int, log: MessageLog | None):
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


class StatusSystem(esper.Processor):
    """Ages active status effects and applies recurring ones each pulse."""

    def process(self):
        game_state = esper.get_component(GameState)[0][1]
        if game_state.time_paused:
            return

        log = try_get_singleton(MessageLog)
        for ent, status in esper.get_component(StatusEffects):
            for status_type in list(status.active.keys()):
                effect = status.active[status_type]
                # Recurring effects carry power; they pulse on the global cadence.
                if effect.power and effect.duration % STATUS_PULSE_INTERVAL == 0:
                    _apply_status_pulse(ent, status_type, effect.power, log)
                effect.duration -= 1
                if effect.duration <= 0:
                    del status.active[status_type]


class FOVSystem(esper.Processor):
    def process(self):
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        for _ent, (pos, fov) in esper.get_components(Position, FieldOfView):
            if fov.dirty:
                fov.visible_tiles = set()
                # compute_fov expects [height, width] or [width, height] depending on order
                # With 'F' order (column-major), it matches our [x][y] structure
                fov_map = tcod.map.compute_fov(
                    transparency=game_map.transparent,
                    pov=(pos.x, pos.y),
                    radius=fov.radius,
                    light_walls=True,
                    algorithm=libtcodpy.FOV_BASIC,
                )

                # Update visible tiles and explored map
                for x in range(game_map.width):
                    for y in range(game_map.height):
                        if fov_map[x, y]:
                            fov.visible_tiles.add(Point(x, y))
                            # Only update explored for player FOV
                            if esper.has_component(_ent, PlayerTag):
                                game_map.explored[x, y] = True

                fov.dirty = False


class RenderSystem(esper.Processor):
    def __init__(self, layout: Layout, asset_loader: AssetLoader):
        self.layout = layout
        self.asset_loader = asset_loader

    @property
    def console(self) -> tcod.console.Console:
        return self.layout.console

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in [
            DisplayMode.EXPLORING,
            DisplayMode.CASTING,
            DisplayMode.COMBINING,
            DisplayMode.TARGETING,
            DisplayMode.SHOPPING,
        ]:
            return

        # 1. Get the Map and Player FOV
        game_map = try_get_singleton(Map)
        if not game_map:
            return

        player_fov = None
        player_pos = None
        for _ent, (fov, _tag) in esper.get_components(FieldOfView, PlayerTag):
            player_fov = fov
            break
        for _ent, (pos, _tag) in esper.get_components(Position, PlayerTag):
            player_pos = pos
            break

        # The camera follows the player; map cells draw into the map viewport,
        # converted from map space to screen space (the console cell to draw at):
        #   screen = viewport.origin + map_cell - camera
        view = self.layout.map_viewport
        focus_x = player_pos.x if player_pos else game_map.width // 2
        focus_y = player_pos.y if player_pos else game_map.height // 2
        cam_x, cam_y = self.layout.camera_offset(focus_x, focus_y, game_map.width, game_map.height)

        # 2. Render the map
        for x in range(game_map.width):
            for y in range(game_map.height):
                screen_x, screen_y = self.layout.map_to_screen(map_x=x, map_y=y, cam_x=cam_x, cam_y=cam_y)
                if not view.contains(screen_x, screen_y):
                    continue

                is_visible = player_fov is not None and Point(x, y) in player_fov.visible_tiles
                is_explored = game_map.explored[x, y]

                if not is_visible and not is_explored:
                    continue

                tile = game_map.tiles[x][y]
                codepoint = self.asset_loader.get_codepoint(tile.sprite_id)
                fg = tile.fg
                bg = tile.bg

                if not is_visible:
                    # Dim the colors for explored but not visible tiles
                    fg = to_rgb([int(c * 0.3) for c in fg])
                    bg = to_rgb([int(c * 0.3) for c in bg])

                self.console.print(x=screen_x, y=screen_y, text=chr(codepoint), fg=fg, bg=bg)

        # 3. Render all entities with Position and Renderable components that are visible
        for _ent, (pos, rend) in esper.get_components(Position, Renderable):
            if player_fov is not None and pos.point not in player_fov.visible_tiles:
                continue

            screen_x, screen_y = self.layout.map_to_screen(map_x=pos.x, map_y=pos.y, cam_x=cam_x, cam_y=cam_y)
            if not view.contains(screen_x, screen_y):
                continue

            codepoint = self.asset_loader.get_codepoint(rend.sprite_id)
            debug_log(f'render entity {_ent} sprite={rend.sprite_id} cp={codepoint} at {(pos.x, pos.y)}')
            # A stunned entity keeps its own glyph color over a yellow highlight.
            if is_stunned(_ent):
                self.console.print(
                    x=screen_x,
                    y=screen_y,
                    text=chr(codepoint),
                    fg=rend.color,
                    bg=blend(UI_BLACK, UI_YELLOW, 0.5),
                )
            else:
                self.console.print(x=screen_x, y=screen_y, text=chr(codepoint), fg=rend.color)


def _destination_blocked(mover: int, x: int, y: int) -> bool:
    """True if an actor already occupying (x, y) blocks the mover.

    The player may step onto a non-blocking enemy (the two overlap); every
    other actor-on-actor collision blocks movement.
    """
    for other_ent, (other_pos, _actor) in esper.get_components(Position, Actor):
        if other_ent == mover or other_pos.x != x or other_pos.y != y:
            continue
        if (
            esper.has_component(mover, PlayerTag)
            and esper.has_component(other_ent, Enemy)
            and not esper.component_for_entity(other_ent, Enemy).blocks_movement
        ):
            continue
        return True
    return False


def move_entity(entity: int, dx: int, dy: int):
    """Move an entity by (dx, dy) if the destination is walkable and unblocked.

    Pure movement: combat (e.g. bumping into an enemy) is the caller's concern.
    """
    pos = esper.component_for_entity(entity, Position)
    new_x = pos.x + dx
    new_y = pos.y + dy

    game_map = try_get_singleton(Map)
    if not game_map:
        return

    if not game_map.is_walkable(new_x, new_y):
        return

    # Enemies may not step onto exit tiles.
    if not esper.has_component(entity, PlayerTag) and game_map.tiles[new_x][new_y].is_exit:
        return

    if _destination_blocked(entity, new_x, new_y):
        return

    pos.x = new_x
    pos.y = new_y
    debug_log(f'move_entity {entity} -> {(new_x, new_y)} (player={esper.has_component(entity, PlayerTag)})')

    if esper.has_component(entity, FieldOfView):
        esper.component_for_entity(entity, FieldOfView).dirty = True

    # Player move consumes a turn at the base player move cost.
    if esper.has_component(entity, PlayerTag):
        actor = esper.component_for_entity(entity, Actor)
        actor.cooldown = get_cooldown(entity, PLAYER_MOVE_COST)


def _apply_knockback(target_ent: int, origin: Point, distance: int):
    """Shove `target_ent` up to `distance` tiles directly away from `origin`.

    Steps one tile at a time along the away-from-origin direction, halting at the
    first wall or occupied tile. A target sitting on the origin has no direction and
    stays put."""
    pos = esper.component_for_entity(target_ent, Position)
    step_x = (pos.x > origin.x) - (pos.x < origin.x)
    step_y = (pos.y > origin.y) - (pos.y < origin.y)
    if step_x == 0 and step_y == 0:
        return

    game_map = try_get_singleton(Map)
    if not game_map:
        return

    for _ in range(distance):
        nx, ny = pos.x + step_x, pos.y + step_y
        if not game_map.is_walkable(nx, ny) or _destination_blocked(target_ent, nx, ny):
            break
        pos.x, pos.y = nx, ny

    if esper.has_component(target_ent, FieldOfView):
        esper.component_for_entity(target_ent, FieldOfView).dirty = True


def get_cooldown(entity: int, base_speed: int) -> int:
    """Calculate cooldown based on status effects."""
    if esper.has_component(entity, StatusEffects):
        active = esper.component_for_entity(entity, StatusEffects).active
        if StatusType.SLOW in active:
            return base_speed * 2
        if StatusType.HASTE in active:
            return max(0, base_speed // 2)
    return max(0, base_speed)


def _spray_hit_particles(target_ent: int):
    """Spray a few damage particles at an enemy's tile. No-op for the player, who
    already gets the screen flash, and for anything without a position to spray from."""
    if esper.has_component(target_ent, PlayerTag) or not esper.has_component(target_ent, Position):
        return
    spawn_particle_burst(
        center=esper.component_for_entity(target_ent, Position).point,
        color=EFFECT_COLORS[EffectType.DAMAGE],
        count=Particle.HIT_COUNT,
    )


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
        _spray_hit_particles(target_ent)
        shielded = ' (shielded)' if dmg < effect.power else ''
        log.add_simple_message(f'{target_name} took {dmg} damage!{shielded}', color=UI_ORANGE)

    elif effect.type == EffectType.HEAL:
        stats.hp = min(stats.max_hp, stats.hp + effect.power)
        log.add_simple_message(f'{target_name} healed for {effect.power} HP!', color=UI_GREEN_BRIGHT)

    elif effect.type == EffectType.DRAIN:
        dmg = _apply_hp_damage(target_ent, effect.power)
        _spray_hit_particles(target_ent)
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
            _apply_knockback(target_ent, origin, effect.power)
        log.add_simple_message(f'{target_name} is knocked back!', color=UI_GRAY_LIGHT)

    elif effect.type in STATUS_APPLY:
        application = STATUS_APPLY[effect.type]
        status.active[application.status] = replace(effect)
        if application.damage_over_time:
            trigger_screen_flash(ent=target_ent, color=EFFECT_COLORS[effect.type])
        log.add_simple_message(application.message.format(name=target_name), color=application.color)
