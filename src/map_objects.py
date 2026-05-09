from dataclasses import dataclass
import tcod

@dataclass
class Tile:
    walkable: bool
    transparent: bool
    char: str
    fg: tuple[int, int, int]
    bg: tuple[int, int, int]
    is_exit: bool = False

    @staticmethod
    def wall() -> 'Tile':
        return Tile(
            walkable=False,
            transparent=False,
            char=' ',
            fg=(255, 255, 255),
            bg=(0, 0, 100),
        )

    @staticmethod
    def floor() -> 'Tile':
        return Tile(
            walkable=True,
            transparent=True,
            char=' ',
            fg=(255, 255, 255),
            bg=(50, 50, 150),
        )

    @staticmethod
    def exit() -> 'Tile':
        return Tile(
            walkable=True,
            transparent=True,
            char='\u2588',  # Full block
            fg=(255, 255, 0),  # Yellow
            bg=(50, 50, 150),
            is_exit=True,
        )

class Map:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.tiles = [[Tile.wall() for _ in range(height)] for _ in range(width)]

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.tiles[x][y].walkable

    def render(self, console: tcod.Console) -> None:
        for x in range(self.width):
            for y in range(self.height):
                tile = self.tiles[x][y]
                console.print(
                    x=x,
                    y=y,
                    string=tile.char,
                    fg=tile.fg,
                    bg=tile.bg,
                )
