import esper

from src import persistence
from src.audio import SoundId, play_sfx
from src.components import (
    NPC,
    QUICK_CAST_ACTIONS,
    Configuration,
    Enemy,
    InputAction,
    Inventory,
    Item,
    ItemType,
    KnownRecipes,
    MessageLog,
    Modal,
    Position,
    RunStats,
    Settings,
    Shopkeeper,
    SpellInventory,
    SpellType,
    TargetingReticle,
    TargetMode,
    UIState,
)
from src.constants import (
    MAX_FLOORS,
    UI_GRAY,
    UI_RED,
    UI_SALMON,
    UI_SKY,
    UI_WHITE,
    UI_YELLOW,
)
from src.debug import debug_log
from src.ecs_helpers import (
    adjacent_component,
    exit_is_sealed,
    get_display_name,
    get_player,
    get_player_component,
    get_singleton,
    try_get_singleton,
)
from src.input_handlers.controller import move_delta
from src.map_objects import Map
from src.procgen import leave_town, transition_to_next_floor
from src.shop import purchase_offer
from src.states import (
    PAUSE_MENU_OPTIONS,
    TITLE_MENU_OPTIONS,
    CraftingView,
    DisplayMode,
    GameState,
    HandlerResult,
    MenuOption,
    PendingTransition,
    PostCastBehavior,
    SettingsPref,
)
from src.systems import (
    can_act,
    can_cast,
    cast_spell,
    craft_known_spell,
    deal_damage,
    discover_and_craft,
    get_spell_config,
    is_game_active,
    is_reagent,
    move_entity,
)
from src.targeting import refresh_lock, visible_enemies


def step_cursor(cursor: int, length: int, action: InputAction | None) -> int:
    """New cursor index after an up/down move, wrapping; 0 when the list is empty."""
    if length == 0:
        return 0
    cursor %= length
    if action == InputAction.MOVE_UP:
        return (cursor - 1) % length
    if action == InputAction.MOVE_DOWN:
        return (cursor + 1) % length
    return cursor


def handle_modal_input(action: InputAction | None):
    # Only Confirm dismisses a modal, so a movement input can't accidentally
    # confirm a descent or blow past the death screen.
    if action != InputAction.CONFIRM:
        return

    modals = esper.get_component(Modal)
    if modals:
        ent, modal = modals[0]
        if modal.page + 1 < len(modal.pages):
            modal.page += 1
            return
        if modal.on_close:
            modal.on_close()
        esper.delete_entity(ent)


def handle_game_over_input(action: InputAction | None) -> HandlerResult:
    """The run-summary screen. Confirm starts the next run back in the town (a fresh run seeded
    from persisted gold/recipes/mastery — the between-run home loop); Cancel/Menu bails out to
    the title. Nothing else acts."""
    if action == InputAction.CONFIRM:
        return PendingTransition.NEW_GAME  # a run always begins in the town, so this is the way home
    if action in (InputAction.CANCEL, InputAction.OPEN_MENU):
        return PendingTransition.RETURN_TO_TITLE
    return DisplayMode.GAME_OVER


def handle_map_view_input(action: InputAction | None) -> HandlerResult:
    """The full-screen map: the map key, Cancel, or Menu closes it back to exploring."""
    if action in (InputAction.OPEN_MAP, InputAction.CANCEL, InputAction.OPEN_MENU):
        return DisplayMode.EXPLORING
    return DisplayMode.MAP_VIEW


