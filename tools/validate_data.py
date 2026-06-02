import sys
from pathlib import Path

import yaml

from src.components import EffectType

VALID_EFFECT_INFO = {
    EffectType.DAMAGE: ['power'],
    EffectType.HEAL: ['power'],
    EffectType.SLOW: ['duration'],
    EffectType.HASTE: ['duration'],
    EffectType.POISON: ['power', 'duration'],
    EffectType.REGEN: ['power', 'duration'],
    EffectType.STUN: ['duration'],
    EffectType.SHIELD: ['power', 'duration'],
    EffectType.DRAIN: ['power', 'lifesteal'],
    EffectType.KNOCKBACK: ['power'],
}


VALID_BEHAVIORS = {'CHASE', 'FLEE', 'PATROL', 'GUARD'}

ALLOWED_SPELL_FIELDS = {
    'id',
    'name',
    'description',
    'range',
    'radius',
    'effects',
    'recipes',
    'shop',
    'rare',
}

ALLOWED_INGREDIENT_FIELDS = {'id', 'name', 'char', 'sprite', 'color', 'price'}

ALLOWED_SHOP_FIELDS = {'price', 'charges'}

ALLOWED_ENEMY_FIELDS = {
    'id',
    'sprite',
    'char',
    'color',
    'hp',
    'damage',
    'speed',
    'behavior',
    'floors',
    'ability',
    'blocks_movement',
    'guardian',
    'drops',
}

ALLOWED_DROP_FIELDS = {'type', 'min', 'max', 'chance'}


def validate_effects(effects, context_label: str) -> int:
    """Validate a list of effect dicts (shared by spells and enemy abilities).

    Returns the number of errors found and prints each one.
    """
    if not isinstance(effects, list) or not effects:
        print(f'ERROR: {context_label} must have a non-empty list of "effects".')
        return 1

    valid_effect_type_names = [e.value for e in VALID_EFFECT_INFO.keys()]
    errors = 0
    for eff_idx, effect in enumerate(effects):
        etype_str = effect.get('type')
        if not etype_str:
            print(f'ERROR: {context_label} effect #{eff_idx} missing "type".')
            errors += 1
            continue

        if etype_str not in valid_effect_type_names:
            print(f'ERROR: {context_label} effect #{eff_idx} has invalid type: "{etype_str}".')
            errors += 1
            continue

        etype = EffectType(etype_str)
        for req_field in VALID_EFFECT_INFO[etype]:
            if req_field not in effect:
                print(f'ERROR: {context_label} effect #{eff_idx} ({etype_str}) missing required field "{req_field}".')
                errors += 1
            elif not isinstance(effect[req_field], int) or effect[req_field] <= 0:
                print(f'ERROR: {context_label} effect #{eff_idx} field "{req_field}" must be a positive integer.')
                errors += 1
    return errors


def validate_shop(shop, context_label: str) -> int:
    """Validate a spell's `shop` listing. Returns the number of errors found."""
    if not isinstance(shop, dict):
        print(f'ERROR: {context_label} "shop" must be a mapping.')
        return 1

    errors = 0
    for key in sorted(set(shop) - ALLOWED_SHOP_FIELDS):
        print(f'ERROR: {context_label} shop has unexpected field "{key}".')
        errors += 1
    for f in ('price', 'charges'):
        if f not in shop:
            print(f'ERROR: {context_label} shop missing "{f}".')
            errors += 1
        elif not isinstance(shop[f], int) or shop[f] <= 0:
            print(f'ERROR: {context_label} shop "{f}" must be a positive integer.')
            errors += 1
    return errors


