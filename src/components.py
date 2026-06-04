import enum
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, NamedTuple, NotRequired, TypedDict

import tcod
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src.constants import DATA_DIR
from src.data_utils import load_str_enum_from_yaml
from src.states import CraftingView


class RecipeConfig(TypedDict):
    # Stored as a sorted tuple (see load_spells_config) so it's hashable and can key
    # the discovered-recipe sets in KnownRecipes.
    ingredients: tuple[ItemType, ...]
    charges: int


class SpellConfig(TypedDict):
    id: str
    name: str
    description: NotRequired[str]
    range: int
    radius: int
    effects: list[Effect]
    recipes: list[RecipeConfig]
    shop: NotRequired[ShopConfig]
    rare: NotRequired[bool]


class IngredientConfig(TypedDict):
    id: str
    name: str
    char: str
    color: list[int]
    price: NotRequired[int]


class ShopConfig(TypedDict):
    """A spell's shop listing: gold cost and charges granted per purchase."""

    price: int
    charges: int


class TileConfig(TypedDict):
    id: str
    type: str
    char: str | None
    fg: list[int] | None
    bg: list[int] | None
    depth: list[int]


class EnemyConfig(TypedDict):
    id: str
    color: list[int]
    hp: int
    damage: int
    speed: int
    behavior: str
    floors: list[int]
    blocks_movement: NotRequired[bool]
    guardian: NotRequired[bool]
    drops: NotRequired[list[LootDrop]]


class CharacterConfig(TypedDict):
    id: str


class GameConfigs(TypedDict):
    """The bundle of parsed config returned by `get_game_configs`, used to build the
    `Configuration` singleton."""

    ingredients: dict[ItemType, IngredientConfig]
    spells: list[SpellConfig]
    characters: dict[str, CharacterConfig]
    tiles: list[TileConfig]
    enemies: dict[str, EnemyConfig]


class Point(NamedTuple):
    x: int
    y: int


class StatusType(enum.StrEnum):
    SLOW = 'slow'
    HASTE = 'haste'
    POISON = 'poison'
    REGEN = 'regen'
    STUN = 'stun'
    SHIELD = 'shield'


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


class ShopOfferKind(enum.StrEnum):
    INGREDIENT = 'ingredient'
    SPELL = 'spell'
    HEAL = 'heal'


@dataclass
class Effect:
    """A single spell effect.

    The same object is parsed from YAML and, for effects that linger, stored on
    an entity's StatusEffects. Instant effects (damage/heal) use `power` only;
    markers (slow/haste/stun) use `duration` only; recurring effects (poison/regen)
    and shields use both — `power` per pulse/per hit, `duration` ticking to expiry.
    `lifesteal` is drain-only: HP returned to the caster (knockback uses `power`
    as a tile distance).
    """

    type: EffectType
    duration: int = 0
    power: int = 0
    lifesteal: int = 0


@dataclass
class EnemyAbility:
    """A ranged enemy attack, modeled as a mini-spell: a range plus the same
    list of Effects spells use. Applied to the player via apply_effect."""

    range: int
    effects: list[Effect]


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

    # These enums are built dynamically inside data_utils, so their __module__ points
    # there by default. Bind them to this module so pickle can resolve members by
    # reference (e.g. src.components.ItemType) when loading a saved game.
    ItemType.__module__ = __name__
    SpellType.__module__ = __name__


@dataclass
class FieldOfView:
    visible_tiles: set[Point] = field(default_factory=set[Point])
    radius: int = 8
    dirty: bool = True


@dataclass
class Position:
    x: int
    y: int

    @property
    def point(self) -> Point:
        return Point(self.x, self.y)


@dataclass
class Renderable:
    sprite_id: str
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class Item:
    type: ItemType
    count: int = 1


@dataclass
class LootDrop:
    """One entry in an enemy's loot table; `chance` is a relative weight."""

    type: ItemType
    min: int = 1
    max: int = 1
    chance: float = 1.0


@dataclass
class Loot:
    """What an enemy drops on death: a list of independent LootDrops."""

    drops: list[LootDrop] = field(default_factory=list[LootDrop])


@dataclass
class Configuration:
    """Singleton component to hold game configurations."""

    ingredients: dict[ItemType, IngredientConfig]
    spells: list[SpellConfig]
    characters: dict[str, CharacterConfig]
    tiles: list[TileConfig]
    enemies: dict[str, EnemyConfig]

    # Index into `spells` by id, built once so lookups don't linear-scan.
    spells_by_id: dict[str, SpellConfig] = field(init=False)

    def __post_init__(self):
        self.spells_by_id = {s['id']: s for s in self.spells}


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


@dataclass
class Keybindings:
    """Singleton component to hold gameplay keybindings."""

    bindings: dict[InputAction, tcod.event.KeySym]
    controller: dict[InputAction, ControllerBinding] = field(default_factory=default_controller_bindings)

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self.__dict__.setdefault('controller', default_controller_bindings())


@dataclass
class UIState:
    """Component to store transient UI state like cursors and selections."""

    main_menu_cursor: int = 0
    crafting_cursor: int = 0
    casting_cursor: int = 0
    settings_cursor: int = 0
    remapping_action: InputAction | None = None
    selected_for_crafting: dict[ItemType, int] = field(default_factory=dict[ItemType, int])
    active_targeting_spell_id: str | None = None
    crafting_view: CraftingView = CraftingView.EXPERIMENT
    spellbook_cursor: int = 0
    shop_cursor: int = 0
    shop_quantity: int = 1
    # Label of the most recent controller button pressed, for the Settings readout.
    last_controller_input: str | None = None


@dataclass
class Stats:
    hp: int
    max_hp: int


