import csv
import json
import time

import pytest
from fastapi.testclient import TestClient

from conftest import FakeClient
from partscat.crawler import Crawler
from partscat.db import Database, now_iso
from partscat.models import Offer
from partscat.web import create_app, spark

from test_crawler import ScriptedShop
from test_bom import HEADER, PARTS, ROWS
from test_doctor import ROBOTS, scripted


def offer(shop, shop_id, title, mpn=None, price=1.0, stock=5, state='in', url=None, **kw):
    return Offer(shop=shop, shop_id=shop_id, url=url or f'https://{shop}.example/{shop_id}', title=title, mpn=mpn, sale_price=price,
                 stock_qty=stock, stock_state=state, **kw)


@pytest.fixture()
def bom_dir(tmp_path):
    folder = tmp_path / 'bom'
    folder.mkdir()
    with open(folder / 'BOM_allocated.csv', 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(ROWS)
    (folder / 'design.json').write_text(json.dumps({'revision': 'EU-test', 'parts': PARTS}), encoding='utf-8')
    return folder


@pytest.fixture()
def data(tmp_path):
    return tmp_path / 'data'


@pytest.fixture()
def filled(data):
    db = Database(data / 'catalog.db')
    db.upsert(offer('salvats', 'a', 'FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', 'FDB5800', 1.98, 4,
                    url='https://www.salvats.lv/lv/fdb5800', shop_sku='FDB5800'), '2026-10-01T00:00:00Z')
    db.upsert(offer('salvats', 'a', 'FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', 'FDB5800', 2.20, 4,
                    url='https://www.salvats.lv/lv/fdb5800', shop_sku='FDB5800'), now_iso())
    db.upsert(offer('semikom', 'b', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK', 'FDB5800', 4.74, 285), now_iso())
    db.upsert(offer('salvats', 'i', 'IPB037N06N3 SMD Tranzistors N-FET, 60V, ±20V, 90A, 300W, 0R0037, TO-263', 'IPB037N06N3', 2.55, 20), now_iso())
    db.upsert(offer('salvats', 'c', '100nF, 50V, 0805, (10gab,), MLCC, X7R, ±5%, SMD Kondensators, 0805', 'CL21B104KBCNNNC', 0.51, 38,
                    pack_qty=10, url='https://www.salvats.lv/lv/100nf'), now_iso())
    db.upsert(offer('salvats', 'x', '<script>alert(1)</script> Tranzistors N-FET, 60V, TO-263', 'XSS123', 1.0, 5,
                    url='javascript:alert(2)'), now_iso())
    return db


def client_for(data, bom_dir=None, shops=None):
    fake = FakeClient()
    db = Database(data / 'catalog.db')
    crawler = Crawler(db, fake, shops(fake) if shops else None, bom_dir=bom_dir)
    app = create_app(data, bom_dir=bom_dir, client=fake, crawler=crawler)
    return TestClient(app), app


def test_empty_database_explains_where_to_start(data):
    client, _ = client_for(data)
    page = client.get('/').text
    assert 'База пуста' in page and 'Обновить позиции BOM' in page


def test_search_groups_shops_and_marks_the_best(filled, data):
    client, _ = client_for(data)
    page = client.get('/?q=FDB5800').text
    assert page.count('FDB5800') >= 2 and 'Salvats' in page and 'Semikom' in page
    assert 'совпадает артикул' in page and 'class="best' in page
    assert '2,20 €' in page and '4,74 €' in page


def test_search_totals_for_a_quantity_and_pack_rounding(filled, data):
    client, _ = client_for(data)
    page = client.get('/?q=CL21B104KBCNNNC&qty=13').text
    assert '1,02 €' in page and '2 уп. = 20 шт.' in page


def test_parametric_search_shows_chips_and_hides_non_matching(filled, data):
    client, _ = client_for(data)
    page = client.get('/?q=n-mosfet+60V+80A+D2PAK').text
    assert 'N-MOSFET' in page and '≥ 60 В' in page and 'TO-263' in page
    assert 'IPB037N06N3' in page and 'CL21B104KBCNNNC' not in page


def test_nothing_found_offers_to_ask_the_shops(filled, data):
    client, _ = client_for(data)
    page = client.get('/?q=NOSUCHPART9').text
    assert 'ничего нет' in page and 'name="kind" value="search"' in page


def test_shop_titles_and_links_are_neutralised(filled, data):
    client, _ = client_for(data)
    page = client.get('/?q=XSS123').text
    assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page
    assert 'javascript:' not in page


def test_part_card_shows_offers_history_and_loads_analogs(filled, data):
    client, _ = client_for(data)
    page = client.get('/part/FDB5800').text
    assert 'FDB5800' in page and 'hx-get="/analogs?mpn=FDB5800"' in page and '<polyline' in page
    assert 'Vds 60.0 В' in page or 'Vds 60 В' in page
    assert client.get('/part/NOPE').status_code == 404


def test_analogs_partial_gives_verdicts_and_toggle(filled, data):
    client, _ = client_for(data)
    page = client.get('/analogs?mpn=FDB5800').text
    assert 'IPB037N06N3' in page and 'verdict' in page and 'показать и неподходящие' in page
    assert 'hx-get="/analogs?mpn=FDB5800&amp;all=1"' in page or 'hx-get="/analogs?mpn=FDB5800&all=1"' in page
    assert 'Подходящих аналогов в базе нет' in client.get('/analogs?mpn=CL21B104KBCNNNC&stock=1').text
    assert 'нет в базе' in client.get('/analogs?mpn=NOPE').text


def test_bom_page_counts_levels_and_shows_issues(filled, data, bom_dir):
    client, _ = client_for(data, bom_dir)
    page = client.get('/bom').text
    assert 'Проверка BOM' in page and 'EU-test' in page and 'FDB5800' in page
    assert 'цена 1,98 € → 2,20 €' in page                              # the BOM price against the stored one
    assert 'нет в базе' in page                                          # lines that were never read
    assert 'Под фильтр ничего не попало' in client.get('/bom?level=bad').text      # nothing is out of stock or disagrees with the schematic
    warn = client.get('/bom?level=warn').text
    assert 'FDB5800' in warn and 'SMD1206-10K-1%' not in warn
    by_ref = client.get('/bom?q=Q501').text
    assert 'TK22E10N1' in by_ref and 'FDB5800' not in by_ref


def test_bom_csv_is_excel_friendly(filled, data, bom_dir):
    client, _ = client_for(data, bom_dir)
    reply = client.get('/bom.csv')
    assert reply.headers['content-type'].startswith('text/csv') and reply.text.startswith('﻿')
    rows = list(csv.DictReader(reply.text.lstrip('﻿').splitlines(), delimiter=';'))
    assert len(rows) == 7 and {'Статус', 'Артикул', 'Сумма сейчас'} <= set(rows[0])


def test_bom_line_analogs(filled, data, bom_dir):
    client, _ = client_for(data, bom_dir)
    page = client.get('/analogs?line=salvats:FDB5800').text
    assert 'IPB037N06N3' in page and 'TO-263' in page


def test_bom_page_without_a_bom_explains_the_search_path(data, tmp_path, monkeypatch):
    monkeypatch.setattr('partscat.web.find_bom_dir', lambda: None)
    client, _ = client_for(data)
    assert 'PARTSCAT_BOM_DIR' in client.get('/bom').text
    assert client.get('/bom.csv').status_code == 404


def shops_for(client):
    return lambda fake: {'a': ScriptedShop(fake, key='a', products={
        'https://a.example/p/1': offer('a', '1', 'Transistor: N-MOSFET; unipolar; 60V; 80A; D2PAK', mpn='FDB5800', url='https://a.example/p/1',
                                       detail=True)})}


def wait_done(client, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        text = client.get('/crawl/status').text
        if 'идёт' not in text:
            return text
        time.sleep(0.05)
    raise AssertionError('the crawl did not finish')


def test_crawl_start_runs_in_the_background_and_reports(data):
    client, app = client_for(data, shops=shops_for(None))
    reply = client.post('/crawl/start', content='kind=urls&urls=https%3A%2F%2Fa.example%2Fp%2F1',
                        headers={'content-type': 'application/x-www-form-urlencoded', 'hx-request': 'true'})
    assert reply.status_code == 200 and 'id="progress"' in reply.text
    status = wait_done(client)
    assert 'готово' in status and 'новых: <b>1</b>' in status
    assert app.state.db.find('a', '1')['mpn'] == 'FDB5800'
    assert [w['url'] for w in app.state.db.watch_list()] == ['https://a.example/p/1']
    assert 'FDB5800' in client.get('/?q=FDB5800').text


def test_connection_check_runs_from_the_crawl_page_and_shows_its_lines(data):
    client, app = client_for(data, shops=lambda fake: {'salvats': scripted(fake)})
    app.state.client.routes['https://salvats.example/robots.txt'] = ROBOTS
    assert 'name="kind" value="doctor"' in client.get('/crawl').text
    reply = client.post('/crawl/start', content='kind=doctor', headers={'content-type': 'application/x-www-form-urlencoded', 'hx-request': 'true'})
    assert reply.status_code == 200 and 'Проверить связь с магазинами' in reply.text
    status = wait_done(client)
    assert 'готово' in status and '[ ok ] Salvats: robots.txt' in status and 'Страниц прочитано' not in status
    assert '<details open><summary>Журнал' in status


def test_crawl_form_posts_redirect_and_busy_notice(data):
    client, _ = client_for(data, shops=shops_for(None))
    reply = client.post('/crawl/start', content='kind=watch', headers={'content-type': 'application/x-www-form-urlencoded'}, follow_redirects=False)
    assert reply.status_code == 303 and reply.headers['location'] == '/crawl'
    wait_done(client)
    assert client.get('/crawl').status_code == 200


def test_crawl_rejects_other_origins_and_unknown_plans(data):
    client, _ = client_for(data, shops=shops_for(None))
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    assert client.post('/crawl/start', content='kind=bom', headers={**headers, 'origin': 'http://evil.example'}).status_code == 403
    assert client.post('/crawl/stop', content='', headers={**headers, 'origin': 'http://evil.example'}).status_code == 403
    assert client.post('/crawl/start', content='kind=format-disk', headers=headers).status_code == 400
    assert client.post('/crawl/start', content='kind=bom', headers={**headers, 'origin': 'http://testserver'}, follow_redirects=False).status_code == 303
    wait_done(client)


def test_untrusted_host_header_is_refused(data):
    client, _ = client_for(data)
    assert client.get('/', headers={'host': 'evil.example'}).status_code == 400


def test_watch_list_add_and_remove(data):
    client, app = client_for(data, shops=shops_for(None))
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    client.post('/crawl/watch', content='url=https%3A%2F%2Fa.example%2Fp%2F9', headers=headers)
    assert [w['url'] for w in app.state.db.watch_list()] == ['https://a.example/p/9']
    reply = client.post('/crawl/watch', content='url=https%3A%2F%2Felsewhere.example%2Fx', headers=headers, follow_redirects=False)
    assert 'notice=foreign' in reply.headers['location']
    client.post('/crawl/watch', content='url=https%3A%2F%2Fa.example%2Fp%2F9&action=remove', headers=headers)
    assert app.state.db.watch_list() == []


def test_health_and_export(filled, data, bom_dir):
    client, _ = client_for(data, bom_dir)
    health = client.get('/health').json()
    assert health['ok'] and health['offers'] == 5 and health['bom_lines'] == 7 and health['crawling'] is False
    csv_text = client.get('/export/offers.csv').text
    assert csv_text.startswith('﻿') and 'FDB5800' in csv_text


def test_spark_points():
    assert spark([{'at': 'a', 'unit_price': 1.0}]) is None
    line = spark([{'at': '2026-10-01', 'unit_price': 1.0}, {'at': '2026-10-02', 'unit_price': 2.0}, {'at': '2026-10-03', 'unit_price': 1.5}])
    assert line['first'] == ('2026-10-01', 1.0) and line['last'] == ('2026-10-03', 1.5) and line['points'].count(',') == 3


def test_show_more_appears_only_when_the_list_was_cut(data):
    db = Database(data / 'catalog.db')
    for n in range(12):
        db.upsert(offer('salvats', f'm{n}', f'Part {n} Tranzistors N-FET, 60V, 80A, TO-263', f'PART{n:03d}', 1.0 + n, 5), now_iso())
    client, _ = client_for(data)
    assert 'Показать ещё' in client.get('/?q=PART&limit=10').text
    assert 'Показать ещё' not in client.get('/?q=PART&limit=40').text
    assert 'Показать ещё' not in client.get('/?q=PART001').text


def test_unnamed_offer_has_a_clear_heading(filled, data):
    Database(data / 'catalog.db').upsert(offer('semikom', 'u', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 310W; D2PAK', None, 6.0, 9), now_iso())
    client, _ = client_for(data)
    assert 'артикул не указан' in client.get('/?q=n-mosfet+60V+310W').text


def test_analogs_offer_to_read_the_unread_candidate_cards(filled, data):
    client, _ = client_for(data)
    page = client.get('/analogs?mpn=FDB5800').text
    assert 'name="kind" value="enrich"' in page and 'Дочитать карточки кандидатов' in page


def test_bom_offers_analogs_only_where_the_comparison_can_work(filled, data, bom_dir):
    client, _ = client_for(data, bom_dir)
    assert client.get('/bom?q=FDB5800').text.count('<summary>аналоги</summary>') == 1
    assert client.get('/bom?q=KF2510').text.count('<summary>аналоги</summary>') == 0
    assert client.get('/bom?q=BAT-CR2032').text.count('<summary>аналоги</summary>') == 0       # an accessory


def test_enrich_by_ids_reads_cards_that_already_have_a_part_number(data):
    client, app = client_for(data, shops=shops_for(None))
    db = app.state.db
    offer_id, _ = db.upsert(offer('a', '1', 'Transistor: N-MOSFET; unipolar; 60V; 80A; D2PAK', mpn='FDB5800', url='https://a.example/p/1'))
    assert db.without_detail() == []                                                 # the default picks only cards without a part number
    assert [o['id'] for o in db.without_detail(ids=[offer_id])] == [offer_id]
    reply = client.post('/crawl/start', content=f'kind=enrich&ids={offer_id}',
                        headers={'content-type': 'application/x-www-form-urlencoded', 'hx-request': 'true'})
    assert reply.status_code == 200
    assert 'готово' in wait_done(client) and db.find('a', '1')['detail_at']
