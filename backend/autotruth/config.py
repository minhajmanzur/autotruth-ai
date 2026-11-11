from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("AUTOTRUTH_DATA_DIR", ROOT / "data"))
SPECS_DIR = DATA_DIR / "specs"
REVIEWS_DIR = DATA_DIR / "reviews"
DB_PATH = Path(os.getenv("AUTOTRUTH_DB", DATA_DIR / "autotruth.db"))
EVAL_RESULTS = ROOT / "eval" / "results" / "latest.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"

LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip() or None

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "auto").strip().lower()  # auto | hybrid | bm25
NLI_MODEL = os.getenv("NLI_MODEL", "cross-encoder/nli-deberta-v3-small").strip()

TOP_K = int(os.getenv("TOP_K", "3"))
# 0 = a claim about a model year with no document on file is unverifiable. N = fall back to the
# nearest sheet within N model years, and say so on the verdict.
MODEL_YEAR_TOLERANCE = int(os.getenv("MODEL_YEAR_TOLERANCE", "0"))
