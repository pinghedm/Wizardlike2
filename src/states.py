import enum

class DisplayMode(enum.Enum):
    EXPLORING = enum.auto()
    COMBINING = enum.auto()

class GameState:
    def __init__(self, floor: int = 1):
        self.display_mode = DisplayMode.EXPLORING
        self.floor = floor
