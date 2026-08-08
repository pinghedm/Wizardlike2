"""InteractPromptSystem floats a talk/shop affordance over visible friendly NPCs.

Drives the system directly against a window-sized Surface (like test_render_system): a 20x20
clean room clamps the camera to (0, 0), so map tile (x, y) draws into the TILE_PX square at
pixel (x*TILE_PX, y*TILE_PX) and the tag sits in the band just above it.
"""

import esper
import pygame
import pytest

from src.components import NPC, InputAction, Position, Settings, Shopkeeper
from src.constants import TILE_PX, WINDOW_HEIGHT, WINDOW_WIDTH
from src.states import DisplayMode
from src.ui_systems.overlays import InteractPromptSystem
from tests.headless_runner import HeadlessRunner

SENTINEL = (255, 0, 255)


def _system(runner: HeadlessRunner) -> InteractPromptSystem:
    return InteractPromptSystem(runner.surface, runner.asset_loader)


def _tag_pixels(runner: HeadlessRunner, tile_x: int, tile_y: int, mode: DisplayMode) -> int:
    """Non-sentinel pixels the system paints in the band just above a tile — i.e. how much
    tag it drew there. Zero means nothing was drawn."""
    surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
    surface.fill(SENTINEL)
    runner.game_state.display_mode = mode
    band = pygame.Rect(0, tile_y * TILE_PX - TILE_PX, WINDOW_WIDTH, TILE_PX)
    InteractPromptSystem(surface, runner.asset_loader).process()
    return sum(
        surface.get_at((x, y))[:3] != SENTINEL
        for x in range(band.left, band.right)
        for y in range(max(0, band.top), band.bottom)
    )


def test_prompt_drawn_over_adjacent_visible_shopkeeper():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(Position(px + 1, py), Shopkeeper(offers=[]))
    runner.tick()  # compute FOV so the shopkeeper's tile is visible

    assert _tag_pixels(runner, px + 1, py, DisplayMode.EXPLORING) > 0


def test_no_prompt_outside_exploring():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(Position(px + 1, py), Shopkeeper(offers=[]))
    runner.tick()

    assert _tag_pixels(runner, px + 1, py, DisplayMode.MENU) == 0


def test_no_prompt_over_unseen_friendly():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    # Far outside the player's FOV radius, so its tile never enters visible_tiles.
    esper.create_entity(Position(px, py + 9), NPC(name='Old Wizard'))
    runner.tick()

    assert _tag_pixels(runner, px, py + 9, DisplayMode.EXPLORING) == 0


def test_friendlies_label_shopkeeper_and_npc():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    esper.create_entity(Position(px + 1, py), Shopkeeper(offers=[]))
    esper.create_entity(Position(px, py + 1), NPC(name='Old Wizard'))

    labels = {(name, verb) for _pos, name, verb in _system(runner)._friendlies()}
    assert labels == {('Merchant', 'Shop'), ('Old Wizard', 'Talk')}


@pytest.mark.parametrize('key, expected', [(pygame.K_RETURN, 'RETURN'), (pygame.K_e, 'E'), (pygame.K_SPACE, 'SPACE')])
def test_confirm_label_follows_binding(key, expected):
    runner = HeadlessRunner(use_random_map=False)
    esper.get_component(Settings)[0][1].keybindings.bindings[InputAction.CONFIRM] = key

    assert _system(runner)._confirm_label() == expected
