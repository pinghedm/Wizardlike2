import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, TypedDict

if TYPE_CHECKING:
    from src.data_loaders import SpriteDefinition

import tcod

from src.constants import DATA_DIR
from src.data_utils import load_str_enum_from_yaml


class EffectConfig(TypedDict):
    type: EffectType
    power: int | None
    duration: int | None


class RecipeConfig(TypedDict):
    ingredients: list[ItemType]
    charges: int


class SpellConfig(TypedDict):
    id: str
    name: str
    range: int
    radius: int
    effects: list[EffectConfig]
    recipes: list[RecipeConfig]


class IngredientConfig(TypedDict):
    id: str
    name: str
    char: str
    color: list[int]


class TileConfig(TypedDict):
    id: str
    type: str
    char: str | None
    fg: list[int] | None
    bg: list[int] | None
    depth: list[int]
    sprite: SpriteDefinition | None


class EnemyConfig(TypedDict):
    id: str
    sprite: SpriteDefinition
    color: list[int]
    hp: int
    damage: int
    speed: int
    behavior: str
    floors: list[int]


class CharacterConfig(TypedDict):
    id: str
    sprite: SpriteDefinition


class Point(NamedTuple):
    x: int
    y: int


class StatusType(enum.StrEnum):
    SLOW = 'slow'


class EffectType(enum.StrEnum):
    DAMAGE = 'damage'
    HEAL = 'heal'
    SLOW = 'slow'


if TYPE_CHECKING:

    class ItemType(enum.StrEnum):
        pass

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


@dataclass
class Keybindings:
    """Singleton component to hold gameplay keybindings."""

    bindings: dict[str, tcod.event.KeySym]


@dataclass
class UIState:
    """Component to store transient UI state like cursors and selections."""

    main_menu_cursor: int = 0
    crafting_cursor: int = 0
    casting_cursor: int = 0
    settings_cursor: int = 0
    remapping_action: str | None = None
    selected_for_crafting: dict[ItemType, int] = field(default_factory=dict[ItemType, int])
    active_targeting_spell_id: str | None = None


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

    active: dict[StatusType, int] = field(default_factory=dict[StatusType, int])


class PlayerTag:
    pass
