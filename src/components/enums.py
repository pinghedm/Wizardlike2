import enum
from typing import TYPE_CHECKING

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
    CONFIRM = enum.auto()
    CANCEL = enum.auto()
    CYCLE_TAB = enum.auto()
    SCROLL_UP = enum.auto()
    SCROLL_DOWN = enum.auto()


# A controller binding is the SDL button or trigger axis driving an action.
type ControllerBinding = ControllerButton | ControllerAxis


def default_controller_bindings() -> dict[InputAction, ControllerBinding]:
    """Default gamepad bindings for the rebindable actions. Movement is omitted:
    it is fixed to the d-pad and left stick."""
    return {
        InputAction.CONFIRM: ControllerButton.A,
        InputAction.CANCEL: ControllerButton.B,
        InputAction.OPEN_CASTING: ControllerButton.X,
        InputAction.OPEN_CRAFTING: ControllerButton.Y,
        InputAction.CYCLE_TAB: ControllerButton.RIGHTSHOULDER,
        InputAction.SCROLL_UP: ControllerAxis.TRIGGERLEFT,
        InputAction.SCROLL_DOWN: ControllerAxis.TRIGGERRIGHT,
    }
