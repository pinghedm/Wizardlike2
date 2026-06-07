import enum
from typing import TYPE_CHECKING

import tcod.event
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src.constants import DATA_DIR
from src.data_utils import load_str_enum_from_yaml


class StatusType(enum.StrEnum):
    SLOW = 'slow'
    HASTE = 'haste'
    POISON = 'poison'
    REGEN = 'regen'
    STUN = 'stun'
    SHIELD = 'shield'
    WET = 'wet'


class EffectType(enum.StrEnum):
    DAMAGE = 'damage'
    HEAL = 'heal'
    SLOW = 'slow'
    HASTE = 'haste'
    POISON = 'poison'
    REGEN = 'regen'
    STUN = 'stun'
    SHIELD = 'shield'
    DRAIN = 'drain'
    KNOCKBACK = 'knockback'
    WET = 'wet'


class ShopOfferKind(enum.StrEnum):
    INGREDIENT = 'ingredient'
    SPELL = 'spell'
    HEAL = 'heal'


class TargetMode(enum.StrEnum):
    """Who a spell is aimed at: the caster (self-cast, skips targeting) or an enemy."""

    SELF = 'self'
    ENEMY = 'enemy'


if TYPE_CHECKING:
    # The real enums are built from YAML at runtime (below); these stubs exist only so
    # the type checker knows the members the code references by name.
    class ItemType(enum.StrEnum):
        GOLD = 'gold'

    class SpellType(enum.StrEnum):
        pass

else:
    ItemType = load_str_enum_from_yaml('ItemType', f'{DATA_DIR}/ingredients.yaml', 'ingredients')
    SpellType = load_str_enum_from_yaml('SpellType', f'{DATA_DIR}/spells.yaml', 'spells')

    # These enums are built dynamically inside data_utils, and live in this submodule, but
    # bind their __module__ to the `src.components` package (which re-exports them) so pickle
    # resolves members by reference (e.g. src.components.ItemType) when loading a saved game.
    ItemType.__module__ = 'src.components'
    SpellType.__module__ = 'src.components'


class InputAction(enum.Enum):
    """Logical input actions that keyboard keys and controller buttons map to."""

    MOVE_UP = enum.auto()
    MOVE_DOWN = enum.auto()
    MOVE_LEFT = enum.auto()
    MOVE_RIGHT = enum.auto()
    OPEN_CRAFTING = enum.auto()
    OPEN_CASTING = enum.auto()
    OPEN_MENU = enum.auto()  # open the pause menu (exploring); also backs out of a submenu
    CONFIRM = enum.auto()
    CANCEL = enum.auto()  # back out of a submenu; a no-op on the map (never opens the menu)
    CYCLE_TAB = enum.auto()
    SCROLL_UP = enum.auto()
    SCROLL_DOWN = enum.auto()
    # Quick-cast a spell by its slot, skipping the picker (keyboard 1-9, controller LB + face).
    QUICK_CAST_1 = enum.auto()
    QUICK_CAST_2 = enum.auto()
    QUICK_CAST_3 = enum.auto()
    QUICK_CAST_4 = enum.auto()
    QUICK_CAST_5 = enum.auto()
    QUICK_CAST_6 = enum.auto()
    QUICK_CAST_7 = enum.auto()
    QUICK_CAST_8 = enum.auto()
    QUICK_CAST_9 = enum.auto()


# Quick-cast actions in slot order, so a slot index is QUICK_CAST_ACTIONS.index(action).
QUICK_CAST_ACTIONS = (
    InputAction.QUICK_CAST_1,
    InputAction.QUICK_CAST_2,
    InputAction.QUICK_CAST_3,
    InputAction.QUICK_CAST_4,
    InputAction.QUICK_CAST_5,
    InputAction.QUICK_CAST_6,
    InputAction.QUICK_CAST_7,
    InputAction.QUICK_CAST_8,
    InputAction.QUICK_CAST_9,
)


# A controller binding is the SDL button or trigger axis driving an action.
type ControllerBinding = ControllerButton | ControllerAxis


# Default bindings for the rebindable actions.
# Movement is omitted from the controller map: it is fixed to the d-pad and left stick.
DEFAULT_KEYBOARD_BINDINGS: dict[InputAction, tcod.event.KeySym] = {
    InputAction.MOVE_UP: tcod.event.KeySym.UP,
    InputAction.MOVE_DOWN: tcod.event.KeySym.DOWN,
    InputAction.MOVE_LEFT: tcod.event.KeySym.LEFT,
    InputAction.MOVE_RIGHT: tcod.event.KeySym.RIGHT,
    InputAction.OPEN_CRAFTING: tcod.event.KeySym.C,
    InputAction.OPEN_CASTING: tcod.event.KeySym.S,
    InputAction.OPEN_MENU: tcod.event.KeySym.ESCAPE,
    InputAction.CONFIRM: tcod.event.KeySym.RETURN,
    InputAction.CYCLE_TAB: tcod.event.KeySym.TAB,
    InputAction.SCROLL_UP: tcod.event.KeySym.PAGEUP,
    InputAction.SCROLL_DOWN: tcod.event.KeySym.PAGEDOWN,
}

DEFAULT_CONTROLLER_BINDINGS: dict[InputAction, ControllerBinding] = {
    InputAction.CONFIRM: ControllerButton.A,
    InputAction.CANCEL: ControllerButton.B,
    InputAction.OPEN_CASTING: ControllerButton.X,
    InputAction.OPEN_CRAFTING: ControllerButton.Y,
    InputAction.CYCLE_TAB: ControllerButton.RIGHTSHOULDER,
    InputAction.SCROLL_UP: ControllerAxis.TRIGGERLEFT,
    InputAction.SCROLL_DOWN: ControllerAxis.TRIGGERRIGHT,
}
