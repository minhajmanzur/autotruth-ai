"""End-to-end pipeline: text -> claims -> evidence -> verdicts, plus cross-review disagreements."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from . import claims as claim_mod
from . import config
from . import ontology as onto
from .models import Analysis, Source, Vehicle, Verdict
from .nli import NLI
from .retrieval import Retriever
from .specs import SpecLibrary, _norm
from .units import UNIT_BY_NAME, to_base
from .verify import Verifier


class Engine:
    def __init__(self, retrieval_mode: str | None = None, nli: bool = True):
        config.SPECS_DIR.mkdir(parents=True, exist_ok=True)
        self.lib = SpecLibrary(config.SPECS_DIR)
        self.retriever = Retriever(self.lib, retrieval_mode)
        self.nli = NLI() if nli else None
        self.verifier = Verifier(self.lib, self.retriever, self.nli)

    def reload(self) -> None:
        self.lib.reload()
        self.retriever.index(config.RETRIEVAL_MODE)

    def extract(self, text: str, vehicle: Vehicle | None, use_llm: bool | None):
        want_llm = claim_mod.llm_available() if use_llm is None else use_llm
        if want_llm and claim_mod.llm_available():
            try:
                v, claims = claim_mod.extract_llm(text, self.lib, vehicle)
                return v, claims, f"llm ({config.LLM_MODEL})"
            except Exception as exc:
                v, claims = claim_mod.extract_rules(text, self.lib, vehicle)
                return v, claims, f"rules (LLM call failed: {type(exc).__name__})"
        v, claims = claim_mod.extract_rules(text, self.lib, vehicle)
        return v, claims, "rules"

    def analyze(self, text: str, source: Source, vehicle: Vehicle | None = None, use_llm: bool | None = None) -> Analysis:
        start = time.perf_counter()
        base, claims, extractor = self.extract(text, vehicle, use_llm)
        verdicts = [self.verifier.verify(c) for c in claims if c.kind == "factual"]
        subjective = [c for c in claims if c.kind == "subjective"]
        counts = {s: sum(v.status == s for v in verdicts) for s in ("supported", "contradicted", "partial", "unverifiable")}
        counts["subjective"] = len(subjective)
        verifiable = len(verdicts) - counts["unverifiable"]
        accuracy = round(counts["supported"] / verifiable, 3) if verifiable else None
        return Analysis(
            id=uuid.uuid4().hex[:12], created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source=source, vehicle=base, verdicts=verdicts, subjective=subjective, counts=counts, accuracy=accuracy,
            summary=_summary(base, verdicts, counts), extractor=extractor, retrieval=self.retriever.description,
            latency_ms=int((time.perf_counter() - start) * 1000), text_chars=len(text),
        )


def _summary(vehicle: Vehicle, verdicts: list[Verdict], counts: dict[str, int]) -> str:
    if not verdicts:
        return "No checkable factual claims were found in this text."
    parts = [f"{counts[k]} {label}" for k, label in (("supported", "supported"), ("contradicted", "contradicted"),
             ("partial", "partially supported"), ("unverifiable", "unverifiable")) if counts[k]]
    text = f"{len(verdicts)} factual claims about the {vehicle.label()}: {', '.join(parts)}."
    wrong = next((v for v in verdicts if v.status == "contradicted"), None)
    if wrong:
        text += f" Most notable error: {wrong.claim.text} - {wrong.reason.split(' Source line:')[0]}"
    return text


# --------------------------------------------------------------------------- disagreements


def _position(v: Verdict) -> tuple | None:
    c = v.claim
    if c.attribute is None:
        return None
    if c.attribute == onto.FEATURE:
        return ("cat", "absent" if c.asserted == "absent" else "present")
    if c.value is not None and c.unit in UNIT_BY_NAME:
        return ("num", to_base(c.value, c.unit))
    if c.value_text:
        return ("cat", c.value_text)
    return None


def _differs(a: tuple, b: tuple) -> bool:
    if a[0] != b[0]:
        return False
    if a[0] == "num":
        return abs(a[1] - b[1]) > 0.02 * max(abs(a[1]), abs(b[1]), 1e-9)
    return a[1] != b[1]


def _compatible(x: Vehicle, y: Vehicle) -> bool:
    return all(not a or not b or _norm(str(a)) == _norm(str(b)) for a, b in ((x.trim, y.trim), (x.market, y.market), (x.year, y.year)))


def disagreements(analyses: list[Analysis]) -> list[dict]:
    """Find factual points where two different reviews of the same vehicle contradict each other."""
    groups: dict[tuple, list[tuple[Analysis, Verdict, tuple]]] = {}
    for a in analyses:
        for v in a.verdicts:
            pos, c = _position(v), v.claim
            if pos is None or not c.vehicle.make:
                continue
            key = (_norm(c.vehicle.make), _norm(c.vehicle.model), c.attribute, c.variant or "",
                   _norm(c.value_text) if c.attribute == onto.FEATURE else "")
            groups.setdefault(key, []).append((a, v, pos))
    out = []
    for members in groups.values():
        involved: set[int] = set()
        for i, (a1, v1, p1) in enumerate(members):
            for j, (a2, v2, p2) in enumerate(members[i + 1:], start=i + 1):
                if a1.id != a2.id and _compatible(v1.claim.vehicle, v2.claim.vehicle) and _differs(p1, p2):
                    involved.update((i, j))
        if not involved:
            continue
        picked = [members[i] for i in sorted(involved)]
        first = picked[0][1].claim
        right = [a.source.title for a, v, _ in picked if v.status == "supported"]
        if right:
            resolution = "Official documentation supports: " + "; ".join(dict.fromkeys(right)) + "."
        elif all(v.status == "unverifiable" for _, v, _ in picked):
            resolution = "No official documentation on file settles this."
        else:
            resolution = "Official documentation fully supports neither side."
        out.append({
            "vehicle": " ".join(str(p) for p in (first.vehicle.year, first.vehicle.make, first.vehicle.model) if p),
            "attribute": first.value_text if first.attribute == onto.FEATURE else (first.attribute_label or first.attribute),
            "resolution": resolution,
            "official": next((v.official for _, v, _ in picked if v.official), None),
            "positions": [{"analysis_id": a.id, "source": a.source.title, "author": a.source.author, "claim": v.claim.text,
                           "trim": v.claim.vehicle.trim, "quote": v.claim.quote, "status": v.status} for a, v, _ in picked],
        })
    return out
