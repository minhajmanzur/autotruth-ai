"""Claim decomposition: review text -> atomic factual claims + subjective statements.

Two extractors share one output schema:
  * ``extract_rules`` - deterministic, offline, no API key
  * ``extract_llm``   - any OpenAI-compatible chat model; every claim it returns
    must quote the review verbatim or it is dropped (the extractor may not invent claims)
"""
from __future__ import annotations

import json
import re
from collections import Counter

from . import config
from . import ontology as onto
from .models import Claim, Vehicle
from .specs import MARKETS, SpecLibrary
from .units import MASK_CHAR, UNIT_BY_NAME, Quantity, find_quantities, fmt, mask_test_conditions, to_base

NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_COUNT_NOUNS = r"(?:seat|speed|airbag|air bag|cylinder|year|passenger|gear)"
_WORD_NUM_RE = re.compile(rf"\b({'|'.join(NUMBER_WORDS)})(?=[\s-]+{_COUNT_NOUNS})", re.IGNORECASE)

QUALIFIERS = {
    "approx": r"about|around|roughly|approximately|approx\.?|nearly|almost|close to|circa|~|some",
    "min": r"over|more than|at least|north of|upwards of|above|exceeds?|in excess of",
    "max": r"under|less than|below|at most|shy of|no more than",
}

# Reviewer phrasing for categorical facts. Stricter than the spec-sheet patterns:
# "automatic climate control" must not become a transmission claim.
CLAIM_CATEGORIES: dict[str, dict[str, str]] = {
    "drivetrain": dict(onto.ATTR["drivetrain"].values),
    "transmission": {
        "CVT": r"\b(?:e-?)?cvt\b|continuously variable",
        "DCT": r"dual[- ]clutch|\bdct\b|\bdsg\b",
        "manual": r"\d+[- ]speed manual|\bmanual (?:gearbox|transmission)|stick shift",
        "single-speed": r"single[- ]speed",
        "automatic": r"\d+[- ]speed auto(?:matic)?\b|\bautomatic (?:gearbox|transmission)|torque[- ]converter",
    },
    "fuel_type": {
        "plug-in hybrid": r"plug[- ]in hybrid|\bphev\b",
        "electric": r"fully electric|all[- ]electric|battery[- ]electric|pure electric|\bbev\b",
        "diesel": r"\bdiesel (?:engine|powertrain|motor)|turbodiesel",
        "hybrid": r"\bis a (?:full |self-charging |conventional )?hybrid\b",
    },
    "aspiration": {
        "naturally aspirated": r"naturally[- ]aspirated|non-turbo|(?:\bno\b|\bnot\b|isn'?t|without|lacks?)\W+(?:\w+\W+){0,2}turbo",
        "supercharged": r"supercharged",
        "turbocharged": r"turbocharged|twin[- ]turbo|\bturbo\b",
    },
}

FEATURE_ALIASES = {
    "head-up display": ["hud", "heads-up display"],
    "adaptive cruise control": ["adaptive cruise", "radar cruise control", "radar cruise"],
    "panoramic sunroof": ["panoramic roof", "pano roof"],
    "panoramic glass roof": ["panoramic roof", "panoramic sunroof", "glass roof"],
    "blind spot monitor": ["blind-spot monitoring", "blind spot monitoring", "blind-spot warning"],
    "wireless phone charger": ["wireless charging", "wireless charger", "wireless charging pad"],
    "360-degree camera": ["surround-view camera", "360 camera", "surround view camera"],
    "apple carplay": ["carplay"],
    "vehicle-to-load": ["v2l"],
    "third-row seats": ["third row", "third-row seating"],
    "ventilated front seats": ["ventilated seats", "cooled seats", "seat ventilation"],
    "lane keeping assist": ["lane-keep assist", "lane keep assist", "lane-keeping assist"],
    "locking rear differential": ["rear diff lock", "locking rear diff", "rear locker"],
}
ABSENT_RE = (r"\bno\b|\bnot\b|\bwithout\b|\blacks?\b|\bmissing\b|n'?t (?:have|get|come|offer|available|offered|even)"
             r"|unavailable|\bomits?\b|\bskips?\b|nowhere|\bcan'?t (?:get|have)\b|\bisn'?t\b|\bnever\b")
