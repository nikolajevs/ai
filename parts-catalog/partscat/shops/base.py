"""Common shape of a shop adapter.

Parsing is done by plain functions on HTML or JSON (testable on saved pages); the Shop methods only
fetch through the polite Client and call them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ..http import Client
from ..models import Offer


class Unsupported(Exception):
    """The shop offers (or allows) no such operation; the message says why."""


@dataclass
class Category:
    shop: str
    url: str
    title: str
    count: int | None = None
    parent: str | None = None          # url of the parent category when the shop gives a tree


@dataclass
class Listing:
    offers: list[Offer] = field(default_factory=list)
    has_next: bool = False
    subcategories: list[Category] = field(default_factory=list)


class Shop:
    key = ''
    name = ''
    host = ''
    base = ''
    min_interval = 2.0
    can_search = True
    why_no_search = ''

    def __init__(self, client: Client):
        self.client = client
        client.min_interval.setdefault(self.host, self.min_interval)

    def owns(self, url: str) -> bool:
        return urlsplit(url).netloc.removeprefix('www.') == self.host.removeprefix('www.')

    def search(self, query: str, page: int = 1) -> Listing:
        raise Unsupported(self.why_no_search or f'{self.name}: поиск недоступен')

    def listing(self, category: Category, page: int = 1) -> Listing:
        raise Unsupported(f'{self.name}: списки категорий недоступны')

    def product(self, url: str) -> Offer:
        raise NotImplementedError

    def categories(self) -> list[Category]:
        return []
