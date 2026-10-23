"""Collecting offers from the shops: what to fetch, in which order, and what to show while it runs.

A plan is a dict with a 'kind':

  bom      refresh the page of every BOM line, plus the watch list
  watch    refresh the watch list only
  urls     read the given product pages (and keep them on the watch list)
  search   ask the shops that allow a text search (Salvats, Semikom), then read some product pages for part numbers
  sweep    read the listings of a shop's categories ({'shop', 'match', 'max_pages'}); the way Electrobase is read
  enrich   read product pages of offers whose part number is still unknown ({'limit', 'kinds', 'shops', 'ids'})
  doctor   check the connection to each shop (the page version of `run.py doctor`); stores nothing

One plan runs at a time. Every fetch goes through the polite client; a shop that bans, blocks or keeps failing is
left alone for the rest of the run and the reason is shown, never swallowed. A stopped or crashed run keeps
what it stored, and a rerun is cheap because the client caches pages on disk.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import doctor
from .bom import find_bom_dir, load_bom, watch_urls
from .db import Database, now_iso
from .http import Client, FetchError
from .models import Offer
from .normalize import fold
from .shops import all_shops, shop_for_url
from .shops.base import Shop, Unsupported

PLAN_TITLES = {
    'bom': 'Обновить позиции BOM', 'watch': 'Обновить список наблюдения', 'urls': 'Прочитать страницы товаров',
    'search': 'Спросить магазины', 'sweep': 'Обойти разделы магазина', 'enrich': 'Узнать артикулы',
    'doctor': 'Проверить связь с магазинами',
}
NETWORK_STREAK = 4          # consecutive network errors before a shop is left alone for the run


class Stopped(Exception):
    pass


@dataclass
class Progress:
    plan: dict = field(default_factory=dict)
    title: str = ''
    state: str = 'idle'                      # idle / running / done / stopped / failed
    step: str = ''
    done: int = 0
    total: int | None = None
    counts: dict = field(default_factory=lambda: dict(new=0, changed=0, same=0, errors=0, pages=0))
    log: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    skipped: dict = field(default_factory=dict)          # shop -> why it was left alone
    started: str | None = None
    finished: str | None = None

    def as_dict(self) -> dict:
        return dict(plan=self.plan, title=self.title, state=self.state, step=self.step, done=self.done, total=self.total,
                    counts=dict(self.counts), log=list(self.log[-60:]), errors=list(self.errors[-30:]),
                    skipped=dict(self.skipped), started=self.started, finished=self.finished)


class Crawler:
    def __init__(self, db: Database, client: Client, shops: dict[str, Shop] | None = None, *, bom_dir=None,
                 on_log: Callable[[str], None] | None = None):
        self.db, self.client = db, client
        self.shops = shops if shops is not None else all_shops(client)
        self.bom_dir = bom_dir
        self.on_log = on_log
        self.echo_steps = False                  # the command line prints every step, the web page shows the current one
        self.progress = Progress()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._streak: dict[str, int] = {}

    # ---- control -------------------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> dict:
        with self._lock:
            return self.progress.as_dict()

    def start(self, plan: dict) -> bool:
        """Run a plan in the background; False when another one is still running."""
        with self._lock:
            if self.running:
                return False
            self.progress = Progress(plan=plan, title=self._title(plan), state='running', started=now_iso())
            self._thread = threading.Thread(target=self._run, args=(plan,), daemon=True, name='crawler')
            self._thread.start()
        return True

    def stop(self) -> None:
        self.client.stop_event.set()

    def run(self, plan: dict) -> dict:
        """Run a plan in this thread (the command line)."""
        with self._lock:
            self.progress = Progress(plan=plan, title=self._title(plan), state='running', started=now_iso())
        self._run(plan)
        return self.snapshot()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # ---- one run -------------------------------------------------------------------------------------

    @staticmethod
    def _title(plan: dict) -> str:
        title = PLAN_TITLES.get(plan.get('kind'), str(plan.get('kind')))
        detail = plan.get('query') or plan.get('shop') or ''
        return f'{title}: {detail}' if detail else title

    def _run(self, plan: dict) -> None:
        self.client.stop_event.clear()
        self._streak = {}
        run_id = self.db.start_run(self.progress.title)
        fresh = plan.get('fresh', plan.get('kind') in ('bom', 'watch', 'urls', 'search', 'enrich'))
        saved_ttl = getattr(self.client, 'ttl', None)
        if fresh and saved_ttl is not None:
            self.client.ttl = 0.0                      # product pages of a refresh must be read, not remembered
        state = 'done'
        try:
            handler = getattr(self, f"_plan_{plan.get('kind')}", None)
            if handler is None:
                raise ValueError(f"неизвестный план: {plan.get('kind')}")
            handler(plan)
            if self.client.stop_event.is_set():
                state = 'stopped'
        except Stopped:
            state = 'stopped'
        except KeyboardInterrupt:
            state = 'stopped'
            raise
        except Exception as error:                     # a bug must reach the screen, not vanish in a thread
            state = 'failed'
            self._log(f'ошибка: {type(error).__name__}: {error}')
            self.progress.errors.append(dict(kind='internal', message=f'{type(error).__name__}: {error}', url='', status=None))
        finally:
            if saved_ttl is not None:
                self.client.ttl = saved_ttl
            with self._lock:
                self.progress.state = state
                self.progress.step = ''
                self.progress.finished = now_iso()
            self.db.finish_run(run_id, state, dict(self.progress.counts), self.progress.errors)

    def _log(self, text: str) -> None:
        with self._lock:
            self.progress.log.append(text)
            del self.progress.log[:-300]
        if self.on_log:
            self.on_log(text)

    def _step(self, text: str, done: int | None = None, total: int | None = None) -> None:
        if self.client.stop_event.is_set():
            raise Stopped
        with self._lock:
            changed = text != self.progress.step
            self.progress.step = text
            if done is not None:
                self.progress.done = done
            if total is not None:
                self.progress.total = total
        if self.echo_steps and self.on_log and changed:
            self.on_log(text)

    def _store(self, offer: Offer) -> int:
        offer_id, status = self.db.upsert(offer)
        with self._lock:
            self.progress.counts[status] += 1
        return offer_id

    def _call(self, shop: Shop, what: str, function: Callable, *args, **kwargs):
        """One fetch of a shop; None after recording the failure. A shop that bans or keeps failing is skipped."""
        if shop.key in self.progress.skipped:
            return None
        try:
            result = function(*args, **kwargs)
            self._streak[shop.key] = 0
            with self._lock:
                self.progress.counts['pages'] += 1
            return result
        except FetchError as error:
            if error.kind == 'stopped':
                raise Stopped
            self._record(shop, what, error)
            if error.kind in ('banned', 'blocked'):
                self._skip(shop, f'{shop.name}: {error}')
            elif error.kind == 'network':
                self._streak[shop.key] = self._streak.get(shop.key, 0) + 1
                if self._streak[shop.key] >= NETWORK_STREAK:
                    self._skip(shop, f'{shop.name}: {NETWORK_STREAK} сетевых ошибок подряд')
            return None
        except Unsupported as error:
            self._log(str(error))
            self._skip(shop, str(error))
            return None

    def _record(self, shop: Shop, what: str, error: FetchError) -> None:
        entry = error.as_dict()
        entry.update(shop=shop.key, what=what)
        with self._lock:
            self.progress.counts['errors'] += 1
            self.progress.errors.append(entry)
        self._log(f'{shop.name}: {what}: {error}')

    def _skip(self, shop: Shop, why: str) -> None:
        with self._lock:
            self.progress.skipped[shop.key] = why
        self._log(f'{shop.name} пропущен до конца запуска')

    # ---- plans ---------------------------------------------------------------------------------------

    def _fetchable(self, shop: Shop, url: str) -> bool:
        """Only pages of the shop's own site are fetched, wherever the address came from (a card link may point elsewhere)."""
        if shop.owns(url) or (shop.key == 'lemona' and url.strip().lower().startswith('lemona:')):
            return True
        self._log(f'{shop.name}: адрес не с сайта магазина, пропущен: {url[:120]}')
        return False

    def _read_pages(self, targets: list[tuple[str, str]]) -> None:
        total = len(targets)
        for number, (shop_key, url) in enumerate(targets, 1):
            shop = self.shops.get(shop_key)
            self._step(f'{number} из {total}: {url.rsplit("/", 1)[-1][:60]}', number - 1, total)
            if shop is None:
                self._log(f'нет адаптера магазина «{shop_key}» для {url}')
                continue
            if not self._fetchable(shop, url):
                continue
            offer = self._call(shop, url, shop.product, url)
            if offer is not None:
                self._store(offer)
        with self._lock:
            self.progress.done = total

    def _watch_targets(self) -> list[tuple[str, str]]:
        return [(row['shop'], row['url']) for row in self.db.watch_list()]

    def _plan_bom(self, plan: dict) -> None:
        folder = plan.get('bom_dir') or self.bom_dir or find_bom_dir()
        if folder is None:
            raise ValueError('не найден BOM_allocated.csv (папка bom рядом с программой или hardware/PCB_EU в репозитории)')
        targets = list(dict.fromkeys([*watch_urls(load_bom(folder)), *self._watch_targets()]))
        self._log(f'BOM: {len(targets)} страниц')
        self._read_pages(targets)

    def _plan_watch(self, plan: dict) -> None:
        targets = self._watch_targets()
        self._log(f'список наблюдения: {len(targets)} страниц')
        self._read_pages(targets)

    def _plan_urls(self, plan: dict) -> None:
        targets = []
        for url in plan.get('urls') or []:
            url = url.strip()
            shop = shop_for_url(self.shops, url) if url else None
            if url and shop is None:
                self._log(f'адрес не относится к магазинам каталога: {url}')
            elif shop is not None:
                targets.append((shop.key, url))
                if plan.get('watch', True):
                    self.db.watch_add(url, shop.key)
        self._read_pages(targets)

    def _plan_search(self, plan: dict) -> None:
        query = (plan.get('query') or '').strip()
        if not query:
            raise ValueError('пустой запрос')
        wanted = plan.get('shops') or list(self.shops)
        shops = [self.shops[key] for key in wanted if key in self.shops and self.shops[key].can_search]
        for key in wanted:
            if key in self.shops and not self.shops[key].can_search:
                self._log(f'{self.shops[key].name}: {self.shops[key].why_no_search}')
        # the other shops cannot be asked: refresh what is already known about the part number
        known = [(o['shop'], o['url']) for o in self.db.by_mpn(query)
                 if o['shop'] in wanted and o['shop'] in self.shops and not self.shops[o['shop']].can_search]
        fresh_ids: list[int] = []
        pages = max(int(plan.get('pages') or 1), 1)
        steps = len(shops) * pages + len(known)
        done = 0
        for shop in shops:
            for page in range(1, pages + 1):
                self._step(f'{shop.name}: поиск «{query}», стр. {page}', done, steps)
                listing = self._call(shop, f'поиск «{query}»', shop.search, query, page)
                done += 1
                if listing is None:
                    break
                fresh_ids.extend(self._store(offer) for offer in listing.offers)
                if not listing.has_next:
                    break
        for shop_key, url in known:
            self._step(f'{self.shops[shop_key].name}: {url.rsplit("/", 1)[-1][:50]}', done, steps)
            done += 1
            if not self._fetchable(self.shops[shop_key], url):
                continue
            offer = self._call(self.shops[shop_key], url, self.shops[shop_key].product, url)
            if offer is not None:
                self._store(offer)
        limit = int(plan.get('enrich', 4))
        if limit and fresh_ids:
            self._enrich(self.db.without_detail(ids=fresh_ids, limit=limit))

    def _plan_enrich(self, plan: dict) -> None:
        rows = self.db.without_detail(shops=plan.get('shops'), kinds=plan.get('kinds'), ids=plan.get('ids'),
                                      limit=int(plan.get('limit') or 30))
        self._enrich(rows)

    def _enrich(self, rows: list[dict]) -> None:
        total = len(rows)
        self._log(f'артикулы: читаю {total} карточек')
        for number, row in enumerate(rows, 1):
            shop = self.shops.get(row['shop'])
            self._step(f"{number} из {total}: {row['title'][:60]}", number - 1, total)
            if shop is None or not self._fetchable(shop, row['url']):
                continue
            offer = self._call(shop, row['url'], shop.product, row['url'])
            if offer is not None:
                self._store(offer)
        with self._lock:
            self.progress.done = total

    def _plan_doctor(self, plan: dict) -> None:
        """Three polite requests per shop (robots.txt, one product page, one search); every result line goes to the log."""
        folder = self.bom_dir or find_bom_dir()
        loaded = load_bom(folder) if folder and (Path(folder) / 'BOM_allocated.csv').is_file() else None
        wanted = [key for key in (plan.get('shops') or self.shops) if key in self.shops]
        for number, key in enumerate(wanted):
            self._step(f'{self.shops[key].name}: проверка связи', number, len(wanted))
            doctor.shops(self.client, loaded, only=[key], emit=self._doctor_line, adapters=self.shops)
        with self._lock:
            self.progress.done = len(wanted)

    def _doctor_line(self, line: doctor.Line) -> None:
        if self.client.stop_event.is_set():              # after «Остановить» every request fails with 'stopped'; that is not a finding
            return
        self._log(line.text())
        if line.status == 'fail':
            with self._lock:
                self.progress.counts['errors'] += 1
                self.progress.errors.append(dict(kind='check', shop=line.title.split(':', 1)[0].lower(), what=line.title,
                                                 message=line.detail or line.title, url='', status=None))

    def _plan_sweep(self, plan: dict) -> None:
        shop = self.shops.get(plan.get('shop'))
        if shop is None:
            raise ValueError(f"неизвестный магазин: {plan.get('shop')}")
        match = fold(plan.get('match') or '')
        max_pages = max(int(plan.get('max_pages') or 40), 1)
        self._step(f'{shop.name}: список разделов')
        categories = self._call(shop, 'список разделов', shop.categories) or []
        parents = {c.parent for c in categories if c.parent}
        if match:
            categories = [c for c in categories if match in fold(c.title) or match in fold(c.url)]
        if plan.get('leaf_only', True):
            categories = [c for c in categories if c.url not in parents] or categories
        self._log(f'{shop.name}: разделов к обходу {len(categories)}')
        queue = deque(categories)
        seen: set[str] = set()
        done, total = 0, len(queue)
        while queue:
            category = queue.popleft()
            if category.url in seen:
                continue
            seen.add(category.url)
            for page in range(1, max_pages + 1):
                self._step(f'{shop.name}: {category.title}, стр. {page}', done, total)
                listing = self._call(shop, f'{category.title}, стр. {page}', shop.listing, category, page)
                if listing is None:
                    break
                for sub in listing.subcategories:
                    if sub.url not in seen:
                        queue.append(sub)
                        total += 1
                for offer in listing.offers:
                    self._store(offer)
                if not listing.has_next or not listing.offers:
                    break
            done += 1
        with self._lock:
            self.progress.done, self.progress.total = done, total
