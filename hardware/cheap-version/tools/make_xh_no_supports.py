"""Remove the two rear support wings from KiCad's horizontal XH model.

Usage (CadQuery): python make_xh_no_supports.py path/to/original.step
Derived geometry: Rene Poeschl, 2019; CC-BY-SA-4.0 with KiCad library exception.
See libraries/GrowBox.3dshapes/SOURCES_mechanical.md. Model only; pin positions stay unchanged.
"""
import sys
from pathlib import Path
import cadquery as cq

OUT=Path(__file__).resolve().parents[1]/'libraries/GrowBox.3dshapes/JST_XH_1x04_P2.50mm_Horizontal_NoSupports.step'

source=Path(sys.argv[1])
original=cq.importers.importStep(str(source)).val()
shape=original
for x0,x1 in [(-2.46,-1.25),(8.75,9.96)]:
    tool=cq.Workplane('XY').box(x1-x0,4.51,6.2,centered=False).translate((x0,-2.2,-.01)).val()
    shape=shape.cut(tool)
assert shape.isValid() and shape.Volume()<original.Volume()
# Wing removal stays strictly outside the four leads (X = 0, 2.5, 5, 7.5 mm).
pin_region=cq.Workplane('XY').box(8.3,15,12,centered=False).translate((-.4,-10,-4)).val()
assert abs(original.intersect(pin_region).Volume()-shape.intersect(pin_region).Volume())<1e-7
model=cq.Assembly(name='XH_4P_NoSupports')
model.add(shape,name='connector',color=cq.Color(.91,.90,.84))
model.save(str(OUT))
# Carry the upstream attribution/license notice in the derived STEP itself.
text=source.read_text(encoding='utf-8')
notice=text[text.index('/*'):text.index('*/')+2]
exported=OUT.read_text(encoding='utf-8')
exported=exported.replace('HEADER;', 'HEADER;\n'+notice+'\n/* Modified: rear support wings removed for GrowBox stock connector. */',1)
OUT.write_text(exported,encoding='utf-8',newline='\n')
print('saved',OUT,'volume',round(original.Volume(),3),'->',round(shape.Volume(),3))
