"""Game logic systems.

Split across submodules: `visuals` (visual-effect triggers and color/glyph tables),
`movement` (entity movement, knockback, action cooldowns), `combat` (damage math,
status pulses, effect application, loot), `processors` (the Death/Action/Status/FOV/
Render esper processors), `ai` (enemy behaviors and the AISystem), `crafting` (spell
config lookup, recipe matching, and casting), and `utils` (small standalone queries).
Public names are re-exported here so callers import them as `from src.systems import X`.
Module-private helpers (e.g. the `_process_*` AI behaviors) are not re-exported; tests
that exercise them import from the submodule directly.
"""

from src.systems.ai import AISystem
from src.systems.combat import apply_effect, deal_damage, roll_loot
from src.systems.crafting import (
    can_craft_known_spell,
    cast_spell,
    craft_known_spell,
    discover_and_craft,
    get_spell_config,
    is_reagent,
    match_recipe,
)
from src.systems.movement import get_action_cooldown, move_entity
from src.systems.processors import (
    ActionSystem,
    DeathSystem,
    FOVSystem,
    MetaSaveSystem,
    RenderSystem,
    StatusSystem,
)
from src.systems.utils import is_game_active
from src.systems.visuals import (
    EFFECT_COLORS,
    PROJECTILE_GLYPHS,
    spawn_particle_burst,
    trigger_cast_visual,
    trigger_screen_flash,
)

__all__ = [
    'EFFECT_COLORS',
    'PROJECTILE_GLYPHS',
    'ActionSystem',
    'AISystem',
    'DeathSystem',
    'FOVSystem',
    'MetaSaveSystem',
    'RenderSystem',
    'StatusSystem',
    'apply_effect',
    'can_craft_known_spell',
    'cast_spell',
    'craft_known_spell',
    'deal_damage',
    'discover_and_craft',
    'get_action_cooldown',
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
