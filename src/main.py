import atexit
import sys
import time
from collections.abc import Callable

import esper
import tcod
import tcod.sdl.joystick

from src import audio, persistence
from src.audio import AudioEngine, MusicTrack, SoundId
from src.components import InputAction, MessageLog, MetaSaveState, Modal, Settings
from src.constants import (
    DISPLAY_SCALE,
    FONT_TILE_PX,
    MAX_ITEMS_PER_ROOM,
    MAX_ROOMS,
    ROOM_MAX_SIZE,
    ROOM_MIN_SIZE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TICKS_PER_SECOND,
)
from src.data_loaders import AssetLoader, get_game_configs, load_music_config, load_sounds_config
from src.debug import debug_log
from src.ecs_helpers import get_singleton, try_get_singleton
from src.entities import (
    create_configuration,
    create_game_state,
    create_message_log,
    create_meta_save_state,
    create_player,
    create_run_stats,
    create_settings,
    create_ui_state,
)
from src.input_handlers import (
    ControllerInput,
    connected_controllers,
    handle_casting_input,
    handle_combining_input,
    handle_exploring_input,
    handle_game_over_input,
    handle_map_view_input,
    handle_menu_input,
    handle_modal_input,
    handle_settings_input,
    handle_shop_input,
    handle_targeting_input,
    note_controller_button,
    resolve_action,
    try_capture_remap_event,
)
from src.layout import Layout
from src.procgen import generate_dungeon
from src.states import DisplayMode, GameState, HandlerResult, PendingTransition
from src.systems import (
    ActionSystem,
    AISystem,
    DeathSystem,
    FOVSystem,
    HazardSystem,
    MetaSaveSystem,
    MomentumSystem,
    RenderSystem,
    StatusSystem,
    refill_basic_spells,
)
from src.targeting import CycleTargetSystem
from src.ui_systems import (
    EffectOverlaySystem,
    HUDSystem,
    MapViewSystem,
    MenuSystem,
    MinimapSystem,
    ModalSystem,
    TargetingOverlaySystem,
)


def init_game_world(asset_loader: AssetLoader):
    # Load cross-run progression (grimoire + gold).
    meta = persistence.load_meta()

    # Load Configs (memoized)
    configs = get_game_configs(asset_loader)

    # State
    create_game_state(floor=1)
    create_message_log()
    create_configuration(configs)
    create_ui_state()
    create_settings()
    create_run_stats()
    create_meta_save_state()

    # Generate Dungeon & Spawns
    game_map, player_start = generate_dungeon(
        max_rooms=MAX_ROOMS,
        room_min_size=ROOM_MIN_SIZE,
        room_max_size=ROOM_MAX_SIZE,
        max_items_per_room=MAX_ITEMS_PER_ROOM,
    )
    esper.create_entity(game_map)

    # ECS Entities
    player = create_player(x=player_start.x, y=player_start.y, meta=meta)
    refill_basic_spells()  # stock the always-known basic attacks for floor 1
    return player


def add_logic_systems():
    # Order matters: Death -> Action -> AI -> FOV -> CycleTarget (after FOV so it
    # re-locks against fresh visibility and enemy positions).
    esper.add_processor(DeathSystem())
    esper.add_processor(ActionSystem())
    esper.add_processor(StatusSystem())
    esper.add_processor(MomentumSystem())
    esper.add_processor(AISystem())
    esper.add_processor(HazardSystem())
    esper.add_processor(FOVSystem())
    esper.add_processor(CycleTargetSystem())
    esper.add_processor(MetaSaveSystem())


def add_render_systems(layout: Layout, asset_loader: AssetLoader):
    esper.add_processor(RenderSystem(layout, asset_loader))
    esper.add_processor(TargetingOverlaySystem(layout))
    esper.add_processor(EffectOverlaySystem(layout))
    esper.add_processor(MinimapSystem(layout, asset_loader))
    esper.add_processor(MenuSystem(layout))
    esper.add_processor(HUDSystem(layout))
    esper.add_processor(MapViewSystem(layout))
    esper.add_processor(ModalSystem(layout))


