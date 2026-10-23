import sqlite3

import pytest

from partscat.db import Database, age_days
from partscat.models import Offer


def make(**kw):
    base = dict(shop='salvats', shop_id='00026030', url='https://www.salvats.lv/lv/x/fdb5800',
                title='FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263',
                mpn='FDB5800', shop_sku='FDB5800', sale_price=1.98, stock_qty=4, stock_state='in',
                category='N kanalu lauku tranzistori SMD')
    base.update(kw)
    return Offer(**base)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / 'data' / 'catalog.db')


def test_insert_then_same_then_changed(db):
    offer_id, status = db.upsert(make(), now='2026-10-23T10:00:00Z')
    assert status == 'new'
    assert db.upsert(make(), now='2026-10-23T11:00:00Z') == (offer_id, 'same')
    assert db.upsert(make(sale_price=2.10), now='2026-10-24T11:00:00Z') == (offer_id, 'changed')
    history = db.history(offer_id)
    assert [h['unit_price'] for h in history] == [1.98, 2.10]
    row = db.offer(offer_id)
    assert row['first_seen'] == '2026-10-23T10:00:00Z' and row['last_seen'] == '2026-10-24T11:00:00Z'


def test_parameters_are_stored_for_filtering(db):
    offer_id, _ = db.upsert(make())
    row = db.offer(offer_id)
    assert row['kind'] == 'mosfet' and row['pkg'] == 'TO-263'
    assert row['params']['vds'] == 60 and row['params']['id'] == 80
    assert row['mpn_norm'] == 'FDB5800'


def test_pack_price_is_divided_into_unit_price(db):
    offer = make(shop_id='1', title='100nF, 50V, 0805, (10gab,), MLCC, X7R, ±5%, SMD Kondensators, 0805',
                 mpn=None, shop_sku='CL21B104KBCNNNC', sale_price=0.51, pack_qty=10, url='https://www.salvats.lv/lv/c')
    offer_id, _ = db.upsert(offer)
    row = db.offer(offer_id)
    assert row['unit_price'] == pytest.approx(0.051) and row['sale_price'] == 0.51 and row['pack_qty'] == 10


def test_listing_does_not_erase_product_page_data(db):
    detail = make(mpn='FDB5800', props={'Gate charge': '135nC'}, tiers=[(10, 1.80)], detail=True)
    offer_id, _ = db.upsert(detail, now='2026-10-23T10:00:00Z')
    listing = make(mpn=None, props={}, tiers=[], detail=False)
    db.upsert(listing, now='2026-10-23T12:00:00Z')
    row = db.offer(offer_id)
    assert row['mpn'] == 'FDB5800' and row['props']['Gate charge'] == '135nC' and row['tiers'] == [[10, 1.8]]
    assert row['detail_at'] == '2026-10-23T10:00:00Z'
    assert row['params']['qg_nc'] == pytest.approx(135)


def test_unreadable_price_keeps_the_last_known_one(db):
    offer_id, _ = db.upsert(make())
    assert db.upsert(make(sale_price=None, stock_qty=None, stock_state='unknown')) == (offer_id, 'same')
    row = db.offer(offer_id)
    assert row['unit_price'] == 1.98 and row['stock_qty'] == 4


def test_by_mpn_matches_mpn_or_sku_after_normalization(db):
    db.upsert(make(shop_id='a', mpn='BC847B-DIO', shop_sku=None, title='BC847B-DIO SMD Tranzistors, NPN, 45V, 0.1A, SOT23'))
    db.upsert(make(shop_id='b', mpn=None, shop_sku='bc847b dio', title='x', url='https://www.salvats.lv/lv/b'))
    assert {r['shop_id'] for r in db.by_mpn('BC847BDIO')} == {'a', 'b'}
    assert db.by_mpn('') == []


def test_candidates_need_every_word_and_ignore_diacritics(db):
    db.upsert(make(shop_id='a', title='SS510 Diode Šotki, 100V, 5A, SMC', mpn='SS510', shop_sku=None, category='Diodes Šotki'))
    db.upsert(make(shop_id='b', title='FDB5800 N-FET 60V', mpn='FDB5800', shop_sku=None))
    assert [r['shop_id'] for r in db.candidates(['sotki'])] == ['a']
    assert [r['shop_id'] for r in db.candidates(['fdb', '60v'])] == ['b']
    assert db.candidates(['fdb', 'sotki']) == []
    assert [r['shop_id'] for r in db.candidates(['ss-510'])] == ['a']


def test_candidates_filter_by_shop_and_kind(db):
    db.upsert(make(shop_id='a'))
    db.upsert(make(shop_id='b', shop='semikom', url='https://www.semikom.lv/b'))
    assert len(db.candidates(['fdb5800'], shops=['semikom'])) == 1
    assert db.candidates(['fdb5800'], kind='bjt') == []
    assert len(db.by_kind('mosfet', pkg='TO-263')) == 2


def test_stats_and_runs(db):
    db.upsert(make())
    run = db.start_run('bom')
    db.finish_run(run, 'ok', {'rows': 1}, ['e'])
    assert db.stats()['total'] == 1 and db.stats()['shops']['salvats']['count'] == 1
    runs = db.recent_runs()
    assert runs[0]['status'] == 'ok' and runs[0]['stats'] == {'rows': 1} and runs[0]['errors'] == ['e']


def test_stale_runs_are_closed(db):
    db.start_run('bom')
    assert db.close_stale_runs() == 1
    assert db.recent_runs()[0]['status'] == 'interrupted'


def test_old_v1_file_is_moved_aside(tmp_path):
    path = tmp_path / 'catalog.db'
    old = sqlite3.connect(path)
    old.execute('CREATE TABLE components (id INTEGER PRIMARY KEY, title TEXT)')
    old.execute("INSERT INTO components (title) VALUES ('legacy')")
    old.commit()
    old.close()
    db = Database(path)
    assert db.stats()['total'] == 0
    backup = tmp_path / 'catalog.v1-backup.db'
    assert backup.exists()
    assert sqlite3.connect(backup).execute('SELECT title FROM components').fetchone()[0] == 'legacy'


def test_age_days():
    assert age_days('2026-10-20T00:00:00Z', now='2026-10-23T12:00:00Z') == pytest.approx(3.5)
    assert age_days(None) is None
