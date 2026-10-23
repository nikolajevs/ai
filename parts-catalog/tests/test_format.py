from datetime import datetime, timezone

from partscat import format as f


def test_money_and_unit_money():
    assert f.money(1.98) == '1,98 €' and f.money(None) == '—' and f.money(12) == '12,00 €'
    assert f.unit_money(12.0) == '12,00 €' and f.unit_money(0.51) == '0,51 €' and f.unit_money(0.0649) == '0,0649 €'
    assert f.unit_money(0.07) == '0,07 €' and f.unit_money(0.045) == '0,045 €' and f.unit_money(None) == '—'


def test_signed_percent_hides_a_zero_change():
    assert f.signed_percent(1.98, 2.20) == '+11 %' and f.signed_percent(2.0, 1.5) == '-25 %'
    assert f.signed_percent(1.0, 1.001) == '' and f.signed_percent(None, 1.0) == '' and f.signed_percent(0, 1.0) == ''


def test_ago_in_words():
    now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
    assert f.ago('2026-10-23T11:59:30Z', now) == 'только что'
    assert f.ago('2026-10-23T11:30:00Z', now) == '30 мин. назад'
    assert f.ago('2026-10-23T09:00:00Z', now) == '3 ч. назад'
    assert f.ago('2026-10-22T09:00:00Z', now) == 'вчера'
    assert f.ago('2026-10-13T12:00:00Z', now) == '10 дн. назад'
    assert f.ago('2026-06-23T12:00:00Z', now) == '4 мес. назад'
    assert f.ago(None, now) == 'никогда'


def test_stock_text_for_pieces_packs_and_states():
    assert f.stock_text({'stock_state': 'in', 'stock_qty': 285, 'pack_qty': 1}) == '285 шт.'
    assert f.stock_text({'stock_state': 'in', 'stock_qty': 1000, 'stock_atleast': True, 'pack_qty': 1}) == '>1000 шт.'
    assert f.stock_text({'stock_state': 'in', 'stock_qty': 38, 'pack_qty': 10}) == '38 уп. (380 шт.)'
    assert f.stock_text({'stock_state': 'out', 'stock_qty': 0, 'pack_qty': 1}) == 'нет в наличии'
    assert f.stock_text({'stock_state': 'order', 'stock_qty': None, 'pack_qty': 1}) == 'под заказ'
    assert f.stock_text({'stock_state': 'in', 'stock_qty': None, 'pack_qty': 1}) == 'в наличии'
    assert f.stock_text({'stock_state': 'unknown', 'stock_qty': None, 'pack_qty': 1}) == 'неизвестно'
    assert f.stock_text({'stock_state': 'order', 'stock_qty': 5, 'pack_qty': 1}) == '5 шт. (под заказ)'


def test_safe_url_allows_only_web_links():
    assert f.safe_url('https://www.salvats.lv/x') == 'https://www.salvats.lv/x'
    assert f.safe_url('http://a.example') == 'http://a.example'
    assert f.safe_url('javascript:alert(1)') == '#' and f.safe_url('data:text/html,x') == '#' and f.safe_url(None) == '#'


def test_part_link_quotes_the_key():
    assert f.part_link('FDB5800') == '/part/FDB5800'
    assert f.part_link('semikom:123') == '/part/semikom%3A123'
    assert f.part_link('A/B C') == '/part/A%2FB%20C'
