import esper
import tcod.event

from src import persistence, shop
from src.components import (
    Enemy,
    Inventory,
    ItemType,
    KnownRecipes,
    Position,
    Shopkeeper,
    ShopOffer,
    ShopOfferKind,
    SpellInventory,
    SpellType,
    Stats,
)
from src.procgen import generate_shop_floor, is_shop_floor, spawn_shopkeeper
from src.shop import build_shop_offers, purchase_offer
from src.states import DisplayMode
from src.systems import craft_known_spell, match_recipe
from tests.headless_runner import HeadlessRunner

GOLD = ItemType('gold')
RARE_COMBO = tuple(sorted([ItemType('reagent_a'), ItemType('reagent_b'), ItemType('reagent_c')]))


def _force_shop_rng(monkeypatch, *, pick: int = 0, rare_roll: float = 0.99):
    """Make the shop's random picks deterministic: `pick` indexes each pool and
    `rare_roll` is the value compared against the rare-spell chance."""
    monkeypatch.setattr(shop.random, 'choice', lambda seq: seq[pick])
    monkeypatch.setattr(shop.random, 'random', lambda: rare_roll)


def _ingredient_offer(price: int = 5) -> ShopOffer:
    return ShopOffer(
        kind=ShopOfferKind.INGREDIENT, price=price, label='Reagent A', purchaseable=ItemType('reagent_a'), amount=1
    )


# --- build_shop_offers ---------------------------------------------------------


def test_shop_always_offers_heal_one_ingredient_and_one_spell(monkeypatch):
    HeadlessRunner()
    _force_shop_rng(monkeypatch)

    kinds = [o.kind for o in build_shop_offers()]

    assert kinds.count(ShopOfferKind.HEAL) == 1
    assert kinds.count(ShopOfferKind.INGREDIENT) == 1
    assert kinds.count(ShopOfferKind.SPELL) == 1  # no rare at floor 1 (chance is 0)


def test_shop_includes_rare_spell_when_the_roll_succeeds(monkeypatch):
    runner = HeadlessRunner()
    runner.game_state.floor = 3
    _force_shop_rng(monkeypatch, rare_roll=0.0)

    targets = [o.purchaseable for o in build_shop_offers() if o.kind == ShopOfferKind.SPELL]

    assert SpellType('test_rare') in targets


def test_shop_omits_rare_spell_when_the_roll_fails(monkeypatch):
    runner = HeadlessRunner()
    runner.game_state.floor = 3
    _force_shop_rng(monkeypatch, rare_roll=0.99)

    targets = [o.purchaseable for o in build_shop_offers() if o.kind == ShopOfferKind.SPELL]

    assert SpellType('test_rare') not in targets


# --- purchase_offer ------------------------------------------------------------


def test_buying_an_ingredient_deducts_gold_and_adds_stock():
    runner = HeadlessRunner()
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 100

    assert purchase_offer(_ingredient_offer(price=5), quantity=3) is True
    assert inv.items[GOLD] == 85
    assert inv.items[ItemType('reagent_a')] == 3


def test_purchase_fails_and_changes_nothing_when_unaffordable():
    runner = HeadlessRunner()
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 4

    assert purchase_offer(_ingredient_offer(price=5), quantity=1) is False
    assert inv.items[GOLD] == 4
    assert ItemType('reagent_a') not in inv.items


def test_purchase_rejects_nonpositive_quantity():
    runner = HeadlessRunner()
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 100

    assert purchase_offer(_ingredient_offer(), quantity=0) is False
    assert inv.items[GOLD] == 100


def test_buying_heal_restores_hp_capped_at_max():
    runner = HeadlessRunner()
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 100
    stats = esper.component_for_entity(runner.player, Stats)
    stats.hp = 50
    heal = ShopOffer(kind=ShopOfferKind.HEAL, price=10, label='Heal', amount=20)

    assert purchase_offer(heal, quantity=2) is True
    assert stats.hp == 90  # 50 + 2 * 20
    assert inv.items[GOLD] == 80

    assert purchase_offer(heal, quantity=1) is True
    assert stats.hp == stats.max_hp  # 110 clamped to 100


def test_buying_an_unknown_spell_teaches_the_recipe_and_grants_charges():
    runner = HeadlessRunner()
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 100
    known = esper.component_for_entity(runner.player, KnownRecipes)
    spell_inv = esper.component_for_entity(runner.player, SpellInventory)
    stype = SpellType('test_bolt')
    assert stype not in known.recipes

    offer = ShopOffer(kind=ShopOfferKind.SPELL, price=25, label='Test Bolt', purchaseable=stype, amount=4)
    assert purchase_offer(offer, quantity=1) is True

    assert stype in known.recipes
    assert spell_inv.spells[stype] == 4
    assert inv.items[GOLD] == 75


def test_a_purchase_persists_gold_to_meta():
    runner = HeadlessRunner()
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 50

    purchase_offer(_ingredient_offer(price=5), quantity=2)

    assert persistence.load_meta()['gold'] == 40


# --- rare spells & combine-discovery -------------------------------------------


def test_combining_cannot_discover_a_rare_spell():
    HeadlessRunner()

    assert match_recipe(RARE_COMBO) is None  # hidden from discovery
    assert match_recipe(RARE_COMBO, hide_rare=False) == (SpellType('test_rare'), 1)


def test_a_known_rare_spell_can_still_be_recrafted():
    runner = HeadlessRunner()
    stype = SpellType('test_rare')
    esper.component_for_entity(runner.player, KnownRecipes).recipes[stype] = {RARE_COMBO}
    inv = esper.component_for_entity(runner.player, Inventory)
    for r in ('reagent_a', 'reagent_b', 'reagent_c'):
        inv.items[ItemType(r)] = 1

    assert craft_known_spell(stype) == 1
    assert esper.component_for_entity(runner.player, SpellInventory).spells[stype] == 1


# --- shop floor generation -----------------------------------------------------


def test_shop_floor_has_a_shopkeeper_no_enemies_and_an_exit():
    runner = HeadlessRunner()
    runner.game_state.floor = 3
    assert is_shop_floor(3)

    new_map, _player_start = generate_shop_floor()

    assert len(esper.get_component(Shopkeeper)) == 1
    assert len(esper.get_component(Enemy)) == 0
    assert any(new_map.tiles[x][y].is_exit for x in range(new_map.width) for y in range(new_map.height))


# --- shop interaction ----------------------------------------------------------


def test_pressing_confirm_next_to_a_shopkeeper_opens_the_shop():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    spawn_shopkeeper(px + 1, py)

    runner.simulate_key(tcod.event.KeySym.RETURN)

    assert runner.display_mode == DisplayMode.SHOPPING


def test_buying_through_the_shop_ui_spends_gold_for_stock():
    runner = HeadlessRunner()
    px, py = runner.player_pos
    inv = esper.component_for_entity(runner.player, Inventory)
    inv.items[GOLD] = 100
    esper.create_entity(Position(px + 1, py), Shopkeeper(offers=[_ingredient_offer(price=5)]))

    runner.simulate_key(tcod.event.KeySym.RETURN)  # open shop
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # quantity -> 2
    runner.simulate_key(tcod.event.KeySym.RIGHT)  # quantity -> 3
    runner.simulate_key(tcod.event.KeySym.RETURN)  # buy 3

    assert inv.items[ItemType('reagent_a')] == 3
    assert inv.items[GOLD] == 85

    runner.simulate_key(tcod.event.KeySym.ESCAPE)
    assert runner.display_mode == DisplayMode.EXPLORING
