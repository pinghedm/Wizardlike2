from collections import Counter
from dataclasses import replace

import esper

from src import persistence
from src.audio import SoundId, cast_sound, play_sfx
from src.components import (
    Configuration,
    DamageModifier,
    EffectType,
    Inventory,
    ItemType,
    KnownRecipes,
    MessageLog,
    Point,
    Position,
    RunStats,
    SpellConfig,
    SpellInventory,
    SpellType,
    Stats,
    StatusEffects,
)
from src.constants import UI_PERIWINKLE, UI_SKY
from src.ecs_helpers import actor_name, get_player, get_singleton, try_get_singleton
from src.systems.combat import apply_effect
from src.systems.momentum import build_momentum, momentum_damage_mult
from src.systems.progression import grant_spell_mastery, spell_charge_bonus, spell_power_mult
from src.systems.visuals import trigger_projectile


def get_spell_config(spell_id: str) -> SpellConfig | None:
    """Look up a spell's config by id via the Configuration index (O(1))."""
    configs = try_get_singleton(Configuration)
    if configs is None:
        return None
    return configs.spells_by_id.get(spell_id)


def refill_basic_spells():
    """Top every basic spell back up to its per-floor charge capacity. Basic spells are the
    wizard's default attacks: known from the start and replenished on entering each floor, so
    a run always begins each level with a fallback even after crafted spells are spent."""
    configs = try_get_singleton(Configuration)
    player = get_player()
    if configs is None or player is None:
        return
    spell_inv = esper.component_for_entity(player, SpellInventory)
    for s_conf in configs.spells:
        if s_conf.get('basic'):
            stype = SpellType(s_conf['id'])
            spell_inv.spells[stype] = s_conf.get('charges', 0) + spell_charge_bonus(stype)


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
    charges = match[1] + spell_charge_bonus(stype)

    for itype, count in Counter(combo).items():
        inventory.items[itype] -= count
    spell_inv.spells[stype] += charges
    play_sfx(SoundId.CRAFT)
    return charges


def discover_and_craft(selection: tuple[ItemType, ...]) -> tuple[SpellType, int] | None:
    """Combine a sorted ingredient selection: match it to a recipe and, on a hit, record the
    discovery (persisting the grimoire), grant the spell's charges, and consume the
    ingredients. Returns (spell, charges) on success, or None when nothing matches."""
    result = match_recipe(selection)
    if result is None:
        return None
    stype, charges = result

    recipes = try_get_singleton(KnownRecipes)
    spell_inv = try_get_singleton(SpellInventory)
    inventory = try_get_singleton(Inventory)
    if recipes is None or spell_inv is None or inventory is None:
        return None

    # A spell seen for the first time counts as a discovery; the recipe set then accrues
    # every combination found for it.
    if stype not in recipes.recipes:
        recipes.recipes[stype] = set()
        run_stats = try_get_singleton(RunStats)
        if run_stats:
            run_stats.spells_discovered += 1
        play_sfx(SoundId.DISCOVERY)
    else:
        play_sfx(SoundId.CRAFT)
    recipes.recipes[stype].add(selection)
    persistence.save_meta()

    charges += spell_charge_bonus(stype)
    spell_inv.spells[stype] += charges
    for itype, count in Counter(selection).items():
        inventory.items[itype] -= count
    return stype, charges


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
        play_sfx(SoundId.REACTION)
        verb = 'is vulnerable' if mod.damage_mult > 1 else 'resists'
        log.add_simple_message(f'{name} {verb} while {mod.vs_status.name}!', color=UI_SKY)
    return mult


def _spell_targets_in_radius(target_x: int, target_y: int, radius: int) -> list[int]:
    """Entities with stats and a status slot whose tile lies within the spell's Euclidean
    impact radius of (target_x, target_y)."""
    targets: list[int] = []
    for ent, (pos, _stats) in esper.get_components(Position, Stats):
        if not esper.has_component(ent, StatusEffects):
            continue
        dx = pos.x - target_x
        dy = pos.y - target_y
        if dx**2 + dy**2 <= radius**2:
            targets.append(ent)
    return targets


def _apply_spell_effects(
    targets: list[int], s_conf: SpellConfig, stype: SpellType, caster: int, origin: Point, log: MessageLog
) -> None:
    """Apply every effect of the cast spell to each target. Mastery scales all effects;
    momentum and elemental-reaction modifiers further scale damage/drain per target."""
    mastery_mult = spell_power_mult(stype)
    momentum_mult = momentum_damage_mult(stype)
    for target in targets:
        react_mult = _apply_reaction_multiplier(target, s_conf.get('modifiers', []), log)
        for effect in s_conf['effects']:
            power_mult = mastery_mult
            if effect.type in (EffectType.DAMAGE, EffectType.DRAIN):
                power_mult *= react_mult * momentum_mult
            resolved = effect if power_mult == 1.0 else replace(effect, power=max(0, round(effect.power * power_mult)))
            apply_effect(target, resolved, origin=origin, caster_ent=caster)


def cast_spell(spell_id: str, target_x: int, target_y: int):
    log = get_singleton(MessageLog)

    player = get_player()
    if player is None:
        return
    player_spell_inv = esper.component_for_entity(player, SpellInventory)

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

    log.add_simple_message(f'You cast {s_conf["name"]}!', color=UI_SKY)

    ranked_up = grant_spell_mastery(stype)
    if ranked_up is not None:
        log.add_simple_message(f'Your mastery of {s_conf["name"]} deepens — rank {ranked_up}!', color=UI_PERIWINKLE)

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
        play_sfx(cast_sound(effects[0].type))

    targets = _spell_targets_in_radius(target_x, target_y, radius)
    _apply_spell_effects(targets, s_conf, stype, player, caster_origin, log)

    build_momentum()  # this cast feeds the combo for the next action
