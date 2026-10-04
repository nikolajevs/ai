"""All checks of the cheap-1 board in one go: python run_checks.py [--no-fab]

Steps (each prints its own summary; the exit code is 1 when any step fails):
  ERC, DRC with the project rules (kicad-cli), schematic <-> board pins, check_fab.py (JLCPCB capabilities),
  verify_input_copper.py, verify_led_copper.py, check_return_paths.py, analyze_dcdc_loops.py, export_fab_cheap.py --check.
KICAD_BIN (default C:\\Program Files\\KiCad\\10.0\\bin) gives kicad-cli and the KiCad Python; CHEAP_PY is a Python with
numpy, scipy and Pillow for the copper checks (for example a venv: pip install numpy scipy pillow); without it those
two steps fail with an actionable note; an incomplete run is not a release pass.
"""
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TOOLS = HERE / 'tools'
KICAD = Path(os.environ.get('KICAD_BIN', r'C:\Program Files\KiCad\10.0\bin'))
KCLI, KPY = str(KICAD / 'kicad-cli.exe'), str(KICAD / 'python.exe')
NUMPY_PY = os.environ.get('CHEAP_PY')
BOARD = str(HERE / 'cheap-version.kicad_pcb')
results = []


def step(name, ok, note=''):
    results.append((name, ok))
    print(f'{"PASS" if ok else "FAIL"}  {name}{": " + note if note else ""}')


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd)


def main():
    tmp = Path(tempfile.mkdtemp())
    erc = tmp / 'erc.json'
    run([KCLI, 'sch', 'erc', '--severity-all', '--format', 'json', '-o', str(erc), str(HERE / 'cheap-version.kicad_sch')])
    n = sum(len(s.get('violations', [])) for s in json.load(open(erc, encoding='utf-8')).get('sheets', []))
    step('ERC', n == 0, f'{n} violation(s)')

    drc = tmp / 'drc.json'
    run([KCLI, 'pcb', 'drc', '--severity-all', '--format', 'json', '-o', str(drc), BOARD])
    d = json.load(open(drc, encoding='utf-8'))
    kinds = dict(Counter(f'{v["severity"]}:{v["type"]}' for v in d['violations']))
    step('DRC (project rules and .kicad_dru)', not d['violations'] and not d['unconnected_items'],
         f'{len(d["violations"])} violation(s) {kinds}, {len(d["unconnected_items"])} unconnected')

    net = tmp / 'net.xml'
    run([KCLI, 'sch', 'export', 'netlist', '--format', 'kicadxml', '-o', str(net), str(HERE / 'cheap-version.kicad_sch')])
    r = run([KPY, str(TOOLS / 'check_sync.py'), str(net), BOARD])
    step('schematic <-> board pins', r.returncode == 0, [ln for ln in r.stdout.splitlines() if 'schematic pins' in ln or 'DIFF' in ln][-1:][0] if r.stdout.strip() else r.stderr[-200:])

    r = run([KPY, str(HERE.parent / 'check_fab.py'), BOARD])
    last = [ln for ln in r.stdout.splitlines() if 'FAIL,' in ln]
    step('JLCPCB capabilities (check_fab.py)', r.returncode == 0, last[-1] if last else r.stderr[-200:])

    r = run([KPY, str(TOOLS / 'verify_input_copper.py'), BOARD], cwd=str(TOOLS))
    step('input / PTC copper', r.returncode == 0 and 'PASS' in r.stdout, [ln for ln in r.stdout.splitlines() if 'PASS' in ln or 'Error' in ln][-1:][0] if r.stdout.strip() else r.stderr[-200:])

    export = tmp / 'board.json'
    run([KPY, str(TOOLS / 'export_view.py'), str(export), BOARD])
    for name, script, args in (('LED / +24V copper widths', 'verify_led_copper.py', []), ('return paths', 'check_return_paths.py', [])):
        if NUMPY_PY:
            r = run([NUMPY_PY, str(TOOLS / script), str(export)] + args, cwd=str(TOOLS))
            step(name, r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
        else:
            step(name, False, 'set CHEAP_PY to a Python with numpy, scipy and Pillow')
    r = run([sys.executable, str(TOOLS / 'analyze_dcdc_loops.py'), str(export)], cwd=str(TOOLS))
    step('DC/DC loop estimate', r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])

    if '--no-fab' not in sys.argv:
        r = run([KPY, str(TOOLS / 'export_fab_cheap.py'), '--check'])
        step('Gerber archive matches the board', r.returncode == 0, [ln for ln in r.stdout.splitlines() if ln.startswith(('OK', 'FAIL'))][-1:][0] if r.stdout.strip() else r.stderr[-200:])
    bad = [name for name, ok in results if not ok]
    print(f'\n{len(results) - len(bad)} of {len(results)} steps passed' + (f'; failed: {bad}' if bad else ''))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
