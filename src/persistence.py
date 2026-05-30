import json
import os
import pickle

import esper

from src.components import Inventory, ItemType, KnownRecipes, SpellType
from src.constants import SAVE_DIR
from src.ecs_helpers import get_singleton

# Cross-run progression (grimoire + gold), one file so it can grow more fields later.
META_FILE = os.path.join(SAVE_DIR, 'meta.json')
SAVE_FILE = os.path.join(SAVE_DIR, 'savegame.sav')


def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR, exist_ok=True)


def _serialize_recipes(recipes: dict) -> dict:
    serialized = {}
    for spell_type, combinations in recipes.items():
        spell_id = spell_type.value if hasattr(spell_type, 'value') else spell_type
        serialized[spell_id] = [
            [item.value if hasattr(item, 'value') else item for item in combo] for combo in combinations
        ]
    return serialized


def _deserialize_recipes(serialized: dict) -> dict:
    recipes = {}
    for spell_id, combos in serialized.items():
        stype = SpellType(spell_id)
        recipes[stype] = {tuple(ItemType(i) for i in combo) for combo in combos}
    return recipes


def save_meta():
    """Persist cross-run progression, gathered from the live world."""
    ensure_save_dir()
    recipes = get_singleton(KnownRecipes)
    inventory = get_singleton(Inventory)
    data = {
        'grimoire': _serialize_recipes(recipes.recipes if recipes else {}),
        'gold': inventory.items.get(ItemType.GOLD, 0) if inventory else 0,
    }
    with open(META_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_meta() -> dict:
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
    snapshot = [esper.components_for_entity(ent) for ent in esper.get_entities()]
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
