import pytest

from partscat import params


def test_salvats_mosfet_title():
    got = params.extract('FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263',
                         category='N kanalu lauku tranzistori SMD')
    assert got['kind'] == 'mosfet' and got['polarity'] == 'N'
    assert got['vds'] == 60 and got['vgs_max'] == 20 and got['id'] == 80 and got['pd'] == 242
    assert got['rds_mohm'] == pytest.approx(6.0)
    assert got['pkg'] == 'TO-263' and got['mount'] == 'smd' and got['logic_level'] is True


def test_voltage_without_comma_before_it():
    got = params.extract('22E10N Tranzistors N-FET 100V, ±20V, 22A, 72W, 0R0115, TO-220')
    assert got['vds'] == 100 and got['id'] == 22 and got['rds_mohm'] == pytest.approx(11.5)


def test_arrow_hint_is_dropped():
    got = params.extract('HUF75639P Tranzistors N-FET, 100V, ±20V, 56A, 200W, 0R025 => IRF3710, TO-220')
    assert got['rds_mohm'] == pytest.approx(25.0) and got['pkg'] == 'TO-220'


def test_tme_style_mosfet():
    got = params.extract('Transistor: N-MOSFET | unipolar | 60V | 340mA | Idm: 2A | 1.08W | SOT23')
    assert got['kind'] == 'mosfet' and got['polarity'] == 'N' and got['vds'] == 60
    assert got['id'] == pytest.approx(0.34) and got['idm'] == pytest.approx(2.0)
    assert got['pd'] == pytest.approx(1.08) and got['pkg'] == 'SOT-23'


def test_semicolon_style_and_package_alias():
    got = params.extract('Transistor: N-MOSFET; unipolar; 60V; 120A; 306W; D2PAK,SOT404')
    assert got['pkg'] == 'TO-263' and got['id'] == 120


def test_title_rds_wins_and_the_property_value_is_kept_beside_it():
    # Salvats writes the headline 6 mΩ (at 10 V) in the title; the property list says 12.6 mΩ without its test condition
    props = {'Drain-source voltage': '60V', 'Drain current': '80A', 'Power': '242W', 'Case': 'D2PAK',
             'Gate-source voltage': '±20V', 'On-state resistance': '12.6mΩ', 'Mounting': 'SMD', 'Gate charge': '135nC'}
    got = params.extract('FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', props)
    assert got['rds_mohm'] == pytest.approx(6.0) and got['rds_src'] == 'title' and got['rds_alt_mohm'] == pytest.approx(12.6)
    assert got['qg_nc'] == pytest.approx(135) and got['pkg'] == 'TO-263' and got['mount'] == 'smd'


def test_property_rds_is_used_when_the_title_has_none():
    props = {'Drain-source voltage': '60V', 'On-state resistance': '12.6mΩ'}
    got = params.extract('Transistor: N-MOSFET; unipolar; 60V; 80A; D2PAK', props)
    assert got['rds_mohm'] == pytest.approx(12.6) and got['rds_src'] == 'props' and 'rds_alt_mohm' not in got


def test_agreeing_property_value_adds_no_alternative():
    props = {'On-state resistance': '6mΩ'}
    got = params.extract('FDB5800 SMD Tranzistors N-FET, 60V, 80A, 0R006, TO-263', props)
    assert got['rds_mohm'] == pytest.approx(6.0) and 'rds_alt_mohm' not in got


def test_p_channel_from_negative_voltage_and_category():
    got = params.extract('IRF9540 Tranzistors P-FET, -100V, -19A, 150W, 0R2, TO-220')
    assert got['polarity'] == 'P' and got['vds'] == 100 and got['id'] == 19


def test_bjt():
    got = params.extract('BC847C(1G) SMD Tranzistors, NPN, 50V, 0.1A, 300MHz, SOT23')
    assert got['kind'] == 'bjt' and got['polarity'] == 'NPN' and got['vce'] == 50 and got['ic'] == pytest.approx(0.1)
    assert got['pkg'] == 'SOT-23'


