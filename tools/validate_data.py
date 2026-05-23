import sys
from pathlib import Path

import yaml


def validate_data() -> bool:
    data_dir = Path('data')
    ingredients_file = data_dir / 'ingredients.yaml'
    spells_file = data_dir / 'spells.yaml'

    errors = 0

    # 1. Validate Ingredients
    if not ingredients_file.exists():
        print(f'ERROR: {ingredients_file} not found.')
        return False

    print(f'Validating {ingredients_file}...')
    try:
        with open(ingredients_file) as f:
            ing_data = yaml.safe_load(f)
    except Exception as e:
        print(f'ERROR: Failed to parse ingredients.yaml: {e}')
        return False

    ing_ids = set()
    for i, ing in enumerate(ing_data.get('ingredients', [])):
        if 'id' not in ing:
            print(f'ERROR: Ingredient #{i} missing "id".')
            errors += 1
            continue
        iid = ing['id']
        if iid in ing_ids:
            print(f'ERROR: Duplicate ingredient ID: "{iid}"')
            errors += 1
        ing_ids.add(iid)

        for field in ['name', 'char', 'color']:
            if field not in ing:
                print(f'ERROR: Ingredient "{iid}" missing "{field}".')
                errors += 1

    # 2. Validate Spells
    if not spells_file.exists():
        print(f'Note: {spells_file} not found, skipping spell validation.')
    else:
        print(f'Validating {spells_file}...')
        try:
            with open(spells_file) as f:
                spell_data = yaml.safe_load(f)
        except Exception as e:
            print(f'ERROR: Failed to parse spells.yaml: {e}')
            return False

        spell_ids = set()
        for i, spell in enumerate(spell_data.get('spells', [])):
            if 'id' not in spell:
                print(f'ERROR: Spell #{i} missing "id".')
                errors += 1
                continue
            sid = spell['id']
            if sid in spell_ids:
                print(f'ERROR: Duplicate spell ID: "{sid}"')
                errors += 1
            spell_ids.add(sid)

            if 'name' not in spell:
                print(f'ERROR: Spell "{sid}" missing "name".')
                errors += 1

            for field in ['range', 'radius']:
                if field not in spell:
                    print(f'ERROR: Spell "{sid}" missing "{field}".')
                    errors += 1
                elif not isinstance(spell[field], int) or spell[field] < 0:
                    print(f'ERROR: Spell "{sid}" {field} must be a non-negative integer.')
                    errors += 1

            effects = spell.get('effects', [])
            if not isinstance(effects, list) or not effects:
                print(f'ERROR: Spell "{sid}" must have a non-empty list of "effects".')
                errors += 1
            else:
                valid_effect_types = {
                    'damage': ['power'],
                    'slow': ['duration'],
                    'heal': ['power'],
                }
                for eff_idx, effect in enumerate(effects):
                    etype = effect.get('type')
                    if not etype:
                        print(f'ERROR: Spell "{sid}" effect #{eff_idx} missing "type".')
                        errors += 1
                        continue

                    if etype not in valid_effect_types:
                        print(f'ERROR: Spell "{sid}" effect #{eff_idx} has invalid type: "{etype}".')
                        errors += 1
                        continue

                    for req_field in valid_effect_types[etype]:
                        if req_field not in effect:
                            print(
                                f'ERROR: Spell "{sid}" effect #{eff_idx} ({etype}) '
                                f'missing required field "{req_field}".'
                            )
                            errors += 1
                        elif not isinstance(effect[req_field], int) or effect[req_field] <= 0:
                            print(
                                f'ERROR: Spell "{sid}" effect #{eff_idx} '
                                f'field "{req_field}" must be a positive integer.'
                            )
                            errors += 1

            recipes = spell.get('recipes', [])
            if not isinstance(recipes, list) or not recipes:
                print(f'ERROR: Spell "{sid}" must have a non-empty list of "recipes".')
                errors += 1
                continue

            for r_idx, recipe in enumerate(recipes):
                if 'ingredients' not in recipe or 'charges' not in recipe:
                    print(f'ERROR: Spell "{sid}" recipe #{r_idx} missing "ingredients" or "charges".')
                    errors += 1
                    continue

                if not isinstance(recipe['charges'], int) or recipe['charges'] <= 0:
                    print(f'ERROR: Spell "{sid}" recipe #{r_idx} charges must be a positive integer.')
                    errors += 1

                for ing_id in recipe['ingredients']:
                    if ing_id not in ing_ids:
                        print(f'ERROR: Spell "{sid}" recipe #{r_idx} uses unknown ingredient: "{ing_id}".')
                        errors += 1

    # 3. Validate Tiles
    tiles_file = data_dir / 'tiles.yaml'
    if not tiles_file.exists():
        print(f'Note: {tiles_file} not found, skipping tile validation.')
    else:
        print(f'Validating {tiles_file}...')
        try:
            with open(tiles_file) as f:
                tiles_data = yaml.safe_load(f)
        except Exception as e:
            print(f'ERROR: Failed to parse tiles.yaml: {e}')
            return False

        tile_ids = set()
        for i, tile in enumerate(tiles_data.get('tiles', [])):
            if 'id' not in tile:
                print(f'ERROR: Tile #{i} missing "id".')
                errors += 1
                continue
            tid = tile['id']
            if tid in tile_ids:
                print(f'ERROR: Duplicate tile ID: "{tid}"')
                errors += 1
            tile_ids.add(tid)

            for field in ['type', 'depth']:
                if field not in tile:
                    print(f'ERROR: Tile "{tid}" missing "{field}".')
                    errors += 1

            # fg and bg are optional; if missing, engine provides defaults (White/Black)
            for field in ['fg', 'bg']:
                if field in tile:
                    val = tile[field]
                    if not isinstance(val, list) or len(val) != 3 or not all(isinstance(v, int) for v in val):
                        print(f'ERROR: Tile "{tid}" {field} must be a list of 3 integers (RGB).')
                        errors += 1

            if 'depth' in tile:
                depth = tile['depth']
                if not isinstance(depth, list) or len(depth) != 2 or not all(isinstance(d, int) for d in depth):
                    print(f'ERROR: Tile "{tid}" depth must be a list of 2 integers.')
                    errors += 1

    if errors == 0:
        print('SUCCESS: All data files are valid.')
        return True
    else:
        print(f'FAILED: {errors} total errors found.')
        return False


if __name__ == '__main__':
    if not validate_data():
        sys.exit(1)
