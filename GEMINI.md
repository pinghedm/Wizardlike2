# WizardLike

WizardLike is a 2D roguelike game inspired by *Chocobo's Mystery Dungeon*. It features procedural dungeon generation, an Entity-Component-System (ECS) architecture, and a dynamic spell discovery system based on combining ingredients.

## Project Overview

- **Language:** Python 3.14
- **Rendering & input:** `pygame-ce` — pixel-native drawing (Surface blits, `pygame.draw`) and keyboard + SDL2 game-controller input (no mouse). FOV (`src/fov.py`) and pathfinding (`src/pathfinding.py`) are hand-rolled; there is no `tcod` dependency.
- **Architecture:** ECS (using `esper`).
- **Data:** YAML-defined ingredients and spell recipes.

## Directory Structure

- `src/`: Core game source code.
- `data/`: YAML configuration files.
- `tools/`: Development utilities (e.g., data validation).
- `tests/`: Pytest suite, headless test harness, and `tests/fixtures/` (test-owned data).
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
./venv/bin/python -m tools.validate_data
```

### Testing
Run the headless playtest suite:
```bash
./venv/bin/python -m pytest tests/
```
Tests run against a real `esper.World` via `tests/headless_runner.py` (simulate input, tick systems, query state). They load their own data from `tests/fixtures/` rather than `data/` — `tests/conftest.py` sets `WIZARDLIKE_DATA_DIR=tests/fixtures` before import, so tests stay decoupled from shipped game content.

### Type Checking
Static type checking is done with `pyright` in **strict** mode (configured under `[tool.pyright]` in `pyproject.toml`, which scopes checking to `src/` against the venv interpreter, so run it plain):
```bash
./venv/bin/pyright
```
Keep `src/` at zero errors. When a value crosses an untyped boundary (e.g. pygame delivers `event.axis`/`event.button` as a bare `int`), normalize it into our own enum at the edge (`ControllerAxis(event.axis)`) rather than reaching for `# type: ignore`.

## Development Conventions

- **Formatting & Linting:** Code must be formatted and linted with `ruff`.
- **Type Safety:** Use Type Hints and `StrEnum` for ingredient/spell identifiers. Code must pass `pyright` in strict mode (`./venv/bin/pyright`) with zero errors.
- **Data Integrity:** All new items or recipes must be added to `data/ingredients.yaml` or `data/spells.yaml` and pass `python -m tools.validate_data`.
- **Testing:** Tests must not assert against shipped `data/` values; build the recipe/spell/config under test in-fixtures (`tests/fixtures/`) or override it in-test, so balance changes don't break tests.
- **Function Calls:** Use explicit keyword arguments for functions with many parameters (e.g., `generate_dungeon`).
- **Architectural Patterns:**
    - **ECS Idiomatic**: Prefer ECS components for transient states (like Modals) over global flags in `GameState`.
    - **Decoupling**: Keep systems decoupled by having them query the ECS for data rather than passing references.
    - **Simplicity**: Favor direct function calls and module-level constants over complex global configuration objects.
    - **Package re-exports**: `components`, `systems`, and `input_handlers` are packages whose `__init__.py` re-exports the genuine public surface (keep `__all__` public-only — never re-export underscore-prefixed internals just to satisfy a test; redirect such tests to import from the submodule directly). Keep submodule dependencies one-way (no cycles). A data table belongs with its sole consumer (e.g. `STATUS_APPLY` lives in `systems/combat.py`), not in the data package; small standalone helpers and orphan type aliases go in a package-local `utils.py`.

## Development Workflow

- **Data Integrity:** Always run `./venv/bin/python -m tools.validate_data` before committing changes to any YAML data files.
- **Code Quality:** Run `./venv/bin/python -m ruff check --fix . && ./venv/bin/python -m ruff format .` to maintain formatting and linting compliance.
- **Type Checking:** Run `./venv/bin/pyright` before committing; keep it at zero errors.
- **Testing:** Run `./venv/bin/python -m pytest tests/` before committing logic changes.
- **Verification:** Ensure the game runs and transitions through levels correctly after any changes to `procgen.py` or input logic.

## Key Files
- `src/main.py`: Entry point, main game loop, system orchestration, `dispatch_input` (single input router, handles modals) and `update_pause_state`.
- `src/components/`: ECS component package (re-exports its public surface via `__init__.py`, so import as `from src.components import X`). Submodules: `enums.py` (`StatusType`/`EffectType`/`ShopOfferKind`/`InputAction` plus the YAML-loaded `ItemType`/`SpellType` and controller bindings — note the `__module__` pin to `src.components` keeps save-game pickles resolving), `configs.py` (parsed YAML-config TypedDicts), `components.py` (the ECS dataclasses and spell-effect model), `utils.py` (shared type aliases like `Message`).
- `src/systems/`: Game-logic package (re-exported via `__init__.py`; import as `from src.systems import X`). Submodules: `visuals.py` (effect color/glyph tables + `trigger_*`/particle helpers), `movement.py` (`move_entity`, `apply_knockback`, `get_action_cooldown`, `step_toward`), `combat.py` (damage math, `apply_effect`, `STATUS_APPLY`, loot), `processors.py` (Death/Action/Status/FOV/Render processors), `ai.py` (enemy behaviors + `AISystem`), `crafting.py` (`cast_spell`, `match_recipe`, spell config lookup), `utils.py` (`is_game_active`). One-way deps: `visuals`/`movement` → `combat` → `processors`; `ai`/`crafting` build on those.
- `src/procgen.py`: Dungeon generation logic and level transition orchestration.
- `src/input_handlers/`: Input package (re-exported via `__init__.py`; import as `from src.input_handlers import X`). Submodules: `controller.py` (device/event layer, SDL controller binding + remap) and `handlers.py` (per-state `handle_*` action routing, plus the `step_cursor` nav helper).
- `src/ui_systems/`: UI rendering processors. Submodules: `hud.py` (HUDSystem + ModalSystem), `menus.py` (MenuSystem — main/pause, crafting, casting, shop, settings, game over; each screen has a pure `_*_rows`/`_*_lines` content method the tests assert on), `overlays.py` (TargetingOverlaySystem + EffectOverlaySystem), `minimap.py` (MinimapSystem + MapViewSystem).
- `src/render.py`: Pixel geometry — `Viewport`, the map/HUD/minimap rects, and the camera transform (`compute_viewport`).
- `src/ui_draw.py`: Pixel-native drawing primitives (`blit_text`, `blit_segments`, `bar`, `panel`, `fill_alpha`, `scroll_arrows`) shared by the UI systems.
- `src/fov.py`: Recursive-shadowcasting `compute_fov`. `src/pathfinding.py`: grid `Dijkstra` (bounded/unbounded flood + `get_path`) driving `AISystem`.
- `src/states.py`: Game state definitions and navigation enums.
- `src/constants.py`: Project-wide constants, including `DATA_DIR` (override via `WIZARDLIKE_DATA_DIR`).
- `src/ecs_helpers.py`: Leaf ECS-query helpers (`get_singleton`, `actor_name`, `spawn_item_entity`) shared without coupling systems.
- `tests/headless_runner.py`: Headless harness for driving the game in tests.
- `data/`: YAML configuration for ingredients, spells, tiles, and characters.
