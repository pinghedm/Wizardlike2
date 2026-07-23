import random
from typing import TypedDict

from src import persistence
from src.components import (
    Configuration,
    Inventory,
    ItemType,
    KnownRecipes,
    ShopOffer,
    ShopOfferKind,
    SpellConfig,
    SpellInventory,
    SpellType,
    Stats,
)
from src.constants import (
    SHOP_FLOOR_INTERVAL,
    SHOP_HEAL_BASE_AMOUNT,
    SHOP_HEAL_BASE_PRICE,
    SHOP_RARE_SPELL_CHANCE,
    TOWN_INGREDIENT_COUNT,
    TOWN_PRICE_MULTIPLIER,
)
from src.ecs_helpers import get_player_component, get_singleton, try_get_singleton
from src.states import GameState


class ShopHealConfig(TypedDict):
    price: int
    amount: int


def shop_heal(floor: int) -> ShopHealConfig:
    """The heal service's gold cost and HP restored, scaled up with depth."""
    tier = max(1, floor // SHOP_FLOOR_INTERVAL)
    return {'price': SHOP_HEAL_BASE_PRICE * tier, 'amount': SHOP_HEAL_BASE_AMOUNT * tier}


def _spell_offer(s_conf: SpellConfig, known: KnownRecipes) -> ShopOffer:
    stype = SpellType(s_conf['id'])
    shop = s_conf.get('shop')
    assert shop is not None  # caller only passes spells with a shop listing
    charges = shop['charges']
    suffix = 'learn recipe' if stype not in known.recipes else f'+{charges} charges'
    return ShopOffer(
        kind=ShopOfferKind.SPELL,
        price=shop['price'],
        label=f'{s_conf["name"]} ({suffix})',
        purchaseable=stype,
        amount=charges,
    )


def build_shop_offers() -> list[ShopOffer]:
    """Roll a shop's stock for the current floor: a heal, one random ingredient,
    one random ordinary spell, and (at a depth-scaled chance) one rare spell."""
    configs = try_get_singleton(Configuration)
    known = try_get_singleton(KnownRecipes)
    game_state = get_singleton(GameState)
    if configs is None or known is None:
        return []
    floor = game_state.floor
    assert floor is not None, 'the dungeon shop only exists on numbered floors'

    heal = shop_heal(floor)
    offers = [
        ShopOffer(
            kind=ShopOfferKind.HEAL,
            price=heal['price'],
            label=f'Heal {heal["amount"]} HP',
            amount=heal['amount'],
        )
    ]

    priced = [(iid, cfg) for iid, cfg in configs.ingredients.items() if 'price' in cfg]
    if priced:
        iid, cfg = random.choice(priced)
        offers.append(
            ShopOffer(
                kind=ShopOfferKind.INGREDIENT,
                price=cfg['price'],
                label=cfg['name'],
                purchaseable=ItemType(iid),
                amount=1,
            )
        )

    shop_spells = [s for s in configs.spells if 'shop' in s]
    # A charge top-up for one spell the player already knows; learning new spells is the
    # rare slot's job (below).
    ordinary = [s for s in shop_spells if not s.get('rare') and SpellType(s['id']) in known.recipes]
    if ordinary:
        offers.append(_spell_offer(random.choice(ordinary), known))

    rare = [s for s in shop_spells if s.get('rare')]
    if rare and random.random() < SHOP_RARE_SPELL_CHANCE * (floor // SHOP_FLOOR_INTERVAL):
        offers.append(_spell_offer(random.choice(rare), known))

    return offers


def build_town_offers() -> list[ShopOffer]:
    """The town merchant's between-run stock-up sheet: a charge top-up for every spell the
    player already knows plus TOWN_INGREDIENT_COUNT random ingredients, at a TOWN_PRICE_MULTIPLIER
    premium. Distinct from the dungeon shop — no heal (the player sets out at full HP)."""
    configs = try_get_singleton(Configuration)
    known = try_get_singleton(KnownRecipes)
    if configs is None or known is None:
        return []

    offers: list[ShopOffer] = []
    priced = [(iid, cfg) for iid, cfg in configs.ingredients.items() if 'price' in cfg]
    for iid, cfg in random.sample(priced, k=min(TOWN_INGREDIENT_COUNT, len(priced))):
        offers.append(
            ShopOffer(
                kind=ShopOfferKind.INGREDIENT,
                price=cfg['price'] * TOWN_PRICE_MULTIPLIER,
                label=cfg['name'],
                purchaseable=ItemType(iid),
                amount=1,
            )
        )

    for s_conf in configs.spells:
        stype = SpellType(s_conf['id'])
        shop = s_conf.get('shop')
        if shop is None or stype not in known.recipes:
            continue
        offers.append(
            ShopOffer(
                kind=ShopOfferKind.SPELL,
                price=shop['price'] * TOWN_PRICE_MULTIPLIER,
                label=f'{s_conf["name"]} (+{shop["charges"]} charges)',
                purchaseable=stype,
                amount=shop['charges'],
            )
        )

    return offers


def purchase_offer(offer: ShopOffer, quantity: int = 1) -> bool:
    """Buy `quantity` units of `offer`. Returns False (no-op) if the quantity is
    invalid or unaffordable."""
    inventory = try_get_singleton(Inventory)
    total = offer.price * quantity
    if inventory is None or quantity < 1 or inventory.items.get(ItemType.GOLD, 0) < total:
        return False
    inventory.items[ItemType.GOLD] -= total

    gained = offer.amount * quantity
    if offer.kind == ShopOfferKind.INGREDIENT:
        assert isinstance(offer.purchaseable, ItemType)
        inventory.items[offer.purchaseable] += gained
    elif offer.kind == ShopOfferKind.SPELL:
        assert isinstance(offer.purchaseable, SpellType)
        _grant_shop_spell(offer.purchaseable, gained)
    elif offer.kind == ShopOfferKind.HEAL:
        _heal_player(gained)

    persistence.save_meta()
    return True


def _grant_shop_spell(stype: SpellType, charges: int):
    """Grant `charges` of `stype`, teaching its first recipe if not yet known."""
    configs = try_get_singleton(Configuration)
    known = try_get_singleton(KnownRecipes)
    spell_inv = try_get_singleton(SpellInventory)
    if configs is None or known is None or spell_inv is None:
        return
    if stype not in known.recipes:
        s_conf = configs.spells_by_id.get(stype.value)
        if s_conf:
            known.recipes[stype] = {s_conf['recipes'][0]['ingredients']}
    spell_inv.spells[stype] += charges


def _heal_player(amount: int):
    """Restore `amount` HP to the player, capped at max."""
    stats = get_player_component(Stats)
    if stats is not None:
        stats.hp = min(stats.max_hp, stats.hp + amount)
