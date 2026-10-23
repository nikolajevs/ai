"""Display helpers for the pages and the terminal: money, quantities, dates, stock, links."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from .pricing import stock_pieces

SHOP_LABELS = {'salvats': 'Salvats', 'electrobase': 'Electrobase', 'semikom': 'Semikom', 'lemona': 'Lemona'}


def money(value: float | None, digits: int = 2) -> str:
    """1.98 -> '1,98 €'."""
    if value is None:
        return '—'
    return f'{value:.{digits}f} €'.replace('.', ',')


def unit_money(value: float | None) -> str:
    """Price of one piece: cents for dear parts, more digits for cheap ones (0.0649 -> '0,0649 €')."""
    if value is None:
        return '—'
    digits = 2 if value >= 1 else 3 if value >= 0.1 else 4
    text = f'{value:.{digits}f}'
    while digits > 2 and text.endswith('0'):
        text, digits = text[:-1], digits - 1
    return f'{text} €'.replace('.', ',')


def signed_percent(old: float | None, new: float | None) -> str:
    if not old or new is None:
        return ''
    value = round((new - old) / old * 100)
    return f'{value:+d} %' if value else ''


def ago(timestamp: str | None, now: datetime | None = None) -> str:
    if not timestamp:
        return 'никогда'
    then = datetime.strptime(timestamp[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    seconds = ((now or datetime.now(timezone.utc)) - then).total_seconds()
    if seconds < 3600:
        return 'только что' if seconds < 120 else f'{int(seconds // 60)} мин. назад'
    if seconds < 86400:
        return f'{int(seconds // 3600)} ч. назад'
    days = int(seconds // 86400)
    if days == 1:
        return 'вчера'
    if days < 60:
        return f'{days} дн. назад'
    return f'{days // 30} мес. назад'


def stock_text(offer: dict) -> str:
    """'285 шт.', '>1000 шт.', '38 уп. (380 шт.)', 'нет в наличии', 'под заказ', 'неизвестно'."""
    state = offer.get('stock_state')
    if state == 'out':
        return 'нет в наличии'
    qty = offer.get('stock_qty')
    pack = max(int(offer.get('pack_qty') or 1), 1)
    if qty is None:
        return 'под заказ' if state == 'order' else 'в наличии' if state == 'in' else 'неизвестно'
    mark = '>' if offer.get('stock_atleast') else ''
    suffix = ' (под заказ)' if state == 'order' else ''
    if pack > 1:
        return f'{mark}{qty} уп. ({mark}{stock_pieces(offer)} шт.){suffix}'
    return f'{mark}{qty} шт.{suffix}'


def safe_url(url: str | None) -> str:
    """Shop pages only link out over http(s); anything else (javascript:, data:) becomes '#'."""
    url = (url or '').strip()
    return url if url.lower().startswith(('https://', 'http://')) else '#'


def part_link(key: str) -> str:
    return '/part/' + quote(key, safe='')


def pack_label(offer: dict) -> str:
    pack = max(int(offer.get('pack_qty') or 1), 1)
    return f'упаковка {pack} шт.' if pack > 1 else ''
