"""Audition a single sound effect in isolation for tuning data/sounds.yaml.

Loads the shipped sound recipes, renders them the same way the game does, and plays the one
you name through PortAudio. Edit a synth param in data/sounds.yaml and rerun to hear the change.

    ./venv/bin/python -m tools.play_sound cast_attack   # play one
    ./venv/bin/python -m tools.play_sound --list        # list every sound id
    ./venv/bin/python -m tools.play_sound --all         # play them all in sequence
"""

import argparse
import sys
import time

import numpy as np
from numpy.typing import NDArray

from src.audio import SAMPLE_RATE, SoundId, _load_sfx, sd
from src.data_loaders import load_sounds_config


def _play(buffer: NDArray[np.float32], sound_id: SoundId) -> None:
    """Play one preloaded buffer and block until it finishes."""
    assert sd is not None
    print(f'playing {sound_id.value}')
    sd.play(buffer, SAMPLE_RATE)
    sd.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description='Play a synthesized sound effect in isolation.')
    parser.add_argument('name', nargs='?', help='the SoundId to play (e.g. cast_attack)')
    parser.add_argument('--list', action='store_true', help='list every available sound id and exit')
    parser.add_argument('--all', action='store_true', help='play every sound in sequence')
    args = parser.parse_args()

    buffers = _load_sfx(load_sounds_config())
    names = sorted(sound_id.value for sound_id in buffers)

    if args.list or (not args.name and not args.all):
        print('\n'.join(names))
        return 0

    if sd is None:
        print('audio unavailable: PortAudio (sounddevice) is not installed', file=sys.stderr)
        return 1

    if args.all:
        for sound_id in sorted(buffers, key=lambda s: s.value):
            _play(buffers[sound_id], sound_id)
            time.sleep(0.15)
        return 0

    try:
        sound_id = SoundId(args.name)
    except ValueError:
        print(f'unknown sound {args.name!r}. available:\n' + '\n'.join(names), file=sys.stderr)
        return 1
    if sound_id not in buffers:
        print(f'{args.name!r} has no rendered buffer (missing WAV file?)', file=sys.stderr)
        return 1
    _play(buffers[sound_id], sound_id)
    return 0


if __name__ == '__main__':
    sys.exit(main())
