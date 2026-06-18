"""_fit_sprite_to_tile is pure pixel math (no font/image I/O), so it's driven directly
with synthetic arrays. build_tileset's slicing path needs a real image sprite, so those
tests write a tiny PNG and feed it through."""

import numpy as np
from PIL import Image

from src.constants import TILE_SCALE
from src.data_loaders import AssetLoader, _fit_sprite_to_tile

TILE = 4  # a small square tile keeps the expected arrays easy to read


def test_grayscale_becomes_white_with_alpha_from_the_value():
    gray = np.full((TILE, TILE), 128, dtype=np.uint8)

    out = _fit_sprite_to_tile(gray, TILE, TILE, scale=1.0)

    assert out.shape == (TILE, TILE, 4)
    assert np.all(out[..., :3] == 255)  # opacity mask over white
    assert np.all(out[..., 3] == 128)


def test_rgb_becomes_white_with_alpha_from_the_brightest_channel():
    rgb = np.zeros((TILE, TILE, 3), dtype=np.uint8)
    rgb[..., 1] = 200  # green is the brightest channel

    out = _fit_sprite_to_tile(rgb, TILE, TILE, scale=1.0)

    assert np.all(out[..., :3] == 255)
    assert np.all(out[..., 3] == 200)


def test_tile_sized_rgba_passes_through_unchanged():
    rgba = np.random.randint(0, 256, (TILE, TILE, 4), dtype=np.uint8)

    out = _fit_sprite_to_tile(rgba, TILE, TILE, scale=1.0)

    assert np.array_equal(out, rgba)


def test_downscaled_sprite_is_centered_with_transparent_margins():
    rgba = np.full((TILE, TILE, 4), 255, dtype=np.uint8)

    out = _fit_sprite_to_tile(rgba, TILE, TILE, scale=0.5)  # -> a 2x2 sprite

    assert out.shape == (TILE, TILE, 4)
    assert np.all(out[0, :] == 0)  # top row is empty margin
    assert np.all(out[1:3, 1:3, 3] == 255)  # the 2x2 sprite sits centered


def test_oversized_sprite_is_clipped_to_the_tile():
    rgba = np.full((TILE, TILE, 4), 255, dtype=np.uint8)

    out = _fit_sprite_to_tile(rgba, TILE, TILE, scale=2.0)  # -> an 8x8 sprite, clipped

    assert out.shape == (TILE, TILE, 4)
    assert np.all(out[..., 3] == 255)  # the clipped center fills the whole tile


# --- build_tileset block sprites --------------------------------------------


def _sprite_loader(tmp_path) -> AssetLoader:
    """An AssetLoader with one image sprite, backed by a tiny on-disk PNG."""
    png = tmp_path / 'thing.png'
    Image.new('RGBA', (10, 10), (255, 255, 255, 255)).save(png)
    loader = AssetLoader()
    loader.register_sprite('thing', {'path': str(png), 'type': 'FILE'})
    return loader


def test_image_sprite_is_also_sliced_into_a_block_of_subtiles(tmp_path):
    loader = _sprite_loader(tmp_path)

    loader.build_tileset()

    # The single-cell form is registered (a Private Use Area codepoint, not the fallback)...
    assert loader.get_codepoint('thing') != ord('█')
    # ...plus a distinct sub-tile per cell of the scaled block.
    block = loader.get_block_codepoints('thing')
    assert block is not None
    assert len(block) == TILE_SCALE * TILE_SCALE
    assert len(set(block)) == len(block)


def test_font_glyph_has_no_block_form(tmp_path):
    loader = _sprite_loader(tmp_path)
    loader.register_char('letter', '@')

    loader.build_tileset()

    # A font glyph fills its block with the one glyph, so it needs no sliced sub-tiles.
    assert loader.get_block_codepoints('letter') is None
