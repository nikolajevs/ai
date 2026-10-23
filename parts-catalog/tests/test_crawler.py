import csv
import threading

import pytest

from conftest import FakeClient
from partscat.crawler import Crawler
from partscat.db import Database
from partscat.http import FetchError
from partscat.models import Offer
from partscat.shops.base import Category, Listing, Shop, Unsupported


def offer(shop, shop_id, title='Transistor: N-MOSFET; unipolar; 60V; 80A; D2PAK', price=1.0, mpn=None, **kw):
    return Offer(shop=shop, shop_id=shop_id, url=f'https://{shop}.example/p/{shop_id}', title=title, mpn=mpn, sale_price=price,
                 stock_qty=5, stock_state='in', **kw)


class ScriptedShop(Shop):
    """A shop whose pages are Python data; a FetchError in `errors[url or (url, page)]` is raised instead of the page."""

    def __init__(self, client, key='fake', pages=None, categories=None, products=None, errors=None, can_search=True):
        self.key, self.name, self.host = key, key.title(), f'{key}.example'
        self.can_search = can_search
        self.why_no_search = f'{key}: поиск недоступен'
        super().__init__(client)
        self.pages = pages or {}
        self._categories = categories or []
        self.products = products or {}
        self.errors = errors or {}
        self.calls = []

    def _maybe_fail(self, key):
        if key in self.errors:
            raise self.errors[key]

    def search(self, query, page=1):
        self.calls.append(('search', query, page))
        self._maybe_fail(('search', query))
        if not self.can_search:
            raise Unsupported(self.why_no_search)
        return self.pages[('search', query, page)]

    def listing(self, category, page=1):
        self.calls.append(('listing', category.url, page))
        self._maybe_fail((category.url, page))
        return self.pages[(category.url, page)]

    def product(self, url):
        self.calls.append(('product', url))
        self._maybe_fail(url)
        return self.products[url]

    def categories(self):
        self.calls.append(('categories',))
        self._maybe_fail('categories')
        return self._categories


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / 'c.db')


def crawler_for(db, *shops, **kw):
    client = FakeClient()
    for shop in shops:
        shop.client = client
    return Crawler(db, client, {s.key: s for s in shops}, **kw), client


def test_sweep_follows_pages_and_tiles_and_counts(db):
    client = FakeClient()
    top = Category('fake', 'https://fake.example/c/tiles', 'Tranzistori')
    leaf = Category('fake', 'https://fake.example/c/leaf', 'N kanalu')
    shop = ScriptedShop(client, categories=[top], pages={
        (top.url, 1): Listing(subcategories=[leaf]),
        (leaf.url, 1): Listing(offers=[offer('fake', '1'), offer('fake', '2')], has_next=True),
        (leaf.url, 2): Listing(offers=[offer('fake', '3')], has_next=False),
    })
    crawler = Crawler(db, client, {'fake': shop})
    result = crawler.run({'kind': 'sweep', 'shop': 'fake', 'match': 'tranz'})
    assert result['state'] == 'done'
    assert result['counts']['new'] == 3 and result['counts']['errors'] == 0 and result['counts']['pages'] == 4
    assert result['done'] == result['total'] == 2                                       # the tile page and the leaf
    assert db.stats()['total'] == 3
    assert db.recent_runs(1)[0]['status'] == 'done'


def test_second_sweep_reports_unchanged_and_changed(db):
    client = FakeClient()
    cat = Category('fake', 'https://fake.example/c/leaf', 'N')
    page = {(cat.url, 1): Listing(offers=[offer('fake', '1', price=1.0), offer('fake', '2', price=2.0)])}
    shop = ScriptedShop(client, categories=[cat], pages=page)
    crawler = Crawler(db, client, {'fake': shop})
    crawler.run({'kind': 'sweep', 'shop': 'fake'})
    page[(cat.url, 1)] = Listing(offers=[offer('fake', '1', price=1.0), offer('fake', '2', price=2.5)])
    result = crawler.run({'kind': 'sweep', 'shop': 'fake'})
    assert (result['counts']['new'], result['counts']['changed'], result['counts']['same']) == (0, 1, 1)


