"""Input handling.

Split into `controller` (the device layer: keymap constants, event-to-action
resolution, Settings remap capture, and the gamepad ControllerInput) and `handlers`
(the per-display-mode `handle_*` action handlers). Public names are re-exported here
so callers import them as `from src.input_handlers import X`.
"""

from src.input_handlers.controller import (
    DPAD_MOVES,
    TRIGGER_ENGAGE,
    ControllerInput,
    connected_controller_name,
    connected_controllers,
    controller_binding_label,
    note_controller_button,
    resolve_action,
    try_capture_remap,
    try_capture_remap_axis,
)
from src.input_handlers.handlers import (
    handle_casting_input,
    handle_combining_input,
    handle_exploring_input,
    handle_game_over_input,
    handle_menu_input,
    handle_modal_input,
    handle_settings_input,
    handle_shop_input,
    handle_targeting_input,
)

__all__ = [
    'DPAD_MOVES',
    'TRIGGER_ENGAGE',
    'ControllerInput',
    'connected_controller_name',
    'connected_controllers',
    'controller_binding_label',
    'handle_casting_input',
    'handle_combining_input',
    'handle_exploring_input',
    'handle_game_over_input',
    'handle_menu_input',
    'handle_modal_input',
    'handle_settings_input',
    'handle_shop_input',
    'handle_targeting_input',
    'note_controller_button',
    'resolve_action',
    'try_capture_remap',
    'try_capture_remap_axis',
]
