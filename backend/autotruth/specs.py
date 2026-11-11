"""Official specification library: PDF parsing, structured facts, configuration matching.

A PDF becomes
  * chunks - one per (trim, section heading), the unit of retrieval
  * facts  - one per specification row, each tied to its chunk, page and exact line

Document identity (make / model / year / market) comes from a sidecar
``<file>.meta.json`` when present, otherwise it is inferred from the first page.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from . import config
from . import ontology as onto
from .models import Vehicle
from .units import UNIT_BY_NAME, Quantity, find_quantities

CELL_GAP = 9  # points of white space that separate two table cells on one row
TRIM_HEADING_RE = re.compile(r"^(?:trim|grade|variant|version|model grade)\s*[:\-–—]\s*(.+)$", re.IGNORECASE)
MARKETS = {
    "GCC": r"\bgcc\b|gulf|\buae\b|emirates|saudi|\bksa\b|middle east|qatar|kuwait|oman|bahrain|dubai",
    "UK": r"\buk\b|united kingdom|britain|british",
    "Europe": r"\beurope(?:an)?\b|\beu\b|germany|german|france",
    "US": r"\bu\.?s\.?a?\b|united states|north america|american market",
    "Japan": r"\bjapan(?:ese)?\b|\bjdm\b",
    "Australia": r"australia",
    "India": r"\bindia\b",
}


@dataclass
class SpecDoc:
    id: str
    file: str
    title: str
    make: str
    model: str
    year: int | None
    market: str | None
    trims: list[str]
    pages: int
    variants: list[str] = field(default_factory=list)  # column-table sheets: powertrains, body styles, grades
    source_url: str | None = None
    aliases: list[str] = field(default_factory=list)   # other names reviewers use for the model: "330i", "C-Class"


@dataclass
class Chunk:
    id: str
    doc_id: str
    trim: str | None
    heading: str
    page: int
    text: str
    standard: str | None = None


@dataclass
class Fact:
    id: str
    doc_id: str
    chunk_id: str
    trim: str | None
    page: int
    heading: str
    line: str
    label: str
    attribute: str
    kind: str  # numeric | count | categorical | feature
    quantities: list[Quantity] = field(default_factory=list)
    count: int | None = None
    value_text: str | None = None
    variant: str | None = None
    standard: str | None = None
    qualifiers: tuple[str, ...] = ()  # which variant(s) this row applies to: ("2.0 Hybrid", "Touring Sports")
    is_range: bool = False            # quantities hold a (low, high) pair, e.g. kerb weight 1,345 - 1,410 kg


@dataclass
class Config:
    doc: SpecDoc
    trim: str | None
    variant: str | None = None  # free-text variant named by the reviewer, for column-table sheets

    @property
    def label(self) -> str:
        v = Vehicle(make=self.doc.make, model=self.doc.model, year=self.doc.year, market=self.doc.market,
                    trim=self.trim or self.variant)
        return v.label()


# --------------------------------------------------------------------------- PDF layout


def _rows(page: fitz.Page) -> list[dict]:
    """Reconstruct visual rows (cells sharing a baseline) from positioned spans."""
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    x0, y0, x1, y1 = span["bbox"]
                    spans.append({"x0": x0, "x1": x1, "y": (y0 + y1) / 2, "text": text, "font": span["font"],
                                  "size": span["size"], "bold": bool(span["flags"] & 16)})
    fonts = Counter()
    for sp in spans:
        fonts[sp["font"]] += len(sp["text"])
    main_font = fonts.most_common(1)[0][0] if fonts else ""
    for sp in spans:
        if sp["font"] != main_font and re.search(r"bold|medium|semi|heavy|black|demi", sp["font"], re.IGNORECASE):
            sp["bold"] = True
    spans.sort(key=lambda s: (round(s["y"]), s["x0"]))
    rows: list[list[dict]] = []
    for s in spans:
        if rows and abs(rows[-1][0]["y"] - s["y"]) <= 3:
            rows[-1].append(s)
        else:
            rows.append([s])
    out = []
    for row in rows:
        row.sort(key=lambda s: s["x0"])
        cells: list[dict] = []
        for s in row:
            if cells and s["x0"] - cells[-1]["x1"] < CELL_GAP:
                cells[-1]["text"] += " " + s["text"]
                cells[-1]["x1"] = s["x1"]
            else:
                cells.append(dict(s))
        out.append({"cells": [c["text"] for c in cells], "x": [(c["x0"], c["x1"]) for c in cells],
                    "size": max(s["size"] for s in row), "bold": all(s["bold"] for s in row), "y": row[0]["y"]})
    return out


def _split(cells: list[str]) -> tuple[str, str] | None:
    if len(cells) >= 2:
        return cells[0].rstrip(":").strip(), " ".join(cells[1:]).strip()
    if ":" in cells[0]:
        label, value = cells[0].split(":", 1)
        if label.strip() and value.strip():
            return label.strip(), value.strip()
    return None


def _facts_for_line(label: str, value: str) -> list[dict]:
    facts: list[dict] = []
    avail = onto.availability(value)
    if avail:
        return [{"attribute": onto.FEATURE, "kind": "feature", "label": label, "value_text": avail}]
    attr = onto.label_attribute(label)
    if attr:
        if attr.kind == "numeric":
            qs = [q for q in find_quantities(value) if q.dimension == attr.dimension]
            if qs:
                variant = onto.fuel_variant(label) if attr.key == "fuel_economy" else None
                facts.append({"attribute": attr.key, "kind": "numeric", "quantities": qs, "variant": variant})
        elif attr.kind == "count":
            m = re.search(r"\d+", value)
            if m:
                facts.append({"attribute": attr.key, "kind": "count", "count": int(m.group(0))})
        else:
            cat = onto.categorical_value(attr, value)
            if cat:
                facts.append({"attribute": attr.key, "kind": "categorical", "value_text": cat})
    low = label.lower()
    if re.search(r"transmission|gearbox", low):
        m = re.search(r"(\d+)[- ]speed", value, re.IGNORECASE)
        if m:
            facts.append({"attribute": "gears", "kind": "count", "count": int(m.group(1))})
    if re.search(r"^engine(?: type| configuration| layout)?$", low):
        m = re.search(r"(\d+)[- ]cylinder|\bV(\d+)\b|inline[- ](\d+)", value, re.IGNORECASE)
        if m:
            facts.append({"attribute": "cylinders", "kind": "count", "count": int(next(g for g in m.groups() if g))})
        asp = onto.categorical_value(onto.ATTR["aspiration"], value)
        if asp:
            facts.append({"attribute": "aspiration", "kind": "categorical", "value_text": asp})
    return facts


def _infer_meta(path: Path, first_page_text: str) -> dict:
    stem_words = re.sub(r"[_\-]+", " ", path.stem).split()
    year = re.search(r"\b(19|20)\d{2}\b", first_page_text) or re.search(r"\b(19|20)\d{2}\b", path.stem)
    words = [w for w in stem_words if not re.fullmatch(r"\d{4}", w) and w.lower() not in {"spec", "specs", "specifications", "brochure"}]
    market = next((m for m, pat in MARKETS.items() if re.search(pat, first_page_text, re.IGNORECASE)), None)
    return {
        "make": words[0].title() if words else "Unknown",
        "model": " ".join(w.title() for w in words[1:2]) or "Unknown",
        "year": int(year.group(0)) if year else None,
        "market": market,
    }


# --------------------------------------------------------------------------- column-table sheets
#
# Real manufacturer sheets rarely say "Maximum power: 203 hp". They put the unit in the row label
# and the variants in columns:
#
#     PERFORMANCE              | 1.8 Hybrid | 2.0 Hybrid
#     Max Speed (mph)          |    112     |    112
#     0-62mph acceleration     | Hatchback  | 9.1 | 7.4
#     (sec)                    | Touring Sports | 9.4 | 7.7

_UNIT_TOKENS = {"din hp": "PS", "ps": "PS", "bhp": "hp", "sec": "s", "secs": "s", "m": "m", "l": "L",
                "litres": "L", "liters": "L", "lb ft": "lb-ft", "lb.ft": "lb-ft", "cu.ft": "cu ft", "cu-ft": "cu ft",
                "in": "in", "ftlbs": "lb-ft", "ft-lbs": "lb-ft", "gallons": "gal", "gal": "gal", "lbs": "lb", "cm³": "cc"}
_NUM = r"\d[\d,]*(?:\.\d+)?"


def _resolve_unit(token: str) -> str | None:
    t = re.sub(r"\s+", " ", token.strip().lower().rstrip("."))
    if t in _UNIT_TOKENS:
        return _UNIT_TOKENS[t]
    q = find_quantities(f"1 {t}")
    return q[0].unit if len(q) == 1 and q[0].raw == f"1 {t}" else None


def _quantity(value: float, unit: str) -> Quantity:
    text = f"{value:g}"
    return Quantity(value, unit, UNIT_BY_NAME[unit].dimension, 0, 0, f"{text} {unit}", len(text.split(".")[1]) if "." in text else 0)


def _label_units(label: str) -> tuple[str, list[str | None]]:
    """'Max. engine power (bhp/DIN hp/kW @ rpm)' -> ('Max. engine power', ['hp', 'PS', 'kW'])."""
    units: list[str | None] = []
    tail = re.search(r",\s*([^,()]{1,14})$", label)  # BMW: "Engine power (HP), PS" - the unit follows a comma
    if tail and _resolve_unit(tail.group(1)):
        return re.sub(r"\s*\([^()]*(?:\)|$)", "", label[:tail.start()]).strip(" –-:"), [_resolve_unit(tail.group(1))]
    for inner in reversed(re.findall(r"\(([^()]*)(?:\)|$)", label)):
        inner = re.sub(r"@.*", "", inner).strip()
        whole = _resolve_unit(inner)
        found = [whole] if whole else [_resolve_unit(t) for t in re.split(r"[/,]", inner)]
        if any(found):
            units = found
            break
    return re.sub(r"\s*\([^()]*(?:\)|$)", "", label).strip(" –-:"), units


def _cell_numbers(text: str) -> tuple[list[float], bool]:
    t = text.split("@")[0]
    rng = re.fullmatch(rf"\s*({_NUM})\s*[–—-]\s*({_NUM})\s*", t)
    if rng:
        return [float(g.replace(",", "")) for g in rng.groups()], True
    if "/" in t and re.fullmatch(rf"\s*{_NUM}(?:\s*/\s*{_NUM})+\s*", t):
        return [float(n.replace(",", "")) for n in re.findall(_NUM, t)], False
    m = re.match(rf"\s*({_NUM})", t)
    return ([float(m.group(1).replace(",", ""))], False) if m else ([], False)


DRIVE_SPLIT_RE = re.compile(r"([^–/]*?\d[^–/]*?)\s*[–-]\s*(FWD|AWD|RWD|4WD)\b\s*/?\s*")
PAREN_VARIANT_RE = re.compile(r"^(.*?)\s*\(\s*([A-Za-z0-9]{2,12})\s*:\s*([^)]+)\)\s*$")


def _split_value(value: str) -> list[tuple[str, str | None]]:
    """One cell can hold several variants: '188 @ 6,000 RPM – FWD 182 @ 6,000 RPM – AWD', '27 (4MATIC: 26)'."""
    drives = DRIVE_SPLIT_RE.findall(value)
    if len(drives) >= 2:
        return [(text.strip(), name) for text, name in drives]
    m = PAREN_VARIANT_RE.match(value)
    if m and re.search(r"\d", m.group(1)) and re.search(r"\d", m.group(3)):
        return [(m.group(1), None), (m.group(3), m.group(2))]
    return [(value, None)]


def _pretty(q: str) -> str:
    q = re.sub(r"\s*\([^()]*\)?", "", q).strip(" –-:")
    return " ".join(w.capitalize() if (w.isupper() and len(w) > 4) or (w.islower() and len(w) > 2) else w for w in q.split())


def _vtokens(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?|[a-z]+", text.lower())) - {"litre", "liter", "l", "the"}


def _is_table_layout(pages: list[list[dict]]) -> bool:
    hits = 0
    for rows in pages:
        for r in rows:
            if len(r["cells"]) >= 2 and any(_label_units(r["cells"][0])[1]) and re.match(rf"\s*{_NUM}", r["cells"][-1]) \
                    and not find_quantities(r["cells"][-1]):
                hits += 1
    column_headers = sum(1 for rows in pages for r in rows
                         if r["bold"] and len(r["cells"]) >= 3 and all(re.search(r"[A-Za-z]{2}", c) for c in r["cells"]))
    return hits >= 5 or column_headers >= 3


def _parse_table(path: Path, pages: list[list[dict]], body: float, meta: dict) -> tuple[SpecDoc, list[Chunk], list[Fact]]:
    doc_id = path.stem
    uk = (meta.get("market") or "").upper() == "UK"
    value_sizes = Counter(round(r["size"], 1) for page in pages for r in page
                          if len(r["cells"]) > 1 and re.fullmatch(rf"\s*{_NUM}\s*", r["cells"][-1]))
    if value_sizes:
        body = value_sizes.most_common(1)[0][0]
    rows = [{**r, "page": n} for n, page in enumerate(pages, start=1) for r in page
            if r["size"] >= body * 0.86 and not re.search(r"PROTECTED|^page \d+", " ".join(r["cells"]), re.IGNORECASE)]
    label_x = Counter(round(r["x"][0][0]) for r in rows if len(r["cells"]) > 1).most_common(1)[0][0]

    def at_label(r: dict) -> bool:
        return abs(r["x"][0][0] - label_x) <= 6

    def is_header(r: dict) -> bool:
        first = r["cells"][0]
        if "header" in r:
            return bool(r["header"])
        if not (r["bold"] and at_label(r)) or re.match(r"^[(a-z]", first):
            return False
        if len(r["cells"]) == 1:
            return not (first.endswith(")") and "(" not in first)
        return all(re.search(r"[A-Za-z]{2}", c) for c in r["cells"][1:])

    merged: list[dict] = []  # glue wrapped label fragments ("(sec)", "braked (kg)") back onto their label
    for r in rows:
        first = r["cells"][0]
        # a wrapped label continues on the next line: "(sec)", or a lone lower-case line such as "braked (kg)"
        if merged and at_label(r) and "header" not in r and (first.startswith("(") or (len(r["cells"]) == 1 and re.match(r"^[a-z]", first))):
            prev = next((m for m in reversed(merged) if m["has_label"]), None)
            if prev:
                prev["cells"] = [prev["cells"][0] + " " + first, *prev["cells"][1:]]
            if len(r["cells"]) == 1:
                continue
            r = {**r, "cells": r["cells"][1:], "x": r["x"][1:], "has_label": False}
        else:
            r = {**r, "has_label": at_label(r)}
        merged.append(r)

    make_prefix = re.compile(rf"^{re.escape(meta['make'])}\s+", re.IGNORECASE)

    def col_name(text: str) -> str:
        return _pretty(make_prefix.sub("", text))

    def is_column_row(r: dict) -> bool:
        """A row of column names with no label cell, set larger than the body (BMW: '330e xDrive | 330i xDrive')."""
        return ("header" not in r and not at_label(r) and len(r["cells"]) >= 2 and body * 1.2 <= r["size"] <= body * 1.6
                and all(re.search(r"[A-Za-z]{2}", c) for c in r["cells"]))

    headers = [r for r in merged if is_header(r) and len(r["cells"]) > 1]
    column_rows = [r for r in merged if is_column_row(r)]
    starts = [x0 for r in headers for x0, _ in r["x"][1:]] + [x0 for r in column_rows for x0, _ in r["x"]]
    value_x = min(starts) - 30 if starts else None
    column_names = {col_name(c) for r in headers for c in r["cells"][1:]} | {col_name(c) for r in column_rows for c in r["cells"]}

    chunks: list[Chunk] = []
    facts: list[Fact] = []
    variants: list[str] = []
    section: dict | None = None

    def flush() -> None:
        nonlocal section
        if section and section["lines"]:
            cid = f"{doc_id}#{len(chunks)}"
            header = " ".join(str(x) for x in (meta.get("year"), meta["make"], meta["model"]) if x)
            std = re.search(onto.TEST_STANDARDS, section["heading"])
            chunks.append(Chunk(cid, doc_id, None, section["heading"], section["page"],
                                f"{header} - {section['heading']}\n" + "\n".join(section["lines"]), std.group(1) if std else None))
            for f in section["facts"]:
                facts.append(Fact(id=f"{cid}/{len(facts)}", doc_id=doc_id, chunk_id=cid, trim=None, heading=section["heading"],
                                  standard=(std.group(1) if std else None) if f["attribute"] in ("fuel_economy", "range") else None, **f))
        section = None

    columns: list[tuple[str, float]] = []
    page_columns: list[tuple[str, float]] = []
    block_variant: str | None = None
    label: str | None = None
    after_header = False
    group: str | None = None
    defaults = meta.get("default_units") or {}
    for r in merged:
        if is_column_row(r):
            page_columns = [(col_name(c), (x0 + x1) / 2) for c, (x0, x1) in zip(r["cells"], r["x"])]
            columns = page_columns
            continue
        if is_header(r):
            flush()
            heading = r["cells"][0]
            columns = [(col_name(c), (x0 + x1) / 2) for c, (x0, x1) in zip(r["cells"][1:], r["x"][1:])] or page_columns
            block_variant = next((c for c in sorted(column_names, key=len, reverse=True) if _vtokens(c) == _vtokens(heading)), None)
            section = {"heading": heading, "page": r["page"], "lines": [], "facts": []}
            label = None
            group = None
            after_header = True
            continue
        if section is None:
            section = {"heading": "Overview", "page": r["page"], "lines": [], "facts": []}
        if after_header and columns and not r["has_label"] and len(r["cells"]) >= len(columns) \
                and all(re.fullmatch(r"[A-Za-z][A-Za-z /-]*", c) for c in r["cells"]):
            columns = [(f"{min(columns, key=lambda c: abs(c[1] - (x0 + x1) / 2))[0]} {_pretty(c)}", (x0 + x1) / 2)
                       for c, (x0, x1) in zip(r["cells"], r["x"])]
            section["lines"].append(" | ".join(r["cells"]))
            continue
        after_header = False
        cells = list(zip(r["cells"], r["x"]))
        if r["has_label"]:
            label, rest = cells[0][0], cells[1:]
        else:
            rest = cells
        section["lines"].append(" | ".join(([label] if label and not r["has_label"] else []) + r["cells"]))
        if r["has_label"] and not rest:
            group = label
        if not rest or label is None:
            continue
        if value_x is not None:
            vals = [c for c in rest if c[1][0] >= value_x]
            subs = [c[0] for c in rest if c[1][0] < value_x]
        else:
            vals, subs = rest[-1:], [c[0] for c in rest[:-1]]
        if not vals:
            continue
        clean, units = _label_units(label)
        for sub_label in subs:  # the unit sometimes sits on the sub-label: "Track | Front (mm) | 1,590"
            if not any(units):
                units = _label_units(sub_label)[1]
        heading = section["heading"]
        attr = onto.label_attribute(clean) or (None if block_variant else onto.label_attribute(f"{heading} {clean}"))
        group_drive = None
        if attr is None and group and group != label and clean.lower() in ("total", "combined", "city", "highway", "overall"):
            attr = onto.label_attribute(f"{_label_units(group)[0]} {clean}")
            if attr:
                if not any(units):
                    units = [u for u in _label_units(group)[1] if u]
                drive = re.search(r"\b(FWD|AWD|RWD|4WD)\b", group)
                group_drive = drive.group(1) if drive else None
        if attr and attr.key == "curb_weight" and re.search(r"front|rear|axle|distribution|\((?:fr|re)", f"{label}", re.IGNORECASE):
            attr = None  # axle loads, not the kerb weight
        if attr and attr.key == "power" and re.search(r"battery", heading, re.IGNORECASE):
            attr = None
        if attr and attr.key in ("length", "width", "height") and re.search(r"interior|luggage|load|cargo|boot", heading, re.IGNORECASE):
            attr = None
        if attr and attr.kind == "numeric" and not any(units):
            implied = _label_units(heading)[1]  # Mercedes: "Exterior Dimensions (in)" over "Wheelbase | 111.8"
            if any(implied) and all(u is None or UNIT_BY_NAME[u].dimension == attr.dimension for u in implied):
                units = implied
            elif attr.key == "power" and re.search(r"horsepower", label, re.IGNORECASE):
                units = ["hp"]
            elif defaults.get(attr.key) and not find_quantities(vals[0][0].split("@")[0]):
                units = [defaults[attr.key]]
        if len(vals) == len(columns):
            pairs = [(v[0], col) for v, (col, _) in zip(vals, columns)]
        elif len(vals) == 1:
            pairs = [(vals[0][0], None)]
        else:
            pairs = []
            for text, (x0, x1) in vals:
                near = sorted(columns, key=lambda c: abs(c[1] - (x0 + x1) / 2))
                if not near:
                    pairs.append((text, None))
                    continue
                pairs.append((text, near[0][0]))
                if len(near) > 1 and abs(abs(near[0][1] - (x0 + x1) / 2) - abs(near[1][1] - (x0 + x1) / 2)) < 12:
                    pairs.append((text, near[1][0]))  # a merged cell sitting midway between two columns
        sub_names = [_pretty(x) for x in subs if _pretty(x)]
        drive_sub = next((x for x in subs if re.fullmatch(r"(?:(?:FWD|AWD|RWD|4WD)\s*){2,}", x.strip())), None)
        if drive_sub:
            sub_names = [n for n in sub_names if n != _pretty(drive_sub)]
        expanded: list[tuple[str, str | None, str | None]] = []
        for whole, col in pairs:
            tokens = whole.split()
            if drive_sub and len(tokens) == len(drive_sub.split()):
                expanded += [(t, col, d) for t, d in zip(tokens, drive_sub.split()) if t != "-"]
            else:
                expanded += [(part, col, extra or group_drive) for part, extra in _split_value(whole)]
        for value, col, extra in expanded:
            quals = tuple(dict.fromkeys(q for q in (block_variant, col, *sub_names, extra) if q))
            shown = (f"{label}{' · ' + ' · '.join(sub_names) if sub_names else ''}: {value}"
                     + (f"  [{' · '.join(q for q in (col, extra) if q)}]" if col or extra else ""))
            base = {"page": r["page"], "line": shown, "label": clean, "qualifiers": quals}
            new: list[dict] = []
            avail = onto.availability(value) or {"S": "standard", "O": "optional"}.get(value.strip())
            names = [n.strip() for n in clean.split("/")]
            figures = [float(n.replace(",", "")) for n in re.findall(_NUM, value)]
            if avail:
                generic = clean.lower() in ("engine", "motor", "type", "front", "rear", "total", "system", "transmission",
                                            "manual", "automatic", "seats", "wheels", "tyres", "tires", "brakes", "other")
                if attr is None and clean not in column_names and len(clean) > 3 and not generic:
                    new.append({"attribute": onto.FEATURE, "kind": "feature", "value_text": avail})
            elif attr and attr.key == "fuel_economy" and len(names) > 1 and len(names) == len(figures) and units and units[0]:
                for name, figure in zip(names, figures):  # "City / Highway / Combined (mpg) | 23 / 34 / 27"
                    q = _quantity(figure, "mpg (UK)" if uk and units[0] == "mpg" else units[0])
                    if q.dimension == attr.dimension:
                        new.append({"attribute": attr.key, "kind": "numeric", "quantities": [q], "variant": onto.fuel_variant(name)})
            elif attr and attr.kind == "numeric":
                nums, is_range = _cell_numbers(value)
                if is_range and units and units[0]:
                    pairs_nu = [(n, units[0]) for n in nums]
                elif len(nums) == len(units):
                    pairs_nu = [(n, u) for n, u in zip(nums, units) if u]
                else:
                    pairs_nu = [(nums[0], units[0])] if nums and units and units[0] else []
                qs = []
                for n, u in pairs_nu:
                    u = "mpg (UK)" if uk and u == "mpg" else u
                    q = _quantity(n, u)
                    if q.dimension == attr.dimension:
                        qs.append(q)
                if not any(units):
                    qs = [q for q in find_quantities(value.split("@")[0]) if q.dimension == attr.dimension]
                    is_range = False
                fuel = (onto.fuel_variant(clean) or onto.fuel_variant(heading)) if attr.key == "fuel_economy" else None
                if not is_range and len(nums) > 1 and len([u for u in units if u]) == 1 and units[0]:
                    # "Top speed, km/h | 210/250": alternative figures in one unit, each a valid official value
                    for n in nums:
                        q = _quantity(n, units[0])
                        if q.dimension == attr.dimension:
                            new.append({"attribute": attr.key, "kind": "numeric", "quantities": [q], "variant": fuel})
                elif qs:
                    new.append({"attribute": attr.key, "kind": "numeric", "quantities": qs, "is_range": is_range and len(qs) == 2,
                                "variant": fuel})
            elif attr and attr.kind == "count":
                m = re.match(r"\s*(\d+)\b(?!\s*valve)", value, re.IGNORECASE)
                if m:
                    new.append({"attribute": attr.key, "kind": "count", "count": int(m.group(1))})
            elif attr:
                # the category may sit in a sub-label cell: "Front engine / FWD Front engine / AWD | S | S O"
                cats = onto.categorical_values(attr, value)
                if not cats:
                    cats = [c for x in subs for c in onto.categorical_values(attr, x)]
                    quals = tuple(q for q in quals if q not in sub_names)  # the sub-label was the value, not a variant
                    base["qualifiers"] = quals
                for cat in cats:
                    new.append({"attribute": attr.key, "kind": "categorical", "value_text": cat})
                gears = re.search(r"(\d+)[- ]speed", value, re.IGNORECASE) if attr.key == "transmission" else None
                if gears:
                    new.append({"attribute": "gears", "kind": "count", "count": int(gears.group(1))})
            if re.fullmatch(r"type", clean, re.IGNORECASE) and (block_variant or re.search(r"engine", heading, re.IGNORECASE)):
                m = re.search(r"(\d+|three|four|five|six|eight)[- ]cylinders?", value, re.IGNORECASE)
                if m:
                    words = {"three": 3, "four": 4, "five": 5, "six": 6, "eight": 8}
                    new.append({"attribute": "cylinders", "kind": "count",
                                "count": words.get(m.group(1).lower()) or int(m.group(1))})
            for f in new:
                section["facts"].append({**base, **f})
                variants.extend(q for q in quals if q not in variants)
    flush()
    title = meta.get("title") or f"{meta.get('year') or ''} {meta['make']} {meta['model']} specifications".strip()
    doc = SpecDoc(id=doc_id, file=path.name, title=title, make=meta["make"], model=meta["model"], year=meta.get("year"),
                  market=meta.get("market"), trims=[], pages=len(pages), variants=variants, source_url=meta.get("source_url"),
                  aliases=meta.get("aliases") or [])
    return doc, chunks, facts


def parse_html(path: Path) -> tuple[SpecDoc, list[Chunk], list[Fact]]:
    """Specification sheets published as a web page of tables (Nissan USA, Mercedes-Benz USA).

    Each table row becomes the same row structure the PDF reader produces, with synthetic column
    positions, so the column-table parser handles both.
    """
    meta_path = path.with_suffix(".meta.json")
    if not meta_path.exists():
        raise ValueError("an HTML specification page needs a .meta.json sidecar (make, model, year, market)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", path.read_text(encoding="utf-8", errors="replace"))

    def clean(cell: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()

    rows: list[dict] = []
    for table in re.findall(r"(?is)<table[^>]*>(.*?)</table>", raw):
        width = 0  # number of cells in this table's header row
        for i, tr in enumerate(re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", table)):
            every = [clean(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
            cells = [(n, c) for n, c in enumerate(every) if c]
            if not cells:
                continue
            texts = [c for _, c in cells]
            is_head = i == 0 and cells[0][0] == 0 and (len(texts) == 1 or all(len(t) <= 16 for t in texts[1:]))
            if is_head:
                width = len(every)
            extra = len(every) - width if width > 1 and len(every) > width else 0
            spans = []
            for n, _ in cells:
                if extra and 1 <= n <= extra:       # sub-label cell: sits between the label and the first value column
                    spans.append((60 + n * 20, 100 + n * 20))
                else:
                    col = n - extra if n > extra else n
                    spans.append((40 + col * 120, 120 + col * 120))
            rows.append({"cells": texts, "x": spans, "size": 10.0, "bold": is_head, "header": is_head, "y": len(rows) * 12.0})
    if not rows:
        raise ValueError("no tables found in the page")
    return _parse_table(path, [rows], 10.0, meta)


def parse_pdf(path: Path) -> tuple[SpecDoc, list[Chunk], list[Fact]]:
    pdf = fitz.open(path)
    pages = [_rows(p) for p in pdf]
    sizes = Counter()
    for rows in pages:
        for r in rows:
            sizes[round(r["size"], 1)] += sum(len(c) for c in r["cells"])
    body = sizes.most_common(1)[0][0] if sizes else 10.0

    meta_path = path.with_suffix(".meta.json")
    first_text = " ".join(" ".join(r["cells"]) for r in pages[0]) if pages else ""
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else _infer_meta(path, first_text)
    if _is_table_layout(pages):
        pdf.close()
        return _parse_table(path, pages, body, meta)
    doc_id = path.stem
    title = meta.get("title") or f"{meta.get('year') or ''} {meta['make']} {meta['model']} specifications".strip()

    chunks: list[Chunk] = []
    facts: list[Fact] = []
    trims: list[str] = []
    trim: str | None = None
    section: dict | None = None  # {"heading", "page", "lines": [(page, label, value, text)]}

    def flush() -> None:
        nonlocal section
        if not section or not section["lines"]:
            section = None
            return
        cid = f"{doc_id}#{len(chunks)}"
        body_text = "\n".join(t for _, _, _, t in section["lines"])
        std = re.search(onto.TEST_STANDARDS, section["heading"] + "\n" + body_text)
        header = " ".join(str(x) for x in (meta.get("year"), meta["make"], meta["model"], section["trim"]) if x)
        chunk = Chunk(cid, doc_id, section["trim"], section["heading"], section["page"],
                      f"{header} - {section['heading']}\n{body_text}", std.group(1) if std else None)
        chunks.append(chunk)
        for page_no, label, value, text in section["lines"]:
            if label is None:
                continue
            for f in _facts_for_line(label, value):
                line_std = re.search(onto.TEST_STANDARDS, text)
                facts.append(Fact(
                    id=f"{cid}/{len(facts)}", doc_id=doc_id, chunk_id=cid, trim=section["trim"], page=page_no,
                    heading=section["heading"], line=text, label=f.get("label", label), attribute=f["attribute"],
                    kind=f["kind"], quantities=f.get("quantities", []), count=f.get("count"),
                    value_text=f.get("value_text"), variant=f.get("variant"),
                    standard=(line_std.group(1) if line_std else chunk.standard) if f["attribute"] in ("fuel_economy", "range") else None,
                ))
        section = None

    for page_no, rows in enumerate(pages, start=1):
        for r in rows:
            text = " ".join(r["cells"]).strip()
            if r["size"] < body * 0.86 or re.match(r"^page \d+", text, re.IGNORECASE):
                continue  # footers, fine print
            is_heading = len(r["cells"]) == 1 and len(text) < 80 and (
                r["size"] >= body * 1.12 or (r["bold"] and not find_quantities(text) and ":" not in text))
            m = TRIM_HEADING_RE.match(text)
            if m and (is_heading or r["bold"]):
                flush()
                trim = m.group(1).strip()
                if trim not in trims:
                    trims.append(trim)
                continue
            if is_heading:
                flush()
                section = {"heading": text, "page": page_no, "trim": trim, "lines": []}
                continue
            if section is None:
                section = {"heading": "Overview", "page": page_no, "trim": trim, "lines": []}
            pair = _split(r["cells"])
            if pair:
                section["lines"].append((page_no, pair[0], pair[1], f"{pair[0]}: {pair[1]}"))
            else:
                section["lines"].append((page_no, None, None, text))
    flush()

    doc = SpecDoc(id=doc_id, file=path.name, title=title, make=meta["make"], model=meta["model"],
                  year=meta.get("year"), market=meta.get("market"), trims=trims, pages=len(pages))
    pdf.close()
    return doc, chunks, facts


# --------------------------------------------------------------------------- library


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


class SpecLibrary:
    def __init__(self, folder: Path):
        self.folder = folder
        self.docs: dict[str, SpecDoc] = {}
        self.chunks: list[Chunk] = []
        self.facts: list[Fact] = []
        self.errors: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self.docs, self.chunks, self.facts, self.errors = {}, [], [], {}
        for path in sorted([*self.folder.glob("*.pdf"), *self.folder.glob("*.html")]):
            try:
                doc, chunks, facts = parse_html(path) if path.suffix == ".html" else parse_pdf(path)
            except Exception as exc:  # a bad PDF must not take the library down
                self.errors[path.name] = str(exc)
                continue
            self.docs[doc.id] = doc
            self.chunks.extend(chunks)
            self.facts.extend(facts)
        self.facts_by_chunk: dict[str, list[Fact]] = {}
        for f in self.facts:
            self.facts_by_chunk.setdefault(f.chunk_id, []).append(f)

    # -- lookups used by claim extraction

    def models(self) -> list[tuple[str, str]]:
        return sorted({(d.make, d.model) for d in self.docs.values()})

    def trims_for(self, make: str | None, model: str | None) -> list[str]:
        out: list[str] = []
        for d in self.docs.values():
            if _norm(d.make) == _norm(make) and _norm(d.model) == _norm(model):
                names = [n for n in d.variants if not re.search(r"wheel|front|rear|&|tyre|body|^\d+in", n, re.IGNORECASE)]
                for n in list(names):  # "330i xDrive" is also just "330i" to a reviewer
                    head = n.split()[0]
                    if " " in n and re.search(r"\d", head) and re.search(r"[A-Za-z]", head) and len(head) >= 3:
                        names.append(head)
                out.extend(t for t in (*d.trims, *names) if t not in out)
        return sorted(out, key=len, reverse=True)

    def aliases(self, make: str, model: str) -> list[str]:
        return sorted({a for d in self.docs.values() if d.make == make and d.model == model for a in d.aliases})

    def markets(self) -> list[str]:
        return sorted({d.market for d in self.docs.values() if d.market})

    def feature_names(self, make: str | None, model: str | None) -> list[str]:
        ids = {d.id for d in self.docs.values() if _norm(d.make) == _norm(make) and _norm(d.model) == _norm(model)}
        return sorted({f.label for f in self.facts if f.kind == "feature" and f.doc_id in ids})

    # -- configuration matching

    def match_configs(self, v: Vehicle) -> tuple[list[Config], str | None]:
        """Resolve a claimed vehicle to (document, trim) pairs. Returns (configs, note).

        An empty list means nothing official covers the claim, and the note says why.
        """
        if not v.make or not v.model:
            return [], "The review does not identify a vehicle that can be matched to official documentation."
        docs = [d for d in self.docs.values() if _norm(d.make) == _norm(v.make) and _norm(d.model) == _norm(v.model)]
        if not docs:
            return [], f"No official documentation for the {v.make} {v.model} is in the specification library."
        notes: list[str] = []
        if v.year:
            by_year = [d for d in docs if d.year == v.year]
            if not by_year and any(d.year is None for d in docs):
                by_year = [d for d in docs if d.year is None]
                notes.append("The official document on file carries no model year, so the year in the review could not be matched.")
            if not by_year and config.MODEL_YEAR_TOLERANCE:
                near = [d for d in docs if d.year and abs(d.year - v.year) <= config.MODEL_YEAR_TOLERANCE]
                if near:
                    gap = min(abs(d.year - v.year) for d in near)
                    by_year = [d for d in near if abs(d.year - v.year) == gap]
                    notes.append(f"No {v.year} document on file; checked against the {by_year[0].year} sheet, "
                                 "which may differ between model years.")
            if not by_year:
                have = ", ".join(str(y) for y in sorted({d.year for d in docs if d.year}))
                return [], (f"The library has {v.make} {v.model} documentation for model year {have}, "
                            f"not {v.year}. Specifications change between model years, so the claim is not checked against them.")
            docs = by_year
        elif len({d.year for d in docs}) > 1:
            notes.append("Model year not stated; checked against every model year on file.")
        elif docs[0].year:
            notes.append(f"The review does not state a model year; checked against the {docs[0].year} sheet. "
                         "Figures can differ between model years.")
        if v.market:
            by_market = [d for d in docs if _norm(d.market) == _norm(v.market)]
            if not by_market:
                have = ", ".join(sorted({d.market or "unspecified" for d in docs}))
                return [], f"No {v.market}-market document for this vehicle (on file: {have})."
            docs = by_market
        elif len({d.market for d in docs}) > 1:
            notes.append("Market not stated; checked against " + ", ".join(sorted({d.market or "unspecified" for d in docs})) + " documents.")

        configs: list[Config] = []
        for d in docs:
            if not d.trims:  # column-table sheet: the variant filters rows during verification
                configs.append(Config(d, None, v.trim))
                continue
            if v.trim:
                hit = next((t for t in d.trims if _norm(t) == _norm(v.trim)), None)
                if hit:
                    configs.append(Config(d, hit))
            else:
                configs.extend(Config(d, t) for t in (d.trims or [None]))
        if v.trim and not configs:
            have = ", ".join(sorted({t for d in docs for t in d.trims}))
            return [], f'No "{v.trim}" trim in the official documents (trims on file: {have}).'
        if not v.trim and len(configs) > 1 and any(c.doc.trims for c in configs):
            notes.append("Trim not stated; checked against every trim.")
        return configs, " ".join(notes) or None
