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
class Modal:
    message: str
    width: int = 40
    height: int = 10
    on_close: Callable[[], None] | None = None


class PlayerTag:
    pass
