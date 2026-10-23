"""Semikom (www.semikom.lv): TME-style titles, prices include 21 % VAT.

The first request of a visit is answered with a tiny script that sets cookies and reloads the page; the HTTP
client repeats the request at once and gets the real page, so no browser is needed. The shop bans an IP that
loads pages faster than about one in four seconds (HTTP 423, 'Banned'), hence the long pause.
Search is /<text>.gs, product pages are /<slug>.<id>.p, groups are /<slug>.<id>.g; '?p=N' pages a list.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..models import Offer
from ..normalize import clean, parse_pack, parse_price, parse_stock
from .base import Category, Listing, Shop

BASE = 'https://www.semikom.lv'
PER_PAGE = 30


def parse_listing(html: str, page_url: str = BASE) -> Listing:
    soup = BeautifulSoup(html, 'html.parser')
    out = Listing()
    for card in soup.select('div.-oProduct'):
        link = card.select_one('a.-oTitle[href]')
        product_id = card.get('-id') or ''
        if link is None or not product_id:
            continue
        price_el = card.select_one('ins.-oPrice')
        price = parse_price(price_el.get('-price') or price_el.get_text(' ')) if price_el else None
        amount = card.select_one('div.-amount b')
        qty, atleast, state = parse_stock(amount.get_text() if amount else None)
        delivery = card.select_one('div.product_delivery_date')
        title = clean(link.get_text(' '))
        out.offers.append(Offer(
            shop='semikom', shop_id=product_id, url=urljoin(BASE, link['href']), title=title, sale_price=price,
            pack_qty=parse_pack(title), stock_qty=qty, stock_atleast=atleast, stock_state=state,
            stock_text=clean(amount.get_text()) if amount else None, note=clean(delivery.get_text(' ')) if delivery else None))
    out.has_next = len(out.offers) >= PER_PAGE
    return out


def _table_fields(soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in soup.select('div._params table tr'):
        head, cell = row.find('th'), row.find('td')
        if head and cell:
            fields[clean(head.get_text()).rstrip(':')] = clean(cell.get_text(' '))
    return fields


def parse_product(html: str, url: str) -> Offer:
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('h1')
    title = clean(heading.get_text(' ')) if heading else ''
    fields = _table_fields(soup)
    price_el = soup.select_one('#_price_single')
    whole, cents = (price_el.select_one('u.-price'), price_el.select_one('u.-cent')) if price_el else (None, None)
    price = None
    if whole is not None:
        price = parse_price(f"{whole.get_text().strip().rstrip('.')}.{cents.get_text().strip() if cents else '00'}")
    qty, atleast, state = parse_stock(fields.get('Pieejamība piegādātāja noliktavā'))
    props: dict[str, str] = {}
    for row in soup.select('table.attributes tr'):
        cells = row.find_all('td')
        if len(cells) >= 2:
            label, value = clean(cells[0].get_text()).rstrip(':'), clean(cells[1].get_text(' '))
            if label and value:
                props[label] = f'{props[label]}, {value}' if label in props else value
    group_links = soup.select('div._params a[href$=".g"]')
    category = ' / '.join(clean(a.get_text(' ')) for a in group_links) or None
    moq = fields.get('Minimalālais daudzums') or fields.get('Minimālais pasūtījums') or '1'
    code = fields.get('Artikuls') or fields.get('Kods')
    return Offer(
        shop='semikom', shop_id=fields.get('ID') or url, url=url, title=title, mpn=code, shop_sku=fields.get('Kods'),
        brand=fields.get('Ražotājs') or props.get('Manufacturer'), category=category, sale_price=price,
        pack_qty=parse_pack(title), stock_qty=qty, stock_atleast=atleast, stock_state=state,
        stock_text=fields.get('Pieejamība piegādātāja noliktavā'), min_qty=int(moq) if moq.isdigit() else 1,
        note=fields.get('Piegādes laiks līdz ofisam'), props=props, detail=True)


def parse_groups(html: str) -> list[Category]:
    """Group links of a page, with the chain of the product breadcrumb as parents when the page has one."""
    soup = BeautifulSoup(html, 'html.parser')
    out, seen = [], set()
    previous = None
    for link in soup.select('a[href$=".g"]'):
        url = urljoin(BASE, link['href'])
        title = clean(link.get_text(' '))
        if url in seen or not title:
            continue
        seen.add(url)
        out.append(Category(shop='semikom', url=url, title=title, parent=previous))
        previous = url
    return out


class Semikom(Shop):
    key = 'semikom'
    name = 'Semikom'
    host = 'www.semikom.lv'
    base = BASE
    min_interval = 4.6

    def search(self, query: str, page: int = 1) -> Listing:
        reply = self.client.get(f'{BASE}/{quote(clean(query), safe="")}.gs', params={'p': page} if page > 1 else None)
        return parse_listing(reply.text, reply.url)

    def listing(self, category: Category, page: int = 1) -> Listing:
        reply = self.client.get(category.url, params={'p': page} if page > 1 else None)
        result = parse_listing(reply.text, reply.url)
        for offer in result.offers:
            offer.category = offer.category or category.title
        return result

    def product(self, url: str) -> Offer:
        reply = self.client.get(url)
        return parse_product(reply.text, url)

    def categories(self) -> list[Category]:
        return parse_groups(self.client.get(BASE + '/').text)
