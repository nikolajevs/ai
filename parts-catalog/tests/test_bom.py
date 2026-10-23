import csv
import json

import pytest

from partscat import bom as bommod
from partscat.db import Database, now_iso
from partscat.models import Offer

HEADER = ['Shop', 'MPN_or_shop_SKU', 'Fitted_or_accessory', 'Buy_pieces', 'Sale_unit', 'Price_per_sale_unit_EUR_VAT', 'Line_EUR_VAT',
          'References', 'Accessory_count', 'URL', 'Price_date']
ROWS = [
    ['Salvats', 'FDB5800', '2', '2', 'шт.', '1.98', '3.96', 'Q102 Q703', '0', 'https://www.salvats.lv/lv/fdb5800', '2026-10-23'],
    ['Salvats', 'CL21B104KBCNNNC', '13', '20', 'уп. 10 шт.', '0.51', '1.02', 'C107 C108', '0', 'https://www.salvats.lv/lv/100nf', '2026-10-20'],
    ['Electrobase', 'CSD19534KCS', '1', '1', 'шт.', '3.09', '3.09', 'Q601', '0', 'https://electrobase.lv/katalogs/csd', '2026-10-23'],
    ['Salvats', 'SMD1206-10K-1%', '2', '2', 'шт.', '0.03', '0.06', 'R110 R102', '0', 'https://www.salvats.lv/lv/10k', '2026-10-20'],
    ['не выбран', 'KF2510-4A', '2', '2', 'шт.', '0.0', '0.0', 'J411 J421', '0', '', '2026-10-22'],
    ['Salvats', 'TK22E10N1', '1', '1', 'шт.', '1.38', '1.38', 'Q501', '0', 'https://www.salvats.lv/lv/tk22', '2026-10-23'],
    ['Salvats', 'BAT-CR2032/P', '1', '1', 'шт.', '0.75', '0.75', '', '1', '', '2026-10-20'],
]
PARTS = [
    {'ref': 'Q102', 'symbol': 'NMOS', 'value': 'FDB5800', 'footprint': 'Package_TO_SOT_SMD:TO-263-2'},
    {'ref': 'Q703', 'symbol': 'NMOS', 'value': 'FDB5800', 'footprint': 'Package_TO_SOT_SMD:TO-263-2'},
    {'ref': 'C107', 'symbol': 'C', 'value': '100n 50V', 'footprint': 'Capacitor_SMD:C_0805_2012Metric'},
    {'ref': 'C108', 'symbol': 'C', 'value': '100n', 'footprint': 'Capacitor_SMD:C_0805_2012Metric'},
    {'ref': 'R110', 'symbol': 'R', 'value': '10k 1%', 'footprint': 'Resistor_SMD:R_1206_3216Metric'},
    {'ref': 'R102', 'symbol': 'R', 'value': '10k 1%', 'footprint': 'Resistor_SMD:R_1206_3216Metric'},
    {'ref': 'Q501', 'symbol': 'NMOS', 'value': 'TK22E10N1', 'footprint': 'Package_TO_SOT_THT:TO-220-3_Vertical'},
]


