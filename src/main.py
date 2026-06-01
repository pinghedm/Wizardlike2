import sys
import time

import esper
import tcod

from src import persistence
from src.components import MessageLog, Modal
from src.constants import (
    DISPLAY_SCALE,
    MAX_ITEMS_PER_ROOM,
    MAX_ROOMS,
    ROOM_MAX_SIZE,
    ROOM_MIN_SIZE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TICKS_PER_SECOND,
)
from src.data_loaders import AssetLoader, get_game_configs
from src.debug import debug_log
from src.ecs_helpers import get_singleton, try_get_singleton
from src.entities import (
    create_configuration,
    create_game_state,
    create_keybindings,
    create_message_log,
    create_player,
    create_run_stats,
    create_ui_state,
)
from src.input_handlers import (
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
from src.layout import Layout
from src.procgen import generate_dungeon
from src.states import DisplayMode, GameState
from src.systems import (
    ActionSystem,
    AISystem,
    DeathSystem,
    FOVSystem,
    RenderSystem,
    StatusSystem,
)
from src.ui_systems import (
    EffectOverlaySystem,
    HUDSystem,
    MenuSystem,
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
    create_keybindings()
    create_run_stats()

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
    return player


def add_logic_systems():
    # Order matters: Death -> Action -> AI -> FOV
    esper.add_processor(DeathSystem())
    esper.add_processor(ActionSystem())
    esper.add_processor(StatusSystem())
    esper.add_processor(AISystem())
    esper.add_processor(FOVSystem())


def add_render_systems(layout: Layout, asset_loader: AssetLoader):
    esper.add_processor(RenderSystem(layout, asset_loader))
    esper.add_processor(TargetingOverlaySystem(layout))
    esper.add_processor(EffectOverlaySystem(layout))
    esper.add_processor(MenuSystem(layout))
    esper.add_processor(HUDSystem(layout))
    esper.add_processor(ModalSystem(layout))


def init_main_menu():
    """Create the minimal state for the startup title screen.

    Only GameState (in MENU mode) and UIState are needed; the title screen has
    no player, map, or config. New Game / Continue build the full world from here.
    """
    create_game_state()
    create_ui_state()
    get_singleton(GameState).display_mode = DisplayMode.MENU


def update_pause_state(game_state: GameState):
    """Pause game time whenever not exploring or a modal is open."""
    has_modal = bool(esper.get_component(Modal))
    game_state.time_paused = (game_state.display_mode != DisplayMode.EXPLORING) or has_modal


def dispatch_input(event: tcod.event.Event, game_state: GameState):
    if esper.get_component(Modal):
        handle_modal_input(event)
        return

    if game_state.display_mode == DisplayMode.EXPLORING:
        game_state.display_mode = handle_exploring_input(event)
    elif game_state.display_mode == DisplayMode.MENU:
        game_state.display_mode = handle_menu_input(event)
    elif game_state.display_mode == DisplayMode.COMBINING:
        game_state.display_mode = handle_combining_input(event)
    elif game_state.display_mode == DisplayMode.CASTING:
        game_state.display_mode = handle_casting_input(event)
    elif game_state.display_mode == DisplayMode.TARGETING:
        game_state.display_mode = handle_targeting_input(event)
    elif game_state.display_mode == DisplayMode.SHOPPING:
        game_state.display_mode = handle_shop_input(event)
    elif game_state.display_mode == DisplayMode.SETTINGS:
        game_state.display_mode = handle_settings_input(event)
    elif game_state.display_mode == DisplayMode.GAME_OVER:
        game_state.display_mode = handle_game_over_input(event)


def apply_pending_transition(game_state: GameState, asset_loader: AssetLoader) -> None:
    """Carry out the side effects of a pending world-transition display_mode.

    EXITING quits the process. LOADING_SAVE / STARTING_NEW_GAME / SAVING perform
    their I/O and reset the mode to EXPLORING. clear_database()/load_game()
    replace the GameState singleton, so re-fetch it via get_singleton().
    """
    mode = game_state.display_mode
    if mode == DisplayMode.EXITING:
        sys.exit()
    elif mode == DisplayMode.LOADING_SAVE:
        persistence.load_game()
        get_singleton(GameState).display_mode = DisplayMode.EXPLORING
    elif mode == DisplayMode.STARTING_NEW_GAME:
        esper.clear_database()
        init_game_world(asset_loader)
        get_singleton(GameState).display_mode = DisplayMode.EXPLORING
    elif mode == DisplayMode.RETURN_TO_TITLE:
        esper.clear_database()
        init_main_menu()
    elif mode == DisplayMode.SAVING:
        persistence.save_game()
        log = try_get_singleton(MessageLog)
        if log:
            log.add_simple_message('Game saved.', color=(0, 255, 255))
        game_state.display_mode = DisplayMode.EXPLORING


def main():
    # Asset Loader
    asset_loader = AssetLoader()

    # Load Configs (memoized) to register sprites/chars
    get_game_configs(asset_loader)

    # BUILD the master tileset
    tileset = asset_loader.build_tileset()

    with tcod.context.new(
        columns=SCREEN_WIDTH,
        rows=SCREEN_HEIGHT,
        width=SCREEN_WIDTH * 20,
        height=SCREEN_HEIGHT * 20,
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

                old_mode = game_state.display_mode
                debug_log(f'frame {frame}: dispatch {type(event).__name__}')
                dispatch_input(event, game_state)

                # Handle world transitions. clear_database() wipes entities and
                # components but leaves the (stateless) processors in place, so a
                # load / new game may replace the GameState singleton.
                apply_pending_transition(game_state, asset_loader)
                game_state = get_singleton(GameState)

                # If the state changed, break the event loop to redraw immediately
                if game_state.display_mode != old_mode:
                    break

            # Precise timing
            elapsed = time.perf_counter() - frame_start
            remaining = tick_rate - elapsed
            if remaining > 0:
                time.sleep(remaining)


if __name__ == '__main__':
    main()
