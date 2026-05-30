"""Screen layout: panel geometry and the camera transform.

`Layout` owns the live tcod console and derives its panel rects from the console
size, so a window resize is just swapping in the new console — the rects follow.
It is injected into the render processors rather than queried from the ECS: the
render target is infrastructure, not game state, and this also lets it survive the
clear_database() done on new game / load. `Rect` is a plain value type.
"""

from dataclasses import dataclass

import tcod.console


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in console cells. (x, y) is the top-left corner."""

    x: int
    y: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height

    def centered(self, width: int, height: int) -> tuple[int, int]:
        """Top-left for a box of the given size centered within this rect."""
        return self.x + (self.width - width) // 2, self.y + (self.height - height) // 2

    def split_left(self, width: int) -> tuple[Rect, Rect]:
        """Divide into a left rect `width` columns wide and the remaining right rect.

        Lets a panel subdivide its own space into nested rects, so each owner
        describes only its internal layout (e.g. the HUD splitting into stats and
        a message log) rather than the parent knowing about it.
        """
        width = min(width, self.width)
        left = Rect(self.x, self.y, width, self.height)
        right = Rect(self.x + width, self.y, self.width - width, self.height)
        return left, right


@dataclass
class Layout:
    """The live console and the UI panels derived from its current size."""

    # Rows reserved for the bottom HUD bar; the map viewport fills the rest.
    HUD_HEIGHT = 5

    console: tcod.console.Console

    @property
    def hud_height(self) -> int:
        return min(self.HUD_HEIGHT, self.console.height)

    @property
    def map_viewport(self) -> Rect:
        """The map view: everything above the HUD bar. New panels (e.g. a minimap)
        can be carved out of this here without touching the render processors."""
        return Rect(0, 0, self.console.width, max(0, self.console.height - self.hud_height))

    @property
    def hud(self) -> Rect:
        return Rect(
            0,
            self.console.height - self.hud_height,
            self.console.width,
            self.hud_height,
        )

    @property
    def modal_area(self) -> Rect:
        """Menus and modals center over the whole screen."""
        return Rect(0, 0, self.console.width, self.console.height)

    def camera_offset(self, player_x: int, player_y: int, map_width: int, map_height: int) -> tuple[int, int]:
        """The top-left map cell the viewport should show to keep the player
        centered, without ever scrolling past the map edges.

        Each axis is handled the same way: start at the player minus half the
        viewport (which centers the player), then clamp into the range of valid
        offsets, [0, map_size - viewport_size]. When the map is smaller than the
        viewport that range is just [0, 0], so the map sits flush to the top-left.
        """
        view = self.map_viewport
        max_x = max(0, map_width - view.width)
        max_y = max(0, map_height - view.height)
        cam_x = min(max(player_x - view.width // 2, 0), max_x)
        cam_y = min(max(player_y - view.height // 2, 0), max_y)
        return cam_x, cam_y