def test_sweep_skips_parent_categories_when_leaves_exist(db):
    client = FakeClient()
    parent = Category('fake', 'https://fake.example/c/p', 'Parent')
    child = Category('fake', 'https://fake.example/c/p/child', 'Child', parent=parent.url)
    shop = ScriptedShop(client, categories=[parent, child], pages={(child.url, 1): Listing(offers=[offer('fake', '1')])})
    Crawler(db, client, {'fake': shop}).run({'kind': 'sweep', 'shop': 'fake'})
    assert [c for c in shop.calls if c[0] == 'listing'] == [('listing', child.url, 1)]


def test_sweep_stops_at_max_pages(db):
    client = FakeClient()
    cat = Category('fake', 'https://fake.example/c/leaf', 'N')
    pages = {(cat.url, n): Listing(offers=[offer('fake', str(n))], has_next=True) for n in range(1, 10)}
    shop = ScriptedShop(client, categories=[cat], pages=pages)
    Crawler(db, client, {'fake': shop}).run({'kind': 'sweep', 'shop': 'fake', 'max_pages': 3})
    assert db.stats()['total'] == 3


def test_ban_leaves_the_shop_alone_but_other_shops_continue(db):
    client = FakeClient()
    ban = FetchError('banned', 'Semikom: магазин ограничил частоту запросов', 'https://a.example/p/1', 423)
    a = ScriptedShop(client, key='a', products={}, errors={'https://a.example/p/1': ban})
    b = ScriptedShop(client, key='b', products={'https://b.example/p/1': offer('b', '1')})
    crawler = Crawler(db, client, {'a': a, 'b': b})
    result = crawler.run({'kind': 'urls', 'urls': ['https://a.example/p/1', 'https://a.example/p/2', 'https://b.example/p/1']})
    assert result['state'] == 'done'
    assert 'a' in result['skipped'] and 'b' not in result['skipped']
    assert [c for c in a.calls if c[0] == 'product'] == [('product', 'https://a.example/p/1')]       # not hit again after the ban
    assert result['counts']['errors'] == 1 and db.stats()['total'] == 1
    assert result['errors'][0]['kind'] == 'banned' and result['errors'][0]['shop'] == 'a'


def test_network_errors_in_a_row_skip_the_shop(db):
    client = FakeClient()
    err = lambda n: FetchError('network', 'нет соединения', f'https://a.example/p/{n}')
    shop = ScriptedShop(client, key='a', errors={f'https://a.example/p/{n}': err(n) for n in range(1, 8)})
    result = Crawler(db, client, {'a': shop}).run({'kind': 'urls', 'urls': [f'https://a.example/p/{n}' for n in range(1, 8)]})
    assert 'a' in result['skipped'] and result['counts']['errors'] == 4


def test_missing_page_is_an_error_entry_not_a_crash(db):
    client = FakeClient()
    gone = FetchError('http', 'HTTP 404', 'https://a.example/p/1', 404)
    shop = ScriptedShop(client, key='a', errors={'https://a.example/p/1': gone}, products={'https://a.example/p/2': offer('a', '2')})
    result = Crawler(db, client, {'a': shop}).run({'kind': 'urls', 'urls': ['https://a.example/p/1', 'https://a.example/p/2']})
    assert result['counts']['errors'] == 1 and result['counts']['new'] == 1 and not result['skipped']


def test_urls_plan_keeps_pages_on_the_watch_list_and_watch_plan_refreshes_them(db):
    client = FakeClient()
    products = {'https://a.example/p/1': offer('a', '1', price=1.0)}
    shop = ScriptedShop(client, key='a', products=products)
    crawler = Crawler(db, client, {'a': shop})
    crawler.run({'kind': 'urls', 'urls': ['https://a.example/p/1', 'https://elsewhere.example/x']})
    assert [w['url'] for w in db.watch_list()] == ['https://a.example/p/1']
    products['https://a.example/p/1'] = offer('a', '1', price=1.5)
    result = crawler.run({'kind': 'watch'})
    assert result['counts']['changed'] == 1 and db.find('a', '1')['sale_price'] == 1.5


