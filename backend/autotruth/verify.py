"""Independent verification layer.

No LLM decides a verdict here. A claim is resolved to official configurations,
evidence is retrieved for each, and the verdict comes from unit-aware numerical
comparison, category matching, feature availability, or NLI for free text.
"""
from __future__ import annotations

import re

from . import ontology as onto
from .models import Claim, ConfigResult, Evidence, Verdict
from .nli import NLI
from .retrieval import Retriever
from .specs import Config, Fact, SpecLibrary, _vtokens
from .units import UNIT_BY_NAME, convert, fmt

SAME_UNIT_TOL = 0.005   # reviewer and document use the same unit
CONVERTED_TOL = 0.015   # the document's second unit is itself rounded
APPROX_TOL = 0.05       # "about 230 hp"
NLI_THRESHOLD = 0.80

# How specification sheets tend to word each attribute, added to the retrieval query so a reviewer's
# "boot" finds the sheet's "Load capacity" row.
QUERY_TERMS = {
    "power": "max maximum power output system engine horsepower hp",
    "torque": "max maximum torque",
    "fuel_economy": "fuel consumption economy combined",
    "displacement": "engine displacement capacity",
    "acceleration": "performance acceleration 0-62mph 0-100",
    "top_speed": "performance max maximum speed",
    "length": "exterior dimensions overall length",
    "width": "exterior dimensions overall width",
    "height": "exterior dimensions overall height",
    "wheelbase": "exterior dimensions wheelbase",
    "ground_clearance": "exterior dimensions ground clearance",
    "curb_weight": "weights kerb curb weight",
    "towing_capacity": "weights towing capacity braked",
    "cargo_volume": "luggage compartment load capacity loadspace boot cargo volume",
    "fuel_tank": "fuel tank capacity",
    "battery_capacity": "battery capacity",
    "range": "range",
    "drivetrain": "transmission drivetrain driven wheels drive",
    "transmission": "transmission type gearbox",
    "cylinders": "engine type cylinders",
    "seating": "seating capacity seats",
}


def _decimals(value: float) -> int:
    text = f"{value:.6f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def _tokens(text: str) -> set[str]:
    stop = {"to", "the", "a", "of", "and", "with"}
    return {t.rstrip("s") for t in re.findall(r"[a-z0-9]+", text.lower())} - stop


def compare_numeric(claim: Claim, fact: Fact) -> tuple[bool, float, str]:
    """Return (matches, signed relative difference of claim vs official, official value in the claim's unit)."""
    c = claim.value
    rounding = 0.5 * 10 ** -_decimals(c)
    digits = max(_decimals(c), 1)

    if fact.is_range:  # e.g. kerb weight 1,345 - 1,410 kg depending on equipment
        lo, hi = sorted(convert(q.value, q.unit, claim.unit) for q in fact.quantities[:2])
        tol = SAME_UNIT_TOL if fact.quantities[0].unit == claim.unit else CONVERTED_TOL
        if claim.qualifier == "approx":
            ok = lo * (1 - APPROX_TOL) <= c <= hi * (1 + APPROX_TOL)
        elif claim.qualifier == "min":
            ok = hi >= c - rounding
        elif claim.qualifier == "max":
            ok = lo <= c + rounding
        else:
            ok = lo * (1 - tol) - rounding <= c <= hi * (1 + tol) + rounding
        rel = 0.0 if ok else ((c - lo) / lo if c < lo else (c - hi) / hi)
        return ok, rel, f"{fmt(round(lo, digits), claim.unit).rsplit(' ' + claim.unit, 1)[0]} – {fmt(round(hi, digits), claim.unit)}"

    # Reviewers write "hp" for both mechanical (bhp) and metric (PS / DIN hp) horsepower, so a claim
    # in either unit may match either figure on the sheet.
    twins = {"hp", "PS"} if claim.unit in ("hp", "PS") else {claim.unit}
    same = [q for q in fact.quantities if q.unit == claim.unit] + [q for q in fact.quantities if q.unit in twins - {claim.unit}]
    refs = [(q.value, SAME_UNIT_TOL) for q in same] or [(convert(fact.quantities[0].value, fact.quantities[0].unit, claim.unit), CONVERTED_TOL)]

    def check(official: float, tol: float) -> tuple[bool, float]:
        rel = (c - official) / official if official else float("inf")
        if claim.qualifier == "approx":
            return abs(rel) <= APPROX_TOL, rel
        if claim.qualifier == "min":
            return official >= c - rounding, rel
        if claim.qualifier == "max":
            return official <= c + rounding, rel
        return abs(c - official) <= rounding + 1e-9 or abs(rel) <= tol, rel

    results = [(check(official, tol), official) for official, tol in refs]
    (ok, rel), official = next((r for r in results if r[0][0]), results[0])
    if not ok and len(twins) > 1:  # "218 hp" may be metric horsepower on a sheet that only lists bhp and kW
        source = fact.quantities[0]
        for alt in sorted(twins):
            converted = convert(source.value, source.unit, alt)
            if claim.qualifier == "exact" and abs(c - converted) <= rounding + 1e-9:  # rounding only, no extra slack
                return True, (c - converted) / converted, fmt(round(converted, digits), alt)
    return ok, rel, fmt(round(official, digits), claim.unit)


