import json
import os
import pickle
from typing import TypedDict

import esper

from src.components import Inventory, ItemType, KnownRecipes, SpellType
from src.constants import SAVE_DIR
from src.ecs_helpers import try_get_singleton

# Cross-run progression (grimoire + gold), one file so it can grow more fields later.
META_FILE = os.path.join(SAVE_DIR, 'meta.json')
SAVE_FILE = os.path.join(SAVE_DIR, 'savegame.sav')

# A discovered spell maps to the set of ingredient combinations that craft it.
Grimoire = dict[SpellType, set[tuple[ItemType, ...]]]


class MetaData(TypedDict):
    """Cross-run progression loaded from / saved to meta.json."""

    recipes: Grimoire
    gold: int


def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR, exist_ok=True)


def _serialize_recipes(recipes: Grimoire) -> dict[str, list[list[str]]]:
    return {
        spell_type.value: [[item.value for item in combo] for combo in combinations]
        for spell_type, combinations in recipes.items()
    }


def _deserialize_recipes(serialized: dict[str, list[list[str]]]) -> Grimoire:
    return {
        SpellType(spell_id): {tuple(ItemType(i) for i in combo) for combo in combos}
        for spell_id, combos in serialized.items()
    }


def save_meta():
    """Persist cross-run progression, gathered from the live world."""
    ensure_save_dir()
    recipes = try_get_singleton(KnownRecipes)
    inventory = try_get_singleton(Inventory)
    data = {
        'grimoire': _serialize_recipes(recipes.recipes if recipes else {}),
        'gold': inventory.items.get(ItemType.GOLD, 0) if inventory else 0,
    }
    with open(META_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_meta() -> MetaData:
    """Load cross-run progression: {'recipes': ..., 'gold': ...}.

    Falls back to an empty grimoire and zero gold when the file is absent or corrupt.
    """
    if not os.path.exists(META_FILE):
        return {'recipes': {}, 'gold': 0}

    try:
        with open(META_FILE) as f:
            data = json.load(f)
        return {'recipes': _deserialize_recipes(data.get('grimoire', {})), 'gold': data.get('gold', 0)}
    except json.JSONDecodeError, OSError, ValueError:
        return {'recipes': {}, 'gold': 0}


def save_game():
    """Snapshot every live entity and its components to disk.

    Pickles a list of component tuples (one per entity). Because no component
    references another entity by id, entities can be recreated in any order
    without remapping. The whole world is captured -- map, player, enemies, and
    the singletons (GameState, Configuration, Keybindings, ...) -- so loading
    resumes exactly where the player left off. (A side effect is that the saved
    game embeds the Configuration it was created with, which is acceptable for a
    local single-player suspend-save and preserves any remapped keybindings.)
    """
    ensure_save_dir()
    snapshot: list[tuple[object, ...]] = [esper.components_for_entity(ent) for ent in esper.get_entities()]
    with open(SAVE_FILE, 'wb') as f:
        pickle.dump(snapshot, f)


def load_game():
    """Replace the live world with a previously saved snapshot.

    Clears the entity/component database (processors survive clear_database and
    do not need re-adding) and recreates every saved entity.
    """
    if not os.path.exists(SAVE_FILE):
        return

    with open(SAVE_FILE, 'rb') as f:
        snapshot = pickle.load(f)

    esper.clear_database()
    for components in snapshot:
        esper.create_entity(*components)


def delete_save():
    if os.path.exists(SAVE_FILE):
        os.remove(SAVE_FILE)


def has_save() -> bool:
    return os.path.exists(SAVE_FILE)
