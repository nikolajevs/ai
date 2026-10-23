"""Data carried from the shop adapters to the database."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Offer:
    """One product of one shop as the shop shows it.

    Prices are EUR including VAT. sale_price is the price of one sale unit (a pack of
    pack_qty pieces, or one piece); unit_price is always per piece.
    """
    shop: str
    shop_id: str
    url: str
    title: str
    mpn: str | None = None
    shop_sku: str | None = None
    brand: str | None = None
    category: str | None = None
    sale_price: float | None = None
    pack_qty: int = 1
    tiers: list[tuple[int, float]] = field(default_factory=list)   # (pieces from, price per piece)
    stock_qty: int | None = None
    stock_atleast: bool = False
    stock_text: str | None = None
    stock_state: str = 'unknown'                                   # in / out / order / unknown
    min_qty: int = 1
    note: str | None = None                                        # delivery date and similar
    props: dict[str, str] = field(default_factory=dict)
    detail: bool = False                                           # the product page was read

    @property
    def unit_price(self) -> float | None:
        if self.sale_price is None:
            return None
        return round(self.sale_price / max(self.pack_qty, 1), 4)
