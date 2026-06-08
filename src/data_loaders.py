import warnings
from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache
from typing import NotRequired, TypedDict

import numpy as np
import numpy.typing as npt
import tcod
import yaml
from PIL import Image

from src.components import (
    DamageModifier,
    Effect,
    EffectType,
    EnemyAbility,
    EnemyConfig,
    GameConfigs,
    IngredientConfig,
    ItemType,
    LootDrop,
    RecipeConfig,
    SpellConfig,
    StatusType,
    TargetMode,
    TileConfig,
)
from src.constants import DATA_DIR, FONT_FILE, FONT_TILE_PX
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


def _fit_sprite_to_tile(tile_pixels: npt.NDArray[np.uint8], tw: int, th: int, scale: float) -> npt.NDArray[np.uint8]:
    """Normalize a sprite's pixels to RGBA and center it, scaled by `scale`, in a fresh
    (th, tw, 4) tile. A grayscale sprite becomes an opacity mask over white; an RGB sprite
    derives its alpha from its brightest channel. A sprite larger than the tile is clipped
    to the tile bounds."""
    # Transparency / RGBA normalization.
    if tile_pixels.ndim == 2:
        h, w = tile_pixels.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = tile_pixels
        tile_pixels = rgba
    elif tile_pixels.ndim == 3 and tile_pixels.shape[2] == 3:
        h, w, _ = tile_pixels.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = np.max(tile_pixels, axis=2)
        tile_pixels = rgba

    # Resize to `scale` of the tile via nearest-neighbor (skip if already that size).
    target_w = int(tw * scale)
    target_h = int(th * scale)
    if (target_w, target_h) != (tile_pixels.shape[1], tile_pixels.shape[0]):
        row_indices = np.linspace(0, tile_pixels.shape[0] - 1, target_h, dtype=np.intp)
        col_indices = np.linspace(0, tile_pixels.shape[1] - 1, target_w, dtype=np.intp)
        resized = tile_pixels[np.ix_(row_indices, col_indices)]
    else:
        resized = tile_pixels

    # Center the sprite in the tile, clipping the source when scale > 1.0.
    final_tile = np.zeros((th, tw, 4), dtype=np.uint8)
    start_x = max(0, (tw - target_w) // 2)
    start_y = max(0, (th - target_h) // 2)
    copy_w = min(target_w, tw - start_x)
    copy_h = min(target_h, th - start_y)
    src_start_x = max(0, (target_w - tw) // 2) if target_w > tw else 0
    src_start_y = max(0, (target_h - th) // 2) if target_h > th else 0
    final_tile[start_y : start_y + copy_h, start_x : start_x + copy_w] = resized[
        src_start_y : src_start_y + copy_h,
        src_start_x : src_start_x + copy_w,
    ]
    return final_tile


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
            for r_data in spell['recipes']:
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


def load_tiles_config(asset_loader: AssetLoader) -> list[TileConfig]:
    try:
        with open(f'{DATA_DIR}/tiles.yaml') as f:
            data = yaml.safe_load(f)['tiles']
            for tile in data:
                asset_loader.register_from_config(tile['id'], tile, ' ')
            return data
    except FileNotFoundError:
        return []


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
    }


class AssetLoader:
    def __init__(self):
        self._cache: dict[str, np.ndarray] = {}
        self._mapping: dict[str, SpriteDefinition] = {}

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

    def build_tileset(self) -> tcod.tileset.Tileset:
        # 1. Rasterize the base font at the native cell size, so glyphs are
        # crisp at the display resolution instead of an upscaled bitmap.
        self.tileset = tcod.tileset.load_truetype_font(FONT_FILE, FONT_TILE_PX, FONT_TILE_PX)

        # Get base tile dimensions
        # tile_shape is (height, width)
        tw, th = self.tileset.tile_width, self.tileset.tile_height

        # Add procedural blocks. tcod's procedural_block_elements assigns tiles through its own
        # deprecated set_tile path (true as of tcod 21.2.0, the latest release, regardless of how
        # it's called), so the resulting DeprecationWarning is not actionable from our side and is
        # suppressed here. Upstream filters the same warning in its own test suite.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            self.tileset += tcod.tileset.procedural_block_elements(shape=self.tileset.tile_shape)

        # 2. Map graphical sprites to new codepoints in the Private Use Area
        current_codepoint = 0xE000
        asset_to_codepoint = {}

        for sprite_id, definition in self._mapping.items():
            if definition.path is None:
                continue

            key = (
                definition.path,
                definition.type,
                definition.region,
                definition.scale,
            )
            if key in asset_to_codepoint:
                definition.codepoint = asset_to_codepoint[key]
                continue

            try:
                if definition.path not in self._cache:
                    self._cache[definition.path] = np.asarray(Image.open(definition.path).convert('RGBA'))

                full_image = self._cache[definition.path]

                if definition.region:
                    x, y, w, h = definition.region
                    tile_pixels = full_image[y : y + h, x : x + w]
                else:
                    tile_pixels = full_image

                final_tile = _fit_sprite_to_tile(tile_pixels, tw, th, definition.scale)

                self.tileset[current_codepoint] = final_tile
                definition.codepoint = current_codepoint
                asset_to_codepoint[key] = current_codepoint
                current_codepoint += 1
            except Exception as exc:
                # Fall back to the block glyph so one bad sprite doesn't abort the boot,
                # but log which sprite failed and why (silent otherwise: it just renders
                # as a solid block with no hint).
                debug_log(f'build_tileset: sprite {sprite_id!r} ({definition.path}) failed: {exc!r}')
                definition.codepoint = ord('\u2588')
                asset_to_codepoint[key] = definition.codepoint

        return self.tileset

    def get_codepoint(self, sprite_id: str) -> int:
        if sprite_id not in self._mapping:
            return ord('\u2588')
        return self._mapping[sprite_id].codepoint or ord('\u2588')
