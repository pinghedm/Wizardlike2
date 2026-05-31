import random

import esper

from src import persistence
from src.components import (
    Configuration,
    Inventory,
    ItemType,
    KnownRecipes,
    PlayerTag,
    ShopOffer,
    ShopOfferKind,
    SpellInventory,
    SpellType,
    Stats,
)
from src.constants import SHOP_HEAL_BASE_AMOUNT, SHOP_HEAL_BASE_PRICE, SHOP_RARE_SPELL_CHANCE
from src.ecs_helpers import get_singleton
from src.states import GameState


def shop_heal(floor: int) -> dict:
    """The heal service's gold cost and HP restored, scaled up with depth."""
    tier = max(1, floor // 3)
    return {'price': SHOP_HEAL_BASE_PRICE * tier, 'amount': SHOP_HEAL_BASE_AMOUNT * tier}


def _spell_offer(s_conf: dict, known: KnownRecipes) -> ShopOffer:
    stype = SpellType(s_conf['id'])
    charges = s_conf['shop']['charges']
    suffix = 'learn recipe' if stype not in known.recipes else f'+{charges} charges'
    return ShopOffer(
        kind=ShopOfferKind.SPELL,
        price=s_conf['shop']['price'],
        label=f'{s_conf["name"]} ({suffix})',
        purchaseable=stype,
        amount=charges,
    )


def build_shop_offers() -> list[ShopOffer]:
    """Roll a shop's stock for the current floor: a heal, one random ingredient,
    one random ordinary spell, and (at a depth-scaled chance) one rare spell."""
    configs = get_singleton(Configuration)
    known = get_singleton(KnownRecipes)
    game_state = get_singleton(GameState)
    if configs is None or known is None or game_state is None:
        return []
    floor = game_state.floor

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
    ordinary = [s for s in shop_spells if not s.get('rare')]
    if ordinary:
        offers.append(_spell_offer(random.choice(ordinary), known))

    rare = [s for s in shop_spells if s.get('rare')]
    if rare and random.random() < SHOP_RARE_SPELL_CHANCE * (floor // 3):
        offers.append(_spell_offer(random.choice(rare), known))

    return offers


def purchase_offer(offer: ShopOffer, quantity: int = 1) -> bool:
    """Buy `quantity` units of `offer`. Returns False (no-op) if the quantity is
    invalid or unaffordable."""
    inventory = get_singleton(Inventory)
    total = offer.price * quantity
    if inventory is None or quantity < 1 or inventory.items.get(ItemType.GOLD, 0) < total:
        return False
    inventory.items[ItemType.GOLD] -= total

    gained = offer.amount * quantity
    if offer.kind == ShopOfferKind.INGREDIENT:
        inventory.items[offer.purchaseable] = inventory.items.get(offer.purchaseable, 0) + gained
    elif offer.kind == ShopOfferKind.SPELL:
        _grant_shop_spell(offer.purchaseable, gained)
    elif offer.kind == ShopOfferKind.HEAL:
        _heal_player(gained)

    persistence.save_meta()
    return True


def _grant_shop_spell(stype: SpellType, charges: int):
    """Grant `charges` of `stype`, teaching its first recipe if not yet known."""
    configs = get_singleton(Configuration)
    known = get_singleton(KnownRecipes)
    spell_inv = get_singleton(SpellInventory)
    if configs is None or known is None or spell_inv is None:
        return
    if stype not in known.recipes:
        s_conf = configs.spells_by_id.get(stype.value)
        if s_conf:
            known.recipes[stype] = {s_conf['recipes'][0]['ingredients']}
    spell_inv.spells[stype] = spell_inv.spells.get(stype, 0) + charges


def _heal_player(amount: int):
    """Restore `amount` HP to the player, capped at max."""
    for _ent, (stats, _tag) in esper.get_components(Stats, PlayerTag):
        stats.hp = min(stats.max_hp, stats.hp + amount)