class Verifier:
    def __init__(self, lib: SpecLibrary, retriever: Retriever, nli: NLI | None = None):
        self.lib, self.retriever, self.nli = lib, retriever, nli

    # ------------------------------------------------------------------ public

    def verify(self, claim: Claim) -> Verdict:
        configs, note = self.lib.match_configs(claim.vehicle)
        if not configs:
            return Verdict(claim=claim, status="unverifiable", reason=note or "No matching official documentation.",
                           config_note=note)
        results: list[ConfigResult] = []
        evidence: list[Evidence] = []
        method = "none"
        for cfg in configs:
            res, ev, m = self._verify_config(claim, cfg)
            results.append(res)
            evidence.extend(ev)
            method = m if m != "none" else method
        decided = [r for r in results if r.status != "unverifiable"]
        if not decided:
            status, reason = "unverifiable", results[0].reason
        elif len(configs) == 1:
            status, reason = results[0].status, results[0].reason
        else:
            kinds = {r.status for r in decided}
            if kinds == {"supported"}:
                status, reason = "supported", f"Holds for every matching configuration ({len(decided)} checked). {decided[0].reason}"
            elif kinds == {"contradicted"}:
                status, reason = "contradicted", f"Contradicted for every matching configuration ({len(decided)} checked). {decided[0].reason}"
            else:
                status = "partial"
                words = {"supported": "Supported", "partial": "Partly supported", "contradicted": "Contradicted"}
                parts = [f"{words[s]} for {', '.join(self._short(r.config, claim) for r in decided if r.status == s)}"
                         for s in words if any(r.status == s for r in decided)]
                reason = "; ".join(parts) + ". The claim does not say which configuration it means."
        official = None
        if decided:
            official = decided[0].official if len(decided) == 1 else " · ".join(
                f"{self._short(r.config, claim)}: {r.official}" for r in decided if r.official)
        return Verdict(claim=claim, status=status, reason=reason, official=official or None, method=method,
                       evidence=evidence[:6], configs=results, config_note=note)

    def _short(self, config_label: str, claim: Claim) -> str:
        head = " ".join(str(p) for p in (claim.vehicle.year, claim.vehicle.make, claim.vehicle.model) if p)
        return config_label.replace(head, "").strip() or config_label

    # ------------------------------------------------------------------ per configuration

    def query_for(self, claim: Claim) -> str:
        if claim.attribute == onto.FEATURE:
            return f"{claim.value_text} equipment standard optional"
        label = claim.attribute_label or ""
        return f"{label} {QUERY_TERMS.get(claim.attribute or '', '')} {claim.variant or ''} {claim.quote}"

    def _evidence(self, cfg: Config, fact: Fact, rank: int | None) -> Evidence:
        return Evidence(doc_id=cfg.doc.id, doc_title=cfg.doc.title, file=cfg.doc.file, page=fact.page,
                        heading=fact.heading, trim=fact.trim or " / ".join(fact.qualifiers) or None, market=cfg.doc.market, text=fact.line,
                        standard=fact.standard, retrieval_rank=rank,
                        url=cfg.doc.source_url if cfg.doc.file.endswith(".html") else None)

    def _verify_config(self, claim: Claim, cfg: Config) -> tuple[ConfigResult, list[Evidence], str]:
        if claim.unit == "mpg" and (cfg.doc.market or "").upper() == "UK":
            claim = claim.model_copy(update={"unit": "mpg (UK)"})  # a UK sheet quotes imperial gallons
        chunks = self.retriever.search(self.query_for(claim), cfg.doc.id, cfg.trim)
        ranked = [(rank, f) for rank, ch in enumerate(chunks, start=1) for f in self.lib.facts_by_chunk.get(ch.id, [])]

        def result(status: str, reason: str, official: str | None = None) -> ConfigResult:
            return ConfigResult(config=cfg.label, status=status, official=official, reason=reason)

        key = claim.attribute
        if key is None:
            return self._verify_nli(claim, cfg, chunks, result)

        if key == onto.FEATURE:
            want = _tokens(claim.value_text or "")
            best: tuple[float, int, Fact] | None = None
            for rank, f in ranked:
                if f.kind != "feature":
                    continue
                have = _tokens(f.label)
                overlap = len(want & have) / max(len(want | have), 1)
                if overlap >= 0.5 and (best is None or overlap > best[0]):
                    best = (overlap, rank, f)
            if not best:
                return result("unverifiable", f'The retrieved official equipment list does not mention "{claim.value_text}".'), [], "feature"
            _, rank, f = best
            if not cfg.doc.trims:
                return self._verify_feature_grid(claim, cfg, [(r, x) for r, x in ranked if x.kind == "feature" and x.label == f.label], result)
            status, reason = self._feature_verdict(claim.asserted or "available", f.value_text or "", f.label)
            return result(status, reason, f.value_text.capitalize()), [self._evidence(cfg, f, rank)], "feature"

        attr = onto.ATTR[key]
        cands = [(rank, f) for rank, f in ranked if f.attribute == key]
        if not cands:
            return result("unverifiable", f"No official {attr.label.lower()} figure was found in the evidence retrieved for this configuration."), [], "none"
        if not cfg.doc.trims:
            return self._verify_qualified(claim, cfg, attr, cands, result)

        if attr.kind == "categorical":
            rank, f = cands[0]
            accepted = onto.CATEGORY_IMPLIES.get((key, claim.value_text), {claim.value_text})
            ok = f.value_text in accepted
            reason = (f"Official specification: {f.line}." if ok else
                      f"Official specification says {f.value_text} ({f.line}), not {claim.value_text}.")
            return result("supported" if ok else "contradicted", reason, f.value_text), [self._evidence(cfg, f, rank)], "categorical"

        if attr.kind == "count":
            hit = next(((r, f) for r, f in cands if f.count == int(claim.value or -1)), None)
            rank, f = hit or min(cands, key=lambda rf: abs((rf[1].count or 0) - (claim.value or 0)))
            reason = (f"Matches the official specification: {f.line}." if hit else
                      f"Official specification: {f.line}. The review says {int(claim.value or 0)}.")
            return result("supported" if hit else "contradicted", reason, str(f.count)), [self._evidence(cfg, f, rank)], "numeric"

        # numeric
        if claim.value is None or claim.unit not in UNIT_BY_NAME or UNIT_BY_NAME[claim.unit].dimension != attr.dimension:
            return result("unverifiable", "The claim has no comparable figure."), [], "none"
        if key == "fuel_economy":
            want_variant = claim.variant or "combined"
            narrowed = [(r, f) for r, f in cands if f.variant == want_variant]
            if claim.variant and not narrowed:
                return result("unverifiable", f"The official document publishes no {claim.variant} fuel economy figure for this configuration."), [], "numeric"
            cands = narrowed or cands
        scored = [(compare_numeric(claim, f), r, f) for r, f in cands]
        match = next((s for s in scored if s[0][0]), None)
        (ok, rel, official), rank, f = match or min(scored, key=lambda s: abs(s[0][1]))
        std = f" (measured on the {f.standard} cycle)" if f.standard else ""
        basis = " combined" if key == "fuel_economy" and not claim.variant and f.variant == "combined" else ""
        if ok:
            reason = f"Matches the official{basis} figure{std}: {f.line}."
        else:
            direction = "higher" if rel > 0 else "lower"
            reason = (f"Official{basis} figure is {official}{std}; the claimed {fmt(claim.value, claim.unit)} "
                      f"is {abs(rel) * 100:.0f}% {direction}. Source line: {f.line}.")
            if claim.qualifier in ("min", "max"):
                reason = f"Official{basis} figure is {official}{std}, which is not {'above' if claim.qualifier == 'min' else 'below'} {fmt(claim.value, claim.unit)}. Source line: {f.line}."
        return result("supported" if ok else "contradicted", reason, official), [self._evidence(cfg, f, rank)], "numeric"

    def _verify_qualified(self, claim: Claim, cfg: Config, attr, cands, result):
        """Column-table sheets: one attribute has a row per variant (powertrain, body style, grade).

        Rows are grouped by the variant they apply to. The claim holds for a variant if it matches
        any of that variant's rows; across variants that gives supported / partial / contradicted.
        """
        method = "categorical" if attr.kind == "categorical" else "numeric"
        if attr.kind == "numeric" and (claim.value is None or claim.unit not in UNIT_BY_NAME
                                       or UNIT_BY_NAME[claim.unit].dimension != attr.dimension):
            return result("unverifiable", "The claim has no comparable figure."), [], "none"
        if attr.key == "fuel_economy":
            want_variant = claim.variant or "combined"
            narrowed = [(r, f) for r, f in cands if f.variant == want_variant]
            if claim.variant and not narrowed:
                return result("unverifiable", f"The official document publishes no {claim.variant} fuel economy figure."), [], method
            cands = narrowed or cands
        scope = ""
        if cfg.variant:
            want = _vtokens(cfg.variant)
            narrowed = [(r, f) for r, f in cands if want <= _vtokens(" ".join(f.qualifiers))]
            if narrowed:
                cands = narrowed
            elif any(f.qualifiers for _, f in cands):
                scope = f" The sheet does not break this figure down by {cfg.variant}, so every listed variant was checked."

        def match(f: Fact) -> tuple[bool, float, str]:
            if attr.kind == "categorical":
                accepted = onto.CATEGORY_IMPLIES.get((attr.key, claim.value_text), {claim.value_text})
                return f.value_text in accepted, 1.0, str(f.value_text)
            if attr.kind == "count":
                return f.count == int(claim.value or -1), abs((f.count or 0) - (claim.value or 0)), str(f.count)
            return compare_numeric(claim, f)

        groups: dict[tuple, list] = {}
        for rank, f in cands:
            groups.setdefault(f.qualifiers, []).append((match(f), rank, f))
        best = {q: next((m for m in ms if m[0][0]), min(ms, key=lambda m: abs(m[0][1]))) for q, ms in groups.items()}
        yes = [q for q, m in best.items() if m[0][0]]
        no = [q for q in best if q not in yes]

        def names(qs: list[tuple]) -> str:
            labels = list(dict.fromkeys(" ".join(q) for q in qs if q))
            return ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")

        ordered = [best[q] for q in yes] + [best[q] for q in no]
        evidence, seen = [], set()
        for _, rank, f in ordered:
            if f.line not in seen and len(evidence) < 4:
                seen.add(f.line)
                evidence.append(self._evidence(cfg, f, rank))
        values = list(dict.fromkeys(m[0][2] for m in ordered))
        official = values[0] if len(values) == 1 else " · ".join(
            f"{' '.join(q) or 'all'}: {best[q][0][2]}" for q in list(best)[:4]) + (" …" if len(best) > 4 else "")
        if not yes:  # report the nearest official figure, not just the first variant listed
            ordered.sort(key=lambda m: abs(m[0][1]))
        (_, rel, off), _, f = ordered[0]
        std = f" (measured on the {f.standard} cycle)" if f.standard else ""
        said = fmt(claim.value, claim.unit) if attr.kind == "numeric" else (str(int(claim.value)) if attr.kind == "count" else str(claim.value_text))
        if yes and not no:
            who = f" for {names(yes)}" if names(yes) else ""
            return result("supported", f"Matches the official figure{who}{std}: {f.line}.{scope}", official), evidence, method
        if yes:
            return result("partial", f"Matches {names(yes) or 'some variants'}{std}; differs for {names(no) or 'others'}. "
                                     f"The review does not say which variant it means.{scope}", official), evidence, method
        if attr.kind == "numeric":
            detail = f"the claimed {said} is {abs(rel) * 100:.0f}% {'higher' if rel > 0 else 'lower'} than the closest figure"
        else:
            detail = f"the review says {said}"
        who = f" ({names(no)})" if names(no) else ""
        return result("contradicted", f"Official figure{who} is {off}{std}; {detail}. Source line: {f.line}.{scope}", official), evidence, method

    def _verify_feature_grid(self, claim: Claim, cfg: Config, rows, result):
        """Equipment grids: one feature, one availability mark per grade."""
        scope = ""
        if cfg.variant:
            want = _vtokens(cfg.variant)
            narrowed = [(r, f) for r, f in rows if want <= _vtokens(" ".join(f.qualifiers))]
            if narrowed:
                rows = narrowed
            else:
                scope = f" The equipment list has no {cfg.variant} column, so every grade was checked."
        name = rows[0][1].label
        by_mark: dict[str, list[str]] = {}
        statuses = []
        for _, f in rows:
            by_mark.setdefault(f.value_text or "", []).append(" ".join(f.qualifiers) or "all grades")
            statuses.append(self._feature_verdict(claim.asserted or "available", f.value_text or "", name)[0])
        words = {"standard": "standard on", "optional": "optional on", "not available": "not available on"}
        summary = "; ".join(f"{words[m]} {', '.join(dict.fromkeys(g))}" for m, g in by_mark.items() if m in words)
        kinds = set(statuses)
        status = "supported" if kinds == {"supported"} else "contradicted" if kinds == {"contradicted"} else "partial"
        evidence = [self._evidence(cfg, f, r) for r, f in rows[:4]]
        return result(status, f"{name}: {summary}.{scope}", summary), evidence, "feature"

    @staticmethod
    def _feature_verdict(asserted: str, official: str, name: str) -> tuple[str, str]:
        table = {
            ("standard", "standard"): ("supported", f"{name} is standard equipment."),
            ("standard", "optional"): ("partial", f"{name} is available, but as an option rather than standard equipment."),
            ("standard", "not available"): ("contradicted", f"{name} is not available on this configuration."),
            ("available", "standard"): ("supported", f"{name} is standard equipment."),
            ("available", "optional"): ("partial", f"{name} is offered only as an option on this configuration."),
            ("available", "not available"): ("contradicted", f"{name} is not available on this configuration."),
            ("optional", "optional"): ("supported", f"{name} is an optional extra."),
            ("optional", "standard"): ("contradicted", f"{name} is standard equipment, not an option."),
            ("optional", "not available"): ("contradicted", f"{name} is not available on this configuration, even as an option."),
            ("absent", "not available"): ("supported", f"{name} is not available on this configuration."),
            ("absent", "optional"): ("partial", f"{name} is not standard, but it can be ordered as an option."),
            ("absent", "standard"): ("contradicted", f"{name} is standard equipment."),
        }
        return table.get((asserted, official), ("unverifiable", "Availability could not be determined."))

    def _verify_nli(self, claim, cfg, chunks, result):
        if not self.nli or not self.nli.available:
            return result("unverifiable", "This claim is not a figure, category or equipment item, and no NLI model is loaded to check free text."), [], "none"
        hypothesis = claim.value_text or claim.text
        best = None
        for rank, ch in enumerate(chunks, start=1):
            for f_line, page in self._lines(ch):
                p = self.nli.predict(f_line, hypothesis)
                label = max(("entailment", "contradiction"), key=lambda k: p[k])
                if best is None or p[label] > best[0]:
                    best = (p[label], label, f_line, page, rank, ch)
        if not best or best[0] < NLI_THRESHOLD:
            return result("unverifiable", "No retrieved passage of the official document entails or contradicts this claim."), [], "nli"
        score, label, line, page, rank, ch = best
        ev = Evidence(doc_id=cfg.doc.id, doc_title=cfg.doc.title, file=cfg.doc.file, page=page, heading=ch.heading,
                      trim=ch.trim, market=cfg.doc.market, text=line, retrieval_rank=rank)
        status = "supported" if label == "entailment" else "contradicted"
        return result(status, f"NLI {label} ({score:.2f}) against: {line}.", None), [ev], "nli"

    def _lines(self, chunk):
        facts = {f.line: f.page for f in self.lib.facts_by_chunk.get(chunk.id, [])}
        for line in chunk.text.split("\n")[1:]:
            yield line, facts.get(line, chunk.page)
