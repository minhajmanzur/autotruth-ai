"""The vocabulary of things a reviewer can claim and a spec sheet can state.

Each attribute has two sets of patterns:
  * ``labels``   - how a specification sheet names the row ("Maximum power")
  * ``keywords`` - how a reviewer talks about it ("produces", "tips the scales")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attribute:
    key: str
    label: str
    kind: str  # numeric | count | categorical
    dimension: str | None = None
    labels: tuple[str, ...] = ()
    label_exclude: str | None = None
    keywords: tuple[str, ...] = ()
    requires_keyword: bool = False
    values: dict[str, str] = field(default_factory=dict)  # categorical: canonical -> regex
    display_unit: str | None = None


def _A(*a, **k) -> Attribute:
    return Attribute(*a, **k)


ATTRIBUTES: tuple[Attribute, ...] = (
    _A("power", "Power output", "numeric", "power",
       labels=(r"\bpower\b", r"\boutput\b", r"horsepower"),
       label_exclude=r"charg|outlet|socket|audio|speaker|steering|tailgate|seat|window",
       keywords=(r"power|output|produc|\bmak(?:es|ing)\b|puts out|develops?",), display_unit="hp"),
    _A("dc_charging", "DC fast-charging power", "numeric", "power",
       labels=(r"dc (?:fast[- ]?)?charging", r"fast[- ]?charging", r"rapid charging"),
       keywords=(r"fast[- ]?charg|dc charg|rapid[- ]?charg|charging speed|charge at",), requires_keyword=True,
       display_unit="kW"),
    _A("torque", "Torque", "numeric", "torque", labels=(r"torque",), keywords=(r"torque|twist",), display_unit="Nm"),
    _A("fuel_economy", "Fuel economy", "numeric", "fuel_economy",
       labels=(r"fuel (?:consumption|economy|efficiency)", r"\bconsumption\b"),
       label_exclude=r"energy|electric",
       keywords=(r"fuel|economy|efficien|consumption|mileage",), display_unit="km/l"),
    _A("displacement", "Engine displacement", "numeric", "volume",
       labels=(r"displacement", r"engine capacity", r"cubic capacity", r"cylinder capacity"),
       keywords=(r"engine|displacement|cylinder|motor|turbo|v6|v8|four|inline",), requires_keyword=True,
       display_unit="cc"),
    _A("acceleration", "0-100 km/h", "numeric", "time",
       labels=(r"0\s*(?:-|–|—|to)\s*100", r"0\s*(?:-|–|—|to)\s*6[02]\s*mph", r"acceleration"),
       keywords=(r"§{3,}|accelerat|sprint|dash|\b6[02]\s*mph\b|\b100\s*(?:km\s*/\s*h|kph)",), requires_keyword=True, display_unit="s"),
    _A("top_speed", "Top speed", "numeric", "speed",
       labels=(r"top speed", r"max(?:imum|\.)? speed"),
       keywords=(r"top speed|tops out|maxes out|maximum speed|max speed|flat out|limited to|v-?max",),
       requires_keyword=True, display_unit="km/h"),
    _A("length", "Overall length", "numeric", "length", labels=(r"\blength\b",),
       label_exclude=r"interior|load|cargo|boot|luggage|seat|cabin",
       keywords=(r"\blong\b|length",), requires_keyword=True, display_unit="mm"),
    _A("width", "Overall width", "numeric", "length", labels=(r"\bwidth\b",), label_exclude=r"track|tyre|tire|interior|load|cargo|boot|luggage|seat|cabin|rim|wheel|mirror|shoulder|elbow",
       keywords=(r"\bwide\b|width",), requires_keyword=True, display_unit="mm"),
    _A("height", "Overall height", "numeric", "length", labels=(r"\bheight\b",), label_exclude=r"seat|load|interior|cargo|boot|luggage|cabin|tonneau",
       keywords=(r"\btall\b|height|\bhigh\b",), requires_keyword=True, display_unit="mm"),
    _A("wheelbase", "Wheelbase", "numeric", "length", labels=(r"wheelbase",),
       keywords=(r"wheelbase",), requires_keyword=True, display_unit="mm"),
    _A("ground_clearance", "Ground clearance", "numeric", "length", labels=(r"ground clearance",),
       keywords=(r"clearance|ride height|off the ground",), requires_keyword=True, display_unit="mm"),
    _A("curb_weight", "Kerb weight", "numeric", "mass", labels=(r"(?:kerb|curb) weight", r"unladen weight", r"^curb\b.*\btotal\b"),
       keywords=(r"weigh|kerb|curb|heavy|tips the scales|\bmass\b",), requires_keyword=True, display_unit="kg"),
    _A("towing_capacity", "Towing capacity", "numeric", "mass", labels=(r"\btow",),
       keywords=(r"\btow|\bpull\b|haul|trailer",), requires_keyword=True, display_unit="kg"),
    _A("cargo_volume", "Cargo volume", "numeric", "volume", labels=(r"cargo|\bboot\b|trunk|luggage|load capacity|loadspace capacity|load volume",),
       keywords=(r"\bboot\b|trunk|cargo|luggage|load ?space|load bay",), requires_keyword=True, display_unit="L"),
    _A("fuel_tank", "Fuel tank", "numeric", "volume", labels=(r"fuel tank", r"tank capacity"),
       keywords=(r"\btank\b",), requires_keyword=True, display_unit="L"),
    _A("battery_capacity", "Battery capacity", "numeric", "energy", labels=(r"battery",),
       keywords=(r"battery|\bpack\b|kwh",), display_unit="kWh"),
    _A("range", "Driving range", "numeric", "distance", labels=(r"\brange\b",),
       keywords=(r"\brange\b|(?:on|per) (?:a )?(?:single |full )?charge",), requires_keyword=True, display_unit="km"),
    _A("seating", "Seating capacity", "count", "count:seating", labels=(r"seating", r"\bseats\b", r"number of seats"),
       label_exclude=r"load|luggage|cargo|boot|seats? (?:up|down|folded|in place)|heated|ventilated|row"),
    _A("airbags", "Airbags", "count", "count:airbags", labels=(r"air ?bags?",)),
    _A("cylinders", "Cylinders", "count", "count:cylinders", labels=(r"\bcylinders\b",)),
    _A("gears", "Number of gears", "count", "count:gears", labels=(r"\bgears\b", r"number of (?:gears|speeds)")),
    _A("warranty_years", "Warranty (years)", "count", "count:warranty_years", labels=(r"warranty",),
       keywords=(r"warranty|guarantee",), requires_keyword=True),
    # Same unit as the vehicle warranty, chosen in claims._assign_attribute when the sentence says "battery".
    _A("battery_warranty_years", "Battery warranty (years)", "count", None, labels=(r"battery (?:pack )?warranty",)),
    _A("drivetrain", "Drivetrain", "categorical", labels=(r"drivetrain", r"drive type", r"driven wheels", r"drive layout", r"drive configuration"),
       values={
           "AWD": r"all[- ]wheel[- ]drive|\bawd\b",
           "4WD": r"four[- ]wheel[- ]drive|\b4wd\b|\b4x4\b",
           "FWD": r"front[- ]wheel[- ]drive|\bfwd\b|^\s*front(?: wheels)?\s*$",
           "RWD": r"rear[- ]wheel[- ]drive|\brwd\b|^\s*rear(?: wheels)?\s*$",
       }),
    _A("transmission", "Transmission", "categorical", labels=(r"transmission", r"gearbox"),
       values={
           "CVT": r"\b(?:e-?)?cvt\b|continuously variable|xtronic",
           "DCT": r"dual[- ]clutch|\bdct\b|\bdsg\b",
           "manual": r"\bmanual\b(?! mode)|stick shift",
           "single-speed": r"single[- ]speed|1-speed|direct drive",
           "automatic": r"\bautomatic\b|\bauto\b(?=\s*(?:gearbox|transmission|'box))|torque[- ]converter",
       }),
    _A("fuel_type", "Powertrain type", "categorical", labels=(r"fuel type", r"powertrain type", r"propulsion"),
       values={
           "plug-in hybrid": r"plug[- ]in hybrid|\bphev\b",
           "hybrid": r"\bhybrid\b",
           "electric": r"battery[- ]electric|fully electric|all[- ]electric|pure electric|\bbev\b|\belectric\b",
           "diesel": r"\bdiesel\b",
           "petrol": r"\bpetrol\b|\bgasoline\b",
       }),
    _A("aspiration", "Aspiration", "categorical", labels=(r"aspiration", r"induction"),
       values={
           "turbocharged": r"turbo(?:charged)?|\bturbo\b",
           "supercharged": r"supercharged",
           "naturally aspirated": r"naturally[- ]aspirated|non-turbo|\bn/?a engine\b",
       }),
)

ATTR = {a.key: a for a in ATTRIBUTES}
ATTRS_BY_DIMENSION: dict[str, list[Attribute]] = {}
for _a in ATTRIBUTES:
    if _a.dimension:
        ATTRS_BY_DIMENSION.setdefault(_a.dimension, []).append(_a)

# Categories that satisfy a broader claimed category ("automatic" is true of a CVT).
CATEGORY_IMPLIES = {
    ("transmission", "automatic"): {"automatic", "CVT", "DCT"},
    ("fuel_type", "hybrid"): {"hybrid", "plug-in hybrid"},
    ("drivetrain", "AWD"): {"AWD", "4WD"},
    ("drivetrain", "4WD"): {"4WD", "AWD"},
}

FUEL_VARIANTS = {  # order matters: "extra urban" is a highway figure
    "highway": r"highway|motorway|extra[- ]?urban|open road|freeway",
    "city": r"\bcity\b|urban|around town|in town",
    "combined": r"combined|overall|average|mixed",
}
TEST_STANDARDS = r"\b(WLTP|WLTC|NEDC|EPA|JC08|ADR ?81/02|GSO|UN ?ECE ?R101|CLTC)\b"

FEATURE = "feature"  # attribute key used for equipment / availability claims
AVAILABILITY = {
    "standard": r"^\s*(?:standard|std\.?|yes|included|●(?:\s*\(.*\))?)\s*$",
    "optional": r"^\s*(?:optional(?: \(.*\))?|option|opt\.?|extra[- ]cost option|○(?:\s*\d+)?)\s*$",
    "not available": r"^\s*(?:not available|n/?a|unavailable|no|—|–|-)\s*$",
}


def label_attribute(label: str) -> Attribute | None:
    """Map a spec-sheet row label to an attribute (longest matching pattern wins)."""
    best: tuple[int, Attribute] | None = None
    low = label.lower()
    for attr in ATTRIBUTES:
        if attr.label_exclude and re.search(attr.label_exclude, low):
            continue
        for pat in attr.labels:
            m = re.search(pat, low)
            if m and (best is None or len(m.group(0)) > best[0]):
                best = (len(m.group(0)), attr)
    return best[1] if best else None


def categorical_value(attr: Attribute, text: str) -> str | None:
    low = text.lower()
    for canonical, pat in attr.values.items():
        if re.search(pat, low):
            return canonical
    return None


def categorical_values(attr: Attribute, text: str) -> list[str]:
    """Every category named in the text: 'Rear-Wheel Drive / 4MATIC All-Wheel Drive' -> ['AWD', 'RWD']."""
    low = text.lower()
    return [canonical for canonical, pat in attr.values.items() if re.search(pat, low)]


def availability(text: str) -> str | None:
    for canonical, pat in AVAILABILITY.items():
        if re.match(pat, text.strip(), re.IGNORECASE):
            return canonical
    return None


def fuel_variant(text: str) -> str | None:
    low = text.lower()
    for name, pat in FUEL_VARIANTS.items():
        if re.search(pat, low):
            return name
    return None
