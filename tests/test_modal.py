"""ModalSystem draws a centered dialogue box pixel-native, so these are pixel smokes that it
renders when a Modal is open and stays blank otherwise (its page text is trivially the modal's
own data; wrapping is covered by test_ui_helpers.py)."""

import esper
import pygame

from src.components import Modal
from src.ui_systems import ModalSystem
from tests.headless_runner import HeadlessRunner

SENTINEL = (255, 0, 255)


def _draw_modal(runner: HeadlessRunner) -> pygame.Surface:
    runner.surface.fill(SENTINEL)
    ModalSystem(runner.surface, runner.asset_loader).process()
    return runner.surface


def test_open_modal_renders_a_box():
    runner = HeadlessRunner(use_random_map=False)
    esper.create_entity(Modal(pages=['Hello modal']))

    surface = _draw_modal(runner)
    drawn = any(tuple(surface.get_at((x, y)))[:3] != SENTINEL for x in range(700, 900, 20) for y in range(400, 600, 20))
    assert drawn


def test_no_modal_draws_nothing():
    runner = HeadlessRunner(use_random_map=False)  # no Modal entity
    assert tuple(_draw_modal(runner).get_at((800, 500)))[:3] == SENTINEL
