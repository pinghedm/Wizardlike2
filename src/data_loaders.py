import yaml
from enum import StrEnum

def _load_enum(file_path: str, root_key: str, enum_name: str) -> StrEnum:
    try:
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
            names = {item['id'].upper(): item['id'] for item in data[root_key]}
            return StrEnum(enum_name, names)
    except (FileNotFoundError, KeyError):
        return StrEnum(enum_name, {'NONE': 'none'})

def load_ingredients_config():
    with open('data/ingredients.yaml', 'r') as f:
        data = yaml.safe_load(f)['ingredients']
        return {item['id']: item for item in data}

def load_spells_config():
    from components import ItemType
    with open('data/spells.yaml', 'r') as f:
        data = yaml.safe_load(f)['spells']
        for spell in data:
            processed_recipes = []
            for r_data in spell['recipes']:
                processed_recipes.append({
                    'ingredients': tuple(sorted([ItemType(id) for id in r_data['ingredients']])),
                    'charges': r_data['charges']
                })
            spell['recipes'] = processed_recipes
        return data
