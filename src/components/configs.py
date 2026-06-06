from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from src.components.components import DamageModifier, Effect, LootDrop
    from src.components.enums import ItemType


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
    modifiers: NotRequired[list[DamageModifier]]
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


class GameConfigs(TypedDict):
    """The bundle of parsed config returned by `get_game_configs`, used to build the
    `Configuration` singleton."""

    ingredients: dict[ItemType, IngredientConfig]
    spells: list[SpellConfig]
    tiles: list[TileConfig]
    enemies: dict[str, EnemyConfig]