def handle_exploring_input(action: InputAction | None):
    game_state = get_singleton(GameState)

    player = get_player()
    if player is None:
        return DisplayMode.EXPLORING
    player_pos = esper.component_for_entity(player, Position)

    if action in QUICK_CAST_ACTIONS:
        return enter_targeting_for_slot(QUICK_CAST_ACTIONS.index(action))
    elif action == InputAction.OPEN_MENU:
        return DisplayMode.MENU
    elif action == InputAction.OPEN_CRAFTING:
        return DisplayMode.COMBINING
    elif action == InputAction.OPEN_WHEEL:
        return DisplayMode.SPELL_WHEEL
    elif action == InputAction.OPEN_MAP:
        return DisplayMode.MAP_VIEW
    elif action == InputAction.CONFIRM:
        if adjacent_component(player_pos, Shopkeeper) is not None:
            return DisplayMode.SHOPPING
        npc = adjacent_component(player_pos, NPC)
        if npc is not None:
            esper.create_entity(Modal(pages=npc.dialogue, title=npc.name))
    elif action == InputAction.SCROLL_UP:
        get_singleton(MessageLog).scroll_index += 1
    elif action == InputAction.SCROLL_DOWN:
        get_singleton(MessageLog).scroll_index -= 1

    dx, dy = move_delta(action)
    if dx != 0 or dy != 0:
        if not can_act(player):
            return DisplayMode.EXPLORING

        _bump_adjacent_enemy(player, player_pos.x + dx, player_pos.y + dy)
        move_entity(player, dx, dy)
        _pick_up_items(player)
        return _try_descend(game_state)

    return DisplayMode.EXPLORING


def _bump_adjacent_enemy(player: int, target_x: int, target_y: int):
    """Deal an enemy's bump damage to the player when its tile is the move target.

    Combat is decoupled from movement: this only applies the bump hit. move_entity then
    walks the player onto a non-blocking enemy, or is stopped by a blocking one.
    """
    near: list[str] = []
    for ent, (epos, enemy) in esper.get_components(Position, Enemy):
        if epos.x == target_x and epos.y == target_y:
            debug_log(f'bump: hit {get_display_name(ent)} at {(target_x, target_y)} for {enemy.bump_damage}')
            deal_damage(
                player,
                enemy.bump_damage,
                f'You bump into a {get_display_name(ent)} and take damage!',
                color=UI_RED,
            )
            return
        if abs(epos.x - target_x) <= 1 and abs(epos.y - target_y) <= 1:
            near.append(f'{get_display_name(ent)}@{(epos.x, epos.y)}')
    # A near miss: an enemy was next to the tile stepped into but not on it (e.g. it took its
    # own real-time tick and stepped away). Silent when no enemy is anywhere near (a plain walk).
    if near:
        debug_log(f'bump: stepped into {(target_x, target_y)}, no enemy on it; nearby={near}')


def _record_pickup(item: Item, run_stats: RunStats | None):
    """Play the pickup cue and tally the item: gold is run currency (flushed to the meta
    save), everything else is a crafting ingredient."""
    if item.type == ItemType.GOLD:
        play_sfx(SoundId.GOLD)
        if run_stats:
            run_stats.gold_collected += item.count
        persistence.mark_meta_dirty()
    else:
        play_sfx(SoundId.PICKUP)
        if run_stats:
            run_stats.ingredients_collected[item.type] += item.count


def _pick_up_items(player: int):
    """Collect every item on the player's tile into their inventory, tallying run stats
    and persisting gold the moment it is picked up."""
    player_pos = esper.component_for_entity(player, Position)
    player_inv = esper.component_for_entity(player, Inventory)
    log = get_singleton(MessageLog)
    run_stats = try_get_singleton(RunStats)
    for ent, (pos, item) in esper.get_components(Position, Item):
        if pos.x == player_pos.x and pos.y == player_pos.y:
            player_inv.items[item.type] += item.count
            log.add_simple_message(f'Picked up {item.count} {item.type.name}!', color=UI_GRAY)
            esper.delete_entity(ent)
            _record_pickup(item, run_stats)