OPTIONAL_RE = r"optional|\boption\b|extra[- ]cost|costs? extra|pay extra|options? (?:list|pack|box)|\bupgrade\b"
STANDARD_RE = r"\bstandard\b|as standard|comes with|included|out of the box|across the range|every"

SUBJECTIVE_RE = re.compile(
    r"\b(feels?|felt|comfortabl\w*|smooth\w*|love[ds]?|like[ds]?|hate[ds]?|great|good|bad|best|worst|better|worse|"
    r"disappoint\w*|impress\w*|i think|in my opinion|to my eyes?|cheap\w*|premium|fun|boring|refined|harsh|noisy|"
    r"quiet|handsome|ugly|pretty|gorgeous|nice|excellent|terrible|awful|amazing|brilliant|composed|plush|supple|"
    r"firm|floaty|engaging|dull|responsive|sluggish|punchy|effortless|cramped|spacious|roomy|airy|intuitive|"
    r"confusing|laggy|solid|flimsy|recommend|worth|overpriced|pleasant|annoying|sharp|vague|lovely|classy|bland|"
    r"feel|seems?|looks?|sounds?|drones?|wallow\w*|honestly|frankly|personally)\b",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[tuple[int, str]]:
    """Return (paragraph index, sentence) pairs."""
    out: list[tuple[int, str]] = []
    for i, para in enumerate(p.strip() for p in re.split(r"\n+", text)):
        out.extend((i, s.strip()) for s in re.split(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z0-9\"'(\[])", para) if s.strip())
    return out


def _clause_variant(text: str, start: int, end: int) -> str | None:
    """Fuel-economy test condition named in the same clause as the figure."""
    left = max(text.rfind(c, 0, start) for c in ",;:(") + 1
    rights = [i for i in (text.find(c, end) for c in ",;:)") if i != -1]
    return onto.fuel_variant(text[left: min(rights) if rights else len(text)])


def _model_re(make: str, model: str) -> re.Pattern:
    def flex(s: str) -> str:
        return r"[\s-]?".join(re.escape(t) for t in re.split(r"[\s-]+", s))
    return re.compile(rf"(?:\b((?:19|20)\d\d)\s+)?(?:\b{flex(make)}\s+)?\b{flex(model)}\b", re.IGNORECASE)


def _trim_pattern(name: str) -> re.Pattern:
    """Names with a figure ("2.0 Hybrid") match loosely: "2.0-litre hybrid", "2.0 hybrid"."""
    parts = [re.escape(p) for p in re.split(r"[\s-]+", name)]
    if re.search(r"\d", name) and len(parts) > 1:
        return re.compile(r"(?<![\w.])" + parts[0] + r"(?:[- ]?lit(?:re|er))?[\s-]+" + r"[\s-]+".join(parts[1:]) + r"(?![\w-])",
                          re.IGNORECASE)
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")


def _trim_spans(text: str, trims: list[str]) -> list[tuple[int, int, str]]:
    """Trim names are matched case-sensitively: 'SE' and 'Summit' are names, 'se' and 'summit' are not."""
    spans: list[tuple[int, int, str]] = []
    for t in trims:  # longest first, so "XLE Hybrid" claims its span before a shorter name could
        for m in _trim_pattern(t).finditer(text):
            if not any(s <= m.start() < e for s, e, _ in spans):
                spans.append((m.start(), m.end(), t))
    return sorted(spans)


def detect_vehicle(text: str, lib: SpecLibrary, override: Vehicle | None = None) -> Vehicle:
    """Work out which vehicle configuration a review is about."""
    v = Vehicle()
    hits: Counter = Counter()
    years: Counter = Counter()
    for make, model in lib.models():
        for m in _model_re(make, model).finditer(text):
            hits[(make, model)] += 1
            if m.group(1):
                years[((make, model), int(m.group(1)))] += 1
        for alias in lib.aliases(make, model):  # "330i", "C-Class": names that identify the model without spelling it out
            pat = r"[\s-]?".join(re.escape(t) for t in re.split(r"[\s-]+", alias))
            for m in re.finditer(rf"(?:\b((?:19|20)\d\d)\s+)?(?:\b{re.escape(make)}\s+)?(?<![\w-]){pat}(?![\w-])", text, re.IGNORECASE):
                hits[(make, model)] += 1
                if m.group(1):
                    years[((make, model), int(m.group(1)))] += 1
    if hits:
        (v.make, v.model), _ = hits.most_common(1)[0]
        ys = Counter({y: n for (mm, y), n in years.items() if mm == (v.make, v.model)})
        v.year = ys.most_common(1)[0][0] if ys else None
        # The review's subject trim: the one named right after the model ("Solara XLE Hybrid"),
        # or the only trim mentioned at all. Other trims are picked up sentence by sentence.
        spans = _trim_spans(text, lib.trims_for(v.make, v.model))
        ends = {m.end() for m in _model_re(v.make, v.model).finditer(text)}
        adjacent = Counter(t for s, _, t in spans if any(0 <= s - e <= 2 for e in ends))
        if adjacent:
            v.trim = adjacent.most_common(1)[0][0]
        elif len({t for _, _, t in spans}) == 1:
            v.trim = spans[0][2]
    else:
        m = re.search(r"\b((?:19|20)\d\d)\s+([A-Z][a-zA-Z]+)\s+([A-Z][\w-]+)", text)
        if m:
            v.year, v.make, v.model = int(m.group(1)), m.group(2), m.group(3)
    markets = Counter({name: len(re.findall(pat, text, re.IGNORECASE)) for name, pat in MARKETS.items()})
    name, n = markets.most_common(1)[0]
    if n:
        v.market = name
    if override:
        for k, val in override.model_dump().items():
            if val not in (None, ""):
                setattr(v, k, val)
    return v


def _qualifier(before: str) -> str:
    tail = before[-28:].lower()
    for name, pat in QUALIFIERS.items():
        if re.search(rf"(?:{pat})\W*(?:a |an |just )?$", tail):
            return name
    return "exact"


def quote_qualifier(quote: str, q: Quantity) -> str:
    """Qualifier ("about", "more than" ...) read from the words in front of the figure in the sentence itself."""
    work = _WORD_NUM_RE.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), quote)
    hit = next((x for x in find_quantities(work) if x.dimension == q.dimension and abs(x.base - q.base) <= 1e-9 * max(abs(q.base), 1)), None)
    return _qualifier(work[:hit.start]) if hit else "exact"


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, max(a[0], b[0]) - min(a[1], b[1]))


