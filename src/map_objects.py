from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from src.components import Effect


@dataclass(frozen=True)
class Tile:
    walkable: bool
    transparent: bool
    sprite_id: str
    fg: tuple[int, int, int]
    bg: tuple[int, int, int]
    is_exit: bool = False
    # A hazard/trap carries effects applied to any actor that enters the cell (HazardSystem).
    # `hidden` marks a detection-reveal trap: drawn as plain floor until the player detects it.
    effects: tuple[Effect, ...] = ()
    hidden: bool = False


class Map:
    # How far to dim the exit tile's color while its guardians still seal it; it lights to
    # full brightness once they're cleared, signaling the way down is open.
    SEALED_EXIT_DIM = 0.35

    def __init__(self, width: int, height: int, default_tile: Tile):
        self.width = width
        self.height = height
        self.tiles = [[default_tile for _ in range(height)] for _ in range(width)]
        self.explored = np.zeros((width, height), dtype=bool, order='F')
        # Which hidden-trap cells the player has detected; a revealed trap draws its warning
        # look, while an undetected one is drawn as `floor_look` (see FOVSystem / _render_map).
        self.revealed: NDArray[np.bool_] = np.zeros((width, height), dtype=bool, order='F')
        # The plain floor tile chosen for this floor, so the renderer can disguise concealed
        # traps as floor. Seeded to the fill tile; procgen overwrites it with the real floor.
        self.floor_look = default_tile
        # Derived arrays are seeded from the fill tile and kept in sync via set_tile.
        self.transparent = np.full((width, height), default_tile.transparent, dtype=bool, order='F')
        self.walkable = np.full((width, height), default_tile.walkable, dtype=bool, order='F')
        # The exit tile's location, recorded as it's placed so the minimap can mark it
        # without scanning the grid each frame.
        self.exit_pos: tuple[int, int] | None = None

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.tiles[x][y].walkable

    def set_tile(self, x: int, y: int, tile: Tile) -> None:
        """Place a tile, keeping the derived walkable/transparent arrays in sync."""
        self.tiles[x][y] = tile
        self.transparent[x, y] = tile.transparent
        self.walkable[x, y] = tile.walkable
        if tile.is_exit:
            self.exit_pos = (x, y)

    def reveal_all_traps(self) -> int:
        """Mark every still-armed hidden trap on this floor as detected (drawn as a warning
        instead of plain floor). Returns how many were newly revealed; sprung traps are already
        visible, so they don't count."""
        count = 0
        for x in range(self.width):
            for y in range(self.height):
                if self.tiles[x][y].hidden and not self.revealed[x, y]:
                    self.revealed[x, y] = True
                    count += 1
        return count
