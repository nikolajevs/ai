"""The PCB_EU bill of materials and its check against the stored offers.

The BOM is read from the board's own files: BOM_allocated.csv (one line per part number with the shop, the
price and the quantity chosen when the BOM was written), BOM_allocated.json (block and usage notes) and
design.json (value and footprint of every reference). A line is matched to a stored offer by its page
address, else by shop and part number. The check reports what changed since the BOM was written: price,
stock, a part number the shop no longer agrees with, data that is too old, a cheaper offer of the same
part number in another shop, and resistors, capacitors and semiconductors whose value or case in the shop
disagrees with the schematic.
"""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .db import Database, age_days
from .normalize import norm_mpn, ohm_code
from .params import canon_package, format_farad, format_ohm, packages_compatible
from .pricing import availability, cost_for, stock_pieces

BOM_FILE = 'BOM_allocated.csv'
DETAIL_FILE = 'BOM_allocated.json'
SUMMARY_FILES = ('BOM_summary.json', 'review/BOM_summary.json')
DESIGN_FILE = 'design.json'
SHOPS = {'salvats': 'salvats', 'electrobase': 'electrobase', 'semikom': 'semikom', 'lemona': 'lemona'}
ROOT = Path(__file__).resolve().parent.parent
LEVEL_ORDER = {'ok': 0, 'none': 1, 'warn': 2, 'bad': 3}


def find_bom_dir(root: Path | None = None) -> Path | None:
    """The folder with BOM_allocated.csv: $PARTSCAT_BOM_DIR, a 'bom' folder beside the app, the board folder of the repository."""
    root = root or ROOT
    candidates = [Path(os.environ['PARTSCAT_BOM_DIR'])] if os.environ.get('PARTSCAT_BOM_DIR') else []
    candidates += [root / 'bom', root.parent / 'hardware' / 'PCB_EU']
    return next((path for path in candidates if (path / BOM_FILE).is_file()), None)


@dataclass
class BomLine:
    shop: str                    # shop key, '' while no shop is chosen
    shop_label: str              # as written in the BOM
    mpn: str
    fitted: int                  # pieces the board needs (accessories: pieces of the accessory)
    buy: int                     # pieces to buy
    unit: str                    # 'шт.' or 'уп. 10 шт.'
    pack: int
    price: float | None          # per sale unit, EUR with VAT
    total: float | None
    refs: list[str]
    accessory: int
    url: str
    date: str
    block: str = ''
    usage: str = ''
    parts: list[dict] = field(default_factory=list)      # design.json entries of the references

    @property
    def needed(self) -> int:
        return self.buy or self.fitted

    @property
    def key(self) -> str:
        return f'{self.shop}:{norm_mpn(self.mpn)}'


@dataclass
class Bom:
    lines: list[BomLine]
    source: str
    revision: str | None = None
    shipping: float | None = None          # from the board's BOM summary; the check does not recompute it

    @property
    def total(self) -> float:
        return round(sum(line.total or 0 for line in self.lines), 2)


def _number(text: str | None) -> float | None:
    try:
        return float((text or '').replace(',', '.'))
    except ValueError:
        return None


def _int(text: str | None, default: int = 0) -> int:
    value = _number(text)
    return int(value) if value is not None else default


def pack_of(unit: str) -> int:
    """'уп. 10 шт.' -> 10, 'шт.' -> 1."""
    match = re.search(r'уп\.?\s*(\d+)', unit or '')
    return int(match.group(1)) if match else 1


