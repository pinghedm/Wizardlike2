from typing import TYPE_CHECKING

import esper
import tcod

from components import Position, Renderable
from map_objects import Map
from states import DisplayMode, GameState

if TYPE_CHECKING:
    from data_loaders import AssetLoader


class RenderSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, asset_loader: AssetLoader):
        self.console = console
        self.asset_loader = asset_loader

    def process(self):
        game_state = esper.get_component(GameState)[0][1]

        if game_state.display_mode != DisplayMode.EXPLORING:
            return

        # 1. Find and render the map
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]
        game_map.render(self.console, self.asset_loader)

        # 2. Render all entities with Position and Renderable components
        for _ent, (pos, rend) in esper.get_components(Position, Renderable):
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
