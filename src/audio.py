"""Audio service: background music + sound effects.

Playback goes through PortAudio (the `sounddevice` library): the engine owns one output
stream; its real-time callback mixes the active one-shot SFX voices and the looping music
voice into the output buffer. Sound effects are numpy waveforms synthesized at startup (a
sound may instead point at a WAV file); music is a looping WAV.

The engine is a module-level service (like :mod:`src.persistence`), deliberately kept *outside*
the ECS: it owns an audio stream that must never enter the save-game pickle. Every public call
is a safe no-op until :func:`init_audio` succeeds, so the headless test harness and machines
with no audio device — or without the PortAudio library installed at all — simply stay silent.
Set ``WIZARDLIKE_NO_AUDIO`` to force that silent path.
"""

import enum
import os
import threading
import wave
from dataclasses import dataclass

import esper
import numpy as np
from numpy.typing import NDArray

try:
    import sounddevice as sd
except OSError:  # native PortAudio library absent — run silently
    sd = None

from src.components import EffectType
from src.constants import DATA_DIR
from src.debug import debug_log
from src.ecs_helpers import RuntimeSingleton, try_get_singleton

# Output stream format. Everything is mixed at this rate in stereo float32; sounds at other
# rates/channels are resampled and up-mixed to match when loaded.
SAMPLE_RATE = 44100
CHANNELS = 2
# Drop the oldest voices past this many concurrent SFX so a burst can't run the mixer away.
MAX_SFX_VOICES = 32


class SoundId(enum.StrEnum):
    """A distinct sound effect. Spell casts pick one of the CAST_* ids by effect family."""

    CAST_ATTACK = 'cast_attack'
    CAST_HEAL = 'cast_heal'
    CAST_BUFF = 'cast_buff'
    CAST_DEBUFF = 'cast_debuff'
    IMPACT = 'impact'
    HIT = 'hit'
    STATUS = 'status'
    POISON_TICK = 'poison_tick'
    REGEN_TICK = 'regen_tick'
    KNOCKBACK = 'knockback'
    DEATH = 'death'
    REACTION = 'reaction'
    CRAFT = 'craft'
    DISCOVERY = 'discovery'
    LEVEL_UP = 'level_up'
    FIZZLE = 'fizzle'
    PICKUP = 'pickup'
    GOLD = 'gold'
    DESCEND = 'descend'
    PURCHASE = 'purchase'
    MENU_MOVE = 'menu_move'
    MENU_CONFIRM = 'menu_confirm'
    MENU_CANCEL = 'menu_cancel'


class MusicTrack(enum.StrEnum):
    MENU = 'menu'
    DUNGEON = 'dungeon'
    SHOP = 'shop'


class Waveform(enum.Enum):
    SINE = enum.auto()
    SQUARE = enum.auto()
    TRIANGLE = enum.auto()
    SAW = enum.auto()
    NOISE = enum.auto()


@dataclass(frozen=True)
class SynthSpec:
    """A procedurally generated blip: an oscillator under an exponential decay envelope,
    optionally sweeping pitch from `freq` to `freq_end` over its duration."""

    waveform: Waveform
    freq: float
    duration: float
    freq_end: float | None = None
    decay: float = 6.0
    volume: float = 0.5


@dataclass(frozen=True)
class SoundFile:
    """A sound loaded from a WAV file (path relative to DATA_DIR) instead of synthesized."""

    path: str


# How each sound id sounds (synth recipe or WAV) is authored in data/sounds.yaml and loaded
# via data_loaders.load_sounds_config; the music track -> file map comes from data/music.yaml.
SoundSpecs = dict[SoundId, SynthSpec | SoundFile]
MusicFiles = dict[MusicTrack, str]


