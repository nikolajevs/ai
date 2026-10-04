#!/usr/bin/env python3
"""Preview renders of the enclosure with the PCB_V1 STEP inside (CadQuery + VTK, off-screen).

Usage:  python hardware/enclosure/render_enclosure.py board.step [out_dir] [view ...]
Views: assembled_front assembled_back exploded open_top lid_inside section_snap section_front (default: all). The board is drawn without colours from
the STEP (PCB green, parts dark grey); this is a review aid, not a photorealistic render.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq
import numpy as np
import vtk
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import enclosure as enc  # noqa: E402

BASE_COLOR, LID_COLOR = (0.80, 0.82, 0.85), (0.55, 0.70, 0.85)
PCB_COLOR, PART_COLOR = (0.08, 0.42, 0.20), (0.22, 0.22, 0.25)


def read_solids(path):
    reader = STEPControl_Reader()
    reader.ReadFile(str(path))
    reader.TransferRoots()
    out = []
    exp = TopExp_Explorer(reader.OneShape(), TopAbs_SOLID)
    while exp.More():
        out.append(cq.Shape.cast(exp.Current()))
        exp.Next()
    return out


def polydata(shape, tol, offset=(0, 0, 0)):
    verts, tris = shape.tessellate(tol, 0.4)
    pts = np.array([(v.x + offset[0], v.y + offset[1], v.z + offset[2]) for v in verts], dtype=float)
    cells = np.hstack([np.full((len(tris), 1), 3), np.array(tris)]).astype(np.int64)
    poly = vtk.vtkPolyData()
    p = vtk.vtkPoints()
    p.SetData(numpy_to_vtk(pts, deep=True))
    poly.SetPoints(p)
    arr = vtk.vtkCellArray()
    arr.SetCells(len(tris), numpy_to_vtkIdTypeArray(cells.ravel(), deep=True))
    poly.SetPolys(arr)
    return poly


def merge(polys):
    app = vtk.vtkAppendPolyData()
    for p in polys:
        app.AddInputData(p)
    app.Update()
    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(app.GetOutput())
    clean.SetTolerance(1e-4)
    clean.Update()
    return clean.GetOutput()


SECTION_COLOR = (0.95, 0.40, 0.10)


def section_actors(items, x0):
    """Exact section: keep x >= x0, cut faces coloured. items: (cq.Shape, colour, tessellation tolerance)."""
    slab = cq.Solid.makeBox(400, 400, 400, pnt=cq.Vector(x0, -200, -100))
    by_color, cut_polys = {}, []
    for shape, color, tol in items:
        bb = shape.BoundingBox()
        if bb.xmax <= x0:
            continue
        if bb.xmin < x0:
            shape = shape.intersect(slab)
        for face in shape.Faces():
            fb = face.BoundingBox()
            if fb.xlen < 1e-3 and abs(fb.xmin - x0) < 1e-3:
                cut_polys.append(polydata(face, tol))
            else:
                by_color.setdefault(color, []).append(polydata(face, tol))
    return [actor(merge(polys), color) for color, polys in by_color.items()] + [actor(merge(cut_polys), SECTION_COLOR)]


def actor(poly, color, opacity=1.0):
    nrm = vtk.vtkPolyDataNormals()
    nrm.SetInputData(poly)
    nrm.SetFeatureAngle(35)
    nrm.SplittingOn()
    nrm.Update()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(nrm.GetOutput())
    act = vtk.vtkActor()
    act.SetMapper(mapper)
    prop = act.GetProperty()
    prop.SetColor(*color)
    prop.SetOpacity(opacity)
    prop.SetSpecular(0.15)
    prop.SetAmbient(0.25)
    return act


def shot(actors, path, eye_dir, focus, dist, up=(0, 0, 1), size=(1500, 1000), parallel=None):
    ren = vtk.vtkRenderer()
    ren.SetBackground(1, 1, 1)
    for a in actors:
        ren.AddActor(a)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(ren)
    win.SetSize(*size)
    win.SetMultiSamples(8)
    cam = ren.GetActiveCamera()
    d = np.array(eye_dir, float)
    d /= np.linalg.norm(d)
    cam.SetFocalPoint(*focus)
    cam.SetPosition(*(np.array(focus) + d * dist))
    cam.SetViewUp(*up)
    if parallel:
        cam.ParallelProjectionOn()
        cam.SetParallelScale(parallel)
    light = vtk.vtkLight()
    light.SetLightTypeToCameraLight()
    light.SetPosition(0.5, 0.8, 1.0)
    ren.AddLight(light)
    ren.ResetCameraClippingRange()
    win.Render()
    img = vtk.vtkWindowToImageFilter()
    img.SetInput(win)
    img.Update()
    png = vtk.vtkPNGWriter()
    png.SetFileName(str(path))
    png.SetInputConnection(img.GetOutputPort())
    png.Write()
    print("wrote", path)


def main():
    board_step = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "renders"
    out.mkdir(exist_ok=True)
    views = set(sys.argv[3:])

    def want(name):
        return not views or name in views

    base_shape = cq.importers.importStep(str(HERE / "GrowBox_base.step")).val()
    lid_shape = cq.importers.importStep(str(HERE / "GrowBox_lid.step")).val()
    base, lid = polydata(base_shape, 0.05), polydata(lid_shape, 0.05)
    pcb, parts, board_shapes = [], [], []
    for sh in read_solids(board_step):
        bb = sh.BoundingBox()
        is_pcb = bb.zmin < 0.01 and bb.zmax < 1.7 and bb.xlen > 90
        board_shapes.append((sh, is_pcb))
        (pcb if is_pcb else parts).append(polydata(sh, 0.15))
    board_actors = [actor(merge(pcb), PCB_COLOR), actor(merge(parts), PART_COLOR)]
    lift = 38.0
    lid_up = vtk.vtkTransform()
    lid_up.Translate(0, 0, lift)
    lid_up_poly = vtk.vtkTransformPolyDataFilter()
    lid_up_poly.SetInputData(lid)
    lid_up_poly.SetTransform(lid_up)
    lid_up_poly.Update()
    c = (100, -100, 8)

    if want("assembled_front"):
        shot([actor(base, BASE_COLOR), actor(lid, LID_COLOR)], out / "assembled_front.png", (-0.55, -1.0, 0.75), c, 330)
    if want("assembled_back"):
        shot([actor(base, BASE_COLOR), actor(lid, LID_COLOR)], out / "assembled_back.png", (0.6, 1.0, 0.75), c, 330)
    if want("exploded"):
        shot([actor(base, BASE_COLOR), actor(lid_up_poly.GetOutput(), LID_COLOR)] + board_actors, out / "exploded.png",
             (-0.55, -1.0, 0.65), (100, -100, 14), 380)
    if want("open_top"):
        shot([actor(base, BASE_COLOR)] + board_actors, out / "open_top.png", (0, -0.05, 1), (100, -100, 0), 250, up=(0, 1, 0))
    if want("lid_inside"):
        lid_flip = vtk.vtkTransform()
        lid_flip.RotateX(180)
        lid_flip_poly = vtk.vtkTransformPolyDataFilter()
        lid_flip_poly.SetInputData(lid)
        lid_flip_poly.SetTransform(lid_flip)
        lid_flip_poly.Update()
        shot([actor(lid_flip_poly.GetOutput(), LID_COLOR)], out / "lid_inside.png", (0, -0.05, 1), (100, 100, -12), 250,
             up=(0, 1, 0))
    if want("section_snap") or want("section_front"):
        items = [(base_shape, BASE_COLOR, 0.05), (lid_shape, LID_COLOR, 0.05)] + [(sh, PCB_COLOR if is_pcb else PART_COLOR, 0.15)
                                                                                  for sh, is_pcb in board_shapes]
        if want("section_snap"):   # through the T-wall snap at KiCad x = 100, seen from -X (T wall on the left)
            shot(section_actors(items, 100.0), out / "section_snap.png", (-1, 0, 0), (100, -57, 8), 200,
                 parallel=24, size=(1200, 1000))
        if want("section_front"):  # through terminal J711 (KiCad x = 60), B wall on the right
            shot(section_actors(items, 60.0), out / "section_front.png", (-1, 0, 0), (60, -142, 8), 200,
                 parallel=24, size=(1200, 1000))


if __name__ == "__main__":
    main()
