"""Parsing helpers shared by the shop adapters: numbers, prices, pack sizes, stock, part numbers."""
from __future__ import annotations

import re
import unicodedata

_NUMBER = re.compile(r'\d[\d\s .,]*')
_PACK = re.compile(r'\(?\b(\d{1,5})\s*(?:gab|pcs|pc|шт)\b\.?,?\)?', re.I)


def parse_number(text) -> float | None:
    """First number in the text: '1 234,50' -> 1234.5, '0,0649 €' -> 0.0649, '2.25' -> 2.25."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = _NUMBER.search(str(text))
    if not match:
        return None
    raw = re.sub(r'[\s ]', '', match.group(0)).rstrip('.,')
    if not raw:
        return None
    if ',' in raw and '.' in raw:
        decimal = ',' if raw.rfind(',') > raw.rfind('.') else '.'
        thousands = '.' if decimal == ',' else ','
        raw = raw.replace(thousands, '').replace(decimal, '.')
    elif raw.count(',') == 1:
        raw = raw.replace(',', '.')
    elif raw.count(',') > 1 or raw.count('.') > 1:
        raw = raw.replace(',', '').replace('.', '')
    try:
        return float(raw)
    except ValueError:
        return None


def parse_price(text) -> float | None:
    """Price in EUR from shop text such as '2.25 €', '0,0649 € /', '4,86 € Ar PVN / gb'."""
    value = parse_number(text)
    return None if value is None else round(value, 4)


def parse_pack(title: str | None) -> int:
    """Pieces per sale unit from a title such as '100nF, 50V, (10gab,), MLCC'; 1 when not a pack."""
    if not title:
        return 1
    match = _PACK.search(title)
    if match:
        qty = int(match.group(1))
        if qty > 1:
            return qty
    return 1


def parse_stock(text: str | None) -> tuple[int | None, bool, str]:
    """Stock text -> (pieces, is_lower_bound, state) with state in in / out / order / unknown.

    '>1000 gab.' -> (1000, True, 'in'); '220 gab.' -> (220, False, 'in'); 'nav noliktavā' -> (0, False, 'out').
    """
    if not text:
        return None, False, 'unknown'
    low = text.lower()
    if re.search(r'nav\s+(pieejam|noliktav)|izpārdots|out of stock|нет в наличии', low):
        return 0, False, 'out'
    match = re.search(r'(>|≥|vairāk nekā|more than)?\s*(\d[\d\s]*)\s*(?:gab|pcs|шт)?', text)
    if match and re.search(r'\d', text):
        qty = int(re.sub(r'\s', '', match.group(2)))
        bound = bool(match.group(1))
        return qty, bound, 'in' if qty > 0 else 'out'
    if re.search(r'pasūtām|pasūtījum|uz pasūt|on order|под заказ', low):
        return None, False, 'order'
    if re.search(r'pieejam|noliktavā|in stock|в наличии', low):
        return None, False, 'in'
    return None, False, 'unknown'


def norm_mpn(text: str | None) -> str:
    """Matching key of a part number: upper case letters and digits only (BC847B-DIO -> BC847BDIO)."""
    if not text:
        return ''
    return re.sub(r'[^0-9A-Z]', '', text.upper())


def fold(text: str | None) -> str:
    """Lower case without diacritics, for searching Latvian titles ('Šotki' -> 'sotki')."""
    if not text:
        return ''
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def clean(text: str | None) -> str:
    """Collapse whitespace; None -> ''."""
    return re.sub(r'\s+', ' ', text or '').strip()


_SI = {'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'µ': 1e-6, 'μ': 1e-6, 'm': 1e-3, '': 1.0, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9}


def si(text: str | None, unit: str) -> float | None:
    """Value of '12.6mΩ' / '60V' / '135 nC' / '±20V' in base units, or None; unit is the letter(s) after the prefix."""
    if not text:
        return None
    pattern = r'(\d+(?:[.,]\d+)?)\s*([pnuµμmkKMG]?)\s*' + re.escape(unit) + r'(?![A-Za-z])'
    match = re.search(pattern, text)
    if not match:
        return None
    return float(match.group(1).replace(',', '.')) * _SI[match.group(2)]


def ohm_code(token: str | None) -> float | None:
    """Resistance written in the 'R' notation: 0R0115 -> 0.0115, 4K7 -> 4700, 0R2 -> 0.2, 1M -> 1e6."""
    if not token:
        return None
    match = re.fullmatch(r'(\d*)([RrKkMm])(\d*)', token.strip())
    if not match or not (match.group(1) or match.group(3)):
        return None
    scale = {'r': 1.0, 'k': 1e3, 'm': 1e6}[match.group(2).lower()]
    return float(f'{match.group(1) or 0}.{match.group(3) or 0}') * scale
