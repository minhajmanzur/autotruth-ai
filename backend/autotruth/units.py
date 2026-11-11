"""Quantity parsing and unit conversion.

Every unit belongs to a dimension and converts to that dimension's base unit,
so "230 hp" and "172 kW" can be compared directly. Fuel economy is the one
non-linear case: L/100km is the inverse of km/l.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UnitDef:
    name: str
    dimension: str
    factor: float | None  # multiply by this to reach the base unit; None = inverse (L/100km)
    aliases: tuple[str, ...]


_M = r"met(?:re|er)s?"
_L = r"lit(?:re|er)s?"

UNITS: tuple[UnitDef, ...] = (
    UnitDef("hp", "power", 0.7457, (r"horsepower", r"horses", r"bhp", r"hp")),
    UnitDef("PS", "power", 0.7355, (r"ps", r"metric horsepower")),
    UnitDef("kW", "power", 1.0, (r"kilowatts?", r"kw")),
    UnitDef("Nm", "torque", 1.0, (rf"newton[- ]?{_M}", r"n[·.\-]?m")),
    UnitDef("lb-ft", "torque", 1.35582, (r"pound[- ]feet", r"lb[.\- ]?ft", r"ft[.\- ]?lbs?")),
    UnitDef("km/l", "fuel_economy", 1.0, (rf"km\s*/\s*{_L}", r"km\s*/\s*l", r"kmpl", rf"kilo{_M} per {_L}")),
    UnitDef("L/100km", "fuel_economy", None, (rf"(?:l|{_L})\s*/\s*100\s*km", rf"{_L} per 100\s*(?:km|kilo{_M})")),
    UnitDef("mpg (UK)", "fuel_economy", 0.354006, (r"mpg \(uk\)", r"uk mpg", r"imperial mpg")),
    UnitDef("mpg", "fuel_economy", 0.425144, (r"mpg", r"miles per gallon")),
    UnitDef("km/h", "speed", 1.0, (r"km\s*/\s*h", r"kph", r"kmh", rf"kilo{_M} per hour")),
    UnitDef("mph", "speed", 1.609344, (r"mph", r"miles per hour")),
    UnitDef("kWh", "energy", 1.0, (r"kwh", r"kilowatt[- ]hours?")),
    UnitDef("mm", "length", 1.0, (r"mm", rf"milli{_M}")),
    UnitDef("cm", "length", 10.0, (r"cm", rf"centi{_M}")),
    UnitDef("m", "length", 1000.0, (_M,)),
    UnitDef("in", "length", 25.4, (r"inch(?:es)?",)),
    UnitDef("kg", "mass", 1.0, (r"kg", r"kilograms?", r"kilos?")),
    UnitDef("lb", "mass", 0.45359237, (r"lbs?", r"pounds?")),
    UnitDef("t", "mass", 1000.0, (r"tonnes?",)),
    UnitDef("cc", "volume", 0.001, (r"cc", r"cm3", r"cm³", rf"cubic centi{_M}")),
    UnitDef("cu ft", "volume", 28.3168, (r"cu\.?\s*ft\.?", r"cubic feet")),
    UnitDef("gal", "volume", 3.78541, (r"gallons?",)),
    UnitDef("L", "volume", 1.0, (_L, r"l")),
    UnitDef("km", "distance", 1.0, (r"km", rf"kilo{_M}")),
    UnitDef("mi", "distance", 1.609344, (r"miles?", r"mi")),
    UnitDef("s", "time", 1.0, (r"seconds?", r"secs?", r"s")),
    # Counts: the unit word itself tells us which attribute is being counted.
    UnitDef("seats", "count:seating", 1.0, (r"seats?", r"seaters?", r"passengers?", r"occupants")),
    UnitDef("airbags", "count:airbags", 1.0, (r"airbags?", r"air bags?")),
    UnitDef("cylinders", "count:cylinders", 1.0, (r"cylinders?", r"cyl")),
    UnitDef("speed", "count:gears", 1.0, (r"speeds?", r"gears?")),
    UnitDef("years", "count:warranty_years", 1.0, (r"years?", r"yrs?")),
)

UNIT_BY_NAME = {u.name: u for u in UNITS}

# Longest alias first so "kWh" wins over "kW" and "km/l" over "km".
_ALIASES = sorted(((a, u) for u in UNITS for a in u.aliases), key=lambda p: -len(p[0]))
_UNIT_GROUPS = "|".join(f"(?P<u{i}>{a})" for i, (a, _) in enumerate(_ALIASES))
_NUMBER = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
QUANTITY_RE = re.compile(
    rf"(?<![\w.,/]){_NUMBER}\s*-?\s*(?:{_UNIT_GROUPS})(?![a-z0-9])",
    re.IGNORECASE,
)

# "0-100 km/h" is a test condition, not a speed figure. Mask it before parsing.
ZERO_TO_100_RE = re.compile(
    r"(?<![\d.,\w])(?:0|zero|nought|rest|standstill)\s*(?:-|–|—|to)\s*(?:100\s*(?:km\s*/\s*h|kph|kmh)?|6[02]\s*mph)(?![\d])",
    re.IGNORECASE,
)
MASK_CHAR = "§"


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str
    dimension: str
    start: int
    end: int
    raw: str
    decimals: int  # precision the author wrote, used for rounding-aware comparison

    @property
    def base(self) -> float:
        return to_base(self.value, self.unit)


def mask_test_conditions(text: str) -> str:
    """Replace '0-100 km/h' spans with same-length filler so offsets stay valid."""
    return ZERO_TO_100_RE.sub(lambda m: MASK_CHAR * len(m.group(0)), text)


def find_quantities(text: str) -> list[Quantity]:
    masked = mask_test_conditions(text)
    out: list[Quantity] = []
    for m in QUANTITY_RE.finditer(masked):
        num = m.group("num").replace(",", "")
        unit = next(u for i, (_, u) in enumerate(_ALIASES) if m.group(f"u{i}") is not None)
        decimals = len(num.split(".")[1]) if "." in num else 0
        out.append(Quantity(float(num), unit.name, unit.dimension, m.start(), m.end(), text[m.start():m.end()], decimals))
    return out


def to_base(value: float, unit: str) -> float:
    u = UNIT_BY_NAME[unit]
    if u.factor is None:
        return 100.0 / value if value else float("inf")
    return value * u.factor


def from_base(base: float, unit: str) -> float:
    u = UNIT_BY_NAME[unit]
    if u.factor is None:
        return 100.0 / base if base else float("inf")
    return base / u.factor


def convert(value: float, unit: str, target: str) -> float:
    if UNIT_BY_NAME[unit].dimension != UNIT_BY_NAME[target].dimension:
        raise ValueError(f"cannot convert {unit} to {target}")
    return from_base(to_base(value, unit), target)


def dimension_of(unit: str) -> str | None:
    u = UNIT_BY_NAME.get(unit)
    return u.dimension if u else None


def fmt(value: float, unit: str) -> str:
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"
    return f"{text} {unit}"
