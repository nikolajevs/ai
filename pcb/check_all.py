"""Run every PCB_V1 check in one go.

  python check_all.py            # verify; fail on any problem
  python check_all.py --write    # also refresh review/*_<REV> reports, sheet images and BOM_schematic.csv

Steps: ERC -> netlist export -> verify_netlist.py -> analyze_led_power.py -> analyze_power_path.py
-> BOM export comparison -> verify_board.py (KiCad Python) -> DRC.
Without --write the deterministic reports (LED_power, Power_path, BOM_schematic.csv) must match
the committed files byte for byte (line endings ignored). ERC/DRC reports carry timestamps and are
compared by their counters only. The price audit (audit_bom_cost.py) is paused and not run here.

KiCad tools are taken from KICAD_CLI / KICAD_PYTHON or the default KiCad 10 install.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REV = 'v16'
HERE = Path(__file__).resolve().parent
PROJECT = HERE / 'PCB_V1'
REVIEW = HERE / 'review'
KICAD_BIN = Path(r'C:\Program Files\KiCad\10.0\bin')
KICAD_CLI = os.environ.get('KICAD_CLI') or shutil.which('kicad-cli') or str(KICAD_BIN / 'kicad-cli.exe')
KICAD_PYTHON = os.environ.get('KICAD_PYTHON') or str(KICAD_BIN / 'python.exe')
SHEETS = {'PCB_V1': 'Root', 'PCB_V1-MCU _ ESP32': 'MCU', 'PCB_V1-MCU _ ESP32-Peripherals': 'Peripherals',
          'PCB_V1-Outputs': 'Outputs', 'PCB_V1-Outputs-Heater': 'Heater',
          'PCB_V1-InputPower': 'InputPower', 'PCB_V1-LEDDrivers': 'LEDDrivers'}
failures = []


def run(label, cmd, capture=True):
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=HERE)
    noise = re.compile(r'memory leak|image handler|^\s*$')
    lines = [ln for ln in (res.stdout + res.stderr).splitlines() if not noise.search(ln)]
    ok = res.returncode == 0
    print(f"[{'OK' if ok else 'FAIL'}] {label}")
    if not ok or not capture:
        for ln in lines[-15:]:
            print('      ' + ln)
    if not ok:
        failures.append(label)
    return res.stdout


def same_text(a, b):
    return Path(a).read_text(encoding='utf-8-sig').replace('\r\n', '\n') == \
        Path(b).read_text(encoding='utf-8-sig').replace('\r\n', '\n')


def compare_or_write(label, generated, committed, write):
    if write:
        shutil.copyfile(generated, committed)
        print(f'[WRITE] {label} -> {committed.relative_to(HERE)}')
    elif not committed.exists() or not same_text(generated, committed):
        print(f'[FAIL] {label}: {committed.relative_to(HERE)} is missing or out of date (run with --write)')
        failures.append(label)
    else:
        print(f'[OK] {label} reproduces {committed.relative_to(HERE)}')


def counters(report, pattern):
    m = re.search(pattern, Path(report).read_text(encoding='utf-8', errors='replace'))
    return tuple(int(x) for x in m.groups()) if m else None


def render_images(svg_dir):
    try:
        import pymupdf
    except ImportError:
        print('[SKIP] sheet images: install pymupdf to render review/*.png')
        return
    for svg in Path(svg_dir).glob('*.svg'):
        name = SHEETS.get(svg.stem)
        if name:
            pix = pymupdf.open(svg)[0].get_pixmap(dpi=90)
            pix.save(REVIEW / f'{name}_{REV}.png')
    print(f'[WRITE] sheet images review/*_{REV}.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--write', action='store_true', help=f'refresh review/*_{REV} and BOM_schematic.csv')
    args = parser.parse_args()
    sch, pcb = PROJECT / 'PCB_V1.kicad_sch', PROJECT / 'PCB_V1.kicad_pcb'
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        erc, drc, net = tmp / 'erc.rpt', tmp / 'drc.rpt', tmp / 'netlist.xml'
        run('ERC', [KICAD_CLI, 'sch', 'erc', '--exit-code-violations', '-o', str(erc), str(sch)])
        print('      ' + str(counters(erc, r'ERC messages: (\d+)\s+Errors (\d+)\s+Warnings (\d+)')) + ' (messages, errors, warnings)')
        run('netlist export', [KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', str(net), str(sch)])
        run('verify_netlist.py', [sys.executable, 'verify_netlist.py', str(net)], capture=False)
        for label, script, name in [('analyze_led_power.py', 'analyze_led_power.py', f'LED_power_{REV}.txt'),
                                    ('analyze_power_path.py', 'analyze_power_path.py', f'Power_path_{REV}.txt')]:
            out = tmp / name
            run(label, [sys.executable, script, str(net), '--output', str(out)])
            if out.exists():
                compare_or_write(label, out, REVIEW / name, args.write)
        bom = tmp / 'bom.csv'
        run('export_bom.py', [sys.executable, 'export_bom.py', str(net), str(bom)])
        if bom.exists():
            compare_or_write('BOM_schematic.csv', bom, PROJECT / 'BOM_schematic.csv', args.write)
        run('verify_board.py (KiCad Python)', [KICAD_PYTHON, 'verify_board.py', str(net), str(pcb)], capture=False)
        run('DRC', [KICAD_CLI, 'pcb', 'drc', '-o', str(drc), str(pcb)])
        violations = counters(drc, r'Found (\d+) DRC violations')
        unconnected = counters(drc, r'Found (\d+) unconnected pads')
        print(f'      DRC violations {violations[0] if violations else "?"}; unconnected pads '
              f'{unconnected[0] if unconnected else "?"} (expected while the board is unrouted)')
        if not violations or violations[0] != 0:
            failures.append('DRC violations')
        if args.write:
            shutil.copyfile(erc, REVIEW / f'ERC_{REV}.rpt')
            shutil.copyfile(drc, REVIEW / f'DRC_staging_{REV}.rpt')
            print(f'[WRITE] review/ERC_{REV}.rpt, review/DRC_staging_{REV}.rpt')
            svg_dir = tmp / 'svg'
            run('schematic SVG export', [KICAD_CLI, 'sch', 'export', 'svg', '-o', str(svg_dir), str(sch)])
            render_images(svg_dir)
    print('\nALL CHECKS PASSED' if not failures else f'\nFAILED: {", ".join(failures)}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
