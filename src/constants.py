import os

MAP_WIDTH = 80
MAP_HEIGHT = 45
SCREEN_WIDTH = 80
SCREEN_HEIGHT = 50
TICKS_PER_SECOND = 30

# Directory holding game-content YAML (ingredients, spells, tiles, etc.).
DATA_DIR = os.environ.get('WIZARDLIKE_DATA_DIR', 'data')
