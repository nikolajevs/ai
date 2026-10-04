"""JLCPCB fabrication files of cheap-1 (KiCad Python): export_fab_cheap.py [--check]

Runs the PCB_V1 exporter (pcb/export_fab.py: Gerber RS-274X X2, Protel extensions, soldermask subtracted from the
silkscreen, zones refilled, Excellon with separate PTH/NPTH files, header dates and versions normalised, read-back checks
of file functions, outline, strokes, drill sizes and hit counts) on pcb/cheap-version/cheap-version.kicad_pcb and writes
fab/cheap-version_cheap1_jlcpcb.zip. With --check the archive is regenerated and compared with the committed one.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent))     # pcb/ holds export_fab.py (this file is export_fab_cheap.py)
import export_fab as ef  # noqa: E402

NAME = 'cheap-version'
ef.BOARD = HERE / 'cheap-version.kicad_pcb'
ef.OUT = HERE / 'fab'
ef.ZIP_NAME = 'cheap-version_cheap1_jlcpcb.zip'
ef.FILES = {k.replace('PCB_V1', NAME): v for k, v in ef.FILES.items()}
ef.DRILLS = tuple(k.replace('PCB_V1', NAME) for k in ef.DRILLS)
ef.HERE = HERE

if __name__ == '__main__':
    sys.exit(ef.main())
