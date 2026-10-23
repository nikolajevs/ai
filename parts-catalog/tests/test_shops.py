import json

import pytest

from partscat import params
from partscat.http import FetchError
from partscat.shops import electrobase, lemona, salvats, semikom
from partscat.shops.base import Category, Unsupported

from conftest import FakeClient, fixture_text


# ---- Salvats ---------------------------------------------------------------------------------------------

def test_salvats_listing_reads_artikuls_price_and_stock():
    page = salvats.parse_listing(fixture_text('salvats', 'listing_100v_tht.html'), 'https://www.salvats.lv/lv/100v-n-fet-tht')
    assert len(page.offers) == 5 and page.has_next and not page.subcategories
    by_mpn = {o.mpn: o for o in page.offers}
    tk = by_mpn['TK22E10N1']                       # the title says '22E10N', the Artikuls is the real part number
    assert tk.title.startswith('22E10N') and tk.shop_id == '19831' and tk.sale_price == 1.38 and tk.stock_qty == 22
    assert tk.url.startswith('https://www.salvats.lv/lv/100v-n-fet-tht/') and tk.stock_state == 'in'
    assert tk.pack_qty == 1 and not tk.detail


def test_salvats_search_result_has_breadcrumb_category():
    page = salvats.parse_listing(fixture_text('salvats', 'search_fdb5800.html'),
                                 'https://www.salvats.lv/lv/search-results?product=FDB5800')
    assert [o.mpn for o in page.offers] == ['FDB5800'] and not page.has_next
    assert page.offers[0].category.endswith('N kanalu lauku tranzistori SMD')
    assert page.offers[0].sale_price == 1.98 and page.offers[0].stock_qty == 4


def test_salvats_category_with_tiles_gives_subcategories():
    page = salvats.parse_listing(fixture_text('salvats', 'category_tiles.html'), 'https://www.salvats.lv/lv/n-kanalu-lauku-tranzistori')
    assert page.offers == [] and [c.title for c in page.subcategories] == [
        'N kanalu lauku tranzistori SMD', 'N kanalu lauku tranzistori THT', 'N/N kanalu lauku tranzistori']


def test_salvats_product_page_properties_feed_the_parameters():
    offer = salvats.parse_product(fixture_text('salvats', 'product_fdb5800.html'), 'https://www.salvats.lv/lv/x/fdb5800')
    assert offer.detail and offer.mpn == 'FDB5800' and offer.brand == 'ON SEMICONDUCTOR (FAIRCHILD)'
    assert offer.props['Drain-source voltage'] == '60V' and offer.props['Gate charge'] == '135nC'
    parsed = params.extract(offer.title, offer.props, offer.category)
    assert parsed['rds_mohm'] == pytest.approx(6.0) and parsed['rds_alt_mohm'] == pytest.approx(12.6) and parsed['qg_nc'] == pytest.approx(135)


def test_salvats_menu_tree():
    tree = salvats.parse_menu(fixture_text('salvats', 'menu.html'))
    by_title = {c.title: c for c in tree}
    assert by_title['N kanālu lauku tranzistori'].parent == 'https://www.salvats.lv/lv/tranzistori'
    assert by_title['Tranzistori'].parent is None


def test_salvats_search_builds_the_documented_request():
    html = fixture_text('salvats', 'search_fdb5800.html')
    client = FakeClient({'https://www.salvats.lv/lv/search-results': html})
    page = salvats.Salvats(client).search('FDB5800')
    assert client.calls[0][2] == {'product': 'FDB5800', 'page': 1} and page.offers[0].mpn == 'FDB5800'


def test_salvats_listing_fills_the_category_name_when_the_card_has_none():
    html = fixture_text('salvats', 'listing_100v_tht.html')
    client = FakeClient({'https://www.salvats.lv/lv/100v-n-fet-tht': html})
    category = Category('salvats', 'https://www.salvats.lv/lv/100v-n-fet-tht', '100V, N-FET, THT')
    page = salvats.Salvats(client).listing(category, 1)
    assert {o.category for o in page.offers} == {'100V, N-FET, THT'}


