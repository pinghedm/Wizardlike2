"""The audio engine: synthesis, WAV loading, the sound registries, and the routing/volume
logic. Playback is exercised against a fake mixer (no real SDL device), and the module-level
cue helpers are checked to stay silent until an engine is attached to the world."""

import threading
import wave

import esper
import numpy as np
import pytest

from src import audio
from src.audio import (
    EFFECT_SOUNDS,
    AudioEngine,
    MusicTrack,
    SoundFile,
    SoundId,
    SynthSpec,
    Waveform,
    _load_wav,
    _render,
    cast_sound,
)
from src.components import EffectType
from src.data_loaders import _parse_sound


def _fake_engine() -> AudioEngine:
    """An AudioEngine bypassing __init__, so it needs no real PortAudio stream. Its mixing
    state (voices, buffers, lock) is set up directly for the playback-routing tests."""
    engine = object.__new__(AudioEngine)
    engine._sfx = {sound_id: np.ones((4, 2), dtype=np.float32) for sound_id in SoundId}
    engine._music_buffers = {}
    engine._sfx_voices = []
    engine._music_voice = None
    engine._music_files = {}
    engine._lock = threading.Lock()
    engine.current_track = None
    engine.music_volume = 1.0
    engine.sfx_volume = 1.0
    engine.muted = False
    return engine


# --- synthesis & loading -------------------------------------------------------------------


def test_render_returns_float32_of_expected_length():
    spec = SynthSpec(Waveform.SINE, freq=440, duration=0.1)
    buffer = _render(spec, rate=1000)
    assert buffer.dtype == np.float32
    assert len(buffer) == 100  # 0.1s * 1000Hz
    assert abs(buffer).max() <= spec.volume + 1e-6


@pytest.mark.parametrize('waveform', list(Waveform))
def test_render_covers_every_waveform(waveform):
    buffer = _render(SynthSpec(waveform, freq=300, duration=0.05, freq_end=600), rate=2000)
    assert buffer.dtype == np.float32
    assert len(buffer) == 100


def test_load_wav_round_trips(tmp_path):
    samples = np.array([0, 16384, -16384, 32767], dtype=np.int16)
    path = tmp_path / 'tone.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(samples.tobytes())

    loaded = _load_wav(str(path))
    assert loaded is not None
    data, rate = loaded
    assert rate == 22050
    assert data.dtype == np.float32
    assert len(data) == 4
    assert abs(data).max() <= 1.0


def test_load_wav_missing_file_returns_none():
    assert _load_wav('audio/does_not_exist.wav') is None


# --- registries ----------------------------------------------------------------------------


def test_parse_sound_builds_a_synth_spec():
    spec = _parse_sound({'waveform': 'square', 'freq': 160, 'freq_end': 90, 'duration': 0.1, 'decay': 16})
    assert spec == SynthSpec(Waveform.SQUARE, freq=160, duration=0.1, freq_end=90, decay=16)


def test_parse_sound_builds_a_sound_file():
    assert _parse_sound({'file': 'audio/hit.wav'}) == SoundFile(path='audio/hit.wav')


def test_effect_sounds_cover_every_effect_type():
    assert set(EFFECT_SOUNDS) == set(EffectType)


@pytest.mark.parametrize('effect_type', list(EffectType))
def test_cast_sound_maps_to_a_cast_id(effect_type):
    cast_ids = {SoundId.CAST_ATTACK, SoundId.CAST_HEAL, SoundId.CAST_BUFF, SoundId.CAST_DEBUFF}
    assert cast_sound(effect_type) in cast_ids


# --- playback routing & volume -------------------------------------------------------------


def test_play_sfx_starts_a_voice_at_the_sfx_volume():
    engine = _fake_engine()
    engine.sfx_volume = 0.6
    engine.play_sfx(SoundId.HIT)
    assert len(engine._sfx_voices) == 1
    assert engine._sfx_voices[0].volume == 0.6


def test_muted_engine_starts_no_sfx_voice():
    engine = _fake_engine()
    engine.muted = True
    engine.play_sfx(SoundId.HIT)
    assert engine._sfx_voices == []


def test_play_music_starts_a_voice_then_dedupes_same_track():
    engine = _fake_engine()
    engine._music_buffers = {MusicTrack.DUNGEON: np.ones((4, 2), dtype=np.float32)}
    engine.play_music(MusicTrack.DUNGEON)
    voice = engine._music_voice
    assert voice is not None
    engine.play_music(MusicTrack.DUNGEON)  # already on this track: same voice, not restarted
    assert engine._music_voice is voice


def test_apply_settings_zeroes_music_volume_when_muted():
    engine = _fake_engine()
    engine.apply_settings(music_volume=0.4, sfx_volume=0.5, muted=False)
    assert engine.music_volume == 0.4
    engine.apply_settings(music_volume=0.4, sfx_volume=0.5, muted=True)
    assert engine.music_volume == 0.0


def test_mix_sums_music_and_sfx_into_the_output_block():
    engine = _fake_engine()
    engine._music_voice = audio._Voice(buffer=np.full((8, 2), 0.1, dtype=np.float32), volume=1.0)
    engine.play_sfx(SoundId.HIT)  # _sfx buffers are all-ones
    out = np.zeros((4, 2), dtype=np.float32)
    engine._mix(out, 4)
    # music (0.1) + sfx (1.0) mixed into every frame.
    assert np.allclose(out, 1.1)


def test_mix_drops_finished_one_shot_voices():
    engine = _fake_engine()
    engine.play_sfx(SoundId.HIT)  # a 4-sample voice
    engine._mix(np.zeros((4, 2), dtype=np.float32), 4)
    assert engine._sfx_voices == []  # fully consumed, pruned


# --- module-level cue helpers --------------------------------------------------------------


def test_play_sfx_is_silent_without_an_engine():
    esper.clear_database()
    audio.play_sfx(SoundId.HIT)  # no engine attached: no-op, must not raise


def test_play_sfx_routes_through_the_attached_singleton():
    esper.clear_database()
    engine = _fake_engine()
    engine.reload_after_clear()  # register as the ECS singleton
    audio.play_sfx(SoundId.GOLD)
    assert len(engine._sfx_voices) == 1
