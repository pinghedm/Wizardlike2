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

- **Formatting & Linting:** Code must be formatted and linted with `ruff`.
- **Type Safety:** Use Type Hints and `StrEnum` for ingredient/spell identifiers.
- **Data Integrity:** All new items or recipes must be added to `data/ingredients.yaml` or `data/spells.yaml` and pass `tools/validate_data.py`.
- **Function Calls:** Use explicit keyword arguments for functions with many parameters (e.g., `generate_dungeon`).
- **Architectural Patterns:**
    - **ECS Idiomatic**: Prefer ECS components for transient states (like Modals) over global flags in `GameState`.
    - **Decoupling**: Keep systems decoupled by having them query the ECS for data rather than passing references.
    - **Simplicity**: Favor direct function calls and module-level constants over complex global configuration objects.

## Development Workflow

- **Data Integrity:** Always run `./venv/bin/python tools/validate_data.py` before committing changes to any YAML data files.
- **Code Quality:** Run `./venv/bin/python -m ruff check --fix . && ./venv/bin/python -m ruff format .` to maintain formatting and linting compliance.
- **Verification:** Ensure the game runs and transitions through levels correctly after any changes to `procgen.py` or input logic.

## Key Files
- `src/main.py`: Entry point, main game loop, and system orchestration.
- `src/components.py`: ECS component definitions.
- `src/procgen.py`: Dungeon generation logic and level transition orchestration.
- `src/input_handlers.py`: Translation of user input into game actions.
- `src/ui_systems.py`: UI rendering processors, including the ModalSystem.
- `src/states.py`: Game state definitions and navigation enums.
- `src/constants.py`: Project-wide constants.
- `data/`: YAML configuration for ingredients, spells, tiles, and characters.
