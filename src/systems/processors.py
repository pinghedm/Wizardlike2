from dataclasses import replace
from typing import TYPE_CHECKING

import esper
import numpy as np
import pygame

from src import persistence
from src.audio import SoundId, play_sfx
from src.components import (
    Actor,
    Boss,
    EffectType,
    Enemy,
    FieldOfView,
    Loot,
    MessageLog,
    MetaSaveState,
    Momentum,
    Point,
    Position,
    Renderable,
    RunStats,
    Stats,
    StatusEffects,
    StatusType,
)
from src.constants import (
    RGB,
    STATUS_PULSE_INTERVAL,
    TILE_PX,
    TRAP_DETECT_RADIUS,
    UI_BLACK,
    UI_YELLOW,
    to_rgb,
)
from src.debug import debug_log
from src.ecs_helpers import (
    exit_is_sealed,
    get_display_name,
    get_player_component,
    get_singleton,
    get_status,
    is_player,
    spawn_item_entity,
    try_get_singleton,
)
from src.fov import compute_fov
from src.map_objects import Map, Tile
from src.render import RenderProcessor, Viewport, compute_viewport
from src.states import WORLD_VIEW_MODES, DisplayMode, GameState
from src.systems.combat import apply_effect, apply_status_pulse, roll_loot
from src.systems.momentum import build_momentum
from src.systems.progression import grant_xp
from src.systems.visuals import EFFECT_COLORS
from src.ui_helpers import blend

if TYPE_CHECKING:
    from src.data_loaders import AssetLoader

# When statuses stack, an entity's glyph tints to the most action-relevant one first.
STATUS_TINT_PRIORITY = (
    StatusType.STUN,
    StatusType.POISON,
    StatusType.WET,
    StatusType.SLOW,
    StatusType.HASTE,
    StatusType.SHIELD,
    StatusType.REGEN,
)


class DeathSystem(esper.Processor):
    """Handles death for all entities with Stats."""

    def process(self):
        log = try_get_singleton(MessageLog)

        for ent, stats in esper.get_component(Stats):
            if stats.hp <= 0:
                if is_player(ent):
                    debug_log(f'DeathSystem: player {ent} died (hp={stats.hp})')
                    get_singleton(GameState).display_mode = DisplayMode.GAME_OVER
                else:
                    debug_log(f'DeathSystem: deleting {ent} ({get_display_name(ent)})')
                    if log:
                        log.add_simple_message(f'The {get_display_name(ent)} dies!', color=UI_YELLOW)
                    play_sfx(SoundId.DEATH)
                    run_stats = try_get_singleton(RunStats)
                    if run_stats:
                        run_stats.enemies_defeated += 1
                    enemy = esper.try_component(ent, Enemy)
                    if enemy is not None:
                        grant_xp(enemy.xp_reward)
                    build_momentum()  # a kill feeds the combo before its loot is rolled
                    self._drop_loot(ent)
                    esper.delete_entity(ent)

    def _drop_loot(self, ent: int):
        """Scatter a slain enemy's rolled loot onto its tile, plus one extra roll per
        momentum bonus — chaining kills/casts makes foes drop more reagents."""
        if not (esper.has_component(ent, Position) and esper.has_component(ent, Loot)):
            return
        loot = esper.component_for_entity(ent, Loot)
        pos = esper.component_for_entity(ent, Position)
        momentum = get_player_component(Momentum)
        rolls = 1 + (momentum.bonus_drops if momentum is not None else 0)
        for _ in range(rolls):
            drop = roll_loot(loot)
            if drop is None:
                continue
            itype, count = drop
            spawn_item_entity(itype, pos.x, pos.y, count)


class MetaSaveSystem(esper.Processor):
    """Persists deferred cross-run progression at a safe moment.

    Gold pickups only mark MetaSaveState dirty (no disk write mid-step); this flushes
    once whenever the game is paused — a menu, a modal, or the descend prompt — which
    coalesces a floor's worth of pickups into a single write off the movement path.
    """

    def process(self):
        if not get_singleton(GameState).time_paused:
            return
        state = try_get_singleton(MetaSaveState)
        if state is not None and state.dirty:
            persistence.save_meta()