def _assign_attribute(q: Quantity, masked: str) -> onto.Attribute | None:
    """Decide which attribute a quantity is about, using the nearest topical keyword."""
    candidates = onto.ATTRS_BY_DIMENSION.get(q.dimension, [])
    best: tuple[int, onto.Attribute] | None = None
    low = masked.lower()
    for attr in candidates:
        if attr.key == "displacement" and not (q.unit == "cc" or to_base(q.value, q.unit) <= 9):
            continue
        if attr.key in ("cargo_volume", "fuel_tank") and to_base(q.value, q.unit) < 20:
            continue
        dist = None
        for pat in attr.keywords:
            for m in re.finditer(pat, low):
                d = _gap((q.start, q.end), m.span())
                dist = d if dist is None else min(dist, d)
        if attr.requires_keyword and (dist is None or dist > 70):
            continue
        score = dist if dist is not None else 200
        if best is None or score < best[0]:
            best = (score, attr)
    if best is None:
        return None
    attr = best[1]
    after = low[q.end: q.end + 30]
    if q.dimension == "length" and re.match(r"[\s-]*(?:\w+[\s-]){0,2}(?:wheels?|alloys?|rims?|screen|display|touchscreen|tyres?|tires?)\b", after):
        return None  # "17-inch wheels", "10.5-inch touchscreen": a size of something else, not a body dimension
    if attr.key == "length" and re.search(r"wheelbase", low[max(0, q.start - 30): q.end + 15]):
        attr = onto.ATTR["wheelbase"]  # "a wheelbase length of 2,640 mm"
    if attr.key == "power" and re.search(r"(?<![a-z])(?:re)?charg", low[max(0, q.start - 40): q.end + 40]):
        return None  # "150 kW fast charging" is not engine output
    if attr.key == "warranty_years" and re.search(r"batter", low[max(0, q.start - 60): q.end + 60]):
        return onto.ATTR["battery_warranty_years"]
    if attr.key == "range" and re.search(r"warranty|service", low[max(0, q.start - 30): q.end + 30]):
        return None
    return attr


