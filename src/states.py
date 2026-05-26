import enum
from dataclasses import dataclass


class DisplayMode(enum.Enum):
    EXPLORING = enum.auto()
    MENU = enum.auto()
    COMBINING = enum.auto()
    CASTING = enum.auto()
    TARGETING = enum.auto()
    SETTINGS = enum.auto()
    LOADING_SAVE = enum.auto()
    STARTING_NEW_GAME = enum.auto()
    SAVING = enum.auto()
    EXITING = enum.auto()


class MenuOption(enum.StrEnum):
    NEW_GAME = 'New Game'
    CONTINUE = 'Continue'
    RESUME = 'Resume'
    SAVE = 'Save'
    LOAD = 'Load'
    SETTINGS = 'Settings'
    QUIT = 'Quit'


# Shown at startup, when no game is running.
TITLE_MENU_OPTIONS = [
    MenuOption.NEW_GAME,
    MenuOption.CONTINUE,
    MenuOption.QUIT,
]

# Shown in-game (pause menu), when a player entity exists.
PAUSE_MENU_OPTIONS = [
    MenuOption.RESUME,
    MenuOption.SAVE,
    MenuOption.LOAD,
    MenuOption.SETTINGS,
    MenuOption.QUIT,
]


@dataclass
class GameState:
    display_mode: DisplayMode = DisplayMode.EXPLORING
    floor: int = 1
    time_paused: bool = False
