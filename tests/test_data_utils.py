"""load_str_enum_from_yaml builds a StrEnum from a YAML id list, falling back to a single
NONE member when the file is missing or lacks the root key."""

from enum import StrEnum

from src.data_utils import load_str_enum_from_yaml


def test_loads_ids_into_a_str_enum(tmp_path):
    path = tmp_path / 'things.yaml'
    path.write_text('things:\n  - id: fire\n  - id: water\n')

    enum_cls = load_str_enum_from_yaml('Thing', str(path), 'things')

    assert issubclass(enum_cls, StrEnum)
    assert enum_cls.FIRE == 'fire'
    assert enum_cls.WATER == 'water'


def test_missing_file_yields_a_lone_none_member(tmp_path):
    enum_cls = load_str_enum_from_yaml('Thing', str(tmp_path / 'absent.yaml'), 'things')

    assert [member.value for member in enum_cls] == ['none']


def test_missing_root_key_yields_a_lone_none_member(tmp_path):
    path = tmp_path / 'other.yaml'
    path.write_text('other: []\n')

    enum_cls = load_str_enum_from_yaml('Thing', str(path), 'things')

    assert enum_cls.NONE == 'none'
