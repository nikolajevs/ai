"""Salvats (www.salvats.lv): plain HTML, robots.txt allows everything.

Search is /lv/search-results?product=<text>&page=N, categories are /lv/<slug>?page=N with 20 cards per page.
'Artikuls' is the manufacturer part number; the first word of the title is a short house alias that can
differ from it (title '22E10N ...', Artikuls 'TK22E10N1'), so MPN comes from the Artikuls field only.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..models import Offer
from ..normalize import clean, parse_pack, parse_price, parse_stock
from .base import Category, Listing, Shop

BASE = 'https://www.salvats.lv'


def _labelled(container) -> dict[str, str]:
    """{'ID': '00026030', 'Artikuls': 'FDB5800', 'Noliktavas stāvoklis': '4'} from alternating label / value strings."""
    out: dict[str, str] = {}
    label = None
    for text in container.stripped_strings:
        if text.endswith(':'):
            label = text[:-1].strip()
        elif label:
            out.setdefault(label, text)
            label = None
    return out


def _stock(value: str | None) -> tuple[int | None, bool, str, str | None]:
    if value is None:
        return None, False, 'unknown', None
    qty, atleast, state = parse_stock(value)
    return qty, atleast, state, value


def _current_page(url: str) -> int:
    values = parse_qs(urlsplit(url).query).get('page')
    return int(values[0]) if values and values[0].isdigit() else 1


def parse_listing(html: str, page_url: str = BASE) -> Listing:
    soup = BeautifulSoup(html, 'html.parser')
    out = Listing()
    for card in soup.select('div.product-item'):
        details = card.select_one('div.product-item-details') or card
        link = details.select_one('div.product-item-name a[href]') or card.select_one('a[href]')
        if link is None:
            continue
        url = urljoin(page_url, link['href'])
        title = clean(link.get_text(' '))
        price_box = details.select_one('div.price-box')
        price = parse_price(re.sub(r'Cena:?', '', price_box.get_text(' '))) if price_box else None
        if price is None:
            out.subcategories.append(Category(shop='salvats', url=url, title=title))     # category tile, not a product
            continue
        fields = _labelled(details.select_one('div.product-des') or details)
        product_id = fields.get('ID', '')
        if not product_id.isdigit():
            hidden = card.select_one('input[type=hidden][value]')
            product_id = hidden['value'] if hidden and hidden['value'].isdigit() else url
        qty, atleast, state, text = _stock(fields.get('Noliktavas stāvoklis'))
        crumbs = [clean(a.get_text(' ')) for a in details.select('ul.product-breadcrumbs li a')]
        sku = fields.get('Artikuls')
        out.offers.append(Offer(
            shop='salvats', shop_id=str(int(product_id)) if product_id.isdigit() else product_id, url=url, title=title,
            mpn=sku, shop_sku=sku, category=' / '.join(crumbs) or None, sale_price=price, pack_qty=parse_pack(title),
            stock_qty=qty, stock_atleast=atleast, stock_text=text, stock_state=state))
    here = _current_page(page_url)
    pages = [int(m.group(1)) for a in soup.select('a[href*="page="]') if (m := re.search(r'[?&]page=(\d+)', a['href']))]
    out.has_next = bool(pages) and max(pages) > here
    return out


def parse_product(html: str, url: str) -> Offer:
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('h1.product-item-name') or soup.select_one('h1')
    title = clean(heading.get_text(' ')) if heading else ''
    price_box = soup.select_one('div.product-item-details div.price-box') or soup.select_one('div.price-box')
    price = parse_price(re.sub(r'Cena:?', '', price_box.get_text(' '))) if price_box else None
    info = soup.select_one('div.product-info-stock-sku')
    fields = {}
    if info:
        for row in info.select('div'):
            label, value = row.select_one('label'), row.select_one('span.info-deta')
            if label and value:
                fields[clean(label.get_text()).rstrip(':')] = clean(value.get_text())
    props: dict[str, str] = {}
    for item in soup.select('ul.description-list-colors li'):
        label, _, value = item.get_text('\t', strip=True).partition('\t')
        label, value = clean(label), clean(value)
        if label and value:
            props[label] = f'{props[label]}, {value}' if label in props else value
    crumbs = [clean(a.get_text(' ')) for a in soup.select('div.bread-crumb li a')]
    qty, atleast, state, text = _stock(fields.get('Noliktavas stāvoklis'))
    product_id = fields.get('ID', '')
    sku = fields.get('Artikuls')
    return Offer(
        shop='salvats', shop_id=str(int(product_id)) if product_id.isdigit() else url, url=url, title=title,
        mpn=sku, shop_sku=sku, brand=props.get('Manufacturer'), category=' / '.join(crumbs[-4:]) or None,
        sale_price=price, pack_qty=parse_pack(title), stock_qty=qty, stock_atleast=atleast, stock_text=text,
        stock_state=state, props=props, detail=True)


def parse_menu(html: str) -> list[Category]:
    """Category tree from the mega menu (levels 2 and 3)."""
    soup = BeautifulSoup(html, 'html.parser')
    out, seen = [], set()
    for level, parent_class in (('level2', None), ('level3', 'level2')):
        for item in soup.select(f'li.{level}'):
            link = item.find('a', href=True)
            if link is None:
                continue
            url = urljoin(BASE, link['href'])
            title = clean(link.get_text(' ')).lstrip('■').strip()
            if url in seen or not title:
                continue
            seen.add(url)
            parent = None
            if parent_class:
                holder = item.find_parent('li', class_=parent_class)
                anchor = holder.find('a', href=True) if holder else None
                parent = urljoin(BASE, anchor['href']) if anchor else None
            out.append(Category(shop='salvats', url=url, title=title, parent=parent))
    return out


class Salvats(Shop):
    key = 'salvats'
    name = 'Salvats'
    host = 'www.salvats.lv'
    base = BASE
    min_interval = 1.5

    def search(self, query: str, page: int = 1) -> Listing:
        reply = self.client.get(f'{BASE}/lv/search-results', params={'product': query, 'page': page})
        return parse_listing(reply.text, reply.url)

    def listing(self, category: Category, page: int = 1) -> Listing:
        reply = self.client.get(category.url, params={'page': page} if page > 1 else None)
        result = parse_listing(reply.text, reply.url)
        for offer in result.offers:
            offer.category = offer.category or category.title
        return result

    def product(self, url: str) -> Offer:
        reply = self.client.get(url)
        return parse_product(reply.text, url)

    def categories(self) -> list[Category]:
        return parse_menu(self.client.get(f'{BASE}/lv').text)
