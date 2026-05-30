import os
import shutil

import pytest

# Point config/enum loading at the test-owned fixtures before any src module imports.
os.environ.setdefault('WIZARDLIKE_DATA_DIR', 'tests/fixtures')
os.environ.setdefault('WIZARDLIKE_SAVE_DIR', 'tests/test_save_data')

from src.constants import SAVE_DIR  # noqa: E402  (must follow the env setup above)


@pytest.fixture(autouse=True)
def isolate_save_dir():
    """Wipe the save dir around every test so persisted saves/meta don't leak between them."""
    shutil.rmtree(SAVE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(SAVE_DIR, ignore_errors=True)