def init_main_menu():
    """Create the minimal state for the startup title screen.

    GameState (in MENU mode), UIState, and Settings are needed; the title screen has
    no player, map, or config. Settings (which holds the keybindings) lets the menu
    resolve input through the same action layer as the game, honoring any saved
    remaps. New Game / Continue build the full world from here.
    """
    create_game_state()
    create_ui_state()
    create_settings()
    create_meta_save_state()
    get_singleton(GameState).display_mode = DisplayMode.MENU


# Modes where game time keeps running: the live map (exploring) and aiming a spell
# (targeting), so foes keep acting while the player lines up a shot.
_REAL_TIME_MODES = (DisplayMode.EXPLORING, DisplayMode.TARGETING)


def update_pause_state(game_state: GameState):
    """Pause game time outside the real-time modes, or whenever a modal is open."""
    has_modal = bool(esper.get_component(Modal))
    game_state.time_paused = (game_state.display_mode not in _REAL_TIME_MODES) or has_modal


def _track_for_mode(mode: DisplayMode) -> MusicTrack:
    if mode in (DisplayMode.MENU, DisplayMode.GAME_OVER):
        return MusicTrack.MENU
    if mode == DisplayMode.SHOPPING:
        return MusicTrack.SHOP
    return MusicTrack.DUNGEON


def update_audio(audio_engine: AudioEngine | None, game_state: GameState):
    """Per-frame audio upkeep: re-attach the engine after a clear_database(), sync its volumes
    to the live Settings, and select the looping track for the current screen. No-op when audio
    is disabled (engine absent)."""
    if audio_engine is None:
        return
    audio_engine.reload_after_clear()
    settings = try_get_singleton(Settings)
    if settings is not None:
        audio_engine.apply_settings(settings.music_volume, settings.sfx_volume, settings.muted)
    audio_engine.play_music(_track_for_mode(game_state.display_mode))


def dispatch_input(
    event: tcod.event.Event, game_state: GameState, controller: ControllerInput, now: float
) -> PendingTransition | None:
    """The single input router: resolve any raw event to an action and dispatch it.

    Keyboard events resolve through resolve_action; controller events through
    ControllerInput.handle_event (d-pad/stick/triggers + the quick-cast modifier, with
    hold-to-repeat) — `now` drives that repeat timing. The live controller readout records
    a pressed button even when a pending Settings remap then consumes the event, so noting
    it comes first; the remap capture comes next, before the event resolves to its action.
    """
    keybindings = get_singleton(Settings).keybindings

    if isinstance(event, tcod.event.ControllerButton) and event.pressed:
        note_controller_button(event.button)

    if game_state.display_mode == DisplayMode.SETTINGS and try_capture_remap_event(event):
        return None

    if isinstance(event, (tcod.event.ControllerAxis, tcod.event.ControllerButton)):
        action = controller.handle_event(event, now, keybindings)
    else:
        action = resolve_action(event, keybindings)
    return dispatch_action(action, game_state)


# Screens that are pure menus/overlays: their cursor navigation and back-out click, and a
# bare confirm clicks too — except where confirm already yields a domain sound (a craft in
# COMBINING, a purchase in SHOPPING), which would otherwise layer two sounds.
_MENU_MODES = (
    DisplayMode.MENU,
    DisplayMode.COMBINING,
    DisplayMode.CASTING,
    DisplayMode.SHOPPING,
    DisplayMode.SETTINGS,
    DisplayMode.GAME_OVER,
    DisplayMode.MAP_VIEW,
)
_DOMAIN_CONFIRM_MODES = (DisplayMode.COMBINING, DisplayMode.SHOPPING)
_NAV_ACTIONS = (
    InputAction.MOVE_UP,
    InputAction.MOVE_DOWN,
    InputAction.MOVE_LEFT,
    InputAction.MOVE_RIGHT,
)


def _play_ui_cue(action: InputAction, mode: DisplayMode, modal_open: bool):
    """Click for menu navigation / confirm / cancel, while a modal is up or on a menu screen.
    Real-time modes (exploring, targeting) are excluded so movement keys stay silent."""
    if not (modal_open or mode in _MENU_MODES):
        return
    if action in _NAV_ACTIONS:
        audio.play_sfx(SoundId.MENU_MOVE)
    elif action == InputAction.CONFIRM and mode not in _DOMAIN_CONFIRM_MODES:
        audio.play_sfx(SoundId.MENU_CONFIRM)
    elif action in (InputAction.CANCEL, InputAction.OPEN_MENU):
        audio.play_sfx(SoundId.MENU_CANCEL)