def load_bom(directory: str | Path) -> Bom:
    directory = Path(directory)
    detail = {}
    if (directory / DETAIL_FILE).is_file():
        for item in json.loads((directory / DETAIL_FILE).read_text(encoding='utf-8')):
            detail[(str(item.get('shop', '')).lower(), norm_mpn(item.get('mpn')))] = item
    parts: dict[str, dict] = {}
    revision = None
    if (directory / DESIGN_FILE).is_file():
        design = json.loads((directory / DESIGN_FILE).read_text(encoding='utf-8'))
        revision = design.get('revision')
        parts = {part['ref']: part for part in design.get('parts', []) if part.get('ref')}
    lines = []
    with open(directory / BOM_FILE, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            label = (row.get('Shop') or '').strip()
            mpn = (row.get('MPN_or_shop_SKU') or '').strip()
            if not mpn:
                continue
            refs = (row.get('References') or '').split()
            extra = detail.get((label.lower(), norm_mpn(mpn)), {})
            price = _number(row.get('Price_per_sale_unit_EUR_VAT'))
            lines.append(BomLine(
                shop=SHOPS.get(label.lower(), ''), shop_label=label, mpn=mpn, fitted=_int(row.get('Fitted_or_accessory')),
                buy=_int(row.get('Buy_pieces')), unit=(row.get('Sale_unit') or '').strip(), pack=pack_of(row.get('Sale_unit') or ''),
                price=price if price else None, total=_number(row.get('Line_EUR_VAT')), refs=refs,
                accessory=_int(row.get('Accessory_count')), url=(row.get('URL') or '').strip(), date=(row.get('Price_date') or '').strip(),
                block=extra.get('block', ''), usage=extra.get('usage', ''), parts=[parts[r] for r in refs if r in parts]))
    shipping = None
    for name in SUMMARY_FILES:
        if (directory / name).is_file():
            shipping = _number(str(json.loads((directory / name).read_text(encoding='utf-8')).get('shipping_EUR', '')))
            break
    return Bom(lines, str(directory), revision, shipping)


# ---- what the schematic asks of a part ------------------------------------------------------------------

def footprint_package(footprint: str | None) -> str | None:
    """'Resistor_SMD:R_1206_3216Metric' -> 'SMD1206', 'Package_TO_SOT_SMD:TO-263-2' -> 'TO-263'."""
    name = (footprint or '').split(':', 1)[-1]
    return canon_package(re.sub(r'[_:]+', ' ', name))


def _farad(token: str) -> float | None:
    scale = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6}
    match = re.fullmatch(r'(\d+(?:[.,]\d+)?)([pnuµμ])F?', token, re.I)
    if match:
        return float(match.group(1).replace(',', '.')) * scale[match.group(2).lower()]
    match = re.fullmatch(r'(\d+)([pnuµμ])(\d+)', token, re.I)           # 4n7, 2u2
    if match:
        return float(f'{match.group(1)}.{match.group(3)}') * scale[match.group(2).lower()]
    return None


def expectation(part: dict) -> dict:
    """What the schematic value and footprint of one reference ask of the part."""
    ref = part.get('ref', '')
    prefix = re.sub(r'[^A-Za-z].*', '', ref).upper()
    exp: dict = {'ref': ref, 'pkg': footprint_package(part.get('footprint'))}
    words = (part.get('value') or '').split()
    for word in words[1:]:
        match = re.fullmatch(r'(\d+(?:[.,]\d+)?)V', word, re.I)
        if match:
            exp['vr'] = float(match.group(1).replace(',', '.'))
            continue
        match = re.fullmatch(r'(\d+(?:[.,]\d+)?)W', word, re.I)
        if match:
            exp['pd'] = float(match.group(1).replace(',', '.'))
            continue
        match = re.fullmatch(r'±?(\d+(?:[.,]\d+)?)%', word)
        if match:
            exp['tol'] = float(match.group(1).replace(',', '.'))
            continue
        if re.fullmatch(r'(C0G|NP0|X7R|X5R|X7S|X6S|Y5V)', word, re.I):
            exp['dielectric'] = 'C0G' if word.upper() == 'NP0' else word.upper()
    if prefix == 'R' and words:
        exp['kind'], exp['ohm'] = 'resistor', ohm_code(words[0])
    elif prefix == 'C' and words:
        exp['kind'], exp['farad'] = 'capacitor', _farad(words[0])
    elif prefix == 'Q':
        symbol = (part.get('symbol') or '').upper()
        if 'MOS' in symbol:
            exp['kind'], exp['polarity'] = 'mosfet', symbol[0] if symbol[0] in 'NP' else None
        elif symbol in ('NPN', 'PNP'):
            exp['kind'], exp['polarity'] = 'bjt', symbol
    elif prefix == 'D':
        exp['kind'] = 'diode'
    return exp


