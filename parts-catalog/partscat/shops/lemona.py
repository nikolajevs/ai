"""Lemona (www.lemona.lv): a Magento PWA read through its own GraphQL endpoint.

Verified from the cloud: urlResolver gives the product id of a page address, and products(filter: {id: {eq: ...}})
returns name, brand, stock, delivery date, quantity price tiers and the price with VAT. Text search, category
and url_key filters of the same endpoint fail (the site search is LupaSearch, a third-party service that was not
reachable from the test environment), so a Lemona offer is added by its page address: from the BOM, from the
watch list, or pasted into the crawler page.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..http import FetchError
from ..models import Offer
from ..normalize import clean
from ..params import canon_package
from .base import Shop, Unsupported

BASE = 'https://www.lemona.lv'
GRAPHQL = BASE + '/graphql'

RESOLVE_QUERY = 'query resolve($url: String!) { urlResolver(url: $url) { id type relative_url } }'
PRODUCT_QUERY = '''query product($id: String) {
  products(filter: {id: {eq: $id}}) {
    items {
      id sku lemona_sku name url_key url_suffix
      brand { title }
      visible_on_front { code value label }
      salable_qty supplier_qty stock_status delivery_date min_sale_qty unit
      packaging { package quantity }
      price_tiers { final_price { value } quantity }
      price_range { minimum_price { final_price { value } } }
      categories { id name }
    }
  }
}'''

_UNIT_TOKEN = re.compile(r'^[±+\-]?\d+(?:[.,]\d+)?[pnuµmkKMG]?[VAWΩFHR%]?$')


def guess_mpn(name: str | None) -> str | None:
    """Lemona names are '<Latvian type> <MPN> <package>': the first token with letters and digits that is not
    a package or a plain value ('Sprieguma stabilizators L7815CV TO220' -> 'L7815CV')."""
    for token in (name or '').replace(',', ' ').split():
        token = token.strip('()')
        if len(token) < 4 or not re.search(r'[A-Za-z]', token) or not re.search(r'\d', token):
            continue
        if _UNIT_TOKEN.match(token) or canon_package(token) or re.fullmatch(r'\d+(?:[.,]\d+)?[xX×]\d+.*', token):
            continue
        return token
    return None


def parse_product(data: dict, url: str | None = None) -> Offer:
    items = (((data or {}).get('data') or {}).get('products') or {}).get('items') or []
    if not items:
        raise FetchError('http', 'Lemona: товар не найден (возможно, снят с продажи)', url or '', 404)
    item = items[0]
    own, supplier = int(item.get('salable_qty') or 0), int(item.get('supplier_qty') or 0)
    in_stock = (item.get('stock_status') or '').upper() == 'IN_STOCK'
    state = 'in' if own > 0 else 'order' if supplier > 0 else 'in' if in_stock else 'out'
    page = f"{BASE}/{item.get('url_key')}{item.get('url_suffix') or '.html'}"
    price = (((item.get('price_range') or {}).get('minimum_price') or {}).get('final_price') or {}).get('value')
    tiers = sorted((int(t['quantity']), float(t['final_price']['value'])) for t in item.get('price_tiers') or []
                   if t.get('quantity') and (t.get('final_price') or {}).get('value') is not None)
    props = {clean(a['label']): clean(a['value']) for a in item.get('visible_on_front') or []
             if a.get('label') and a.get('value') and a.get('code') != 'sku'}
    mpn = guess_mpn(item.get('name'))
    if mpn:
        props['MPN из названия'] = mpn
    packaging = item.get('packaging') or []
    note = ' '.join(x for x in (
        f"Поставка: {item['delivery_date']}" if item.get('delivery_date') else '',
        f"упаковка: {packaging[0].get('package')} × {packaging[0].get('quantity')}" if packaging else '') if x) or None
    return Offer(
        shop='lemona', shop_id=str(item['id']), url=page, title=clean(item.get('name')), mpn=mpn,
        shop_sku=item.get('lemona_sku') or item.get('sku'), brand=(item.get('brand') or {}).get('title'),
        category=' / '.join(c['name'] for c in item.get('categories') or [] if c.get('name')) or None,
        sale_price=float(price) if price is not None else None, tiers=tiers, stock_qty=own + supplier,
        stock_text=f'склад {own}, поставщик {supplier}', stock_state=state, min_qty=int(item.get('min_sale_qty') or 1),
        note=note, props=props, detail=True)


class Lemona(Shop):
    key = 'lemona'
    name = 'Lemona'
    host = 'www.lemona.lv'
    base = BASE
    min_interval = 1.5
    can_search = False
    why_no_search = ('Lemona: поиск по сайту идёт через сторонний сервис LupaSearch, который не удалось проверить; '
                     'товары добавляются по адресу страницы (из BOM, списка наблюдения или со страницы «Сбор»)')

    def _graphql(self, query: str, variables: dict, ttl_hours: float | None = None) -> dict:
        reply = self.client.post_json(GRAPHQL, {'query': query, 'variables': variables}, headers={'Store': 'lv_lv'},
                                      ttl_hours=ttl_hours)
        data = reply.json()
        if data.get('errors') and not data.get('data'):
            raise FetchError('http', f"Lemona: {data['errors'][0].get('message', 'ошибка GraphQL')}", GRAPHQL)
        return data

    def product_id(self, url: str) -> int:
        path = urlsplit(url).path or '/'
        found = ((self._graphql(RESOLVE_QUERY, {'url': path}, ttl_hours=24 * 30).get('data') or {}).get('urlResolver')) or {}
        if found.get('type') != 'PRODUCT' or not found.get('id'):
            raise FetchError('http', f'Lemona: {path} не страница товара', url, 404)
        return int(found['id'])

    def lookup(self, product_id: int, url: str | None = None) -> Offer:
        return parse_product(self._graphql(PRODUCT_QUERY, {'id': str(product_id)}), url)

    def product(self, url: str) -> Offer:
        by_id = re.fullmatch(r'lemona:(\d+)', url.strip())       # 'lemona:30362' adds a product without its address
        return self.lookup(int(by_id.group(1)) if by_id else self.product_id(url), url)

    def search(self, query: str, page: int = 1):
        raise Unsupported(self.why_no_search)
