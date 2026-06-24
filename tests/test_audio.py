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
    CHANNELS,
    EFFECT_SOUNDS,
    MAX_SFX_VOICES,
    AudioEngine,
    MusicTrack,
    SoundFile,
    SoundId,
    SynthSpec,
    Waveform,
    _load_sfx,
    _load_wav,
    _prepare_buffer,
    _render,
    _resample,
    _to_stereo,
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


def test_load_wav_reads_unsigned_8bit_centered_on_128(tmp_path):
    samples = np.array([128, 255, 0, 192], dtype=np.uint8)
    path = tmp_path / 'u8.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(samples.tobytes())

    loaded = _load_wav(str(path))
    assert loaded is not None
    data, _rate = loaded
    assert data[0] == 0.0  # 128 -> silence
    assert abs(data).max() <= 1.0


def test_load_wav_reshapes_multichannel_frames(tmp_path):
    frames = np.array([[100, -100], [200, -200]], dtype=np.int16)
    path = tmp_path / 'stereo.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(frames.tobytes())

    loaded = _load_wav(str(path))
    assert loaded is not None
    data, _rate = loaded
    assert data.shape == (2, 2)


def test_load_wav_unsupported_sample_width_returns_none(tmp_path):
    path = tmp_path / 'w24.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(3)  # 24-bit isn't in the supported width map
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00\x00\x00\x00\x00')

    assert _load_wav(str(path)) is None


# --- buffer shaping ------------------------------------------------------------------------


def test_resample_at_the_same_rate_returns_the_input():
    data = np.arange(8, dtype=np.float32)
    assert _resample(data, 1000, 1000) is data


def test_resample_scales_length_by_the_rate_ratio():
    out = _resample(np.ones(100, dtype=np.float32), 1000, 2000)
    assert out.shape == (200,)
    assert out.dtype == np.float32


def test_resample_handles_each_channel_of_stereo():
    data = np.tile(np.arange(50, dtype=np.float32)[:, None], (1, 2))
    out = _resample(data, 1000, 500)
    assert out.shape == (25, 2)


def test_to_stereo_duplicates_mono_across_channels():
    out = _to_stereo(np.ones(4, dtype=np.float32))
    assert out.shape == (4, CHANNELS)
    assert np.array_equal(out[:, 0], out[:, 1])


def test_to_stereo_drops_extra_channels():
    out = _to_stereo(np.ones((4, 5), dtype=np.float32))
    assert out.shape == (4, CHANNELS)


def test_prepare_buffer_matches_the_stream_format():
    out = _prepare_buffer(np.ones(100, dtype=np.float32), rate=22050)
    assert out.dtype == np.float32
    assert out.shape[1] == CHANNELS


def test_load_sfx_renders_synth_specs_and_skips_missing_wavs():
    specs = {
        SoundId.HIT: SynthSpec(Waveform.SINE, freq=200, duration=0.05),
        SoundId.GOLD: SoundFile(path='audio/missing.wav'),
    }
    buffers = _load_sfx(specs)
    assert SoundId.HIT in buffers
    assert SoundId.GOLD not in buffers  # its WAV is absent, so the cue stays silent
    assert buffers[SoundId.HIT].shape[1] == CHANNELS


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


def test_mix_loops_the_music_voice_past_its_end():
    engine = _fake_engine()
    engine._music_voice = audio._Voice(buffer=np.full((4, 2), 0.5, dtype=np.float32), volume=1.0)
    out = np.zeros((10, 2), dtype=np.float32)

    engine._mix(out, 10)  # 10 frames over a 4-sample loop wraps twice

    assert engine._music_voice.pos == 10 % 4
    assert np.allclose(out, 0.5)


def test_callback_mixes_into_the_output_block():
    engine = _fake_engine()
    engine.play_sfx(SoundId.HIT)
    out = np.zeros((4, 2), dtype=np.float32)

    engine._callback(out, 4, None, None)

    assert np.allclose(out, 1.0)


