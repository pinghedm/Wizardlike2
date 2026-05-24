import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from src.ai_behaviors import AIBehavior

import tcod

from src.constants import DATA_DIR
from src.data_utils import load_str_enum_from_yaml


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
class Configuration:
    """Singleton component to hold game configurations."""

    ingredients: dict
    spells: list
    characters: dict
    tiles: list
    enemies: dict


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
    selected_for_crafting: dict[ItemType, int] = field(default_factory=dict)
    active_targeting_spell_id: str | None = None


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

    behavior: AIBehavior
    last_known_player_position: Point | None = None


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

    active: dict[StatusType, int] = field(default_factory=dict)


class PlayerTag:
    pass
