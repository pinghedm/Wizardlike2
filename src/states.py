import enum
from dataclasses import dataclass


class DisplayMode(enum.Enum):
    EXPLORING = enum.auto()
    MENU = enum.auto()
    COMBINING = enum.auto()
    CASTING = enum.auto()
    TARGETING = enum.auto()


class MenuOption(enum.StrEnum):
    QUIT = 'Quit'


MAIN_MENU_OPTIONS = [
    MenuOption.QUIT,
]


@dataclass
class GameState:
    display_mode: DisplayMode = DisplayMode.EXPLORING
    floor: int = 1
    time_paused: bool = False