def _try_descend(game_state: GameState) -> DisplayMode:
    """When the player stands on the exit, finish the run on the last floor (victory) or
    open the descend modal. Returns the resulting mode (EXPLORING when not on an exit)."""
    player = get_player()
    maps = esper.get_component(Map)
    if player is None or not maps:
        return DisplayMode.EXPLORING
    player_pos = esper.component_for_entity(player, Position)
    if not maps[0][1].tiles[player_pos.x][player_pos.y].is_exit:
        return DisplayMode.EXPLORING

    # Leaving the hub enters floor 1 — the hub is not a numbered floor and is never sealed.
    if game_state.is_town:
        esper.create_entity(Modal(pages=['You leave town and enter the dungeon...'], on_close=leave_town))
        return DisplayMode.EXPLORING

    if exit_is_sealed():
        get_singleton(MessageLog).add_simple_message(
            'The stairs are sealed — vanquish the gate guardians!', color=UI_YELLOW
        )
        return DisplayMode.EXPLORING

    assert game_state.floor is not None  # not in town, so we are on a numbered floor
    if game_state.floor >= MAX_FLOORS:
        get_singleton(MessageLog).add_simple_message('Level Complete!', color=UI_YELLOW)
        run_stats = try_get_singleton(RunStats)
        if run_stats:
            run_stats.won = True
        return DisplayMode.GAME_OVER

    esper.create_entity(
        Modal(
            pages=['You descend deeper into the dungeon...'],
            on_close=transition_to_next_floor,
        )
    )
    return DisplayMode.EXPLORING


def handle_settings_input(action: InputAction | None):
    ui_state = get_singleton(UIState)
    settings = get_singleton(Settings)
    actions = list(settings.keybindings.bindings.keys())
    # The preference toggles occupy the leading cursor rows; the rebindable keybindings follow.
    total_rows = len(SettingsPref) + len(actions)
    ui_state.settings_cursor %= total_rows

    if action in (InputAction.CANCEL, InputAction.OPEN_MENU):
        return DisplayMode.MENU
    if action in (InputAction.MOVE_UP, InputAction.MOVE_DOWN):
        ui_state.settings_cursor = step_cursor(ui_state.settings_cursor, total_rows, action)
    elif ui_state.settings_cursor < len(SettingsPref):
        _adjust_preference(settings, SettingsPref(ui_state.settings_cursor), action)
    elif action == InputAction.CONFIRM:
        # Arm the remap; try_capture_remap binds the next raw keypress / button.
        ui_state.remapping_action = actions[ui_state.settings_cursor - len(SettingsPref)]

    return DisplayMode.SETTINGS


# Left/right (or confirm) nudges a preference; the delta is the direction.
def _pref_delta(action: InputAction | None) -> int:
    if action in (InputAction.MOVE_RIGHT, InputAction.CONFIRM):
        return 1
    if action == InputAction.MOVE_LEFT:
        return -1
    return 0


def _adjust_preference(settings: Settings, pref: SettingsPref, action: InputAction | None):
    """Step the selected preference and persist it: post-cast cycles, volumes move in 10%
    steps, and mute toggles. Confirm/right advances, left goes back."""
    delta = _pref_delta(action)
    if delta == 0:
        return
    if pref == SettingsPref.POST_CAST:
        options = list(PostCastBehavior)
        settings.post_cast = options[(options.index(settings.post_cast) + delta) % len(options)]
    elif pref == SettingsPref.MUSIC_VOLUME:
        settings.music_volume = _clamp_volume(settings.music_volume + 0.1 * delta)
    elif pref == SettingsPref.SFX_VOLUME:
        settings.sfx_volume = _clamp_volume(settings.sfx_volume + 0.1 * delta)
    elif pref == SettingsPref.MUTED:
        settings.muted = not settings.muted
    persistence.save_meta()


def _clamp_volume(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 2)


