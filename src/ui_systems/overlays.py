import math
from collections.abc import Iterator

import esper
import pygame

from src.audio import SoundId, play_sfx
from src.components import (
    NPC,
    Actor,
    CastVisual,
    FieldOfView,
    FloatingNumber,
    InputAction,
    Particle,
    Position,
    Projectile,
    ScreenFlash,
    Settings,
    Shopkeeper,
    SpellInventory,
    SpellType,
    TargetingReticle,
    UIState,
)
from src.constants import (
    TILE_PX,
    UI_BLACK,
    UI_FONT_PX,
    UI_GRAY_DARK,
    UI_MAROON,
    UI_NAVY,
    UI_SKY,
    UI_YELLOW,
    to_rgb,
)
from src.ecs_helpers import chebyshev_distance, get_player_component, get_singleton, try_get_singleton
from src.map_objects import Map
from src.render import RenderProcessor, Viewport, compute_viewport, map_viewport_rect
from src.states import DisplayMode, GameState
from src.systems import spawn_particle_burst, trigger_cast_visual
from src.ui_draw import blit_text, fill_alpha


def _viewport(surface: pygame.Surface) -> Viewport | None:
    """The map camera/viewport anchored on the player, shared with RenderSystem, or None
    when there's no player or map to anchor to."""
    player_pos = get_player_component(Position)
    game_map = try_get_singleton(Map)
    if player_pos is None or game_map is None:
        return None
    return compute_viewport(surface, player_pos.x, player_pos.y, game_map.width, game_map.height)


def _key_label(action: InputAction) -> str:
    """The keyboard key currently bound to `action`, upper-cased for a control hint —
    reads the live keybindings so a remap keeps every prompt accurate."""
    bindings = get_singleton(Settings).keybindings.bindings
    return pygame.key.name(bindings[action]).upper()


def _tiles_in_radius(center_x: int, center_y: int, radius: int) -> Iterator[tuple[int, int]]:
    """Yield the map tiles in the bounding box of `radius` around (center_x, center_y)."""
    for map_y in range(center_y - radius, center_y + radius + 1):
        for map_x in range(center_x - radius, center_x + radius + 1):
            yield map_x, map_y


