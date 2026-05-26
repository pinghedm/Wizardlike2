import os

MAP_WIDTH = 80
MAP_HEIGHT = 45
SCREEN_WIDTH = 80
SCREEN_HEIGHT = 50
TICKS_PER_SECOND = 30

# Number of floors in a full run. Reaching the exit on this floor wins the game;
# earlier floors descend deeper. Tune for run length / difficulty.
MAX_FLOORS = 10

# Recurring status effects (poison, regen) fire one pulse every this many ticks
# while active. A status' authored `duration` is in ticks, so author it as a
# multiple of this interval to get a predictable number of pulses.
STATUS_PULSE_INTERVAL = 30

# Directory holding game-content YAML (ingredients, spells, tiles, etc.).
DATA_DIR = os.environ.get('WIZARDLIKE_DATA_DIR', 'data')

# Directory for save games and persistent meta-data (grimoire).
SAVE_DIR = os.environ.get('WIZARDLIKE_SAVE_DIR', 'save_data')

# UI colors
UI_WHITE = (255, 255, 255)
UI_YELLOW = (255, 255, 0)
UI_GRAY = (200, 200, 200)
UI_GRAY_DARK = (100, 100, 100)
UI_CYAN = (0, 255, 255)
UI_CYAN_DARK = (0, 200, 200)
UI_RED = (255, 0, 0)
UI_RED_DARK = (50, 0, 0)
