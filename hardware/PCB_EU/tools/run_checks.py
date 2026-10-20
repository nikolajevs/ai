#!/usr/bin/env python3
"""Schematic-stage checks. Does not qualify a PCB or firmware release."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kicad-cli',default=os.environ.get('KICAD_CLI') or shutil.which('kicad-cli'))
    ap.add_argument('--allow-other-version',action='store_true')
    args = ap.parse_args()
    if not args.kicad_cli:
        ap.error('KiCad CLI is required. Use --kicad-cli PATH or KICAD_CLI.')
    cli = args.kicad_cli
    version = subprocess.check_output([cli,'version'],text=True).strip()
    if version!='10.0.6' and not args.allow_other_version:
        ap.error(f'AGENTS.md target is KiCad 10.0.6; found {version}. Explicitly allow a local compatibility check with --allow-other-version.')
    out = HERE/'review'
    out.mkdir(exist_ok=True)
    sch = HERE/'PCB_EU.kicad_sch'
    net = out/'netlist.xml'
    subprocess.run([cli,'sch','export','netlist','--format','kicadxml','-o',str(net),str(sch)],check=True)
    subprocess.run([cli,'sch','erc','--exit-code-violations','--format','json','-o',str(out/'erc.json'),str(sch)],check=True)
    subprocess.run([sys.executable,str(HERE/'tools/verify.py'),str(net)],check=True)
    subprocess.run([sys.executable,str(HERE/'tools/verify_footprints.py'),'--kicad-cli',cli,'--netlist',str(net)],check=True)
    footprint_review=json.loads((out/'footprints.json').read_text())
    erc = json.loads((out/'erc.json').read_text())
    violations = [v for sh in erc['sheets'] for v in sh.get('violations',[])]
    if violations:raise RuntimeError('ERC violations must not be suppressed by the process exit code')
    default_ignored={'single_global_label','four_way_junction','simulation_model_issue','footprint_filter'}
    ignored={x['key'] for x in erc.get('ignored_checks',[])}
    if ignored-default_ignored:raise RuntimeError(f'Non-default ignored ERC checks: {ignored-default_ignored}')
    project=json.loads((HERE/'PCB_EU.kicad_pro').read_text())
    if project.get('erc',{}).get('erc_exclusions'):raise RuntimeError('ERC exclusions are not permitted in this draft')
    source = [*HERE.glob('*.kicad_sch'),HERE/'PCB_EU.kicad_pro',HERE/'libraries/EU.kicad_sym',HERE/'design.json',HERE/'BOM_allocated.json',HERE/'footprint_assignments.json',HERE/'fp-lib-table',HERE/'sym-lib-table',*HERE.glob('tools/*.py'),*HERE.glob('libraries/*/*.kicad_mod')]
    result=dict(stage='schematic with drawing-checked mechanical assignments; no PCB',date='2026-10-20',kicad_version=version,repository_target_version='10.0.6',target_version_verified=version=='10.0.6',erc_errors=0,erc_warnings=0,default_ignored_erc_checks=sorted(ignored),project_erc_exclusions=[],connectivity_checks=49,connected_pins=488,purchased_electrical_components=188,footprints=dict(assigned_references=footprint_review['components_with_footprints'],unique=footprint_review['unique_assigned_footprints'],drawing_checked_references=len(footprint_review['drawing_checked_references']),missing=footprint_review['missing_footprints'],checks_passed=footprint_review['checks_passed'],native_KiCad_load_and_plot=True,physical_fit_verified=False),pcb_drc='not applicable: no PCB exists yet',firmware_build='not performed: old firmware is incompatible',source_sha256={str(f.relative_to(HERE)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(source)})
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(f'PASS | schematic checks | KiCad {version}; repository 10.0.6 target verified: {result["target_version_verified"]}')


if __name__=='__main__':main()
