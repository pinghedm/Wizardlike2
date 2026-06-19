import enum
from dataclasses import dataclass


class DisplayMode(enum.Enum):
    """A screen the player is currently looking at. An input handler returns one to switch
    screens."""

    EXPLORING = enum.auto()
    MENU = enum.auto()
    COMBINING = enum.auto()
    CASTING = enum.auto()
    TARGETING = enum.auto()
    SHOPPING = enum.auto()
    SETTINGS = enum.auto()
    GAME_OVER = enum.auto()
    MAP_VIEW = enum.auto()  # full-screen overview of discovered walls


class PendingTransition(enum.Enum):
    """A world-level command an input handler queues for the main loop to carry out after
    it runs (see apply_pending_transition)."""

    NEW_GAME = enum.auto()
    LOAD_SAVE = enum.auto()
    SAVE = enum.auto()
    RETURN_TO_TITLE = enum.auto()
    EXIT = enum.auto()


# An input handler's return value: either the screen to show next (DisplayMode) or a
# one-shot world command for the main loop to run (PendingTransition).
HandlerResult = DisplayMode | PendingTransition


# Display modes that draw the dungeon view (map, entities, HUD). The crafting/casting/
# targeting/shop overlays all render on top of the live map, so the map and HUD draw
# behind them too; the menu, settings, and game-over screens replace the view entirely.
WORLD_VIEW_MODES = (
    DisplayMode.EXPLORING,
    DisplayMode.CASTING,
    DisplayMode.COMBINING,
    DisplayMode.TARGETING,
    DisplayMode.SHOPPING,
)


class CraftingView(enum.StrEnum):
    """Sub-views of the crafting screen, toggled with Tab."""

    EXPERIMENT = 'experiment'  # combine ingredients by hand to discover recipes
    SPELLBOOK = 'spellbook'  # browse known recipes and re-craft them


class PostCastBehavior(enum.StrEnum):
    """What the targeting screen does after a spell is cast (a user preference)."""

    STAY = 'stay'  # keep aiming the same spell, so it can be fired again at once
    RESELECT = 'reselect'  # back to the spell picker
    EXPLORE = 'explore'  # back to the map


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
