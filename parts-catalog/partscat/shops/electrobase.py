"""Electrobase (electrobase.lv): a Drupal shop with TME-style titles.

robots.txt forbids the site search ('/search/', '?search=') and the '?sort=' / '?items_per_page=' listings,
so there is no text search here: the catalog is read page by page from the category listings
('?page=N', counted from 0) and the manufacturer part number is read from the product page when needed.
Listing prices already include VAT; the dataLayer price in the same page is without VAT and is not used.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..models import Offer
from ..normalize import clean, parse_price, parse_stock
from .base import Category, Listing, Shop, Unsupported

BASE = 'https://electrobase.lv'


def _datalayer_items(soup: BeautifulSoup) -> dict[str, dict]:
    """{EB code: item} from the dataLayer.push({... "event": "view_item_list" ...}) script."""
    for script in soup.find_all('script'):
        text = script.string or ''
        at = text.find('"view_item_list"')
        if at < 0:
            continue
        start = text.rfind('dataLayer.push(', 0, at)
        brace = text.find('{', start if start >= 0 else 0)
        try:
            data, _ = json.JSONDecoder().raw_decode(text[brace:])
        except ValueError:
            continue
        return {item['item_id']: item for item in data.get('ecommerce', {}).get('items', []) if 'item_id' in item}
    return {}


def _stock(element) -> tuple[int | None, bool, str, str | None, str | None]:
    if element is None:
        return None, False, 'unknown', None, None
    first = next((s.strip() for s in element.find_all(string=True, recursive=False) if s.strip()), '')
    qty, atleast, state = parse_stock(first)
    delivery = None
    for span in element.select('span.stock-date-text'):
        text = clean(span.get_text(' '))
        if text.lower().startswith('piegāde'):
            delivery = text
    return qty, atleast, state, first or None, delivery


def parse_listing(html: str, page_url: str = BASE) -> Listing:
    soup = BeautifulSoup(html, 'html.parser')
    layer = _datalayer_items(soup)
    out = Listing()
    for box in soup.select('div.product_box'):
        link = box.select_one('h2.product-name a[href]')
        code_el = box.select_one('div.product-code')
        code = re.search(r'EB\d+', code_el.get_text()) if code_el else None
        if link is None or code is None:
            continue
        price_el = box.select_one('div.product-price')
        price = parse_price(price_el.get_text(' ')) if price_el else None
        qty, atleast, state, text, delivery = _stock(box.select_one('div.stock-level'))
        item = layer.get(code.group(0), {})
        out.offers.append(Offer(
            shop='electrobase', shop_id=code.group(0), url=urljoin(BASE, link['href']), title=clean(link.get_text(' ')),
            brand=item.get('item_brand') or None, category=item.get('item_category2') or None, sale_price=price,
            stock_qty=qty, stock_atleast=atleast, stock_text=text, stock_state=state, note=delivery))
    out.has_next = soup.select_one('li.pager-next a') is not None
    return out


def _jsonld_product(soup: BeautifulSoup) -> dict:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or '')
        except ValueError:
            continue
        for node in (data.get('@graph') or [data]) if isinstance(data, dict) else data:
            if isinstance(node, dict) and node.get('@type') == 'Product':
                return node
    return {}


def _field(soup: BeautifulSoup, name: str) -> str | None:
    element = soup.select_one(f'div.field-name-{name} div.field-item')
    return clean(element.get_text(' ')) if element else None


def parse_product(html: str, url: str) -> Offer:
    soup = BeautifulSoup(html, 'html.parser')
    ld = _jsonld_product(soup)
    heading = soup.select_one('h1.product-name') or soup.select_one('h1')
    title = clean(heading.get_text(' ')) if heading else clean(ld.get('name'))
    code_el = soup.select_one('h4.product-code')
    code = re.search(r'EB\d+', code_el.get_text()) if code_el else None
    code_text = code.group(0) if code else ld.get('sku') or url
    price_el = soup.select_one('div.product-price-box .product-price')
    price = parse_price(price_el.get_text(' ')) if price_el else None
    if price is None:
        price = parse_price(((ld.get('offers') or {}).get('price')))
    qty, atleast, state, text, delivery = _stock(soup.select_one('div.product-detail-info div.stock-level'))
    props: dict[str, str] = {}
    for panel in soup.select('div.panel'):
        heading_el = panel.select_one('.panel-title')
        if heading_el and 'propert' in heading_el.get_text().lower():
            for row in panel.select('table tr'):
                cells = row.find_all('td')
                if len(cells) >= 2:
                    label, value = clean(cells[0].get_text(' ')), clean(cells[1].get_text(' '))
                    if label and value:
                        props[label] = f'{props[label]}, {value}' if label in props else value
    brand = _field(soup, 'field-producer') or ((ld.get('brand') or {}).get('name'))
    crumbs = [clean(a.get_text(' ')) for a in soup.select('ol.breadcrumb li a, ul.breadcrumb li a')]
    return Offer(
        shop='electrobase', shop_id=code_text, url=url, title=title,
        mpn=_field(soup, 'field-producer-product-code') or ld.get('mpn') or None, brand=brand,
        category=' / '.join(c for c in crumbs[1:] if c) or ld.get('category'), sale_price=price,
        stock_qty=qty, stock_atleast=atleast, stock_text=text, stock_state=state, note=delivery, props=props, detail=True)


def parse_menu(html: str) -> list[Category]:
    """Every '/katalogs/...' link of the home page menu with its item count: the whole category tree."""
    soup = BeautifulSoup(html, 'html.parser')
    out, seen = [], set()
    for link in soup.select('a[href^="/katalogs/"]'):
        path = link['href'].split('?')[0].split('#')[0].rstrip('/')
        match = re.match(r'(.*?)\s*\((\d+)\)\s*$', clean(link.get_text(' ')))
        if not match or path in seen or path.count('/') < 2:
            continue
        seen.add(path)
        parent = path.rsplit('/', 1)[0]
        out.append(Category(shop='electrobase', url=BASE + path, title=match.group(1), count=int(match.group(2)),
                            parent=BASE + parent if parent.count('/') >= 2 else None))
    return out


class Electrobase(Shop):
    key = 'electrobase'
    name = 'Electrobase'
    host = 'electrobase.lv'
    base = BASE
    min_interval = 2.5
    can_search = False
    why_no_search = ('Electrobase: robots.txt запрещает поиск по сайту, поэтому детали берутся из каталога по разделам '
                     'и со страниц товаров')

    def listing(self, category: Category, page: int = 1) -> Listing:
        reply = self.client.get(category.url, params={'page': page - 1} if page > 1 else None)
        result = parse_listing(reply.text, reply.url)
        for offer in result.offers:
            offer.category = offer.category or category.title
        return result

    def product(self, url: str) -> Offer:
        if urlsplit(url).netloc == 'www.electrobase.lv':
            url = url.replace('://www.', '://', 1)
        reply = self.client.get(url)
        return parse_product(reply.text, url)

    def categories(self) -> list[Category]:
        return parse_menu(self.client.get(BASE + '/').text)

    def search(self, query: str, page: int = 1) -> Listing:
        raise Unsupported(self.why_no_search)
