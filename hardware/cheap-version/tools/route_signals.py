"""Autoroute everything route_power.py left open with Freerouting (KiCad Python).

  python route_signals.py cheap-version.kicad_pcb --jar freerouting.jar [--java java] [--passes 30]
                          [--work DIR] [--ses FILE] [--write]

The board must come from the power stage of route_power.py: its tracks and vias are locked and
therefore exported as fixed wiring, its zones as copper areas. Unlocked tracks (a previous
autorouter result) and the finish fills are removed first, so the step can be repeated. The DSN file
is patched before the run:
  - In1.Cu becomes a power layer: the GND plane receives no autorouted copper;
  - every script zone on the outer layers also becomes a keepout, because the router otherwise
    crosses a plane with foreign wiring and cuts the pour;
  - the class widths of PWR12, PWR3V3 and AUX24 are narrowed for the router (ROUTER_WIDTHS), since it
    cannot neck a wide track down to fine-pitch pins.
The router runs without its pin-fanout stage (the ground ties are made by route_power.py) and with
usage telemetry off. With --ses an existing session file is imported instead of running the router.

Freerouting 2.4.1 needs Java 25. The router is not deterministic across input changes: the committed
board, not this script, is the record of the result. Next: route_complete.py, then
`route_power.py --finish`.
"""
import argparse
import os
import subprocess

import pcbnew as p

import route_power

NO_ROUTE_LAYERS = ['In1.Cu']    # the GND plane (route_power.PLANES): no autorouted copper
# Class widths used by the router only (mm). The project classes stay at 0.8 / 0.5 / 1.0 mm for hand work and the
# power pours; wide tracks cannot reach fine-pitch pins, and the router cannot neck down on its own.
# These are routing hints, NOT a current-capacity approval (especially on 0.5 oz inner copper).
# Main power paths must be reinforced and layer-change vias reviewed before production.
ROUTER_WIDTHS = {'MAIN24': 2.0, 'HEATER24': 3.0, 'LED_INPUT': 2.0, 'SWITCH': 1.5, 'LED48': 0.8, 'AUX24': 0.6, 'PWR12': 0.5, 'PWR3V3': 0.4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('board')
    ap.add_argument('--jar', default=os.environ.get('FREEROUTING_JAR'))
    ap.add_argument('--java', default=os.environ.get('JAVA', 'java'))
    ap.add_argument('--passes', type=int, default=30)
    ap.add_argument('--work', default='.')
    ap.add_argument('--ses')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()

    board = route_power.load_board(args.board)
    names = {z.GetZoneName() for z in board.Zones()}
    assert route_power.TAG + 'GND plane' in names, 'run the power stage of route_power.py first'
    route_power.remove_zones(board, {name for name, *_ in route_power.FINISH})
    stale = [t for t in board.GetTracks() if not t.IsLocked()]
    for t in stale:
        route_power.discard(board, t)
    fixed = len(board.GetTracks())
    print(f'fixed tracks and vias {fixed}, removed unlocked {len(stale)}')

    ses = args.ses
    if not ses:
        assert args.jar, 'give --jar or FREEROUTING_JAR'
        os.makedirs(args.work, exist_ok=True)
        dsn = os.path.join(args.work, 'cheap.dsn')
        ses = os.path.join(args.work, 'cheap.ses')
        assert p.ExportSpecctraDSN(board, dsn), 'DSN export failed'
        text = open(dsn, encoding='utf-8').read()
        for layer in NO_ROUTE_LAYERS:       # solid ground: declared a plane so that no signal enters it
            marker = f'(layer {layer}\n      (type signal)'
            assert text.count(marker) == 1, layer
            text = text.replace(marker, f'(layer {layer}\n      (type power)')
        for cls, width in ROUTER_WIDTHS.items():
            head = text.index(f'(class {cls} ')
            rule = text.index('(width ', head)
            end = text.index(')', rule)
            text = text[:rule] + f'(width {round(width * 1000)}' + text[end:]
        # The router crosses a plane with foreign wiring; keep every script zone intact with a keepout.
        areas = []
        for z in board.Zones():
            layer = board.GetLayerName(z.GetLayer())
            if z.GetZoneName().startswith(route_power.TAG) and layer in ('F.Cu', 'B.Cu'):
                o = z.Outline().Outline(0)
                pts = [(o.CPoint(k).x // 1000, -(o.CPoint(k).y // 1000)) for k in range(o.PointCount())]
                pts.append(pts[0])
                areas.append(f'    (keepout "" (polygon {layer} 0  ' + '  '.join(f'{x} {y}' for x, y in pts) + '))\n')
        first = text.index('    (plane ')
        text = text[:first] + ''.join(areas) + text[first:]
        open(dsn, 'w', encoding='utf-8', newline='\n').write(text)
        if os.path.exists(ses):
            os.remove(ses)
        cmd = [args.java, '-jar', os.path.abspath(args.jar), '-de', 'cheap.dsn', '-do', 'cheap.ses',
               '-mp', str(args.passes), '-l', 'en', '--gui.enabled=false',
               '--router.fanout.enabled=false',              # no blanket via on every SMD pin
               '--usage_and_diagnostic_data.disable_analytics=true', '--profile.allow_telemetry=false']
        with open(os.path.join(args.work, 'freerouting.log'), 'w') as log:
            subprocess.run(cmd, cwd=args.work, stdout=log, stderr=subprocess.STDOUT, check=True)
    assert os.path.exists(ses), 'no session file'
    assert p.ImportSpecctraSES(board, ses), 'session import failed'

    p.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    total = len(board.GetTracks())
    print(f'tracks and vias {total} (autorouter {total - fixed}), unrouted '
          f'{board.GetConnectivity().GetUnconnectedCount(False)}')
    if args.write:
        p.SaveBoard(args.board, board)
        text = open(args.board, encoding='utf-8').read().replace('\r\n', '\n')
        open(args.board, 'w', encoding='utf-8', newline='\n').write(text)
        print('saved')


if __name__ == '__main__':
    main()
