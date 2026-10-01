"""Export the JLCPCB fabrication files of PCB_V1 and verify them (KiCad Python + kicad-cli).

  python export_fab.py                  # write fab/PCB_V1_<REV>_jlcpcb.zip from PCB_V1/PCB_V1.kicad_pcb
  python export_fab.py --check         # regenerate and compare with the committed zip, change nothing

Gerber RS-274X with X2 attributes, Protel file extensions, 4.6 format, soldermask subtracted from the
silkscreen, zones refilled before plotting; Excellon drills in millimetres with separate PTH and NPTH
files and slots as routed holes. Header lines that carry a date or the KiCad version are normalised, so
exporting the same board again gives the same archive.

The exported files are read back and checked against the board: file functions, outline size, narrowest
track and silkscreen stroke, drill sizes and hit counts. Board-level JLCPCB limits are in check_fab.py.
Run it with the KiCad Python; kicad-cli is taken from KICAD_CLI or the default KiCad 10 install.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parent
BOARD = HERE / 'PCB_V1' / 'PCB_V1.kicad_pcb'
OUT = HERE / 'fab'
KICAD_CLI = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
REV = re.search(r"^REV = '(v\d+)'", (HERE / 'check_all.py').read_text(encoding='utf-8'), re.M).group(1)
ZIP_NAME = f'PCB_V1_{REV}_jlcpcb.zip'

LAYERS = 'F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts'
# file name -> (X2 FileFunction, minimum stroke width mm checked in the drawn tracks)
FILES = {
    'PCB_V1-F_Cu.gtl': ('Copper,L1,Top', 0.09),
    'PCB_V1-In1_Cu.g1': ('Copper,L2,Inr', 0.09),
    'PCB_V1-In2_Cu.g2': ('Copper,L3,Inr', 0.09),
    'PCB_V1-B_Cu.gbl': ('Copper,L4,Bot', 0.09),
    'PCB_V1-F_Mask.gts': ('Soldermask,Top', None),
    'PCB_V1-B_Mask.gbs': ('Soldermask,Bot', None),
    'PCB_V1-F_Silkscreen.gto': ('Legend,Top', 0.2),
    'PCB_V1-B_Silkscreen.gbo': ('Legend,Bot', 0.2),
    'PCB_V1-F_Paste.gtp': ('Paste,Top', None),
    'PCB_V1-Edge_Cuts.gm1': ('Profile,NP', None),
}
DRILLS = ('PCB_V1-PTH.drl', 'PCB_V1-NPTH.drl')

DATE = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2})?')
VERSION = re.compile(r'(KiCad,Pcbnew,|Kicad,Pcbnew,|PCBNEW |KiCad )10\.\d+\.\d+')


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if res.returncode != 0:
        sys.exit(f'FAILED: {" ".join(cmd[:4])} ...\n{res.stdout}{res.stderr}')


def normalise(path):
    text = path.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
    lines = []
    for ln in text.split('\n'):
        if 'CreationDate' in ln or 'date ' in ln or ln.startswith('; DRILL file'):
            ln = DATE.sub('2000-01-01T00:00:00+00:00', ln)
        ln = VERSION.sub(r'\g<1>10.0.0', ln)
        lines.append(ln)
    path.write_text('\n'.join(lines), encoding='utf-8', newline='\n')


def export(tmp):
    board = str(BOARD)
    run([KICAD_CLI, 'pcb', 'export', 'gerbers', '--output', str(tmp) + os.sep, '--layers', LAYERS, '--subtract-soldermask',
         '--no-netlist', '--precision', '6', '--check-zones', board])
    run([KICAD_CLI, 'pcb', 'export', 'drill', '--output', str(tmp) + os.sep, '--format', 'excellon', '--drill-origin', 'absolute',
         '--excellon-zeros-format', 'decimal', '--excellon-oval-format', 'route', '--excellon-units', 'mm',
         '--excellon-separate-th', board])
    for name in list(FILES) + list(DRILLS):
        assert (tmp / name).exists(), f'missing {name}'
        normalise(tmp / name)


def read_gerber(path, min_stroke):
    text = path.read_text(encoding='utf-8')
    function = re.search(r'%TF\.FileFunction,([^*]+)\*%', text).group(1)
    apertures = {m.group(1): float(m.group(2)) for m in re.finditer(r'%ADD(\d+)C,([\d.]+)\*%', text)}
    current, region = None, False
    drawn, xs, ys = Counter(), [], []
    for ln in text.split('\n'):
        if ln.startswith('G36'):
            region = True
        elif ln.startswith('G37'):
            region = False
        m = re.match(r'D(\d+)\*$', ln)
        if m:
            current = m.group(1)
            continue
        m = re.match(r'X(-?\d+)Y(-?\d+)D0([12])\*$', ln)
        if m:
            xs.append(int(m.group(1)) / 1e6)
            ys.append(int(m.group(2)) / 1e6)
            if m.group(3) == '1' and not region and current in apertures:
                drawn[apertures[current]] += 1
    return function, drawn, (min(xs), min(ys), max(xs), max(ys)) if xs else None


def read_drill(path):
    tools, current, hits, slots = {}, None, Counter(), Counter()
    for ln in path.read_text(encoding='utf-8').split('\n'):
        m = re.match(r'T(\d+)C([\d.]+)', ln)
        if m:
            tools[m.group(1)] = float(m.group(2))
            continue
        m = re.match(r'T(\d+)$', ln)
        if m:
            current = tools[m.group(1)]
            continue
        if ln.startswith('M15'):
            slots[current] += 1
        elif re.match(r'X-?[\d.]+Y-?[\d.]+$', ln) and current is not None:
            hits[current] += 1
    return hits, slots


def expected_holes(plated):
    board = p.LoadBoard(str(BOARD))
    hits, slots = Counter(), Counter()
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            dx, dy = p.ToMM(pad.GetDrillSizeX()), p.ToMM(pad.GetDrillSizeY())
            if dx <= 0 or (pad.GetAttribute() == p.PAD_ATTRIB_PTH) != plated:
                continue
            if abs(dx - dy) > 1e-6:
                slots[round(min(dx, dy), 3)] += 1
            else:
                hits[round(dx, 3)] += 1
    if plated:
        for t in board.GetTracks():
            if isinstance(t, p.PCB_VIA):
                hits[round(p.ToMM(t.GetDrill()), 3)] += 1
    return hits, slots


def verify(tmp):
    problems = []
    for name, (function, min_stroke) in FILES.items():
        got, drawn, box = read_gerber(tmp / name, min_stroke)
        if got != function:
            problems.append(f'{name}: file function {got}, expected {function}')
        if min_stroke is not None and drawn and min(drawn) < min_stroke - 1e-9:
            problems.append(f'{name}: stroke {min(drawn)} mm below {min_stroke}')
        print(f'  {name:26s} {function:16s} narrowest drawn stroke {min(drawn) if drawn else "-"} mm')
        if function == 'Profile,NP':
            w, h = box[2] - box[0], box[3] - box[1]
            print(f'  outline {w:.3f} x {h:.3f} mm')
            if abs(w - 100) > 0.01 or abs(h - 100) > 0.01:
                problems.append(f'outline {w:.3f} x {h:.3f} mm, expected 100 x 100')
    for name, plated in zip(DRILLS, (True, False)):
        hits, slots = read_drill(tmp / name)
        want_hits, want_slots = expected_holes(plated)
        if {round(k, 3): v for k, v in hits.items()} != dict(want_hits) or {round(k, 3): v for k, v in slots.items()} != dict(want_slots):
            problems.append(f'{name}: hits {dict(hits)} slots {dict(slots)}, board has hits {dict(want_hits)} slots {dict(want_slots)}')
        print(f'  {name:26s} hits {sum(hits.values())} in {len(hits)} sizes, routed slots {sum(slots.values())}: '
              + ', '.join(f'{k:.2f} mm x{v}' for k, v in sorted(hits.items())))
    return problems


def build_zip(tmp, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(list(FILES) + list(DRILLS)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (tmp / name).read_bytes())


def main():
    check = '--check' in sys.argv
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        export(tmp)
        problems = verify(tmp)
        new = tmp / ZIP_NAME
        build_zip(tmp, new)
        if problems:
            print('\nFAILED:\n  ' + '\n  '.join(problems))
            return 1
        target = OUT / ZIP_NAME
        if check:
            same = target.exists() and target.read_bytes() == new.read_bytes()
            print(f'\n{"OK" if same else "FAIL"}: {ZIP_NAME} {"matches" if same else "differs from or is missing in"} fab/')
            return 0 if same else 1
        OUT.mkdir(exist_ok=True)
        shutil.copyfile(new, target)
        print(f'\nWrote {target.relative_to(HERE)} ({target.stat().st_size} bytes, {len(FILES) + len(DRILLS)} files)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
