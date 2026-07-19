import esper
import pygame

from src.components import Inventory, Item, ItemType, Loot, LootDrop, Position, Stats
from src.ecs_helpers import spawn_item_entity
from src.systems import DeathSystem, roll_loot
from tests.headless_runner import HeadlessRunner

GOLD = ItemType('gold')
REAGENT = ItemType('reagent_a')


def _force_roll(monkeypatch, *, pick: int = 0, count: int = 1):
    """Make roll_loot deterministic: pick drop index `pick`, roll quantity `count`."""
    monkeypatch.setattr('src.systems.combat.random.choices', lambda population, weights=None, k=1: [population[pick]])
    monkeypatch.setattr('src.systems.combat.random.randint', lambda lo, hi: count)


# --- roll_loot ----------------------------------------------------------------


def test_roll_loot_returns_weighted_pick_with_rolled_quantity(monkeypatch):
    HeadlessRunner(use_random_map=False)
    _force_roll(monkeypatch, pick=0, count=3)
    loot = Loot(drops=[LootDrop(GOLD, 2, 4, chance=1.0), LootDrop(REAGENT, 1, 1, chance=1.0)])

    assert roll_loot(loot) == (GOLD, 3)


def test_roll_loot_returns_none_when_quantity_is_zero(monkeypatch):
    HeadlessRunner(use_random_map=False)
    _force_roll(monkeypatch, pick=0, count=0)
    loot = Loot(drops=[LootDrop(GOLD, 0, 4, chance=1.0)])

    assert roll_loot(loot) is None


def test_roll_loot_returns_none_with_empty_table():
    HeadlessRunner(use_random_map=False)
    assert roll_loot(Loot(drops=[])) is None


# --- DeathSystem drops --------------------------------------------------------


def test_death_system_drops_loot_at_enemy_tile(monkeypatch):
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    enemy = runner.spawn_enemy(px + 3, py)
    esper.add_component(enemy, Loot(drops=[LootDrop(GOLD, 2, 4, chance=1.0)]))
    enemy_pos = esper.component_for_entity(enemy, Position)
    esper.component_for_entity(enemy, Stats).hp = 0

    _force_roll(monkeypatch, pick=0, count=3)
    DeathSystem().process()

    dropped = [
        item for _e, (pos, item) in esper.get_components(Position, Item) if (pos.x, pos.y) == (enemy_pos.x, enemy_pos.y)
    ]
    assert (GOLD, 3) in [(d.type, d.count) for d in dropped]


# --- pickup -------------------------------------------------------------------


def test_pickup_leaves_items_on_other_tiles():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    spawn_item_entity(GOLD, px + 2, py, count=1)  # two tiles off, not where we step

    runner.simulate_key(pygame.K_RIGHT)  # step to px+1; the scan skips the far pile

    assert any(item.type == GOLD for _e, (_pos, item) in esper.get_components(Position, Item))


def test_pickup_credits_the_stack_count():
    runner = HeadlessRunner(use_random_map=False)
    px, py = runner.player_pos
    spawn_item_entity(GOLD, px + 1, py, count=7)

    runner.simulate_key(pygame.K_RIGHT)

    inv = esper.component_for_entity(runner.player, Inventory)
    assert inv.items.get(GOLD, 0) == 7
    # The pickup's delete is deferred; a tick flushes it and consumes the entity.
    runner.tick(1)
    assert not any(item.type == GOLD for _e, (_pos, item) in esper.get_components(Position, Item))
