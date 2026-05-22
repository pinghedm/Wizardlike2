import enum
from dataclasses import dataclass


class DisplayMode(enum.Enum):
    EXPLORING = enum.auto()
    MENU = enum.auto()
    COMBINING = enum.auto()


class MenuOption(enum.StrEnum):
    COMBINE = 'Combine'
    QUIT = 'Quit'


MAIN_MENU_OPTIONS = [
    MenuOption.COMBINE,
    MenuOption.QUIT,
]


@dataclass
class GameState:
    display_mode: DisplayMode = DisplayMode.EXPLORING
    floor: int = 1
    time_paused: bool = False