def test_bom_plan_reads_every_line_with_a_page(db, tmp_path):
    folder = tmp_path / 'bom'
    folder.mkdir()
    with open(folder / 'BOM_allocated.csv', 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Shop', 'MPN_or_shop_SKU', 'Fitted_or_accessory', 'Buy_pieces', 'Sale_unit', 'Price_per_sale_unit_EUR_VAT',
                         'Line_EUR_VAT', 'References', 'Accessory_count', 'URL', 'Price_date'])
        writer.writerow(['Salvats', 'A1', '1', '1', 'шт.', '1', '1', 'Q1', '0', 'https://salvats.example/p/1', '2026-10-20'])
        writer.writerow(['Electrobase', 'B1', '1', '1', 'шт.', '2', '2', 'Q2', '0', 'https://electrobase.example/p/2', '2026-10-20'])
        writer.writerow(['не выбран', 'C1', '1', '1', 'шт.', '0', '0', 'J1', '0', '', '2026-10-20'])
    client = FakeClient()
    salvats = ScriptedShop(client, key='salvats', products={'https://salvats.example/p/1': offer('salvats', '1', mpn='A1')})
    electrobase = ScriptedShop(client, key='electrobase', products={'https://electrobase.example/p/2': offer('electrobase', '2', mpn='B1')})
    result = Crawler(db, client, {'salvats': salvats, 'electrobase': electrobase}, bom_dir=folder).run({'kind': 'bom'})
    assert result['state'] == 'done' and result['counts']['new'] == 2 and result['done'] == result['total'] == 2


def test_bom_plan_without_a_bom_fails_visibly(db, tmp_path, monkeypatch):
    monkeypatch.setenv('PARTSCAT_BOM_DIR', str(tmp_path / 'nothing'))
    monkeypatch.setattr('partscat.crawler.find_bom_dir', lambda: None)
    crawler, _ = crawler_for(db)
    result = crawler.run({'kind': 'bom'})
    assert result['state'] == 'failed' and 'BOM_allocated.csv' in result['errors'][0]['message']
    assert db.recent_runs(1)[0]['status'] == 'failed'


def test_search_asks_searchable_shops_and_reads_part_numbers(db):
    client = FakeClient()
    results = Listing(offers=[offer('fake', '1', title='Transistor: N-MOSFET; unipolar; 60V; 80A; D2PAK'), offer('fake', '2')])
    shop = ScriptedShop(client, pages={('search', 'FDB5800', 1): results},
                        products={'https://fake.example/p/1': offer('fake', '1', mpn='FDB5800', detail=True),
                                  'https://fake.example/p/2': offer('fake', '2', mpn='FQB80N06', detail=True)})
    cold = ScriptedShop(client, key='cold', can_search=False)
    result = Crawler(db, client, {'fake': shop, 'cold': cold}).run({'kind': 'search', 'query': 'FDB5800'})
    assert result['state'] == 'done'
    assert db.find('fake', '1')['mpn'] == 'FDB5800' and db.find('fake', '2')['mpn'] == 'FQB80N06'
    assert any('поиск недоступен' in line for line in result['log'])
    assert not [c for c in cold.calls if c[0] == 'search']


def test_search_refreshes_known_offers_of_shops_without_search(db):
    client = FakeClient()
    db.upsert(offer('cold', '9', mpn='FDB5800', price=1.0))
    cold = ScriptedShop(client, key='cold', can_search=False, products={'https://cold.example/p/9': offer('cold', '9', mpn='FDB5800', price=1.2)})
    result = Crawler(db, client, {'cold': cold}).run({'kind': 'search', 'query': 'FDB5800', 'enrich': 0})
    assert db.find('cold', '9')['sale_price'] == 1.2 and result['counts']['changed'] == 1