class ActionSystem(esper.Processor):
    """Manages cooldowns for all actors."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused:
            return

        for _ent, actor in esper.get_component(Actor):
            if actor.cooldown > 0:
                actor.cooldown -= 1
            if actor.cast_cooldown > 0:
                actor.cast_cooldown -= 1


class StatusSystem(esper.Processor):
    """Ages active status effects and applies recurring ones each pulse."""

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.time_paused:
            return

        log = try_get_singleton(MessageLog)
        for ent, status in esper.get_component(StatusEffects):
            for status_type in list(status.active.keys()):
                effect = status.active[status_type]
                # Recurring effects carry power; they pulse on the global cadence.
                if effect.power and effect.duration % STATUS_PULSE_INTERVAL == 0:
                    apply_status_pulse(ent, status_type, effect.power, log)
                effect.duration -= 1
                if effect.duration <= 0:
                    del status.active[status_type]


class HazardSystem(esper.Processor):
    """Applies a hazard/trap tile's on-enter effects to any actor that steps onto it, and
    springs (reveals) a concealed trap the instant it's triggered. Tracks each actor's last
    cell so effects fire once per entry — not every tick it stands there. Purely ECS-driven,
    so it covers player steps, enemy pathing, and knockback landings without coupling to them."""

    def __init__(self) -> None:
        super().__init__()
        self._last_cell: dict[int, Point] = {}

    def process(self):
        if get_singleton(GameState).time_paused:
            return
        game_map = try_get_singleton(Map)
        if game_map is None:
            return

        live: set[int] = set()
        # StatusEffects gates to actors (player + enemies) — apply_effect reads Stats and
        # StatusEffects, so items/NPCs on hazard cells are correctly skipped.
        for ent, (pos, _status) in esper.get_components(Position, StatusEffects):
            live.add(ent)
            if self._last_cell.get(ent) == pos.point:
                continue
            self._last_cell[ent] = pos.point
            tile = game_map.tiles[pos.x][pos.y]
            if not tile.effects:
                continue
            if tile.hidden and is_player(ent):
                log = try_get_singleton(MessageLog)
                if log:
                    log.add_simple_message('You spring a hidden trap!', color=UI_YELLOW)
            for effect in tile.effects:
                apply_effect(ent, effect, origin=pos.point)
            if tile.hidden:
                # A trap fires once, then it's spent — swapped for a visible, inert marker. A
                # hazard (not hidden) stays armed and re-triggers on each fresh entry.
                game_map.set_tile(pos.x, pos.y, _spring_trap(tile))

        # Forget entities that no longer exist (slain enemies) so the cache can't grow unbounded.
        self._last_cell = {ent: cell for ent, cell in self._last_cell.items() if ent in live}


class FOVSystem(esper.Processor):
    def process(self):
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        for ent, (pos, fov) in esper.get_components(Position, FieldOfView):
            if fov.dirty:
                fov_map = compute_fov(game_map.transparent, (pos.x, pos.y), fov.radius)

                # Build the visible-tile set from just the lit cells (np.argwhere), rather than
                # scanning the whole map in Python; fold the same mask into explored for the player.
                fov.visible_tiles = {Point(int(x), int(y)) for x, y in np.argwhere(fov_map)}
                if is_player(ent):
                    game_map.explored |= fov_map
                    _reveal_nearby_traps(game_map, pos, fov.visible_tiles)
                    _discover_visible_bosses(fov.visible_tiles)

                fov.dirty = False


def _spring_trap(tile: Tile) -> Tile:
    """The spent form of a triggered trap: visible but inert (no effects), and dimmed so it
    reads as already-sprung rather than a live threat."""
    return replace(tile, hidden=False, effects=(), fg=to_rgb([int(c * 0.5) for c in tile.fg]))


def _discover_visible_bosses(visible_tiles: set[Point]) -> None:
    """Latch a boss as discovered the first time it enters the player's line of sight, so its
    HP bar only appears once the player has actually found it. Stays true thereafter."""
    for _ent, (boss, pos) in esper.get_components(Boss, Position):
        if not boss.discovered and pos.point in visible_tiles:
            boss.discovered = True


def _reveal_nearby_traps(game_map: Map, player_pos: Position, visible_tiles: set[Point]) -> None:
    """Mark concealed traps the player can now perceive: those in line of sight and within
    TRAP_DETECT_RADIUS."""
    for p in visible_tiles:
        if max(abs(p.x - player_pos.x), abs(p.y - player_pos.y)) > TRAP_DETECT_RADIUS:
            continue
        tile = game_map.tiles[p.x][p.y]
        if tile.hidden and not game_map.revealed[p.x, p.y]:
            game_map.revealed[p.x, p.y] = True


def _status_tint(ent: int) -> RGB | None:
    """The tint of the entity's highest-priority active status, or None if it has none."""
    for status in STATUS_TINT_PRIORITY:
        if get_status(ent, status):
            return EFFECT_COLORS[EffectType(status)]
    return None


