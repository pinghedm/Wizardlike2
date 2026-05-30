import warnings
from dataclasses import dataclass
from enum import Enum, auto
from functools import lru_cache

import numpy as np
import tcod
import yaml
from PIL import Image

from src.components import Effect, EffectType, EnemyAbility, ItemType, LootDrop
from src.constants import DATA_DIR


class AssetType(Enum):
    FILE = auto()
    REGION = auto()


@dataclass
class SpriteDefinition:
    # If path is None, this is a font character, and codepoint is the direct Unicode value.
    path: str | None = None
    type: AssetType | None = None
    # Region is [x, y, width, height] in PIXELS
    region: tuple[int, int, int, int] | None = None
    scale: float = 1.0
    codepoint: int | None = None


def load_ingredients_config(asset_loader: AssetLoader):
    with open(f'{DATA_DIR}/ingredients.yaml') as f:
        data = yaml.safe_load(f)['ingredients']
        items = {item['id']: item for item in data}
        for iid, config in items.items():
            if 'sprite' in config:
                asset_loader.register_sprite(iid, config['sprite'])
            else:
                # Use the character defined in YAML, or a block fallback
                char = config.get('char', '\u2588')
                asset_loader.register_char(iid, char)
        return items


def _parse_effects(raw: list[dict]) -> list[Effect]:
    return [
        Effect(
            type=EffectType(effect['type']),
            duration=effect.get('duration', 0),
            power=effect.get('power', 0),
        )
        for effect in raw
    ]


def load_spells_config(asset_loader: AssetLoader):
    with open(f'{DATA_DIR}/spells.yaml') as f:
        data = yaml.safe_load(f)['spells']
        for spell in data:
            spell['effects'] = _parse_effects(spell.get('effects', []))

            processed_recipes = []
            for r_data in spell['recipes']:
                processed_recipes.append(
                    {
                        'ingredients': tuple(sorted([ItemType(id) for id in r_data['ingredients']])),
                        'charges': r_data['charges'],
                    }
                )
            spell['recipes'] = processed_recipes

            if 'sprite' in spell:
                asset_loader.register_sprite(spell['id'], spell['sprite'])
            else:
                # Spells default to a question mark if no graphic is provided
                asset_loader.register_char(spell['id'], '?')
        return data


def load_characters_config(asset_loader: AssetLoader):
    try:
        with open(f'{DATA_DIR}/characters.yaml') as f:
            data = yaml.safe_load(f)['characters']
            chars = {char['id']: char for char in data}
            for cid, config in chars.items():
                if 'sprite' in config:
                    asset_loader.register_sprite(cid, config['sprite'])
                else:
                    char = config.get('char', '@')
                    asset_loader.register_char(cid, char)
            return chars
    except FileNotFoundError:
        return {}


def load_enemies_config(asset_loader: AssetLoader):
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
                if 'sprite' in config:
                    asset_loader.register_sprite(eid, config['sprite'])
                else:
                    char = config.get('char', '?')
                    asset_loader.register_char(eid, char)
            return enemies
    except FileNotFoundError:
        return {}


def load_tiles_config(asset_loader: AssetLoader):
    try:
        with open(f'{DATA_DIR}/tiles.yaml') as f:
            data = yaml.safe_load(f)['tiles']
            for tile in data:
                if 'sprite' in tile:
                    asset_loader.register_sprite(tile['id'], tile['sprite'])
                else:
                    char = tile.get('char', ' ')
                    asset_loader.register_char(tile['id'], char)
            return data
    except FileNotFoundError:
        return []


@lru_cache(maxsize=1)
def get_game_configs(asset_loader: AssetLoader):
    """
    Load and process all game configurations.
    Memoized to ensure sprite registration and disk I/O only happen once.
    """
    return {
        'ingredients': load_ingredients_config(asset_loader),
        'spells': load_spells_config(asset_loader),
        'characters': load_characters_config(asset_loader),
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

    def register_sprite(self, sprite_id: str, config: SpriteDefinition):
        """Register an external graphical sprite."""
        asset_type_str = config.get('type', 'FILE').upper()
        asset_type = AssetType[asset_type_str]
        region = tuple(config['region']) if 'region' in config else None

        self._mapping[sprite_id] = SpriteDefinition(
            path=config['path'],
            type=asset_type,
            region=region,
            scale=config.get('scale', 1.0),
        )

    def build_tileset(self) -> tcod.tileset.Tileset:
        # 1. Load base font (Dejavu)
        base_path = 'data/dejavu10x10_gs_tc.png'
        self.tileset = tcod.tileset.load_tilesheet(base_path, 32, 8, tcod.tileset.CHARMAP_TCOD)

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

        for _sprite_id, definition in self._mapping.items():
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

                # 1. Slicing
                if definition.region:
                    x, y, w, h = definition.region
                    tile_pixels = full_image[y : y + h, x : x + w]
                else:
                    tile_pixels = full_image

                # 2. Transparency/RGBA Normalization
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

                # 3. Scaling and Centering
                # We want the sprite to be 'definition.scale' size relative to the target tile
                final_tile = np.zeros((th, tw, 4), dtype=np.uint8)

                target_w = int(tw * definition.scale)
                target_h = int(th * definition.scale)

                # Simple nearest-neighbor resize if needed
                if (target_w, target_h) != (tile_pixels.shape[1], tile_pixels.shape[0]):
                    # Calculate indices for nearest neighbor
                    row_indices = (np.linspace(0, tile_pixels.shape[0] - 1, target_h)).astype(int)
                    col_indices = (np.linspace(0, tile_pixels.shape[1] - 1, target_w)).astype(int)
                    resized = tile_pixels[np.ix_(row_indices, col_indices)]
                else:
                    resized = tile_pixels

                # Center the resized sprite in the final tile
                # Clip to tile boundaries if scale > 1.0
                start_x = max(0, (tw - target_w) // 2)
                start_y = max(0, (th - target_h) // 2)

                copy_w = min(target_w, tw - start_x)
                copy_h = min(target_h, th - start_y)

                # If scale > 1.0, we might need to clip the source 'resized' image
                src_start_x = max(0, (target_w - tw) // 2) if target_w > tw else 0
                src_start_y = max(0, (target_h - th) // 2) if target_h > th else 0

                final_tile[start_y : start_y + copy_h, start_x : start_x + copy_w] = resized[
                    src_start_y : src_start_y + copy_h,
                    src_start_x : src_start_x + copy_w,
                ]

                self.tileset[current_codepoint] = final_tile
                definition.codepoint = current_codepoint
                asset_to_codepoint[key] = current_codepoint
                current_codepoint += 1
            except Exception:
                definition.codepoint = ord('\u2588')
                asset_to_codepoint[key] = definition.codepoint

        return self.tileset

    def get_codepoint(self, sprite_id: str) -> int:
        if sprite_id not in self._mapping:
            return ord('\u2588')
        return self._mapping[sprite_id].codepoint