# A spell's cast sound, chosen by its primary effect (same shape as visuals.EFFECT_COLORS).
EFFECT_SOUNDS: dict[EffectType, SoundId] = {
    EffectType.DAMAGE: SoundId.CAST_ATTACK,
    EffectType.DRAIN: SoundId.CAST_ATTACK,
    EffectType.KNOCKBACK: SoundId.CAST_ATTACK,
    EffectType.HEAL: SoundId.CAST_HEAL,
    EffectType.REGEN: SoundId.CAST_HEAL,
    EffectType.HASTE: SoundId.CAST_BUFF,
    EffectType.SHIELD: SoundId.CAST_BUFF,
    EffectType.REVEAL: SoundId.CAST_BUFF,
    EffectType.SLOW: SoundId.CAST_DEBUFF,
    EffectType.STUN: SoundId.CAST_DEBUFF,
    EffectType.POISON: SoundId.CAST_DEBUFF,
    EffectType.WET: SoundId.CAST_DEBUFF,
}


def cast_sound(effect_type: EffectType) -> SoundId:
    """The cast sound for a spell whose primary effect is `effect_type`."""
    return EFFECT_SOUNDS.get(effect_type, SoundId.CAST_ATTACK)


def _render(spec: SynthSpec, rate: int) -> NDArray[np.float32]:
    """Render a SynthSpec to a mono float32 waveform in [-1, 1]."""
    count = max(1, int(spec.duration * rate))
    t = np.linspace(0.0, spec.duration, count, endpoint=False, dtype=np.float64)
    if spec.freq_end is None:
        phase = 2 * np.pi * spec.freq * t
        inst_freq = np.full(count, spec.freq)
    else:
        sweep = (spec.freq_end - spec.freq) / spec.duration
        phase = 2 * np.pi * (spec.freq * t + 0.5 * sweep * t * t)
        inst_freq = spec.freq + sweep * t

    if spec.waveform is Waveform.SINE:
        wave_data = np.sin(phase)
    elif spec.waveform is Waveform.SQUARE:
        wave_data = np.sign(np.sin(phase))
    elif spec.waveform is Waveform.TRIANGLE:
        wave_data = 2.0 / np.pi * np.arcsin(np.sin(phase))
    elif spec.waveform is Waveform.SAW:
        ramp = inst_freq * t
        wave_data = 2.0 * (ramp - np.floor(0.5 + ramp))
    else:  # NOISE
        wave_data = np.random.uniform(-1.0, 1.0, count)

    envelope = np.exp(-spec.decay * t)
    return (wave_data * envelope * spec.volume).astype(np.float32)


def _load_wav(path: str) -> tuple[NDArray[np.float32], int] | None:
    """Load a WAV file (relative to DATA_DIR) as a float32 array in [-1, 1] plus its sample
    rate, or None if the file is missing or in an unsupported sample format."""
    full = path if os.path.isabs(path) else os.path.join(DATA_DIR, path)
    if not os.path.exists(full):
        return None
    with wave.open(full, 'rb') as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())

    dtypes = {1: np.uint8, 2: np.int16, 4: np.int32}
    dtype = dtypes.get(width)
    if dtype is None:
        return None
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if width == 1:  # unsigned 8-bit is centered on 128
        data = (data - 128.0) / 128.0
    else:
        data /= float(np.iinfo(dtype).max)
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate


def _resample(data: NDArray[np.float32], src_rate: int, dst_rate: int) -> NDArray[np.float32]:
    """Linearly resample `data` (1-D mono or 2-D (samples, channels)) to `dst_rate`."""
    if src_rate == dst_rate:
        return data
    src_len = data.shape[0]
    dst_len = max(1, round(src_len * dst_rate / src_rate))
    src_idx = np.arange(src_len, dtype=np.float64)
    dst_idx = np.linspace(0.0, src_len - 1, dst_len, dtype=np.float64)
    if data.ndim == 1:
        return np.asarray(np.interp(dst_idx, src_idx, data), dtype=np.float32)
    out = np.empty((dst_len, data.shape[1]), dtype=np.float32)
    for ch in range(data.shape[1]):
        out[:, ch] = np.asarray(np.interp(dst_idx, src_idx, data[:, ch]), dtype=np.float32)
    return out


