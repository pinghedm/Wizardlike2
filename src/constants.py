import os

# Dungeon size in tiles. Independent of the screen — kept larger than the map
# viewport so the camera scrolls to follow the player rather than showing it all.
MAP_WIDTH = 140
MAP_HEIGHT = 90
SCREEN_WIDTH = 80
SCREEN_HEIGHT = 50
TICKS_PER_SECOND = 30

# Dungeon room generation. Rooms are placed by rejection sampling, so MAX_ROOMS is
# an attempt count rather than a guarantee; a higher count packs the large map with
# rooms instead of long stretches of corridor.
MAX_ROOMS = 60
ROOM_MIN_SIZE = 9
ROOM_MAX_SIZE = 16

# Items scattered per room, drawn uniformly from 0..N. Scales up slightly with
# depth (see transition_to_next_floor).
MAX_ITEMS_PER_ROOM = 4

# Each logical console cell is drawn at this multiple of the tileset's native tile
# size, so the 10x10 font reads as chunky cells instead of tiny ones. The console
# is sized to window_pixels / (native_tile_px * DISPLAY_SCALE), so enlarging the
# window shows more cells (more map and HUD room) rather than just zooming in.
DISPLAY_SCALE = 2

# Number of floors in a full run. Reaching the exit on this floor wins the game;
# earlier floors descend deeper. Tune for run length / difficulty.
MAX_FLOORS = 10

# Cooldown (in ticks) the player incurs per move/cast, before status modifiers.
# At TICKS_PER_SECOND this caps the player's action rate; SLOW doubles it and
# HASTE halves it (see get_cooldown). Lower = more responsive movement.
PLAYER_MOVE_COST = 5

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
