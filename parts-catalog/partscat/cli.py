"""Command line: python run.py [serve | crawl | bom | search | analogs | doctor | export] ...

Without a command the web page is started and opened in the browser.
"""
from __future__ import annotations

import argparse
import csv
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from . import doctor as doctor_mod
from .analogs import analogs_for_mpn, find_analogs, spec_for_line
from .bom import check_bom, export_rows, find_bom_dir, load_bom
from .crawler import Crawler
from .db import Database
from .format import ago, money, stock_text, unit_money
from .http import Client
from .pricing import cost_for
from .search import cheapest_for, explain, search

ROOT = Path(__file__).resolve().parent.parent
LEVEL_LABEL = {'ok': 'ок', 'warn': 'проверить', 'bad': 'ПРОБЛЕМА', 'none': 'нет данных'}


def data_dir(args) -> Path:
    return Path(getattr(args, 'data', None) or os.environ.get('PARTSCAT_DATA') or ROOT / 'data')


def open_db(args) -> Database:
    db = Database(data_dir(args) / 'catalog.db')
    db.close_stale_runs()
    return db


def make_client(args) -> Client:
    return Client(cache_dir=data_dir(args) / 'cache')


def shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + '…'


# ---- commands -------------------------------------------------------------------------------------------

def cmd_serve(args) -> int:
    import uvicorn
    from .web import create_app
    port = args.port or int(os.environ.get('PARTSCAT_PORT', '8086'))
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            print(f'Порт {port} уже занят (возможно, каталог уже запущен: http://127.0.0.1:{port}). '
                  f'Другой порт: python run.py serve --port {port + 1}')
            return 1
    app = create_app(data_dir(args), bom_dir=args.bom)
    url = f'http://127.0.0.1:{port}'
    print(f'Каталог деталей запущен: {url}  (Ctrl+C — остановить)')
    print(f'Данные: {data_dir(args)}')
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
    return 0


def run_plan(args, plan: dict) -> int:
    db, client = open_db(args), make_client(args)
    crawler = Crawler(db, client, bom_dir=args.bom, on_log=print)
    crawler.echo_steps = True
    try:
        result = crawler.run(plan)
    except KeyboardInterrupt:
        print('\nПрервано. Уже прочитанное сохранено в базе.')
        return 130
    counts = result['counts']
    print(f"\n{result['title']}: {'готово' if result['state'] == 'done' else result['state']}. "
          f"Страниц {counts['pages']}, новых {counts['new']}, изменилось {counts['changed']}, без изменений {counts['same']}, ошибок {counts['errors']}.")
    for shop, why in result['skipped'].items():
        print(f'  пропущен: {why}')
    return 0 if result['state'] in ('done', 'stopped') else 1


def cmd_crawl(args) -> int:
    plans = {
        'bom': lambda: {'kind': 'bom'},
        'watch': lambda: {'kind': 'watch'},
        'urls': lambda: {'kind': 'urls', 'urls': args.urls, 'watch': not args.no_watch},
        'search': lambda: {'kind': 'search', 'query': ' '.join(args.query), 'shops': args.shop or None, 'pages': args.pages, 'enrich': args.enrich},
        'sweep': lambda: {'kind': 'sweep', 'shop': args.shop, 'match': args.match, 'max_pages': args.pages},
        'enrich': lambda: {'kind': 'enrich', 'limit': args.limit, 'shops': args.shop or None},
    }
    return run_plan(args, plans[args.plan]())