# Each interactive screen's input handler, keyed by the mode it drives. A handler returns
# either the next screen (applied to display_mode) or a PendingTransition for the main loop.
_MODE_HANDLERS: dict[DisplayMode, Callable[[InputAction | None], HandlerResult]] = {
    DisplayMode.EXPLORING: handle_exploring_input,
    DisplayMode.MENU: handle_menu_input,
    DisplayMode.COMBINING: handle_combining_input,
    DisplayMode.CASTING: handle_casting_input,
    DisplayMode.TARGETING: handle_targeting_input,
    DisplayMode.SHOPPING: handle_shop_input,
    DisplayMode.SETTINGS: handle_settings_input,
    DisplayMode.GAME_OVER: handle_game_over_input,
    DisplayMode.MAP_VIEW: handle_map_view_input,
}


def dispatch_action(action: InputAction | None, game_state: GameState) -> PendingTransition | None:
    """Route a resolved input action to the active mode's handler.

    Both keyboard and controller input funnel through here as InputActions, so
    the handlers never see raw keys or buttons. A None action (unbound input) is
    a no-op. A handler either returns the next screen (applied to display_mode here)
    or a PendingTransition, which is returned for the main loop to carry out.
    """
    if action is None:
        return None

    modal_open = bool(esper.get_component(Modal))
    _play_ui_cue(action, game_state.display_mode, modal_open)
    if modal_open:
        handle_modal_input(action)
        return None

    handler = _MODE_HANDLERS.get(game_state.display_mode)
    if handler is None:
        return None
    result = handler(action)

    if isinstance(result, PendingTransition):
        return result
    game_state.display_mode = result
    return None


def apply_pending_transition(
    transition: PendingTransition | None, game_state: GameState, asset_loader: AssetLoader
) -> None:
    """Carry out a world-level command an input handler queued.

    EXIT quits the process. LOAD_SAVE / NEW_GAME / SAVE perform their I/O and reset the
    screen to EXPLORING; RETURN_TO_TITLE rebuilds the title menu. clear_database() and
    load_game() replace the GameState singleton, so re-fetch it via get_singleton().
    """
    if transition is None:
        return
    if transition == PendingTransition.EXIT:
        sys.exit()
    elif transition == PendingTransition.LOAD_SAVE:
        persistence.load_game()
        # A save predating these singletons carries none; seed them so input still
        # resolves and in-world gold changes still get flushed.
        if try_get_singleton(Settings) is None:
            create_settings()
        if try_get_singleton(MetaSaveState) is None:
            create_meta_save_state()
        get_singleton(GameState).display_mode = DisplayMode.EXPLORING
    elif transition == PendingTransition.NEW_GAME:
        esper.clear_database()
        init_game_world(asset_loader)
        get_singleton(GameState).display_mode = DisplayMode.EXPLORING
    elif transition == PendingTransition.RETURN_TO_TITLE:
        esper.clear_database()
        init_main_menu()
    elif transition == PendingTransition.SAVE:
        persistence.save_game()
        log = try_get_singleton(MessageLog)
        if log:
            log.add_simple_message('Game saved.', color=(0, 255, 255))
        game_state.display_mode = DisplayMode.EXPLORING


