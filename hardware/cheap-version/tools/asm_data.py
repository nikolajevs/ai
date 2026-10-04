"""Part data of the assembly document: values from the BOM, assembly steps, packages, polarity rules."""
import csv
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]

STEPS = {
    1: ('Нижняя сторона: C911', 'SMD'),
    2: ('Микросхемы', 'SMD'),
    3: ('Транзисторы и диоды SMD', 'SMD'),
    4: ('Резисторы и конденсаторы 0603', 'SMD'),
    5: ('Резисторы и конденсаторы 0805', 'SMD'),
    6: ('Резисторы и конденсаторы 1206, 1210, 2512; PTC-предохранитель F301', 'SMD'),
    7: ('Индуктивности, предохранители Littelfuse, кварц, электролиты C901 и C909', 'SMD'),
    8: ('Модуль ESP32 и разъём microSD', 'SMD'),
    9: ('Выводные детали сверху', 'THT'),
    10: ('Нижняя сторона: держатель батарейки BT301 и батарейка', 'THT'),
}


def load_bom(path=HERE / 'BOM_cheap1.csv'):
    """ref -> dict(value, mpn, source, footprint) from BOM_cheap1.csv"""
    out = {}
    for row in csv.DictReader(open(path, encoding='utf-8-sig', newline='')):
        for ref in row['Designators'].split():
            if ref in ('insert',):
                continue
            out.setdefault(ref, dict(value=row['Value'], mpn=row['MPN'], source=row['Source'], footprint=row['Footprint'],
                                     mfr=row['Manufacturer'], lcsc=row['LCSC']))
    return out


def package(fp):
    lib = fp['lib']
    m = re.match(r'[CR]_(\d{4})_', lib)
    if m:
        return m.group(1)
    if lib.startswith('Fuse_1206'):
        return '1206'
    return lib


def step_of(fp):
    ref, lib = fp['ref'], fp['lib']
    if fp['no_bom'] or fp['dnp'] or 'DNP' in fp['value']:
        return None
    if fp['side'] == 'B':
        return 10 if fp['kind'] == 'THT' else 1
    if fp['kind'] == 'THT':
        return 9
    if ref in ('U201', 'J401'):
        return 8
    if ref[0] == 'U':
        return 2
    if ref[0] in 'QD':
        return 3
    if ref[0] in 'LY' or lib.startswith('Fuse_Littelfuse') or lib.startswith('CP_Elec'):
        return 7
    pk = package(fp)
    if pk == '0603':
        return 4
    if pk == '0805':
        return 5
    return 6


def short_value(v):
    return (v.replace(' X5R', '').replace(' X7R', '').replace(' X7S', '').replace(' C0G', '')
             .replace('10u 35V', '10u 35V').strip())


# polarity badges: ref -> [(pad number, text)]
POLARITY = {}
for r in ('C901', 'C909'):
    POLARITY[r] = [('1', '+')]
for r in ('D521', 'D902', 'D711', 'D721'):
    POLARITY[r] = [('1', 'K')]
POLARITY['D303'] = [('1', '1'), ('3', 'K')]
for r in ('D301', 'D302', 'D501', 'D511'):
    POLARITY[r] = [('1', '1')]
for r in ('Q501', 'Q511', 'Q521'):
    POLARITY[r] = [('1', 'G'), ('2', 'S'), ('3', 'D')]
for r in ('Q711', 'Q721'):
    POLARITY[r] = [('1', '1'), ('5', 'D')]
POLARITY['Q601'] = [('1', 'G'), ('2', 'D'), ('3', 'S')]
for r in ('U101', 'U301', 'U601', 'U700', 'U710', 'U720', 'U902', 'U201'):
    POLARITY[r] = [('1', '1')]
POLARITY['BT301'] = [('1', '+'), ('2', '−')]
POLARITY['J901'] = [('1', '−'), ('2', '+')]
POLARITY['J601'] = [('1', '+'), ('2', '−')]
POLARITY['J521'] = [('1', '+'), ('2', '−')]
for r in ('J711', 'J721', 'J731'):
    POLARITY[r] = [('1', '+'), ('2', '−')]
for r in ('J201', 'J301', 'J501', 'J511', 'J302'):
    POLARITY[r] = [('1', '1')]
