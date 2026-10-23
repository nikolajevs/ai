"""Electrical parameters from shop titles and property lists.

Salvats writes 'FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263',
Electrobase and Semikom write the TME style 'Transistor: N-MOSFET | unipolar | 60V | 340mA | 1.08W | SOT23'.
Both are split into tokens and every token is classified on its own, so '(1...3V)' of a logic level
range is never taken for the drain-source voltage.
"""
from __future__ import annotations

import re

from .normalize import fold, ohm_code, si

# canonical package -> pattern; the order matters (TO-220F before TO-220)
_PACKAGES = (
    ('TO-220F', r'ITO-?220|TO-?220F[P]?\b|TO-?220-?3?\s*FP|TO-?220\s*ISO'),
    ('TO-220', r'TO-?220(?:AB|-?3L?)?(?![0-9A-Z])'),
    ('TO-247', r'TO-?247(?:-?3|AC|AD)?(?![0-9A-Z])'),
    ('TO-3P', r'TO-?3PN?(?![0-9A-Z])'),
    ('TO-263', r'TO-?263(?:-?[2-7]|AB)?(?![0-9A-Z])|D2-?PAK|SOT-?404'),
    ('TO-252', r'TO-?252(?:-?[23])?(?![0-9A-Z])|\bD-?PAK|SOT-?428'),
    ('TO-251', r'TO-?251|\bI-?PAK'),
    ('TO-92', r'TO-?92(?![0-9A-Z])'),
    ('TO-126', r'TO-?126'),
    ('TO-262', r'TO-?262|I2-?PAK'),
    ('SOT-223', r'SOT-?223'),
    ('SOT-143', r'SOT-?143'),
    ('SOT-89', r'SOT-?89'),
    ('SOT-26', r'SOT-?26(?![0-9])|SC-?74'),
    ('SOT-343', r'SOT-?343'),
    ('SOT-23', r'SOT-?23(?:-?3)?(?![0-9A-Z-])'),
    ('SOT-323', r'SOT-?323|SC-?70'),
    ('SO-8', r'\bSO-?8\b|SOIC-?8|SOP-?8'),
    ('SMB', r'\bSMB\b|DO-?214AA'),
    ('SMC', r'\bSMC\b|DO-?214AB'),
    ('SMA', r'\bSMA\b|DO-?214AC'),
    ('SOD-123', r'SOD-?123'),
    ('SOD-323', r'SOD-?323'),
    ('MiniMELF', r'MINIMELF|SOD-?80'),
    ('DO-41', r'DO-?41'),
    ('DO-201', r'DO-?201'),
    ('SMD2512', r'(?<![0-9])2512(?![0-9])'),
    ('SMD1206', r'(?<![0-9])1206(?![0-9])'),
    ('SMD0805', r'(?<![0-9])0805(?![0-9])'),
    ('SMD0603', r'(?<![0-9])0603(?![0-9])'),
    ('SMD0402', r'(?<![0-9])0402(?![0-9])'),
)
_PACKAGE_RE = [(name, re.compile(pattern, re.I)) for name, pattern in _PACKAGES]

# packages that share a footprint (the tab insulation differs, which the analog finder reports)
FOOTPRINT_GROUPS = (
    {'TO-220', 'TO-220F'},
    {'TO-252'},
    {'TO-263'},
)


_GENERIC_PACKAGE = re.compile(r'\b(SOT|TO|DO|SOD|DIP|SIP)-?(\d+[A-Z]*)\b', re.I)


def canon_package(text: str | None) -> str | None:
    """'D2PAK' / 'TO263' / 'SOT404' -> 'TO-263'; None when the text names no known package."""
    if not text:
        return None
    for name, pattern in _PACKAGE_RE:
        if pattern.search(text):
            return name
    match = _GENERIC_PACKAGE.search(text)
    if match:
        return f'{match.group(1).upper()}-{match.group(2).upper()}'
    return None


