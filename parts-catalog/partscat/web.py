"""The pages: search, part card, BOM check, collecting. Local use only (the server listens on 127.0.0.1)."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import format as fmt
from .analogs import KIND_POOL, VERDICTS, analogs_for_mpn, find_analogs, spec_for_line
from .bom import Bom, check_bom, export_rows, find_bom_dir, load_bom
from .crawler import Crawler
from .db import Database
from .http import Client
from .pricing import availability, cost_for
from .search import cheapest_for, explain, search
from .shops import SHOP_CLASSES

APP_DIR = Path(__file__).resolve().parent
SHOP_CHOICES = [(cls.key, cls.name) for cls in SHOP_CLASSES]
SHOP_NOTES = {cls.key: (cls.why_no_search or 'есть поиск по сайту') for cls in SHOP_CLASSES}
SPARK_W, SPARK_H = 120, 28


def spark(history: list[dict]) -> dict | None:
    """Points of a tiny price line for the part card: {'points', 'first', 'last'}; None below two points."""
    prices = [(row['at'], row['unit_price']) for row in history if row['unit_price'] is not None]
    if len(prices) < 2:
        return None
    values = [p for _, p in prices]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    step = SPARK_W / (len(prices) - 1)
    points = ' '.join(f'{i * step:.1f},{SPARK_H - 3 - (p - low) / span * (SPARK_H - 6):.1f}' for i, (_, p) in enumerate(prices))
    return dict(points=points, first=prices[0], last=prices[-1], low=low, high=high)


def create_app(data_dir: str | Path, *, bom_dir: str | Path | None = None, client: Client | None = None,
               crawler: Crawler | None = None) -> FastAPI:
    data_dir = Path(data_dir)
    db = Database(data_dir / 'catalog.db')
    db.close_stale_runs()
    client = client or Client(cache_dir=data_dir / 'cache')
    crawler = crawler or Crawler(db, client, bom_dir=bom_dir)
    bom_cache: dict = {}

    app = FastAPI(title='Каталог деталей', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
    app.mount('/static', StaticFiles(directory=APP_DIR / 'static'), name='static')
    templates = Jinja2Templates(directory=APP_DIR / 'templates')
    templates.env.filters.update(money=fmt.money, unit_money=fmt.unit_money, ago=fmt.ago, stock=fmt.stock_text,
                                 safe_url=fmt.safe_url, percent=fmt.signed_percent, partlink=fmt.part_link, quote=lambda s: quote(s, safe=''))
    templates.env.globals.update(shop_choices=SHOP_CHOICES, shop_notes=SHOP_NOTES, verdicts=VERDICTS,
                                 running=lambda: crawler.running)

    app.state.db, app.state.crawler, app.state.client = db, crawler, client

    # ---- helpers ---------------------------------------------------------------------------------

    def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context, status_code=status_code)

    async def form(request: Request) -> dict[str, list[str]]:
        """urlencoded POST body; parsed by hand so that python-multipart is not needed."""
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            raise PermissionError('чужой источник запроса')
        return parse_qs((await request.body()).decode('utf-8', 'replace'), keep_blank_values=True)

    def one(data: dict, key: str, default: str = '') -> str:
        return (data.get(key) or [default])[0].strip()

    def number(text: str, default: int, low: int = 1, high: int = 100000) -> int:
        try:
            return min(max(int(float(text.replace(',', '.'))), low), high)
        except ValueError:
            return default

    def current_bom() -> tuple[Bom | None, Path | None]:
        folder = Path(bom_dir) if bom_dir else find_bom_dir()
        if folder is None or not (folder / 'BOM_allocated.csv').is_file():
            return None, folder
        stamp = tuple((folder / name).stat().st_mtime_ns if (folder / name).exists() else 0
                      for name in ('BOM_allocated.csv', 'BOM_allocated.json', 'design.json'))
        if bom_cache.get('stamp') != (folder, stamp):
            bom_cache.update(stamp=(folder, stamp), bom=load_bom(folder))
        return bom_cache['bom'], folder

    def progress_response(request: Request, status_code: int = 200) -> HTMLResponse:
        return render(request, '_progress.html', status_code=status_code, progress=crawler.snapshot())

    def go(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    # ---- search ----------------------------------------------------------------------------------

    @app.get('/', response_class=HTMLResponse)
    def index(request: Request):
        params = request.query_params
        text = params.get('q', '').strip()
        shops = [s for s in params.getlist('shop') if s in dict(SHOP_CHOICES)]
        in_stock = params.get('stock') == '1'
        qty = number(params.get('qty', ''), 0, 0, 1000000)
        limit = number(params.get('limit', ''), 40, 10, 400)
        sort = params.get('sort', 'relevance')
        result = search(db, text, shops=shops or None, in_stock=in_stock, limit=limit) if text else None
        rows = []
        if result:
            groups = sorted(result.groups, key=lambda g: g.best['unit_price'] if g.best else 1e9) if sort == 'price' else result.groups
            for group in groups:
                best = cheapest_for(group, qty) if qty else group.best
                rows.append(dict(group=group, best=best, offers=[
                    dict(offer=o, cost=cost_for(o, qty) if qty else None, status=availability(o, qty or 1)) for o in group.offers]))
        return render(request, 'search.html', q=text, shops_selected=shops, in_stock=in_stock, qty=qty or '', limit=limit, sort=sort,
                      result=result, rows=rows, chips=explain(result.query) if result else [], progress=crawler.snapshot(),
                      stats=db.stats(), page='search')

    # ---- one part --------------------------------------------------------------------------------

    @app.get('/part/{key:path}', response_class=HTMLResponse)
    def part(request: Request, key: str):
        if ':' in key and not db.by_mpn(key):
            shop, _, shop_id = key.partition(':')
            found = db.find(shop, shop_id)
            offers = [found] if found else []
        else:
            offers = db.by_mpn(key)
        if not offers:
            return render(request, 'part.html', status_code=404, key=key, offers=[], page='search', stats=db.stats())
        merged: dict = {}
        for offer in sorted(offers, key=lambda o: len(o['params'])):
            merged.update(offer['params'])
        entries = [dict(offer=o, history=spark(db.history(o['id'])), watched=o['url'] in {w['url'] for w in db.watch_list()}) for o in
                   sorted(offers, key=lambda o: (o['stock_state'] == 'out', o['unit_price'] if o['unit_price'] is not None else 1e9))]
        return render(request, 'part.html', key=key, offers=offers, entries=entries, params=merged, page='search', stats=db.stats(),
                      mpn=next((o['mpn'] for o in offers if o['mpn']), None) or offers[0]['title'])

    @app.get('/analogs', response_class=HTMLResponse)
    def analogs(request: Request):
        params = request.query_params
        include_no = params.get('all') == '1'
        in_stock = params.get('stock') == '1'
        spec, found, reference = None, [], params.get('mpn', '')
        line_key = params.get('line')
        if line_key:
            bom, _ = current_bom()
            line = next((l for l in bom.lines if l.key == line_key), None) if bom else None
            spec = spec_for_line(db, line) if line else None
            reference = line.mpn if line else line_key
            if spec:
                found = find_analogs(db, spec, include_no=include_no, in_stock=in_stock)
        elif reference:
            spec, found = analogs_for_mpn(db, reference, include_no=include_no, in_stock=in_stock)
        unread = []
        for analog in found:
            if analog.open:
                unread.extend(o['id'] for o in analog.group.offers if not o['detail_at'] and o['stock_state'] != 'out')
        base = {'line': line_key} if line_key else {'mpn': reference}
        toggle = '/analogs?' + urlencode({**base, **({} if include_no else {'all': '1'}), **({'stock': '1'} if in_stock else {})})
        return render(request, '_analogs.html', spec=spec, analogs=found, reference=reference, include_no=include_no,
                      in_stock=in_stock, toggle=toggle, unread=unread[:12])

    # ---- BOM -------------------------------------------------------------------------------------

    @app.get('/bom', response_class=HTMLResponse)
    def bom_page(request: Request):
        bom, folder = current_bom()
        if bom is None:
            return render(request, 'bom.html', bom=None, folder=folder, page='bom', stats=db.stats(), progress=crawler.snapshot())
        report = check_bom(db, bom)
        level = request.query_params.get('level', 'all')
        needle = request.query_params.get('q', '').strip().lower()
        checks = [c for c in report.checks if (level == 'all' or c.level == level) and
                  (not needle or needle in c.line.mpn.lower() or needle in ' '.join(c.line.refs).lower() or needle in c.line.block.lower())]
        analog_lines = set()
        for c in checks:                                    # an analogs link only where the comparison has something to compare
            spec = None if c.line.accessory else spec_for_line(db, c.line)
            if spec is not None and spec.kind in KIND_POOL:
                analog_lines.add(c.line.key)
        return render(request, 'bom.html', bom=bom, folder=folder, report=report, checks=checks, level=level, q=request.query_params.get('q', ''),
                      analog_lines=analog_lines, page='bom', stats=db.stats(), progress=crawler.snapshot())

    @app.get('/bom.csv')
    def bom_csv():
        bom, _ = current_bom()
        if bom is None:
            return Response('BOM не найден', status_code=404, media_type='text/plain; charset=utf-8')
        rows = export_rows(check_bom(db, bom))
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]) if rows else ['Статус'], delimiter=';')
        writer.writeheader()
        writer.writerows(rows)
        return Response('﻿' + buffer.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="bom_check.csv"'})

    # ---- collecting ------------------------------------------------------------------------------

    @app.get('/crawl', response_class=HTMLResponse)
    def crawl_page(request: Request):
        return render(request, 'crawl.html', progress=crawler.snapshot(), stats=db.stats(), runs=db.recent_runs(8),
                      watch=db.watch_list(), page='crawl', notice=request.query_params.get('notice', ''))

    @app.get('/crawl/status', response_class=HTMLResponse)
    def crawl_status(request: Request):
        return progress_response(request)

    @app.post('/crawl/start')
    async def crawl_start(request: Request):
        try:
            data = await form(request)
        except PermissionError as error:
            return Response(str(error), status_code=403, media_type='text/plain; charset=utf-8')
        kind = one(data, 'kind')
        plan: dict = {'kind': kind}
        if kind == 'search':
            plan.update(query=one(data, 'query'), shops=data.get('shop') or None, enrich=number(one(data, 'enrich', '4'), 4, 0, 30))
        elif kind == 'sweep':
            plan.update(shop=one(data, 'shop'), match=one(data, 'match'), max_pages=number(one(data, 'max_pages', '40'), 40, 1, 400))
        elif kind == 'enrich':
            ids = [int(x) for x in one(data, 'ids').replace(',', ' ').split() if x.isdigit()][:40]
            plan.update(limit=number(one(data, 'limit', '30'), 30, 1, 500), ids=ids or None)
        elif kind == 'urls':
            plan.update(urls=[u for u in one(data, 'urls').replace(',', '\n').split() if u], watch='unwatch' not in data)
        elif kind not in ('bom', 'watch', 'doctor'):
            return Response('неизвестный план', status_code=400, media_type='text/plain; charset=utf-8')
        started = crawler.start(plan)
        if request.headers.get('hx-request'):
            return progress_response(request)
        return go('/crawl' + ('' if started else '?notice=busy'))

    @app.post('/crawl/stop')
    async def crawl_stop(request: Request):
        try:
            await form(request)
        except PermissionError as error:
            return Response(str(error), status_code=403, media_type='text/plain; charset=utf-8')
        crawler.stop()
        if request.headers.get('hx-request'):
            return progress_response(request)
        return go('/crawl')

    @app.post('/crawl/watch')
    async def crawl_watch(request: Request):
        try:
            data = await form(request)
        except PermissionError as error:
            return Response(str(error), status_code=403, media_type='text/plain; charset=utf-8')
        url = one(data, 'url')
        if one(data, 'action') == 'remove':
            db.watch_remove(url)
        elif url:
            from .shops import shop_for_url
            shop = shop_for_url(crawler.shops, url)
            if shop is None:
                return go('/crawl?notice=foreign')
            db.watch_add(url, shop.key)
        return go(one(data, 'next') if one(data, 'next').startswith('/') else '/crawl')

    # ---- misc ------------------------------------------------------------------------------------

    @app.get('/export/offers.csv')
    def export_offers():
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=';')
        writer.writerow(['shop', 'shop_id', 'mpn', 'title', 'brand', 'category', 'kind', 'package', 'sale_price_eur', 'pack_qty',
                         'unit_price_eur', 'stock_qty', 'stock_state', 'last_seen', 'url'])
        for row in db.rows_for_export():
            writer.writerow([row['shop'], row['shop_id'], row['mpn'], row['title'], row['brand'], row['category'], row['kind'], row['pkg'],
                             row['sale_price'], row['pack_qty'], row['unit_price'], row['stock_qty'], row['stock_state'], row['last_seen'],
                             row['url']])
        return Response('﻿' + buffer.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="offers.csv"'})

    @app.get('/health')
    def health():
        stats = db.stats()
        bom, _ = current_bom()
        return JSONResponse(dict(ok=True, offers=stats['total'], with_mpn=stats['with_mpn'], bom_lines=len(bom.lines) if bom else None,
                                 crawling=crawler.running))

    return app
