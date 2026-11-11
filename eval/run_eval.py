"""Claim-level evaluation of the AutoTruth AI pipeline against eval/benchmark.json.

    python eval/run_eval.py                 # pipeline, current extractor
    python eval/run_eval.py --ablation      # also BM25-only retrieval
    python eval/run_eval.py --baseline      # also an LLM-judges-everything baseline (needs LLM_API_KEY)

Writes eval/results/latest.json (shown on the dashboard's Evaluation tab).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import pymupdf  # noqa: E402

from autotruth import claims as claim_mod  # noqa: E402
from autotruth import config, ontology as onto  # noqa: E402
from autotruth.models import Source, Vehicle, Verdict  # noqa: E402
from autotruth.pipeline import Engine  # noqa: E402
from autotruth.units import UNIT_BY_NAME, to_base  # noqa: E402


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def same_claim(gold: dict, v: Verdict) -> bool:
    c = v.claim
    if c.attribute != gold["attribute"] or gold["in"].lower() not in c.quote.lower():
        return False
    if isinstance(gold["value"], str):
        return norm(c.value_text) == norm(gold["value"])
    if c.value is None:
        return False
    if gold.get("unit") and c.unit in UNIT_BY_NAME:
        g = to_base(gold["value"], gold["unit"])
        return abs(to_base(c.value, c.unit) - g) <= 1e-6 * max(abs(g), 1)
    return abs(c.value - gold["value"]) < 1e-9


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def pct(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


_page_text: dict[tuple[str, int], str] = {}


def citation_is_verbatim(file: str, page: int, line: str) -> bool:
    """A citation is real only if both halves of the cited row are on the cited PDF page."""
    key = (file, page)
    if key not in _page_text:
        with pymupdf.open(config.SPECS_DIR / file) as pdf:
            _page_text[key] = re.sub(r"\s+", " ", pdf[page - 1].get_text())
    label, _, value = line.partition(": ")
    return label in _page_text[key] and value in _page_text[key]


def evaluate(engine: Engine, bench: dict, samples: dict, use_llm: bool) -> dict:
    ext = {"tp": 0, "fp": 0, "fn": 0}
    subj = {"tp": 0, "fp": 0, "fn": 0}
    contra = {"tp": 0, "fp": 0, "fn": 0}
    matched = verdict_ok = numeric_n = numeric_ok = trim_ok = vehicle_ok = 0
    cite_n = cite_ok = verbatim_n = verbatim_ok = 0
    recall_hits = {1: 0, 2: 0, 3: 0}
    recall_n = 0
    confusion: dict[str, dict[str, int]] = {}
    latencies: list[int] = []
    extractors_used: set[str] = set()
    errors: list[dict] = []
    gold_total = predicted_total = 0

    for rid, gold in bench["reviews"].items():
        review = samples[rid]
        a = engine.analyze(review["text"], Source(title=review["title"]), use_llm=use_llm)
        latencies.append(a.latency_ms)
        extractors_used.add(a.extractor)
        gv = gold["vehicle"]
        vehicle_ok += all(norm(getattr(a.vehicle, k)) == norm(gv[k]) for k in ("make", "model", "year", "market", "trim"))

        remaining = list(a.verdicts)
        predicted_total += len(remaining)
        gold_total += len(gold["claims"])
        for g in gold["claims"]:
            v = next((x for x in remaining if same_claim(g, x)), None)
            if v is None:
                ext["fn"] += 1
                contra["fn"] += g["verdict"] == "contradicted"
                errors.append({"review": rid, "type": "missed claim", "gold": f"{g['attribute']}={g['value']}", "sentence": g["in"]})
                continue
            remaining.remove(v)
            ext["tp"] += 1
            matched += 1
            trim_ok += norm(v.claim.vehicle.trim) == norm(g["trim"])
            confusion.setdefault(g["verdict"], {}).setdefault(v.status, 0)
            confusion[g["verdict"]][v.status] += 1
            ok = v.status == g["verdict"]
            verdict_ok += ok
            if not ok:
                errors.append({"review": rid, "type": "wrong verdict", "gold": g["verdict"], "predicted": v.status,
                               "claim": v.claim.text, "reason": v.reason})
            if v.status == "contradicted":
                contra["tp" if g["verdict"] == "contradicted" else "fp"] += 1
            elif g["verdict"] == "contradicted":
                contra["fn"] += 1
            if v.claim.value is not None and v.claim.unit and not UNIT_BY_NAME[v.claim.unit].dimension.startswith("count"):
                numeric_n += 1
                numeric_ok += ok
            if g["heading"]:
                if v.evidence:
                    cite_n += 1
                    cite_ok += all(e.heading == g["heading"] for e in v.evidence) and (
                        not g["trim"] or all(norm(e.trim) == norm(g["trim"]) for e in v.evidence))
                gold_vehicle = Vehicle(**{**gv, "trim": g["trim"]})
                for cfg in engine.lib.match_configs(gold_vehicle)[0]:
                    chunks = engine.retriever.search(engine.verifier.query_for(v.claim), cfg.doc.id, cfg.trim, k=3)
                    recall_n += 1
                    for k in recall_hits:
                        recall_hits[k] += any(c.heading == g["heading"] for c in chunks[:k])
            for e in v.evidence:
                verbatim_n += 1
                verbatim_ok += citation_is_verbatim(e.file, e.page, e.text)
        for v in remaining:  # predicted claims with no gold counterpart
            ext["fp"] += 1
            contra["fp"] += v.status == "contradicted"
            errors.append({"review": rid, "type": "spurious claim", "claim": v.claim.text, "sentence": v.claim.quote})

        gold_subj = [s.lower() for s in gold["subjective"]]
        pred_subj = [c.quote.lower() for c in a.subjective]
        hit = sum(any(g in p for p in pred_subj) for g in gold_subj)
        subj["tp"] += hit
        subj["fn"] += len(gold_subj) - hit
        subj["fp"] += sum(not any(g in p for g in gold_subj) for p in pred_subj)

    n_reviews = len(bench["reviews"])
    gold_dist: dict[str, int] = {}
    for r in bench["reviews"].values():
        for g in r["claims"]:
            gold_dist[g["verdict"]] = gold_dist.get(g["verdict"], 0) + 1
    return {
        "extractor": " + ".join(sorted(extractors_used)),
        "retrieval": engine.retriever.description,
        "reviews": n_reviews,
        "gold_claims": gold_total,
        "predicted_claims": predicted_total,
        "gold_verdict_distribution": gold_dist,
        "claim_extraction": prf(**ext),
        "subjective_separation": prf(**subj),
        "vehicle_configuration_accuracy": pct(vehicle_ok, n_reviews),
        "claim_trim_accuracy": pct(trim_ok, matched),
        "verification_accuracy_on_extracted": pct(verdict_ok, matched),
        "verification_accuracy_end_to_end": pct(verdict_ok, gold_total),
        "numeric_matching_accuracy": pct(numeric_ok, numeric_n),
        "contradiction_detection": prf(**contra),
        "retrieval_recall_at_k": {f"@{k}": pct(h, recall_n) for k, h in recall_hits.items()},
        "citation_correctness": pct(cite_ok, cite_n),
        "citation_verbatim_in_pdf": pct(verbatim_ok, verbatim_n),
        "hallucination_rate": {
            "spurious_claims": pct(ext["fp"], predicted_total),
            "fabricated_citations": pct(verbatim_n - verbatim_ok, verbatim_n),
        },
        "unsupported_claim_rate_gold": pct(gold_total - gold_dist.get("supported", 0), gold_total),
        "confusion": confusion,
        "latency_ms": {"mean": round(statistics.mean(latencies)), "max": max(latencies)},
        "cost_per_review_usd": 0.0 if not use_llm else None,
        "errors": errors,
    }


BASELINE_SYSTEM = """You are checking a car reviewer's claims against excerpts of the official specification sheet.
For each numbered claim answer supported, contradicted, partial or unverifiable:
supported = the excerpt confirms it; contradicted = the excerpt states otherwise; partial = true only in part
(for example true for one trim but not another, or optional rather than standard); unverifiable = the excerpt does not cover it.
Return JSON only: {"verdicts": [{"n": 1, "verdict": "..."}, ...]} with one entry per claim."""


def baseline(engine: Engine, bench: dict, samples: dict) -> dict:
    """Ordinary RAG: same gold claims, same retrieved evidence, but the LLM alone decides the verdict.

    Isolates what the independent verification layer adds over 'retrieve, then ask the model'.
    One request per review, so the run fits a free-tier daily quota.
    """
    from openai import OpenAI

    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    n = ok = 0
    contra = {"tp": 0, "fp": 0, "fn": 0}
    confusion: dict[str, dict[str, int]] = {}
    errors: list[dict] = []
    tokens = 0
    for rid, gold in bench["reviews"].items():
        sentences = [s for _, s in claim_mod.split_sentences(samples[rid]["text"])]
        blocks = []
        for i, g in enumerate(gold["claims"], start=1):
            sentence = next((s for s in sentences if g["in"].lower() in s.lower()), g["in"])
            vehicle = Vehicle(**{**gold["vehicle"], "trim": g["trim"]})
            configs, _ = engine.lib.match_configs(vehicle)
            excerpt = "\n\n".join(c.text for cfg in configs for c in engine.retriever.search(sentence, cfg.doc.id, cfg.trim))
            blocks.append(f"### Claim {i}\nVehicle: {vehicle.label()}\nReviewer's sentence: {sentence}\n"
                          f"Claim to check: {g['attribute']} = {g['value']} {g.get('unit', '')}\n"
                          f"Official excerpt:\n{excerpt or '(no official document matches this vehicle)'}")
        resp = client.chat.completions.create(
            model=config.LLM_MODEL, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": "\n\n".join(blocks)}])
        tokens += resp.usage.total_tokens if resp.usage else 0
        answers = {int(v["n"]): v.get("verdict") for v in json.loads(resp.choices[0].message.content or "{}").get("verdicts", [])}
        for i, g in enumerate(gold["claims"], start=1):
            pred = answers.get(i, "missing")
            n += 1
            ok += pred == g["verdict"]
            confusion.setdefault(g["verdict"], {}).setdefault(pred, 0)
            confusion[g["verdict"]][pred] += 1
            if pred != g["verdict"]:
                errors.append({"review": rid, "type": "wrong verdict", "claim": f"{g['attribute']}={g['value']}",
                               "gold": g["verdict"], "predicted": pred, "sentence": g["in"]})
            if pred == "contradicted":
                contra["tp" if g["verdict"] == "contradicted" else "fp"] += 1
            elif g["verdict"] == "contradicted":
                contra["fn"] += 1
    return {"model": config.LLM_MODEL, "claims": n, "verification_accuracy": pct(ok, n),
            "contradiction_detection": prf(**contra), "confusion": confusion, "total_tokens": tokens, "errors": errors}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use the LLM claim extractor (needs LLM_API_KEY)")
    ap.add_argument("--ablation", action="store_true", help="also evaluate BM25-only retrieval")
    ap.add_argument("--baseline", action="store_true", help="also run the LLM-as-judge baseline (needs LLM_API_KEY)")
    args = ap.parse_args()

    bench = json.loads((ROOT / "eval" / "benchmark.json").read_text(encoding="utf-8"))
    samples = {s["id"]: s for s in json.loads((config.REVIEWS_DIR / "samples.json").read_text(encoding="utf-8"))}
    if (args.llm or args.baseline) and not claim_mod.llm_available():
        sys.exit("LLM_API_KEY is not set; --llm and --baseline need it.")

    config.MODEL_YEAR_TOLERANCE = 0  # the benchmark expects a strict model-year match
    engine = Engine()
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "pipeline": evaluate(engine, bench, samples, False)}
    if args.ablation:
        out["ablation_bm25_only"] = evaluate(Engine(retrieval_mode="bm25"), bench, samples, False)
    if args.llm:
        out["pipeline_llm_extractor"] = evaluate(engine, bench, samples, True)
    if args.baseline:
        out["baseline_llm_judge"] = baseline(engine, bench, samples)

    dest = ROOT / "eval" / "results" / "latest.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")

    for name, res in out.items():
        if not isinstance(res, dict):
            continue
        print(f"\n== {name} ==")
        for k, v in res.items():
            if k != "errors":
                print(f"  {k}: {v}")
        for e in res.get("errors", []):
            print("  !", e)
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
