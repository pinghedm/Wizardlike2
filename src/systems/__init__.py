"""Game logic systems.

Split across submodules: `core` (visual-effect triggers, damage/combat math,
movement, and the Death/Action/Status/FOV/Render processors), `ai` (enemy behaviors
and the AISystem), and `crafting` (spell config lookup, recipe matching, and casting).
Public names are re-exported here so callers import them as `from src.systems import X`.
Module-private helpers (e.g. the `_process_*` AI behaviors) are not re-exported; tests
that exercise them import from the submodule directly.
"""

from src.systems.ai import AISystem
from src.systems.core import (
    EFFECT_COLORS,
    PROJECTILE_GLYPHS,
    ActionSystem,
    DeathSystem,
    FOVSystem,
    RenderSystem,
    StatusSystem,
    apply_effect,
    deal_damage,
    get_cooldown,
    is_game_active,
    move_entity,
    roll_loot,
    spawn_particle_burst,
    trigger_cast_visual,
    trigger_screen_flash,
)
from src.systems.crafting import (
    can_craft_known_spell,
    cast_spell,
    craft_known_spell,
    get_spell_config,
    is_reagent,
    match_recipe,
)

__all__ = [
    'EFFECT_COLORS',
    'PROJECTILE_GLYPHS',
    'ActionSystem',
    'AISystem',
    'DeathSystem',
    'FOVSystem',
    'RenderSystem',
    'StatusSystem',
    'apply_effect',
    'can_craft_known_spell',
    'cast_spell',
    'craft_known_spell',
    'deal_damage',
    'get_cooldown',
    'get_spell_config',
    'is_game_active',
    'is_reagent',
    'match_recipe',
    'move_entity',
    'roll_loot',
    'spawn_particle_burst',
    'trigger_cast_visual',
    'trigger_screen_flash',
]
