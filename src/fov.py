"""Field-of-view via recursive shadowcasting

`compute_fov` returns a boolean grid (same [x][y] shape as the transparency map)
marking the tiles visible from `pov` within `radius`. With `light_walls` (the
default), opaque tiles at the edge of sight are lit so walls bounding a lit room
are drawn.
"""

import numpy as np
from numpy.typing import NDArray

# Per-octant coordinate transforms (xx, xy, yx, yy) mapping the scan's local (dx, dy)
# into map space, so one scan routine covers all eight octants.
_OCTANTS: tuple[tuple[int, int, int, int], ...] = (
    (1, 0, 0, 1), (0, 1, 1, 0), (0, -1, 1, 0), (-1, 0, 0, 1),
    (-1, 0, 0, -1), (0, -1, -1, 0), (0, 1, -1, 0), (1, 0, 0, -1),
)  # fmt: skip


class _ShadowCaster:
    def __init__(self, transparent: NDArray[np.bool_], radius: int, light_walls: bool) -> None:
        self.transparent = transparent
        self.width = int(transparent.shape[0])
        self.height = int(transparent.shape[1])
        self.radius = radius
        self.radius_sq = radius * radius
        self.light_walls = light_walls
        self.visible: NDArray[np.bool_] = np.zeros_like(transparent)
        self.ox = 0
        self.oy = 0

    def compute(self, ox: int, oy: int) -> NDArray[np.bool_]:
        self.ox, self.oy = ox, oy
        self.visible[ox, oy] = True
        for xx, xy, yx, yy in _OCTANTS:
            self._cast(1, 1.0, 0.0, xx, xy, yx, yy)
        return self.visible

    def _cast(self, row: int, start: float, end: float, xx: int, xy: int, yx: int, yy: int) -> None:
        if start < end:
            return
        new_start = 0.0
        for j in range(row, self.radius + 1):
            dx, dy = -j - 1, -j
            blocked = False
            while dx <= 0:
                dx += 1
                mx = self.ox + dx * xx + dy * xy
                my = self.oy + dx * yx + dy * yy
                l_slope = (dx - 0.5) / (dy + 0.5)
                r_slope = (dx + 0.5) / (dy - 0.5)
                if start < r_slope:
                    continue
                if end > l_slope:
                    break
                in_bounds = 0 <= mx < self.width and 0 <= my < self.height
                if dx * dx + dy * dy <= self.radius_sq and in_bounds:
                    if self.light_walls or bool(self.transparent[mx, my]):
                        self.visible[mx, my] = True
                passable = in_bounds and bool(self.transparent[mx, my])
                if blocked:
                    if not passable:
                        new_start = r_slope
                        continue
                    blocked = False
                    start = new_start
                elif not passable and j < self.radius:
                    # An opaque tile in open sight starts a narrower child scan past it.
                    blocked = True
                    self._cast(j + 1, start, l_slope, xx, xy, yx, yy)
                    new_start = r_slope
            if blocked:
                break


def compute_fov(
    transparent: NDArray[np.bool_], pov: tuple[int, int], radius: int = 8, light_walls: bool = True
) -> NDArray[np.bool_]:
    return _ShadowCaster(transparent, radius, light_walls).compute(pov[0], pov[1])
