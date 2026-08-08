"""UI render processors, split by domain: full-screen menus, map overlays, and the HUD.

Re-exports the processor classes so callers import `from src.ui_systems import X`
unchanged. Submodules: `menus.py` (the `MenuSystem` modal screens), `overlays.py`
(targeting + transient combat visuals over the map), `hud.py` (the bottom HUD bar and
message modals).
"""

from src.ui_systems.hud import HUDSystem, ModalSystem
from src.ui_systems.menus import MenuSystem
from src.ui_systems.minimap import MapViewSystem, MinimapSystem
from src.ui_systems.overlays import EffectOverlaySystem, InteractPromptSystem, TargetingOverlaySystem

__all__ = [
    'EffectOverlaySystem',
    'HUDSystem',
    'InteractPromptSystem',
    'MapViewSystem',
    'MenuSystem',
    'MinimapSystem',
    'ModalSystem',
    'TargetingOverlaySystem',
]
