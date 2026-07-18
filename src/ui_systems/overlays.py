import math
from collections.abc import Iterator

import esper
import numpy as np

from src.audio import SoundId, play_sfx
from src.components import (
    Actor,
    CastVisual,
    FloatingNumber,
    Particle,
    Position,
    Projectile,
    ScreenFlash,
    SpellInventory,
    SpellType,
    TargetingReticle,
    UIState,
)
from src.constants import (
    TILE_SCALE,
    UI_GRAY_DARK,
    UI_MAROON,
    UI_NAVY,
    UI_SKY,
    UI_YELLOW,
    to_rgb,
)
from src.ecs_helpers import get_player_component, get_singleton, try_get_singleton
from src.layout import LayoutProcessor, Rect
from src.map_objects import Map
from src.states import DisplayMode, GameState
from src.systems import spawn_particle_burst, trigger_cast_visual
from src.ui_helpers import blend


def _iter_cells_in_radius(
    view: Rect, cam_x: int, cam_y: int, center_x: int, center_y: int, radius: int
) -> Iterator[tuple[int, int, int, int]]:
    """Yield (screen_x, screen_y, map_x, map_y) for the viewport cells whose map tile lies in
    the bounding box of `radius` map tiles around (center_x, center_y), clipped to the viewport.
    Each tile spans a TILE_SCALE block of cells, so adjacent cells share a map tile. Walking only
    the affected box keeps an AoE paint off the rest of the viewport."""
    for map_y in range(center_y - radius, center_y + radius + 1):
        base_sy = view.y + (map_y - cam_y) * TILE_SCALE
        for map_x in range(center_x - radius, center_x + radius + 1):
            base_sx = view.x + (map_x - cam_x) * TILE_SCALE
            for screen_y in range(base_sy, base_sy + TILE_SCALE):
                for screen_x in range(base_sx, base_sx + TILE_SCALE):
                    if view.contains(screen_x, screen_y):
                        yield screen_x, screen_y, map_x, map_y


class TargetingOverlaySystem(LayoutProcessor):
    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode != DisplayMode.TARGETING:
            return

        reticles = esper.get_component(TargetingReticle)
        if not reticles:
            return

        _ent, reticle = reticles[0]
        player_pos = get_player_component(Position)
        if player_pos is None:
            return

        game_map = try_get_singleton(Map)
        if not game_map:
            return

        # The overlay highlights tiles, so it shares the map's camera transform:
        # iterate the viewport's screen cells, map each back to its map cell for
        # the distance tests, and paint the screen cell.
        view = self.layout.map_viewport
        cam_x, cam_y = self.layout.camera_offset(player_pos.x, player_pos.y, game_map.width, game_map.height)

        # Outline the spell's area-of-effect: shade only in-range cells that border an
        # out-of-range one, leaving the interior (and any enemies in it) visible. Blend so
        # an enemy on the ring keeps showing its glyph and status tint underneath.
        if reticle.radius > 0:
            r2 = reticle.radius**2
            for screen_x, screen_y, map_x, map_y in _iter_cells_in_radius(
                view, cam_x, cam_y, reticle.x, reticle.y, reticle.radius
            ):
                if (map_x - reticle.x) ** 2 + (map_y - reticle.y) ** 2 > r2:
                    continue
                on_edge = any(
                    (map_x + dx - reticle.x) ** 2 + (map_y + dy - reticle.y) ** 2 > r2
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )
                if on_edge:
                    base = to_rgb(self.console.rgb[screen_y, screen_x]['bg'])
                    self.console.rgb[screen_y, screen_x]['bg'] = blend(base, UI_MAROON, 0.6)

        # Frame the locked tile's block with bright brackets instead of covering it, so the
        # reticle reads clearly over the target's glyph and any status tint, never hiding it.
        tx, ty = self.layout.map_to_screen(map_x=reticle.x, map_y=reticle.y, cam_x=cam_x, cam_y=cam_y)
        mid_y = ty + TILE_SCALE // 2
        for bx, bracket in ((tx - 1, '['), (tx + TILE_SCALE, ']')):
            if view.contains(bx, mid_y):
                self.console.print(bx, mid_y, bracket, fg=UI_YELLOW)

        # Name the spell being aimed, its remaining charges, and the controls.
        spell_id = get_singleton(UIState).active_targeting_spell_id
        if spell_id is not None:
            spell_inv = get_player_component(SpellInventory)
            charges = spell_inv.spells.get(SpellType(spell_id), 0) if spell_inv else 0
            label = f' Aiming: {SpellType(spell_id).name} ({charges} charges)'
            if reticle.target_ent is None:
                label += ' (no target)'
            self.console.print(view.x, view.y, f'{label} ', fg=UI_YELLOW, bg=UI_NAVY)
            self.console.print(view.x, view.y + 1, ' Move: arrows  Tab: switch  Enter: cast ', fg=UI_YELLOW, bg=UI_NAVY)


