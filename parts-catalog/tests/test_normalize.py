import pytest

from partscat import normalize as n


@pytest.mark.parametrize('text,expected', [
    ('2.25 €', 2.25),
    ('0,0649 €', 0.0649),
    ('4,86 € Ar PVN / gb', 4.86),
    ('1 234,50 €', 1234.5),
    ('1.234,50', 1234.5),
    ('1,234.50', 1234.5),
    ('Cena: 1.98 €', 1.98),
    ('no digits', None),
    ('', None),
    (None, None),
    (3, 3.0),
])
def test_parse_number(text, expected):
    assert n.parse_number(text) == expected


def test_parse_price_rounds_to_four_places():
    assert n.parse_price('0,06490001 €') == 0.0649


@pytest.mark.parametrize('title,qty', [
    ('100nF, 50V, 0805, (10gab,), MLCC, X7R, ±5%, SMD Kondensators, 0805', 10),
    ('1K, 0603 (1.8x0.8mm), (10gab), 50V, 0.1W, ±5%, SMD, Rezistors, 0603', 10),
    ('FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', 1),
    ('Plate 1gab', 1),
    ('', 1),
    (None, 1),
])
def test_parse_pack(title, qty):
    assert n.parse_pack(title) == qty


@pytest.mark.parametrize('text,expected', [
    ('Pieejams piegādātāja noliktavā >1000 gab.', (1000, True, 'in')),
    ('Pieejams piegādātāja noliktavā 220 gab.', (220, False, 'in')),
    ('4', (4, False, 'in')),
    ('0', (0, False, 'out')),
    ('Nav noliktavā', (0, False, 'out')),
    ('Pasūtāms', (None, False, 'order')),
    ('Pieejams', (None, False, 'in')),
    ('', (None, False, 'unknown')),
    (None, (None, False, 'unknown')),
])
def test_parse_stock(text, expected):
    assert n.parse_stock(text) == expected


def test_norm_mpn_keeps_letters_and_digits_only():
    assert n.norm_mpn('BC847B-DIO') == 'BC847BDIO'
    assert n.norm_mpn('lm3429mh/nopb') == 'LM3429MHNOPB'
    assert n.norm_mpn('SS5P10-M3/86A') == 'SS5P10M386A'
    assert n.norm_mpn(None) == ''


def test_fold_removes_diacritics():
    assert n.fold('Diodes Šotki') == 'diodes sotki'
    assert n.fold('Ražotāja preces kods') == 'razotaja preces kods'


@pytest.mark.parametrize('text,unit,expected', [
    ('12.6mΩ', 'Ω', 0.0126),
    ('60V', 'V', 60.0),
    ('135 nC', 'C', 135e-9),
    ('±20V', 'V', 20.0),
    ('242W', 'W', 242.0),
    ('1,5A', 'A', 1.5),
    ('80mA', 'A', 0.08),
    ('nothing', 'V', None),
    (None, 'V', None),
])
def test_si(text, unit, expected):
    value = n.si(text, unit)
    assert value == pytest.approx(expected) if expected is not None else value is None


@pytest.mark.parametrize('token,expected', [
    ('0R0115', 0.0115), ('0R2', 0.2), ('4K7', 4700.0), ('10K', 10000.0), ('1M', 1e6),
    ('100R', 100.0), ('R040', 0.04), ('TO-220', None), ('R', None), (None, None),
])
def test_ohm_code(token, expected):
    value = n.ohm_code(token)
    assert value == pytest.approx(expected) if expected is not None else value is None