def main():
    # Persist any deferred cross-run progress on shutdown — covers every exit path
    # (window close, menu Quit, an unhandled exit) that the per-frame MetaSaveSystem,
    # which only flushes while paused, might not catch first.
    atexit.register(persistence.flush_meta)

    # Asset Loader
    asset_loader = AssetLoader()

    # Load Configs (memoized) to register sprites/chars
    get_game_configs(asset_loader)

    # BUILD the master tileset
    tileset = asset_loader.build_tileset()

    with tcod.context.new(
        columns=SCREEN_WIDTH,
        rows=SCREEN_HEIGHT,
        width=SCREEN_WIDTH * FONT_TILE_PX,
        height=SCREEN_HEIGHT * FONT_TILE_PX,
        tileset=tileset,
        title='WizardLike',
        vsync=True,
    ) as context:
        root_console = tcod.console.Console(SCREEN_WIDTH, SCREEN_HEIGHT)
        layout = Layout(root_console)

        # Register processors once. They are stateless and survive the
        # clear_database() done on load / new game, so they are never re-added.
        add_logic_systems()
        add_render_systems(layout, asset_loader)

        # Boot into the title screen (New Game / Continue / Quit).
        init_main_menu()

        # Open the audio device and start the menu music. main() holds the engine so it
        # survives the clear_database() on new game / load (update_audio re-attaches it);
        # shutdown closes the device on exit. Stays silent if no device is available.
        settings = get_singleton(Settings)
        audio_engine = audio.init_audio(
            sound_specs=load_sounds_config(),
            music_files=load_music_config(),
            music_volume=settings.music_volume,
            sfx_volume=settings.sfx_volume,
            muted=settings.muted,
        )
        atexit.register(audio.shutdown)

        # Enable gamepad input. Connected controllers are held in a list so SDL
        # keeps them open and keeps delivering their button events; the list is
        # refreshed when one is plugged in or removed.
        tcod.sdl.joystick.init()
        controllers = connected_controllers()
        debug_log(f'controllers connected: {len(controllers)}')

        # Turns d-pad / stick / trigger input into discrete, repeating actions.
        controller = ControllerInput()

        tick_rate = 1 / TICKS_PER_SECOND

        frame = 0
        while True:
            frame_start = time.perf_counter()
            frame += 1

            # React to a resized window: size the console to the window divided by
            # DISPLAY_SCALE (so present() upscales each cell), then repoint the
            # layout so its panels recompute. recommended_console_size() already
            # divides the window by the native tile size; DISPLAY_SCALE makes cells
            # that many times chunkier.
            native_columns, native_rows = context.recommended_console_size()
            columns = max(1, native_columns // DISPLAY_SCALE)
            rows = max(1, native_rows // DISPLAY_SCALE)
            if (columns, rows) != (root_console.width, root_console.height):
                root_console = tcod.console.Console(columns, rows)
                layout.console = root_console

            # Fetch fresh game state
            game_state = get_singleton(GameState)

            # Update time_paused based on mode or modals
            update_pause_state(game_state)

            # Keep audio attached, volumes synced, and the right track looping for this screen.
            update_audio(audio_engine, game_state)

            root_console.clear()

            # Run all processors
            debug_log(f'frame {frame}: process begin (mode={game_state.display_mode}, paused={game_state.time_paused})')
            esper.process()
            debug_log(f'frame {frame}: process end')

            context.present(root_console)
            debug_log(f'frame {frame}: present end')

            for event in tcod.event.get():
                if isinstance(event, tcod.event.Quit):
                    sys.exit()

                if isinstance(event, tcod.event.ControllerDevice):
                    controllers = connected_controllers()
                    debug_log(f'controllers changed: {len(controllers)} connected')
                    continue

                old_mode = game_state.display_mode
                debug_log(f'frame {frame}: dispatch {type(event).__name__}')
                transition = dispatch_input(event, game_state, controller, frame_start)

                # Carry out any queued world command. clear_database() wipes entities and
                # components but leaves the (stateless) processors in place, so a
                # load / new game may replace the GameState singleton.
                apply_pending_transition(transition, game_state, asset_loader)
                game_state = get_singleton(GameState)

                # If the state changed, break the event loop to redraw immediately
                if game_state.display_mode != old_mode:
                    break

            # A held d-pad / stick / trigger repeats like a held key, once it is due.
            repeat_action = controller.tick(frame_start)
            if repeat_action is not None:
                transition = dispatch_action(repeat_action, game_state)
                apply_pending_transition(transition, game_state, asset_loader)
                game_state = get_singleton(GameState)

            # Precise timing
            elapsed = time.perf_counter() - frame_start
            remaining = tick_rate - elapsed
            if remaining > 0:
                time.sleep(remaining)


if __name__ == '__main__':
    main()