@dataclass
class Inventory:
    items: dict[ItemType, int] = field(default_factory=dict[ItemType, int])


@dataclass
class KnownRecipes:
    # Maps a Spell to the set of ingredient combinations discovered for it
    recipes: dict[SpellType, set[tuple[ItemType, ...]]] = field(
        default_factory=dict[SpellType, set[tuple[ItemType, ...]]]
    )


@dataclass
class SpellInventory:
    # Tracks remaining uses of each spell
    spells: dict[SpellType, int] = field(default_factory=dict[SpellType, int])


MessageSegment = tuple[str, tuple[int, int, int]]
Message = list[MessageSegment]


@dataclass
class MessageLog:
    # A list of messages, where each message is a list of (text, color) segments
    messages: list[Message] = field(default_factory=list[Message])
    scroll_index: int = 0

    def add_message(self, segments: Message):
        self.messages.append(segments)
        self.scroll_index = 0

    def add_simple_message(self, text: str, color: tuple[int, int, int] = (255, 255, 255)):
        self.add_message([(text, color)])


@dataclass
class Modal:
    message: str
    width: int = 40
    height: int = 10
    on_close: Callable[[], None] | None = None


@dataclass
class Actor:
    """Component for entities that can take actions based on cooldowns."""

    cooldown: int = 0
    speed: int = 100  # Number of ticks between actions


@dataclass
class AI:
    """Marks an AI-driven entity. The active behavior is selected by an
    accompanying tag (ChaseTag / FleeTag / PatrolTag)."""

    last_known_player_position: Point | None = None


class ChaseTag:
    """Behavior tag: pursue the player's last-known position."""


class FleeTag:
    """Behavior tag: flee from the player's last-known position."""


class GuardTag:
    """Behavior tag: hold position; attack only when the player is reachable."""


@dataclass
class PatrolTag:
    """Behavior tag: walk a fixed loop of waypoints."""

    path: list[Point]
    index: int = 0


@dataclass
class Enemy:
    """Component for enemy-specific properties."""

    attack_damage: int = 15
    bump_damage: int = 5
    blocks_movement: bool = False
    ability: EnemyAbility | None = None


@dataclass
class TargetingReticle:
    """Component to track the position of a spell targeting reticle."""

    x: int
    y: int
    range: int
    radius: int


@dataclass
class StatusEffects:
    """Component to track active status effects on an entity."""

    active: dict[StatusType, Effect] = field(default_factory=dict[StatusType, Effect])


@dataclass
class ScreenFlash:
    """A transient color wash over the map viewport (player damage feedback).

    `ticks` counts frames remaining; intensity fades as `ticks / max_ticks`.
    Only one exists at a time — a fresh hit replaces any in-flight flash.
    """

    DURATION: ClassVar[int] = 6  # frames a flash lives at ~30 tps (~0.2s)
    MAX_ALPHA: ClassVar[float] = 0.55  # blend strength at full intensity

    color: tuple[int, int, int]
    ticks: int
    max_ticks: int


@dataclass
class CastVisual:
    """A transient colored burst over a cast spell's impact radius.

    `ticks` counts frames remaining; intensity fades as `ticks / max_ticks`.
    Only one exists at a time.
    """

    DURATION: ClassVar[int] = 8  # frames a burst lives at ~30 tps (~0.27s)
    MAX_ALPHA: ClassVar[float] = 0.6  # blend strength at full intensity

    center: Point
    radius: int
    color: tuple[int, int, int]
    ticks: int
    max_ticks: int


@dataclass
class Projectile:
    """A glyph flying from the caster to a spell's target point.

    Purely cosmetic — the spell's effects already applied on cast. On arrival it
    spawns the impact burst and a particle spray, then is removed. `progress`
    advances from 0 toward 1.0 along start -> target each frame.
    """

    SPEED: ClassVar[float] = 0.5  # cells advanced per frame (~15 cells/s at ~30 tps)

    start: Point
    target: Point
    glyph: str
    color: tuple[int, int, int]
    burst_radius: int
    progress: float = 0.0


@dataclass
class Particle:
    """One short-lived drifting glyph in an impact or hit spray.

    Holds a sub-cell float position so it can move smoothly; drifts by (vx, vy)
    each frame and fades as `ticks / max_ticks`. Drawn foreground-only.
    """

    DURATION: ClassVar[int] = 7  # frames a particle lives
    BURST_COUNT: ClassVar[int] = 8  # particles per impact spray
    HIT_COUNT: ClassVar[int] = 4  # particles per enemy-hit spray

    x: float
    y: float
    vx: float
    vy: float
    glyph: str
    color: tuple[int, int, int]
    ticks: int
    max_ticks: int


class PlayerTag:
    pass


@dataclass
class ShopOffer:
    """One line in the shopkeeper's stock. `purchaseable` is the ingredient or
    spell bought (None for heal); `amount` is the per-unit count, charges, or HP."""

    kind: ShopOfferKind
    price: int
    label: str
    purchaseable: ItemType | SpellType | None = None
    amount: int = 0


@dataclass
class Shopkeeper:
    """A non-hostile vendor; press Confirm while adjacent to trade. Holds the
    stock rolled when this shop floor was generated."""

    offers: list[ShopOffer] = field(default_factory=list[ShopOffer])


@dataclass
class RunStats:
    """Per-run tally shown on the game-over / victory summary. A fresh one is created
    each new run; the deepest floor is read from GameState at display time."""

    enemies_defeated: int = 0
    gold_collected: int = 0
    spells_discovered: int = 0
    damage_dealt: int = 0
    spells_cast: Counter[SpellType] = field(default_factory=Counter[SpellType])
    ingredients_collected: Counter[ItemType] = field(default_factory=Counter[ItemType])
    won: bool = False
