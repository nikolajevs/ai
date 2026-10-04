"""Text-level editor for the generated KiCad schematics of cheap-version; SPDX-License-Identifier: MIT.

The PCB_V1 sheets are generated: every pin has a 2.54 mm wire stub ending in a label or global label.
This module edits such a sheet without reformatting it: it replaces blocks of text, so untouched parts
of the file stay byte-identical. Used by make_cheap1.py; see hardware/cheap-version/README.md.
"""
from __future__ import annotations

import math
import re
import uuid
from pathlib import Path

NS = uuid.UUID("0b9c5d2e-6f1a-4f43-9d6a-3f6c1b2e7a10")
STUB = 2.54


def uid(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _children(text: str, open_idx: int):
    """(start, end) of the direct children of the list opening at open_idx."""
    out, depth, start, in_str = [], 0, 0, False
    i = open_idx + 1
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            if depth == 0:
                start = i
            depth += 1
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
            if depth == 0:
                out.append((start, i + 1))
        i += 1
    return out


def _head(block: str) -> str:
    return re.match(r"\(([^\s()]+)", block).group(1)


def _eat_indent(text: str, s: int) -> int:
    """start index that also swallows the tabs and the newline in front of a block"""
    while s > 0 and text[s - 1] == "\t":
        s -= 1
    if s > 0 and text[s - 1] == "\n":
        s -= 1
    return s


class Sheet:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8")

    def save(self, path: Path | None = None):
        Path(path or self.path).write_text(self.text, encoding="utf-8", newline="\n")

    # ------------------------------------------------------------------ block access
    def blocks(self):
        return [(s, e, _head(self.text[s:e])) for s, e in _children(self.text, self.text.index("("))]

    def symbol(self, ref: str):
        key = f'(property "Reference" "{ref}"'
        for s, e, h in self.blocks():
            if h == "symbol" and key in self.text[s:e]:
                return s, e
        raise KeyError(ref)

    def has_symbol(self, ref: str) -> bool:
        try:
            self.symbol(ref)
            return True
        except KeyError:
            return False

    def lib_symbol_span(self, lib_id: str):
        for s, e, h in self.blocks():
            if h == "lib_symbols":
                for cs, ce in _children(self.text, s):
                    if self.text[cs:ce].startswith(f'(symbol "{lib_id}"'):
                        return cs, ce
                return None
        return None

    def lib_symbols_span(self):
        for s, e, h in self.blocks():
            if h == "lib_symbols":
                return s, e
        raise KeyError("lib_symbols")

    # ------------------------------------------------------------------ geometry
    @staticmethod
    def parse_pins(lib_text: str):
        pins = []
        for m in re.finditer(r'\(pin\s+(\w+)\s+(\w+)\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)\s*\(length\s+([\d.]+)\)(.*?)\(number\s+"([^"]*)"',
                             lib_text, re.S):
            name = re.search(r'\(name\s+"([^"]*)"', m.group(7))
            pins.append(dict(etype=m.group(1), x=float(m.group(3)), y=float(m.group(4)), angle=int(m.group(5)),
                             number=m.group(8), name=name.group(1) if name else ""))
        return pins

    def instance_transform(self, blk: str):
        lib_id = re.search(r'\(lib_id "([^"]+)"\)', blk).group(1)
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+) (\d+)\)", blk)
        mirror = re.search(r"\(mirror (\w)\)", blk)
        return lib_id, float(at.group(1)), float(at.group(2)), int(at.group(3)), mirror.group(1) if mirror else None

    @staticmethod
    def pin_point(px, py, X, Y, rot, mirror):
        x, y = px, py
        if mirror == "x":
            y = -y
        elif mirror == "y":
            x = -x
        th = math.radians(rot)
        xr = x * math.cos(th) - y * math.sin(th)
        yr = x * math.sin(th) + y * math.cos(th)
        return round(X + xr, 2), round(Y - yr, 2)

    def pins_of_instance(self, ref: str):
        s, e = self.symbol(ref)
        blk = self.text[s:e]
        lib_id, X, Y, rot, mirror = self.instance_transform(blk)
        ls = self.lib_symbol_span(lib_id)
        pins = self.parse_pins(self.text[ls[0]:ls[1]])
        out = []
        for p in pins:
            pt = self.pin_point(p["x"], p["y"], X, Y, rot, mirror)
            out.append(dict(p, point=pt))
        return out

    # ------------------------------------------------------------------ wire helpers
    def _wires(self):
        res = []
        for s, e, h in self.blocks():
            if h == "wire":
                m = re.search(r"\(xy ([-\d.]+) ([-\d.]+)\)\s*\(xy ([-\d.]+) ([-\d.]+)\)", self.text[s:e])
                res.append((s, e, (round(float(m.group(1)), 2), round(float(m.group(2)), 2)),
                            (round(float(m.group(3)), 2), round(float(m.group(4)), 2))))
        return res

    def _marks_at(self, point):
        """label / global_label / no_connect blocks anchored at point"""
        res = []
        for s, e, h in self.blocks():
            if h in ("label", "global_label", "no_connect", "hierarchical_label"):
                m = re.search(r"\(at ([-\d.]+) ([-\d.]+)", self.text[s:e])
                if m and (round(float(m.group(1)), 2), round(float(m.group(2)), 2)) == point:
                    res.append((s, e))
        return res

    # ------------------------------------------------------------------ editing
    def pin_nets(self, ref: str):
        """{pin number: label text at the end of the stub} as found in the sheet (for reporting)"""
        res = {}
        wires = self._wires()
        for p in self.pins_of_instance(ref):
            far = None
            for s, e, a, b in wires:
                if a == p["point"]:
                    far = b
                elif b == p["point"]:
                    far = a
            if far:
                for s, e in self._marks_at(far):
                    m = re.search(r'^\((?:label|global_label) "([^"]*)"', self.text[s:e])
                    if m:
                        res[p["number"]] = m.group(1)
        return res

    def remove_symbol(self, ref: str):
        pins = self.pins_of_instance(ref)
        wires = self._wires()
        spans = [self.symbol(ref)]
        for p in pins:
            for s, e, a, b in wires:
                if p["point"] in (a, b):
                    far = b if a == p["point"] else a
                    spans.append((s, e))
                    others = [w for w in wires if w[0] != s and far in (w[2], w[3])]
                    if not others:
                        spans.extend(self._marks_at(far))
            spans.extend(self._marks_at(p["point"]))
        for s, e in sorted(set(spans), reverse=True):
            self.text = self.text[:_eat_indent(self.text, s)] + self.text[e:]

    def delete_blocks(self, heads):
        """delete every top-level block whose head is in heads (e.g. wire, junction, label)"""
        for s, e, h in sorted(self.blocks(), reverse=True):
            if h in heads:
                self.text = self.text[:_eat_indent(self.text, s)] + self.text[e:]

    def set_prop(self, ref: str, name: str, value: str):
        s, e = self.symbol(ref)
        blk = self.text[s:e]
        pat = re.compile(r'(\(property "' + re.escape(name) + r'" )"[^"]*"')
        if pat.search(blk):
            blk = pat.sub(lambda m: m.group(1) + '"' + value.replace('"', "'") + '"', blk, count=1)
        else:
            lc = re.search(r'\t\t\(property "LCSC" "[^"]*"\n(?:\t\t\t.*\n)*?\t\t\)\n', blk)
            anchor = lc.end() if lc else blk.index("\t\t(pin ")
            at = re.search(r"\(at ([-\d.]+ [-\d.]+ \d+)\)", blk).group(1)
            new = (f'\t\t(property "{name}" "{value}"\n\t\t\t(at {at})\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n'
                   f'\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t\t(justify left)\n\t\t\t)\n\t\t)\n')
            blk = blk[:anchor] + new + blk[anchor:]
        self.text = self.text[:s] + blk + self.text[e:]

    def props(self, ref: str):
        s, e = self.symbol(ref)
        return dict(re.findall(r'\(property "([^"]+)" "([^"]*)"', self.text[s:e]))

    def prop_pos(self, ref: str, name: str):
        s, e = self.symbol(ref)
        m = re.search(r'\(property "' + re.escape(name) + r'" "[^"]*"\s*\(at ([-\d.]+) ([-\d.]+)', self.text[s:e])
        return float(m.group(1)), float(m.group(2))

    def set_lib_id(self, ref: str, lib_id: str):
        s, e = self.symbol(ref)
        blk = re.sub(r'\(lib_id "[^"]+"\)', f'(lib_id "{lib_id}")', self.text[s:e], count=1)
        self.text = self.text[:s] + blk + self.text[e:]

    def replace_text(self, startswith: str, new: str):
        """replace the string of a free text note that starts with `startswith`"""
        for s, e, h in self.blocks():
            if h == "text" and self.text[s:e].startswith(f'(text "{startswith}'):
                blk = re.sub(r'^\(text "(?:[^"\\]|\\.)*"', lambda m: '(text "' + new.replace('"', "'") + '"', self.text[s:e])
                self.text = self.text[:s] + blk + self.text[e:]
                return
        raise KeyError(startswith)

    def ensure_lib_symbol(self, lib_id: str, text: str):
        """text: full '(symbol "Lib:Name" ...)' block indented for the lib_symbols container (2 tabs)."""
        if self.lib_symbol_span(lib_id):
            return
        s, e = self.lib_symbols_span()
        close = self.text.rindex(")", s, e)
        j = close
        while self.text[j - 1] in "\t":
            j -= 1
        self.text = self.text[:j] + text.rstrip("\n") + "\n" + self.text[j:]

    def prune_lib_symbols(self):
        """drop embedded library symbols that no instance uses any more"""
        used = set(re.findall(r'\(lib_id "([^"]+)"\)', self.text))
        s, e = self.lib_symbols_span()
        for cs, ce in sorted(_children(self.text, s), reverse=True):
            name = re.match(r'\(symbol "([^"]+)"', self.text[cs:ce]).group(1)
            if name not in used:
                self.text = self.text[:_eat_indent(self.text, cs)] + self.text[ce:]

    def instance_path(self):
        return re.search(r'\(path "([^"]+)"', self.text).group(1)

    def project_name(self):
        return re.search(r'\(project "([^"]+)"', self.text).group(1)

    # ------------------------------------------------------------------ new items
    def _append(self, texts):
        end = self.text.rstrip().rindex(")")
        j = end
        while self.text[j - 1] in "\t":
            j -= 1
        self.text = self.text[:j] + "\n".join(texts) + "\n" + self.text[j:]

    def _stub_text(self, ref, pins, X, Y, rot, mirror, nets, global_nets):
        extra = []
        for p in pins:
            net = nets.get(p["number"], "__missing__")
            if net == "__missing__":
                raise KeyError(f"{ref} pin {p['number']} ({p['name']}) has no net assignment")
            px, py = self.pin_point(p["x"], p["y"], X, Y, rot, mirror)
            if net is None:
                extra.append(f"\t(no_connect\n\t\t(at {fmt(px)} {fmt(py)})\n\t\t(uuid {uid(ref, 'nc', p['number'], self.path.name)})\n\t)")
                continue
            # the stub leaves the pin away from the body
            direction = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[(p["angle"] + rot) % 360]
            qx, qy = round(px + direction[0] * STUB, 2), round(py + direction[1] * STUB, 2)
            extra.append(f"\t(wire\n\t\t(pts\n\t\t\t(xy {fmt(px)} {fmt(py)}) (xy {fmt(qx)} {fmt(qy)})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n"
                         f"\t\t\t(type default)\n\t\t)\n\t\t(uuid {uid(ref, 'wire', p['number'], self.path.name)})\n\t)")
            angle, just = {(-1, 0): (180, "right bottom"), (1, 0): (0, "left bottom"), (0, 1): (270, "right"), (0, -1): (90, "left")}[direction]
            if net in global_nets:
                extra.append(f'\t(global_label "{net}"\n\t\t(shape bidirectional)\n\t\t(at {fmt(qx)} {fmt(qy)} {angle})\n\t\t(effects\n'
                             f'\t\t\t(font\n\t\t\t\t(size 1.0 1.0)\n\t\t\t)\n\t\t\t(justify {just.split()[0]})\n\t\t)\n'
                             f"\t\t(uuid {uid(ref, 'label', p['number'], self.path.name)})\n\t)")
            else:
                extra.append(f'\t(label "{net}"\n\t\t(at {fmt(qx)} {fmt(qy)} {angle})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.0 1.0)\n'
                             f"\t\t\t)\n\t\t\t(justify {just})\n\t\t)\n\t\t(uuid {uid(ref, 'label', p['number'], self.path.name)})\n\t)")
        return extra

    def attach_stubs(self, ref: str, nets: dict, global_nets=()):
        """wire stubs and labels for every pin of an existing instance"""
        s, e = self.symbol(ref)
        lib_id, X, Y, rot, mirror = self.instance_transform(self.text[s:e])
        ls = self.lib_symbol_span(lib_id)
        pins = self.parse_pins(self.text[ls[0]:ls[1]])
        self._append(self._stub_text(ref, pins, X, Y, rot, mirror, nets, global_nets))

    def add_symbol(self, lib_id: str, ref: str, at, rot, props: dict, nets: dict, pos_ref=None, pos_value=None,
                   mirror=None, global_nets=()):
        """nets: {pin number: net name | None (no connect)}; global_nets: names written as global labels."""
        ls = self.lib_symbol_span(lib_id)
        pins = self.parse_pins(self.text[ls[0]:ls[1]])
        X, Y = at
        out = ["\t(symbol", f'\t\t(lib_id "{lib_id}")', f"\t\t(at {fmt(X)} {fmt(Y)} {rot})"]
        if mirror:
            out.append(f"\t\t(mirror {mirror})")
        out += ["\t\t(unit 1)", "\t\t(exclude_from_sim no)", "\t\t(in_bom yes)", "\t\t(on_board yes)", "\t\t(dnp no)",
                f"\t\t(uuid {uid(ref, 'sym', self.path.name)})"]
        allp = {"Reference": ref, **props}
        for k, v in allp.items():
            if k == "Reference" and pos_ref:
                px, py = pos_ref
            elif k == "Value" and pos_value:
                px, py = pos_value
            else:
                px, py = X, Y
            hide = "" if k in ("Reference", "Value") else "\t\t\t\t(hide yes)\n"
            out.append(f'\t\t(property "{k}" "{v}"\n\t\t\t(at {fmt(px)} {fmt(py)} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n'
                       f"\t\t\t\t)\n{hide}\t\t\t\t(justify left)\n\t\t\t)\n\t\t)")
        for p in pins:
            out.append(f'\t\t(pin "{p["number"]}"\n\t\t\t(uuid {uid(ref, "pin", p["number"], self.path.name)})\n\t\t)')
        out.append(f'\t\t(instances\n\t\t\t(project "{self.project_name()}"\n\t\t\t\t(path "{self.instance_path()}"\n'
                   f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)')
        out.append("\t)")
        extra = self._stub_text(ref, pins, X, Y, rot, mirror, nets, global_nets)
        self._append(out + extra)

    def global_net_names(self):
        return set(re.findall(r'\(global_label "([^"]*)"', self.text))

    def check_pins(self):
        """number of symbol pins with / without a wire or label at their connection point"""
        wires = self._wires()
        ok = bad = 0
        for s, e, h in self.blocks():
            if h != "symbol":
                continue
            ref = re.search(r'\(property "Reference" "([^"]*)"', self.text[s:e]).group(1)
            if ref.startswith("#"):
                continue
            for p in self.pins_of_instance(ref):
                if any(p["point"] in (a, b) for _, _, a, b in wires) or self._marks_at(p["point"]):
                    ok += 1
                else:
                    bad += 1
        return ok, bad


def load_stock_symbol(lib_file: Path, name: str, lib_nick: str) -> str:
    """Extract a symbol from a stock library and format it for embedding in a schematic (2-tab indent)."""
    t = Path(lib_file).read_text(encoding="utf-8")
    i = t.index(f'(symbol "{name}"')
    depth, j, in_str = 0, i, False
    while True:
        c = t[j]
        if in_str:
            if c == "\\":
                j += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    blk = t[i:j + 1].replace(f'(symbol "{name}"', f'(symbol "{lib_nick}:{name}"', 1)
    return "\n".join(("\t" + ln if ln.strip() else ln) for ln in ("\t" + blk).split("\n"))
