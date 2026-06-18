from typing import TYPE_CHECKING

import esper
import tcod
import tcod.map
from tcod import libtcodpy

from src import persistence
from src.components import (
    Actor,
    EffectType,
    FieldOfView,
    Loot,
    MessageLog,
    MetaSaveState,
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
    TILE_SCALE,
    UI_BLACK,
    UI_YELLOW,
    to_rgb,
)
from src.debug import debug_log
from src.ecs_helpers import (
    get_display_name,
    get_player_component,
    get_singleton,
    get_status,
    is_player,
    spawn_item_entity,
    try_get_singleton,
)
from src.layout import LayoutProcessor
from src.map_objects import Map
from src.states import WORLD_VIEW_MODES, DisplayMode, GameState
from src.systems.combat import apply_status_pulse, roll_loot
from src.systems.visuals import EFFECT_COLORS
from src.ui_helpers import blend

if TYPE_CHECKING:
    from src.data_loaders import AssetLoader
    from src.layout import Layout

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
                    run_stats = try_get_singleton(RunStats)
                    if run_stats:
                        run_stats.enemies_defeated += 1
                    self._drop_loot(ent)
                    esper.delete_entity(ent)

    def _drop_loot(self, ent: int):
        """Scatter a slain enemy's rolled loot onto its tile."""
        if not (esper.has_component(ent, Position) and esper.has_component(ent, Loot)):
            return
        drop = roll_loot(esper.component_for_entity(ent, Loot))
        if drop is None:
            return
        pos = esper.component_for_entity(ent, Position)
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


class FOVSystem(esper.Processor):
    def process(self):
        maps = esper.get_component(Map)
        if not maps:
            return
        game_map = maps[0][1]

        for ent, (pos, fov) in esper.get_components(Position, FieldOfView):
            if fov.dirty:
                fov.visible_tiles = set()
                # compute_fov expects [height, width] or [width, height] depending on order
                # With 'F' order (column-major), it matches our [x][y] structure
                fov_map = tcod.map.compute_fov(
                    transparency=game_map.transparent,
                    pov=(pos.x, pos.y),
                    radius=fov.radius,
                    light_walls=True,
                    algorithm=libtcodpy.FOV_BASIC,
                )

                # Update visible tiles and explored map
                for x in range(game_map.width):
                    for y in range(game_map.height):
                        if fov_map[x, y]:
                            fov.visible_tiles.add(Point(x, y))
                            # Only update explored for player FOV
                            if is_player(ent):
                                game_map.explored[x, y] = True

                fov.dirty = False


class RenderSystem(LayoutProcessor):
    def __init__(self, layout: Layout, asset_loader: AssetLoader):
        super().__init__(layout)
        self.asset_loader = asset_loader

    def process(self):
        game_state = get_singleton(GameState)
        if game_state.display_mode not in WORLD_VIEW_MODES:
            return

        # 1. Get the Map and Player FOV
        game_map = try_get_singleton(Map)
        if not game_map:
            return

        player_fov = get_player_component(FieldOfView)
        player_pos = get_player_component(Position)

        # The camera follows the player; map cells draw into the map viewport,
        # converted from map space to screen space (the console cell to draw at):
        #   screen = viewport.origin + map_cell - camera
        view = self.layout.map_viewport
        focus_x = player_pos.x if player_pos else game_map.width // 2
        focus_y = player_pos.y if player_pos else game_map.height // 2
        cam_x, cam_y = self.layout.camera_offset(focus_x, focus_y, game_map.width, game_map.height)

        # 2. Render the map. Each tile fills a TILE_SCALE x TILE_SCALE block of cells, so
        # the dungeon reads larger than the one-cell HUD. Walk only the tiles under the
        # viewport and inline the block transform (origin hoisted out of the loop): at this
        # cell count the Rect that map_viewport rebuilds per call otherwise dominates the
        # frame (measured ~28ms -> <1ms here).
        tiles_x, tiles_y = self.layout.viewport_tiles
        origin_x, origin_y = view.x - cam_x * TILE_SCALE, view.y - cam_y * TILE_SCALE
        for x in range(cam_x, min(game_map.width, cam_x + tiles_x)):
            for y in range(cam_y, min(game_map.height, cam_y + tiles_y)):
                is_visible = player_fov is not None and Point(x, y) in player_fov.visible_tiles
                is_explored = game_map.explored[x, y]
                if not is_visible and not is_explored:
                    continue

                tile = game_map.tiles[x][y]
                fg = tile.fg
                bg = tile.bg

                if not is_visible:
                    # Dim the colors for explored but not visible tiles
                    fg = to_rgb([int(c * 0.3) for c in fg])
                    bg = to_rgb([int(c * 0.3) for c in bg])

                self._draw_block(tile.sprite_id, origin_x + x * TILE_SCALE, origin_y + y * TILE_SCALE, fg=fg, bg=bg)

        # 3. Render all entities with Position and Renderable components that are visible,
        # filling the same TILE_SCALE block so they read at the scaled tile size.
        for ent, (pos, rend) in esper.get_components(Position, Renderable):
            if player_fov is not None and pos.point not in player_fov.visible_tiles:
                continue

            block_x, block_y = self.layout.map_to_screen(map_x=pos.x, map_y=pos.y, cam_x=cam_x, cam_y=cam_y)
            if not view.contains(block_x, block_y):
                continue

            debug_log(f'render entity {ent} sprite={rend.sprite_id} at {(pos.x, pos.y)}')
            # A statused entity keeps its glyph color over a tint of its active status.
            tint = self._status_tint(ent)
            bg = blend(UI_BLACK, tint, 0.5) if tint is not None else None
            self._draw_block(rend.sprite_id, block_x, block_y, fg=rend.color, bg=bg)

    def _draw_block(self, sprite_id: str, x: int, y: int, fg: RGB, bg: RGB | None) -> None:
        """Draw a sprite into its TILE_SCALE x TILE_SCALE block at console cell (x, y).
        An image sprite rasterized at block size draws its sub-tiles one per cell; a font
        glyph (no block form) just fills the block with the single glyph."""
        block = self.asset_loader.get_block_codepoints(sprite_id)
        if block is None:
            codepoint = self.asset_loader.get_codepoint(sprite_id)
            self.console.draw_rect(x, y, TILE_SCALE, TILE_SCALE, ch=codepoint, fg=fg, bg=bg)
            return
        for i, codepoint in enumerate(block):
            self.console.print(x + i % TILE_SCALE, y + i // TILE_SCALE, chr(codepoint), fg=fg, bg=bg)

    def _status_tint(self, ent: int) -> RGB | None:
        """The tint of the entity's highest-priority active status, or None if it has none."""
        for status in STATUS_TINT_PRIORITY:
            if get_status(ent, status):
                return EFFECT_COLORS[EffectType(status)]
        return None
