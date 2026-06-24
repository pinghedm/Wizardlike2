"""Explored-area maps: a small, translucent always-on corner minimap and a full-screen
overview (DisplayMode.MAP_VIEW), both drawn by the same fill at different sizes.

We render the explored open space (walkable floor) as the lit ink, leaving walls and the
unknown dark — so a 1-wide corridor reads as a lit path rather than vanishing between two
walls (rendering walls instead loses thin gaps at this resolution). To squeeze more detail
out of a small panel, each cell packs a 2x2 grid of sub-cells via quadrant block glyphs,
lit wherever the sampled region holds explored floor.

The corner minimap is translucent: instead of an opaque box, it dims the dungeon already
drawn behind it — both glyph (fg) and background (bg) — so the live view shows through in
the gaps, then overlays the bright paths on top.
"""

import esper
import tcod.console

from src.components import Guardian, Position
from src.constants import (
    UI_BLACK,
    UI_GRAY,
    UI_GRAY_DARK,
    UI_GRAY_MID,
    UI_GREEN_BRIGHT,
    UI_ORANGE,
    UI_YELLOW,
    to_rgb,
)
from src.ecs_helpers import exit_is_sealed, get_player_component, get_singleton, try_get_singleton
from src.layout import Layout, LayoutProcessor
from src.map_objects import Map
from src.states import WORLD_VIEW_MODES, DisplayMode, GameState
from src.ui_helpers import blend, draw_titled_frame

# The 2x2 sub-cell offsets (top-left, top-right, bottom-left, bottom-right) and the block
# glyph for each 4-bit fill mask built from them, so QUADRANTS[mask] fills exactly those cells.
_SUBCELLS = ((0, 0), (1, 0), (0, 1), (1, 1))
_QUADRANTS = ' ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█'