def _to_stereo(data: NDArray[np.float32]) -> NDArray[np.float32]:
    """Shape any sound to (samples, CHANNELS): mono is duplicated, extra channels dropped."""
    if data.ndim == 1:
        data = data[:, np.newaxis]
    if data.shape[1] == 1:
        data = np.repeat(data, CHANNELS, axis=1)
    return np.ascontiguousarray(data[:, :CHANNELS], dtype=np.float32)


def _prepare_buffer(data: NDArray[np.float32], rate: int) -> NDArray[np.float32]:
    """Resample and up-mix a synthesized/loaded sound to the stream's rate and channels."""
    return _to_stereo(_resample(data, rate, SAMPLE_RATE))


def _load_sfx(sound_specs: SoundSpecs) -> dict[SoundId, NDArray[np.float32]]:
    """Render/load every sound spec into a stream-ready stereo buffer. A SoundFile whose WAV
    is missing is skipped (that cue stays silent)."""
    buffers: dict[SoundId, NDArray[np.float32]] = {}
    for sound_id, spec in sound_specs.items():
        if isinstance(spec, SoundFile):
            loaded = _load_wav(spec.path)
            if loaded is None:
                continue
            data, rate = loaded
        else:
            data, rate = _render(spec, SAMPLE_RATE), SAMPLE_RATE
        buffers[sound_id] = _prepare_buffer(data, rate)
    return buffers


@dataclass
class _Voice:
    """A sound being played: a stereo buffer and the next sample index to read from it."""

    buffer: NDArray[np.float32]
    volume: float
    pos: int = 0


class AudioEngine(RuntimeSingleton):
    """Owns the PortAudio output stream and the preloaded sound buffers. The stream's real-time
    callback mixes the live voices into the output block; play_sfx/play_music mutate the voice
    set under a lock. One per process, constructed by init_audio once the stream opens."""

    def __init__(self, sound_specs: SoundSpecs, music_files: MusicFiles):
        self._music_files = music_files
        self._sfx = _load_sfx(sound_specs)
        self._music_buffers: dict[MusicTrack, NDArray[np.float32]] = {}
        self._sfx_voices: list[_Voice] = []
        self._music_voice: _Voice | None = None
        self.current_track: MusicTrack | None = None
        self.music_volume = 1.0
        self.sfx_volume = 1.0
        self.muted = False
        self._lock = threading.Lock()
        assert sd is not None  # init_audio only builds the engine when PortAudio is present
        self._stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32', callback=self._callback
        )
        self._stream.start()

    def _callback(self, outdata: NDArray[np.float32], frames: int, _time: object, _status: object) -> None:
        self._mix(outdata, frames)

    def _mix(self, outdata: NDArray[np.float32], frames: int) -> None:
        """Sum the looping music voice and the one-shot SFX voices into `outdata`, advancing
        each voice and dropping finished one-shots. Runs on the audio thread."""
        outdata.fill(0.0)
        with self._lock:
            music = self._music_voice
            if music is not None and self.music_volume > 0.0:
                written = 0
                while written < frames:
                    chunk = min(frames - written, len(music.buffer) - music.pos)
                    block = music.buffer[music.pos : music.pos + chunk] * self.music_volume
                    outdata[written : written + chunk] += block
                    music.pos += chunk
                    written += chunk
                    if music.pos >= len(music.buffer):
                        music.pos = 0  # loop
            for voice in self._sfx_voices:
                chunk = min(frames, len(voice.buffer) - voice.pos)
                outdata[:chunk] += voice.buffer[voice.pos : voice.pos + chunk] * voice.volume
                voice.pos += chunk
            self._sfx_voices = [v for v in self._sfx_voices if v.pos < len(v.buffer)]

    def play_sfx(self, sound_id: SoundId) -> None:
        if self.muted:
            return
        buffer = self._sfx.get(sound_id)
        if buffer is None:
            return
        with self._lock:
            self._sfx_voices.append(_Voice(buffer=buffer, volume=self.sfx_volume))
            if len(self._sfx_voices) > MAX_SFX_VOICES:
                del self._sfx_voices[: len(self._sfx_voices) - MAX_SFX_VOICES]

    def play_music(self, track: MusicTrack) -> None:
        if track is self.current_track:
            return
        self.current_track = track
        buffer = self._music_buffers.get(track)
        if buffer is None:
            path = self._music_files.get(track)
            loaded = _load_wav(path) if path is not None else None
            if loaded is None:
                with self._lock:
                    self._music_voice = None
                return
            data, rate = loaded
            buffer = _prepare_buffer(data, rate)
            self._music_buffers[track] = buffer
        with self._lock:
            self._music_voice = _Voice(buffer=buffer, volume=self.music_volume)

    def stop_music(self) -> None:
        self.current_track = None
        with self._lock:
            self._music_voice = None

    def apply_settings(self, music_volume: float, sfx_volume: float, muted: bool) -> None:
        self.music_volume = 0.0 if muted else music_volume
        self.sfx_volume = sfx_volume
        self.muted = muted

    def shutdown(self) -> None:
        self._stream.stop()
        self._stream.close()

    def reload_after_clear(self) -> None:
        attach(self)


