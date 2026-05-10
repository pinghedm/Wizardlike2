import esper
import tcod
from components import PlayerTag, Position, Renderable
from map_objects import Map
from states import DisplayMode, GameState


class RenderSystem(esper.Processor):
    def __init__(self, console: tcod.console.Console, game_map: Map, asset_loader: 'AssetLoader'):
        self.console = console
        self.game_map = game_map
        self.asset_loader = asset_loader

    def process(self):
        game_state = esper.get_component(GameState)[0][1]
        
        if game_state.display_mode != DisplayMode.EXPLORING:
            return

        # 1. Render the map first
        self.game_map.render(self.console, self.asset_loader)

        # 2. Render all entities with Position and Renderable components
        for ent, (pos, rend) in esper.get_components(Position, Renderable):
            codepoint = self.asset_loader.get_codepoint(rend.sprite_id)
            
            # Draw the entity using the assigned codepoint and stored color
            self.console.print(
                x=pos.x,
                y=pos.y,
                string=chr(codepoint),
                fg=rend.color
            )

class MovementSystem(esper.Processor):
    def __init__(self, game_map: Map):
        self.game_map = game_map

    def move_entity(self, entity: int, dx: int, dy: int):
        pos = esper.component_for_entity(entity, Position)
        new_x = pos.x + dx
        new_y = pos.y + dy

        if self.game_map.is_walkable(new_x, new_y):
            pos.x = new_x
            pos.y = new_y