def _statement(attr_label: str, c: dict) -> str:
    prefix = {"approx": "about ", "min": "more than ", "max": "less than "}.get(c.get("qualifier", "exact"), "")
    if c.get("value") is not None:
        unit = c.get("unit") or ""
        value = fmt(c["value"], unit) if unit in UNIT_BY_NAME and not UNIT_BY_NAME[unit].dimension.startswith("count") else f"{c['value']:g}"
        variant = f" ({c['variant']})" if c.get("variant") else ""
        return f"{attr_label}{variant}: {prefix}{value}"
    if c.get("asserted"):
        return f"{c['value_text']}: {c['asserted']}"
    return f"{attr_label}: {c.get('value_text')}"


def extract_rules(text: str, lib: SpecLibrary, override: Vehicle | None = None) -> tuple[Vehicle, list[Claim]]:
    base = detect_vehicle(text, lib, override)
    trims = lib.trims_for(base.make, base.model)
    features = lib.feature_names(base.make, base.model)
    claims: list[Claim] = []

    def names_model(make: str, model: str, sentence: str) -> bool:
        if _model_re(make, model).search(sentence):
            return True
        return any(re.search(r"(?<![\w-])" + r"[\s-]?".join(re.escape(t) for t in re.split(r"[\s-]+", a)) + r"(?![\w-])", sentence, re.IGNORECASE)
                   for a in lib.aliases(make, model))

    rivals = [m for m in lib.models() if m != (base.make, base.model)]

    def add(sentence: str, vehicle: Vehicle, **c) -> None:
        attr = onto.ATTR.get(c["attribute"])
        label = attr.label if attr else "Equipment"
        claims.append(Claim(id=f"c{len(claims) + 1}", text=_statement(label, c), quote=sentence,
                            attribute_label=label, vehicle=vehicle, extractor="rules", **c))

    topic_trim: str | None = None  # last trim named earlier in the current paragraph
    paragraph = -1
    for para, sentence in split_sentences(text):
        if para != paragraph:
            paragraph, topic_trim = para, None
        work = _WORD_NUM_RE.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), sentence)
        about_base = bool(base.make and base.model and names_model(base.make, base.model, work))
        # A comparison review: a sentence that names another car on file, and not the review's subject, is about that car.
        rival = None if about_base or override else next((m for m in rivals if names_model(*m, work)), None)
        spans = _trim_spans(work, lib.trims_for(*rival) if rival else trims)
        if not spans and about_base:
            topic_trim = None  # "…is standard on the Elantra" speaks about the whole range again
        masked = mask_test_conditions(work)
        for s, e, _ in spans:  # "Long Range" is a name, not a statement about range
            masked = masked[:s] + "#" * (e - s) + masked[e:]

        def vehicle_at(pos: int, spans=spans, topic=topic_trim, rival=rival) -> Vehicle:
            v = Vehicle(make=rival[0], model=rival[1]) if rival else base.model_copy()
            if override and override.trim:
                return v
            if rival:
                topic = None
            if spans:
                before = [t for s, _, t in spans if s <= pos]
                v.trim = before[-1] if before else spans[0][2]
            elif topic:
                v.trim = topic
            return v

        if spans and not rival:
            topic_trim = spans[-1][2]

        found = 0
        seen: dict[tuple, float] = {}
        for q in find_quantities(work):
            attr = _assign_attribute(q, masked)
            if not attr:
                continue
            vehicle = vehicle_at(q.start)
            variant = None
            if attr.key == "fuel_economy":
                variant = _clause_variant(work, q.start, q.end)
            key = (attr.key, vehicle.trim, variant)
            b = to_base(q.value, q.unit)
            if key in seen and abs(seen[key] - b) <= 0.03 * max(abs(b), 1e-9):
                continue  # "203 hp (151 kW)" is one claim written in two units
            seen[key] = b
            add(sentence, vehicle, attribute=attr.key, value=q.value, unit=q.unit,
                qualifier=_qualifier(work[:q.start]), variant=variant)
            found += 1

        m = re.search(r"\bV(6|8|10|12)\b", work)
        if m:
            add(sentence, vehicle_at(m.start()), attribute="cylinders", value=float(m.group(1)), unit="cylinders")
            found += 1

        m = re.search(r"\bseats (\d+|five|six|seven|eight)\b(?! speed)", sentence, re.IGNORECASE)
        if m:
            n = NUMBER_WORDS.get(m.group(1).lower()) or int(m.group(1))
            add(sentence, vehicle_at(m.start()), attribute="seating", value=float(n), unit="seats")
            found += 1

        low = work.lower()
        for key, patterns in CLAIM_CATEGORIES.items():
            for canonical, pat in patterns.items():
                m = re.search(pat, low)
                if m:
                    add(sentence, vehicle_at(m.start()), attribute=key, value_text=canonical)
                    found += 1
                    break

        hits = []
        for name in features:
            for alias in (name.lower(), *FEATURE_ALIASES.get(name.lower(), [])):
                pat = r"[\s-]+".join(re.escape(t) for t in re.split(r"[\s-]+", alias))
                m = re.search(rf"(?<!\w){pat}s?(?!\w)", low)
                if m:
                    hits.append((m, name))
                    break
        # "smart cruise control" is one feature, not also "cruise control"
        hits = [(m, n) for m, n in hits if not any(o.start() <= m.start() and m.end() <= o.end() and o.span() != m.span() for o, _ in hits)]
        for m, name in hits:
            window = low[max(0, m.start() - 45): m.end() + 40]
            asserted = ("absent" if re.search(ABSENT_RE, low[max(0, m.start() - 45): m.start()] + " " + low[m.end(): m.end() + 22])
                        else "optional" if re.search(OPTIONAL_RE, window)
                        else "standard" if re.search(STANDARD_RE, window) else "available")
            add(sentence, vehicle_at(m.start()), attribute=onto.FEATURE, value_text=name, asserted=asserted)
            found += 1

        if not found and SUBJECTIVE_RE.search(sentence) and MASK_CHAR not in sentence:
            claims.append(Claim(id=f"c{len(claims) + 1}", text=sentence, quote=sentence, kind="subjective",
                                vehicle=vehicle_at(0), extractor="rules"))
    return base, claims


