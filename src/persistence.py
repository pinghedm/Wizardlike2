import json
import os
import pickle
from typing import TypedDict

import esper
import tcod.event
from tcod.sdl.joystick import ControllerAxis, ControllerButton

from src.components import (
    ControllerBinding,
    InputAction,
    Inventory,
    ItemType,
    Keybindings,
    KnownRecipes,
    MetaSaveState,
    Settings,
    SpellType,
)
from src.constants import SAVE_DIR
from src.ecs_helpers import try_get_singleton
from src.states import PostCastBehavior

# Cross-run progression and preferences, one file so it can grow more fields later.
META_FILE = os.path.join(SAVE_DIR, 'meta.json')
SAVE_FILE = os.path.join(SAVE_DIR, 'savegame.sav')

# A discovered spell maps to the set of ingredient combinations that craft it.
Grimoire = dict[SpellType, set[tuple[ItemType, ...]]]


# The JSON shapes written to / read from meta.json, before parsing into runtime types.
# Loader-internal: app code sees only the parsed MetaData below.
class _RawControl(TypedDict, total=False):
    axis: str
    button: str


class _RawKeybindings(TypedDict, total=False):
    bindings: dict[str, int]
    controller: dict[str, _RawControl]


class _RawSettings(TypedDict, total=False):
    post_cast: str
    keybindings: _RawKeybindings


class _RawMeta(TypedDict, total=False):
    grimoire: dict[str, list[list[str]]]
    gold: int
    settings: _RawSettings


class MetaData(TypedDict):
    """Cross-run progression and preferences loaded from / saved to meta.json."""

    recipes: Grimoire
    gold: int
    keybindings: Keybindings
    post_cast: PostCastBehavior


def ensure_save_dir():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR, exist_ok=True)


def mark_meta_dirty():
    """Flag cross-run progression as changed in-world (e.g. a gold pickup) so the
    MetaSaveSystem persists it at the next paused moment, rather than writing now."""
    state = try_get_singleton(MetaSaveState)
    if state is not None:
        state.dirty = True


def flush_meta():
    """Persist cross-run progression now if it has unsaved in-world changes. Used at exit,
    where the per-frame MetaSaveSystem won't get another chance to flush."""
    state = try_get_singleton(MetaSaveState)
    if state is not None and state.dirty:
        save_meta()


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


def _serialize_control(control: ControllerBinding) -> _RawControl:
    # Tag the kind so a button and an axis with the same int value don't collide on load.
    if isinstance(control, ControllerAxis):
        return {'axis': control.name}
    return {'button': control.name}


def _deserialize_control(control: _RawControl) -> ControllerBinding:
    axis = control.get('axis')
    if axis is not None:
        return ControllerAxis[axis]
    button = control.get('button')
    if button is not None:
        return ControllerButton[button]
    raise ValueError(f'serialized control has neither axis nor button: {control!r}')


def _serialize_keybindings(keybindings: Keybindings) -> _RawKeybindings:
    return {
        'bindings': {action.name: int(sym) for action, sym in keybindings.bindings.items()},
        'controller': {action.name: _serialize_control(c) for action, c in keybindings.controller.items()},
    }


def _deserialize_keybindings(data: _RawKeybindings) -> Keybindings:
    return Keybindings(
        bindings={InputAction[name]: tcod.event.KeySym(value) for name, value in data.get('bindings', {}).items()},
        controller={InputAction[name]: _deserialize_control(c) for name, c in data.get('controller', {}).items()},
    )


def _read_meta_file() -> _RawMeta:
    """The raw meta.json dict, or {} when it is absent or corrupt."""
    if not os.path.exists(META_FILE):
        return {}
    try:
        with open(META_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError, OSError, ValueError:
        return {}


def save_meta():
    """Persist cross-run progression and preferences, gathered from the live world.

    Merges into the existing file and only writes a section whose source component is
    present, so saving from a context that lacks one (e.g. the title screen has no
    player) never clobbers the others.
    """
    ensure_save_dir()
    data = _read_meta_file()
    recipes = try_get_singleton(KnownRecipes)
    inventory = try_get_singleton(Inventory)
    settings = try_get_singleton(Settings)
    if recipes is not None:
        data['grimoire'] = _serialize_recipes(recipes.recipes)
    if inventory is not None:
        data['gold'] = inventory.items.get(ItemType.GOLD, 0)
    if settings is not None:
        data['settings'] = {
            'post_cast': settings.post_cast.value,
            'keybindings': _serialize_keybindings(settings.keybindings),
        }
    with open(META_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    # Any pending in-world change is now on disk, whether this write was a deliberate
    # commit (purchase, remap, discovery) or a MetaSaveSystem flush.
    state = try_get_singleton(MetaSaveState)
    if state is not None:
        state.dirty = False


def load_meta() -> MetaData:
    """Load cross-run progression and preferences, filling defaults for missing fields.

    Always returns a complete record (empty grimoire, zero gold, empty saved bindings,
    default post-cast) when the file is absent, corrupt, or predates a field.
    """
    data = _read_meta_file()
    settings: _RawSettings = data.get('settings', {})
    return {
        'recipes': _deserialize_recipes(data.get('grimoire', {})),
        'gold': data.get('gold', 0),
        'keybindings': _deserialize_keybindings(settings.get('keybindings', {})),
        'post_cast': PostCastBehavior(settings.get('post_cast', PostCastBehavior.STAY.value)),
    }


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