def _to_cell(map_x: int, map_y: int, cols: int, rows: int, game_map: Map) -> tuple[int, int]:
    """Map-tile (map_x, map_y) to its column/row within a cols x rows minimap panel."""
    return min(cols - 1, map_x * cols // game_map.width), min(rows - 1, map_y * rows // game_map.height)


def _explored_mask_grid(cols: int, rows: int, game_map: Map) -> list[int]:
    """The per-cell 4-bit quadrant fill masks (row-major, length cols*rows) for `game_map`'s
    explored open space downsampled onto a cols x rows panel via 2x2 sub-cells. This is the
    expensive part of drawing a minimap, so callers on the per-frame path cache the result."""
    sub_cols, sub_rows = cols * 2, rows * 2
    masks = [0] * (cols * rows)
    for cy in range(rows):
        for cx in range(cols):
            mask = 0
            for bit, (qx, qy) in enumerate(_SUBCELLS):
                sx, sy = cx * 2 + qx, cy * 2 + qy
                mx0 = sx * game_map.width // sub_cols
                my0 = sy * game_map.height // sub_rows
                # Keep the sampled region at least 1 tile wide even when sub-cells are finer
                # than tiles (a small map in a big panel), so the slice is never empty.
                mx1 = max(mx0 + 1, (sx + 1) * game_map.width // sub_cols)
                my1 = max(my0 + 1, (sy + 1) * game_map.height // sub_rows)
                if (game_map.explored[mx0:mx1, my0:my1] & game_map.walkable[mx0:mx1, my0:my1]).any():
                    mask |= 1 << bit
            masks[cy * cols + cx] = mask
    return masks


def _draw_explored(
    console: tcod.console.Console,
    x0: int,
    y0: int,
    cols: int,
    rows: int,
    masks: list[int],
    game_map: Map,
    player_pos: Position | None,
) -> None:
    """Draw the explored-path quadrant glyphs from `masks`, then the live markers over them."""
    if cols < 1 or rows < 1:
        return
    for cy in range(rows):
        for cx in range(cols):
            mask = masks[cy * cols + cx]
            if mask:
                console.print(x0 + cx, y0 + cy, _QUADRANTS[mask], fg=UI_GRAY)

    # Markers, drawn over the paths but only on explored tiles so they don't reveal unseen
    # ground: living guardians, then the exit (dim while they seal it, bright once cleared),
    # and the player on top.
    for _ent, (pos, _guardian) in esper.get_components(Position, Guardian):
        if game_map.explored[pos.x, pos.y]:
            gx, gy = _to_cell(pos.x, pos.y, cols, rows, game_map)
            console.print(x0 + gx, y0 + gy, 'G', fg=UI_ORANGE)

    if game_map.exit_pos is not None and game_map.explored[game_map.exit_pos]:
        ex, ey = _to_cell(*game_map.exit_pos, cols, rows, game_map)
        console.print(x0 + ex, y0 + ey, '>', fg=UI_GRAY_DARK if exit_is_sealed() else UI_YELLOW)

    if player_pos is not None:
        px, py = _to_cell(player_pos.x, player_pos.y, cols, rows, game_map)
        console.print(x0 + px, y0 + py, '@', fg=UI_GREEN_BRIGHT)


def _fill_explored(
    console: tcod.console.Console, x0: int, y0: int, cols: int, rows: int, game_map: Map, player_pos: Position | None
) -> None:
    """Fill a cols x rows region at (x0, y0) with the explored open space of `game_map`, plus
    markers, downsampling the map onto it via 2x2 quadrant sub-cells. Recomputes the masks each
    call — for the full-screen map view, which opens infrequently."""
    if cols < 1 or rows < 1:
        return
    masks = _explored_mask_grid(cols, rows, game_map)
    _draw_explored(console, x0, y0, cols, rows, masks, game_map, player_pos)


class MinimapSystem(LayoutProcessor):
    """The always-on corner minimap, drawn translucently over the world view."""

    # How far to fade the dungeon behind the minimap toward black: 0 leaves the live view at
    # full brightness, 1 is an opaque black panel. The explored paths draw bright on top.
    BACKDROP_FADE = 0.7

    def __init__(self, layout: Layout):
        super().__init__(layout)
        # The explored-path fill costs several ms, but it only changes as the player explores.
        # Cache it, recomputing when the floor's map, the panel size, or the explored-cell
        # count changes; the markers and translucent backdrop still redraw every frame.
        self._cached_map: Map | None = None
        self._cached_size: tuple[int, int] = (0, 0)
        self._cached_explored: int = -1
        self._masks: list[int] = []

    def _masks_for(self, game_map: Map, cols: int, rows: int) -> list[int]:
        explored_count = int(game_map.explored.sum())
        if (
            game_map is not self._cached_map
            or (cols, rows) != self._cached_size
            or explored_count != self._cached_explored
        ):
            self._cached_map = game_map
            self._cached_size = (cols, rows)
            self._cached_explored = explored_count
            self._masks = _explored_mask_grid(cols, rows, game_map)
        return self._masks

    def process(self):
        if get_singleton(GameState).display_mode not in WORLD_VIEW_MODES:
            return
        game_map = try_get_singleton(Map)
        if game_map is None:
            return
        rect = self.layout.minimap_rect(game_map.width, game_map.height)
        view = self.layout.map_viewport
        if rect.width < 3 or rect.height < 3 or rect.y + rect.height > view.y + view.height:
            return

        masks = self._masks_for(game_map, rect.width, rect.height)

        # Translucency: blend the dungeon already drawn here toward black in place (the same
        # blend-over-the-console approach the combat overlays use), keeping its glyphs faintly
        # visible, then overlay the explored paths on top.
        for y in range(rect.y, rect.y + rect.height):
            for x in range(rect.x, rect.x + rect.width):
                cell = self.console.rgb[y, x]
                cell['fg'] = blend(to_rgb(cell['fg']), UI_BLACK, self.BACKDROP_FADE)
                cell['bg'] = blend(to_rgb(cell['bg']), UI_BLACK, self.BACKDROP_FADE)
        _draw_explored(
            self.console, rect.x, rect.y, rect.width, rect.height, masks, game_map, get_player_component(Position)
        )


class MapViewSystem(LayoutProcessor):
    """The full-screen map overview (DisplayMode.MAP_VIEW), large enough to resolve corridors."""

    def process(self):
        if get_singleton(GameState).display_mode != DisplayMode.MAP_VIEW:
            return
        game_map = try_get_singleton(Map)
        if game_map is None:
            return
        area = self.layout.modal_area
        draw_titled_frame(
            self.console, area.x, area.y, area.width, area.height, title='Map', fg=UI_GRAY_MID, bg=UI_BLACK
        )
        _fill_explored(
            self.console,
            area.x + 1,
            area.y + 1,
            area.width - 2,
            area.height - 2,
            game_map,
            get_player_component(Position),
        )
