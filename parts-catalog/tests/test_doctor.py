"""The connection check: what it says about the installation, the data, the BOM and every shop."""
import json

import pytest

from conftest import FakeClient, fixture_text
from partscat import doctor
from partscat.crawler import Crawler
from partscat.db import Database
from partscat.http import FetchError
from partscat.models import Offer
from partscat.shops import lemona
from partscat.shops.base import Listing
from test_crawler import ScriptedShop, offer

ROBOTS = 'User-agent: *\nDisallow: /cart\n'
BOM_HEADER = ('Shop,MPN_or_shop_SKU,Fitted_or_accessory,Buy_pieces,Sale_unit,Price_per_sale_unit_EUR_VAT,Line_EUR_VAT,References,'
              'Accessory_count,URL,Price_date\n')


class FailingClient(FakeClient):
    """A FakeClient that raises the given FetchError for some addresses."""

    def __init__(self, routes, fail):
        super().__init__(routes)
        self.fail = fail

    def get(self, url, *, params=None, **kw):
        if url in self.fail:
            self.calls.append(('GET', url, params))
            raise self.fail[url]
        return super().get(url, params=params, **kw)


def healthy_routes():
    def lemona_answer(payload):
        if 'urlResolver' in payload['query']:
            return {'data': {'urlResolver': {'id': 30362, 'type': 'PRODUCT', 'relative_url': 'x.html'}}}
        return json.loads(fixture_text('lemona', 'product_30362.json'))
    return {
        'https://www.salvats.lv/robots.txt': ROBOTS,
        doctor.SAMPLES['salvats']: fixture_text('salvats', 'product_fdb5800.html'),
        'https://www.salvats.lv/lv/search-results': fixture_text('salvats', 'search_fdb5800.html'),
        'https://electrobase.lv/robots.txt': ROBOTS,
        doctor.SAMPLES['electrobase']: fixture_text('electrobase', 'product_lm3429.html'),
        'https://www.semikom.lv/robots.txt': ROBOTS,
        doctor.SAMPLES['semikom']: fixture_text('semikom', 'product_fdb5800.html'),
        'https://www.semikom.lv/FDB5800.gs': fixture_text('semikom', 'search_n_mosfet_60v.html'),
        'https://www.lemona.lv/robots.txt': ROBOTS,
        lemona.GRAPHQL: lemona_answer,
    }


# ---- installation, data, BOM -----------------------------------------------------------------------------

def test_installation_lines_are_ok_here():
    lines = doctor.environment()
    assert {line.status for line in lines} == {'ok'}
    assert lines[0].title == 'Python' and [line.title for line in lines[1:]] == [f'библиотека {name}' for name in doctor.LIBRARIES]


def test_missing_library_says_how_to_install_it(monkeypatch):
    real = doctor.importlib.import_module

    def refuse(name, *args):
        if name == 'bs4':
            raise ImportError(name)
        return real(name, *args)
    monkeypatch.setattr(doctor.importlib, 'import_module', refuse)
    broken = [line for line in doctor.environment() if line.status == 'fail']
    assert [line.title for line in broken] == ['библиотека bs4'] and 'pip install -r requirements.txt' in broken[0].detail


def test_database_states(tmp_path):
    [line] = doctor.data(tmp_path)
    assert line.status == 'warn' and 'Сбор' in line.detail                      # empty is a finding, not a failure
    Database(tmp_path / 'catalog.db').upsert(Offer(shop='salvats', shop_id='1', url='https://x/1', title='T', mpn='A', sale_price=1.0))
    [line] = doctor.data(tmp_path)
    assert line.status == 'ok' and '1 предложений' in line.detail
    broken = tmp_path / 'broken'
    broken.mkdir()
    (broken / 'catalog.db').write_bytes(b'this is not a database file' * 200)
    [line] = doctor.data(broken)
    assert line.status == 'fail' and 'DatabaseError' in line.detail


def test_bom_found_counts_lines_with_pages_and_missing_bom_warns(tmp_path, monkeypatch):
    folder = tmp_path / 'bom'
    folder.mkdir()
    (folder / 'BOM_allocated.csv').write_text(
        BOM_HEADER + 'Salvats,FDB5800,1,1,шт.,1.98,1.98,Q102,0,https://www.salvats.lv/lv/x/fdb5800,2026-10-23\n'
                     'не выбран,KF2510-4A,1,1,шт.,,,J1,0,,\n', encoding='utf-8')
    [line], loaded = doctor.bom(folder)
    assert line.status == 'ok' and '2 строк, из них со страницей магазина 1' in line.detail and len(loaded.lines) == 2
    monkeypatch.setattr(doctor, 'find_bom_dir', lambda: None)
    [line], loaded = doctor.bom(None)
    assert line.status == 'warn' and loaded is None and 'PARTSCAT_BOM_DIR' in line.detail


# ---- shops -----------------------------------------------------------------------------------------------

