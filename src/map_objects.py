from dataclasses import dataclass
import tcod

@dataclass
class Tile:
    walkable: bool
    transparent: bool
    sprite_id: str
    fg: tuple[int, int, int]
    bg: tuple[int, int, int]
    is_exit: bool = False

class Map:
    def __init__(self, width: int, height: int, default_tile: Tile):
        self.width = width
        self.height = height
        self.tiles = [[default_tile for _ in range(height)] for _ in range(width)]

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.tiles[x][y].walkable

    def render(self, console: tcod.Console, asset_loader: 'AssetLoader') -> None:
        for x in range(self.width):
            for y in range(self.height):
                tile = self.tiles[x][y]
                codepoint = asset_loader.get_codepoint(tile.sprite_id)
                console.print(
                    x=x,
                    y=y,
                    string=chr(codepoint),
                    fg=tile.fg,
                    bg=tile.bg,
                )
