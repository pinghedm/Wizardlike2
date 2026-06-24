from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class Tile:
    walkable: bool
    transparent: bool
    sprite_id: str
    fg: tuple[int, int, int]
    bg: tuple[int, int, int]
    is_exit: bool = False


class Map:
    # How far to dim the exit tile's color while its guardians still seal it; it lights to
    # full brightness once they're cleared, signaling the way down is open.
    SEALED_EXIT_DIM = 0.35

    def __init__(self, width: int, height: int, default_tile: Tile):
        self.width = width
        self.height = height
        self.tiles = [[default_tile for _ in range(height)] for _ in range(width)]
        self.explored = np.zeros((width, height), dtype=bool, order='F')
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