def packages_compatible(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a == b or any(a in group and b in group for group in FOOTPRINT_GROUPS)


def tokens(title: str | None) -> list[str]:
    """Title split at ';', '|' and ',' that are not inside brackets, stripped; a '=> IRF3710' hint is dropped."""
    if not title:
        return []
    title = re.sub(r'\s*=>\s*[^,;|]*', '', title)
    out, depth, current = [], 0, []
    for ch in title:
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth = max(0, depth - 1)
        if ch in ';|,' and depth == 0:
            out.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    out.append(''.join(current).strip())
    return [t for t in out if t]


def detect_kind(title: str | None, props: dict | None = None, category: str | None = None) -> str:
    text = fold(f'{title or ""} {category or ""} {(props or {}).get("Type of transistor", "")}')
    if re.search(r'\b[np]-?(?:mosfet|fet)\b|n-kanalu lauku|p-kanalu lauku|lauku tranzistor|mosfet', text):
        return 'mosfet'
    if re.search(r'\bigbt\b', text):
        return 'igbt'
    if re.search(r'\bnpn\b|\bpnp\b|bipolar', text):
        return 'bjt'
    if re.search(r'zener|zenera|stabilitron', text):
        return 'zener'
    if re.search(r'\btvs\b|transil|supresor|drosibas diod|\besd\b', text):
        return 'tvs'
    if re.search(r'schottky|sotki', text):
        return 'schottky'
    if re.search(r'\bdiod|taisngriez', text):
        return 'diode'
    if re.search(r'rezistor|resistor|\bshunt|sunt', text):
        return 'resistor'
    if re.search(r'kondensator|capacitor|\bmlcc\b|elektrolit', text):
        return 'capacitor'
    if re.search(r'induktiv|inductor|drossel|choke', text):
        return 'inductor'
    if re.search(r'\bfuse|drosinatajs', text):
        return 'fuse'
    return 'other'


def _first(pattern: str, tokens_: list[str], flags: int = 0):
    rx = re.compile(pattern, flags)
    for tok in tokens_:
        match = rx.fullmatch(tok)
        if match:
            return match
    return None


def _volt(tok: str) -> tuple[float, bool] | None:
    match = re.fullmatch(r'([±+\-])?\s*(\d+(?:[.,]\d+)?)\s*V', tok.strip())
    if not match:
        return None
    return float(match.group(2).replace(',', '.')), match.group(1) == '±'


def _amps(tok: str) -> float | None:
    match = re.fullmatch(r'[+\-]?\s*(\d+(?:[.,]\d+)?)\s*(m?)A', tok.strip())
    if not match:
        return None
    return float(match.group(1).replace(',', '.')) * (1e-3 if match.group(2) else 1.0)


def _watts(tok: str) -> float | None:
    match = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(m?)W', tok.strip())
    if not match:
        return None
    return float(match.group(1).replace(',', '.')) * (1e-3 if match.group(2) else 1.0)


def _mount(title: str | None, props: dict, category: str | None) -> str | None:
    value = fold(props.get('Mounting') or '')
    if value:
        return 'smd' if 'smd' in value else 'tht' if 'tht' in value else None
    text = fold(f'{title or ""} {category or ""}')
    if re.search(r'\bsmd\b', text):
        return 'smd'
    if re.search(r'\btht\b', text):
        return 'tht'
    return None


def _prop(props: dict, *names: str) -> str | None:
    lowered = {k.lower(): v for k, v in props.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _transistor_common(toks: list[str], props: dict, out: dict) -> None:
    """Fields shared by MOSFET, IGBT and BJT titles."""
    # '22E10N Tranzistors N-FET 100V' has no comma before the voltage: also try the last word
    words = [w for t in toks if ' ' in t for w in t.split()]
    for tok in toks + words:
        volt = _volt(tok)
        if volt:
            value, plus_minus = volt
            if plus_minus:
                out.setdefault('vgs_max', value)
            else:
                out.setdefault('vds', value)
            continue
        if re.match(r'(?:Idm|Ipk)\s*:', tok, re.I):
            out.setdefault('idm', si(tok.split(':', 1)[1], 'A'))
            continue
        amp = _amps(tok)
        if amp is not None:
            out.setdefault('id', amp)
            continue
        watt = _watts(tok)
        if watt is not None:
            out.setdefault('pd', watt)
    pkg = canon_package(_prop(props, 'Case')) or next((canon_package(t) for t in toks if canon_package(t)), None)
    if pkg:
        out['pkg'] = pkg


def _mosfet(title: str | None, props: dict, category: str | None) -> dict:
    toks = tokens(title)
    out: dict = {}
    head = fold(f'{title or ""} {_prop(props, "Type of transistor") or ""}')
    polarity = re.search(r'\b([np])-?\s?(?:mosfet|fet)\b', head)
    if not polarity:
        polarity = re.search(r'\b([np])-kanalu lauku', fold(category or ''))
    if polarity:
        out['polarity'] = polarity.group(1).upper()
    _transistor_common(toks, props, out)
    if 'vds' in out and out.get('polarity') is None and re.search(r'(?:^|[;|,]\s*)-\d', title or ''):
        out['polarity'] = 'P'
    rds = None
    for tok in toks:
        value = ohm_code(tok)
        if value is not None and re.fullmatch(r'\d*R\d*', tok):
            rds = value
            break
        milli = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*m(?:Ω|Ohm|ohm)', tok)
        if milli:
            rds = float(milli.group(1).replace(',', '.')) * 1e-3
            break
    # The title of a Salvats card gives the headline value (0R006 = 6 mΩ at 10 V); the TME-style property list gives
    # a value under test conditions it does not state (12.6 mΩ for the same part). The title wins, the other value is kept.
    prop_rds = si(_prop(props, 'On-state resistance', 'Rds(on)'), 'Ω') or si(_prop(props, 'On-state resistance', 'Rds(on)'), 'Ohm')
    if rds is not None:
        out['rds_mohm'], out['rds_src'] = round(rds * 1000, 3), 'title'
        if prop_rds is not None and abs(prop_rds - rds) > 0.02 * rds:
            out['rds_alt_mohm'] = round(prop_rds * 1000, 3)
    elif prop_rds is not None:
        out['rds_mohm'], out['rds_src'] = round(prop_rds * 1000, 3), 'props'
    if re.search(r'\blogl|logic', fold(title or '')):
        out['logic_level'] = True
        match = re.search(r'LogL\w*\(\s*[\d.]+\s*\.\.\.\s*([\d.]+)\s*V\)', title or '', re.I)
        if match and float(match.group(1)) <= 5:
            out['vgs_th_max'] = float(match.group(1))
    for key, names, unit in (('vds', ('Drain-source voltage',), 'V'), ('id', ('Drain current',), 'A'),
                             ('pd', ('Power',), 'W'), ('vgs_max', ('Gate-source voltage',), 'V'),
                             ('qg_nc', ('Gate charge',), 'C')):
        value = si(_prop(props, *names), unit)
        if value is not None:
            out[key] = round(value * 1e9, 3) if key == 'qg_nc' else abs(value)
    return out


def _bjt(title: str | None, props: dict, category: str | None) -> dict:
    toks = tokens(title)
    out: dict = {}
    polarity = re.search(r'\b(npn|pnp)\b', fold(f'{title or ""} {category or ""}'))
    if polarity:
        out['polarity'] = polarity.group(1).upper()
    _transistor_common(toks, props, out)
    if 'vds' in out:
        out['vce'] = out.pop('vds')
    if 'id' in out:
        out['ic'] = out.pop('id')
    return out


def _diode(title: str | None, props: dict, category: str | None, kind: str) -> dict:
    toks = tokens(title)
    out: dict = {}
    for tok in toks:
        volt = _volt(tok)
        if volt:
            out.setdefault('vr' if kind != 'zener' else 'vz', volt[0])
            continue
        dual = re.fullmatch(r'(\d)\s*x\s*(\d+(?:[.,]\d+)?)\s*(m?)A', tok)
        if dual:
            out.setdefault('if', float(dual.group(2).replace(',', '.')) * (1e-3 if dual.group(3) else 1.0))
            out['dual'] = True
            continue
        amp = _amps(tok)
        if amp is not None:
            out.setdefault('if', amp)
            continue
        watt = _watts(tok)
        if watt is not None:
            out.setdefault('pd', watt)
    # Salvats puts the Zener voltage in front of the word: '8.2V Stabilitrons SMD, BZV55-...'
    lead = re.match(r'(\d+(?:[.,]\d+)?)\s*V\b', title or '')
    if kind == 'zener' and lead:
        out['vz'] = float(lead.group(1).replace(',', '.'))
    if kind == 'tvs':
        standoff = re.search(r'(\d+(?:[.,]\d+)?)\s*V\b', title or '')
        if standoff and 'vr' not in out:
            out['vr'] = float(standoff.group(1).replace(',', '.'))
        out['bidirectional'] = bool(re.search(r'bidirectional|divvirzien|bi-?dir', fold(title or '')))
    pkg = canon_package(_prop(props, 'Case')) or next((canon_package(t) for t in toks if canon_package(t)), None)
    pkg = pkg or canon_package(title)
    if pkg:
        out['pkg'] = pkg
    return out


def _resistor(title: str | None, props: dict, category: str | None) -> dict:
    toks = tokens(title)
    out: dict = {}
    lead = re.match(r'(\w+?)-(\d{4})-(\d+(?:[.,]\d+)?)%', title or '')
    if lead and ohm_code(lead.group(1)) is not None:
        out['ohm'] = ohm_code(lead.group(1))
        out['tol'] = float(lead.group(3).replace(',', '.'))
    for tok in toks:
        code = ohm_code(tok)
        if code is not None and re.search(r'\d', tok) and 'ohm' not in out:
            out['ohm'] = code
            continue
        match = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*([kKMm]?)\s*(?:Ω|Ohm|ohm)', tok)
        if match and 'ohm' not in out:
            out['ohm'] = float(match.group(1).replace(',', '.')) * {'': 1.0, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'm': 1e-3}[match.group(2)]
            continue
        tol = re.fullmatch(r'±?\s*(\d+(?:[.,]\d+)?)\s*%', tok)
        if tol:
            out.setdefault('tol', float(tol.group(1).replace(',', '.')))
            continue
        watt = _watts(tok)
        if watt is not None:
            out.setdefault('pd', watt)
    fraction = re.search(r'\b(\d)/(\d+)\s*W\b', title or '')
    if fraction and 'pd' not in out:
        out['pd'] = int(fraction.group(1)) / int(fraction.group(2))
    pkg = canon_package(title)
    if pkg:
        out['pkg'] = pkg
    return out


_TOLERANCE_CODE = {'F': 1.0, 'G': 2.0, 'J': 5.0, 'K': 10.0, 'M': 20.0}
_FARAD_SCALE = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'mk': 1e-6, 'm': 1e-3, None: 1.0, '': 1.0}


def _capacitor(title: str | None, props: dict, category: str | None) -> dict:
    toks = tokens(title)
    out: dict = {}
    # '330pF-1206-NPO-50-J SMD Kondensators' and '10/50V 105C, Ø5x11mm' (microfarad / volt)
    ceramic = re.match(r'(\d+(?:[.,]\d+)?)\s*(p|n|u|µ|μ|mk)F-(\d{4})-(\w+)-(\d+(?:[.,]\d+)?)-(\w)', title or '')
    if ceramic:
        out['farad'] = float(ceramic.group(1).replace(',', '.')) * _FARAD_SCALE[ceramic.group(2)]
        out['dielectric'] = 'C0G' if ceramic.group(4).upper() == 'NPO' else ceramic.group(4).upper()
        out['vr'] = float(ceramic.group(5).replace(',', '.'))
        if ceramic.group(6).upper() in _TOLERANCE_CODE:
            out['tol'] = _TOLERANCE_CODE[ceramic.group(6).upper()]
    electrolytic = re.match(r'(\d+(?:[.,]\d+)?)/(\d+(?:[.,]\d+)?)V\b', title or '')
    if electrolytic:
        out['farad'] = float(electrolytic.group(1).replace(',', '.')) * 1e-6
        out['vr'] = float(electrolytic.group(2).replace(',', '.'))
        out['electrolytic'] = True
    for tok in toks:
        match = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(p|n|u|µ|μ|m|mk)?F', tok.strip())
        if match and 'farad' not in out:
            out['farad'] = float(match.group(1).replace(',', '.')) * _FARAD_SCALE[match.group(2)]
            continue
        volt = _volt(tok)
        if volt:
            out.setdefault('vr', volt[0])
            continue
        tol = re.fullmatch(r'±?\s*(\d+(?:[.,]\d+)?)\s*%', tok)
        if tol:
            out.setdefault('tol', float(tol.group(1).replace(',', '.')))
            continue
        dielectric = re.fullmatch(r'(X7R|X5R|X7S|X6S|X8R|C0G|NP0|Y5V|Z5U)', tok.strip(), re.I)
        if dielectric:
            out['dielectric'] = 'C0G' if dielectric.group(1).upper() == 'NP0' else dielectric.group(1).upper()
    pkg = canon_package(title)
    if pkg:
        out['pkg'] = pkg
    return out


def extract(title: str | None, props: dict | None = None, category: str | None = None) -> dict:
    """Parameter dict {'kind': ..., ...}; unknown fields are absent, not None."""
    props = props or {}
    kind = detect_kind(title, props, category)
    out: dict = {}
    if kind == 'mosfet':
        out = _mosfet(title, props, category)
    elif kind == 'igbt':
        out = _mosfet(title, props, category)
    elif kind == 'bjt':
        out = _bjt(title, props, category)
    elif kind in ('diode', 'schottky', 'zener', 'tvs'):
        out = _diode(title, props, category, kind)
    elif kind == 'resistor':
        out = _resistor(title, props, category)
    elif kind == 'capacitor':
        out = _capacitor(title, props, category)
    mount = _mount(title, props, category)
    if mount:
        out['mount'] = mount
    out = {k: v for k, v in out.items() if v is not None}
    out['kind'] = kind
    return out


def describe(params: dict) -> str:
    """Short human line for tables: 'N-MOSFET 60 В 80 А 6 мОм D2PAK'."""
    kind = params.get('kind')
    parts: list[str] = []
    if kind == 'mosfet':
        parts.append(f"{params.get('polarity', '?')}-MOSFET")
        if 'vds' in params:
            parts.append(f"{params['vds']:g} В")
        if 'id' in params:
            parts.append(f"{params['id']:g} А")
        if 'rds_mohm' in params:
            parts.append(f"{params['rds_mohm']:g} мОм")
        if params.get('logic_level'):
            parts.append('logic')
    elif kind == 'bjt':
        parts.append(params.get('polarity', 'BJT'))
        for key, suffix in (('vce', 'В'), ('ic', 'А'), ('pd', 'Вт')):
            if key in params:
                parts.append(f'{params[key]:g} {suffix}')
    elif kind in ('diode', 'schottky', 'zener', 'tvs'):
        parts.append({'diode': 'диод', 'schottky': 'Шоттки', 'zener': 'стабилитрон', 'tvs': 'TVS'}[kind])
        for key, suffix in (('vz', 'В'), ('vr', 'В'), ('if', 'А'), ('pd', 'Вт')):
            if key in params:
                parts.append(f'{params[key]:g} {suffix}')
    elif kind == 'resistor':
        parts.append('резистор')
        if 'ohm' in params:
            parts.append(format_ohm(params['ohm']))
        if 'tol' in params:
            parts.append(f"{params['tol']:g}%")
        if 'pd' in params:
            parts.append(f"{params['pd']:g} Вт")
    elif kind == 'capacitor':
        parts.append('конденсатор')
        if 'farad' in params:
            parts.append(format_farad(params['farad']))
        if 'vr' in params:
            parts.append(f"{params['vr']:g} В")
        if 'dielectric' in params:
            parts.append(params['dielectric'])
    if params.get('pkg'):
        parts.append(params['pkg'])
    if params.get('mount') and not params.get('pkg'):
        parts.append(params['mount'].upper())
    return ' '.join(parts)


def format_ohm(value: float) -> str:
    for scale, suffix in ((1e6, 'М'), (1e3, 'к')):
        if value >= scale:
            return f'{value / scale:g}{suffix}Ом'
    if value >= 1:
        return f'{value:g} Ом'
    return f'{value * 1000:g} мОм'


def format_farad(value: float) -> str:
    for scale, suffix in ((1e-6, 'мкФ'), (1e-9, 'нФ'), (1e-12, 'пФ')):
        if value >= scale * 0.999:
            return f'{value / scale:g} {suffix}'
    return f'{value:g} Ф'
