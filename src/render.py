"""Pixel-space camera/viewport

given the window surface and the tile the camera should follow, `compute_viewport` yields the map's
on-screen pixel region plus the top-left map tile to draw, clamped so the camera
never scrolls past the map edges. `Viewport.tile_to_px` converts a map tile to the
top-left pixel of its TILE_PX square.
"""

from dataclasses import dataclass

import pygame

from src.constants import TILE_PX

# Pixels reserved at the bottom of the window for the HUD bar; the map fills the rest.
HUD_PX = 140


@dataclass(frozen=True)
class Viewport:
    """The map's on-screen pixel rect and the camera's top-left map tile."""

    px_x: int
    px_y: int
    width: int
    height: int
    cam_x: int
    cam_y: int

    def tile_to_px(self, map_x: int, map_y: int) -> tuple[int, int]:
        """Top-left pixel of the TILE_PX square for map tile (map_x, map_y)."""
        return self.px_x + (map_x - self.cam_x) * TILE_PX, self.px_y + (map_y - self.cam_y) * TILE_PX

    def contains_px(self, px: int, py: int) -> bool:
        return self.px_x <= px < self.px_x + self.width and self.px_y <= py < self.px_y + self.height


def map_viewport_rect(surface: pygame.Surface) -> tuple[int, int, int, int]:
    """The (x, y, w, h) pixel rect the map draws into: the whole window above the HUD strip."""
    width, height = surface.get_size()
    return 0, 0, width, max(0, height - HUD_PX)


def compute_viewport(surface: pygame.Surface, focus_x: int, focus_y: int, map_w: int, map_h: int) -> Viewport:
    """Center the camera on (focus_x, focus_y), clamped so it never scrolls off the map."""
    px_x, px_y, width, height = map_viewport_rect(surface)
    tiles_x = width // TILE_PX
    tiles_y = height // TILE_PX
    cam_x = min(max(focus_x - tiles_x // 2, 0), max(0, map_w - tiles_x))
    cam_y = min(max(focus_y - tiles_y // 2, 0), max(0, map_h - tiles_y))
    return Viewport(px_x, px_y, width, height, cam_x, cam_y)