def validate_drops(drops, ing_ids, context_label: str) -> int:
    """Validate an enemy's loot `drops` list. Returns the number of errors found."""
    if not isinstance(drops, list):
        print(f'ERROR: {context_label} "drops" must be a list.')
        return 1

    errors = 0
    for idx, drop in enumerate(drops):
        if not isinstance(drop, dict):
            print(f'ERROR: {context_label} drop #{idx} must be a mapping.')
            errors += 1
            continue

        for key in sorted(set(drop) - ALLOWED_DROP_FIELDS):
            print(f'ERROR: {context_label} drop #{idx} has unexpected field "{key}".')
            errors += 1

        if 'type' not in drop:
            print(f'ERROR: {context_label} drop #{idx} missing "type".')
            errors += 1
        elif drop['type'] not in ing_ids:
            print(f'ERROR: {context_label} drop #{idx} uses unknown item: "{drop["type"]}".')
            errors += 1

        for f in ('min', 'max'):
            if f in drop and (not isinstance(drop[f], int) or drop[f] < 0):
                print(f'ERROR: {context_label} drop #{idx} "{f}" must be a non-negative integer.')
                errors += 1

        lo, hi = drop.get('min'), drop.get('max')
        if isinstance(lo, int) and isinstance(hi, int) and lo > hi:
            print(f'ERROR: {context_label} drop #{idx} min must be <= max.')
            errors += 1

        if 'chance' in drop and (not isinstance(drop['chance'], (int, float)) or drop['chance'] <= 0):
            print(f'ERROR: {context_label} drop #{idx} "chance" must be a positive number.')
            errors += 1

    return errors


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

        for field in sorted(set(ing) - ALLOWED_INGREDIENT_FIELDS):
            print(f'ERROR: Ingredient "{iid}" has unexpected field "{field}".')
            errors += 1

        if 'price' in ing and (not isinstance(ing['price'], int) or ing['price'] <= 0):
            print(f'ERROR: Ingredient "{iid}" price must be a positive integer.')
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

            unexpected = set(spell) - ALLOWED_SPELL_FIELDS
            for field in sorted(unexpected):
                print(f'ERROR: Spell "{sid}" has unexpected field "{field}".')
                errors += 1

            if 'description' in spell and not isinstance(spell['description'], str):
                print(f'ERROR: Spell "{sid}" description must be a string.')
                errors += 1

            if 'rare' in spell and not isinstance(spell['rare'], bool):
                print(f'ERROR: Spell "{sid}" rare must be a boolean.')
                errors += 1

            if 'shop' in spell:
                errors += validate_shop(spell['shop'], f'Spell "{sid}"')

            for field in ['range', 'radius']:
                if field not in spell:
                    print(f'ERROR: Spell "{sid}" missing "{field}".')
                    errors += 1
                elif not isinstance(spell[field], int) or spell[field] < 0:
                    print(f'ERROR: Spell "{sid}" {field} must be a non-negative integer.')
                    errors += 1

            errors += validate_effects(spell.get('effects', []), f'Spell "{sid}"')

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

    # 4. Validate Enemies
    enemies_file = data_dir / 'enemies.yaml'
    if not enemies_file.exists():
        print(f'Note: {enemies_file} not found, skipping enemy validation.')
    else:
        print(f'Validating {enemies_file}...')
        try:
            with open(enemies_file) as f:
                enemies_data = yaml.safe_load(f)
        except Exception as e:
            print(f'ERROR: Failed to parse enemies.yaml: {e}')
            return False

        enemy_ids = set()
        for i, enemy in enumerate(enemies_data.get('enemies', [])):
            if 'id' not in enemy:
                print(f'ERROR: Enemy #{i} missing "id".')
                errors += 1
                continue
            eid = enemy['id']
            if eid in enemy_ids:
                print(f'ERROR: Duplicate enemy ID: "{eid}"')
                errors += 1
            enemy_ids.add(eid)

            required_fields = ['sprite', 'hp', 'damage', 'speed', 'behavior', 'floors', 'color']
            for field in required_fields:
                if field not in enemy:
                    print(f'ERROR: Enemy "{eid}" missing "{field}".')
                    errors += 1

            unexpected = set(enemy) - ALLOWED_ENEMY_FIELDS
            for field in sorted(unexpected):
                print(f'ERROR: Enemy "{eid}" has unexpected field "{field}".')
                errors += 1

            if 'behavior' in enemy and enemy['behavior'] not in VALID_BEHAVIORS:
                print(f'ERROR: Enemy "{eid}" behavior must be one of {sorted(VALID_BEHAVIORS)}.')
                errors += 1

            for field in ('blocks_movement', 'guardian'):
                if field in enemy and not isinstance(enemy[field], bool):
                    print(f'ERROR: Enemy "{eid}" {field} must be a boolean.')
                    errors += 1

            if 'floors' in enemy:
                floors = enemy['floors']
                if not isinstance(floors, list) or len(floors) != 2 or not all(isinstance(f, int) for f in floors):
                    print(f'ERROR: Enemy "{eid}" floors must be a list of 2 integers.')
                    errors += 1

            if 'color' in enemy:
                color = enemy['color']
                if not isinstance(color, list) or len(color) != 3 or not all(isinstance(c, int) for c in color):
                    print(f'ERROR: Enemy "{eid}" color must be a list of 3 integers.')
                    errors += 1

            if 'ability' in enemy:
                ability = enemy['ability']
                rng = ability.get('range')
                if not isinstance(rng, int) or rng < 0:
                    print(f'ERROR: Enemy "{eid}" ability range must be a non-negative integer.')
                    errors += 1
                errors += validate_effects(ability.get('effects', []), f'Enemy "{eid}" ability')

            if 'drops' in enemy:
                errors += validate_drops(enemy['drops'], ing_ids, f'Enemy "{eid}"')

    if errors == 0:
        print('SUCCESS: All data files are valid.')
        return True
    else:
        print(f'FAILED: {errors} total errors found.')
        return False


if __name__ == '__main__':
    if not validate_data():
        sys.exit(1)
