"""pygame-ce renderer prototype for WizardLike.

Evaluates swapping tcod's cell-grid console for a pixel renderer while keeping the
existing esper world, logic systems, movement/combat, and spell casting untouched.
The world is built and ticked exactly as the real game does (src.main helpers); only
rendering and input are reimplemented here in pygame. The headline is the radial
spell wheel — the free-form UI the console grid can't draw smoothly.

Run: ./venv/bin/python -m prototype.pygame_app
Controls: WASD/arrows move · SPACE opens the spell wheel · in the wheel, mouse or
A/D picks a spell and click/Enter selects it · then click a tile to cast · Esc backs out.
"""

import math

import esper
import pygame

from src.components import (
    Actor,
    Boss,
    Configuration,
    FieldOfView,
    MessageLog,
    Position,
    Renderable,
    SpellInventory,
    SpellType,
    Stats,
)
from src.constants import TICKS_PER_SECOND
from src.data_loaders import AssetLoader
from src.ecs_helpers import get_player, get_player_component, get_singleton
from src.input_handlers import handle_exploring_input
from src.main import add_logic_systems, init_game_world
from src.map_objects import Map
from src.states import DisplayMode, GameState
from src.systems import can_cast, cast_spell
from src.systems.crafting import get_spell_config
from src.systems.visuals import EFFECT_COLORS

from src.components import InputAction  # isort: skip  (grouped with the action map below)

TILE_PX = 28  # pixels per map tile
SCREEN_W, SCREEN_H = 1280, 800
FLOOR_COLOR = (26, 26, 34)
WALL_COLOR = (70, 74, 92)
BG_COLOR = (12, 12, 16)

# pygame key -> game InputAction, so the prototype drives the real exploring handler.
KEY_ACTIONS = {
    pygame.K_UP: InputAction.MOVE_UP,
    pygame.K_w: InputAction.MOVE_UP,
    pygame.K_DOWN: InputAction.MOVE_DOWN,
    pygame.K_s: InputAction.MOVE_DOWN,
    pygame.K_LEFT: InputAction.MOVE_LEFT,
    pygame.K_a: InputAction.MOVE_LEFT,
    pygame.K_RIGHT: InputAction.MOVE_RIGHT,
    pygame.K_d: InputAction.MOVE_RIGHT,
}


def _dim(color, factor):
    return tuple(int(c * factor) for c in color)


