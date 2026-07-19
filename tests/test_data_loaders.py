"""AssetLoader's sprite path renders to pygame Surfaces: an image sprite is its PNG scaled
to the requested tile size, a char sprite is a font glyph. Both need a display (conftest's
session dummy display provides one so .convert_alpha() works)."""

import pygame

from src import data_loaders
from src.audio import MusicTrack, SoundId
from src.data_loaders import AssetLoader


def _image_loader(tmp_path) -> AssetLoader:
    """An AssetLoader with one image sprite, backed by a tiny on-disk PNG."""
    png = tmp_path / 'thing.png'
    pygame.image.save(pygame.Surface((10, 10)), str(png))
    loader = AssetLoader()
    loader.register_sprite('thing', {'path': str(png), 'type': 'FILE'})
    return loader


def test_get_sprite_scales_an_image_to_the_requested_size(tmp_path):
    loader = _image_loader(tmp_path)

    sprite = loader.get_sprite('thing', 24)

    assert sprite.get_size() == (24, 24)


def test_get_sprite_caches_per_key(tmp_path):
    loader = _image_loader(tmp_path)

    # The same (id, size, fg) returns the identical cached Surface, not a re-render.
    assert loader.get_sprite('thing', 24) is loader.get_sprite('thing', 24)


def test_get_sprite_renders_a_char_sprite_as_a_glyph(tmp_path):
    loader = AssetLoader()
    loader.register_char('letter', '@')

    sprite = loader.get_sprite('letter', 20)

    assert sprite.get_size() == (20, 20)
    # The glyph leaves visible pixels (not a wholly transparent tile).
    assert pygame.mask.from_surface(sprite).count() > 0


def test_unknown_sprite_falls_back_to_a_rendered_glyph(tmp_path):
    # An unregistered id still yields a size-correct Surface (the fallback block glyph),
    # so a missing sprite renders as a placeholder rather than crashing.
    assert AssetLoader().get_sprite('absent', 20).get_size() == (20, 20)


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