def handle_menu_input(action: InputAction | None) -> HandlerResult:
    ui_state = get_singleton(UIState)

    # Title menu before a run starts, pause menu once a player exists.
    game_active = is_game_active()
    options = PAUSE_MENU_OPTIONS if game_active else TITLE_MENU_OPTIONS
    ui_state.main_menu_cursor %= len(options)

    if action in (InputAction.CANCEL, InputAction.OPEN_MENU):
        # Cancel/menu resumes an active game; at the title screen there is nothing
        # to resume, so stay on the menu.
        return DisplayMode.EXPLORING if game_active else DisplayMode.MENU

    elif action == InputAction.CONFIRM:
        selection = options[ui_state.main_menu_cursor]
        if selection == MenuOption.QUIT:
            return PendingTransition.EXIT
        elif selection == MenuOption.RESUME:
            return DisplayMode.EXPLORING
        elif selection == MenuOption.SAVE:
            return PendingTransition.SAVE
        elif selection == MenuOption.SETTINGS:
            return DisplayMode.SETTINGS
        elif selection in (MenuOption.CONTINUE, MenuOption.LOAD):
            if persistence.has_save():
                return PendingTransition.LOAD_SAVE
        elif selection == MenuOption.NEW_GAME:
            return PendingTransition.NEW_GAME

    else:
        ui_state.main_menu_cursor = step_cursor(ui_state.main_menu_cursor, len(options), action)

    return DisplayMode.MENU


def handle_combining_input(action: InputAction | None):
    ui_state = get_singleton(UIState)

    # Cycle between the manual experiment view and the spellbook.
    if action == InputAction.CYCLE_TAB:
        ui_state.crafting_view = (
            CraftingView.SPELLBOOK if ui_state.crafting_view == CraftingView.EXPERIMENT else CraftingView.EXPERIMENT
        )
        return DisplayMode.COMBINING

    # The crafting action, Cancel, or the menu key closes the whole screen from either view.
    if action in (InputAction.CANCEL, InputAction.OPEN_CRAFTING, InputAction.OPEN_MENU):
        return DisplayMode.EXPLORING

    if ui_state.crafting_view == CraftingView.SPELLBOOK:
        return _handle_spellbook_input(action, ui_state)
    return _handle_experiment_input(action, ui_state)


def _handle_experiment_input(action: InputAction | None, ui_state: UIState):
    """Manual ingredient combining: select reagents and combine to discover recipes."""
    player = get_player()
    if player is None:
        return DisplayMode.EXPLORING
    player_inv = esper.component_for_entity(player, Inventory)

    inv_list = sorted(i for i in player_inv.items if is_reagent(i))
    ui_state.crafting_cursor = step_cursor(ui_state.crafting_cursor, len(inv_list), action)

    if action == InputAction.MOVE_RIGHT:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) < player_inv.items[itype]:
                ui_state.selected_for_crafting[itype] = ui_state.selected_for_crafting.get(itype, 0) + 1

    elif action == InputAction.MOVE_LEFT:
        if inv_list:
            itype = inv_list[ui_state.crafting_cursor]
            if ui_state.selected_for_crafting.get(itype, 0) > 0:
                ui_state.selected_for_crafting[itype] -= 1

    elif action == InputAction.CONFIRM:
        return _combine_selection(ui_state)

    return DisplayMode.COMBINING


def _combine_selection(ui_state: UIState) -> DisplayMode:
    """Combine the experiment's selected ingredients into a spell. Reports success or a
    fizzle and clears the mix; returns EXPLORING on a successful craft, else COMBINING."""
    flat_selection: list[ItemType] = []
    for itype, count in ui_state.selected_for_crafting.items():
        flat_selection.extend([itype] * count)
    selection = tuple(sorted(flat_selection))
    if not selection:
        return DisplayMode.COMBINING

    log = get_singleton(MessageLog)
    result = discover_and_craft(selection)
    ui_state.selected_for_crafting = {}

    if result is None:
        play_sfx(SoundId.FIZZLE)
        log.add_simple_message('The combination fizzles...', color=UI_RED)
        return DisplayMode.COMBINING

    stype, charges = result
    log.add_message(
        [
            ('SUCCESS: Crafted ', UI_WHITE),
            (stype.name, UI_SKY),
            (f'! (+{charges} charges)', UI_WHITE),
        ]
    )
    return DisplayMode.EXPLORING


