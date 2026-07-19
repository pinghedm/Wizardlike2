from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import NotRequired, TypedDict

import pygame
import yaml

from src.audio import MusicFiles, MusicTrack, SoundFile, SoundId, SoundSpecs, SynthSpec, Waveform
from src.components import (
    BossAbility,
    DamageModifier,
    Effect,
    EffectType,
    EnemyAbility,
    EnemyConfig,
    GameConfigs,
    IngredientConfig,
    ItemType,
    LootDrop,
    NPCConfig,
    RecipeConfig,
    SpellConfig,
    StatusType,
    TargetMode,
    TileConfig,
    TileType,
)
from src.constants import DATA_DIR, FONT_FILE, RGB, UI_WHITE
from src.debug import debug_log


class AssetType(Enum):
    FILE = auto()
    REGION = auto()


class _RawSprite(TypedDict):
    """A sprite as authored in YAML, before the AssetLoader parses it into a
    SpriteDefinition. Loader-internal: the rest of the app references sprites by id."""

    path: str
    type: NotRequired[str]
    region: NotRequired[list[int]]
    scale: NotRequired[float]


class _RenderableConfig(TypedDict):
    """The renderable slice every content config shares: an external 'sprite' or, failing
    that, a font 'char'. The shape `register_from_config` reads to register either."""

    sprite: NotRequired[_RawSprite]
    char: NotRequired[str]


@dataclass
class SpriteDefinition:
    # If path is None, this is a font character, and codepoint is the direct Unicode value.
    path: str | None = None
    type: AssetType | None = None
    # Region is [x, y, width, height] in PIXELS
    region: tuple[int, int, int, int] | None = None
    scale: float = 1.0
    codepoint: int | None = None


def load_ingredients_config(
    asset_loader: AssetLoader,
) -> dict[ItemType, IngredientConfig]:
    with open(f'{DATA_DIR}/ingredients.yaml') as f:
        data = yaml.safe_load(f)['ingredients']
        items = {ItemType(item['id']): item for item in data}
        for itype, config in items.items():
            asset_loader.register_from_config(itype.value, config, '\u2588')
        return items


class _RawEffect(TypedDict):
    """An effect as authored in YAML, before parsing into an `Effect`."""

    type: str
    power: NotRequired[int]
    duration: NotRequired[int]
    lifesteal: NotRequired[int]


def _parse_effects(raw: list[_RawEffect]) -> list[Effect]:
    return [
        Effect(
            type=EffectType(effect['type']),
            duration=effect.get('duration', 0),
            power=effect.get('power', 0),
            lifesteal=effect.get('lifesteal', 0),
        )
        for effect in raw
    ]


class _RawModifier(TypedDict):
    """A spell's reaction modifier as authored in YAML, before parsing."""

    vs_status: str
    damage_mult: float


def _parse_modifiers(raw: list[_RawModifier]) -> list[DamageModifier]:
    return [
        DamageModifier(
            vs_status=StatusType(mod['vs_status']),
            damage_mult=float(mod['damage_mult']),
        )
        for mod in raw
    ]


def load_spells_config(asset_loader: AssetLoader) -> list[SpellConfig]:
    with open(f'{DATA_DIR}/spells.yaml') as f:
        data = yaml.safe_load(f)['spells']
        for spell in data:
            spell['effects'] = _parse_effects(spell.get('effects', []))
            spell['modifiers'] = _parse_modifiers(spell.get('modifiers', []))
            spell['target'] = TargetMode(spell['target'])

            processed_recipes: list[RecipeConfig] = []
            for r_data in spell.get('recipes', []):
                processed_recipes.append(
                    {
                        'ingredients': tuple(sorted(ItemType(id) for id in r_data['ingredients'])),
                        'charges': r_data['charges'],
                    }
                )
            spell['recipes'] = processed_recipes

            asset_loader.register_from_config(spell['id'], spell, '?')
        return data


def register_character_sprites(asset_loader: AssetLoader):
    """Register a sprite for each character id in characters.yaml. Characters carry no
    runtime config beyond their sprite, so nothing is returned."""
    try:
        with open(f'{DATA_DIR}/characters.yaml') as f:
            for char in yaml.safe_load(f)['characters']:
                asset_loader.register_from_config(char['id'], char, '@')
    except FileNotFoundError:
        return


