#!/usr/bin/env python3
"""BOM and purchase list of cheap-1 from the schematic and the stock list; SPDX-License-Identifier: MIT.

Usage:  python hardware/cheap-version/tools/export_bom.py [netlist.xml]
        (without an argument the netlist is exported with kicad-cli; KICAD_CLI overrides the executable)

Writes hardware/cheap-version/BOM_cheap1.csv (every fitted line, with the stock check) and BUY_cheap1.csv (what has to be
bought, LCSC order quantities rounded to the minimum and multiple of the PCB_V1 price list). Prices are the 28-30.09.2026
LCSC snapshot behind ../PCB_V1/BOM_PCB_V1_v22.csv, with exact-part overrides dated 2026-10-04 below, matched by LCSC number or MPN: lines without a match have no price.
The "Source" field of a schematic part is "stock:<id>" for parts taken from stock/components-*.csv.
Also writes BOM_LCSC_cheap1.csv for LCSC import: purchased parts only, grouped by LCSC code,
with quantities rounded once per code to the snapshot minimum/multiple. Parts without a code are reported separately.
"""
from __future__ import annotations

import csv
import math
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
V1_BOM = HERE.parent / "PCB_V1" / "BOM_PCB_V1_v22.csv"
STOCK = sorted((HERE / "stock").glob("components-*.csv"))[-1]
SKIP_PREFIX = ("#", "NT", "TP")
# parts that are not on the schematic but are bought for the board (as in PCB_V1); the 10 A blade fuse for F902 is not
# bought (the user has fuses), only the holder
EXTRAS = [
    dict(refs="BT301", value="CR2032 cell", footprint="", mpn="CR2032", mfr="", lcsc="", source="buy"),
]


def natural(ref):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref)]


def netlist_path(argv):
    if len(argv) > 1:
        return Path(argv[1])
    out = Path(tempfile.mkdtemp()) / "cheap1.xml"
    cli = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
    subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out),
                    str(HERE / "cheap-version.kicad_sch")], check=True, capture_output=True)
    return out


def load_stock():
    stock = {}
    with open(STOCK, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            stock[row["id"]] = dict(qty=int(row["остаток"] or 0), name=row["название"], value=row["номинал"])
    return stock


# Exact-part LCSC snapshot checked 2026-10-04; normal price, no temporary discount.
# mpn: (LCSC, minimum/multiple, USD each, stock at observation)
VERIFIED = {
    "0603WAF3162T5E": ("C25967", 100, 0.0022, 77300),
    "0603WAF4703T5E": ("C23178", 100, 0.0030, 1017700),
    "RT0603BRD0788K7L": ("C728599", 20, 0.0380, 7680),
    "FXL0630-4R7-M": ("C167220", 5, 0.1695, 72865),
    "JER2512F3R120": ("C49164917", 5, 0.0771, 56525),
}


def load_prices():
    by_lcsc, by_mpn, by_ref = {}, {}, {}
    with open(V1_BOM, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            def num(key, default=0.0):
                try:
                    return float(row[key])
                except (KeyError, ValueError):
                    return default
            info = dict(min=int(num("LCSC minimum", 1)), mult=int(num("LCSC multiple", 1)), unit=num("Unit USD 1 board"),
                        lcsc=row["LCSC Part Number"], page=row.get("LCSC page", ""))
            info.update(mpn=row["MPN"], mfr=row["Manufacturer"])
            if info["unit"]:
                if row["LCSC Part Number"]:
                    by_lcsc[row["LCSC Part Number"]] = info
                if row["MPN"]:
                    by_mpn[row["MPN"].casefold()] = info
                for ref in row["Designators"].split():
                    by_ref[ref] = info
    for mpn, (code, minimum, unit, available) in VERIFIED.items():
        info = dict(min=minimum, mult=minimum, unit=unit, lcsc=code, mpn=mpn,
                    page=f"https://www.lcsc.com/product-detail/{code}.html",
                    checked="2026-10-04", available=available)
        by_lcsc[code] = by_mpn[mpn.casefold()] = info
    return by_lcsc, by_mpn, by_ref


def groups(netlist):
    root = ET.parse(netlist).getroot()
    lines = defaultdict(list)
    for comp in root.findall(".//components/comp"):
        ref = comp.get("ref")
        if ref.startswith(SKIP_PREFIX):
            continue
        value = (comp.findtext("value") or "").strip()
        if "DNP" in value:
            continue
        fields = {f.get("name"): (f.text or "").strip() for f in comp.findall("fields/field")}
        key = (re.sub(r"\s*/\s*(comp|CS|slope)\s+tune$", "", value), comp.findtext("footprint") or "", fields.get("MPN", ""),
               fields.get("Manufacturer", ""), fields.get("LCSC", ""), fields.get("Source", ""))
        lines[key].append(ref)
    return lines


def write_lcsc_import(rows):
    parts = {}
    excluded = []
    for row in rows:
        if not row["lcsc"]:
            excluded.append(row)
            continue
        code = row["lcsc"]
        if not re.fullmatch(r"C[0-9]+", code):
            raise ValueError(f"Invalid LCSC code for {row['refs']}: {code}")
        if not row["price"]:
            raise ValueError(f"No minimum/multiple for {row['refs']} ({code})")
        part = parts.setdefault(code, dict(mpn=row["mpn"], mfr=row["mfr"], refs=[], values=[], need=0,
                                          minimum=row["price"]["min"], multiple=row["price"]["mult"]))
        if (part["mpn"], part["minimum"], part["multiple"]) != (
                row["mpn"], row["price"]["min"], row["price"]["mult"]):
            raise ValueError(f"Conflicting MPN or order limits for {code}")
        part["need"] += row["to_buy"]
        part["refs"].append(row["refs"])
        if row["value"] not in part["values"]:
            part["values"].append(row["value"])
    output = HERE / "BOM_LCSC_cheap1.csv"
    total = 0
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Quantity", "LCSC Part Number", "Manufacturer Part Number", "Manufacturer", "Description",
                         "Customer Part Number"])
        for code, part in parts.items():
            quantity = max(part["minimum"], math.ceil(part["need"] / part["multiple"]) * part["multiple"])
            writer.writerow([quantity, code, part["mpn"], part["mfr"], "; ".join(part["values"]), " ".join(part["refs"])])
            total += quantity
    print(f"LCSC import: {len(parts)} codes, {total} ordered pieces -> {output.name}")
    for row in excluded:
        print(f"  excluded from LCSC import (no code): {row['refs']} {row['value']}")