def _handle_spellbook_input(action: InputAction | None, ui_state: UIState):
    """Browse known recipes and instantly re-craft the selected one from stock."""
    player_recipes = get_player_component(KnownRecipes)
    if player_recipes is None:
        return DisplayMode.EXPLORING

    known = sorted(player_recipes.recipes.keys(), key=lambda s: s.name)
    ui_state.spellbook_cursor = step_cursor(ui_state.spellbook_cursor, len(known), action)

    if action == InputAction.CONFIRM and known:
        stype = known[ui_state.spellbook_cursor]
        log = get_singleton(MessageLog)
        charges = craft_known_spell(stype)
        s_conf = get_spell_config(stype.value)
        spell_name = s_conf.get('name', stype.name) if s_conf else stype.name

        if charges is None:
            log.add_simple_message(f'Not enough ingredients to craft {spell_name}.', color=UI_SALMON)
        else:
            log.add_message(
                [
                    ('Crafted ', UI_WHITE),
                    (spell_name, UI_SKY),
                    (f'! (+{charges} charges)', UI_WHITE),
                ]
            )

    return DisplayMode.COMBINING


def _spell_group_key(stype: SpellType) -> tuple[str, str]:
    """Sort key that clusters spells by their primary effect type, then name — so the wheel and
    list group like spells together (all damage, all heals, ...)."""
    s_conf = get_spell_config(stype.value)
    primary = s_conf['effects'][0].type.value if s_conf and s_conf['effects'] else ''
    return (primary, stype.name)


def available_spells() -> list[SpellType]:
    """The player's castable spells (those with charges), in the order they're listed and
    quick-cast slots are numbered. Basic spells anchor the low slots — they refill each floor,
    so they're the reliable fallback — followed by the discovered spells grouped by effect type."""
    spell_inv = get_player_component(SpellInventory)
    if spell_inv is None:
        return []
    configs = try_get_singleton(Configuration)
    basic_ids = {c['id'] for c in configs.spells if c.get('basic')} if configs else set[str]()
    charged = [s for s, n in spell_inv.spells.items() if n > 0]
    basics = sorted((s for s in charged if s.value in basic_ids), key=lambda s: s.name)
    rest = sorted((s for s in charged if s.value not in basic_ids), key=_spell_group_key)
    return basics + rest


def known_spells() -> list[SpellType]:
    """Every spell the player can cast — the always-known basics plus discovered recipes —
    charged or not, ordered like available_spells. The wheel shows all of these, greying out the
    depleted ones; the basics never grey out (they refill each floor)."""
    recipes = get_player_component(KnownRecipes)
    configs = try_get_singleton(Configuration)
    if recipes is None or configs is None:
        return []
    basics = {SpellType(c['id']) for c in configs.spells if c.get('basic')}
    known = basics | set(recipes.recipes.keys())
    ordered_basics = sorted((s for s in known if s in basics), key=lambda s: s.name)
    rest = sorted((s for s in known if s not in basics), key=_spell_group_key)
    return ordered_basics + rest


def enter_targeting_for_slot(slot: int) -> DisplayMode:
    """Ready the spell in `slot` of the available (charged) list, skipping the picker."""
    spells = available_spells()
    if slot >= len(spells):
        return get_singleton(GameState).display_mode
    return enter_targeting_for_spell(spells[slot])


