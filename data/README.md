# Data Directory

This directory contains the YAML data files that define game content.

## Ingredients (`ingredients.yaml`)

Defines all pickable items/ingredients. These are dynamically loaded into the game as `ItemType` enums.

### Schema

| Field   | Type              | Description                          |
| :------ | :---------------- | :----------------------------------- |
| `id`    | `string`          | Unique identifier (snake_case).      |
| `name`  | `string`          | Display name for the UI.             |
| `char`  | `string`          | Unicode character for map rendering. |
| `color` | `[int, int, int]` | RGB color array (0-255).             |

### Example
```yaml
ingredients:
  - id: fire_crystal
    name: Fire Crystal
    char: "\u2588"
    color: [255, 0, 0]
```

## Spells (`spells.yaml`)

Defines recipes for combining ingredients into spells.

### Schema

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string` | Unique identifier for the spell. |
| `name` | `string` | Display name of the spell. |
| `recipes` | `list[object]` | List of recipes. Each recipe has `ingredients` (list of strings) and `charges` (int). |

### Example
```yaml
spells:
  - id: fireball
    name: Fireball
    recipes:
      - ingredients: [fire_crystal, fire_crystal]
        charges: 3
```

## Validation


Run the validation script after making changes:

```bash
./venv/bin/python tools/validate_data.py
```
