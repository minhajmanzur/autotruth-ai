"""Fast tests: BM25 retrieval, no model downloads."""
from __future__ import annotations

import pytest

from autotruth import config
from autotruth.claims import extract_rules
from autotruth.models import Source
from autotruth.pipeline import Engine, disagreements
from autotruth.units import convert, find_quantities


@pytest.fixture(scope="module")
def engine() -> Engine:
    if not list(config.SPECS_DIR.glob("*.pdf")):
        pytest.skip("run scripts/make_demo_specs.py first")
    config.MODEL_YEAR_TOLERANCE = 0
    return Engine(retrieval_mode="bm25", nli=False)


def verdicts(engine: Engine, text: str) -> dict[str, str]:
    a = engine.analyze(text, Source(title="t"), use_llm=False)
    return {v.claim.text: v.status for v in a.verdicts}


def test_units():
    q = find_quantities("makes 203 hp (151 kW) and 6.5 L/100 km, 0-100 km/h in 8.4 s, 2,825 mm")
    assert [(x.value, x.unit) for x in q] == [(203, "hp"), (151, "kW"), (6.5, "L/100km"), (8.4, "s"), (2825, "mm")]
    assert convert(6.5, "L/100km", "km/l") == pytest.approx(15.38, abs=0.01)
    assert convert(225, "hp", "kW") == pytest.approx(167.8, abs=0.1)


def test_library_parses_trims_and_pages(engine):
    doc = engine.lib.docs["meridian-solara-2025-gcc"]
    assert doc.trims == ["SE", "XLE Hybrid"] and doc.year == 2025 and doc.market == "GCC"
    fact = next(f for f in engine.lib.facts if f.doc_id == doc.id and f.trim == "XLE Hybrid" and "system power" in f.line)
    assert fact.page == 4 and fact.heading == "Engine & Performance" and fact.attribute == "power"


def test_supported_and_contradicted(engine):
    v = verdicts(engine, "The 2025 Meridian Solara XLE Hybrid makes 225 horsepower and returns 20 km/l combined.")
    assert v == {"Power output: 225 hp": "supported", "Fuel economy (combined): 20 km/l": "contradicted"}


def test_unit_conversion_in_verification(engine):
    v = verdicts(engine, "The 2025 Meridian Solara XLE Hybrid produces 168 kW and uses 4.2 l/100km combined.")
    assert set(v.values()) == {"supported"} and len(v) == 2


def test_trim_unspecified_is_partial(engine):
    v = verdicts(engine, "The 2025 Meridian Solara for the GCC market makes 225 hp.")
    assert v == {"Power output: 225 hp": "partial"}


def test_market_matching(engine):
    assert verdicts(engine, "In Europe the 2025 Meridian Solara Excel Hybrid has a 3-year warranty.") == {"Warranty (years): 3": "supported"}
    assert verdicts(engine, "The UAE-spec 2025 Meridian Solara XLE Hybrid has a 3-year warranty.") == {"Warranty (years): 3": "contradicted"}


def test_wrong_model_year_is_unverifiable(engine):
    assert verdicts(engine, "The 2023 Meridian Solara SE makes 203 hp.") == {"Power output: 203 hp": "unverifiable"}


def test_feature_availability(engine):
    v = verdicts(engine, "The 2025 Kestrel Ridgeback Adventure has a panoramic sunroof as standard. "
                         "There is no locking rear differential on the Adventure.")
    assert v == {"Panoramic sunroof: standard": "partial", "Locking rear differential: absent": "supported"}


def test_subjective_is_separated(engine):
    a = engine.analyze("The 2025 Kestrel Ridgeback Summit feels unstoppable. It has a 3.5-litre V6.", Source(title="t"), use_llm=False)
    assert [c.quote for c in a.subjective] == ["The 2025 Kestrel Ridgeback Summit feels unstoppable."]
    assert {v.claim.attribute for v in a.verdicts} == {"displacement", "cylinders"}


def test_turbocharged_does_not_hide_power(engine):
    _, cs = extract_rules("The 2025 Kestrel Ridgeback Adventure has a turbocharged four-cylinder with 245 horsepower.", engine.lib)
    assert ("power", 245.0) in {(c.attribute, c.value) for c in cs}


def test_disagreement_detection(engine):
    a = engine.analyze("The 2025 Meridian Solara XLE Hybrid makes 225 horsepower.", Source(title="A"), use_llm=False)
    b = engine.analyze("My 2025 Meridian Solara XLE Hybrid makes 230 horsepower.", Source(title="B"), use_llm=False)
    found = disagreements([a, b])
    assert len(found) == 1 and found[0]["attribute"] == "Power output"
    assert "A" in found[0]["resolution"] and "B" not in found[0]["resolution"].replace("Official", "")


def test_qualifier_comes_from_the_sentence_not_the_model():
    from autotruth.claims import quote_qualifier

    def q(text):
        return find_quantities(text)[0]

    assert quote_qualifier("Towing is limited to 2,500 kg on the Adventure.", q("2500 kg")) == "exact"
    assert quote_qualifier("It weighs about 1,650 kg.", q("1650 kg")) == "approx"
    assert quote_qualifier("It makes more than 200 hp.", q("200 hp")) == "min"
    assert quote_qualifier("It weighs under 1,700 kg.", q("1700 kg")) == "max"