# ---- Electrobase -----------------------------------------------------------------------------------------

def test_electrobase_listing_price_includes_vat_and_brand_comes_from_datalayer():
    page = electrobase.parse_listing(fixture_text('electrobase', 'listing_nfet.html'))
    assert len(page.offers) == 5 and page.has_next
    first = page.offers[0]
    assert first.shop_id == 'EB1837250589' and first.sale_price == pytest.approx(0.0649)
    assert first.brand == 'MICRO COMMERCIAL COMPONENTS' and first.mpn is None
    assert first.stock_qty == 1000 and first.stock_atleast and first.stock_state == 'in'
    assert first.url == 'https://electrobase.lv/katalogs/tranzistori-ar-n-veida-kanalu-smd/transistor-n-mosfet-unipolar-60v-340ma-idm-2a-108w-sot23'
    assert params.extract(first.title)['vds'] == 60


def test_electrobase_product_page_gives_mpn_properties_and_stock():
    offer = electrobase.parse_product(fixture_text('electrobase', 'product_lm3429.html'),
                                      'https://electrobase.lv/katalogs/led-draiveri/x')
    assert offer.mpn == 'LM3429MH/NOPB' and offer.brand == 'TEXAS INSTRUMENTS' and offer.shop_id == 'EB266320036'
    assert offer.sale_price == pytest.approx(4.86) and offer.stock_qty == 724 and not offer.stock_atleast
    assert offer.props['Case'] == 'HTSSOP14' and offer.props['Topology'] == 'boost, buck-boost'
    assert offer.note.startswith('Piegāde līdz') and offer.detail


def test_electrobase_menu_has_counts_and_parents():
    tree = electrobase.parse_menu(fixture_text('electrobase', 'menu.html'))
    smd = next(c for c in tree if c.title == 'Tranzistori ar N veida kanālu SMD')
    parent = next(c for c in tree if c.title == 'Tranzistori ar N veida kanālu')
    assert smd.count == 1432 and smd.parent == parent.url and parent.count == 2957


def test_electrobase_listing_pages_count_from_zero():
    html = fixture_text('electrobase', 'listing_nfet.html')
    category = Category('electrobase', 'https://electrobase.lv/katalogs/x', 'N channel')
    client = FakeClient({'https://electrobase.lv/katalogs/x': html})
    shop = electrobase.Electrobase(client)
    shop.listing(category, 1)
    shop.listing(category, 3)
    assert [c[2] for c in client.calls] == [None, {'page': 2}]


def test_electrobase_search_is_refused_with_the_reason():
    with pytest.raises(Unsupported) as caught:
        electrobase.Electrobase(FakeClient()).search('FDB5800')
    assert 'robots.txt' in str(caught.value)


# ---- Semikom ---------------------------------------------------------------------------------------------

def test_semikom_listing():
    page = semikom.parse_listing(fixture_text('semikom', 'search_n_mosfet_60v.html'))
    assert len(page.offers) == 4 and not page.has_next
    first = page.offers[0]
    assert first.shop_id == '387067' and first.sale_price == 4.5 and first.stock_qty == 354
    assert first.url == 'https://www.semikom.lv/transistor-n-mosfet-unipolar-60v-120a-306w-d2pak-sot404.387067.p'
    assert first.note == 'Saņemsi: 29.10.2026' and first.mpn is None


def test_semikom_product_page():
    offer = semikom.parse_product(fixture_text('semikom', 'product_fdb5800.html'), 'https://www.semikom.lv/x.2082248.p')
    assert offer.mpn == 'FDB5800' and offer.brand == 'ONSEMI' and offer.sale_price == pytest.approx(4.74)
    assert offer.stock_qty == 285 and offer.min_qty == 1 and offer.shop_id == '2082248'
    assert offer.category.endswith('Tranzistori ar N veida kanālu SMD') and offer.props['Gate charge'] == '135nC'


