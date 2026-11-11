"""Evidence retrieval over specification chunks.

Hybrid by default: BM25 (lexical) and BGE embeddings in Qdrant (semantic), fused
with reciprocal rank fusion. Falls back to BM25 alone if the embedding model
cannot be loaded, and reports which mode is actually running.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import config
from .specs import Chunk, SpecLibrary

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(docs)) if docs else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query: list[str], i: int) -> float:
        tf, s = self.tf[i], 0.0
        for t in query:
            f = tf.get(t)
            if f:
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
        return s


class Retriever:
    COLLECTION = "spec_chunks"

    def __init__(self, lib: SpecLibrary, mode: str | None = None):
        self.lib = lib
        self.mode = "bm25"
        self.note: str | None = None
        self._embedder = None
        self._qdrant = None
        self.index(mode or config.RETRIEVAL_MODE)

    def index(self, mode: str = "auto") -> None:
        self.chunks: list[Chunk] = self.lib.chunks
        self.bm25 = BM25([tokenize(c.text) for c in self.chunks])
        self.mode, self._qdrant = "bm25", None
        if mode == "bm25" or not self.chunks:
            return
        try:
            from fastembed import TextEmbedding
            from qdrant_client import QdrantClient, models

            self._embedder = self._embedder or TextEmbedding(config.EMBEDDING_MODEL)
            vectors = [v.tolist() for v in self._embedder.embed([c.text for c in self.chunks])]
            client = QdrantClient(":memory:")
            client.create_collection(self.COLLECTION, vectors_config=models.VectorParams(
                size=len(vectors[0]), distance=models.Distance.COSINE))
            client.upsert(self.COLLECTION, points=[
                models.PointStruct(id=i, vector=v, payload={"doc_id": c.doc_id, "trim": c.trim or ""})
                for i, (c, v) in enumerate(zip(self.chunks, vectors))])
            self._qdrant, self.mode = client, "hybrid"
        except Exception as exc:  # no model, no network, missing wheel: stay lexical
            self.note = f"Embeddings unavailable ({type(exc).__name__}: {exc}); using BM25 only."

    @property
    def description(self) -> str:
        return (f"hybrid (BM25 + {config.EMBEDDING_MODEL} in Qdrant, RRF)" if self.mode == "hybrid" else "BM25")

    def search(self, query: str, doc_id: str, trim: str | None, k: int | None = None) -> list[Chunk]:
        pool = [i for i, c in enumerate(self.chunks) if c.doc_id == doc_id and c.trim == trim]
        if not pool:
            return []
        # long sheets are cut into many small sections, so look at more of them
        k = k or (config.TOP_K if len(pool) <= 20 else config.TOP_K * 2)
        q = tokenize(query)
        lexical = sorted(pool, key=lambda i: -self.bm25.score(q, i))
        if self.mode != "hybrid":
            return [self.chunks[i] for i in lexical[:k]]
        from qdrant_client import models

        vec = next(iter(self._embedder.query_embed(query))).tolist()
        hits = self._qdrant.query_points(
            self.COLLECTION, query=vec, limit=len(pool),
            query_filter=models.Filter(must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="trim", match=models.MatchValue(value=trim or "")),
            ])).points
        dense = [h.id for h in hits]
        rrf: dict[int, float] = {}
        for ranking in (lexical, dense):
            for rank, i in enumerate(ranking):
                rrf[i] = rrf.get(i, 0.0) + 1.0 / (60 + rank + 1)
        return [self.chunks[i] for i in sorted(rrf, key=lambda i: -rrf[i])[:k]]
