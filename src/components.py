from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple

from data_loaders import _load_enum


class Point(NamedTuple):
    x: int
    y: int


ItemType = _load_enum('data/ingredients.yaml', 'ingredients', 'ItemType')
SpellType = _load_enum('data/spells.yaml', 'spells', 'SpellType')


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


class PlayerTag:
    pass