def load_enemies_config(asset_loader: AssetLoader) -> dict[str, EnemyConfig]:
    try:
        with open(f'{DATA_DIR}/enemies.yaml') as f:
            data = yaml.safe_load(f)['enemies']
            enemies = {enemy['id']: enemy for enemy in data}
            for eid, config in enemies.items():
                if 'ability' in config:
                    config['ability'] = EnemyAbility(
                        range=config['ability']['range'],
                        effects=_parse_effects(config['ability'].get('effects', [])),
                    )
                if 'abilities' in config:
                    config['abilities'] = [
                        BossAbility(
                            ability=EnemyAbility(range=a['range'], effects=_parse_effects(a.get('effects', []))),
                            hp_threshold=a.get('hp_threshold', 1.0),
                            cooldown=a.get('cooldown', 0),
                            name=a.get('name', ''),
                        )
                        for a in config['abilities']
                    ]
                if 'effect_multipliers' in config:
                    config['effect_multipliers'] = {
                        EffectType(etype): float(mult) for etype, mult in config['effect_multipliers'].items()
                    }
                if 'drops' in config:
                    config['drops'] = [
                        LootDrop(
                            type=ItemType(d['type']),
                            min=d.get('min', 1),
                            max=d.get('max', 1),
                            chance=d.get('chance', 1.0),
                        )
                        for d in config['drops']
                    ]
                asset_loader.register_from_config(eid, config, '?')
            return enemies
    except FileNotFoundError:
        return {}


def load_npcs_config(asset_loader: AssetLoader) -> list[NPCConfig]:
    """Load the curated story NPCs and register each one's sprite."""
    try:
        with open(f'{DATA_DIR}/npcs.yaml') as f:
            npcs = yaml.safe_load(f)['npcs']
            for npc in npcs:
                asset_loader.register_from_config(npc['id'], npc, '@')
            return npcs
    except FileNotFoundError:
        return []


def load_tiles_config(asset_loader: AssetLoader) -> list[TileConfig]:
    try:
        with open(f'{DATA_DIR}/tiles.yaml') as f:
            data = yaml.safe_load(f)['tiles']
            for tile in data:
                tile['type'] = TileType(tile['type'])
                tile['effects'] = _parse_effects(tile.get('effects', []))
                asset_loader.register_from_config(tile['id'], tile, ' ')
            return data
    except FileNotFoundError:
        return []


class _RawSound(TypedDict, total=False):
    waveform: str
    freq: float
    duration: float
    freq_end: float
    decay: float
    volume: float
    file: str


def _parse_sound(raw: _RawSound) -> SynthSpec | SoundFile:
    """A single sounds.yaml entry: a WAV file reference or a synth recipe. Reads tolerantly
    (validate_data enforces that synth entries supply waveform/freq/duration)."""
    file = raw.get('file')
    if file is not None:
        return SoundFile(path=file)
    return SynthSpec(
        waveform=Waveform[raw.get('waveform', 'sine').upper()],
        freq=raw.get('freq', 0.0),
        duration=raw.get('duration', 0.0),
        freq_end=raw.get('freq_end'),
        decay=raw.get('decay', 6.0),
        volume=raw.get('volume', 0.5),
    )


def load_sounds_config() -> SoundSpecs:
    """Parse data/sounds.yaml into the synth/file recipe for each SoundId. Entries whose key
    isn't a known SoundId are skipped (validate_data flags those); a missing file yields {}."""
    try:
        with open(f'{DATA_DIR}/sounds.yaml') as f:
            data: dict[str, _RawSound] = yaml.safe_load(f)['sounds']
    except FileNotFoundError:
        return {}
    specs: SoundSpecs = {}
    for key, raw in data.items():
        try:
            specs[SoundId(key)] = _parse_sound(raw)
        except ValueError:
            debug_log(f'sounds.yaml: unknown sound id {key!r}, skipping')
    return specs