# --------------------------------------------------------------------------- LLM extractor

LLM_SYSTEM = """You decompose automotive reviews into atomic claims. Return JSON only:
{"vehicle": {"make": str|null, "model": str|null, "year": int|null, "market": str|null, "trim": str|null},
 "claims": [{"quote": str, "kind": "factual"|"subjective", "attribute": str|null, "value": number|null,
             "unit": str|null, "value_text": str|null, "qualifier": "exact"|"approx"|"min"|"max",
             "variant": "city"|"highway"|"combined"|null, "asserted": "standard"|"available"|"optional"|"absent"|null,
             "trim": str|null}]}
Rules:
- One claim per checkable fact. A sentence with three figures yields three claims.
- "quote" is the sentence copied verbatim from the review. Never paraphrase it, never invent a claim.
- kind "factual" = measurable or checkable against a specification sheet. kind "subjective" = opinion or impression.
- attribute is one of: {attributes}; use "feature" for equipment (set value_text to the feature name and "asserted");
  use null for a factual claim that fits none of them (put the claim in value_text).
- Numeric claims: value and unit exactly as written (units: {units}). Do not convert.
- Categorical claims: value_text is one of the listed values for that attribute.
- "trim" is the trim level the claim is about, if the sentence or its context makes that clear.
Known vehicles in the specification library: {vehicles}"""