def spec_issues(parts: list[dict], offer: dict) -> list['Issue']:
    """Disagreements between the schematic and the parsed shop data; a value the shop does not give is not a disagreement."""
    have = offer['params']
    issues: list[Issue] = []
    for part in parts:
        exp = expectation(part)
        where = f"{exp['ref']}"
        if exp.get('pkg') and have.get('pkg') and not packages_compatible(exp['pkg'], have['pkg']):
            issues.append(Issue('bad', 'spec', f"корпус в магазине {have['pkg']}, на плате {exp['pkg']} ({where})"))
        kind = have.get('kind')
        if exp.get('kind') == 'resistor' and kind == 'resistor':
            if exp.get('ohm') and have.get('ohm') and abs(have['ohm'] - exp['ohm']) > exp['ohm'] * 0.01:
                issues.append(Issue('bad', 'spec', f"сопротивление в магазине {format_ohm(have['ohm'])}, в схеме {format_ohm(exp['ohm'])} ({where})"))
            if exp.get('tol') and have.get('tol') and have['tol'] > exp['tol']:
                issues.append(Issue('warn', 'spec', f"допуск в магазине {have['tol']:g} %, в схеме {exp['tol']:g} % ({where})"))
            if exp.get('pd') and have.get('pd') and have['pd'] < exp['pd']:
                issues.append(Issue('bad', 'spec', f"мощность в магазине {have['pd']:g} Вт, в схеме {exp['pd']:g} Вт ({where})"))
        elif exp.get('kind') == 'capacitor' and kind == 'capacitor':
            if exp.get('farad') and have.get('farad') and abs(have['farad'] - exp['farad']) > exp['farad'] * 0.02:
                issues.append(Issue('bad', 'spec', f"ёмкость в магазине {format_farad(have['farad'])}, в схеме {format_farad(exp['farad'])} ({where})"))
            if exp.get('vr') and have.get('vr') and have['vr'] < exp['vr']:
                issues.append(Issue('bad', 'spec', f"напряжение в магазине {have['vr']:g} В, в схеме {exp['vr']:g} В ({where})"))
            if exp.get('dielectric') and have.get('dielectric') and have['dielectric'] != exp['dielectric']:
                issues.append(Issue('warn', 'spec', f"диэлектрик в магазине {have['dielectric']}, в схеме {exp['dielectric']} ({where})"))
        elif exp.get('kind') in ('mosfet', 'bjt') and kind in ('mosfet', 'bjt'):
            if exp.get('polarity') and have.get('polarity') and have['polarity'] != exp['polarity']:
                issues.append(Issue('bad', 'spec', f"полярность в магазине {have['polarity']}, в схеме {exp['polarity']} ({where})"))
    unique = {}
    for issue in issues:
        unique.setdefault((issue.code, issue.text.rsplit(' (', 1)[0]), issue)
    return list(unique.values())


# ---- the check ------------------------------------------------------------------------------------------

@dataclass
class Issue:
    level: str                   # bad / warn / info
    code: str
    text: str


@dataclass
class LineCheck:
    line: BomLine
    offer: dict | None
    issues: list[Issue]
    level: str                   # ok / none / warn / bad
    now_total: float | None      # what the planned quantity costs now in the matched offer
    now_unit: float | None       # price per sale unit now
    age: float | None            # days since the offer was last seen
    cheaper: dict | None = None  # {'offer', 'total', 'saves'} the same part number in another shop
    others: list[dict] = field(default_factory=list)   # for a line without a shop: offers of the part number

    @property
    def delta(self) -> float | None:
        if self.now_total is None or self.line.total is None:
            return None
        return round(self.now_total - self.line.total, 2)