def cmd_bom(args) -> int:
    folder = Path(args.bom) if args.bom else find_bom_dir()
    if folder is None:
        print('BOM не найден: задайте --bom ПАПКА или PARTSCAT_BOM_DIR (папка с BOM_allocated.csv и design.json).')
        return 1
    db = open_db(args)
    bom = load_bom(folder)
    report = check_bom(db, bom)
    if args.csv:
        rows = export_rows(report)
        with open(args.csv, 'w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        print(f'Записано: {args.csv}')
    counts = report.counts()
    print(f"BOM {folder} ({bom.revision or '?'}): {len(bom.lines)} строк — ок {counts['ok']}, проверить {counts['warn']}, "
          f"проблем {counts['bad']}, нет данных {counts['none']}")
    print(f"Сумма в BOM {money(report.bom_total)}, сейчас по базе {money(report.now_total)} (обновлено строк {report.refreshed} из {len(bom.lines)})")
    if report.with_shipping:
        print(f"С доставкой по сводке BOM ({money(bom.shipping)}): {money(report.with_shipping[0])} → {money(report.with_shipping[1])}")
    print()
    shown = [c for c in report.checks if not args.level or c.level == args.level]
    for c in shown:
        if c.level == 'ok' and not args.all and not args.level:
            continue
        line = c.line
        print(f"{LEVEL_LABEL[c.level]:<10} {line.shop_label:<12} {shorten(line.mpn, 24):<24} {line.buy:>4} шт. "
              f"{money(line.price):>8} → {money(c.now_unit):>8}  {'; '.join(i.text for i in c.issues)}")
        if args.analogs and c.level != 'ok' and not line.accessory:
            spec = spec_for_line(db, line)
            for analog in (find_analogs(db, spec, limit=3) if spec else []):
                best = analog.group.best
                print(f"             ↳ {analog.label}: {analog.group.mpn or analog.group.title} "
                      f"{unit_money(best['unit_price']) if best else ''} {best['shop'] if best else ''}")
    if not args.all and not args.level:
        print(f"\n(строки «ок» не показаны: {counts['ok']}; ключ --all покажет всё)")
    return 0


def cmd_search(args) -> int:
    db = open_db(args)
    text = ' '.join(args.query)
    result = search(db, text, shops=args.shop or None, in_stock=args.in_stock, limit=args.limit)
    chips = explain(result.query)
    print(f"{result.note}" + (f"  [{' · '.join(chips)}]" if chips else ''))
    for group in result.groups:
        print(f"\n{group.mpn or group.title}  {group.summary}  {'; '.join(group.reasons)}")
        best = cheapest_for(group, args.qty) if args.qty else group.best
        for offer in group.offers:
            cost = cost_for(offer, args.qty) if args.qty else None
            extra = f"  на {args.qty} шт.: {money(cost['total'])}" if cost else ''
            mark = '*' if best is offer else ' '
            print(f" {mark} {offer['shop']:<12} {unit_money(offer['unit_price']):>9}  {stock_text(offer):<22} {ago(offer['last_seen']):<14}{extra}")
            print(f"     {offer['url']}")
    return 0


def cmd_analogs(args) -> int:
    db = open_db(args)
    spec, found = analogs_for_mpn(db, args.mpn, include_no=args.all, in_stock=args.in_stock, limit=args.limit)
    if spec is None:
        print(f'«{args.mpn}» нет в базе или такой тип деталей не сравнивается. Прочитайте страницу детали: python run.py crawl urls АДРЕС')
        return 1
    print(f'Сравнение с: {spec.title}' + (f' (корпус {spec.pkg})' if spec.pkg else ''))
    for analog in found:
        best = analog.group.best
        print(f"\n[{analog.label}] {analog.group.mpn or analog.group.title}  {analog.group.summary}"
              + (f"  — {best['shop']} {unit_money(best['unit_price'])}" if best else ''))
        if analog.reasons:
            print('   ' + '; '.join(analog.reasons))
    if not found:
        print('Подходящих аналогов в базе нет.')
    print('\nСравниваются только значения из названий и свойств магазинов; распиновку и нагрев проверяйте по даташиту.')
    return 0


def cmd_doctor(args) -> int:
    failed = 0

    def emit(line):
        nonlocal failed
        failed += line.status == 'fail'
        print(line.text(), flush=True)

    for line in doctor_mod.environment():
        emit(line)
    for line in doctor_mod.data(data_dir(args)):
        emit(line)
    lines, loaded = doctor_mod.bom(args.bom)
    for line in lines:
        emit(line)
    if not args.offline:
        print('\nМагазины (по три запроса на магазин, с паузами):')
        doctor_mod.shops(make_client(args), loaded, only=args.shop or None, emit=emit)
    print('\nГотово.' if not failed else f'\nПроблем: {failed}. Подробности выше.')
    return 1 if failed else 0


def cmd_export(args) -> int:
    db = open_db(args)
    with open(args.file, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle, delimiter=';')
        writer.writerow(['shop', 'shop_id', 'mpn', 'title', 'brand', 'category', 'kind', 'package', 'sale_price_eur', 'pack_qty',
                         'unit_price_eur', 'stock_qty', 'stock_state', 'last_seen', 'url'])
        count = 0
        for row in db.rows_for_export():
            writer.writerow([row['shop'], row['shop_id'], row['mpn'], row['title'], row['brand'], row['category'], row['kind'], row['pkg'],
                             row['sale_price'], row['pack_qty'], row['unit_price'], row['stock_qty'], row['stock_state'], row['last_seen'],
                             row['url']])
            count += 1
    print(f'Записано {count} строк: {args.file}')
    return 0


# ---- argument parser ------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='run.py', description='Каталог деталей PCB_EU: поиск по четырём магазинам, проверка BOM, аналоги.')
    parser.add_argument('--data', help='папка с базой и кэшем (по умолчанию data рядом с run.py или PARTSCAT_DATA)')
    parser.add_argument('--bom', help='папка с BOM_allocated.csv и design.json')
    common = argparse.ArgumentParser(add_help=False)          # the same two options are accepted after the command, too
    common.add_argument('--data', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument('--bom', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='command')

    serve = sub.add_parser('serve', parents=[common], help='запустить веб-страницу (по умолчанию)')
    serve.add_argument('--port', type=int)
    serve.add_argument('--no-browser', action='store_true')
    serve.set_defaults(func=cmd_serve)

    crawl = sub.add_parser('crawl', parents=[common], help='собрать данные из магазинов')
    plans = crawl.add_subparsers(dest='plan', required=True)
    plans.add_parser('bom', parents=[common], help='страницы деталей из BOM и список наблюдения')
    plans.add_parser('watch', parents=[common], help='только список наблюдения')
    urls = plans.add_parser('urls', parents=[common], help='прочитать страницы товаров и добавить в наблюдение')
    urls.add_argument('urls', nargs='+')
    urls.add_argument('--no-watch', action='store_true', help='не добавлять в список наблюдения')
    ask = plans.add_parser('search', parents=[common], help='спросить магазины с поиском (Salvats, Semikom)')
    ask.add_argument('query', nargs='+')
    ask.add_argument('--shop', action='append', choices=['salvats', 'electrobase', 'semikom', 'lemona'])
    ask.add_argument('--pages', type=int, default=1)
    ask.add_argument('--enrich', type=int, default=4, help='сколько карточек без артикула дочитать')
    sweep = plans.add_parser('sweep', parents=[common], help='обойти разделы магазина')
    sweep.add_argument('shop', choices=['salvats', 'electrobase', 'semikom'])
    sweep.add_argument('--match', default='', help='часть названия раздела, например tranzistori')
    sweep.add_argument('--pages', type=int, default=40, help='страниц на раздел')
    enrich = plans.add_parser('enrich', parents=[common], help='прочитать карточки без известного артикула')
    enrich.add_argument('--limit', type=int, default=30)
    enrich.add_argument('--shop', action='append', choices=['salvats', 'electrobase', 'semikom', 'lemona'])
    crawl.set_defaults(func=cmd_crawl)

    bom = sub.add_parser('bom', parents=[common], help='проверить BOM по базе')
    bom.add_argument('--all', action='store_true', help='показать и строки «ок»')
    bom.add_argument('--level', choices=['ok', 'warn', 'bad', 'none'])
    bom.add_argument('--analogs', action='store_true', help='для проблемных строк показать аналоги')
    bom.add_argument('--csv', help='записать результат в CSV')
    bom.set_defaults(func=cmd_bom)

    find = sub.add_parser('search', parents=[common], help='поиск по базе')
    find.add_argument('query', nargs='+')
    find.add_argument('--shop', action='append', choices=['salvats', 'electrobase', 'semikom', 'lemona'])
    find.add_argument('--in-stock', action='store_true')
    find.add_argument('--qty', type=int, default=0, help='посчитать цену на столько штук')
    find.add_argument('--limit', type=int, default=20)
    find.set_defaults(func=cmd_search)

    alt = sub.add_parser('analogs', parents=[common], help='аналоги детали по артикулу')
    alt.add_argument('mpn')
    alt.add_argument('--all', action='store_true', help='и неподходящие')
    alt.add_argument('--in-stock', action='store_true')
    alt.add_argument('--limit', type=int, default=15)
    alt.set_defaults(func=cmd_analogs)

    doc = sub.add_parser('doctor', parents=[common], help='проверить установку, данные и связь с магазинами')
    doc.add_argument('--offline', action='store_true', help='не обращаться к магазинам')
    doc.add_argument('--shop', action='append', choices=['salvats', 'electrobase', 'semikom', 'lemona'])
    doc.set_defaults(func=cmd_doctor)

    export = sub.add_parser('export', parents=[common], help='выгрузить все предложения в CSV')
    export.add_argument('file')
    export.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):                 # Russian text on a Windows console and in pipes
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if not getattr(args, 'func', None):
        args = build_parser().parse_args([*(argv or []), 'serve'])
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        return 130
    except BrokenPipeError:                                  # `run.py bom | head`
        return 0
