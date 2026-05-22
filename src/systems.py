from typing import TYPE_CHECKING

import esper
import tcod
import tcod.map
from tcod import libtcodpy

from components import FieldOfView, PlayerTag, Point, Position, Renderable
from map_objects import Map
from states import DisplayMode, GameState

if TYPE_CHECKING:
    from data_loaders import AssetLoader


class FOVSystem(esper.Processor):
    def process(self):
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        for _ent, (pos, fov) in esper.get_components(Position, FieldOfView):
            if fov.dirty:
                fov.visible_tiles = set()
                # compute_fov expects [height, width] or [width, height] depending on order
                # With 'F' order (column-major), it matches our [x][y] structure
                fov_map = tcod.map.compute_fov(
                    transparency=game_map.transparent,
                    pov=(pos.x, pos.y),
                    radius=fov.radius,
                    light_walls=True,
                    algorithm=libtcodpy.FOV_BASIC,
                )

                # Update visible tiles and explored map
                for x in range(game_map.width):
                    for y in range(game_map.height):
                        if fov_map[x, y]:
                            fov.visible_tiles.add(Point(x, y))
                            game_map.explored[x, y] = True

                fov.dirty = False


class RenderSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, asset_loader: AssetLoader):
        self.console = console
        self.asset_loader = asset_loader

    def process(self):
        game_state = esper.get_component(GameState)[0][1]

        if game_state.display_mode != DisplayMode.EXPLORING:
            return

        # 1. Get the Map and Player FOV
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        player_fov = None
        for _ent, (fov, _tag) in esper.get_components(FieldOfView, PlayerTag):
            player_fov = fov
            break

        # 2. Render the map
        for x in range(game_map.width):
            for y in range(game_map.height):
                is_visible = player_fov is not None and Point(x, y) in player_fov.visible_tiles
                is_explored = game_map.explored[x, y]

                if not is_visible and not is_explored:
                    continue

                tile = game_map.tiles[x][y]
                codepoint = self.asset_loader.get_codepoint(tile.sprite_id)
                fg = tile.fg
                bg = tile.bg

                if not is_visible:
                    # Dim the colors for explored but not visible tiles
                    fg = tuple(int(c * 0.3) for c in fg)
                    bg = tuple(int(c * 0.3) for c in bg)

                self.console.print(x=x, y=y, string=chr(codepoint), fg=fg, bg=bg)

        # 3. Render all entities with Position and Renderable components that are visible
        for _ent, (pos, rend) in esper.get_components(Position, Renderable):
            if player_fov is not None and pos.point not in player_fov.visible_tiles:
                continue

            codepoint = self.asset_loader.get_codepoint(rend.sprite_id)
            self.console.print(x=pos.x, y=pos.y, string=chr(codepoint), fg=rend.color)


def move_entity(entity: int, dx: int, dy: int):
    pos = esper.component_for_entity(entity, Position)
    new_x = pos.x + dx
    new_y = pos.y + dy

    maps = esper.get_component(Map)
    if maps:
        game_map = maps[0][1]
        if game_map.is_walkable(new_x, new_y):
            pos.x = new_x
            pos.y = new_y

            # If the entity has a FieldOfView, mark it as dirty
            if esper.has_component(entity, FieldOfView):
                fov = esper.component_for_entity(entity, FieldOfView)
                fov.dirty = True
