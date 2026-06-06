import math
from collections.abc import Iterator

import esper
import numpy as np

from src.components import (
    CastVisual,
    Particle,
    Position,
    Projectile,
    ScreenFlash,
    TargetingReticle,
)
from src.constants import (
    UI_MAROON,
    UI_NAVY,
    UI_YELLOW,
    to_rgb,
)
from src.ecs_helpers import get_player_component, get_singleton, try_get_singleton
from src.layout import LayoutProcessor, Rect
from src.map_objects import Map
from src.states import DisplayMode, GameState
from src.systems import spawn_particle_burst, trigger_cast_visual
from src.ui_helpers import blend


def _iter_viewport_cells(view: Rect, cam_x: int, cam_y: int) -> Iterator[tuple[int, int, int, int]]:
    """Yield (screen_x, screen_y, map_x, map_y) for every cell of the map viewport,
    pairing each on-screen cell with the map cell the camera maps it to."""
    for screen_y in range(view.y, view.y + view.height):
        for screen_x in range(view.x, view.x + view.width):
            yield screen_x, screen_y, screen_x - view.x + cam_x, screen_y - view.y + cam_y


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

        for screen_x, screen_y, map_x, map_y in _iter_viewport_cells(view, cam_x, cam_y):
            dist_to_reticle_sq = (map_x - reticle.x) ** 2 + (map_y - reticle.y) ** 2
            dist_to_player_sq = (map_x - player_pos.x) ** 2 + (map_y - player_pos.y) ** 2

            if dist_to_reticle_sq <= reticle.radius**2:
                self.console.rgb[screen_y, screen_x]['bg'] = UI_MAROON
            elif dist_to_player_sq <= reticle.range**2:
                self.console.rgb[screen_y, screen_x]['bg'] = UI_NAVY

        # Draw yellow reticle X at its on-screen position.
        screen_rx, screen_ry = self.layout.map_to_screen(map_x=reticle.x, map_y=reticle.y, cam_x=cam_x, cam_y=cam_y)
        if view.contains(screen_rx, screen_ry):
            self.console.print(screen_rx, screen_ry, 'X', fg=UI_YELLOW)


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
                    esper.delete_entity(ent, immediate=True)
                    continue
            if cam is None:
                continue
            cell_x = round(proj.start.x + (proj.target.x - proj.start.x) * proj.progress)
            cell_y = round(proj.start.y + (proj.target.y - proj.start.y) * proj.progress)
            screen_x, screen_y = self.layout.map_to_screen(map_x=cell_x, map_y=cell_y, cam_x=cam[0], cam_y=cam[1])
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
                screen_x, screen_y = self.layout.map_to_screen(
                    map_x=round(particle.x), map_y=round(particle.y), cam_x=cam[0], cam_y=cam[1]
                )
                if view.contains(screen_x, screen_y):
                    ratio = particle.ticks / particle.max_ticks
                    fg = to_rgb([int(c * ratio) for c in particle.color])
                    self.console.print(screen_x, screen_y, particle.glyph, fg=fg)
            if not paused:
                particle.ticks -= 1
                if particle.ticks <= 0:
                    esper.delete_entity(ent, immediate=True)

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

        for screen_x, screen_y, map_x, map_y in _iter_viewport_cells(view, cam_x, cam_y):
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
