"""Export the actual schematic BOM; all rows remain unqualified for purchasing.
Usage: python export_bom.py freshly-exported-kicad.xml output.csv
The curated BOM_v0.1 files are a separate, partial component-selection list.
"""
import csv
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
components = root.findall('./components/comp')
refs = [c.get('ref') for c in components]
assert len(refs) == len(set(refs)), 'Duplicate reference designators'
with Path(sys.argv[2]).open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.writer(stream)
    writer.writerow(['Reference', 'Value', 'Footprint', 'Datasheet', 'Sheet', 'Procurement status'])
    for comp in sorted(components, key=lambda c: c.get('ref')):
        writer.writerow([comp.get('ref'), comp.findtext('value', ''),
                         comp.findtext('footprint', ''), comp.findtext('datasheet', ''),
                         comp.find('sheetpath').get('names'), 'ENGINEERING DRAFT - DO NOT ORDER'])
print(f'Exported {len(components)} schematic components')
