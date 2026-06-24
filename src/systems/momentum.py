"""Arcane momentum — the combo system. Casting and slaying build stacks that amplify spell
damage and enrich loot; the meter bleeds a stack after a lull (MomentumSystem) and shatters
when the player is struck. A leaf module: building/resetting and the per-spell damage scaling
all hang off the player's Momentum component, so the crafting, combat, and processor layers
drive it without coupling to each other.
"""

import esper

from src.components import Configuration, MessageLog, Momentum, SpellType
from src.constants import UI_ORANGE
from src.ecs_helpers import get_player_component, get_singleton, try_get_singleton
from src.states import GameState


def build_momentum(amount: int = 1) -> None:
    """Add `amount` stacks (capped) and refresh the decay timer — a cast or a kill feeds the
    combo. No-op when there's no player."""
    momentum = get_player_component(Momentum)
    if momentum is None:
        return
    momentum.stacks = min(Momentum.MAX_STACKS, momentum.stacks + amount)
    momentum.decay_ticks = Momentum.DECAY_TICKS


def reset_momentum() -> None:
    """Shatter the combo to zero — the player took a hit and broke the chain."""
    momentum = get_player_component(Momentum)
    if momentum is not None and momentum.stacks > 0:
        momentum.stacks = 0
        momentum.decay_ticks = 0
        log = try_get_singleton(MessageLog)
        if log:
            log.add_simple_message('Your momentum shatters!', color=UI_ORANGE)


def momentum_damage_mult(stype: SpellType) -> float:
    """Damage multiplier from current momentum for `stype`: its per-stack bonus times the
    player's stacks (1.0 when there's no player or the spell defines no momentum scaling)."""
    momentum = get_player_component(Momentum)
    config = try_get_singleton(Configuration)
    if momentum is None or config is None:
        return 1.0
    spell = config.spells_by_id.get(stype.value)
    per_stack = spell.get('momentum_damage_per_stack', 0.0) if spell else 0.0
    return 1.0 + momentum.stacks * per_stack


class MomentumSystem(esper.Processor):
    """Bleeds the player's arcane momentum after a lull, on the real-time cadence: once the
    decay timer runs out it sheds a stack and restarts, so a chain fades if not fed."""

    def process(self):
        if get_singleton(GameState).time_paused:
            return
        momentum = get_player_component(Momentum)
        if momentum is None or momentum.stacks == 0:
            return
        momentum.decay_ticks -= 1
        if momentum.decay_ticks <= 0:
            momentum.stacks -= 1
            momentum.decay_ticks = Momentum.DECAY_TICKS if momentum.stacks > 0 else 0