def _camera(player_pos, game_map):
    """Top-left map tile so the player sits centered, clamped to the map edges."""
    vw, vh = SCREEN_W // TILE_PX, SCREEN_H // TILE_PX
    cam_x = min(max(player_pos.x - vw // 2, 0), max(0, game_map.width - vw))
    cam_y = min(max(player_pos.y - vh // 2, 0), max(0, game_map.height - vh))
    return cam_x, cam_y


class Prototype:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption('WizardLike — pygame-ce prototype')
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 22)
        self.big_font = pygame.font.Font(None, 34)

        # Build and wire the real world exactly as the game does.
        asset_loader = AssetLoader()
        self.player = init_game_world(asset_loader)
        add_logic_systems()
        self._grant_demo_spells()

        self.mode = 'explore'  # 'explore' | 'wheel' | 'aim'
        self.wheel = []  # list of (spell_id, name, color, charges)
        self.selected = 0
        self.aim_spell = None
        self.flashes = []  # expanding cast rings: [x, y, age]

    def _grant_demo_spells(self):
        """Stock a handful of spells so the wheel has several wedges to show off."""
        inv = esper.component_for_entity(self.player, SpellInventory)
        for s_conf in get_singleton(Configuration).spells[:8]:
            stype = SpellType(s_conf['id'])
            inv.spells[stype] = max(inv.spells[stype], 5)

    # --- spell wheel data ---------------------------------------------------

    def _spell_color(self, spell_id):
        s_conf = get_spell_config(spell_id)
        if s_conf and s_conf['effects']:
            return EFFECT_COLORS.get(s_conf['effects'][0].type, (200, 200, 200))
        return (200, 200, 200)

    def _build_wheel(self):
        inv = esper.component_for_entity(self.player, SpellInventory)
        self.wheel = []
        for stype, charges in inv.spells.items():
            s_conf = get_spell_config(str(stype))
            name = s_conf['name'] if s_conf else str(stype)
            self.wheel.append((str(stype), name, self._spell_color(str(stype)), charges))
        self.wheel.sort(key=lambda w: (w[3] == 0, w[1]))  # castable first, then by name
        self.selected = 0

    # --- input --------------------------------------------------------------

    def _handle_event(self, event):
        if event.type == pygame.QUIT:
            return False
        if self.mode == 'explore':
            self._explore_event(event)
        elif self.mode == 'wheel':
            self._wheel_event(event)
        elif self.mode == 'aim':
            self._aim_event(event)
        return True

    def _explore_event(self, event):
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_SPACE:
            self._build_wheel()
            self.mode = 'wheel'
        elif event.key in KEY_ACTIONS:
            handle_exploring_input(KEY_ACTIONS[event.key])

    def _wheel_event(self, event):
        if not self.wheel:
            self.mode = 'explore'
            return
        if event.type == pygame.MOUSEMOTION:
            self._select_from_mouse(event.pos)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.mode = 'explore'
            elif event.key in (pygame.K_a, pygame.K_LEFT):
                self.selected = (self.selected - 1) % len(self.wheel)
            elif event.key in (pygame.K_d, pygame.K_RIGHT):
                self.selected = (self.selected + 1) % len(self.wheel)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._pick_selected()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._select_from_mouse(event.pos)
            self._pick_selected()

    def _pick_selected(self):
        spell_id, _name, _color, charges = self.wheel[self.selected]
        if charges <= 0:
            return
        self.aim_spell = spell_id
        self.mode = 'aim'

    def _aim_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.mode = 'explore'
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._cast_at(event.pos)

    def _cast_at(self, pos):
        game_map = get_singleton(Map)
        player_pos = esper.component_for_entity(self.player, Position)
        cam_x, cam_y = _camera(player_pos, game_map)
        map_x = cam_x + pos[0] // TILE_PX
        map_y = cam_y + pos[1] // TILE_PX
        inv = esper.component_for_entity(self.player, SpellInventory)
        if inv.spells[SpellType(self.aim_spell)] > 0 and can_cast(self.player):
            cast_spell(spell_id=self.aim_spell, target_x=map_x, target_y=map_y)
            self.flashes.append([map_x, map_y, 0])
        self.mode = 'explore'

    def _select_from_mouse(self, pos):
        cx, cy = SCREEN_W // 2, SCREEN_H // 2
        dx, dy = pos[0] - cx, pos[1] - cy
        if math.hypot(dx, dy) < 60:  # dead zone in the hub
            return
        span = 2 * math.pi / len(self.wheel)
        ang = math.atan2(dy, dx) + math.pi / 2  # slice 0 at the top
        self.selected = round(ang / span) % len(self.wheel)

    # --- render -------------------------------------------------------------

    def _render_world(self):
        game_map = get_singleton(Map)
        fov = get_player_component(FieldOfView)
        player_pos = esper.component_for_entity(self.player, Position)
        cam_x, cam_y = _camera(player_pos, game_map)
        vw, vh = SCREEN_W // TILE_PX + 1, SCREEN_H // TILE_PX + 1

        for x in range(cam_x, min(game_map.width, cam_x + vw)):
            for y in range(cam_y, min(game_map.height, cam_y + vh)):
                visible = fov is not None and (x, y) in fov.visible_tiles
                if not visible and not game_map.explored[x, y]:
                    continue
                tile = game_map.tiles[x][y]
                if tile.hidden and not game_map.revealed[x, y]:
                    tile = game_map.floor_look
                if tile.is_exit:
                    color = (90, 200, 120)
                elif not tile.walkable:
                    color = WALL_COLOR
                else:
                    color = FLOOR_COLOR
                if not visible:
                    color = _dim(color, 0.4)
                rect = ((x - cam_x) * TILE_PX, (y - cam_y) * TILE_PX, TILE_PX, TILE_PX)
                pygame.draw.rect(self.screen, color, rect)

        self._render_entities(game_map, fov, cam_x, cam_y)
        self._render_flashes(cam_x, cam_y)

    def _render_entities(self, game_map, fov, cam_x, cam_y):
        for ent, (pos, rend) in esper.get_components(Position, Renderable):
            if fov is not None and (pos.x, pos.y) not in fov.visible_tiles:
                continue
            cx = (pos.x - cam_x) * TILE_PX + TILE_PX // 2
            cy = (pos.y - cam_y) * TILE_PX + TILE_PX // 2
            radius = TILE_PX // 2 - 2
            if esper.has_component(ent, Boss):
                radius = TILE_PX - 4
            pygame.draw.circle(self.screen, _dim(rend.color, 0.4), (cx, cy), radius)
            pygame.draw.circle(self.screen, rend.color, (cx, cy), radius, width=3)
            if ent == self.player:
                pygame.draw.circle(self.screen, (255, 255, 255), (cx, cy), radius + 3, width=2)

    def _render_flashes(self, cam_x, cam_y):
        alive = []
        for flash in self.flashes:
            x, y, age = flash
            if age > 18:
                continue
            cx = (x - cam_x) * TILE_PX + TILE_PX // 2
            cy = (y - cam_y) * TILE_PX + TILE_PX // 2
            r = 6 + age * 5
            alpha = max(0, 200 - age * 11)
            ring = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(ring, (255, 230, 120, alpha), (r + 2, r + 2), r, width=3)
            self.screen.blit(ring, (cx - r - 2, cy - r - 2))
            flash[2] += 1
            alive.append(flash)
        self.flashes = alive

    def _render_wheel(self):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        cx, cy = SCREEN_W // 2, SCREEN_H // 2
        n = len(self.wheel)
        span = 2 * math.pi / n
        r_in, r_out = 70, 210
        for i, (_spell_id, name, color, charges) in enumerate(self.wheel):
            mid = -math.pi / 2 + i * span
            a0, a1 = mid - span / 2 + 0.02, mid + span / 2 - 0.02
            selected = i == self.selected
            castable = charges > 0
            fill = color if castable else (90, 90, 96)
            if selected:
                fill = tuple(min(255, c + 60) for c in fill)
            elif not castable:
                fill = _dim(fill, 0.5)
            else:
                fill = _dim(fill, 0.75)
            self._draw_wedge(cx, cy, r_in, r_out + (14 if selected else 0), a0, a1, fill)

            lx = cx + math.cos(mid) * (r_in + r_out) / 2
            ly = cy + math.sin(mid) * (r_in + r_out) / 2
            label = self.font.render(name, True, (255, 255, 255) if castable else (150, 150, 150))
            self.screen.blit(label, label.get_rect(center=(lx, ly - 8)))
            chg = self.font.render(f'x{charges}', True, (230, 230, 160) if castable else (120, 120, 120))
            self.screen.blit(chg, chg.get_rect(center=(lx, ly + 12)))

        pygame.draw.circle(self.screen, (24, 24, 30), (cx, cy), r_in - 6)
        sel_name = self.wheel[self.selected][1]
        hub = self.big_font.render(sel_name, True, (255, 255, 255))
        self.screen.blit(hub, hub.get_rect(center=(cx, cy - 8)))
        hint = self.font.render('click to select', True, (170, 170, 180))
        self.screen.blit(hint, hint.get_rect(center=(cx, cy + 18)))

    def _draw_wedge(self, cx, cy, r_in, r_out, a0, a1, color):
        steps = max(2, int((a1 - a0) / 0.12) + 1)
        points = []
        for k in range(steps + 1):
            a = a0 + (a1 - a0) * k / steps
            points.append((cx + math.cos(a) * r_out, cy + math.sin(a) * r_out))
        for k in range(steps + 1):
            a = a1 - (a1 - a0) * k / steps
            points.append((cx + math.cos(a) * r_in, cy + math.sin(a) * r_in))
        pygame.draw.polygon(self.screen, color, points)

    def _render_hud(self):
        stats = get_player_component(Stats)
        game_state = get_singleton(GameState)
        hp = f'HP {stats.hp}/{stats.max_hp}' if stats else 'HP -'
        lines = [f'Floor {game_state.floor}    {hp}', 'WASD/arrows move · SPACE spell wheel']
        if self.mode == 'aim':
            lines.append(f'Aiming {self.aim_spell} — click a tile (Esc cancels)')
        for i, text in enumerate(lines):
            surf = self.font.render(text, True, (230, 230, 240))
            self.screen.blit(surf, (12, 10 + i * 22))

        log = get_singleton(MessageLog)
        for i, msg in enumerate(log.messages[-4:]):
            text, color = msg[0]
            surf = self.font.render(text, True, color)
            self.screen.blit(surf, (12, SCREEN_H - 96 + i * 22))

    # --- loop ---------------------------------------------------------------

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if not self._handle_event(event):
                    running = False

            # Freeze world time while a menu/aim overlay is up, like the real game.
            get_singleton(GameState).time_paused = self.mode != 'explore'
            get_singleton(GameState).display_mode = DisplayMode.EXPLORING
            esper.process()

            self.screen.fill(BG_COLOR)
            self._render_world()
            if self.mode == 'wheel':
                self._render_wheel()
            self._render_hud()
            pygame.display.flip()
            self.clock.tick(TICKS_PER_SECOND)

        pygame.quit()


if __name__ == '__main__':
    Prototype().run()