def llm_available() -> bool:
    return bool(config.LLM_API_KEY)


def extract_llm(text: str, lib: SpecLibrary, override: Vehicle | None = None) -> tuple[Vehicle, list[Claim]]:
    from openai import OpenAI

    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    attrs = "; ".join(f"{a.key}" + (f" ({'/'.join(a.values)})" if a.values else "") for a in onto.ATTRIBUTES)
    units = ", ".join(u.name for u in UNIT_BY_NAME.values() if not u.dimension.startswith("count"))
    vehicles = "; ".join(f"{d.year} {d.make} {d.model} [{d.market}] trims: {', '.join(d.trims)}" for d in lib.docs.values())
    system = LLM_SYSTEM.replace("{attributes}", attrs).replace("{units}", units).replace("{vehicles}", vehicles or "none")
    resp = client.chat.completions.create(
        model=config.LLM_MODEL, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")

    base = detect_vehicle(text, lib, None)
    for k, val in (data.get("vehicle") or {}).items():
        if k in Vehicle.model_fields and val not in (None, "") and getattr(base, k) is None:
            setattr(base, k, int(val) if k == "year" else str(val))
    if override:
        for k, val in override.model_dump().items():
            if val not in (None, ""):
                setattr(base, k, val)

    flat = re.sub(r"\s+", " ", text)
    claims: list[Claim] = []
    for raw in data.get("claims") or []:
        quote = re.sub(r"\s+", " ", str(raw.get("quote") or "")).strip()
        if not quote or quote not in flat:
            continue  # not grounded in the review: drop it
        vehicle = base.model_copy()
        if raw.get("trim") and not (override and override.trim):
            vehicle.trim = str(raw["trim"])
        if raw.get("kind") == "subjective":
            claims.append(Claim(id=f"c{len(claims) + 1}", text=quote, quote=quote, kind="subjective", vehicle=vehicle, extractor="llm"))
            continue
        key = raw.get("attribute")
        c: dict = {"attribute": key if key in onto.ATTR or key == onto.FEATURE else None,
                   "qualifier": raw.get("qualifier") if raw.get("qualifier") in QUALIFIERS else "exact",
                   "variant": raw.get("variant") if raw.get("variant") in onto.FUEL_VARIANTS else None,
                   "value_text": raw.get("value_text"), "asserted": raw.get("asserted")}
        if raw.get("value") is not None and raw.get("unit"):
            parsed = find_quantities(f"{raw['value']} {raw['unit']}")
            # the number must literally appear in the quoted sentence
            if not parsed or not re.search(rf"(?<![\d.]){re.escape(f'{parsed[0].value:g}')}(?![\d])", quote.replace(",", "")):
                continue
            # The model's own "qualifier" is not trusted (it read "limited to 2,500 kg" as "less than").
            c.update(value=parsed[0].value, unit=parsed[0].unit, qualifier=quote_qualifier(quote, parsed[0]))
        elif raw.get("value") is not None:
            c.update(value=float(raw["value"]))
        attr = onto.ATTR.get(c["attribute"] or "")
        label = attr.label if attr else ("Equipment" if c["attribute"] == onto.FEATURE else "Claim")
        statement = _statement(label, c) if c["attribute"] else str(c["value_text"] or quote)
        claims.append(Claim(id=f"c{len(claims) + 1}", text=statement, quote=quote, attribute_label=label,
                            vehicle=vehicle, extractor="llm", **c))
    return base, claims
