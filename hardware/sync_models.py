"""Attach 3D models to the board footprints and list the parts that still have none.

Run with KiCad's bundled Python from the pcb directory:
  python sync_models.py PCB_V1/PCB_V1.kicad_pcb            # report only
  python sync_models.py PCB_V1/PCB_V1.kicad_pcb --write    # update the board file

- GrowBox footprints: the board copy receives the model list of the project library footprint.
- Stock KiCad footprints whose model file is missing from the KiCad 10 library get the project model
  from OVERRIDES (applied only when that file exists, so models delivered later are picked up on rerun).
- Net ties and bare test pads need no model and are ignored.
The script only changes 3D model entries; positions, pads, nets and fields are untouched.
"""
import os
import re
import sys
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parent
PROJECT = HERE / 'PCB_V1'
LIBRARY = PROJECT / 'libraries' / 'GrowBox.pretty'
KICAD_3D = Path(os.environ.get('KICAD10_3DMODEL_DIR', r'C:\Program Files\KiCad\10.0\share\kicad\3dmodels'))
PROJECT_3D = '${KIPRJMOD}/libraries/GrowBox.3dshapes/'
OVERRIDES = {
    'Inductor_SMD:L_Bourns_SRP1770TA_16.9x16.9mm': PROJECT_3D + 'L_Bourns_SRP1770TA_16.9x16.9mm.step',
    'Package_SO:ONSemi_SO-8FL_488AA': PROJECT_3D + 'ONSemi_SO-8FL_488AA.step',
    # Same 3.9 x 4.9 mm SOIC-8 body; only the hidden exposed pad differs from the DDA footprint.
    'Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.71x3.4mm':
        '${KICAD10_3DMODEL_DIR}/Package_SO.3dshapes/SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.81mm.step',
    'Battery:BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032': PROJECT_3D + 'BatteryHolder_MYOUNG_BS-07-A1BJ001_CR2032.step',
    'Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A': PROJECT_3D + 'SW_Push_1P1T_XKB_TS-1187A.step',
}


def resolve(name):
    env = {'KIPRJMOD': str(PROJECT), 'KICAD10_3DMODEL_DIR': str(KICAD_3D)}
    path = re.sub(r'\$\{(\w+)\}', lambda m: env.get(m.group(1), m.group(0)), name)
    return Path(path)


def exists(name):
    path = resolve(name)
    return any(path.with_suffix(s).exists() for s in ('.step', '.stp', '.wrl')) or path.exists()


def model(filename, source=None):
    m = p.FP_3DMODEL()
    m.m_Filename = filename
    if source is not None:
        m.m_Offset, m.m_Rotation, m.m_Scale, m.m_Show = source.m_Offset, source.m_Rotation, source.m_Scale, source.m_Show
    return m


def main():
    board_path = sys.argv[1]
    write = '--write' in sys.argv
    board = p.LoadBoard(board_path)
    library = {}
    changed, missing = [], []
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        ref = fp.GetReference()
        nick, name = str(fp.GetFPID().GetLibNickname()), str(fp.GetFPID().GetLibItemName())
        if fp.IsNetTie() or name.startswith('TestPoint_Pad'):
            continue
        wanted = None
        if nick == 'GrowBox':
            if name not in library:
                library[name] = p.FootprintLoad(str(LIBRARY), name)
            wanted = [model(m.m_Filename, m) for m in library[name].Models()]
        elif f'{nick}:{name}' in OVERRIDES and not all(exists(m.m_Filename) for m in fp.Models()):
            target = OVERRIDES[f'{nick}:{name}']
            if exists(target):
                wanted = [model(target)]
        if wanted is not None:
            current = [m.m_Filename for m in fp.Models()]
            if current != [m.m_Filename for m in wanted]:
                fp.Models().clear()
                for m in wanted:
                    fp.Models().push_back(m)
                changed.append(f'{ref} -> {", ".join(m.m_Filename for m in wanted) or "(none)"}')
        if not fp.Models() or not all(exists(m.m_Filename) for m in fp.Models()):
            missing.append(f'{ref} ({nick}:{name})')
    print(f'{len(changed)} footprints updated' + ('' if write else ' (dry run)'))
    for line in changed:
        print('  ' + line)
    print(f'{len(missing)} footprints without a resolvable 3D model')
    for line in missing:
        print('  ' + line)
    if write and changed:
        p.SaveBoard(board_path, board)
        text = Path(board_path).read_text(encoding='utf-8')
        Path(board_path).write_text(text.replace('\r\n', '\n'), encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
