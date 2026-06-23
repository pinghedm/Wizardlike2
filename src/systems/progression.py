"""Player progression: granting experience / leveling up, and per-spell mastery.

A leaf system depending only on components, ecs_helpers, audio, constants, and persistence,
so the processors (kills) and crafting (casts) layers can both call into it without a cycle.
"""

import esper

from src import persistence
from src.audio import SoundId, play_sfx
from src.components import (
    Configuration,
    Experience,
    MessageLog,
    SpellMastery,
    SpellMasteryConfig,
    SpellType,
    Stats,
)
from src.constants import UI_PERIWINKLE
from src.ecs_helpers import get_player, get_player_component, try_get_singleton


def grant_xp(amount: int) -> None:
    """Add `amount` XP to the player, leveling up (and raising/refilling HP) for each
    threshold crossed. No-op when there's no player (e.g. at the title screen)."""
    if amount <= 0:
        return
    player = get_player()
    if player is None:
        return
    exp = esper.try_component(player, Experience)
    stats = esper.try_component(player, Stats)
    if exp is None or stats is None:
        return

    exp.xp += amount
    log = try_get_singleton(MessageLog)
    while exp.xp >= exp.next_level_xp:
        exp.xp -= exp.next_level_xp
        exp.level += 1
        stats.max_hp += Experience.HP_PER_LEVEL
        stats.hp = stats.max_hp
        play_sfx(SoundId.LEVEL_UP)
        if log:
            log.add_simple_message(f'You channel new power — level {exp.level}!', color=UI_PERIWINKLE)


def _spell_mastery_config(spell_id: str) -> SpellMasteryConfig | None:
    """A spell's mastery tuning, or None when that spell isn't masterable."""
    config = try_get_singleton(Configuration)
    spell = config.spells_by_id.get(spell_id) if config else None
    return spell.get('mastery') if spell else None


def _casts_for_rank(rank: int, casts_per_rank: int) -> int:
    """Total casts needed to reach `rank`; each rank costs one more step than the last."""
    return casts_per_rank * rank * (rank + 1) // 2


def spell_rank(stype: SpellType) -> int:
    """The player's current mastery rank for `stype` (0 if unmasterable or no player)."""
    cfg = _spell_mastery_config(stype.value)
    mastery = get_player_component(SpellMastery)
    if cfg is None or mastery is None:
        return 0
    casts = mastery.casts.get(stype, 0)
    rank = 0
    while rank < cfg['max_rank'] and casts >= _casts_for_rank(rank + 1, cfg['casts_per_rank']):
        rank += 1
    return rank


def grant_spell_mastery(stype: SpellType) -> int | None:
    """Record a cast of `stype` toward mastery, persisting it across runs (deferred). Returns
    the new rank when this cast raised it, else None (including for unmasterable spells)."""
    if _spell_mastery_config(stype.value) is None:
        return None
    player = get_player()
    if player is None:
        return None
    mastery = esper.try_component(player, SpellMastery)
    if mastery is None:
        return None
    before = spell_rank(stype)
    mastery.casts[stype] = mastery.casts.get(stype, 0) + 1
    persistence.mark_meta_dirty()
    after = spell_rank(stype)
    return after if after > before else None


def spell_charge_bonus(stype: SpellType) -> int:
    """Extra charges `stype` gains on refill/craft from the player's mastery rank."""
    cfg = _spell_mastery_config(stype.value)
    return spell_rank(stype) * cfg['charge_bonus_per_rank'] if cfg else 0


def spell_power_mult(stype: SpellType) -> float:
    """Effect-power multiplier for `stype` from the player's mastery rank (1.0 if none)."""
    cfg = _spell_mastery_config(stype.value)
    return 1.0 + spell_rank(stype) * cfg['power_per_rank'] if cfg else 1.0
