#!/usr/bin/env python3
"""DRC of isolated footprint samples. This is NOT DRC of the product PCB.

Run with the Python interpreter providing pcbnew from the same KiCad build.
No placement, routing, thermal, card access or assembly is qualified here.
SPDX-License-Identifier: MIT
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import pcbnew as pcb

HERE=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kicad-cli',required=True)
    args=ap.parse_args()
    cli_version=subprocess.check_output([args.kicad_cli,'version'],text=True).strip()
    if not pcb.GetBuildVersion().startswith(cli_version):raise RuntimeError('pcbnew and CLI versions differ')
    ids=sorted({p['footprint'] for p in json.loads((HERE/'design.json').read_text())['parts'] if p['footprint']})
    with tempfile.TemporaryDirectory(prefix='eu-isolated-fp-') as tmp:
        work=Path(tmp);board=pcb.BOARD();sources={}
        for i,fp_id in enumerate(ids):
            lib,name=fp_id.split(':');path=HERE/'libraries'/(lib+'.pretty')
            fp=pcb.FootprintLoad(str(path),name)
            if fp is None:raise RuntimeError(fp_id)
            fp.SetReference(f'X{i+1}')
            fp.SetPosition(pcb.VECTOR2I(pcb.FromMM(40+60*(i%4)),pcb.FromMM(40+50*(i//4))))
            fp.SetFPID(pcb.LIB_ID(lib,name));board.Add(fp);nets={}
            for pad in fp.Pads():
                number=pad.GetNumber()
                if not number:continue
                if number not in nets:
                    net=pcb.NETINFO_ITEM(board,f'X{i+1}_{number}');board.Add(net);nets[number]=net
                pad.SetNet(nets[number])
            f=path/(name+'.kicad_mod');sources[str(f.relative_to(HERE))]=hashlib.sha256(f.read_bytes()).hexdigest()
        for x1,y1,x2,y2 in [(0,0,260,0),(260,0,260,450),(260,450,0,450),(0,450,0,0)]:
            line=pcb.PCB_SHAPE();line.SetShape(pcb.SHAPE_T_SEGMENT);line.SetLayer(pcb.Edge_Cuts);line.SetWidth(pcb.FromMM(.05))
            line.SetStart(pcb.VECTOR2I(pcb.FromMM(x1),pcb.FromMM(y1)));line.SetEnd(pcb.VECTOR2I(pcb.FromMM(x2),pcb.FromMM(y2)));board.Add(line)
        pcb.SaveBoard(str(work/'isolated.kicad_pcb'),board)
        (work/'fp-lib-table').write_text((HERE/'fp-lib-table').read_text().replace('${KIPRJMOD}',str(HERE)))
        (work/'isolated.kicad_pro').write_text('{"meta":{"filename":"isolated.kicad_pro","version":3}}\n')
        report=work/'drc.json'
        subprocess.run([args.kicad_cli,'pcb','drc','--format','json','--output',str(report),str(work/'isolated.kicad_pcb')],check=True)
        raw=json.loads(report.read_text());violations=raw['violations']
        if violations:raise RuntimeError(Counter(v['type'] for v in violations))
        result={'scope':'isolated library samples, not the product PCB','kicad_version':cli_version,
                'pcbnew_build':pcb.GetBuildVersion(),'unique_footprints':len(ids),'violations':0,
                'unconnected_items':len(raw.get('unconnected_items',[])),
                'unconnected_reason':'Duplicate-number lands are intentionally not routed on the sample board. No product nets are present.',
                'product_pcb_drc':'not part of this isolated-sample check; see review/pcb_drc.json for the placement candidate',
                'source_sha256':sources}
        (HERE/'review/footprint_drc.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(f'PASS | isolated footprint DRC | {len(ids)} footprints, 0 violations; {result["unconnected_items"]} unrouted duplicate-pad connections')


if __name__=='__main__':main()
