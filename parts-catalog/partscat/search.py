"""Search over the stored offers.

A query is a mix of words and parameters: 'FDB5800', 'n-mosfet 60V 80A D2PAK', 'schottky 100V SMC',
'100nF 50V 0805'. Words are matched in title, part number, brand and category; recognised parameters
become constraints on the parsed values (60V means at least 60 V, 10mΩ at most 10 mΩ). Offers of the
same part number from different shops are shown together.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .db import Database
from .normalize import fold, norm_mpn
from .params import canon_package, describe, format_farad
from .pricing import cost_for

KIND_WORDS = {
    'mosfet': 'mosfet', 'fet': 'mosfet', 'mosfets': 'mosfet', 'igbt': 'igbt', 'bjt': 'bjt', 'transistor': None,
    'diode': 'diode', 'diodes': 'diode', 'schottky': 'schottky', 'sotki': 'schottky', 'zener': 'zener',
    'stabilitron': 'zener', 'tvs': 'tvs', 'transil': 'tvs', 'resistor': 'resistor', 'rezistors': 'resistor',
    'capacitor': 'capacitor', 'kondensators': 'capacitor', 'mlcc': 'capacitor', 'fuse': 'fuse',
}
POLARITY_WORDS = {
    'n-mosfet': ('mosfet', 'N'), 'nmosfet': ('mosfet', 'N'), 'n-fet': ('mosfet', 'N'), 'n-channel': ('mosfet', 'N'),
    'p-mosfet': ('mosfet', 'P'), 'pmosfet': ('mosfet', 'P'), 'p-fet': ('mosfet', 'P'), 'p-channel': ('mosfet', 'P'),
    'npn': ('bjt', 'NPN'), 'pnp': ('bjt', 'PNP'),
}
KIND_GROUPS = {'diode': ('diode', 'schottky')}      # a query for 'diode' also finds Schottky diodes, not the other way round
VOLT_KEYS = ('vds', 'vce', 'vr', 'vz')
AMP_KEYS = ('id', 'ic', 'if')

_OP = r'(>=|<=|≥|≤|>|<|=)?'
_NUM = r'(\d+(?:[.,]\d+)?)'
_RX_VOLT = re.compile(_OP + _NUM + r'\s*[vв]$', re.I)
_RX_AMP = re.compile(_OP + _NUM + r'\s*(m?)[aа]$', re.I)
_RX_WATT = re.compile(_OP + _NUM + r'\s*(m?)w$', re.I)
_RX_RDS = re.compile(_OP + _NUM + r'\s*m(?:Ω|ohm|ом)$', re.I)
_RX_FARAD = re.compile(_NUM + r'\s*(p|n|u|µ|μ|mk|m)?f$', re.I)
_FARAD = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'mk': 1e-6, 'm': 1e-3, None: 1.0}


@dataclass
class Constraint:
    key: str          # volt / amp / watt / rds_mohm / farad
    op: str           # >= <= =
    value: float
    text: str


@dataclass
class Query:
    text: str
    words: list[str] = field(default_factory=list)
    kind: str | None = None
    polarity: str | None = None
    pkg: str | None = None
    mount: str | None = None
    logic: bool = False
    constraints: list[Constraint] = field(default_factory=list)

    @property
    def structured(self) -> bool:
        return bool(self.kind or self.polarity or self.pkg or self.mount or self.logic or self.constraints)


def _op(raw: str | None, default: str) -> str:
    return {'≥': '>=', '≤': '<=', '>': '>=', '<': '<=', None: default, '': default}.get(raw, raw or default)


def parse_query(text: str) -> Query:
    query = Query(text=text.strip())
    for raw in re.split(r'[\s;]+', query.text):
        token = raw.strip(' ,')
        if not token:
            continue
        low = token.lower()
        if low in POLARITY_WORDS:
            query.kind, query.polarity = POLARITY_WORDS[low]
            continue
        if low in KIND_WORDS:
            if KIND_WORDS[low]:
                query.kind = KIND_WORDS[low]
            continue
        if low in ('smd', 'tht'):
            query.mount = low
            continue
        if low in ('logic', 'logiclevel', 'logl', 'logic-level'):
            query.logic = True
            continue
        match = _RX_RDS.match(token)
        if match:
            query.constraints.append(Constraint('rds_mohm', _op(match.group(1), '<='), float(match.group(2).replace(',', '.')), token))
            continue
        match = _RX_VOLT.match(token)
        if match:
            query.constraints.append(Constraint('volt', _op(match.group(1), '>='), float(match.group(2).replace(',', '.')), token))
            continue
        match = _RX_WATT.match(token)
        if match:
            scale = 1e-3 if match.group(3) else 1.0
            query.constraints.append(Constraint('watt', _op(match.group(1), '>='), float(match.group(2).replace(',', '.')) * scale, token))
            continue
        match = _RX_AMP.match(token)
        if match:
            scale = 1e-3 if match.group(3) else 1.0
            query.constraints.append(Constraint('amp', _op(match.group(1), '>='), float(match.group(2).replace(',', '.')) * scale, token))
            continue
        match = _RX_FARAD.match(token)
        if match and not re.fullmatch(r'\d+f', low):
            query.constraints.append(Constraint('farad', '=', float(match.group(1).replace(',', '.')) * _FARAD[match.group(2).lower() if match.group(2) else None], token))
            if not query.kind:
                query.kind = 'capacitor'
            continue
        if _looks_like_package(token) and canon_package(token):
            query.pkg = canon_package(token)
            continue
        query.words.append(token)
    return query


def _looks_like_package(token: str) -> bool:
    return bool(re.fullmatch(r'(?i)(?:to-?\d+[a-z]*|d2-?pak|d-?pak|sot-?\d+(?:-?\d)?|so-?8|soic-?8|sop-?8|sm[abc]|0402|0603|0805|1206|2512|do-?\d+[a-z]*|sod-?\d+)', token))


KIND_TITLES = {'mosfet': 'MOSFET', 'igbt': 'IGBT', 'bjt': 'биполярный транзистор', 'diode': 'диод', 'schottky': 'диод Шоттки',
               'zener': 'стабилитрон', 'tvs': 'TVS', 'resistor': 'резистор', 'capacitor': 'конденсатор', 'fuse': 'предохранитель'}
_CONSTRAINT_TEXT = {'volt': ('В', 1.0), 'amp': ('А', 1.0), 'watt': ('Вт', 1.0), 'rds_mohm': ('мОм', 1.0)}


def explain(query: Query) -> list[str]:
    """How the query was understood, for chips under the search box: ['N-MOSFET', '≥ 60 В', 'TO-263']."""
    out = []
    if query.polarity and query.kind == 'mosfet':
        out.append(f'{query.polarity}-MOSFET')
    elif query.polarity:
        out.append(query.polarity)
    elif query.kind:
        out.append(KIND_TITLES.get(query.kind, query.kind))
    for c in query.constraints:
        symbol = {'>=': '≥', '<=': '≤', '=': '='}[c.op]
        if c.key == 'farad':
            out.append(f'{symbol} {format_farad(c.value)}')
        else:
            unit = _CONSTRAINT_TEXT[c.key][0]
            out.append(f'{symbol} {c.value:g} {unit}')
    if query.pkg:
        out.append(query.pkg)
    if query.mount:
        out.append(query.mount.upper())
    if query.logic:
        out.append('logic-level')
    return out


def value_of(params: dict, key: str) -> float | None:
    """The parsed number a constraint talks about, for whatever kind the offer is."""
    if key == 'volt':
        return next((params[k] for k in VOLT_KEYS if k in params), None)
    if key == 'amp':
        return next((params[k] for k in AMP_KEYS if k in params), None)
    if key == 'watt':
        return params.get('pd')
    return params.get(key)


def check(params: dict, query: Query) -> tuple[bool, int, int]:
    """(passes, constraints confirmed, constraints with no data). A violated constraint fails the offer."""
    if query.kind and params.get('kind') not in KIND_GROUPS.get(query.kind, (query.kind,)):
        return False, 0, 0
    if query.polarity and params.get('polarity') != query.polarity:
        return False, 0, 0
    if query.pkg and params.get('pkg') != query.pkg:
        return False, 0, 0
    if query.mount and params.get('mount') != query.mount:
        return False, 0, 0
    if query.logic and not params.get('logic_level'):
        return False, 0, 0
    confirmed = unknown = 0
    for c in query.constraints:
        have = value_of(params, c.key)
        if have is None:
            unknown += 1
            continue
        if c.op == '>=' and have >= c.value * 0.9999:
            confirmed += 1
        elif c.op == '<=' and have <= c.value * 1.0001:
            confirmed += 1
        elif c.op == '=' and abs(have - c.value) <= abs(c.value) * 0.02:
            confirmed += 1
        else:
            return False, 0, 0
    return True, confirmed, unknown


@dataclass
class Group:
    """Offers of one part number (or one unnamed offer) across the shops."""
    key: str
    mpn: str | None
    title: str
    brand: str | None
    kind: str
    params: dict
    summary: str
    offers: list[dict]
    score: float
    reasons: list[str]
    unknown: int = 0

    @property
    def best(self) -> dict | None:
        priced = [o for o in self.offers if o.get('unit_price') is not None]
        in_stock = [o for o in priced if o.get('stock_state') != 'out']
        pool = in_stock or priced
        return min(pool, key=lambda o: o['unit_price']) if pool else None


@dataclass
class Result:
    query: Query
    groups: list[Group]
    candidates: int
    note: str = ''
    total_groups: int = 0           # before the limit cut the list


def _score(offer: dict, query: Query) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    for word in query.words:
        key = norm_mpn(word)
        if not key:
            continue
        if offer['mpn_norm'] == key or offer['sku_norm'] == key:
            score += 100
            reasons.append('совпадает артикул')
        elif key in re.split(r'[^0-9A-Z]+', (offer['title'] or '').upper()):
            score += 85
            reasons.append('артикул в названии')
        elif len(key) >= 4 and (offer['mpn_norm'].startswith(key) or key.startswith(offer['mpn_norm']) and len(offer['mpn_norm']) >= 5):
            score += 70
            reasons.append('близкий артикул')
        elif len(key) >= 3 and (key in offer['mpn_norm'] or key in offer['sku_norm']):
            score += 40
            reasons.append('часть артикула')
        else:
            score += 15
    if offer.get('stock_state') in ('in', 'order'):
        score += 3
    return score, reasons


def group_rows(scored: list[tuple[float, dict, list[str], int]]) -> list[Group]:
    """Offers of one part number into one Group (parameters merged: shops give different fields of the same part)."""
    groups: dict[str, Group] = {}
    for score, row, reasons, unknown in scored:
        key = row['mpn_norm'] or f"{row['shop']}:{row['shop_id']}"
        group = groups.get(key)
        if group is None:
            groups[key] = Group(key=key, mpn=row['mpn'], title=row['title'], brand=row['brand'], kind=row['kind'],
                                params=dict(row['params']), summary=describe(row['params']), offers=[row], score=score,
                                reasons=list(dict.fromkeys(reasons)), unknown=unknown)
            continue
        group.offers.append(row)
        group.score = max(group.score, score)
        group.reasons = list(dict.fromkeys([*group.reasons, *reasons]))
        merged = {**row['params'], **group.params} if len(group.params) >= len(row['params']) else {**group.params, **row['params']}
        if merged != group.params:
            group.params, group.summary = merged, describe(merged)
        group.mpn = group.mpn or row['mpn']
        group.brand = group.brand or row['brand']
        group.unknown = min(group.unknown, unknown)
    ordered = sorted(groups.values(), key=lambda g: (-g.score, g.best['unit_price'] if g.best else 1e9, g.key))
    for group in ordered:
        group.offers.sort(key=lambda o: (o['stock_state'] == 'out', o['unit_price'] if o['unit_price'] is not None else 1e9))
    return ordered


def search(db: Database, text: str, *, shops: list[str] | None = None, in_stock: bool = False, limit: int = 60) -> Result:
    query = parse_query(text)
    if not query.words and not query.structured:
        return Result(query, [], 0, 'введите артикул или параметры, например FDB5800 или «n-mosfet 60V 80A D2PAK»')
    kinds = KIND_GROUPS.get(query.kind, (query.kind,)) if query.kind else None
    if query.words:
        rows = db.candidates(query.words, shops=shops, kind=kinds, limit=4000)
    else:
        rows = db.by_kind(kinds, shops=shops, pkg=query.pkg) if kinds else db.candidates([], shops=shops, limit=20000)
    scored: list[tuple[float, dict, list[str], int]] = []
    for row in rows:
        if in_stock and row['stock_state'] == 'out':
            continue
        passes, confirmed, unknown = check(row['params'], query)
        if not passes:
            continue
        score, reasons = _score(row, query)
        score += 5 * confirmed - 2 * unknown
        if confirmed:
            reasons.append(f'подтверждено параметров: {confirmed}')
        scored.append((score, row, reasons, unknown))
    ordered = group_rows(scored)
    note = f'найдено {len(scored)} предложений в {len(ordered)} позициях'
    if len(ordered) > limit:
        note += f', показаны первые {limit}'
    return Result(query, ordered[:limit], len(scored), note, len(ordered))


def cheapest_for(group: Group, pieces: int) -> dict | None:
    """The offer with the lowest total for `pieces` pieces among those that have them."""
    best, best_total = None, None
    for offer in group.offers:
        cost = cost_for(offer, pieces)
        if cost is None or offer.get('stock_state') == 'out':
            continue
        if best_total is None or cost['total'] < best_total:
            best, best_total = offer, cost['total']
    return best
