import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from data_loaders import _load_enum


class Point(NamedTuple):
    x: int
    y: int


class BehaviorType(enum.Enum):
    CHASE = enum.auto()
    PATROL = enum.auto()
    FLEE = enum.auto()


ItemType = _load_enum('data/ingredients.yaml', 'ingredients', 'ItemType')
SpellType = _load_enum('data/spells.yaml', 'spells', 'SpellType')


@dataclass
class FieldOfView:
    visible_tiles: set[Point] = field(default_factory=set)
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
class Stats:
    hp: int
    max_hp: int


@dataclass
class Inventory:
    items: dict[ItemType, int] = field(default_factory=dict)


@dataclass
class KnownRecipes:
    # Maps a Spell to the set of ingredient combinations discovered for it
    recipes: dict[SpellType, set[tuple[ItemType, ...]]] = field(default_factory=dict)


@dataclass
class SpellInventory:
    # Tracks remaining uses of each spell
    spells: dict[SpellType, int] = field(default_factory=dict)


@dataclass
class MessageLog:
    # A list of messages, where each message is a list of (text, color) segments
    messages: list[list[tuple[str, tuple[int, int, int]]]] = field(default_factory=list)
    scroll_index: int = 0

    def add_message(self, segments: list[tuple[str, tuple[int, int, int]]]):
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
    """Basic AI component."""

    behavior: BehaviorType = BehaviorType.CHASE
    last_known_player_position: Point | None = None


@dataclass
class Enemy:
    """Component for enemy-specific properties."""

    attack_damage: int = 15
    bump_damage: int = 5
    blocks_movement: bool = False


class PlayerTag:
    pass
