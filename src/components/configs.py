from typing import TYPE_CHECKING, NotRequired, TypedDict

if TYPE_CHECKING:
    from src.components.components import BossAbility, DamageModifier, Effect, LootDrop
    from src.components.enums import EffectType, ItemType, TargetMode, TileType


class RecipeConfig(TypedDict):
    # Stored as a sorted tuple (see load_spells_config) so it's hashable and can key
    # the discovered-recipe sets in KnownRecipes.
    ingredients: tuple[ItemType, ...]
    charges: int


class SpellMasteryConfig(TypedDict):
    """Per-spell mastery tuning. Casting the spell accrues mastery; each rank (up to
    `max_rank`, costing progressively more casts) grants bonus charges on refill/craft and
    scales the spell's effect power."""

    casts_per_rank: int  # casts for rank 1; each later rank costs progressively more
    max_rank: int
    charge_bonus_per_rank: int
    power_per_rank: float


class SpellConfig(TypedDict):
    id: str
    name: str
    description: NotRequired[str]
    target: TargetMode
    radius: int
    effects: list[Effect]
    modifiers: NotRequired[list[DamageModifier]]
    recipes: list[RecipeConfig]
    shop: NotRequired[ShopConfig]
    rare: NotRequired[bool]
    basic: NotRequired[bool]
    charges: NotRequired[int]  # a basic spell's per-floor charge capacity
    mastery: NotRequired[SpellMasteryConfig]
    momentum_damage_per_stack: NotRequired[float]  # damage bonus per momentum stack (combo)


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
    type: TileType  # a `trap` is a concealed hazard; concealment is derived from the type
    char: str | None
    fg: list[int] | None
    bg: list[int] | None
    depth: list[int]
    effects: NotRequired[list[Effect]]  # on-enter payload for hazard/trap tiles


class EnemyConfig(TypedDict):
    id: str
    color: list[int]
    hp: int
    damage: int
    speed: int
    xp: int
    behavior: str
    floors: list[int]
    blocks_movement: NotRequired[bool]
    guardian: NotRequired[bool]
    boss: NotRequired[bool]  # implies the exit-seal; carries a phase-gated `abilities` set
    abilities: NotRequired[list[BossAbility]]
    effect_multipliers: NotRequired[dict[EffectType, float]]  # incoming-effect resist/immune/vuln
    drops: NotRequired[list[LootDrop]]


class NPCConfig(TypedDict):
    id: str
    name: str
    floor: int
    dialogue: list[str]
    color: NotRequired[list[int]]


class GameConfigs(TypedDict):
    """The bundle of parsed config returned by `get_game_configs`, used to build the
    `Configuration` singleton."""

    ingredients: dict[ItemType, IngredientConfig]
    spells: list[SpellConfig]
    tiles: list[TileConfig]
    enemies: dict[str, EnemyConfig]
    npcs: list[NPCConfig]
