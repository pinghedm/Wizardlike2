import esper
import tcod

from src.components import Configuration, EffectType, SpellInventory, SpellType, Stats
from src.states import DisplayMode
from tests.headless_runner import HeadlessRunner


def test_full_gameplay_loop():
    runner = HeadlessRunner(use_random_map=False)

    # 1. Setup: Give ingredients
    runner.give_item('reagent_a', 1)
    runner.give_item('reagent_b', 1)

    # 2. Spawn enemy
    enemy_starting_hp = 20
    enemy_ent = runner.spawn_enemy(runner.player_pos.x + 1, runner.player_pos.y, hp=enemy_starting_hp)

    # 3. Enter Crafting Mode
    runner.simulate_key(tcod.event.KeySym.c)
    assert runner.display_mode == DisplayMode.COMBINING

    # 4. Select ingredients (Right selects, Down moves cursor)
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # select reagent A
    runner.simulate_key(tcod.event.KeySym.DOWN)  # move cursor to reagent B
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # select reagent B

    # 5. Craft
    runner.simulate_key(tcod.event.KeySym.RETURN)  # Confirm craft
    assert runner.display_mode == DisplayMode.EXPLORING

    # 6. Check Inventory
    player_spell_inv = esper.component_for_entity(runner.player, SpellInventory)
    assert SpellType('test_bolt') in player_spell_inv.spells
    assert player_spell_inv.spells[SpellType('test_bolt')] == 3

    # 7. Cast
    runner.simulate_key(tcod.event.KeySym.s)
    assert runner.display_mode == DisplayMode.CASTING
    runner.simulate_key(tcod.event.KeySym.RETURN)  # Confirm spell
    assert runner.display_mode == DisplayMode.TARGETING

    # 8. Fire
    # Currently, the UI system targets the player's position by default.
    # Move the reticle to the enemy's position.
    runner.simulate_key(tcod.event.KeySym.RIGHT)
    runner.simulate_key(tcod.event.KeySym.RETURN)  # Confirm targeting
    assert runner.display_mode == DisplayMode.EXPLORING

    # 9. Tick to process damage
    runner.tick(2)

    # 10. Check enemy HP and logs
    if esper.entity_exists(enemy_ent):
        stats = esper.component_for_entity(enemy_ent, Stats)
        configs = esper.get_component(Configuration)[0][1]
        spells_config = configs.spells
        s_conf = next((s for s in spells_config if s['id'] == 'test_bolt'), None)
        damage = [e for e in s_conf['effects'] if e.type == EffectType.DAMAGE][0].power
        assert stats.hp == (enemy_starting_hp - damage)  # Ensure damage was taken

    messages = runner.get_log_messages()
    assert any('took 12 damage!' in msg for msg in messages)
