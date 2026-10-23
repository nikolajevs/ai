"""What buying N pieces of an offer costs: packs, minimum quantity and quantity price tiers."""
from __future__ import annotations

from math import ceil


def cost_for(offer: dict, pieces: int) -> dict | None:
    """Cheapest way to get at least `pieces` pieces from one offer.

    Returns {'total', 'buy', 'unit', 'packs'} in EUR with VAT; None when the offer has no price.
    A pack offer (pack_qty > 1) is bought in whole packs at the pack price; other offers use the best
    quantity tier that the bought amount reaches.
    """
    price = offer.get('sale_price')
    if price is None:
        return None
    pieces = max(int(pieces), 1)
    pack = max(int(offer.get('pack_qty') or 1), 1)
    minimum = max(int(offer.get('min_qty') or 1), 1)
    if pack > 1:
        packs = max(ceil(pieces / pack), ceil(minimum / pack), 1)
        total = packs * price
        return dict(total=round(total, 2), buy=packs * pack, unit=round(total / (packs * pack), 4), packs=packs)
    buy = max(pieces, minimum)
    unit = offer.get('unit_price') if offer.get('unit_price') is not None else price
    for from_pieces, tier_price in sorted(tuple(t) for t in offer.get('tiers') or []):
        if buy >= from_pieces:
            unit = tier_price
    return dict(total=round(buy * unit, 2), buy=buy, unit=round(unit, 4), packs=None)


def stock_pieces(offer: dict) -> int | None:
    """Pieces on the shelf. For a pack offer the shop counts packs, so the count is multiplied by the pack size."""
    qty = offer.get('stock_qty')
    if qty is None:
        return None
    return qty * max(int(offer.get('pack_qty') or 1), 1)


def availability(offer: dict, pieces: int) -> str:
    """'ok' enough in stock, 'short' some but not enough, 'out' none, 'order' on order, 'unknown'."""
    state = offer.get('stock_state')
    have = stock_pieces(offer)
    if state == 'out' or have == 0:
        return 'out'
    if state == 'order':
        return 'order'
    if have is None:
        return 'unknown' if state == 'unknown' else 'ok'
    return 'ok' if have >= pieces else 'short'
