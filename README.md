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

- **Arrow Keys**: Move your character (bump into enemies to attack).
- **C**: Open/Close the Crafting Menu.
- **S**: Open/Close the Spellcasting Menu.
- **Escape**: Open the main menu.
- **In Crafting Menu**:
  - **Up/Down**: Navigate your inventory.
  - **Left/Right**: Add/Remove ingredients to your mix.
  - **Enter**: Attempt to combine ingredients.
  - **C / Escape**: Return to the dungeon.
- **In Spellcasting Menu**:
  - **Up/Down**: Select a known spell.
  - **Enter**: Choose the spell, then use the **Arrow Keys** to aim and **Enter** to cast.
  - **S / Escape**: Cancel.

## Crafting & Discovery

- Explore the dungeon to find glowing ingredients scattered on the floor.
- Collect ingredients to add them to your inventory.
- Open the **Spellbook (C)** to experiment with combinations.
- Successfully crafting a spell will record the recipe in your Spellbook and grant you spell charges.

## Adding Content

All game data is defined in the `data/` directory.

- `ingredients.yaml`: Add new reagents or change their visual properties.
- `spells.yaml`: Add new spell recipes and define their potency (charges).

_Always run the data validator after modifying these files:_

```bash
python -m tools.validate_data
```

## Development

Run the test suite (headless playtests against a real game world):

```bash
python -m pytest tests/
```

Lint and format with `ruff`:

```bash
python -m ruff check --fix . && python -m ruff format .
```

Tests load their own data from `tests/fixtures/` (via `WIZARDLIKE_DATA_DIR`), so they stay independent of the content in `data/`.

### Debugging

Set `WIZARDLIKE_DEBUG=1` to stream per-frame and per-system debug logs to stderr (unset = silent). When chasing a crash, the last line printed is the operation that crashed:

```bash
WIZARDLIKE_DEBUG=1 python -m src.main 2> debug.log
```