def enter_targeting_for_spell(stype: SpellType) -> DisplayMode:
    """Ready `stype` for casting.

    Self-cast spells (target: self, e.g. heals/buffs) resolve on the caster immediately,
    with no targeting step. Otherwise the reticle locks onto the nearest visible enemy
    (replacing any reticle already up, so quick-cast works mid-aim), or no-ops with a
    message when none are in view.
    """
    player = get_player()
    if player is None:
        return get_singleton(GameState).display_mode

    s_conf = get_spell_config(stype.value)
    if s_conf is None:
        return get_singleton(GameState).display_mode

    ui_state = get_singleton(UIState)
    player_pos = esper.component_for_entity(player, Position)
    for ret_ent, _reticle in esper.get_component(TargetingReticle):
        esper.delete_entity(ret_ent)

    # A self-cast spell resolves on the caster, no targeting step.
    if s_conf['target'] == TargetMode.SELF:
        if not can_cast(player):
            play_sfx(SoundId.MENU_CANCEL)  # still recovering from the last cast
            return get_singleton(GameState).display_mode
        ui_state.active_targeting_spell_id = None
        cast_spell(spell_id=stype.value, target_x=player_pos.x, target_y=player_pos.y)
        return DisplayMode.EXPLORING

    reticle = TargetingReticle(x=player_pos.x, y=player_pos.y, radius=s_conf.get('radius', 0))
    refresh_lock(reticle, player)
    if reticle.target_ent is None:
        get_singleton(MessageLog).add_simple_message('No visible targets.', color=UI_GRAY)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.EXPLORING

    ui_state.active_targeting_spell_id = stype.value
    esper.create_entity(reticle)
    return DisplayMode.TARGETING


def _step_target(targets: list[int], current: int | None, step: int) -> int | None:
    """The next/previous target after `current`, wrapping; None when there are none."""
    if not targets:
        return None
    if current not in targets:
        return targets[0]
    return targets[(targets.index(current) + step) % len(targets)]


def _resolve_after_cast(ret_ent: int, ui_state: UIState) -> DisplayMode:
    """Apply the post-cast preference. Under STAY, keep the reticle up while charges remain;
    otherwise (the spell ran out, or RESELECT) drop to the picker to ready another, and EXPLORE
    leaves to the map."""
    spell_id = ui_state.active_targeting_spell_id
    behavior = get_singleton(Settings).post_cast
    spell_inv = get_player_component(SpellInventory)
    remaining = spell_inv.spells.get(SpellType(spell_id), 0) if (spell_inv and spell_id) else 0
    if behavior == PostCastBehavior.STAY and remaining > 0:
        return DisplayMode.TARGETING

    esper.delete_entity(ret_ent)
    ui_state.active_targeting_spell_id = None
    if behavior == PostCastBehavior.EXPLORE:
        return DisplayMode.EXPLORING
    return DisplayMode.SPELL_WHEEL


def handle_wheel_input(action: InputAction | None):
    """The radial spell wheel — the spell picker. It shows every known spell (depleted ones greyed
    out); Left/right (or up/down) rotate, Confirm fires the selected spell if it has charges, and
    the wheel key / Cancel / Menu close it."""
    ui_state = get_singleton(UIState)
    spell_inv = get_player_component(SpellInventory)
    if spell_inv is None:
        return DisplayMode.EXPLORING

    if action in (InputAction.CANCEL, InputAction.OPEN_WHEEL, InputAction.OPEN_MENU):
        return DisplayMode.EXPLORING

    spells = known_spells()
    if spells:
        cursor = ui_state.wheel_cursor % len(spells)
        if action in (InputAction.MOVE_RIGHT, InputAction.MOVE_DOWN):
            ui_state.wheel_cursor = (cursor + 1) % len(spells)
        elif action in (InputAction.MOVE_LEFT, InputAction.MOVE_UP):
            ui_state.wheel_cursor = (cursor - 1) % len(spells)
        elif action == InputAction.CONFIRM:
            stype = spells[cursor]
            if spell_inv.spells.get(stype, 0) > 0:
                return enter_targeting_for_spell(stype)
            play_sfx(SoundId.MENU_CANCEL)  # a depleted spell can't be cast

    return DisplayMode.SPELL_WHEEL


