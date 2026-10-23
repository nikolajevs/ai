import pytest

from partscat import analogs as an
from partscat.db import Database
from partscat.models import Offer


def put(db, shop, shop_id, title, mpn, price=1.0, stock=10, state='in', **kw):
    db.upsert(Offer(shop=shop, shop_id=shop_id, url=f'https://{shop}.example/{shop_id}', title=title, mpn=mpn, sale_price=price,
                    stock_qty=stock, stock_state=state, **kw))


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / 'c.db')
    put(d, 'salvats', 'ref', 'FDB5800 SMD Tranzistors N-FET, LogLev(1...25V), 60V, ±20V, 80A, 242W, 0R006, TO-263', 'FDB5800', 1.98, 4)
    put(d, 'salvats', 'a', 'IPB037N06N3 SMD Tranzistors N-FET, 60V, ±20V, 90A, 300W, 0R0037, TO-263', 'IPB037N06N3', 2.55, 20)
    put(d, 'salvats', 'b', 'IRF1010ESPBF SMD Tranzistors N-FET, 60V, ±20V, 84A, 200W, 0R012, TO-263', 'IRF1010ESPBF', 2.42, 9)
    put(d, 'salvats', 'c', 'IPP037N06L3 Tranzistors N-FET, LogLev(1...2.2V), 60V, ±20V, 90A, 300W, 0R0037, TO-220', 'IPP037N06L3', 2.2, 5)
    put(d, 'semikom', 'd', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK', 'FQB80N06', 2.0, 60)
    put(d, 'semikom', 'e', 'Transistor: P-MOSFET; unipolar; -60V; -80A; 242W; D2PAK', 'IRF5210S', 3.0, 60)
    put(d, 'semikom', 'f', 'Transistor: N-MOSFET; unipolar; 55V; 90A; 242W; D2PAK', 'LOW55V', 1.0, 60)
    put(d, 'electrobase', 'g', 'Transistor: N-MOSFET | unipolar | 60V | 100A | 200W | TO263', 'DUPE', 2.7, 0, state='out')
    return d


def spec_of(db, mpn):
    return an.spec_from_offer(db.by_mpn(mpn)[0])


def by_mpn(analogs):
    return {a.group.mpn: a for a in analogs}


def plain(spec):
    """The reference without the logic-level mark: the shop titles of standard-level parts never carry a mark of their own."""
    spec.params.pop('logic_level', None)
    return spec


def test_mosfet_verdicts(db):
    found = by_mpn(an.find_analogs(db, plain(spec_of(db, 'FDB5800')), include_no=True))
    assert found['IPB037N06N3'].verdict == 'drop-in'                                   # same case, better Rds(on) and current
    assert found['IRF1010ESPBF'].verdict == 'no'                                        # 12 mΩ against 6 mΩ
    assert found['IPP037N06L3'].verdict == 'other-pkg'                                  # TO-220 against TO-263
    assert found['FQB80N06'].verdict == 'check'                                         # Rds(on) is not in the Semikom title
    assert found['IRF5210S'].verdict == 'no' and found['LOW55V'].verdict == 'no'


def test_logic_level_reference_asks_to_check_a_candidate_without_the_mark(db):
    found = by_mpn(an.find_analogs(db, spec_of(db, 'FDB5800')))
    assert found['IPB037N06N3'].verdict == 'check'
    assert any('Logic-level' in r for r in found['IPB037N06N3'].reasons)
    assert found['IPP037N06L3'].verdict == 'other-pkg'                                  # logic-level, but TO-220


def test_reasons_name_the_decisive_parameter(db):
    found = by_mpn(an.find_analogs(db, spec_of(db, 'FDB5800'), include_no=True))
    assert any('Rds(on)' in r for r in found['IRF1010ESPBF'].reasons)
    assert any(r.startswith('не указано в магазине:') and 'Rds(on)' in r for r in found['FQB80N06'].reasons)
    assert any(c.label == 'Канал' and c.status == 'bad' for c in found['IRF5210S'].checks)
    assert any(c.label == 'Vds' and c.status == 'bad' for c in found['LOW55V'].checks)


def test_default_list_hides_rejected_and_sorts_by_verdict_then_open_questions(db):
    analogs = an.find_analogs(db, plain(spec_of(db, 'FDB5800')))
    assert 'IRF5210S' not in by_mpn(analogs) and 'LOW55V' not in by_mpn(analogs) and 'IRF1010ESPBF' not in by_mpn(analogs)
    assert [a.group.mpn for a in analogs] == ['IPB037N06N3', 'FQB80N06', 'DUPE', 'IPP037N06L3']     # DUPE: not in stock
    assert [a.verdict for a in analogs] == sorted((a.verdict for a in analogs), key=an.RANK.get)


def test_reference_part_is_not_its_own_analog(db):
    assert 'FDB5800' not in by_mpn(an.find_analogs(db, spec_of(db, 'FDB5800'), include_no=True))


def test_in_stock_filter_and_shop_filter(db):
    spec = spec_of(db, 'FDB5800')
    assert 'DUPE' in by_mpn(an.find_analogs(db, spec, include_no=True))
    assert 'DUPE' not in by_mpn(an.find_analogs(db, spec, include_no=True, in_stock=True))
    assert set(by_mpn(an.find_analogs(db, spec, include_no=True, shops=['semikom']))) == {'FQB80N06', 'IRF5210S', 'LOW55V'}


def test_analogs_for_mpn_merges_the_shops_data(db):
    put(db, 'semikom', 'ref2', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK', 'FDB5800', 4.74, 285)
    spec, analogs = an.analogs_for_mpn(db, 'fdb-5800')
    assert spec.params['rds_mohm'] == 6.0 and spec.pkg == 'TO-263' and spec.params['logic_level']
    assert analogs[0].group.mpn == 'IPB037N06N3'
    assert an.analogs_for_mpn(db, 'NOSUCHPART') == (None, [])


def test_footprint_package_of_the_board_overrides_the_shop_case(db):
    spec = plain(an.spec_from_offer(db.by_mpn('IPP037N06L3')[0], footprint_pkg='TO-263'))
    found = by_mpn(an.find_analogs(db, spec, include_no=True))
    assert found['IPB037N06N3'].verdict == 'drop-in'                                    # judged against the board's TO-263 footprint
    assert any(c.label == 'Корпус' and c.status == 'ok' for c in found['IPB037N06N3'].checks)


# ---- other kinds ----------------------------------------------------------------------------------------

@pytest.fixture()
def passives(tmp_path):
    d = Database(tmp_path / 'p.db')
    put(d, 'salvats', 'r1', '10K, 1206, 1%, 0.25W, SMD Rezistors, 1206', 'SMD1206-10K-1%', 0.03, 500)
    put(d, 'salvats', 'r2', '10K, 1206, 5%, 0.25W, SMD Rezistors, 1206', 'SMD1206-10K-5%', 0.02, 500)
    put(d, 'salvats', 'r3', '10K, 1206, 1%, 0.25W, SMD Rezistors, 1206', 'RC1206FR-0710KL', 0.04, 500)
    put(d, 'salvats', 'r4', '4K7, 1206, 1%, 0.25W, SMD Rezistors, 1206', 'SMD1206-4K7-1%', 0.03, 500)
    put(d, 'salvats', 'r5', '10K, 0805, 1%, 0.125W, SMD Rezistors, 0805', 'SMD0805-10K-1%', 0.03, 500)
    put(d, 'salvats', 'c1', '100nF, 50V, 0805, (10gab,), MLCC, X7R, ±10%, SMD Kondensators, 0805', 'CL21B104KBCNNNC', 0.51, 20, pack_qty=10)
    put(d, 'salvats', 'c2', '100nF, 50V, 0805, (10gab,), MLCC, X5R, ±10%, SMD Kondensators, 0805', 'CL21A104KBCNNNC', 0.40, 20, pack_qty=10)
    put(d, 'salvats', 'c3', '100nF, 25V, 0805, (10gab,), MLCC, X7R, ±10%, SMD Kondensators, 0805', 'CL21B104KACNNNC', 0.30, 20, pack_qty=10)
    put(d, 'salvats', 'c4', '100nF, 100V, 0805, (10gab,), MLCC, X7R, ±10%, SMD Kondensators, 0805', 'C0805C104K1RACTU', 0.60, 20, pack_qty=10)
    put(d, 'salvats', 'c5', '220nF, 50V, 0805, (10gab,), MLCC, X7R, ±10%, SMD Kondensators, 0805', 'CL21B224KBFNNNE', 0.60, 20, pack_qty=10)
    put(d, 'salvats', 'd1', 'SS510-YAN, SMD, Diode Schottky, 100V, 5A, SMC', 'SS510-YAN', 0.35, 30)
    put(d, 'salvats', 'd2', 'SS5100-YAN, SMD, Diode Schottky, 100V, 5A, SMC', 'SS5100-YAN', 0.30, 30)
    put(d, 'salvats', 'd3', 'S5M-YAN, SMD, Diode, 1000V, 5A, SMC', 'S5M-YAN', 0.20, 30)
    put(d, 'salvats', 'd4', 'SS54-YAN, SMD, Diode Schottky, 40V, 5A, SMC', 'SS54-YAN', 0.20, 30)
    put(d, 'salvats', 'd5', 'SS510B-YAN, SMD, Diode Schottky, 100V, 5A, SMB', 'SS510B-YAN', 0.20, 30)
    put(d, 'salvats', 'z1', '33V Stabilitrons SMD, BZV55-C33, 0.5W, MiniMELF', 'BZV55-C33', 0.13, 30)
    put(d, 'salvats', 'z2', '33V Stabilitrons SMD, BZV55-B33, 0.5W, MiniMELF', 'BZV55-B33', 0.14, 30)
    put(d, 'salvats', 'z3', '30V Stabilitrons SMD, BZV55-C30, 0.5W, MiniMELF', 'BZV55-C30', 0.12, 30)
    return d


def test_resistor_analogs_need_the_same_value_tolerance_and_case(passives):
    spec = an.Spec(title='R110 10k 1%', params={'kind': 'resistor', 'ohm': 10000.0, 'tol': 1.0, 'pd': 0.25, 'pkg': 'SMD1206', 'mount': 'smd'}, pkg='SMD1206')
    found = by_mpn(an.find_analogs(passives, spec, include_no=True))
    assert found['SMD1206-10K-1%'].verdict == 'drop-in' and found['RC1206FR-0710KL'].verdict == 'drop-in'
    assert found['SMD1206-10K-5%'].verdict == 'no'                                    # 5 % where 1 % is drawn
    assert found['SMD1206-4K7-1%'].verdict == 'no'
    assert 'SMD0805-10K-1%' not in found                                                # another size is not offered


def test_capacitor_analogs_voltage_dielectric_and_value(passives):
    spec = an.spec_from_offer(passives.by_mpn('CL21B104KBCNNNC')[0])
    found = by_mpn(an.find_analogs(passives, spec, include_no=True))
    assert found['C0805C104K1RACTU'].verdict == 'drop-in'                                # 100 V part for a 50 V place
    assert found['CL21A104KBCNNNC'].verdict == 'check'                                  # X5R instead of X7R
    assert found['CL21B104KACNNNC'].verdict == 'no' and found['CL21B224KBFNNNE'].verdict == 'no'


def test_diode_analogs_voltage_current_type_and_case(passives):
    spec = an.spec_from_offer(passives.by_mpn('SS510-YAN')[0])
    found = by_mpn(an.find_analogs(passives, spec, include_no=True))
    assert found['SS5100-YAN'].verdict == 'drop-in'
    assert found['S5M-YAN'].verdict == 'check' and any(c.label == 'Тип' and c.status == 'worse' for c in found['S5M-YAN'].checks)
    assert found['SS54-YAN'].verdict == 'no'
    assert found['SS510B-YAN'].verdict == 'other-pkg'


def test_zener_analogs_match_the_voltage(passives):
    spec = an.spec_from_offer(passives.by_mpn('BZV55-C33')[0])
    found = by_mpn(an.find_analogs(passives, spec, include_no=True))
    assert found['BZV55-B33'].verdict == 'drop-in' and found['BZV55-C30'].verdict == 'no'


def test_spec_from_design_value(passives):
    spec = an.spec_from_design({'ref': 'R110', 'kind': 'resistor', 'ohm': 10000.0, 'tol': 1.0, 'pkg': 'SMD1206'})
    assert spec.kind == 'resistor' and spec.pkg == 'SMD1206'
    assert by_mpn(an.find_analogs(passives, spec))['SMD1206-10K-1%'].verdict == 'drop-in'
    assert an.spec_from_design({'ref': 'Q1', 'kind': 'mosfet'}) is None


def test_unsupported_kinds_have_no_analogs(passives):
    assert an.find_analogs(passives, an.Spec(title='x', params={'kind': 'other'})) == []
    assert an.compare_parts(an.Spec(title='x', params={'kind': 'other'}), {})[0] == 'no'


# ---- reference of a BOM line ------------------------------------------------------------------------------

def line_of(mpn, shop, refs_parts, url=''):
    from partscat.bom import BomLine
    return BomLine(shop=shop, shop_label=shop.title(), mpn=mpn, fitted=1, buy=1, unit='шт.', pack=1, price=0.03, total=0.03,
                   refs=[p['ref'] for p in refs_parts], accessory=0, url=url, date='2026-10-20', parts=refs_parts)


def test_spec_for_line_takes_case_and_value_from_the_schematic(passives):
    parts = [{'ref': 'R110', 'symbol': 'R', 'value': '10k 1%', 'footprint': 'Resistor_SMD:R_1206_3216Metric'}]
    spec = an.spec_for_line(passives, line_of('SMD1206-10K-1%', 'salvats', parts))
    assert spec.mpn == 'SMD1206-10K-1%' and spec.pkg == 'SMD1206'
    assert (spec.params['ohm'], spec.params['tol']) == (10000.0, 1.0)


def test_spec_for_line_does_not_require_a_tolerance_the_schematic_does_not_state(passives):
    parts = [{'ref': 'R201', 'symbol': 'R', 'value': '10k', 'footprint': 'Resistor_SMD:R_1206_3216Metric'}]
    spec = an.spec_for_line(passives, line_of('SMD1206-10K-1%', 'salvats', parts))
    assert 'tol' not in spec.params
    found = by_mpn(an.find_analogs(passives, spec))
    assert found['SMD1206-10K-5%'].verdict == 'drop-in'


def test_spec_for_line_falls_back_to_the_schematic_when_the_catalog_is_empty(tmp_path):
    parts = [{'ref': 'C9', 'symbol': 'C', 'value': '100n 50V', 'footprint': 'Capacitor_SMD:C_0805_2012Metric'}]
    spec = an.spec_for_line(Database(tmp_path / 'empty.db'), line_of('NOSUCH', 'salvats', parts))
    assert spec.kind == 'capacitor' and spec.pkg == 'SMD0805' and spec.params['vr'] == 50.0
    assert an.spec_for_line(Database(tmp_path / 'empty.db'), line_of('NOSUCH', 'salvats', [])) is None


def test_spec_for_line_uses_the_board_footprint_for_a_transistor(db):
    parts = [{'ref': 'Q102', 'symbol': 'NMOS', 'value': 'FDB5800', 'footprint': 'Package_TO_SOT_SMD:TO-263-2'}]
    spec = an.spec_for_line(db, line_of('FDB5800', 'salvats', parts))
    assert spec.kind == 'mosfet' and spec.pkg == 'TO-263' and spec.mpn == 'FDB5800'


def test_rds_from_another_kind_of_source_is_a_question_not_a_rejection(db):
    # the reference has the headline 6 mΩ from a title; the candidate's 12.6 mΩ comes from a property list
    put(db, 'semikom', 'p', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK', 'PROPS12', 3.0, 10,
        props={'On-state resistance': '12.6mΩ'})
    found = by_mpn(an.find_analogs(db, plain(spec_of(db, 'FDB5800')), include_no=True))
    assert found['PROPS12'].verdict == 'check'
    rds = next(c for c in found['PROPS12'].checks if c.label == 'Rds(on)')
    assert rds.status == 'unknown' and 'разных источников' in rds.note
    assert any('сверить по даташиту' in r and 'Rds(on)' in r for r in found['PROPS12'].reasons)
    # a value that no change of test conditions explains is still a rejection
    put(db, 'semikom', 'q', 'Transistor: N-MOSFET; unipolar; 60V; 80A; 242W; D2PAK', 'PROPS80', 3.0, 10,
        props={'On-state resistance': '80mΩ'})
    assert by_mpn(an.find_analogs(db, plain(spec_of(db, 'FDB5800')), include_no=True))['PROPS80'].verdict == 'no'


def test_open_questions_are_counted():
    analog = an.Analog(group=None, verdict='check', checks=[an.Check('a', '1', '1', 'ok'), an.Check('b', '1', '?', 'unknown'),
                                                           an.Check('c', '1', '2', 'worse')])
    assert analog.open == 2
