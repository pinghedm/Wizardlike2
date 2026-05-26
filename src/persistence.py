import json
import os
import pickle

import esper

from src.components import ItemType, SpellType
from src.constants import SAVE_DIR

GRIMOIRE_FILE = os.path.join(SAVE_DIR, 'grimoire.json')
SAVE_FILE = os.path.join(SAVE_DIR, 'savegame.sav')


def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR, exist_ok=True)


def save_grimoire(recipes: dict):
    ensure_save_dir()
    serialized = {}
    for spell_type, combinations in recipes.items():
        spell_id = spell_type.value if hasattr(spell_type, 'value') else spell_type
        serialized[spell_id] = [
            [item.value if hasattr(item, 'value') else item for item in combo] for combo in combinations
        ]

    with open(GRIMOIRE_FILE, 'w') as f:
        json.dump(serialized, f, indent=2)


def load_grimoire() -> dict:
    if not os.path.exists(GRIMOIRE_FILE):
        return {}

    try:
        with open(GRIMOIRE_FILE) as f:
            data = json.load(f)

        # Convert IDs back to Enums
        recipes = {}
        for spell_id, combos in data.items():
            stype = SpellType(spell_id)
            recipes[stype] = {tuple(ItemType(i) for i in combo) for combo in combos}
        return recipes
    except json.JSONDecodeError, OSError, ValueError:
        return {}


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
