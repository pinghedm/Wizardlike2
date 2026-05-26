import os

# Point config/enum loading at the test-owned fixtures before any src module imports.
os.environ.setdefault('WIZARDLIKE_DATA_DIR', 'tests/fixtures')
os.environ.setdefault('WIZARDLIKE_SAVE_DIR', 'tests/test_save_data')