def handle_targeting_input(action: InputAction | None):
    """Lock onto visible enemies while staying mobile: the arrows walk the caster, Tab
    cycles to the next target, Confirm casts at the locked one (the reticle follows it as
    everyone moves), and cancel backs out to the wheel picker."""
    reticles = esper.get_component(TargetingReticle)
    if not reticles:
        return DisplayMode.EXPLORING
    ret_ent, reticle = reticles[0]
    ui_state = get_singleton(UIState)

    player = get_player()
    if player is None:
        return DisplayMode.EXPLORING

    # A quick-cast key swaps to that spell without leaving targeting.
    if action in QUICK_CAST_ACTIONS:
        return enter_targeting_for_slot(QUICK_CAST_ACTIONS.index(action))

    # Cancel, the wheel key, or the menu key back out to the wheel picker.
    if action in (InputAction.CANCEL, InputAction.OPEN_WHEEL, InputAction.OPEN_MENU):
        esper.delete_entity(ret_ent)
        ui_state.active_targeting_spell_id = None
        return DisplayMode.SPELL_WHEEL

    refresh_lock(reticle, player)

    if action == InputAction.CYCLE_TAB:
        reticle.target_ent = _step_target(visible_enemies(player), reticle.target_ent, 1)
        refresh_lock(reticle, player)
        return DisplayMode.TARGETING

    dx, dy = move_delta(action)
    if dx != 0 or dy != 0:
        if not can_act(player):
            return DisplayMode.TARGETING
        move_entity(player, dx, dy)  # the lock re-evaluates next tick
        _pick_up_items(player)
        # Stepping onto the exit descends (victory screen, or the descend modal), which leaves
        # targeting; otherwise keep aiming. _try_descend signals a descent via GAME_OVER or a
        # freshly opened Modal — a plain EXPLORING means we're not on an exit.
        result = _try_descend(get_singleton(GameState))
        if result is DisplayMode.GAME_OVER or esper.get_component(Modal):
            esper.delete_entity(ret_ent)
            ui_state.active_targeting_spell_id = None
            return result
        return DisplayMode.TARGETING

    if action == InputAction.CONFIRM:
        spell_id = ui_state.active_targeting_spell_id
        if spell_id is None:
            esper.delete_entity(ret_ent)
            return DisplayMode.SPELL_WHEEL
        if reticle.target_ent is None:
            return DisplayMode.TARGETING  # nothing to hit; wait for one to wander in
        if not can_cast(player):
            play_sfx(SoundId.MENU_CANCEL)  # still recovering from the last cast
            return DisplayMode.TARGETING
        cast_spell(spell_id=spell_id, target_x=reticle.x, target_y=reticle.y)
        return _resolve_after_cast(ret_ent, ui_state)

    return DisplayMode.TARGETING


def handle_shop_input(action: InputAction | None):
    ui_state = get_singleton(UIState)

    shopkeepers = esper.get_component(Shopkeeper)
    player_inv = get_player_component(Inventory)
    if not shopkeepers or player_inv is None:
        return DisplayMode.EXPLORING
    offers = shopkeepers[0][1].offers

    if action in (InputAction.CANCEL, InputAction.OPEN_MENU):
        return DisplayMode.EXPLORING
    if not offers:
        return DisplayMode.SHOPPING

    ui_state.shop_cursor %= len(offers)
    offer = offers[ui_state.shop_cursor]
    max_qty = max(1, player_inv.items.get(ItemType.GOLD, 0) // offer.price)
    ui_state.shop_quantity = max(1, min(ui_state.shop_quantity, max_qty))

    if action in (InputAction.MOVE_UP, InputAction.MOVE_DOWN):
        ui_state.shop_cursor = step_cursor(ui_state.shop_cursor, len(offers), action)
        ui_state.shop_quantity = 1
    elif action == InputAction.MOVE_LEFT:
        ui_state.shop_quantity = max(1, ui_state.shop_quantity - 1)
    elif action == InputAction.MOVE_RIGHT:
        ui_state.shop_quantity = min(max_qty, ui_state.shop_quantity + 1)
    elif action == InputAction.CONFIRM:
        log = get_singleton(MessageLog)
        quantity = ui_state.shop_quantity
        if purchase_offer(offer, quantity):
            play_sfx(SoundId.PURCHASE)
            log.add_simple_message(f'Bought {quantity}x {offer.label}.', color=UI_SKY)
        else:
            log.add_simple_message('Not enough gold.', color=UI_SALMON)
        ui_state.shop_quantity = 1

    return DisplayMode.SHOPPING
