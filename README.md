# WizardLike

WizardLike is a 2D roguelike game where survival depends on finding and combining ingredients to discover powerful spells. Inspired by the _Mystery Dungeon_ series, it features a tile-based dungeon crawl, procedural level generation, and an experimental crafting system.

## How to Play

### Prerequisites

- Python 3.14

### Setup

1. Clone the repository.
2. Initialize the environment:
   ```bash
   python3.14 -m venv venv
   source venv/bin/activate  # Or ./venv/bin/activate on some shells
   pip install pip-tools
   pip-sync requirements.txt requirements-dev.txt
   ```

### Running the Game

Launch the game from the project root:

```bash
python -m src.main
```

### Controls

#### Keyboard

- **Arrow Keys**: Move your character (bump into enemies to attack).
- **C**: Open/Close the Crafting Menu.
- **S**: Open/Close the Spellcasting Menu.
- **1–9**: Quick-cast a spell by slot — jumps straight into targeting for that spell, skipping the picker.
- **Enter**: Confirm.
- **Tab**: Switch tabs / cycle the current target.
- **PageUp / PageDown**: Scroll the message log.
- **Escape**: Open the pause menu (and back out of any submenu).
- **In the Crafting Menu**:
  - **Tab**: Toggle between the Spellbook and the Experiment (mixing) views.
  - **Up/Down**: Navigate your spellbook; **Left/Right**: add/remove ingredients in the mix.
  - **Enter**: Combine the mix (or craft the selected known recipe).
  - **C / Escape**: Return to the dungeon.
- **In the Spellcasting Menu**:
  - **Arrow Keys**: Select a known spell (or press **1–9** to quick-cast).
  - **Enter**: Choose the spell, then use the **Arrow Keys** to aim, **Tab** to switch target, and **Enter** to cast.
  - **S / Escape**: Cancel.

By default, the game **keeps you in targeting with the same spell** after a cast so you can
fire again immediately; this is configurable (see [Settings](#settings) below).

#### Controller / gamepad

- **D-Pad / Left Stick**: Move.
- **A**: Confirm — **B**: Cancel / back.
- **X**: Spellcasting Menu — **Y**: Crafting Menu.
- **Start**: Pause menu.
- **Right Shoulder**: Switch tabs / cycle target.
- **Left / Right Triggers**: Scroll the message log.
- **Left Shoulder (hold) + A / X / Y / B**: Quick-cast spell slots 1–4.

Movement, **Start**, and the quick-cast shoulder modifier are fixed; the other buttons and
triggers can be rebound from the Settings screen.

### Settings

Open the pause menu (**Escape** / **Start**) and choose **Settings** to:

- Change the **After casting** behavior — _Stay_ (keep aiming the same spell, the default),
  _Reselect_ (return to the spell picker), or _Explore_ (return to the map). Highlight the row
  and press **Left/Right** to cycle it.
- Adjust **Music volume** / **Sound volume** (Left/Right, in 10% steps) and toggle **Muted**.
- **Remap** keyboard keys and controller buttons: highlight an action, press **Enter**, then
  press the new key or button.

Your settings (and metaprogression like gold) persist across runs.

## Crafting & Discovery

- Explore the dungeon to find glowing ingredients scattered on the floor.
- Collect ingredients to add them to your inventory.
- Open the **Spellbook (C)** to experiment with combinations.
- Successfully crafting a spell will record the recipe in your Spellbook and grant you spell charges.

## Adding Content

All game data is defined in the `data/` directory.

- `ingredients.yaml`: Add new reagents or change their visual properties.
- `spells.yaml`: Add new spell recipes and define their potency (charges).
- `sounds.yaml`: Tune the synthesized sound effects (see [Audio](#audio)).
- `music.yaml`: Map each background-music track to a WAV file.

_Always run the data validator after modifying these files:_

```bash
python -m tools.validate_data
```

## Audio

Sound and music play through [PortAudio](https://www.portaudio.com/) (the `sounddevice`
dependency), because the SDL bundled with `tcod` ships without a working audio driver. If no
output device is available the game runs silently — set `WIZARDLIKE_DEBUG=1` to see why.

- **Sound effects** are synthesized at startup from `data/sounds.yaml` — each `SoundId` is a
  small waveform recipe (`waveform`/`freq`/`freq_end`/`duration`/`decay`/`volume`), so they
  need no asset files. Tweak the numbers to retune a sound. (An entry may instead give a
  `file:` to play a WAV.)
- **Music** loops from WAV files referenced by `data/music.yaml` (`menu` / `dungeon` / `shop`),
  found under `data/audio/`. Files are optional — a missing one just leaves that track silent.

Music files must be **PCM WAV** (8/16/32-bit integer; float WAVs are not supported). The
engine resamples and downmixes automatically, so rate and channel count don't matter. Convert
an MP3 with [ffmpeg](https://ffmpeg.org/):

```bash
ffmpeg -i song.mp3 -acodec pcm_s16le data/audio/dungeon.wav
```

## Development

Run the test suite (headless playtests against a real game world):

```bash
python -m pytest tests/
```

#### Coverage

Measure test coverage with `pytest-cov` (the source is configured in `pyproject.toml`, so a
bare `--cov` covers `src/`). An HTML report is the most readable — written to `htmlcov/`, open
`htmlcov/index.html`:

```bash
python -m pytest --cov --cov-report=html
```

Or print a terminal summary instead:

```bash
python -m pytest --cov --cov-report=term-missing
```

Lint and format with `ruff`:

```bash
python -m ruff check --fix . && python -m ruff format .
```

Type-check with `pyright` (strict mode; `pyproject.toml` already scopes it to `src/`, so run it plain and keep it at zero errors):

```bash
pyright
```

Tests load their own data from `tests/fixtures/` (via `WIZARDLIKE_DATA_DIR`), so they stay independent of the content in `data/`.

### Debugging

Set `WIZARDLIKE_DEBUG=1` to stream per-frame and per-system debug logs to stderr (unset = silent). When chasing a crash, the last line printed is the operation that crashed:

```bash
WIZARDLIKE_DEBUG=1 python -m src.main 2> debug.log
```