@pytest.fixture()
def bom_dir(tmp_path):
    folder = tmp_path / 'bom'
    folder.mkdir()
    with open(folder / 'BOM_allocated.csv', 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(ROWS)
    (folder / 'design.json').write_text(json.dumps({'revision': 'EU-test', 'parts': PARTS}), encoding='utf-8')
    (folder / 'BOM_allocated.json').write_text(json.dumps([
        {'shop': 'Salvats', 'mpn': 'FDB5800', 'block': 'PTC', 'usage': 'ключ PTC'}]), encoding='utf-8')
    return folder


def stored(shop, shop_id, url, title, mpn, price, stock, state='in', pack=1, **kw):
    return Offer(shop=shop, shop_id=shop_id, url=url, title=title, mpn=mpn, sale_price=price, stock_qty=stock, stock_state=state,
                 pack_qty=pack, **kw)


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / 'c.db')
    now = now_iso()
    d.upsert(stored('salvats', 'a', 'https://www.salvats.lv/lv/fdb5800',
                    'FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', 'FDB5800', 2.20, 4,
                    shop_sku='FDB5800'), now)
    d.upsert(stored('semikom', 'b', 'https://www.semikom.lv/fdb5800.1.p', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK',
                    'FDB5800', 4.74, 285), now)
    d.upsert(stored('salvats', 'c', 'https://www.salvats.lv/lv/100nf', '100nF, 50V, 0805, (10gab,), MLCC, X7R, ±5%, SMD Kondensators, 0805',
                    'CL21B104KBCNNNC', 0.51, 38, pack=10), now)
    d.upsert(stored('electrobase', 'EB9', 'https://electrobase.lv/katalogs/csd', 'Transistor: N-MOSFET | unipolar | 100V | 100A | 118W | TO220-3',
                    'CSD19534KCS', 3.09, 0, state='out'), now)
    d.upsert(stored('salvats', 'd', 'https://www.salvats.lv/lv/10k', '10K, 0805, 1%, SMD Rezistors, 0805', 'SMD1206-10K-1%', 0.03, 500), now)
    d.upsert(stored('salvats', 'e', 'https://www.salvats.lv/lv/tk22', '22E10N Tranzistors N-FET 100V, ±20V, 22A, 72W, 0R0115, TO-220',
                    'TK22E10N1', 1.38, 22), '2026-10-01T00:00:00Z')
    d.upsert(stored('semikom', 'f', 'https://www.semikom.lv/kf.2.p', 'Connector: wire-board | 2.54mm | male | PIN: 4', 'KF2510-4A', 0.20, 100), now)
    return d


def test_load_bom_reads_lines_values_and_notes(bom_dir):
    bom = bommod.load_bom(bom_dir)
    assert bom.revision == 'EU-test' and len(bom.lines) == 7
    fdb = bom.lines[0]
    assert (fdb.shop, fdb.mpn, fdb.fitted, fdb.buy, fdb.pack, fdb.price, fdb.refs) == ('salvats', 'FDB5800', 2, 2, 1, 1.98, ['Q102', 'Q703'])
    assert fdb.block == 'PTC' and [p['ref'] for p in fdb.parts] == ['Q102', 'Q703']
    pack = bom.lines[1]
    assert (pack.pack, pack.fitted, pack.buy, pack.unit) == (10, 13, 20, 'уп. 10 шт.')
    none = bom.lines[4]
    assert none.shop == '' and none.price is None and none.url == ''
    assert bom.total == round(3.96 + 1.02 + 3.09 + 0.06 + 0.0 + 1.38 + 0.75, 2)


def test_find_bom_dir_prefers_env_then_local_folder(bom_dir, tmp_path, monkeypatch):
    monkeypatch.setenv('PARTSCAT_BOM_DIR', str(bom_dir))
    assert bommod.find_bom_dir() == bom_dir
    monkeypatch.delenv('PARTSCAT_BOM_DIR')
    root = tmp_path / 'app'
    (root / 'bom').mkdir(parents=True)
    assert bommod.find_bom_dir(root) is None
    (root / 'bom' / 'BOM_allocated.csv').write_text('Shop\n', encoding='utf-8')
    assert bommod.find_bom_dir(root) == root / 'bom'


def test_footprint_package_and_expectation():
    assert bommod.footprint_package('Resistor_SMD:R_1206_3216Metric') == 'SMD1206'
    assert bommod.footprint_package('Package_TO_SOT_SMD:TO-263-2') == 'TO-263'
    assert bommod.footprint_package('Diode_SMD:D_SMB') == 'SMB'
    assert bommod.footprint_package('Diode_SMD:D_MiniMELF') == 'MiniMELF'
    assert bommod.footprint_package('EU_Parts:Vishay_TO-277A_D_K1_A2') == 'TO-277A'
    assert bommod.footprint_package('Capacitor_THT:CP_Radial_D8.0mm_P5.00mm') is None
    r = bommod.expectation({'ref': 'R101', 'symbol': 'R', 'value': '0R01 3W 1%', 'footprint': 'Resistor_SMD:R_2512_6332Metric'})
    assert (r['kind'], r['ohm'], r['pd'], r['tol'], r['pkg']) == ('resistor', 0.01, 3.0, 1.0, 'SMD2512')
    c = bommod.expectation({'ref': 'C1', 'symbol': 'C', 'value': '4n7 C0G', 'footprint': 'Capacitor_SMD:C_1206_3216Metric'})
    assert (c['kind'], round(c['farad'] * 1e9, 3), c['dielectric']) == ('capacitor', 4.7, 'C0G')
    c = bommod.expectation({'ref': 'C2', 'symbol': 'C', 'value': '22u 6.3V', 'footprint': ''})
    assert (round(c['farad'] * 1e6), c['vr']) == (22, 6.3)
    q = bommod.expectation({'ref': 'Q411', 'symbol': 'NMOS_GSD', 'value': 'FAN1 AO3422', 'footprint': 'Package_TO_SOT_SMD:SOT-23'})
    assert (q['kind'], q['polarity']) == ('mosfet', 'N')
    assert bommod.expectation({'ref': 'Q702', 'symbol': 'PNP', 'value': 'BC857B', 'footprint': ''})['polarity'] == 'PNP'


