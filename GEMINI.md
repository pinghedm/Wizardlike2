# WizardLike

WizardLike is a 2D roguelike game inspired by *Chocobo's Mystery Dungeon*. It features procedural dungeon generation, an Entity-Component-System (ECS) architecture, and a dynamic spell discovery system based on combining ingredients.

## Project Overview

- **Language:** Python 3.14
- **Rendering:** `tcod` with a dual-purpose tileset (ASCII/Text + Procedural Blocks).
- **Architecture:** ECS (using `esper`).
- **Data:** YAML-defined ingredients and spell recipes.

## Directory Structure

- `src/`: Core game source code.
- `data/`: YAML configuration files.
- `tools/`: Development utilities (e.g., data validation).
- `venv/`: Virtual environment.

## Building and Running

### Setup
1. Create a virtual environment:
   ```bash
   python3.14 -m venv venv
   ```
2. Sync dependencies:
   ```bash
   ./venv/bin/pip install pip-tools
   ./venv/bin/pip-sync requirements.txt requirements-dev.txt
   ```

### Running the Game
```bash
./venv/bin/python src/main.py
```

### Data Validation
Always run the validation tool before committing changes to data files:
```bash
./venv/bin/python tools/validate_data.py
```

## Development Conventions

- **Formatting:** Code must be formatted with `black` (line length 120, single quotes).
- **Linting:** `ruff` is used for linting and formatting.
- **Type Safety:** Use Type Hints and `StrEnum` for ingredient/spell identifiers.
- **Data Integrity:** All new items or recipes must be added to `data/ingredients.yaml` or `data/spells.yaml` and pass `tools/validate_data.py`.