def test_enrich_reads_only_offers_without_a_part_number(db):
    client = FakeClient()
    db.upsert(offer('fake', '1'))
    db.upsert(offer('fake', '2', mpn='KNOWN'))
    shop = ScriptedShop(client, products={'https://fake.example/p/1': offer('fake', '1', mpn='FDB5800', detail=True)})
    result = Crawler(db, client, {'fake': shop}).run({'kind': 'enrich', 'limit': 10})
    assert [c for c in shop.calls if c[0] == 'product'] == [('product', 'https://fake.example/p/1')]
    assert db.find('fake', '1')['mpn'] == 'FDB5800' and result['counts']['changed'] + result['counts']['same'] == 1


def test_a_stored_address_outside_the_shop_site_is_never_fetched(db):
    client = FakeClient()
    stray = Offer(shop='fake', shop_id='7', url='http://192.168.0.1/admin', title='Transistor: N-MOSFET; 60V', sale_price=1.0,
                  stock_qty=5, stock_state='in')
    db.upsert(stray)                                   # a card link that pointed elsewhere
    db.upsert(offer('fake', '8', mpn='FDB5800', detail=True))
    shop = ScriptedShop(client, products={})
    result = Crawler(db, client, {'fake': shop}).run({'kind': 'enrich', 'limit': 10})
    assert [c for c in shop.calls if c[0] == 'product'] == []
    assert any('адрес не с сайта магазина' in line and '192.168.0.1' in line for line in result['log'])
    db.upsert(Offer(shop='cold', shop_id='9', url='https://elsewhere.example/p/9', title='Transistor: N-MOSFET; 60V', mpn='FDB5800',
                    sale_price=1.0, stock_qty=5, stock_state='in'))
    cold = ScriptedShop(client, key='cold', can_search=False, products={})
    asked = Crawler(db, client, {'cold': cold}).run({'kind': 'search', 'query': 'FDB5800', 'enrich': 0})
    assert asked['state'] == 'done' and [c for c in cold.calls if c[0] == 'product'] == []
    assert any('elsewhere.example' in line for line in asked['log'])


def test_stop_ends_the_run_and_keeps_what_was_stored(db):
    client = FakeClient()
    cat = Category('fake', 'https://fake.example/c/leaf', 'N')
    pages = {(cat.url, n): Listing(offers=[offer('fake', str(n))], has_next=True) for n in range(1, 30)}
    shop = ScriptedShop(client, categories=[cat], pages=pages)
    crawler = Crawler(db, client, {'fake': shop})
    original = shop.listing

    def listing_then_stop(category, page=1):
        result = original(category, page)
        if page == 3:
            crawler.stop()
        return result

    shop.listing = listing_then_stop
    result = crawler.run({'kind': 'sweep', 'shop': 'fake'})
    assert result['state'] == 'stopped' and db.stats()['total'] == 3
    assert db.recent_runs(1)[0]['status'] == 'stopped'


def test_unknown_plan_and_empty_query_fail_visibly(db):
    crawler, _ = crawler_for(db)
    assert crawler.run({'kind': 'nonsense'})['state'] == 'failed'
    assert crawler.run({'kind': 'search', 'query': ' '})['state'] == 'failed'


def test_background_run_and_single_plan_at_a_time(db):
    client = FakeClient()
    gate = threading.Event()
    shop = ScriptedShop(client, key='a', products={})
    original = shop.product

    def slow(url):
        gate.wait(5)
        return offer('a', '1')

    shop.product = slow
    crawler = Crawler(db, client, {'a': shop})
    assert crawler.start({'kind': 'urls', 'urls': ['https://a.example/p/1']}) is True
    assert crawler.running and crawler.snapshot()['state'] == 'running'
    assert crawler.start({'kind': 'watch'}) is False
    gate.set()
    crawler.wait(5)
    assert not crawler.running and crawler.snapshot()['state'] == 'done'
    assert crawler.start({'kind': 'watch'}) is True
    crawler.wait(5)


def test_fresh_runs_bypass_the_page_cache_and_restore_it(db):
    client = FakeClient()
    seen = []
    shop = ScriptedShop(client, key='a')

    def product(url):
        seen.append(client.ttl)
        return offer('a', '1')

    shop.product = product
    Crawler(db, client, {'a': shop}).run({'kind': 'urls', 'urls': ['https://a.example/p/1']})
    assert seen == [0.0] and client.ttl == 72000.0