class TargetingOverlaySystem(RenderProcessor):
    def process(self):
        if get_singleton(GameState).display_mode != DisplayMode.TARGETING:
            return
        reticles = esper.get_component(TargetingReticle)
        if not reticles:
            return
        _ent, reticle = reticles[0]
        viewport = _viewport(self.surface)
        if viewport is None:
            return

        self._outline_aoe(viewport, reticle)

        # Frame the aimed tile with a bright outline instead of covering it, so the target's
        # sprite and any status tint stay visible underneath. Color signals the mode: yellow
        # for a lock-on, sky-blue for the free-moving cursor.
        tx, ty = viewport.tile_to_px(reticle.x, reticle.y)
        if viewport.contains_px(tx, ty):
            color = UI_YELLOW if reticle.locked else UI_SKY
            pygame.draw.rect(self.surface, color, (tx, ty, TILE_PX, TILE_PX), width=2)

        self._draw_label(viewport, reticle)

    def _outline_aoe(self, viewport: Viewport, reticle: TargetingReticle) -> None:
        """Shade only in-range tiles that border an out-of-range one, leaving the interior (and
        any enemies in it) visible; the translucent fill keeps the sprites beneath readable."""
        if reticle.radius <= 0:
            return
        r2 = reticle.radius**2
        for map_x, map_y in _tiles_in_radius(reticle.x, reticle.y, reticle.radius):
            if (map_x - reticle.x) ** 2 + (map_y - reticle.y) ** 2 > r2:
                continue
            on_edge = any(
                (map_x + dx - reticle.x) ** 2 + (map_y + dy - reticle.y) ** 2 > r2
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            if not on_edge:
                continue
            px, py = viewport.tile_to_px(map_x, map_y)
            if viewport.contains_px(px, py):
                fill_alpha(self.surface, px, py, TILE_PX, TILE_PX, UI_MAROON, 0.6)

    def _draw_label(self, viewport: Viewport, reticle: TargetingReticle) -> None:
        """Name the spell being aimed, its charges, and the mode-appropriate controls, on a navy
        strip at the top. The toggle-aim and cast keys are read live, so a remap stays accurate."""
        spell_id = get_singleton(UIState).active_targeting_spell_id
        if spell_id is None:
            return
        spell_inv = get_player_component(SpellInventory)
        charges = spell_inv.spells.get(SpellType(spell_id), 0) if spell_inv else 0
        label = f'Aiming: {SpellType(spell_id).name} ({charges} charges)'
        if reticle.target_ent is None:
            label += ' (no target)'
        toggle, cast = _key_label(InputAction.TOGGLE_AIM), _key_label(InputAction.CONFIRM)
        if reticle.locked:
            controls = f'Arrows: move  Tab: switch  {toggle}: free-aim  {cast}: cast'
        else:
            controls = f'Arrows: aim  Tab: nearest  {toggle}: lock  {cast}: cast'
        for row, text in enumerate((label, controls)):
            y = viewport.px_y + row * UI_FONT_PX
            width = self.font.size(text)[0] + 12
            pygame.draw.rect(self.surface, UI_NAVY, (viewport.px_x, y, width, UI_FONT_PX))
            blit_text(self.surface, self.font, text, viewport.px_x + 6, y, UI_YELLOW)


class InteractPromptSystem(RenderProcessor):
    """Floats a small tag over each visible friendly (shopkeeper / story NPC) so they read as
    talk-to characters rather than another enemy sprite. From afar it names them; step adjacent
    and it becomes the action hint ('<Confirm>: Shop' / '<Confirm>: Talk'), mirroring the
    Confirm-while-adjacent interaction in the exploring handler. The Confirm control is read from
    the live keybindings, not hard-coded, so a remap keeps the hint accurate."""

    _PAD = 3

    def process(self):
        if get_singleton(GameState).display_mode != DisplayMode.EXPLORING:
            return
        viewport = _viewport(self.surface)
        player_pos = get_player_component(Position)
        player_fov = get_player_component(FieldOfView)
        if viewport is None or player_pos is None:
            return
        confirm = self._confirm_label()
        for pos, name, verb in self._friendlies():
            if player_fov is not None and pos.point not in player_fov.visible_tiles:
                continue
            adjacent = chebyshev_distance(pos, player_pos) <= 1
            px, py = viewport.tile_to_px(pos.x, pos.y)
            if not viewport.contains_px(px, py):
                continue
            self._draw_tag(px, py, f'{confirm}: {verb}' if adjacent else name, highlight=adjacent)

    def _confirm_label(self) -> str:
        """The keyboard key currently bound to Confirm, upper-cased like the Settings readout."""
        return _key_label(InputAction.CONFIRM)

    def _friendlies(self) -> Iterator[tuple[Position, str, str]]:
        """Each interactable friendly as (position, far-off nameplate, adjacent action verb)."""
        for _ent, (pos, _shop) in esper.get_components(Position, Shopkeeper):
            yield pos, 'Merchant', 'Shop'
        for _ent, (pos, npc) in esper.get_components(Position, NPC):
            yield pos, npc.name, 'Talk'

    def _draw_tag(self, px: int, py: int, text: str, highlight: bool) -> None:
        """Center a pill of `text` just above the tile at (px, py) — a bright navy/yellow action
        cue when adjacent, a subtle dark/sky nameplate otherwise."""
        text_w = self.measure(text)
        height = self.font.get_height()
        x = px + TILE_PX // 2 - text_w // 2
        y = py - height - 2
        bg, fg = (UI_NAVY, UI_YELLOW) if highlight else (UI_BLACK, UI_SKY)
        rect = (x - self._PAD, y - 1, text_w + 2 * self._PAD, height + 2)
        if highlight:
            pygame.draw.rect(self.surface, bg, rect)
        else:
            fill_alpha(self.surface, *rect, bg, 0.55)
        blit_text(self.surface, self.font, text, x, y, fg)


# The recharge bar that floats over the player while a cast cools: its width in pixels and a fill
# that grows as it nears ready (at least a sliver the whole time, full once ready).
_COOLDOWN_BAR_HEIGHT = 4


def _cooldown_bar_fill(remaining: int, total: int, width: int) -> int:
    """Filled pixels for a recharge bar `remaining`/`total` ticks from ready. Fills as it
    recharges — at least one the whole time it's cooling, the full width once ready."""
    if remaining <= 0 or total <= 0:
        return width
    fill = 1 - remaining / total
    return max(1, round(fill * width))


class EffectOverlaySystem(RenderProcessor):
    """Renders and ages out transient combat visuals: the damage flash, cast burst,
    projectiles, particles, and floating numbers, drawn pixel-native over the map.

    Registered after the map/targeting draw but before the HUD, so it covers only the map
    area. Effects age every frame (independent of time_paused) so they fade even while the
    casting picker or a modal is open; projectiles/particles freeze with game time.
    """

    VISUAL_MODES = (DisplayMode.EXPLORING, DisplayMode.SPELL_WHEEL, DisplayMode.COMBINING, DisplayMode.TARGETING)

    def process(self):
        if get_singleton(GameState).display_mode not in self.VISUAL_MODES:
            return
        viewport = _viewport(self.surface)
        self._render_cast_visual(viewport)
        self._render_screen_flash()
        self._render_projectiles(viewport)
        self._render_particles(viewport)
        self._render_floating_numbers(viewport)
        if viewport is not None:
            self._render_cast_cooldown(viewport)

    def _time_paused(self) -> bool:
        return get_singleton(GameState).time_paused

    def _tile_center(self, viewport: Viewport, map_x: int, map_y: int) -> tuple[int, int]:
        px, py = viewport.tile_to_px(map_x, map_y)
        return px + TILE_PX // 2, py + TILE_PX // 2

    def _render_projectiles(self, viewport: Viewport | None):
        # Projectiles are part of game time: frozen in flight while a menu/modal pauses the
        # game, advancing only when exploring.
        paused = self._time_paused()
        for ent, proj in esper.get_component(Projectile):
            if not paused:
                dist = max(1.0, math.hypot(proj.target.x - proj.start.x, proj.target.y - proj.start.y))
                proj.progress += Projectile.SPEED / dist
                if proj.progress >= 1.0:
                    # Arrival: hand off to the impact burst and a particle spray.
                    trigger_cast_visual(center=proj.target, radius=proj.burst_radius, color=proj.color)
                    spawn_particle_burst(center=proj.target, color=proj.color, count=Particle.BURST_COUNT)
                    play_sfx(SoundId.IMPACT)
                    esper.delete_entity(ent, immediate=True)
                    continue
            if viewport is None:
                continue
            cell_x = round(proj.start.x + (proj.target.x - proj.start.x) * proj.progress)
            cell_y = round(proj.start.y + (proj.target.y - proj.start.y) * proj.progress)
            cx, cy = self._tile_center(viewport, cell_x, cell_y)
            if viewport.contains_px(cx, cy):
                pygame.draw.circle(self.surface, proj.color, (cx, cy), max(3, TILE_PX // 6))

    def _render_particles(self, viewport: Viewport | None):
        paused = self._time_paused()
        for ent, particle in esper.get_component(Particle):
            if not paused:
                particle.x += particle.vx
                particle.y += particle.vy
            if viewport is not None:
                cx, cy = self._tile_center(viewport, round(particle.x), round(particle.y))
                if viewport.contains_px(cx, cy):
                    ratio = particle.ticks / particle.max_ticks
                    fg = to_rgb([int(c * ratio) for c in particle.color])
                    pygame.draw.circle(self.surface, fg, (cx, cy), 3)
            if not paused:
                particle.ticks -= 1
                if particle.ticks <= 0:
                    esper.delete_entity(ent, immediate=True)

    def _render_floating_numbers(self, viewport: Viewport | None):
        # Pure feedback like the screen flash: rises and fades every frame regardless of
        # time_paused, so a number clears even while a modal is open.
        for ent, number in esper.get_component(FloatingNumber):
            number.y -= FloatingNumber.RISE_SPEED
            if viewport is not None:
                cx, cy = self._tile_center(viewport, round(number.x), round(number.y))
                ratio = number.ticks / number.max_ticks
                fg = to_rgb([int(c * ratio) for c in number.color])
                text_w = self.font.size(number.text)[0]
                # Rest the number's bottom just above the tile so it floats over the head, not on it.
                text_y = cy - TILE_PX // 2 - self.font.get_height()
                if viewport.contains_px(cx, cy):
                    blit_text(self.surface, self.font, number.text, cx - text_w // 2, text_y, fg)
            number.ticks -= 1
            if number.ticks <= 0:
                esper.delete_entity(ent, immediate=True)

    def _render_cast_cooldown(self, viewport: Viewport):
        """Float a small recharge bar just above the player while a cast cooldown runs, so
        next-cast readiness reads without leaving the action. Fills as it nears ready, then
        vanishes once the wizard can cast again."""
        actor = get_player_component(Actor)
        pos = get_player_component(Position)
        if actor is None or pos is None or actor.cast_cooldown <= 0:
            return
        px, py = viewport.tile_to_px(pos.x, pos.y)
        bar_w = TILE_PX
        filled = _cooldown_bar_fill(actor.cast_cooldown, actor.cast_cooldown_max, bar_w)
        fill_ratio = 1 - actor.cast_cooldown / actor.cast_cooldown_max
        k = 0.5 + 0.5 * fill_ratio  # dim right after casting, brightening as it nears ready
        bright = to_rgb([int(c * k) for c in UI_SKY])
        bar_y = py - _COOLDOWN_BAR_HEIGHT - 3
        pygame.draw.rect(self.surface, UI_GRAY_DARK, (px, bar_y, bar_w, _COOLDOWN_BAR_HEIGHT))
        if filled > 0:
            pygame.draw.rect(self.surface, bright, (px, bar_y, filled, _COOLDOWN_BAR_HEIGHT))

    def _render_cast_visual(self, viewport: Viewport | None):
        visuals = esper.get_component(CastVisual)
        if not visuals:
            return
        ent, visual = visuals[0]
        if viewport is not None:
            alpha = CastVisual.MAX_ALPHA * visual.ticks / visual.max_ticks
            r2 = visual.radius**2
            for map_x, map_y in _tiles_in_radius(visual.center.x, visual.center.y, visual.radius):
                if (map_x - visual.center.x) ** 2 + (map_y - visual.center.y) ** 2 <= r2:
                    px, py = viewport.tile_to_px(map_x, map_y)
                    if viewport.contains_px(px, py):
                        fill_alpha(self.surface, px, py, TILE_PX, TILE_PX, visual.color, alpha)
        visual.ticks -= 1
        if visual.ticks <= 0:
            esper.delete_entity(ent, immediate=True)

    def _render_screen_flash(self):
        flashes = esper.get_component(ScreenFlash)
        if not flashes:
            return
        ent, flash = flashes[0]
        vx, vy, vw, vh = map_viewport_rect(self.surface)
        alpha = ScreenFlash.MAX_ALPHA * flash.ticks / flash.max_ticks
        fill_alpha(self.surface, vx, vy, vw, vh, flash.color, alpha)
        flash.ticks -= 1
        if flash.ticks <= 0:
            esper.delete_entity(ent, immediate=True)
