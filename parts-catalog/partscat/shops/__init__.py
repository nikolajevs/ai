"""Shop adapters."""
from __future__ import annotations

from ..http import Client
from .base import Shop
from .electrobase import Electrobase
from .lemona import Lemona
from .salvats import Salvats
from .semikom import Semikom

SHOP_CLASSES = (Salvats, Electrobase, Semikom, Lemona)
SHOP_NAMES = {cls.key: cls.name for cls in SHOP_CLASSES}


def all_shops(client: Client) -> dict[str, Shop]:
    return {cls.key: cls(client) for cls in SHOP_CLASSES}


def shop_for_url(shops: dict[str, Shop], url: str) -> Shop | None:
    """The adapter whose host the page address belongs to; 'lemona:30362' is a Lemona product without an address."""
    if url.strip().lower().startswith('lemona:'):
        return shops.get('lemona')
    return next((shop for shop in shops.values() if shop.owns(url)), None)
