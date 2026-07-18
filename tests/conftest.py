import os
import shutil

import pytest

# Point config/enum loading at the test-owned fixtures before any src module imports.
os.environ.setdefault('WIZARDLIKE_DATA_DIR', 'tests/fixtures')
os.environ.setdefault('WIZARDLIKE_SAVE_DIR', 'tests/test_save_data')
# Headless SDL: the pygame renderer needs a video/audio driver to open a display and
# convert() surfaces. The dummy drivers let the suite run without a real window or audio
# device, so `pytest` works as-is (no env vars to set by hand).
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame  # noqa: E402  (must follow the SDL env setup above)

from src.constants import SAVE_DIR  # noqa: E402  (must follow the env setup above)


@pytest.fixture(scope='session', autouse=True)
def _pygame_display():
    """Open a dummy display for the session so AssetLoader.get_sprite can convert()
    surfaces (convert requires an initialized video mode)."""
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


@pytest.fixture(autouse=True)
def isolate_save_dir():
    """Wipe the save dir around every test so persisted saves/meta don't leak between them."""
    shutil.rmtree(SAVE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(SAVE_DIR, ignore_errors=True)