# The little recharge bar that floats above the player while casting cools: its width in cells and
# a thin lower-block glyph so it reads as a slim line rather than a chunky row of full blocks.
_COOLDOWN_BAR_WIDTH = 4
_COOLDOWN_BAR_GLYPH = '▁'


def _cooldown_bar_fill(remaining: int, total: int, width: int) -> int:
    """Number of filled cells for a recharge bar `remaining`/`total` ticks from ready. Fills as it
    recharges — at least one cell the whole time it's cooling, the full width once ready."""
    if remaining <= 0 or total <= 0:
        return width
    fill = 1 - remaining / total
    return max(1, round(fill * width))


class EffectOverlaySystem(LayoutProcessor):
    """Renders and ages out transient combat visuals: the damage screen flash and
    the spell-cast impact burst.

    Registered after the map/targeting draw but before the HUD, so it tints only the
    map area, never the HUD or modals. Effects age on every frame (independent of
    time_paused) so they fade out even while the casting picker or a modal is open.
    """

    # Display modes that draw the map, and so can show map-anchored combat visuals.
    VISUAL_MODES = (DisplayMode.EXPLORING, DisplayMode.CASTING, DisplayMode.COMBINING, DisplayMode.TARGETING)

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in self.VISUAL_MODES:
            return
        self._render_cast_visual()
        self._render_screen_flash()
        self._render_projectiles()
        self._render_particles()
        self._render_floating_numbers()
        self._render_cast_cooldown()

    def _time_paused(self) -> bool:
        return get_singleton(GameState).time_paused

    def _camera(self) -> tuple[int, int] | None:
        """The current camera offset, or None if there's no player or map to anchor to."""
        player_pos = get_player_component(Position)
        game_map = try_get_singleton(Map)
        if player_pos is None or game_map is None:
            return None
        return self.layout.camera_offset(player_pos.x, player_pos.y, game_map.width, game_map.height)

    def _render_projectiles(self):
        # Projectiles are part of game time: frozen in flight while a menu/modal pauses
        # the game, advancing only when exploring.
        paused = self._time_paused()
        cam = self._camera()
        view = self.layout.map_viewport
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
            if cam is None:
                continue
            cell_x = round(proj.start.x + (proj.target.x - proj.start.x) * proj.progress)
            cell_y = round(proj.start.y + (proj.target.y - proj.start.y) * proj.progress)
            block_x, block_y = self.layout.map_to_screen(map_x=cell_x, map_y=cell_y, cam_x=cam[0], cam_y=cam[1])
            screen_x, screen_y = block_x + TILE_SCALE // 2, block_y + TILE_SCALE // 2
            if view.contains(screen_x, screen_y):
                self.console.print(screen_x, screen_y, proj.glyph, fg=proj.color)

    def _render_particles(self):
        paused = self._time_paused()
        cam = self._camera()
        view = self.layout.map_viewport
        for ent, particle in esper.get_component(Particle):
            if not paused:
                particle.x += particle.vx
                particle.y += particle.vy
            if cam is not None:
                block_x, block_y = self.layout.map_to_screen(
                    map_x=round(particle.x), map_y=round(particle.y), cam_x=cam[0], cam_y=cam[1]
                )
                screen_x, screen_y = block_x + TILE_SCALE // 2, block_y + TILE_SCALE // 2
                if view.contains(screen_x, screen_y):
                    ratio = particle.ticks / particle.max_ticks
                    fg = to_rgb([int(c * ratio) for c in particle.color])
                    self.console.print(screen_x, screen_y, particle.glyph, fg=fg)
            if not paused:
                particle.ticks -= 1
                if particle.ticks <= 0:
                    esper.delete_entity(ent, immediate=True)

    def _render_floating_numbers(self):
        # Pure feedback like the screen flash: rises and fades every frame regardless of
        # time_paused, so a number clears even while a modal is open.
        cam = self._camera()
        view = self.layout.map_viewport
        for ent, number in esper.get_component(FloatingNumber):
            number.y -= FloatingNumber.RISE_SPEED
            if cam is not None:
                block_x, block_y = self.layout.map_to_screen(
                    map_x=round(number.x), map_y=round(number.y), cam_x=cam[0], cam_y=cam[1]
                )
                screen_x = block_x + TILE_SCALE // 2 - len(number.text) // 2
                if view.contains(screen_x, block_y):
                    ratio = number.ticks / number.max_ticks
                    fg = to_rgb([int(c * ratio) for c in number.color])
                    self.console.print(screen_x, block_y, number.text, fg=fg)
            number.ticks -= 1
            if number.ticks <= 0:
                esper.delete_entity(ent, immediate=True)

    def _render_cast_cooldown(self):
        """Float a small recharge bar a row above the player while a cast cooldown is running, so
        next-cast readiness reads without leaving the action. It fills as it nears ready, then
        vanishes. Gone entirely once the wizard can cast again."""
        actor = get_player_component(Actor)
        pos = get_player_component(Position)
        cam = self._camera()
        if actor is None or pos is None or cam is None or actor.cast_cooldown <= 0:
            return
        block_x, block_y = self.layout.map_to_screen(map_x=pos.x, map_y=pos.y, cam_x=cam[0], cam_y=cam[1])
        width = _COOLDOWN_BAR_WIDTH
        start_x = block_x + TILE_SCALE // 2 - width // 2  # centered over the player's tile
        y = block_y - 1  # the row just above the head
        view = self.layout.map_viewport

        filled = _cooldown_bar_fill(actor.cast_cooldown, actor.cast_cooldown_max, width)
        fill_ratio = 1 - actor.cast_cooldown / actor.cast_cooldown_max
        r, g, b = UI_SKY
        k = 0.5 + 0.5 * fill_ratio  # dim right after casting, brightening as it nears ready
        bright = (int(r * k), int(g * k), int(b * k))
        for i in range(width):
            sx = start_x + i
            if view.contains(sx, y):
                self.console.print(sx, y, _COOLDOWN_BAR_GLYPH, fg=bright if i < filled else UI_GRAY_DARK)

    def _render_cast_visual(self):
        visuals = esper.get_component(CastVisual)
        if not visuals:
            return
        ent, visual = visuals[0]
        self._draw_cast_burst(visual)
        visual.ticks -= 1
        if visual.ticks <= 0:
            esper.delete_entity(ent, immediate=True)

    def _draw_cast_burst(self, visual: CastVisual):
        cam = self._camera()
        if cam is None:
            return
        cam_x, cam_y = cam

        view = self.layout.map_viewport
        alpha = CastVisual.MAX_ALPHA * visual.ticks / visual.max_ticks

        for screen_x, screen_y, map_x, map_y in _iter_cells_in_radius(
            view, cam_x, cam_y, visual.center.x, visual.center.y, visual.radius
        ):
            if (map_x - visual.center.x) ** 2 + (map_y - visual.center.y) ** 2 <= visual.radius**2:
                base = to_rgb(self.console.rgb[screen_y, screen_x]['bg'])
                self.console.rgb[screen_y, screen_x]['bg'] = blend(base, visual.color, alpha)

    def _render_screen_flash(self):
        flashes = esper.get_component(ScreenFlash)
        if not flashes:
            return
        ent, flash = flashes[0]

        view = self.layout.map_viewport
        alpha = ScreenFlash.MAX_ALPHA * flash.ticks / flash.max_ticks
        region = self.console.rgb['bg'][view.y : view.y + view.height, view.x : view.x + view.width]
        region[:] = region * (1 - alpha) + np.array(flash.color, dtype=float) * alpha

        flash.ticks -= 1
        if flash.ticks <= 0:
            esper.delete_entity(ent, immediate=True)
