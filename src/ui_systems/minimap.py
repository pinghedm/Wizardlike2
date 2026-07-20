"""Explored-area maps: a small, translucent always-on corner minimap and a full-screen
overview (DisplayMode.MAP_VIEW), both a downscaled render of the same explored open space.

We light the explored *walkable floor* and leave walls / the unknown dark, so a 1-wide
corridor reads as a lit path rather than vanishing between two walls. The pixel renderer
gets the sub-tile detail for free: the lit mask is built at map resolution (one pixel per
tile) and scaled up to the panel, so thin corridors stay visible.
"""

import esper
import numpy as np
import pygame

from src.components import Guardian, Position
from src.constants import (
    RGB,
    UI_BLACK,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_GRAY_MID,
    UI_GREEN_BRIGHT,
    UI_ORANGE,
    UI_YELLOW,
)
from src.data_loaders import AssetLoader
from src.ecs_helpers import exit_is_sealed, get_player_component, get_singleton, try_get_singleton
from src.map_objects import Map
from src.render import RenderProcessor, map_viewport_rect, minimap_rect
from src.states import WORLD_VIEW_MODES, DisplayMode, GameState
from src.ui_draw import blit_text, fill_alpha


def _thicken(mask: np.ndarray) -> np.ndarray:
    """Grow the lit mask by one tile in each direction (4-connected dilation), so 1-wide corridors
    read as a slightly thicker path once the small mask is scaled up to the panel."""
    out = mask.copy()
    out[:-1, :] |= mask[1:, :]
    out[1:, :] |= mask[:-1, :]
    out[:, :-1] |= mask[:, 1:]
    out[:, 1:] |= mask[:, :-1]
    return out


def _explored_surface(game_map: Map, color: RGB, alpha: int) -> pygame.Surface:
    """A map-resolution SRCALPHA Surface (one pixel per tile): explored walkable tiles (dilated a
    touch for visibility) filled `color` at `alpha`, everything else transparent. Scaled up by the
    caller."""
    lit = _thicken(np.asarray(game_map.explored) & np.asarray(game_map.walkable))  # (W, H) bool, [x][y]
    surface = pygame.Surface(lit.shape, pygame.SRCALPHA)
    rgb = pygame.surfarray.pixels3d(surface)
    alpha_view = pygame.surfarray.pixels_alpha(surface)
    rgb[lit] = color
    alpha_view[lit] = alpha
    del rgb, alpha_view  # release the surface locks
    return surface


def _draw_markers(surface: pygame.Surface, rect: pygame.Rect, game_map: Map, player_pos: Position | None) -> None:
    """Draw the live markers over the paths (only on explored tiles, so they don't reveal unseen
    ground): living guardians, the exit (dim while sealed, bright once cleared), player on top."""
    size = max(3, rect.width // 60)

    def at(map_x: int, map_y: int) -> tuple[int, int]:
        return rect.x + map_x * rect.width // game_map.width, rect.y + map_y * rect.height // game_map.height

    for _ent, (pos, _guardian) in esper.get_components(Position, Guardian):
        if game_map.explored[pos.x, pos.y]:
            pygame.draw.rect(surface, UI_ORANGE, (*at(pos.x, pos.y), size, size))

    if game_map.exit_pos is not None and game_map.explored[game_map.exit_pos]:
        color = UI_GRAY_DARK if exit_is_sealed() else UI_YELLOW
        pygame.draw.rect(surface, color, (*at(*game_map.exit_pos), size, size))

    if player_pos is not None:
        px, py = at(player_pos.x, player_pos.y)
        pygame.draw.circle(surface, UI_GREEN_BRIGHT, (px + size // 2, py + size // 2), size)


class MinimapSystem(RenderProcessor):
    """The always-on corner minimap, drawn translucently over the world view."""

    BACKDROP_FADE = 0.35  # how far to dim the dungeon behind the panel toward black
    PATH_ALPHA = 150  # translucency of the explored paths, so the live view shows through

    def __init__(self, surface: pygame.Surface, asset_loader: AssetLoader):
        super().__init__(surface, asset_loader)
        # The scaled path fill only changes as the player explores, so cache it (keyed by floor,
        # explored-cell count, and panel size); the backdrop + markers still redraw every frame.
        self._cache_key: tuple[int, int, int, int] | None = None
        self._cache_surface: pygame.Surface | None = None

    def _path_surface(self, game_map: Map, rect: pygame.Rect) -> pygame.Surface:
        key = (id(game_map), int(game_map.explored.sum()), rect.width, rect.height)
        if key != self._cache_key:
            small = _explored_surface(game_map, UI_GRAY, self.PATH_ALPHA)
            self._cache_surface = pygame.transform.scale(small, (rect.width, rect.height))
            self._cache_key = key
        assert self._cache_surface is not None
        return self._cache_surface

    def process(self):
        if get_singleton(GameState).display_mode not in WORLD_VIEW_MODES:
            return
        game_map = try_get_singleton(Map)
        if game_map is None:
            return
        _vx, _vy, vw, vh = map_viewport_rect(self.surface)
        if vw < 3 or vh < 3:
            return
        rect = minimap_rect(self.surface, game_map.width, game_map.height)

        fill_alpha(self.surface, rect.x, rect.y, rect.width, rect.height, UI_BLACK, self.BACKDROP_FADE)
        self.surface.blit(self._path_surface(game_map, rect), (rect.x, rect.y))
        _draw_markers(self.surface, rect, game_map, get_player_component(Position))
        pygame.draw.rect(self.surface, UI_GRAY_DARK, rect, width=1)  # subtle frame


class MapViewSystem(RenderProcessor):
    """The full-screen map overview (DisplayMode.MAP_VIEW), large enough to resolve corridors."""

    MARGIN = 40

    def process(self):
        if get_singleton(GameState).display_mode != DisplayMode.MAP_VIEW:
            return
        game_map = try_get_singleton(Map)
        if game_map is None:
            return

        width, height = self.surface.get_size()
        self.surface.fill(UI_BLACK)
        # Aspect-fit the whole level into the screen, centered, inside a margin.
        scale = min((width - 2 * self.MARGIN) / game_map.width, (height - 2 * self.MARGIN) / game_map.height)
        panel_w, panel_h = int(game_map.width * scale), int(game_map.height * scale)
        rect = pygame.Rect((width - panel_w) // 2, (height - panel_h) // 2, panel_w, panel_h)

        paths = pygame.transform.scale(_explored_surface(game_map, UI_GRAY, 255), (panel_w, panel_h))
        self.surface.blit(paths, rect.topleft)
        _draw_markers(self.surface, rect, game_map, get_player_component(Position))

        blit_text(self.surface, self.font, 'Map', (width - self.font.size('Map')[0]) // 2, 10, UI_GRAY_MID)
