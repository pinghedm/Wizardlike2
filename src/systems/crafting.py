from collections import Counter
from dataclasses import replace

import esper

from src.components import (
    Configuration,
    DamageModifier,
    EffectType,
    Inventory,
    ItemType,
    KnownRecipes,
    MessageLog,
    PlayerTag,
    Point,
    Position,
    RunStats,
    SpellConfig,
    SpellInventory,
    SpellType,
    Stats,
    StatusEffects,
)
from src.constants import UI_CYAN, UI_GRAY_MID
from src.ecs_helpers import actor_name, try_get_singleton
from src.systems.combat import apply_effect
from src.systems.visuals import trigger_projectile


def get_spell_config(spell_id: str) -> SpellConfig | None:
    """Look up a spell's config by id via the Configuration index (O(1))."""
    configs = try_get_singleton(Configuration)
    if configs is None:
        return None
    return configs.spells_by_id.get(spell_id)


# Item types that are pickups but not crafting reagents (currency, etc.).
NON_REAGENT_ITEMS = {ItemType.GOLD}


def is_reagent(itype: ItemType) -> bool:
    """Whether an item type can be used as a crafting reagent."""
    return itype not in NON_REAGENT_ITEMS


def match_recipe(selection: tuple[ItemType, ...], hide_rare: bool = True) -> tuple[SpellType, int] | None:
    """Match a sorted ingredient selection to a spell recipe.

    Returns (spell_type, charges) for the first matching recipe, or None. Rare
    spells are shop-only and can't be discovered by combining, so they're skipped
    unless `hide_rare` is False (e.g. re-crafting one already learned at a shop).
    """
    configs = esper.get_component(Configuration)[0][1]
    for s_conf in configs.spells:
        if hide_rare and s_conf.get('rare'):
            continue
        for r_data in s_conf['recipes']:
            if r_data['ingredients'] == selection:
                return SpellType(s_conf['id']), r_data['charges']
    return None


def _affordable_recipe(inventory: Inventory, combos: set[tuple[ItemType, ...]]) -> tuple[ItemType, ...] | None:
    """The cheapest combo (fewest ingredients) the inventory can fully pay for, or None."""
    for combo in sorted(combos, key=len):
        if all(inventory.items.get(itype, 0) >= count for itype, count in Counter(combo).items()):
            return combo
    return None


def can_craft_known_spell(stype: SpellType) -> bool:
    """Whether the player can afford any known recipe for `stype` from current stock."""
    recipes = try_get_singleton(KnownRecipes)
    inventory = try_get_singleton(Inventory)
    if recipes is None or inventory is None:
        return False
    return _affordable_recipe(inventory, recipes.recipes.get(stype, set())) is not None


def craft_known_spell(stype: SpellType) -> int | None:
    """Re-craft a known spell from the player's ingredients on hand.

    Picks the cheapest known recipe (fewest ingredients) the player can afford,
    consumes those ingredients, and grants its charges. Returns the charges
    granted, or None if no known recipe for the spell is affordable.
    """
    recipes = try_get_singleton(KnownRecipes)
    inventory = try_get_singleton(Inventory)
    spell_inv = try_get_singleton(SpellInventory)
    if recipes is None or inventory is None or spell_inv is None:
        return None

    combo = _affordable_recipe(inventory, recipes.recipes.get(stype, set()))
    if combo is None:
        return None
    match = match_recipe(combo, hide_rare=False)
    if match is None:
        return None
    charges = match[1]

    for itype, count in Counter(combo).items():
        inventory.items[itype] -= count
    spell_inv.spells[stype] = spell_inv.spells.get(stype, 0) + charges
    return charges


def _apply_reaction_multiplier(target_ent: int, modifiers: list[DamageModifier], log: MessageLog) -> float:
    """The combined damage multiplier from a spell's modifiers whose status the target
    currently carries — an elemental reaction. Each matched status is consumed (one-shot),
    and the multipliers compose. Returns 1.0 when nothing matches.
    """
    if not modifiers or not esper.has_component(target_ent, StatusEffects):
        return 1.0

    active = esper.component_for_entity(target_ent, StatusEffects).active
    name = actor_name(target_ent)
    mult = 1.0
    for mod in modifiers:
        if mod.vs_status not in active:
            continue
        mult *= mod.damage_mult
        del active[mod.vs_status]
        verb = 'is vulnerable' if mod.damage_mult > 1 else 'resists'
        log.add_simple_message(f'{name} {verb} while {mod.vs_status.name}!', color=UI_CYAN)
    return mult


def cast_spell(spell_id: str, target_x: int, target_y: int):
    log = esper.get_component(MessageLog)[0][1]

    # Query for player
    player_ents = esper.get_components(SpellInventory, PlayerTag)
    if not player_ents:
        return
    player, (player_spell_inv, _tag) = player_ents[0]

    stype = SpellType(spell_id)

    # Consume charge
    player_spell_inv.spells[stype] -= 1

    run_stats = try_get_singleton(RunStats)
    if run_stats:
        run_stats.spells_cast[stype] += 1

    # Look up config
    s_conf = get_spell_config(spell_id)
    if not s_conf:
        return

    log.add_simple_message(f'You cast {s_conf["name"]}!', color=UI_CYAN)

    radius = s_conf.get('radius', 0)
    caster_origin = esper.component_for_entity(player, Position).point

    # Launch a projectile from the caster; it fires the impact burst on arrival,
    # colored/styled by the spell's primary effect.
    effects = s_conf['effects']
    if effects:
        trigger_projectile(
            start=caster_origin,
            target=Point(target_x, target_y),
            effect_type=effects[0].type,
            burst_radius=radius,
        )

    # Find all entities in impact zone using Euclidean distance
    targets: list[int] = []
    for ent, (pos, _stats) in esper.get_components(Position, Stats):
        if not esper.has_component(ent, StatusEffects):
            continue

        dx = pos.x - target_x
        dy = pos.y - target_y
        if dx**2 + dy**2 <= radius**2:
            targets.append(ent)

    if not targets:
        log.add_simple_message('The spell hits nothing.', color=UI_GRAY_MID)
        return

    # Knockback shoves targets directly away from the caster. Reaction modifiers scale
    # the spell's damage per target based on the statuses that target already carries.
    for target in targets:
        mult = _apply_reaction_multiplier(target, s_conf.get('modifiers', []), log)
        for effect in s_conf['effects']:
            resolved = effect
            if mult != 1.0 and effect.type in (EffectType.DAMAGE, EffectType.DRAIN):
                resolved = replace(effect, power=max(0, round(effect.power * mult)))
            apply_effect(target, resolved, origin=caster_origin, caster_ent=player)