def test_play_sfx_evicts_oldest_voices_past_the_cap():
    engine = _fake_engine()
    for _ in range(MAX_SFX_VOICES + 5):
        engine.play_sfx(SoundId.HIT)
    assert len(engine._sfx_voices) == MAX_SFX_VOICES


def test_play_music_with_a_missing_file_clears_the_voice():
    engine = _fake_engine()
    engine._music_files = {MusicTrack.SHOP: 'audio/missing.wav'}

    engine.play_music(MusicTrack.SHOP)

    assert engine.current_track is MusicTrack.SHOP  # recorded as the request...
    assert engine._music_voice is None  # ...but the file didn't load, so nothing plays


def test_stop_music_clears_the_track_and_voice():
    engine = _fake_engine()
    engine.current_track = MusicTrack.DUNGEON
    engine._music_voice = audio._Voice(buffer=np.ones((4, 2), dtype=np.float32), volume=1.0)

    engine.stop_music()

    assert engine.current_track is None
    assert engine._music_voice is None


def test_engine_construction_opens_and_starts_one_stream(monkeypatch):
    opened: dict[str, object] = {}

    class _FakeStream:
        def __init__(self, **kwargs: object):
            opened.update(kwargs)

        def start(self) -> None:
            opened['started'] = True

    monkeypatch.setattr(audio.sd, 'OutputStream', _FakeStream)

    engine = AudioEngine({SoundId.HIT: SynthSpec(Waveform.SINE, freq=200, duration=0.02)}, {})

    assert opened['started'] is True
    assert opened['samplerate'] == audio.SAMPLE_RATE
    assert SoundId.HIT in engine._sfx  # specs were rendered during construction


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


@pytest.mark.parametrize(
    'call',
    [
        lambda: audio.play_music(MusicTrack.DUNGEON),
        audio.stop_music,
        lambda: audio.apply_settings(0.5, 0.5, False),
        audio.shutdown,
    ],
)
def test_cue_helpers_are_silent_without_an_engine(call):
    esper.clear_database()
    call()  # no engine attached: a no-op, must not raise


def test_cue_helpers_route_to_the_attached_engine():
    esper.clear_database()
    engine = _fake_engine()
    engine._music_buffers = {MusicTrack.DUNGEON: np.ones((4, 2), dtype=np.float32)}
    engine.reload_after_clear()

    audio.play_music(MusicTrack.DUNGEON)
    assert engine.current_track is MusicTrack.DUNGEON

    audio.apply_settings(music_volume=0.3, sfx_volume=0.7, muted=False)
    assert engine.sfx_volume == 0.7

    audio.stop_music()
    assert engine._music_voice is None


def test_shutdown_stops_and_closes_the_attached_engine_stream():
    esper.clear_database()
    engine = _fake_engine()
    closed: list[str] = []

    class _FakeStream:
        def stop(self) -> None:
            closed.append('stop')

        def close(self) -> None:
            closed.append('close')

    engine._stream = _FakeStream()
    engine.reload_after_clear()

    audio.shutdown()

    assert closed == ['stop', 'close']


def test_init_audio_returns_none_when_disabled(monkeypatch):
    monkeypatch.setenv('WIZARDLIKE_NO_AUDIO', '1')
    assert audio.init_audio({}, {}, music_volume=1.0, sfx_volume=1.0, muted=False) is None


def test_init_audio_returns_none_when_the_device_fails(monkeypatch):
    monkeypatch.delenv('WIZARDLIKE_NO_AUDIO', raising=False)

    def _boom(*_args: object, **_kwargs: object) -> AudioEngine:
        raise RuntimeError('no output device')

    monkeypatch.setattr(audio, 'AudioEngine', _boom)
    esper.clear_database()

    assert audio.init_audio({}, {}, music_volume=1.0, sfx_volume=1.0, muted=False) is None
