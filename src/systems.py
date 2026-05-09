import esper
import tcod
from components import Position, Renderable, PlayerTag
from map_objects import Map
from states import GameState

class RenderSystem(esper.Processor):
    def __init__(self, console: tcod.Console, game_map: Map):
        self.console = console
        self.game_map = game_map
        self.state = GameState.EXPLORING

    def process(self):
        if self.state != GameState.EXPLORING:
            return

        # 1. Render the map first
        self.game_map.render(self.console)

        # 2. Render all entities with Position and Renderable components
        for ent, (pos, rend) in esper.get_components(Position, Renderable):
            self.console.print(
                x=pos.x,
                y=pos.y,
                string=rend.char,
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
