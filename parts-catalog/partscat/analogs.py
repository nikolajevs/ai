"""Replacement candidates for a part, with a verdict and the reasons for it.

A candidate is compared with the reference parameter by parameter. Every parameter is 'better', 'ok',
'worse' (tolerable, look at it), 'bad' (disqualifies) or 'unknown' (the shop title does not say). The verdict:

  drop-in    same case, nothing worse, nothing unknown that matters      "можно ставить"
  check      same case, something worse or not stated in the shop data    "проверить"
  other-pkg  electrically fine but another case                           "другой корпус"
  no         a disqualifying parameter (polarity, voltage, value)         "не подходит"

Only what the shop titles and property lists state is compared. Pin order, thermal design and the
datasheet curves stay with the person; the page says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .bom import BomLine, expectation, find_offer
from .db import Database
from .normalize import norm_mpn
from .params import describe, format_farad, format_ohm, packages_compatible
from .search import Group, group_rows

VERDICTS = {'drop-in': 'можно ставить', 'check': 'проверить', 'other-pkg': 'другой корпус', 'no': 'не подходит'}
RANK = {'drop-in': 0, 'check': 1, 'other-pkg': 2, 'no': 3}
KIND_POOL = {'mosfet': ('mosfet',), 'bjt': ('bjt',), 'diode': ('diode', 'schottky'), 'schottky': ('diode', 'schottky'),
             'zener': ('zener',), 'tvs': ('tvs',), 'resistor': ('resistor',), 'capacitor': ('capacitor',)}
SAME_CASE_ONLY = ('resistor', 'capacitor')           # other sizes of a chip passive are not replacements
VARYING_PINOUT = {'SOT-23', 'SOT-323', 'SOT-223', 'SOT-89', 'SOT-26', 'SOT-143', 'TO-92', 'SO-8', 'SOT-343'}
DIELECTRIC_RANK = {'C0G': 3, 'X7R': 2, 'X7S': 2, 'X8R': 2, 'X6S': 1, 'X5R': 1, 'Y5V': 0, 'Z5U': 0}


@dataclass
class Spec:
    """The reference: a stored part, or a value and case read from the schematic."""
    title: str
    params: dict
    pkg: str | None = None
    mpn: str | None = None

    @property
    def kind(self) -> str:
        return self.params.get('kind', 'other')

    @property
    def mount(self) -> str | None:
        return self.params.get('mount')


@dataclass
class Check:
    label: str
    ref: str
    cand: str
    status: str          # better / ok / worse / bad / unknown
    note: str = ''       # why a value is uncertain, shown as a tooltip


@dataclass
class Analog:
    group: Group
    verdict: str
    checks: list[Check]
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return VERDICTS[self.verdict]

    @property
    def in_stock(self) -> bool:
        return any(o.get('stock_state') != 'out' for o in self.group.offers)

    @property
    def open(self) -> int:
        """How many parameters are worse or still unknown: the fewer, the less there is left to look up."""
        return sum(1 for c in self.checks if c.status in ('worse', 'unknown'))


def spec_from_offer(offer: dict, footprint_pkg: str | None = None) -> Spec:
    params = dict(offer['params'])
    return Spec(title=offer['title'], params=params, pkg=footprint_pkg or params.get('pkg'), mpn=offer.get('mpn') or offer.get('shop_sku'))


def spec_from_design(expect: dict) -> Spec | None:
    """A chip resistor or capacitor straight from the schematic value, for lines the catalog does not hold yet."""
    kind = expect.get('kind')
    if kind == 'resistor' and expect.get('ohm'):
        keys = ('ohm', 'tol', 'pd')
    elif kind == 'capacitor' and expect.get('farad'):
        keys = ('farad', 'vr', 'dielectric')
    else:
        return None
    params = {'kind': kind, **{k: expect[k] for k in keys if expect.get(k)}}
    pkg = expect.get('pkg')
    if pkg:
        params['pkg'] = pkg
    params['mount'] = 'smd'
    return Spec(title=f"{expect['ref']} {describe(params)}", params=params, pkg=pkg)


def spec_for_line(db: Database, line: BomLine) -> Spec | None:
    """The reference of a BOM line: the stored part with the case of the board footprint (and, for chip resistors and
    capacitors, the value the schematic asks for), or the schematic value alone while the catalog holds nothing."""
    expect = expectation(line.parts[0]) if line.parts else {}
    offer = find_offer(db, line)
    if offer is None or offer['kind'] not in KIND_POOL:
        rows = [o for o in db.by_mpn(line.mpn) if o['kind'] in KIND_POOL]
        offer = max(rows, key=lambda o: len(o['params'])) if rows else None
    if offer is None:
        return spec_from_design(expect) if expect else None
    spec = spec_from_offer(offer, footprint_pkg=expect.get('pkg'))
    spec.mpn = line.mpn
    if spec.kind in SAME_CASE_ONLY:
        spec.params.pop('tol', None)                      # a tolerance is a requirement only where the schematic states it
        spec.params.update({key: expect[key] for key in ('ohm', 'farad', 'vr', 'tol', 'dielectric', 'pd') if expect.get(key)})
    return spec


# ---- parameter comparison -------------------------------------------------------------------------------

def _compare(label: str, ref, cand, fmt: Callable[[float], str], *, high: bool = True, ok: float = 1.0, worse: float = 1.0) -> Check | None:
    """Higher-is-better (high) or lower-is-better parameter. `ok` and `worse` are ratios of the reference."""
    if ref is None:
        return None
    if cand is None:
        return Check(label, fmt(ref), 'не указано', 'unknown')
    if high:
        status = 'better' if cand >= ref * 1.1 else 'ok' if cand >= ref * ok else 'worse' if cand >= ref * worse else 'bad'
    else:
        status = 'better' if cand <= ref * 0.9 else 'ok' if cand <= ref * ok else 'worse' if cand <= ref * worse else 'bad'
    return Check(label, fmt(ref), fmt(cand), status)


def _match(label: str, ref, cand, fmt: Callable[[float], str], *, ok: float, worse: float) -> Check | None:
    """A value that has to agree: within `ok` (fraction) is fine, within `worse` is worth a look, further is no."""
    if ref is None:
        return None
    if cand is None:
        return Check(label, fmt(ref), 'не указано', 'unknown')
    gap = abs(cand - ref) / ref if ref else 0.0
    return Check(label, fmt(ref), fmt(cand), 'ok' if gap <= ok else 'worse' if gap <= worse else 'bad')


def _same(label: str, ref, cand) -> Check | None:
    if ref is None:
        return None
    if cand is None:
        return Check(label, str(ref), 'не указано', 'unknown')
    return Check(label, str(ref), str(cand), 'ok' if ref == cand else 'bad')


def _volt(value: float) -> str:
    return f'{value:g} В'


def _amp(value: float) -> str:
    return f'{value:g} А'


def _watt(value: float) -> str:
    return f'{value:g} Вт'


def _mohm(value: float) -> str:
    return f'{value:g} мОм'


def _rds(ref: dict, cand: dict) -> Check | None:
    """Rds(on) of a title (headline value, 10 V) against one from a property list (conditions not stated) can differ
    by a factor of two for the same part, so a moderately higher value from another kind of source is 'check', not 'no'."""
    want, have = ref.get('rds_mohm'), cand.get('rds_mohm')
    check = _compare('Rds(on)', want, have, _mohm, high=False, ok=1.1, worse=1.4)
    if check and want and have and ref.get('rds_src') != cand.get('rds_src') and check.status in ('worse', 'bad') and have <= want * 2.5:
        return Check('Rds(on)', check.ref, check.cand, 'unknown', 'значения из разных источников (заголовок или список свойств), условия измерения могут отличаться')
    return check


def _mosfet(ref: dict, cand: dict) -> list[Check | None]:
    checks = [
        _same('Канал', ref.get('polarity'), cand.get('polarity')),
        _compare('Vds', ref.get('vds'), cand.get('vds'), _volt),
        _compare('Id', ref.get('id'), cand.get('id'), _amp, ok=1.0, worse=0.7),
        _rds(ref, cand),
        _compare('Vgs макс.', ref.get('vgs_max'), cand.get('vgs_max'), _volt, ok=1.0, worse=0.75),
        _compare('Qg', ref.get('qg_nc'), cand.get('qg_nc'), lambda v: f'{v:g} нКл', high=False, ok=1.3, worse=2.0),
        _compare('Pd', ref.get('pd'), cand.get('pd'), _watt, ok=0.7, worse=0.4),
    ]
    if ref.get('logic_level'):
        checks.append(Check('Logic-level', 'да', 'да' if cand.get('logic_level') else 'не указано',
                            'ok' if cand.get('logic_level') else 'unknown'))
    return checks


def _bjt(ref: dict, cand: dict) -> list[Check | None]:
    return [
        _same('Тип', ref.get('polarity'), cand.get('polarity')),
        _compare('Vce', ref.get('vce'), cand.get('vce'), _volt),
        _compare('Ic', ref.get('ic'), cand.get('ic'), _amp, ok=1.0, worse=0.7),
        _compare('Pd', ref.get('pd'), cand.get('pd'), _watt, ok=0.8, worse=0.5),
        Check('hFE, fT', 'по даташиту', 'по даташиту', 'unknown', 'в названиях магазинов нет коэффициента усиления и частоты'),
    ]


def _diode(ref: dict, cand: dict) -> list[Check | None]:
    checks: list[Check | None] = [
        _compare('Vr', ref.get('vr'), cand.get('vr'), _volt),
        _compare('If', ref.get('if'), cand.get('if'), _amp, ok=1.0, worse=0.7),
    ]
    if ref.get('kind') == 'schottky' and cand.get('kind') != 'schottky':
        checks.append(Check('Тип', 'Шоттки', 'не Шоттки', 'worse'))             # a higher forward drop heats the diode
    elif ref.get('kind') != 'schottky' and cand.get('kind') == 'schottky':
        checks.append(Check('Тип', 'обычный', 'Шоттки', 'ok'))
    if ref.get('dual') != cand.get('dual') and (ref.get('dual') or cand.get('dual')):
        checks.append(Check('Сборка', 'двойной' if ref.get('dual') else 'одиночный', 'двойной' if cand.get('dual') else 'одиночный', 'bad'))
    return checks


def _zener(ref: dict, cand: dict) -> list[Check | None]:
    return [
        _match('Vz', ref.get('vz'), cand.get('vz'), _volt, ok=0.03, worse=0.06),
        _compare('Pd', ref.get('pd'), cand.get('pd'), _watt, ok=0.8, worse=0.5),
    ]


def _tvs(ref: dict, cand: dict) -> list[Check | None]:
    checks: list[Check | None] = [_match('Vrwm', ref.get('vr'), cand.get('vr'), _volt, ok=0.02, worse=0.06)]
    if ref.get('bidirectional') != cand.get('bidirectional'):
        checks.append(Check('Полярность', 'двунаправленный' if ref.get('bidirectional') else 'однонаправленный',
                            'двунаправленный' if cand.get('bidirectional') else 'однонаправленный', 'bad'))
    return checks


def _resistor(ref: dict, cand: dict) -> list[Check | None]:
    return [
        _match('Сопротивление', ref.get('ohm'), cand.get('ohm'), format_ohm, ok=0.005, worse=0.02),
        _compare('Допуск', ref.get('tol'), cand.get('tol'), lambda v: f'{v:g} %', high=False, ok=1.0, worse=1.0),
        _compare('Мощность', ref.get('pd'), cand.get('pd'), _watt, ok=1.0, worse=0.99),
    ]


def _capacitor(ref: dict, cand: dict) -> list[Check | None]:
    checks: list[Check | None] = [
        _match('Ёмкость', ref.get('farad'), cand.get('farad'), format_farad, ok=0.03, worse=0.25),
        _compare('Напряжение', ref.get('vr'), cand.get('vr'), _volt),
        _compare('Допуск', ref.get('tol'), cand.get('tol'), lambda v: f'{v:g} %', high=False, ok=1.0, worse=2.0),
    ]
    want, have = ref.get('dielectric'), cand.get('dielectric')
    if want:
        if not have:
            checks.append(Check('Диэлектрик', want, 'не указано', 'unknown'))
        else:
            status = 'ok' if DIELECTRIC_RANK.get(have, 1) >= DIELECTRIC_RANK.get(want, 1) else 'worse'
            checks.append(Check('Диэлектрик', want, have, status))
    if bool(ref.get('electrolytic')) != bool(cand.get('electrolytic')):
        checks.append(Check('Тип', 'электролит' if ref.get('electrolytic') else 'керамика',
                            'электролит' if cand.get('electrolytic') else 'керамика', 'bad'))
    return checks


COMPARE = {'mosfet': _mosfet, 'bjt': _bjt, 'diode': _diode, 'schottky': _diode, 'zener': _zener, 'tvs': _tvs,
           'resistor': _resistor, 'capacitor': _capacitor}


def compare_parts(spec: Spec, cand_params: dict, cand_pkg_hint: str | None = None) -> tuple[str, list[Check], list[str]]:
    """(verdict, checks, reasons) of a candidate against the reference."""
    kind = spec.kind
    if kind not in COMPARE:
        return 'no', [], ['для такого типа детали сравнение не поддерживается']
    checks = [c for c in COMPARE[kind](spec.params, cand_params) if c is not None]
    cand_pkg = cand_params.get('pkg') or cand_pkg_hint
    package_ok = None
    if spec.pkg:
        if not cand_pkg:
            checks.append(Check('Корпус', spec.pkg, 'не указан', 'unknown'))
        elif packages_compatible(spec.pkg, cand_pkg):
            status = 'ok'
            if spec.pkg != cand_pkg:
                status = 'worse'                                  # TO-220 and TO-220F: same holes, different tab
            checks.append(Check('Корпус', spec.pkg, cand_pkg, status))
            package_ok = True
        else:
            checks.append(Check('Корпус', spec.pkg, cand_pkg, 'bad'))
            package_ok = False
    if spec.mount and cand_params.get('mount') and spec.mount != cand_params['mount']:
        checks.append(Check('Монтаж', spec.mount.upper(), cand_params['mount'].upper(), 'bad'))
        package_ok = False
    if (spec.pkg in VARYING_PINOUT or cand_pkg in VARYING_PINOUT) and kind in ('mosfet', 'bjt', 'diode', 'schottky', 'tvs', 'zener'):
        checks.append(Check('Расположение выводов', 'по даташиту', 'по даташиту', 'unknown', 'у этого корпуса порядок выводов зависит от детали'))
    hard = [c for c in checks if c.status == 'bad' and c.label not in ('Корпус', 'Монтаж')]
    soft = [c for c in checks if c.status in ('worse', 'unknown')]
    if hard:
        return 'no', checks, [f'{c.label}: {c.cand} при {c.ref}' for c in hard]
    if package_ok is False:
        return 'other-pkg', checks, [f'{c.label}: {c.cand} вместо {c.ref}' for c in checks if c.status == 'bad']
    reasons = [f'{c.label}: {c.cand} при {c.ref}' for c in soft if c.status == 'worse']
    missing = [c.label for c in soft if c.status == 'unknown' and c.cand == 'не указано']
    datasheet = [c.label for c in soft if c.status == 'unknown' and c.cand != 'не указано']
    if missing:
        reasons.append('не указано в магазине: ' + ', '.join(missing))
    if datasheet:
        reasons.append('сверить по даташиту: ' + ', '.join(datasheet))
    return ('check' if soft else 'drop-in'), checks, reasons


# ---- search ---------------------------------------------------------------------------------------------

def find_analogs(db: Database, spec: Spec, *, shops: list[str] | None = None, in_stock: bool = False,
                 include_no: bool = False, limit: int = 40) -> list[Analog]:
    """Candidates of the same kind, grouped by part number across the shops, best verdict and cheapest first."""
    pool = KIND_POOL.get(spec.kind)
    if pool is None:
        return []
    own = norm_mpn(spec.mpn)
    rows = []
    for row in db.by_kind(pool, shops=shops):
        if own and row['mpn_norm'] == own:
            continue
        if in_stock and row['stock_state'] == 'out':
            continue
        rows.append((0.0, row, [], 0))
    out: list[Analog] = []
    for group in group_rows(rows):
        verdict, checks, reasons = compare_parts(spec, group.params)
        if spec.kind in SAME_CASE_ONLY and any(c.label in ('Корпус', 'Монтаж') and c.status == 'bad' for c in checks):
            continue
        if verdict == 'no' and not include_no:
            continue
        out.append(Analog(group, verdict, checks, reasons))
    out.sort(key=lambda a: (RANK[a.verdict], a.open, not a.in_stock, a.group.best['unit_price'] if a.group.best else 1e9, a.group.key))
    return out[:limit]


def analogs_for_mpn(db: Database, mpn: str, **options) -> tuple[Spec | None, list[Analog]]:
    """Analogs of a part number that the catalog holds (the offer with the most parsed parameters is the reference)."""
    offers = [o for o in db.by_mpn(mpn) if o['kind'] in KIND_POOL]
    if not offers:
        return None, []
    merged: dict = {}
    for offer in sorted(offers, key=lambda o: len(o['params'])):
        merged.update(offer['params'])
    best = max(offers, key=lambda o: len(o['params']))
    spec = Spec(title=best['title'], params=merged, pkg=merged.get('pkg'), mpn=best.get('mpn') or mpn)
    return spec, find_analogs(db, spec, **options)
