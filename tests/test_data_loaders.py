"""_fit_sprite_to_tile is pure pixel math (no font/image I/O), so it's driven directly
with synthetic arrays. build_tileset's slicing path needs a real image sprite, so those
tests write a tiny PNG and feed it through."""

import numpy as np
from PIL import Image

from src import data_loaders
from src.audio import MusicTrack, SoundId
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


def test_identical_sprites_share_one_rasterization(tmp_path):
    png = tmp_path / 'shared.png'
    Image.new('RGBA', (10, 10), (255, 255, 255, 255)).save(png)
    loader = AssetLoader()
    loader.register_sprite('one', {'path': str(png)})
    loader.register_sprite('two', {'path': str(png)})  # same path/region/scale

    loader.build_tileset()

    # The second sprite reuses the first's codepoints rather than re-rasterizing.
    assert loader.get_codepoint('one') == loader.get_codepoint('two')
    assert loader.get_block_codepoints('one') == loader.get_block_codepoints('two')


def test_region_sprite_rasterizes_just_its_region(tmp_path):
    png = tmp_path / 'sheet.png'
    Image.new('RGBA', (20, 20), (255, 255, 255, 255)).save(png)
    loader = AssetLoader()
    loader.register_sprite('cell', {'path': str(png), 'type': 'REGION', 'region': [0, 0, 10, 10]})

    loader.build_tileset()

    assert loader.get_codepoint('cell') != ord('█')  # registered, not the fallback


def test_unloadable_sprite_falls_back_to_the_block_glyph(tmp_path):
    loader = AssetLoader()
    loader.register_sprite('broken', {'path': str(tmp_path / 'missing.png')})

    loader.build_tileset()

    assert loader.get_codepoint('broken') == ord('█')


# --- registration & config loading ------------------------------------------


def test_register_sprite_keeps_the_pixel_region():
    loader = AssetLoader()
    loader.register_sprite('thing', {'path': 'x.png', 'type': 'REGION', 'region': [3, 4, 5, 6]})
    assert loader._mapping['thing'].region == (3, 4, 5, 6)


def test_register_from_config_uses_the_sprite_block_when_present():
    loader = AssetLoader()
    loader.register_from_config('thing', {'sprite': {'path': 'x.png'}}, default_char='?')
    assert loader._mapping['thing'].path == 'x.png'


def test_register_from_config_falls_back_to_a_font_char():
    loader = AssetLoader()
    loader.register_from_config('thing', {'char': 'K'}, default_char='?')
    assert loader._mapping['thing'].codepoint == ord('K')


def test_get_codepoint_for_unknown_sprite_is_the_block_glyph():
    assert AssetLoader().get_codepoint('absent') == ord('█')


def test_content_loaders_tolerate_missing_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr(data_loaders, 'DATA_DIR', str(tmp_path))  # an empty data dir
    loader = AssetLoader()

    assert data_loaders.load_enemies_config(loader) == {}
    assert data_loaders.load_tiles_config(loader) == []
    assert data_loaders.load_npcs_config(loader) == []
    data_loaders.register_character_sprites(loader)  # no characters.yaml: returns quietly
    assert data_loaders.load_sounds_config() == {}
    assert data_loaders.load_music_config() == {}


def test_load_sounds_config_parses_known_ids_and_skips_unknown(tmp_path, monkeypatch):
    (tmp_path / 'sounds.yaml').write_text(
        'sounds:\n'
        '  hit: {waveform: square, freq: 200, duration: 0.1}\n'
        '  not_a_sound: {waveform: sine, freq: 100, duration: 0.1}\n'
    )
    monkeypatch.setattr(data_loaders, 'DATA_DIR', str(tmp_path))

    specs = data_loaders.load_sounds_config()

    assert SoundId.HIT in specs
    assert list(specs) == [SoundId.HIT]  # the unknown id is dropped


def test_load_music_config_parses_known_tracks_and_skips_unknown(tmp_path, monkeypatch):
    (tmp_path / 'music.yaml').write_text('music:\n  dungeon: audio/d.wav\n  not_a_track: audio/x.wav\n')
    monkeypatch.setattr(data_loaders, 'DATA_DIR', str(tmp_path))

    assert data_loaders.load_music_config() == {MusicTrack.DUNGEON: 'audio/d.wav'}
