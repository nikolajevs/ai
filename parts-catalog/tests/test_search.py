import pytest

from partscat import search as srch
from partscat.db import Database
from partscat.models import Offer
from partscat.pricing import cost_for, stock_pieces, availability


def offer(shop, shop_id, title, mpn=None, price=1.0, stock=5, state='in', sku=None, brand=None, **kw):
    return Offer(shop=shop, shop_id=shop_id, url=f'https://{shop}.example/{shop_id}', title=title, mpn=mpn, shop_sku=sku,
                 brand=brand, sale_price=price, stock_qty=stock, stock_state=state, **kw)


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / 'c.db')
    rows = [
        offer('salvats', '1', 'FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', 'FDB5800', 1.98, 4,
              sku='FDB5800', category='N kanalu lauku tranzistori SMD'),
        offer('semikom', '2', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK', 'FDB5800', 4.74, 285, brand='ONSEMI'),
        offer('semikom', '3', 'Transistor: N-MOSFET; unipolar; 60V; 120A; 306W; D2PAK,SOT404', None, 4.50, 354),
        offer('electrobase', 'EB1', 'Transistor: N-MOSFET | unipolar | 100V | 22A | 72W | TO220-3', None, 1.9, 1000),
        offer('salvats', '4', '22E10N Tranzistors N-FET 100V, ±20V, 22A, 72W, 0R0115, TO-220', 'TK22E10N1', 1.38, 22, sku='TK22E10N1'),
        offer('salvats', '5', 'BC847B-DIO SMD Tranzistors, NPN, 45V, 0.1A, 300MHz, SOT23', 'BC847B-DIO', 0.06, 100, sku='BC847B-DIO'),
        offer('salvats', '6', 'SS510-YAN, SMD, Diode Schottky, 100V, 5A, SMC', 'SS510-YAN', 0.35, 30),
        offer('salvats', '7', '100nF, 50V, 0805, (10gab,), MLCC, X7R, ±5%, SMD Kondensators, 0805', 'CL21B104KBCNNNC', 0.51, 20,
              pack_qty=10, sku='CL21B104KBCNNNC'),
        offer('semikom', '8', 'Transistor: N-MOSFET; unipolar; 60V; 62A; 115W; D2PAK', None, 2.74, 0, state='out'),
    ]
    for row in rows:
        d.upsert(row)
    return d


def test_parse_query_splits_words_and_parameters():
    q = srch.parse_query('n-mosfet 60V 80A D2PAK <10mΩ smd logic FDB')
    assert (q.kind, q.polarity, q.pkg, q.mount, q.logic) == ('mosfet', 'N', 'TO-263', 'smd', True)
    assert q.words == ['FDB']
    assert {(c.key, c.op, c.value) for c in q.constraints} == {('volt', '>=', 60.0), ('amp', '>=', 80.0), ('rds_mohm', '<=', 10.0)}


def test_parse_query_units():
    q = srch.parse_query('100nF 2.2uF 500mA 250mW')
    assert {(c.key, round(c.value, 12)) for c in q.constraints} == {('farad', 1e-7), ('farad', 2.2e-6), ('amp', 0.5), ('watt', 0.25)}
    assert q.kind == 'capacitor'
    assert srch.parse_query('0805 to220 sot23').pkg is not None


def test_exact_mpn_finds_all_shops_in_one_group(db):
    result = srch.search(db, 'FDB5800')
    assert [g.mpn for g in result.groups][:1] == ['FDB5800']
    top = result.groups[0]
    assert {o['shop'] for o in top.offers} == {'salvats', 'semikom'}
    assert top.best['shop'] == 'salvats' and top.best['unit_price'] == 1.98
    assert 'совпадает артикул' in top.reasons


def test_search_by_mpn_ignores_dashes_and_case(db):
    assert srch.search(db, 'bc847bdio').groups[0].mpn == 'BC847B-DIO'
    assert srch.search(db, 'BC847B-DIO').groups[0].mpn == 'BC847B-DIO'
    assert srch.search(db, 'tk22e10n1').groups[0].offers[0]['shop'] == 'salvats'


def test_parametric_search_returns_only_matching_offers(db):
    result = srch.search(db, 'n-mosfet 60V 80A D2PAK')
    titles = [o['shop_id'] for g in result.groups for o in g.offers]
    assert set(titles) == {'1', '2', '3'}                 # TO-263 / D2PAK, >= 60 V, >= 80 A (the 62 A one is out)
    assert srch.search(db, 'n-mosfet 100V TO220').groups[0].offers[0]['shop_id'] in ('EB1', '4')


def test_less_than_constraint_for_rds_keeps_unknown_below_confirmed(db):
    result = srch.search(db, 'mosfet <10mΩ')
    first = result.groups[0]
    assert first.mpn == 'FDB5800' and first.unknown == 0                  # only the Salvats card states 6 mΩ
    assert all(g.unknown == 1 for g in result.groups[1:])                  # the rest have no Rds(on) in the title: shown, ranked lower


def test_violated_constraint_removes_the_offer(db):
    ids = {o['shop_id'] for g in srch.search(db, 'mosfet <5mΩ').groups for o in g.offers}
    assert '1' not in ids                                                  # 6 mΩ is above 5 mΩ


def test_in_stock_filter(db):
    ids = {o['shop_id'] for g in srch.search(db, 'n-mosfet 60V D2PAK', in_stock=True).groups for o in g.offers}
    assert '8' not in ids and '1' in ids
    ids = {o['shop_id'] for g in srch.search(db, 'n-mosfet 60V D2PAK').groups for o in g.offers}
    assert '8' in ids


def test_shop_filter(db):
    result = srch.search(db, 'FDB5800', shops=['semikom'])
    assert {o['shop'] for g in result.groups for o in g.offers} == {'semikom'}


def test_capacitor_value_search(db):
    result = srch.search(db, '100nF 50V 0805')
    assert [g.mpn for g in result.groups] == ['CL21B104KBCNNNC']


def test_empty_and_unknown_queries(db):
    assert srch.search(db, '').groups == []
    assert srch.search(db, 'nonexistent-part-9999').groups == []
    assert 'введите' in srch.search(db, '  ').note


def test_cheapest_for_quantity_uses_pack_rounding(db):
    group = srch.search(db, 'CL21B104KBCNNNC').groups[0]
    assert srch.cheapest_for(group, 13)['shop_id'] == '7'


def test_diode_search_matches_schottky(db):
    assert srch.search(db, 'diode 100V SMC').groups[0].mpn == 'SS510-YAN'


# ---- pricing ---------------------------------------------------------------------------------------------

def test_cost_for_single_pieces_and_tiers():
    row = {'sale_price': 0.83, 'unit_price': 0.83, 'pack_qty': 1, 'min_qty': 1, 'tiers': [[5, 0.75]]}
    assert cost_for(row, 1) == dict(total=0.83, buy=1, unit=0.83, packs=None)
    assert cost_for(row, 10) == dict(total=7.5, buy=10, unit=0.75, packs=None)


def test_cost_for_packs_rounds_up_to_whole_packs():
    row = {'sale_price': 0.51, 'unit_price': 0.051, 'pack_qty': 10, 'min_qty': 1, 'tiers': []}
    assert cost_for(row, 13) == dict(total=1.02, buy=20, unit=0.051, packs=2)
    assert cost_for(row, 1)['total'] == 0.51


def test_cost_for_respects_minimum_quantity_and_missing_price():
    assert cost_for({'sale_price': 1.0, 'unit_price': 1.0, 'pack_qty': 1, 'min_qty': 5, 'tiers': []}, 1)['buy'] == 5
    assert cost_for({'sale_price': None}, 3) is None


def test_stock_in_packs_counts_pieces_and_availability():
    pack = {'stock_qty': 20, 'pack_qty': 10, 'stock_state': 'in'}
    assert stock_pieces(pack) == 200 and availability(pack, 13) == 'ok'
    assert availability({'stock_qty': 4, 'pack_qty': 1, 'stock_state': 'in'}, 5) == 'short'
    assert availability({'stock_qty': 0, 'pack_qty': 1, 'stock_state': 'out'}, 1) == 'out'
    assert availability({'stock_qty': None, 'pack_qty': 1, 'stock_state': 'order'}, 1) == 'order'
    assert availability({'stock_qty': None, 'pack_qty': 1, 'stock_state': 'unknown'}, 1) == 'unknown'


def test_explain_lists_what_was_understood():
    assert srch.explain(srch.parse_query('n-mosfet 60V 80A D2PAK <10mΩ smd logic FDB')) == [
        'N-MOSFET', '≥ 60 В', '≥ 80 А', '≤ 10 мОм', 'TO-263', 'SMD', 'logic-level']
    assert srch.explain(srch.parse_query('100nF 50V 0805')) == ['конденсатор', '= 100 нФ', '≥ 50 В', 'SMD0805']
    assert srch.explain(srch.parse_query('FDB5800')) == []
