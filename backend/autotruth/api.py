"""FastAPI application. Run from the project root:

    .venv/Scripts/python -m uvicorn autotruth.api:app --app-dir backend --port 8000
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, claims, config, sources
from .models import Analysis, AnalyzeRequest, Source
from .pipeline import Engine, disagreements
from .store import Store

state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["engine"] = Engine()
    state["store"] = Store(config.DB_PATH)
    yield


app = FastAPI(title="AutoTruth AI", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def engine() -> Engine:
    return state["engine"]


def store() -> Store:
    return state["store"]


def _samples() -> list[dict]:
    path = config.REVIEWS_DIR / "samples.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@app.get("/api/health")
def health() -> dict:
    e = engine()
    return {
        "version": __version__,
        "retrieval": e.retriever.description,
        "retrieval_note": e.retriever.note,
        "nli": e.nli.backend if e.nli and e.nli.available else None,
        "nli_model": config.NLI_MODEL,
        "llm": config.LLM_MODEL if claims.llm_available() else None,
        "extractor": "llm" if claims.llm_available() else "rules",
        "documents": len(e.lib.docs), "chunks": len(e.lib.chunks), "facts": len(e.lib.facts),
        "library_errors": e.lib.errors,
    }


@app.get("/api/library")
def library() -> list[dict]:
    e = engine()
    out = []
    for d in e.lib.docs.values():
        facts = [f for f in e.lib.facts if f.doc_id == d.id]
        out.append({**d.__dict__, "facts": len(facts), "chunks": sum(c.doc_id == d.id for c in e.lib.chunks),
                    "sections": sorted({f.heading for f in facts})})
    return out


@app.get("/api/library/{doc_id}/facts")
def library_facts(doc_id: str) -> list[dict]:
    e = engine()
    if doc_id not in e.lib.docs:
        raise HTTPException(404, "Unknown document")
    return [{"trim": f.trim, "page": f.page, "heading": f.heading, "line": f.line, "attribute": f.attribute,
             "kind": f.kind, "standard": f.standard} for f in e.lib.facts if f.doc_id == doc_id]


@app.get("/api/specs/{file}")
def spec_file(file: str) -> FileResponse:
    path = config.SPECS_DIR / file
    if not re.fullmatch(r"[\w.\- ]+\.pdf", file) or not path.is_file():
        raise HTTPException(404, "Unknown document")
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")


@app.post("/api/library/upload")
async def upload_spec(file: UploadFile = File(...), make: str = Form(...), model: str = Form(...),
                      year: int | None = Form(None), market: str | None = Form(None)) -> dict:
    name = re.sub(r"[^\w.\-]+", "-", (file.filename or "spec.pdf")).strip("-")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a PDF.")
    path = config.SPECS_DIR / name
    path.write_bytes(data)
    meta = {"make": make.strip(), "model": model.strip(), "year": year, "market": (market or "").strip() or None}
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    engine().reload()
    doc = engine().lib.docs.get(path.stem)
    if not doc:
        raise HTTPException(422, f"Could not parse the PDF: {engine().lib.errors.get(name, 'unknown error')}")
    return {"id": doc.id, "trims": doc.trims, "facts": sum(f.doc_id == doc.id for f in engine().lib.facts)}


@app.get("/api/samples")
def samples() -> list[dict]:
    return _samples()


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> Analysis:
    if req.url and not req.text:
        try:
            source, text = sources.fetch(req.url.strip())
        except sources.FetchError as exc:
            raise HTTPException(422, str(exc)) from exc
        if req.title:
            source.title = req.title
    elif req.text and req.text.strip():
        text = req.text
        source = Source(type="text", title=req.title or "Pasted review", url=req.url, author=req.author)
    else:
        raise HTTPException(400, "Provide review text or a URL.")
    if len(text) > 200_000:
        raise HTTPException(413, "Text is too long (limit 200,000 characters).")
    if req.author:
        source.author = req.author
    result = engine().analyze(text, source, req.vehicle, req.use_llm)
    if req.save:
        store().save(result)
    return result


@app.get("/api/analyses")
def analyses() -> list[dict]:
    return [{"id": a.id, "created_at": a.created_at, "title": a.source.title, "author": a.source.author,
             "type": a.source.type, "vehicle": a.vehicle.label(), "counts": a.counts, "accuracy": a.accuracy}
            for a in store().all()]


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> Analysis:
    a = store().get(analysis_id)
    if not a:
        raise HTTPException(404, "Unknown analysis")
    return a


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: str) -> dict:
    if not store().delete(analysis_id):
        raise HTTPException(404, "Unknown analysis")
    return {"deleted": analysis_id}


@app.get("/api/disagreements")
def get_disagreements() -> list[dict]:
    return disagreements(store().all())


@app.get("/api/eval")
def eval_results() -> dict:
    if not config.EVAL_RESULTS.exists():
        return {}
    return json.loads(config.EVAL_RESULTS.read_text(encoding="utf-8"))


if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
