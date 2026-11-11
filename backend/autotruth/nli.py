"""Natural-language inference for claims that are not a number, a category or a feature.

Runs a DeBERTa NLI cross-encoder. Prefers the model's ONNX export on
onnxruntime (already installed for the embeddings, no torch); falls back to
sentence-transformers if that is installed. If neither loads, ``available`` is
False and free-text claims are reported as unverifiable rather than guessed.
"""
from __future__ import annotations

import numpy as np

from . import config

LABELS = ("contradiction", "entailment", "neutral")  # label order of cross-encoder/nli-deberta-v3-*


class NLI:
    def __init__(self, model: str | None = None):
        self.model = model or config.NLI_MODEL
        self.backend: str | None = None
        self.error: str | None = None
        self._loaded = False

    def _load(self) -> None:
        self._loaded = True
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer

            self._tok = Tokenizer.from_file(hf_hub_download(self.model, "tokenizer.json"))
            self._tok.enable_truncation(max_length=256)
            self._sess = ort.InferenceSession(hf_hub_download(self.model, "onnx/model.onnx"),
                                              providers=["CPUExecutionProvider"])
            self._inputs = {i.name for i in self._sess.get_inputs()}
            self.backend = "onnx"
            return
        except Exception as exc:
            self.error = f"onnx: {type(exc).__name__}: {exc}"
        try:
            from sentence_transformers import CrossEncoder

            self._ce = CrossEncoder(self.model)
            self.backend = "sentence-transformers"
        except Exception as exc:
            self.error = f"{self.error}; sentence-transformers: {type(exc).__name__}: {exc}"

    @property
    def available(self) -> bool:
        if not self._loaded:
            self._load()
        return self.backend is not None

    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        """Probability that the premise contradicts / entails / is neutral to the hypothesis."""
        if not self.available:
            raise RuntimeError(self.error or "NLI model unavailable")
        if self.backend == "onnx":
            enc = self._tok.encode(premise, hypothesis)
            feed = {"input_ids": np.array([enc.ids], dtype=np.int64),
                    "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
                    "token_type_ids": np.array([enc.type_ids], dtype=np.int64)}
            logits = self._sess.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0][0]
        else:
            logits = np.asarray(self._ce.predict([(premise, hypothesis)])[0])
        e = np.exp(logits - logits.max())
        return dict(zip(LABELS, (e / e.sum()).tolist()))