def test_semikom_search_url_is_the_encoded_query():
    client = FakeClient({'https://www.semikom.lv/n-mosfet%2060v%20d2pak.gs': fixture_text('semikom', 'search_n_mosfet_60v.html')})
    page = semikom.Semikom(client).search('n-mosfet 60v d2pak')
    assert len(page.offers) == 4


def test_semikom_waits_longer_than_the_ban_threshold():
    client = FakeClient()
    semikom.Semikom(client)
    assert client.min_interval['www.semikom.lv'] >= 4.5


# ---- Lemona ----------------------------------------------------------------------------------------------

def lemona_data():
    return json.loads(fixture_text('lemona', 'product_30362.json'))


def test_lemona_product_from_graphql():
    offer = lemona.parse_product(lemona_data())
    assert offer.shop_id == '30362' and offer.sale_price == 0.83 and offer.tiers == [(5, 0.75)]
    assert offer.url == 'https://www.lemona.lv/sprieguma-stabilizators-l7815cv-to220.html'
    assert offer.stock_qty == 75 and offer.stock_state == 'in' and offer.brand == 'STMICROELECTRONICS'
    assert offer.mpn == 'L7815CV' and offer.shop_sku == '7815' and offer.props['Korpuss'] == 'TO220'


def test_lemona_out_of_stock_and_supplier_only():
    data = lemona_data()
    item = data['data']['products']['items'][0]
    item.update(salable_qty=0, supplier_qty=40, stock_status='IN_STOCK', delivery_date='2026-11-02')
    offer = lemona.parse_product(data)
    assert offer.stock_state == 'order' and offer.stock_qty == 40 and 'Поставка: 2026-11-02' in offer.note
    item.update(supplier_qty=0, stock_status='OUT_OF_STOCK')
    assert lemona.parse_product(data).stock_state == 'out'


def test_lemona_missing_product_is_a_clear_error():
    with pytest.raises(FetchError) as caught:
        lemona.parse_product({'data': {'products': {'items': []}}}, 'https://www.lemona.lv/x.html')
    assert caught.value.status == 404


def test_lemona_resolves_the_page_address_then_reads_the_product():
    def answer(payload):
        if 'urlResolver' in payload['query']:
            assert payload['variables'] == {'url': '/sprieguma-stabilizators-l7815cv-to220.html'}
            return {'data': {'urlResolver': {'id': 30362, 'type': 'PRODUCT', 'relative_url': 'x.html'}}}
        assert payload['variables'] == {'id': '30362'}
        return lemona_data()
    client = FakeClient({lemona.GRAPHQL: answer})
    offer = lemona.Lemona(client).product('https://www.lemona.lv/sprieguma-stabilizators-l7815cv-to220.html')
    assert offer.shop_id == '30362'
    assert [c[0] for c in client.calls] == ['POST', 'POST']


def test_lemona_accepts_an_id_instead_of_an_address():
    client = FakeClient({lemona.GRAPHQL: lambda payload: lemona_data()})
    assert lemona.Lemona(client).product('lemona:30362').shop_id == '30362'
    assert len(client.calls) == 1


def test_lemona_category_page_is_not_a_product():
    client = FakeClient({lemona.GRAPHQL: {'data': {'urlResolver': {'id': 3295, 'type': 'CATEGORY', 'relative_url': 'x'}}}})
    with pytest.raises(FetchError):
        lemona.Lemona(client).product('https://www.lemona.lv/pusvaditaji.html')


def test_lemona_search_is_refused_with_the_reason():
    with pytest.raises(Unsupported) as caught:
        lemona.Lemona(FakeClient()).search('L7815CV')
    assert 'LupaSearch' in str(caught.value)


@pytest.mark.parametrize('name,expected', [
    ('Sprieguma stabilizators L7815CV TO220', 'L7815CV'),
    ('Tranzistors IRF540N TO220 N-FET 100V 33A', 'IRF540N'),
    ('Rezistors 10K 1% 0805', None),
    ('LED 5mm sarkana', None),
])
def test_lemona_mpn_guess(name, expected):
    assert lemona.guess_mpn(name) == expected
