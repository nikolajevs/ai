"""Self-check for the first start: libraries, data, BOM, and one polite look at every shop.

Per shop it makes at most three requests (robots.txt, one product page read with the real parser, one search where
the shop allows it) and says what came back, so a ban, a proxy block or a changed page layout shows up here and
not in the middle of a long crawl.
"""
from __future__ import annotations

import importlib
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .bom import find_bom_dir, load_bom
from .db import Database
from .http import Client, FetchError
from .robots import Rules
from .shops import all_shops
from .shops.base import Shop, Unsupported

LIBRARIES = ('fastapi', 'uvicorn', 'jinja2', 'requests', 'bs4')
SAMPLES = {      # product pages that exist; used when the BOM has no page of that shop
    'salvats': 'https://www.salvats.lv/lv/100v-n-fet-tht/22e10n-tranzistors-n-fet-100v-20v-22a-72w-0r0115-to-220',
    'electrobase': 'https://electrobase.lv/katalogs/led-draiveri/ic-driver-boostbuck-boost-led-driver-htssop14-5a-372v-ch-1',
    'semikom': 'https://www.semikom.lv/transistor-n-mosfet-unipolar-60v-120a-306w-d2pak-sot404.387067.p',
    'lemona': 'https://www.lemona.lv/sprieguma-stabilizators-l7815cv-to220.html',
}
SEARCH_SAMPLE = 'FDB5800'


@dataclass
class Line:
    status: str          # ok / warn / fail
    title: str
    detail: str = ''

    def text(self) -> str:
        mark = {'ok': '[ ok ]', 'warn': '[ !! ]', 'fail': '[FAIL]'}[self.status]
        return f'{mark} {self.title}' + (f': {self.detail}' if self.detail else '')


def environment() -> list[Line]:
    lines = [Line('ok' if sys.version_info >= (3, 10) else 'fail', 'Python', f'{platform.python_version()} ({sys.executable})')]
    for name in LIBRARIES:
        try:
            module = importlib.import_module(name)
            lines.append(Line('ok', f'библиотека {name}', getattr(module, '__version__', '')))
        except ImportError:
            lines.append(Line('fail', f'библиотека {name}', 'не установлена: python -m pip install -r requirements.txt'))
    return lines


def data(data_dir: Path) -> list[Line]:
    path = data_dir / 'catalog.db'
    try:
        stats = Database(path).stats()
    except Exception as error:                    # an unreadable file is the finding, not a crash
        return [Line('fail', f'база {path}', f'{type(error).__name__}: {error}')]
    if not stats['total']:
        return [Line('warn', f'база {path}', 'пуста: страница «Сбор» → «Обновить позиции BOM»')]
    return [Line('ok', f'база {path}', f"{stats['total']} предложений, артикул известен у {stats['with_mpn']}")]


def bom(bom_dir) -> tuple[list[Line], object]:
    folder = Path(bom_dir) if bom_dir else find_bom_dir()
    if folder is None or not (folder / 'BOM_allocated.csv').is_file():
        return [Line('warn', 'BOM', 'не найден (PARTSCAT_BOM_DIR, папка bom рядом с run.py или ../hardware/PCB_EU)')], None
    loaded = load_bom(folder)
    with_pages = sum(1 for line in loaded.lines if line.shop and line.url)
    return [Line('ok', f'BOM {folder}', f'{len(loaded.lines)} строк, из них со страницей магазина {with_pages}, ревизия {loaded.revision or "?"}')], loaded


def _sample_url(shop: Shop, loaded) -> str:
    if loaded is not None:
        for line in loaded.lines:
            if line.shop == shop.key and line.url and shop.owns(line.url):
                return line.url
    return SAMPLES.get(shop.key, '')


def _robots_line(client: Client, shop: Shop) -> Line:
    try:
        reply = client.get(f'https://{shop.host}/robots.txt', check_robots=False, ttl_hours=0)
    except FetchError as error:
        return Line('fail', f'{shop.name}: robots.txt', f'{error.kind}: {error}')
    rules = Rules(reply.text)
    allowed = rules.allowed(f'https://{shop.host}/')
    return Line('ok' if allowed else 'warn', f'{shop.name}: robots.txt', f"получен, {len(reply.text)} байт, главная страница {'разрешена' if allowed else 'ЗАПРЕЩЕНА'}")


def _product_line(shop: Shop, url: str) -> Line:
    if not url:
        return Line('warn', f'{shop.name}: страница товара', 'нет образца')
    try:
        offer = shop.product(url)
    except FetchError as error:
        return Line('fail', f'{shop.name}: страница товара', f'{error.kind}: {error} ({url})')
    except Exception as error:                    # a layout the parser does not know
        return Line('fail', f'{shop.name}: страница товара', f'разбор не удался, вероятно изменилась вёрстка: {type(error).__name__}: {error}')
    problems = [name for name, value in (('название', offer.title), ('цена', offer.sale_price)) if not value]
    detail = f"{offer.title[:60]} | артикул {offer.mpn or '—'} | {offer.sale_price if offer.sale_price is not None else '—'} € | остаток {offer.stock_qty if offer.stock_qty is not None else offer.stock_state}"
    if problems:
        return Line('fail', f'{shop.name}: страница товара', f"не прочиталось: {', '.join(problems)}; {detail}")
    return Line('ok', f'{shop.name}: страница товара', detail)


def _search_line(shop: Shop) -> Line | None:
    if not shop.can_search:
        return Line('ok', f'{shop.name}: поиск', 'не используется — ' + shop.why_no_search)
    try:
        listing = shop.search(SEARCH_SAMPLE)
    except Unsupported as error:
        return Line('ok', f'{shop.name}: поиск', str(error))
    except FetchError as error:
        return Line('fail', f'{shop.name}: поиск', f'{error.kind}: {error}')
    except Exception as error:
        return Line('fail', f'{shop.name}: поиск', f'разбор не удался: {type(error).__name__}: {error}')
    if not listing.offers:
        return Line('warn', f'{shop.name}: поиск «{SEARCH_SAMPLE}»', 'страница получена, но карточек не найдено (вёрстка могла измениться)')
    return Line('ok', f'{shop.name}: поиск «{SEARCH_SAMPLE}»', f'{len(listing.offers)} карточек, первая: {listing.offers[0].title[:60]}')


def shops(client: Client, loaded, only: list[str] | None = None, emit: Callable[[Line], None] | None = None,
          adapters: dict[str, Shop] | None = None) -> list[Line]:
    """Look at every shop politely; a shop that answers with a ban or a block is not asked again."""
    lines: list[Line] = []
    saved_ttl = client.ttl
    client.ttl = 0.0                              # a check must see the shop as it is now
    try:
        for key, shop in (adapters if adapters is not None else all_shops(client)).items():
            if only and key not in only:
                continue
            checks = [_robots_line(client, shop)]
            if checks[0].status != 'fail':
                checks.append(_product_line(shop, _sample_url(shop, loaded)))
                if checks[-1].status != 'fail' or 'banned' not in checks[-1].detail:
                    search = _search_line(shop)
                    if search:
                        checks.append(search)
            for line in checks:
                lines.append(line)
                if emit:
                    emit(line)
    finally:
        client.ttl = saved_ttl
    return lines
