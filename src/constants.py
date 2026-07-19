import os
from collections.abc import Sequence

# An (r, g, b) color.
type RGB = tuple[int, int, int]


def to_rgb(color: Sequence[int]) -> RGB:
    """Coerce a 3-element color sequence (e.g. a YAML list or numpy pixel) into an RGB tuple."""
    r, g, b = color
    return (int(r), int(g), int(b))


# Dungeon size in tiles. Independent of the screen — kept larger than the map
# viewport so the camera scrolls to follow the player rather than showing it all.
MAP_WIDTH = 140
MAP_HEIGHT = 90
TICKS_PER_SECOND = 30

# A map tile is drawn TILE_PX square. UI_FONT_PX is the base HUD/menu text height. WINDOW_WIDTH/HEIGHT are
# the default window size; the viewport shows more map when the window is enlarged.
TILE_PX = 40
UI_FONT_PX = 20
WINDOW_WIDTH = 1600
WINDOW_HEIGHT = 1000

# Dungeon room generation. Rooms are placed by rejection sampling, so MAX_ROOMS is
# an attempt count rather than a guarantee; a higher count packs the large map with
# rooms instead of long stretches of corridor.
MAX_ROOMS = 60
ROOM_MIN_SIZE = 9
ROOM_MAX_SIZE = 16

# Items scattered per room, drawn uniformly from 0..N. Scales up slightly with
# depth (see transition_to_next_floor).
MAX_ITEMS_PER_ROOM = 4

# The UI/glyph typeface, loaded by AssetLoader.font() at each size it's asked for. Any
# .ttf/.otf works (swap the filename).
FONT_FILE = 'data/fonts/incite.ttf'

# Number of floors in a full run. Reaching the exit on this floor wins the game;
# earlier floors descend deeper. Tune for run length / difficulty.
MAX_FLOORS = 10

# Every SHOP_FLOOR_INTERVAL floors is a safe shop floor instead of a combat level, and the
# shop "tier" (floor // SHOP_FLOOR_INTERVAL) scales its heal cost/amount and rare-spell odds.
SHOP_FLOOR_INTERVAL = 3

# Bases for the shopkeeper's healing service. Each shop scales both the gold cost
# and the HP restored up with depth from these values.
SHOP_HEAL_BASE_PRICE = 20
SHOP_HEAL_BASE_AMOUNT = 50

# Chance per shop tier that a shop also stocks a rare, shop-only spell:
# ~10% at the first shop, ~20% at the second, ~30% at the third.
SHOP_RARE_SPELL_CHANCE = 0.1

# Cooldown (in ticks) the player incurs per move, before status modifiers.
# At TICKS_PER_SECOND this caps the player's action rate; SLOW doubles it and
# HASTE halves it (see get_action_cooldown). Lower = more responsive movement.
PLAYER_MOVE_COST = 5

# Casting is rate-limited (movement is not): each cast sets a cooldown that must elapse before the
# next. The base cost shrinks by LEVEL_CAST_SPEEDUP per player level and MASTERY_CAST_SPEEDUP per
# spell-mastery rank — investment makes a wizard cast faster — floored at MIN_CAST_COST (~move
# speed), then modulated by SLOW/HASTE. At TICKS_PER_SECOND=30, 27 ticks ≈ 0.9s between casts.
PLAYER_CAST_COST = 27
MIN_CAST_COST = 10
LEVEL_CAST_SPEEDUP = 1
MASTERY_CAST_SPEEDUP = 1

# Recurring status effects (poison, regen) fire one pulse every this many ticks
# while active. A status' authored `duration` is in ticks, so author it as a
# multiple of this interval to get a predictable number of pulses.
STATUS_PULSE_INTERVAL = 30

# Passive trap-spotting reach: a hidden trap surfaces only when the player sees a cell within
# this Chebyshev radius (see FOVSystem/_reveal_nearby_traps). 1 means adjacent-only — traps are
# near-invisible ambushes, and a reveal effect is how you light up a whole floor's worth at once.
# Enemies get no detection and blunder in.
TRAP_DETECT_RADIUS = 1

# Directory holding game-content YAML (ingredients, spells, tiles, etc.).
DATA_DIR = os.environ.get('WIZARDLIKE_DATA_DIR', 'data')

# Directory for save games and persistent meta-data (metaprogression).
SAVE_DIR = os.environ.get('WIZARDLIKE_SAVE_DIR', 'save_data')

# UI colors
UI_BLACK: RGB = (0, 0, 0)
UI_WHITE: RGB = (255, 255, 255)
UI_YELLOW: RGB = (255, 255, 0)
UI_GRAY: RGB = (200, 200, 200)
UI_GRAY_LIGHT: RGB = (220, 220, 220)
UI_GRAY_MID: RGB = (150, 150, 150)
UI_GRAY_DARK: RGB = (100, 100, 100)
UI_CYAN: RGB = (0, 255, 255)
UI_CYAN_DARK: RGB = (0, 200, 200)
UI_RED: RGB = (255, 0, 0)
UI_RED_DARK: RGB = (50, 0, 0)
UI_SALMON: RGB = (255, 100, 100)
UI_MAROON: RGB = (100, 0, 0)
UI_NAVY: RGB = (0, 0, 50)
UI_GREEN: RGB = (40, 160, 40)
UI_GREEN_MID: RGB = (50, 200, 50)
UI_GREEN_BRIGHT: RGB = (0, 255, 0)
UI_ORANGE: RGB = (255, 120, 0)
UI_BLUE: RGB = (80, 120, 255)
UI_SKY: RGB = (80, 170, 255)
UI_PERIWINKLE: RGB = (100, 100, 255)
UI_CRIMSON: RGB = (200, 0, 80)
UI_MAGENTA: RGB = (255, 0, 255)