def test_every_shop_answers():
    client = FakeClient(healthy_routes())
    emitted = []
    lines = doctor.shops(client, None, emit=emitted.append)
    assert lines == emitted and len(lines) == 12 and {line.status for line in lines} == {'ok'}
    text = '\n'.join(line.text() for line in lines)
    assert 'Salvats: поиск «FDB5800»' in text and 'Semikom: поиск «FDB5800»' in text
    assert 'Electrobase: поиск: не используется' in text and 'Lemona: поиск: не используется' in text
    assert client.ttl == 72000.0                                              # the check reads fresh pages and puts the cache setting back


def test_only_the_named_shop_is_asked():
    client = FakeClient(healthy_routes())
    lines = doctor.shops(client, None, only=['semikom'])
    assert len(lines) == 3 and {call[1].split('/')[2] for call in client.calls} == {'www.semikom.lv'}


def test_a_page_from_the_bom_is_preferred_to_the_built_in_sample(tmp_path):
    folder = tmp_path / 'bom'
    folder.mkdir()
    url = 'https://www.salvats.lv/lv/x/my-own-page'
    (folder / 'BOM_allocated.csv').write_text(BOM_HEADER + f'Salvats,FDB5800,1,1,шт.,1.98,1.98,Q102,0,{url},2026-10-23\n', encoding='utf-8')
    routes = healthy_routes()
    routes[url] = routes.pop(doctor.SAMPLES['salvats'])
    _, loaded = doctor.bom(folder)
    lines = doctor.shops(FakeClient(routes), loaded, only=['salvats'])
    assert {line.status for line in lines} == {'ok'}


def test_a_ban_is_reported_and_the_search_is_not_attempted():
    sample = doctor.SAMPLES['semikom']
    client = FailingClient(healthy_routes(), {sample: FetchError('banned', 'www.semikom.lv: Banned (HTTP 423)', sample, 423)})
    lines = doctor.shops(client, None, only=['semikom'])
    assert [line.status for line in lines] == ['ok', 'fail'] and 'banned' in lines[1].detail
    assert not [call for call in client.calls if call[1].endswith('.gs')]


def test_unreachable_robots_txt_stops_the_check_of_that_shop():
    robots = 'https://www.salvats.lv/robots.txt'
    client = FailingClient(healthy_routes(), {robots: FetchError('network', 'www.salvats.lv: timeout', robots)})
    lines = doctor.shops(client, None, only=['salvats'])
    assert [line.status for line in lines] == ['fail'] and 'network' in lines[0].detail
    assert [call[1] for call in client.calls] == [robots]


def test_a_robots_txt_that_closes_the_site_is_a_warning_and_the_page_check_follows():
    routes = healthy_routes()
    routes['https://www.salvats.lv/robots.txt'] = 'User-agent: *\nDisallow: /\n'
    lines = doctor.shops(FakeClient(routes), None, only=['salvats'])
    assert lines[0].status == 'warn' and 'ЗАПРЕЩЕНА' in lines[0].detail and len(lines) == 3


def test_a_changed_page_layout_is_a_failure_and_an_empty_search_a_warning():
    routes = healthy_routes()
    routes[doctor.SAMPLES['salvats']] = '<html><body>nothing here</body></html>'
    routes['https://www.salvats.lv/lv/search-results'] = '<html><body>nothing here</body></html>'
    lines = doctor.shops(FakeClient(routes), None, only=['salvats'])
    assert [line.status for line in lines] == ['ok', 'fail', 'warn']
    assert 'не прочиталось' in lines[1].detail or 'разбор не удался' in lines[1].detail
    assert 'карточек не найдено' in lines[2].detail


# ---- the same check from the «Сбор» page -----------------------------------------------------------------

def scripted(client, **kw):
    good = offer('salvats', '1', title='FDB5800 N-FET', price=1.98, mpn='FDB5800')
    return ScriptedShop(client, key='salvats', products={doctor.SAMPLES['salvats']: good}, pages={('search', 'FDB5800', 1): Listing(offers=[good])}, **kw)


def test_doctor_plan_logs_every_line_and_stores_nothing(tmp_path):
    db = Database(tmp_path / 'c.db')
    client = FakeClient({'https://salvats.example/robots.txt': ROBOTS})
    result = Crawler(db, client, {'salvats': scripted(client)}).run({'kind': 'doctor'})
    assert result['state'] == 'done' and result['counts']['errors'] == 0 and result['errors'] == []
    assert [line.split(':')[0] for line in result['log']] == ['[ ok ] Salvats'] * 3
    assert db.stats()['total'] == 0 and result['done'] == result['total'] == 1


def test_doctor_plan_turns_failed_checks_into_visible_errors(tmp_path):
    db = Database(tmp_path / 'c.db')
    client = FakeClient({'https://salvats.example/robots.txt': ROBOTS})
    broken = scripted(client, errors={doctor.SAMPLES['salvats']: FetchError('http', 'salvats.example: HTTP 500', doctor.SAMPLES['salvats'], 500)})
    result = Crawler(db, client, {'salvats': broken}).run({'kind': 'doctor'})
    assert result['state'] == 'done' and result['counts']['errors'] == 1
    [error] = result['errors']
    assert error['kind'] == 'check' and error['shop'] == 'salvats' and 'HTTP 500' in error['message']
    assert any(line.startswith('[FAIL] Salvats: страница товара') for line in result['log'])
