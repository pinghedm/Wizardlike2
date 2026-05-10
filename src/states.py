from dataclasses import dataclass
import enum

class DisplayMode(enum.Enum):
    EXPLORING = enum.auto()
    COMBINING = enum.auto()

@dataclass
class GameState:
    display_mode: DisplayMode = DisplayMode.EXPLORING
    floor: int = 1