def load_music_config() -> MusicFiles:
    """Parse data/music.yaml into the WAV path for each MusicTrack. Unknown track keys are
    skipped; a missing file yields {} (all tracks silent)."""
    try:
        with open(f'{DATA_DIR}/music.yaml') as f:
            data: dict[str, str] = yaml.safe_load(f)['music']
    except FileNotFoundError:
        return {}
    tracks: MusicFiles = {}
    for key, path in data.items():
        try:
            tracks[MusicTrack(key)] = path
        except ValueError:
            debug_log(f'music.yaml: unknown track {key!r}, skipping')
    return tracks


@lru_cache(maxsize=1)
def get_game_configs(asset_loader: AssetLoader) -> GameConfigs:
    """
    Load and process all game configurations.
    Memoized to ensure sprite registration and disk I/O only happen once.
    """
    register_character_sprites(asset_loader)
    return {
        'ingredients': load_ingredients_config(asset_loader),
        'spells': load_spells_config(asset_loader),
        'tiles': load_tiles_config(asset_loader),
        'enemies': load_enemies_config(asset_loader),
        'npcs': load_npcs_config(asset_loader),
    }


class AssetLoader:
    def __init__(self):
        self._mapping: dict[str, SpriteDefinition] = {}
        # pygame render caches, populated lazily during rendering (once a display exists).
        self._images: dict[str, pygame.Surface] = {}
        self._sprites: dict[tuple[str, int, RGB | None], pygame.Surface] = {}
        self._fonts: dict[int, pygame.font.Font] = {}

    def register_char(self, sprite_id: str, char: str):
        """Register a font-based character directly."""
        self._mapping[sprite_id] = SpriteDefinition(codepoint=ord(char))

    def register_sprite(self, sprite_id: str, config: _RawSprite):
        """Register an external graphical sprite."""
        asset_type = AssetType[config.get('type', 'FILE').upper()]
        region = None
        if 'region' in config:
            x, y, w, h = config['region']
            region = (x, y, w, h)

        self._mapping[sprite_id] = SpriteDefinition(
            path=config['path'],
            type=asset_type,
            region=region,
            scale=config.get('scale', 1.0),
        )

    def register_from_config(self, sprite_id: str, config: _RenderableConfig, default_char: str):
        """Register `sprite_id` from a content config's optional 'sprite' block, falling
        back to a font character ('char' if authored, else `default_char`)."""
        if 'sprite' in config:
            self.register_sprite(sprite_id, config['sprite'])
        else:
            self.register_char(sprite_id, config.get('char', default_char))

    def font(self, size: int) -> pygame.font.Font:
        """The game typeface at `size` px, cached per size."""
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(FONT_FILE, size)
        return self._fonts[size]

    def _source_image(self, path: str) -> pygame.Surface:
        if path not in self._images:
            self._images[path] = pygame.image.load(path).convert_alpha()
        return self._images[path]

    def get_sprite(self, sprite_id: str, size: int, fg: RGB | None = None) -> pygame.Surface:
        """A `size`x`size` px Surface for `sprite_id`. An image sprite blits its source PNG
        region scaled to fit (tinted by `fg` when it isn't white, matching the old fg multiply);
        a font/char sprite renders the glyph in `fg` (white by default), centered on a
        transparent tile. Cached per (sprite_id, size, fg)."""
        key = (sprite_id, size, fg)
        cached = self._sprites.get(key)
        if cached is not None:
            return cached

        definition = self._mapping.get(sprite_id)
        if definition is not None and definition.path is not None:
            source = self._source_image(definition.path)
            if definition.region is not None:
                x, y, w, h = definition.region
                source = source.subsurface(pygame.Rect(x, y, w, h))
            surface = pygame.transform.smoothscale(source, (size, size))
            if fg is not None and fg != UI_WHITE:
                surface = surface.copy()
                surface.fill((*fg, 255), special_flags=pygame.BLEND_RGBA_MULT)
        else:
            surface = pygame.Surface((size, size), pygame.SRCALPHA)
            codepoint = definition.codepoint if definition and definition.codepoint else ord('\u2588')
            glyph = self.font(size).render(chr(codepoint), True, fg or UI_WHITE)
            surface.blit(glyph, glyph.get_rect(center=(size // 2, size // 2)))

        surface = surface.convert_alpha()  # store in display format so per-frame blits are fast
        self._sprites[key] = surface
        return surface
