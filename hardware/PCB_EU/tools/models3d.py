#!/usr/bin/env python3
"""Attach/verify project-local models; never change electrical or 2D geometry.

Pure Python for source edits; no CadQuery/pcbnew dependency. SPDX-License-Identifier: MIT
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from verify_footprints import parse,children,child

HERE=Path(__file__).resolve().parents[1]
PREFIX='${KIPRJMOD}/libraries/EU.3dshapes/'
TOKEN=re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+')


def config():
    return json.loads((HERE/'models3d.json').read_text())


def spans(text,key):
    """Balanced forms, ignoring parentheses inside quoted strings."""
    stack=[];result=[];want_key=False
    for t in TOKEN.finditer(text):
        s=t.group()
        if s=='(':
            stack.append([t.start(),None]);want_key=True
        elif s==')':
            start,k=stack.pop()
            if k==key:result.append((start,t.end()))
            want_key=False
        elif want_key:
            stack[-1][1]=s;want_key=False
    if stack:raise ValueError('Unbalanced KiCad data')
    return result


def replace_model(text,filename,offset=None,rotation=None):
    found=spans(text,'model')
    if len(found)>1:raise ValueError('Unexpected multiple component models; preserve/review manually')
    if found:
        # Replace just the filename token, preserving the entire original file.
        a,b=found[0];block=text[a:b]
        matches=list(TOKEN.finditer(block));token=matches[2]
        quoted=token.group().startswith('"')
        name=json.dumps(filename) if quoted else filename
        block=block[:token.start()]+name+block[token.end():]
        for key,vector in [('offset',offset),('rotate',rotation)]:
            if vector is None:continue
            forms=spans(block,key)
            if key=='offset' and not forms:forms=spans(block,'at')
            if len(forms)!=1:raise ValueError(f'Expected one model {key}')
            x,y=forms[0]
            value=' '.join(f'{v:g}' for v in vector)
            block=block[:x]+f'({key} (xyz {value}))'+block[y:]
        return text[:a]+block+text[b:]
    at=text.rfind(')')
    line_start=text.rfind('\n',0,at)+1
    closing_indent=text[line_start:at]
    if closing_indent.strip():
        line_start=at;closing_indent=''
    indent=closing_indent+'\t'
    offset=' '.join(f'{v:g}' for v in (offset if offset is not None else [0,0,0]))
    rotation=' '.join(f'{v:g}' for v in (rotation if rotation is not None else [0,0,0]))
    block=(indent+'(model '+json.dumps(filename)+'\n'+
           indent+f'\t(offset (xyz {offset}))\n'+indent+'\t(scale (xyz 1 1 1))\n'+
           indent+f'\t(rotate (xyz {rotation}))\n'+indent+')\n')
    return text[:line_start]+block+text[line_start:]


def library_paths():
    t=parse((HERE/'fp-lib-table').read_text())
    return {child(v,'name')[1]:Path(child(v,'uri')[1].replace('${KIPRJMOD}',str(HERE))) for v in children(t,'lib')}


def model_for(ref,footprint,cfg=None):
    cfg=cfg or config()
    mechanical=cfg.get('board_only_models',{}).get(ref)
    if mechanical:return mechanical['model']
    if ref.startswith(('TP','H')):return None
    return cfg['reference_overrides'].get(ref,cfg['footprints'].get(footprint))


def model_transform(ref,cfg):
    """Only explicitly configured board-only assemblies may use nonzero transforms."""
    spec=cfg.get('board_only_models',{}).get(ref,{})
    result=[]
    for key in ['offset_mm','rotation_deg']:
        vector=spec.get(key,[0,0,0])
        if len(vector)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vector):
            raise ValueError(f'{ref}: invalid {key}')
        result.append(vector)
    return result


def sync_sources():
    cfg=config();libs=library_paths();changed=[]
    for fp,name in cfg['footprints'].items():
        lib,base=fp.split(':');path=libs[lib]/(base+'.kicad_mod')
        old=path.read_text();new=replace_model(old,PREFIX+name)
        if old!=new:path.write_text(new);changed.append(fp)
    return changed


def attach_board(path):
    cfg=config();text=path.read_text();edits=[]
    for a,b in spans(text,'footprint'):
        block=text[a:b];node=parse(block)
        props={v[1]:v[2] for v in children(node,'property')}
        name=model_for(props['Reference'],node[1],cfg)
        if name:
            mechanical=props['Reference'] in cfg.get('board_only_models',{})
            offset,rotation=model_transform(props['Reference'],cfg)
            new=replace_model(block,PREFIX+name,offset if mechanical else None,rotation if mechanical else None)
            if new!=block:edits.append((a,b,new))
    for a,b,new in reversed(edits):text=text[:a]+new+text[b:]
    if edits:path.write_text(text)
    return len(edits)


def set_native(fp,ref):
    """Called by the native PCB builder, before any back-side transform."""
    import pcbnew as p
    cfg=config()
    name=model_for(ref,fp.GetFPID().GetUniStringLibId(),cfg)
    if name:
        md=p.FP_3DMODEL();md.m_Filename=PREFIX+name
        md.m_Scale=p.VECTOR3D(1,1,1)
        offset,rotation=model_transform(ref,cfg)
        md.m_Offset=p.VECTOR3D(*offset)
        md.m_Rotation=p.VECTOR3D(*rotation)
        fp.Models().clear();fp.Models().push_back(md)


def without_models(text):
    for a,b in reversed(spans(text,'model')):text=text[:a]+text[b:]
    return parse(text)


def verify(board):
    cfg=config();libs=library_paths();seen=[];mechanical_seen=[];source_files=set()
    for fp in children(parse(board.read_text()),'footprint'):
        props={v[1]:v[2] for v in children(fp,'property')};ref=props['Reference']
        wanted=model_for(ref,fp[1],cfg);mm=children(fp,'model')
        mechanical=ref in cfg.get('board_only_models',{})
        if wanted is None:
            assert ref.startswith(('TP','H')),(ref,'missing model assignment')
            assert not mm,(ref,'bare copper/hole should have no invented component model')
            continue
        assert len(mm)==1 and mm[0][1]==PREFIX+wanted,(ref,'wrong model')
        assert 'hide' not in mm[0] and not children(mm[0],'hide'),(ref,'hidden model')
        opacity=children(mm[0],'opacity')
        assert not opacity or float(opacity[0][1])==1,(ref,'nonopaque component model')
        assert child(child(mm[0],'scale'),'xyz')[1:]==['1','1','1'],(ref,'model scaling')
        offset,rotation=model_transform(ref,cfg)
        assert [float(v) for v in child(child(mm[0],'rotate'),'xyz')[1:]]==rotation,(ref,'unexpected model rotation')
        offsets=children(mm[0],'offset') or children(mm[0],'at')
        assert len(offsets)==1 and [float(v) for v in child(offsets[0],'xyz')[1:]]==offset,(ref,'unexpected model offset')
        path=HERE/'libraries/EU.3dshapes'/wanted
        assert path.is_file(),(ref,'missing STEP file',wanted)
        data=path.read_bytes()
        assert b'ISO-10303-21;' in data[:40],(ref,'invalid STEP header')
        assert hashlib.sha256(data).hexdigest()==cfg['models'][wanted]['sha256'],(ref,'model file changed')
        source_files.add(wanted)
        if mechanical:
            assert 'board_only' in child(fp,'attr'),(ref,'mechanical model must belong to a board-only footprint')
            mechanical_seen.append(ref)
        else:seen.append(ref)
    parts=[v for v in json.loads((HERE/'design.json').read_text())['parts'] if not v['ref'].startswith(('#','TP'))]
    assert set(seen)=={v['ref'] for v in parts},'Board/model/physical component set mismatch'
    assert set(mechanical_seen)==set(cfg.get('board_only_models',{})),'Configured board-only models missing from PCB'
    for fp,wanted in cfg['footprints'].items():
        lib,base=fp.split(':');path=libs[lib]/(base+'.kicad_mod')
        mm=children(parse(path.read_text()),'model')
        assert len(mm)==1 and mm[0][1]==PREFIX+wanted,(fp,'library attachment differs')
    # Retain all imported CAD contributor/licence files and audit exact bytes.
    for name,data in cfg['models'].items():
        path=HERE/'libraries/EU.3dshapes'/name
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==data['sha256'],name
    return dict(physical_components=len(seen),local_resolvable_models=len(seen),
                board_only_model_refs=sorted(mechanical_seen),board_only_resolvable_models=len(mechanical_seen),
                total_resolvable_models=len(seen)+len(mechanical_seen),
                unique_attached_models=len(source_files),missing_models=[],
                model_files=len(cfg['models']),library_footprints=len(cfg['footprints']),
                known_fit_issues=cfg['known_fit_issues'],mechanical_qualification=False)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write',action='store_true')
    ap.add_argument('--board',type=Path,default=HERE/'PCB_EU.kicad_pcb')
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    if args.write:
        before=without_models(args.board.read_text())
        print('Updated library footprints:',len(sync_sources()))
        print('Updated PCB model references:',attach_board(args.board))
        assert before==without_models(args.board.read_text()),'Non-3D board data changed'
    result=verify(args.board)
    if args.output:args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