def test_check_reports_price_stock_and_cheaper_offers(bom_dir, db):
    report = bommod.check_bom(db, bommod.load_bom(bom_dir))
    by_mpn = {c.line.mpn: c for c in report.checks}
    fdb = by_mpn['FDB5800']
    assert fdb.level == 'warn'                                                    # 1.98 -> 2.20 is +11 %
    codes = {i.code for i in fdb.issues}
    assert {'price', 'low'} <= codes and 'cheaper' not in codes                    # Semikom is dearer
    assert fdb.now_total == 4.40 and fdb.delta == 0.44
    assert by_mpn['CL21B104KBCNNNC'].level == 'ok'
    assert by_mpn['CL21B104KBCNNNC'].now_total == 1.02                              # 2 packs of 10 for 13 pieces
    csd = by_mpn['CSD19534KCS']
    assert csd.level == 'bad' and csd.issues[0].code == 'out'


def test_stale_data_and_spec_mismatch(bom_dir, db):
    report = bommod.check_bom(db, bommod.load_bom(bom_dir), now='2026-10-23T12:00:00Z')
    by_mpn = {c.line.mpn: c for c in report.checks}
    assert any(i.code == 'stale' for i in by_mpn['TK22E10N1'].issues) and by_mpn['TK22E10N1'].level == 'warn'
    resistor = by_mpn['SMD1206-10K-1%']
    assert resistor.level == 'bad'
    assert any(i.code == 'spec' and 'корпус в магазине SMD0805, на плате SMD1206' in i.text for i in resistor.issues)


def test_line_without_shop_lists_where_it_exists(bom_dir, db):
    report = bommod.check_bom(db, bommod.load_bom(bom_dir))
    kf = next(c for c in report.checks if c.line.mpn == 'KF2510-4A')
    assert kf.level == 'warn' and kf.offer is None
    assert 'semikom 0,40 €' in kf.issues[0].text and kf.others[0]['shop'] == 'semikom'


def test_missing_offer_is_unknown_not_a_failure(bom_dir, tmp_path):
    report = bommod.check_bom(Database(tmp_path / 'empty.db'), bommod.load_bom(bom_dir))
    assert report.counts()['none'] == 7 and report.counts()['bad'] == 0
    assert report.now_total == report.bom_total and report.refreshed == 0


def test_url_variants_find_the_page_with_or_without_www(bom_dir, db):
    line = bommod.load_bom(bom_dir).lines[2]
    line.url = 'https://www.electrobase.lv/katalogs/csd/'
    assert bommod.find_offer(db, line)['shop_id'] == 'EB9'


def test_real_bom_of_the_repository_loads():
    folder = bommod.find_bom_dir()
    if folder is None:
        pytest.skip('the board folder is not next to the app')
    bom = bommod.load_bom(folder)
    assert len(bom.lines) > 50 and bom.total > 50
    assert all(line.mpn for line in bom.lines)
    assert sum(1 for line in bom.lines if line.parts) > 40


def test_shipping_comes_from_the_board_summary(bom_dir, tmp_path):
    assert bommod.load_bom(bom_dir).shipping is None
    (bom_dir / 'review').mkdir()
    (bom_dir / 'review' / 'BOM_summary.json').write_text(json.dumps({'shipping_EUR': '5.87', 'total_EUR': '84.67'}), encoding='utf-8')
    bom = bommod.load_bom(bom_dir)
    report = bommod.check_bom(Database(tmp_path / 'empty.db'), bom)
    assert bom.shipping == 5.87
    assert report.with_shipping == (round(bom.total + 5.87, 2), round(bom.total + 5.87, 2))
