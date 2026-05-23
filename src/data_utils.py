from enum import StrEnum

import yaml


def load_str_enum_from_yaml(enum_name: str, file_path: str, root_key: str):
    """Creates a StrEnum class from a YAML file's list of items with 'id' fields."""
    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
            names = {item['id'].upper(): item['id'] for item in data[root_key]}
            return StrEnum(enum_name, names)
    except FileNotFoundError, KeyError:
        return StrEnum(enum_name, {'NONE': 'none'})