def test_schottky_dual():
    got = params.extract('42CTQ030S, SMD, 2xDiodes Schottky, 30V, 2x20A, (Anod-Katod-Anod), TO-263')
    assert got['kind'] == 'schottky' and got['vr'] == 30 and got['if'] == 20 and got['dual'] is True


def test_zener_voltage_in_front_of_the_word():
    got = params.extract('8.2V Stabilitrons SMD, BZV55-..., ±5%, 0.5W, MiniMELF')
    assert got['kind'] == 'zener' and got['vz'] == pytest.approx(8.2) and got['pd'] == 0.5 and got['pkg'] == 'MiniMELF'


def test_tvs_direction():
    assert params.extract('SMAJ6.0CA SMD Supresors, 6V, max400W, bidirectional types, DO-214AA')['bidirectional'] is True
    assert params.extract('SMBJ48A(BUW) SMD Supresors, 48V, max600W, unidirectional types, SMB')['bidirectional'] is False


def test_resistors():
    got = params.extract('47K, 0603 (1.8x0.8mm), (10gab), 50V, 0.1W, ±5%, SMD, Rezistors, 0603')
    assert got['ohm'] == 47000 and got['pd'] == 0.1 and got['tol'] == 5 and got['pkg'] == 'SMD0603'
    got = params.extract('11K-1206-1% SMD Rezistors, 1206')
    assert got['ohm'] == 11000 and got['tol'] == 1 and got['pkg'] == 'SMD1206'


def test_capacitors():
    got = params.extract('100nF, 50V, 0805, (10gab,), MLCC, X7R, ±5%, SMD Kondensators, 0805')
    assert got['farad'] == pytest.approx(100e-9) and got['vr'] == 50 and got['dielectric'] == 'X7R' and got['tol'] == 5
    got = params.extract('330pF-1206-NPO-50-J SMD Kondensators, 1206')
    assert got['farad'] == pytest.approx(330e-12) and got['dielectric'] == 'C0G' and got['vr'] == 50 and got['tol'] == 5
    got = params.extract('10/50V 105C, Ø5x11mm, ±20%, Kondensatori zemas induktivitātes, 2000h')
    assert got['farad'] == pytest.approx(10e-6) and got['vr'] == 50 and got['electrolytic'] is True
    assert params.extract('2.2mkF, 25V, 0805, (10gab,), MLCC, X5R, ±10%, SMD Kondensators, 0805')['farad'] == pytest.approx(2.2e-6)


@pytest.mark.parametrize('text,expected', [
    ('D2PAK', 'TO-263'), ('TO263', 'TO-263'), ('SOT404', 'TO-263'), ('DPAK', 'TO-252'), ('TO-252-3', 'TO-252'),
    ('TO220-3', 'TO-220'), ('TO-220F', 'TO-220F'), ('TO-220AB', 'TO-220'), ('SOT23', 'SOT-23'), ('SO8', 'SO-8'),
    ('SOT-89', 'SOT-89'), ('DO-214AA', 'SMB'), ('nothing', None), (None, None),
])
def test_canon_package(text, expected):
    assert params.canon_package(text) == expected


def test_packages_compatible():
    assert params.packages_compatible('TO-220', 'TO-220F')
    assert params.packages_compatible('TO-252', 'TO-252')
    assert not params.packages_compatible('TO-252', 'TO-263')
    assert not params.packages_compatible(None, 'TO-220')


def test_describe():
    line = params.describe(params.extract('FDB5800 SMD Tranzistors N-FET, 60V, 80A, 242W, 0R006, TO-263'))
    assert line == 'N-MOSFET 60 В 80 А 6 мОм TO-263'


def test_extract_never_returns_none_values():
    assert all(v is not None for v in params.extract('Transistor: N-MOSFET | 60V | Idm: ?').values())
