"""Screen layout: panel geometry and the camera transform.

`Layout` owns the live tcod console and derives its panel rects from the console
size, so a window resize is just swapping in the new console — the rects follow.
It is injected into the render processors rather than queried from the ECS: the
render target is infrastructure, not game state, and this also lets it survive the
clear_database() done on new game / load. `Rect` is a plain value type.
"""

from dataclasses import dataclass

import esper
import tcod.console

from src.constants import TILE_SCALE


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
    HUD_HEIGHT = 7

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

    @property
    def viewport_tiles(self) -> tuple[int, int]:
        """How many map tiles fit across the viewport, given each tile is drawn as a
        TILE_SCALE x TILE_SCALE block of console cells."""
        view = self.map_viewport
        return view.width // TILE_SCALE, view.height // TILE_SCALE

    # Minimap panel width as a fraction of the viewport, clamped to this cell range.
    MINIMAP_MIN_W = 14
    MINIMAP_MAX_W = 28

    def minimap_rect(self, map_width: int, map_height: int) -> Rect:
        """The minimap panel, carved from the top-right of the map viewport. Its width is
        a fraction of the viewport (clamped); its interior height tracks the map's aspect
        ratio so the downscaled level isn't stretched. The 1-cell frame accounts for the
        +2/-2 between the outer panel and its interior."""
        view = self.map_viewport
        width = min(self.MINIMAP_MAX_W, max(self.MINIMAP_MIN_W, view.width // 4))
        interior_h = max(1, round((width - 2) * map_height / map_width))
        height = interior_h + 2
        return Rect(view.x + view.width - width, view.y, width, height)

    def camera_offset(self, player_x: int, player_y: int, map_width: int, map_height: int) -> tuple[int, int]:
        """The top-left map tile the viewport should show to keep the player
        centered, without ever scrolling past the map edges.

        Each axis is handled the same way: start at the player minus half the
        visible tile span (which centers the player), then clamp into the range of
        valid offsets, [0, map_size - tiles_visible]. When the map is smaller than the
        view that range is just [0, 0], so the map sits flush to the top-left.
        """
        tiles_x, tiles_y = self.viewport_tiles
        max_x = max(0, map_width - tiles_x)
        max_y = max(0, map_height - tiles_y)
        cam_x = min(max(player_x - tiles_x // 2, 0), max_x)
        cam_y = min(max(player_y - tiles_y // 2, 0), max_y)
        return cam_x, cam_y

    def map_to_screen(self, map_x: int, map_y: int, cam_x: int, cam_y: int) -> tuple[int, int]:
        """Convert a map tile to the top-left console cell of its TILE_SCALE-sized
        block, for the given camera offset (from `camera_offset`). The result may fall
        outside `map_viewport`; callers that need to clip should test it with
        `map_viewport.contains`."""
        view = self.map_viewport
        return view.x + (map_x - cam_x) * TILE_SCALE, view.y + (map_y - cam_y) * TILE_SCALE


class LayoutProcessor(esper.Processor):
    """Base for render processors that draw into the injected `Layout`'s console.

    Holds the shared layout reference and exposes its live console, so subclasses
    only implement `process()`."""

    def __init__(self, layout: Layout):
        self.layout = layout

    @property
    def console(self) -> tcod.console.Console:
        return self.layout.console