class RenderSystem(RenderProcessor):
    """Draws the dungeon — tiles then entities — into the pygame window surface.

    Terrain is ~900 tile draws (`pygame.draw.rect` + a sprite blit each), which dominates the
    render loop's cost. It only changes when the camera scrolls, the FOV/exploration shifts, a
    trap springs or is revealed, the exit unseals, or the window resizes — so we render it into a
    cached layer, redraw that layer only when what it depicts changes, and blit it each frame.
    Entities move every step and are cheap, so they redraw straight to the window on top.
    """

    def __init__(self, surface: pygame.Surface, asset_loader: AssetLoader) -> None:
        super().__init__(surface, asset_loader)
        self._terrain: pygame.Surface | None = None
        self._terrain_sig: tuple[object, ...] | None = None
        # The visible-tile set the cache was rendered for, held so its id() can't be recycled onto
        # a different set while the signature still references it.
        self._terrain_visible: set[Point] | None = None

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in WORLD_VIEW_MODES:
            return

        game_map = try_get_singleton(Map)
        if not game_map:
            return

        player_fov = get_player_component(FieldOfView)
        player_pos = get_player_component(Position)
        focus_x = player_pos.x if player_pos else game_map.width // 2
        focus_y = player_pos.y if player_pos else game_map.height // 2
        viewport = compute_viewport(self.surface, focus_x, focus_y, game_map.width, game_map.height)

        self._blit_terrain(game_map, viewport, player_fov)
        self._render_entities(viewport, player_fov)

    def _blit_terrain(self, game_map: Map, viewport: Viewport, player_fov: FieldOfView | None) -> None:
        """Blit the cached terrain layer, re-rendering it first only when the signature of what it
        depicts has changed. FOV recompute reassigns `visible_tiles` (and updates explored/revealed
        in the same tick), so its identity tracks visibility changes; `revision` tracks sprung and
        revealed traps; the rest are direct camera/seal/size inputs."""
        size = self.surface.get_size()
        visible = player_fov.visible_tiles if player_fov is not None else None
        sig: tuple[object, ...] = (
            id(game_map),
            game_map.revision,
            viewport.cam_x,
            viewport.cam_y,
            size,
            exit_is_sealed(),
            id(visible),
        )
        if self._terrain is None or sig != self._terrain_sig:
            if self._terrain is None or self._terrain.get_size() != size:
                self._terrain = pygame.Surface(size)
            self._terrain.fill(UI_BLACK)
            self._render_map(self._terrain, game_map, viewport, player_fov)
            self._terrain_sig = sig
            self._terrain_visible = visible
        self.surface.blit(self._terrain, (0, 0))

    def _render_map(
        self, target: pygame.Surface, game_map: Map, viewport: Viewport, player_fov: FieldOfView | None
    ) -> None:
        """Draw the explored/visible tiles under the viewport into `target`: a bg rect, then the
        tile's sprite (a glyph for terrain, an image for the exit). Explored-but-unseen tiles are
        dimmed; a still-sealed exit is dimmed until its guardians are cleared."""
        tiles_x = viewport.width // TILE_PX + 1
        tiles_y = viewport.height // TILE_PX + 1
        sealed = exit_is_sealed()
        for x in range(viewport.cam_x, min(game_map.width, viewport.cam_x + tiles_x)):
            for y in range(viewport.cam_y, min(game_map.height, viewport.cam_y + tiles_y)):
                is_visible = player_fov is not None and Point(x, y) in player_fov.visible_tiles
                if not is_visible and not game_map.explored[x, y]:
                    continue

                tile = game_map.tiles[x][y]
                # A concealed trap the player hasn't detected yet masquerades as plain floor.
                if tile.hidden and not game_map.revealed[x, y]:
                    tile = game_map.floor_look
                fg, bg = tile.fg, tile.bg
                if tile.is_exit and sealed:
                    fg = to_rgb([int(c * Map.SEALED_EXIT_DIM) for c in fg])
                if not is_visible:
                    fg = to_rgb([int(c * 0.3) for c in fg])
                    bg = to_rgb([int(c * 0.3) for c in bg])

                px, py = viewport.tile_to_px(x, y)
                pygame.draw.rect(target, bg, (px, py, TILE_PX, TILE_PX))
                target.blit(self.asset_loader.get_sprite(tile.sprite_id, TILE_PX, fg), (px, py))

    def _render_entities(self, viewport: Viewport, player_fov: FieldOfView | None) -> None:
        """Blit each visible entity's sprite at its tile, over a tint of its highest-priority
        active status (a filled bg tile) when it has one."""
        for ent, (pos, rend) in esper.get_components(Position, Renderable):
            if player_fov is not None and pos.point not in player_fov.visible_tiles:
                continue
            px, py = viewport.tile_to_px(pos.x, pos.y)
            if not viewport.contains_px(px, py):
                continue
            tint = _status_tint(ent)
            if tint is not None:
                pygame.draw.rect(self.surface, blend(UI_BLACK, tint, 0.5), (px, py, TILE_PX, TILE_PX))
            self.surface.blit(self.asset_loader.get_sprite(rend.sprite_id, TILE_PX, rend.color), (px, py))
