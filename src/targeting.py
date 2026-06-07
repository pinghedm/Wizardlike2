"""Cycle-targeting support: finding lockable enemies and keeping the reticle on one.

Used by the targeting input handler and by CycleTargetSystem, which maintains the lock
in real time each tick (enemies move and die while the player aims). Kept dependency-free
of the input/system packages so both can share it without an import cycle.
"""

import esper

from src.components import Enemy, FieldOfView, Position, TargetingReticle, UIState
from src.ecs_helpers import get_player, get_singleton
from src.states import DisplayMode, GameState


def visible_enemies(player: int) -> list[int]:
    """Living enemies inside the player's FOV, nearest first. Cycle targeting ignores
    spell range, so any visible foe can be locked."""
    player_pos = esper.component_for_entity(player, Position)
    fov = esper.component_for_entity(player, FieldOfView)
    ranked: list[tuple[int, int]] = []
    for ent, (pos, _enemy) in esper.get_components(Position, Enemy):
        if pos.point not in fov.visible_tiles:
            continue
        dist_sq = (pos.x - player_pos.x) ** 2 + (pos.y - player_pos.y) ** 2
        ranked.append((dist_sq, ent))
    ranked.sort()
    return [ent for _dist, ent in ranked]


def refresh_lock(reticle: TargetingReticle, player: int) -> None:
    """Keep the lock valid and the reticle on it: a target that died or left the player's
    FOV is dropped for the nearest remaining one; the reticle then follows its tile."""
    targets = visible_enemies(player)
    if reticle.target_ent not in targets:
        reticle.target_ent = targets[0] if targets else None
    if reticle.target_ent is not None:
        pos = esper.component_for_entity(reticle.target_ent, Position)
        reticle.x, reticle.y = pos.x, pos.y


class CycleTargetSystem(esper.Processor):
    """Maintains the cycle-targeting lock each tick: follows the locked enemy as it moves,
    re-locks to the nearest when it dies or leaves view, and drops out of targeting once
    no enemy remains in sight."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode != DisplayMode.TARGETING:
            return

        reticles = esper.get_component(TargetingReticle)
        if not reticles:
            return
        ret_ent, reticle = reticles[0]

        player = get_player()
        if player is None:
            return

        if not visible_enemies(player):
            # immediate: we're mid-process, so drop the reticle now rather than next tick.
            esper.delete_entity(ret_ent, immediate=True)
            get_singleton(UIState).active_targeting_spell_id = None
            game_state.display_mode = DisplayMode.EXPLORING
            return

        refresh_lock(reticle, player)