def main():
    stock = load_stock()
    by_lcsc, by_mpn, by_ref = load_prices()
    rows = []
    for (value, footprint, mpn, mfr, lcsc, source), refs in groups(netlist_path(sys.argv)).items():
        rows.append(dict(refs=" ".join(sorted(refs, key=natural)), qty=len(refs), value=value, footprint=footprint.split(":")[-1],
                         mpn=mpn, mfr=mfr, lcsc=lcsc, source=source))
    for extra in EXTRAS:
        rows.append(dict(extra, qty=1))
    rows.sort(key=lambda r: (re.match(r"[A-Z]+", r["refs"]).group(), natural(r["refs"].split()[0])))

    used = defaultdict(int)
    for r in rows:
        m = re.match(r"stock:(\d+)", r["source"])
        r["stock_id"] = m.group(1) if m else ""
        if r["stock_id"]:
            used[r["stock_id"]] += r["qty"]
    total = 0.0
    problems = []
    for i, r in enumerate(rows, 1):
        r["line"] = i
        sid = r["stock_id"]
        r["from_stock"], r["to_buy"] = 0, r["qty"]
        if sid:
            if sid not in stock:
                problems.append(f"line {i} {r['refs']}: stock id {sid} is not in the stock list")
                continue
            have = stock[sid]["qty"]
            r["from_stock"] = min(r["qty"], have)
            r["to_buy"] = r["qty"] - r["from_stock"]
            r["stock_note"] = f"id {sid}: {have} in stock, {used[sid]} used"
            if used[sid] > have:
                problems.append(f"stock id {sid} ({stock[sid]['name']}): needed {used[sid]}, in stock {have}")
            elif used[sid] == have:
                r["stock_note"] += " (no spare)"
        else:
            r["stock_note"] = ""
        r["price"] = by_lcsc.get(r["lcsc"]) or by_mpn.get(r["mpn"].casefold())
        if not r["price"] and not r["mpn"]:               # the schematic has no part number: take it from the V1 line of the same reference
            v1 = by_ref.get(r["refs"].split()[0])
            if v1:
                r["price"] = v1
                r["mpn"], r["mfr"], r["lcsc"] = v1["mpn"], v1["mfr"], v1["lcsc"]
        if r["to_buy"]:
            if r["price"]:
                p = r["price"]
                r["order_qty"] = max(p["min"], math.ceil(r["to_buy"] / p["mult"]) * p["mult"])
                r["order_usd"] = round(r["order_qty"] * p["unit"], 4)
                total += r["order_usd"]
            else:
                r["order_qty"], r["order_usd"] = "", ""

    with open(HERE / "BOM_cheap1.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Line", "Designators", "Qty", "Value", "Footprint", "Manufacturer", "MPN", "LCSC", "Source", "From stock",
                    "To buy", "Stock note"])
        for r in rows:
            w.writerow([r["line"], r["refs"], r["qty"], r["value"], r["footprint"], r["mfr"], r["mpn"], r["lcsc"],
                        r["source"] or "buy", r["from_stock"], r["to_buy"], r["stock_note"]])
    buy = [r for r in rows if r["to_buy"]]
    with open(HERE / "BUY_cheap1.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Line", "Designators", "Value", "MPN", "Manufacturer", "LCSC", "Need", "Order qty (LCSC min/multiple)",
                    "Unit USD", "Order USD", "Note"])
        for r in buy:
            p = r["price"]
            note = "no price: buy locally / check supplier" if not p else "V1 price snapshot 2026-09-28..30; stock not refreshed"
            if p and p.get("checked"):
                note = f"LCSC checked {p['checked']}; stock {p['available']}; {p['page']}"
            if r["source"].startswith("buy:"):
                note = (note + "; " if note else "") + r["source"][4:].strip()
            w.writerow([r["line"], r["refs"], r["value"], r["mpn"], r["mfr"], r["lcsc"], r["to_buy"],
                        r.get("order_qty", ""), p["unit"] if p else "", r.get("order_usd", ""), note])
    priced = sum(1 for r in buy if r["price"])
    print(f"{len(rows)} BOM lines, {sum(r['qty'] for r in rows)} parts; from stock {sum(r['from_stock'] for r in rows)}; "
          f"to buy {sum(r['to_buy'] for r in buy)} parts in {len(buy)} lines ({priced} priced)")
    print(f"order estimate (LCSC minimums, dated snapshot prices, {priced} of {len(buy)} lines): USD {total:.2f}")
    for line in problems:
        print("PROBLEM:", line)
    if problems:
        return 1
    write_lcsc_import(buy)
    for r in buy:
        if not r["price"]:
            print(f"  no price: line {r['line']} {r['refs']} {r['value']} {r['mpn']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