# The engine is reached as an ECS singleton (`try_get_singleton(AudioEngine)`) so cue sites
# query for it the same way every other system queries world state — no module global. It is
# *not* part of the game's state, though: main() owns the instance so it outlives the
# clear_database() on new game / load / return-to-title (rebuilding it would reopen the audio
# stream and re-synthesize every sound), persistence.save_game() filters it out of the pickle, and
# attach() restores the singleton after a clear. Absent the singleton (headless tests, no
# device, audio disabled) every call below is a silent no-op.


def init_audio(
    sound_specs: SoundSpecs, music_files: MusicFiles, music_volume: float, sfx_volume: float, muted: bool
) -> AudioEngine | None:
    """Open the audio device, preload the given sounds, apply the saved volumes, and register
    the engine as the ECS singleton. Returns the engine for main() to hold, or None when audio
    is disabled (WIZARDLIKE_NO_AUDIO), PortAudio is unavailable, or no device opens."""
    if sd is None or os.environ.get('WIZARDLIKE_NO_AUDIO'):
        return None
    try:
        engine = AudioEngine(sound_specs, music_files)
    except Exception as exc:  # no output device / PortAudio failure: run silently rather than crash
        debug_log(f'audio disabled: {exc!r}')
        return None
    engine.apply_settings(music_volume, sfx_volume, muted)
    attach(engine)
    return engine


def attach(engine: AudioEngine) -> None:
    """(Re)register the engine as the ECS singleton if a clear_database() removed it."""
    if try_get_singleton(AudioEngine) is None:
        esper.create_entity(engine)


def play_sfx(sound_id: SoundId) -> None:
    engine = try_get_singleton(AudioEngine)
    if engine is not None:
        engine.play_sfx(sound_id)


def play_music(track: MusicTrack) -> None:
    engine = try_get_singleton(AudioEngine)
    if engine is not None:
        engine.play_music(track)


def stop_music() -> None:
    engine = try_get_singleton(AudioEngine)
    if engine is not None:
        engine.stop_music()


def apply_settings(music_volume: float, sfx_volume: float, muted: bool) -> None:
    engine = try_get_singleton(AudioEngine)
    if engine is not None:
        engine.apply_settings(music_volume, sfx_volume, muted)


def shutdown() -> None:
    engine = try_get_singleton(AudioEngine)
    if engine is not None:
        engine.shutdown()
