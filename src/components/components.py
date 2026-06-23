from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar, NamedTuple

import tcod

from src.components.configs import EnemyConfig, IngredientConfig, NPCConfig, SpellConfig, TileConfig
from src.components.enums import (
    DEFAULT_CONTROLLER_BINDINGS,
    DEFAULT_KEYBOARD_BINDINGS,
    ControllerBinding,
    EffectType,
    InputAction,
    ItemType,
    ShopOfferKind,
    SpellType,
    StatusType,
)
from src.components.utils import Message
from src.states import CraftingView, PostCastBehavior


class Point(NamedTuple):
    x: int
    y: int


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
class DamageModifier:
    """A conditional damage multiplier a spell applies when its target already carries
    a status — an elemental reaction (e.g. lightning hits a WET foe for x2, fire for x0.5).
    `damage_mult` scales the spell's damage: > 1 vulnerability, < 1 resistance. One-shot:
    the triggering status is consumed when the modifier lands.
    """

    vs_status: StatusType
    damage_mult: float


@dataclass
class EnemyAbility:
    """A ranged enemy attack, modeled as a mini-spell: a range plus the same
    list of Effects spells use. Applied to the player via apply_effect."""

    range: int
    effects: list[Effect]


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
    tiles: list[TileConfig]
    enemies: dict[str, EnemyConfig]
    npcs: list[NPCConfig]

    # Index into `spells` by id, built once so lookups don't linear-scan.
    spells_by_id: dict[str, SpellConfig] = field(init=False)

    def __post_init__(self):
        self.spells_by_id = {s['id']: s for s in self.spells}


@dataclass
class Keybindings:
    """Keyboard and controller input bindings (an attribute of the Settings singleton)."""

    bindings: dict[InputAction, tcod.event.KeySym] = field(default_factory=DEFAULT_KEYBOARD_BINDINGS.copy)
    controller: dict[InputAction, ControllerBinding] = field(default_factory=DEFAULT_CONTROLLER_BINDINGS.copy)

    def __setstate__(self, state: dict[str, object]) -> None:
        self.__dict__.update(state)
        self.__dict__.setdefault('controller', DEFAULT_CONTROLLER_BINDINGS.copy())


@dataclass
class Settings:
    """Singleton component for persistent player preferences (input bindings + behavior)."""

    keybindings: Keybindings = field(default_factory=Keybindings)
    post_cast: PostCastBehavior = PostCastBehavior.STAY
    music_volume: float = 1.0
    sfx_volume: float = 1.0
    muted: bool = False


@dataclass
class MetaSaveState:
    """Singleton flag: cross-run progression (gold) changed in-world and is awaiting a
    flush to disk. The MetaSaveSystem writes it at the next paused moment, coalescing a
    burst of gold pickups into one write instead of touching disk on every step."""

    dirty: bool = False


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
class Experience:
    """Player progression. XP accrues from casting spells and slaying enemies; crossing a
    level threshold raises max HP and heals to full. `xp` counts toward the next level only
    (it resets on level-up); the threshold grows with `level`. Created fresh per run."""

    LEVEL_XP: ClassVar[int] = 100  # XP to advance one level, times the current level
    HP_PER_LEVEL: ClassVar[int] = 20  # max HP gained on level-up

    xp: int = 0
    level: int = 1

    @property
    def next_level_xp(self) -> int:
        """XP required to advance from the current level to the next."""
        return self.level * self.LEVEL_XP


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


@dataclass
class SpellMastery:
    """Per-spell mastery, grown by casting and persisted across runs (like the grimoire).
    Holds only the accumulated cast count per spell; the rank it maps to and the bonuses it
    confers come from each spell's own `mastery` config (see SpellMasteryConfig)."""

    casts: dict[SpellType, int] = field(default_factory=dict[SpellType, int])


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
    """A centered, time-pausing text box. `pages` are shown one at a time; each Confirm
    advances `page`, and Confirm on the last page runs `on_close` and dismisses the modal."""

    pages: list[str]
    title: str = 'Message'
    width: int = 40
    height: int = 10
    on_close: Callable[[], None] | None = None
    page: int = 0


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
    xp_reward: int = 0


@dataclass
class TargetingReticle:
    """Tracks the spell targeting reticle: the tile it sits on (and shows the AoE radius
    of) and `target_ent`, the locked-on enemy it follows."""

    x: int
    y: int
    radius: int
    target_ent: int | None = None


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
class NPC:
    """A non-hostile character; press Confirm while adjacent to read their dialogue,
    one page at a time."""

    name: str
    dialogue: list[str] = field(default_factory=list[str])


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