@dataclass
class BomReport:
    bom: Bom
    checks: list[LineCheck]

    def counts(self) -> dict[str, int]:
        counts = {'ok': 0, 'none': 0, 'warn': 0, 'bad': 0}
        for check in self.checks:
            counts[check.level] += 1
        return counts

    @property
    def bom_total(self) -> float:
        return self.bom.total

    @property
    def now_total(self) -> float:
        """The BOM total with every refreshed line at today's price (other lines keep the BOM price)."""
        return round(sum(c.now_total if c.now_total is not None else (c.line.total or 0) for c in self.checks), 2)

    @property
    def with_shipping(self) -> tuple[float, float] | None:
        """(BOM total, today's total), both plus the shipping of the BOM summary; None when the summary is missing."""
        if self.bom.shipping is None:
            return None
        return round(self.bom_total + self.bom.shipping, 2), round(self.now_total + self.bom.shipping, 2)

    @property
    def refreshed(self) -> int:
        return sum(1 for c in self.checks if c.now_total is not None)

    def by_shop(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for c in self.checks:
            value = c.now_total if c.now_total is not None else (c.line.total or 0)
            totals[c.line.shop or 'не выбран'] = round(totals.get(c.line.shop or 'не выбран', 0) + value, 2)
        return totals


def url_variants(url: str) -> list[str]:
    """The same page written with or without 'www.', a trailing slash or a query."""
    if not url:
        return []
    parts = urlsplit(url.strip())
    hosts = {parts.netloc, parts.netloc.removeprefix('www.'), 'www.' + parts.netloc.removeprefix('www.')}
    out = []
    for host in hosts:
        for path in {parts.path, parts.path.rstrip('/')}:
            out.append(urlunsplit((parts.scheme, host, path, parts.query, '')))
            out.append(urlunsplit((parts.scheme, host, path, '', '')))
    return list(dict.fromkeys(out))


def find_offer(db: Database, line: BomLine) -> dict | None:
    for url in url_variants(line.url):
        found = db.find_by_url(url)
        if found:
            return found
    for offer in db.by_mpn(line.mpn):
        if not line.shop or offer['shop'] == line.shop:
            return offer
    return None


def offers_by_total(db: Database, mpn: str, pieces: int, exclude: int | None = None) -> list[tuple[float, dict]]:
    """Offers of one part number that have the pieces, cheapest total first."""
    out = []
    for offer in db.by_mpn(mpn):
        if offer['id'] == exclude or availability(offer, pieces) in ('out', 'short'):
            continue
        cost = cost_for(offer, pieces)
        if cost is not None:
            out.append((cost['total'], offer))
    return sorted(out, key=lambda pair: pair[0])


def _money(value: float) -> str:
    return f'{value:.2f} €'.replace('.', ',')


def check_line(db: Database, line: BomLine, *, now: str | None = None, max_age_days: float = 3.0) -> LineCheck:
    issues: list[Issue] = []
    if not line.shop:
        found = offers_by_total(db, line.mpn, line.needed)
        text = ('магазин не выбран; в базе есть: ' + ', '.join(f"{o['shop']} {_money(total)}" for total, o in found[:3])
                if found else 'магазин не выбран, этого артикула нет в базе')
        return LineCheck(line, None, [Issue('warn' if found else 'info', 'no_shop', text)], 'warn' if found else 'none',
                         None, None, None, others=[o for _, o in found[:5]])
    offer = find_offer(db, line)
    if offer is None:
        return LineCheck(line, None, [Issue('info', 'missing', 'ещё не читалась из магазина')], 'none', None, None, None)
    age = age_days(offer['last_seen'], now)
    cost = cost_for(offer, line.needed)
    now_total = cost['total'] if cost else None
    if age is not None and age > max_age_days:
        issues.append(Issue('warn', 'stale', f"данные магазина от {offer['last_seen'][:10]} ({age:.0f} дн.)"))
    shop_codes = {norm_mpn(offer.get('mpn')), norm_mpn(offer.get('shop_sku'))} - {''}
    if shop_codes and norm_mpn(line.mpn) not in shop_codes:
        issues.append(Issue('warn', 'mpn', f"артикул в магазине {offer.get('mpn') or offer.get('shop_sku')}, в BOM {line.mpn}"))
    status = availability(offer, line.needed)
    have = stock_pieces(offer)
    if status == 'out':
        issues.append(Issue('bad', 'out', 'нет в наличии'))
    elif status == 'short':
        issues.append(Issue('bad', 'short', f'на складе {have} шт., нужно купить {line.needed}'))
    elif status == 'order':
        issues.append(Issue('warn', 'order', 'только под заказ' + (f": {offer['note']}" if offer.get('note') else '')))
    elif status == 'unknown':
        issues.append(Issue('info', 'stock_unknown', 'остаток неизвестен'))
    elif have is not None and not offer.get('stock_atleast') and have < max(2 * line.needed, 10):
        issues.append(Issue('info', 'low', f'на складе всего {have} шт.'))
    if offer['sale_price'] is None:
        issues.append(Issue('warn', 'no_price', 'в магазине нет цены'))
    elif line.price:
        diff = offer['sale_price'] - line.price
        if abs(diff) >= 0.005:
            percent = diff / line.price * 100
            level = 'warn' if abs(percent) >= 5 and abs(diff) >= 0.02 else 'info'
            issues.append(Issue(level, 'price', f"цена {_money(line.price)} → {_money(offer['sale_price'])} ({percent:+.0f} %)"))
    if line.pack != max(offer['pack_qty'], 1):
        issues.append(Issue('warn', 'pack', f"упаковка в BOM {line.pack} шт., в магазине {offer['pack_qty']} шт."))
    cheaper = None
    if now_total is not None:
        for total, other in offers_by_total(db, line.mpn, line.needed, exclude=offer['id']):
            saves = round(now_total - total, 2)
            if saves >= max(0.05, now_total * 0.03):
                cheaper = {'offer': other, 'total': total, 'saves': saves}
                issues.append(Issue('info', 'cheaper', f"дешевле в {other['shop']}: {_money(total)} вместо {_money(now_total)}"))
            break
    issues.extend(spec_issues(line.parts, offer))
    level = 'ok'
    for issue in issues:
        mapped = 'bad' if issue.level == 'bad' else 'warn' if issue.level == 'warn' else 'ok'
        if LEVEL_ORDER[mapped] > LEVEL_ORDER[level]:
            level = mapped
    return LineCheck(line, offer, issues, level, now_total, offer['sale_price'], age, cheaper=cheaper)


def check_bom(db: Database, bom: Bom, *, now: str | None = None, max_age_days: float = 3.0) -> BomReport:
    checks = [check_line(db, line, now=now, max_age_days=max_age_days) for line in bom.lines]
    checks.sort(key=lambda c: -LEVEL_ORDER[c.level])
    return BomReport(bom, checks)


# ---- lists the crawler and the exports use --------------------------------------------------------------

def watch_urls(bom: Bom) -> list[tuple[str, str]]:
    """[(shop key, page address)] of every BOM line that has both."""
    return [(line.shop, line.url) for line in bom.lines if line.shop and line.url]


def export_rows(report: BomReport) -> list[dict]:
    rows = []
    for c in report.checks:
        offer = c.offer or {}
        rows.append({
            'Статус': {'ok': 'ок', 'warn': 'проверить', 'bad': 'проблема', 'none': 'нет данных'}[c.level],
            'Магазин': c.line.shop_label, 'Артикул': c.line.mpn, 'Позиции': ' '.join(c.line.refs),
            'Нужно': c.line.fitted, 'Купить': c.line.buy, 'Единица': c.line.unit,
            'Цена в BOM': c.line.price, 'Цена сейчас': c.now_unit, 'Сумма в BOM': c.line.total, 'Сумма сейчас': c.now_total,
            'Остаток': stock_pieces(offer) if offer else None, 'Данные от': (offer.get('last_seen') or '')[:10],
            'Замечания': '; '.join(issue.text for issue in c.issues), 'Ссылка': offer.get('url') or c.line.url})
    return rows
