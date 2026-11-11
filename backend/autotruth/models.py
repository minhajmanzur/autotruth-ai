from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["supported", "contradicted", "partial", "unverifiable"]


class Vehicle(BaseModel):
    make: str | None = None
    model: str | None = None
    year: int | None = None
    market: str | None = None
    trim: str | None = None

    def label(self) -> str:
        parts = [str(self.year) if self.year else None, self.make, self.model, self.trim]
        text = " ".join(p for p in parts if p) or "Unknown vehicle"
        return f"{text} ({self.market})" if self.market else text


class Claim(BaseModel):
    id: str
    text: str  # normalised atomic statement
    quote: str  # the sentence it came from, verbatim
    kind: Literal["factual", "subjective"] = "factual"
    attribute: str | None = None
    attribute_label: str | None = None
    value: float | None = None
    unit: str | None = None
    value_text: str | None = None  # categorical value, feature name or free text
    qualifier: Literal["exact", "approx", "min", "max"] = "exact"
    variant: str | None = None  # e.g. city / highway / combined
    asserted: str | None = None  # features: standard | available | optional | absent
    vehicle: Vehicle = Field(default_factory=Vehicle)
    extractor: str = "rules"


class Evidence(BaseModel):
    doc_id: str
    doc_title: str
    file: str
    page: int
    heading: str
    trim: str | None = None
    market: str | None = None
    text: str  # the exact line from the document
    standard: str | None = None  # measurement standard named on that line / section
    url: str | None = None       # set when the source is a web page rather than a PDF
    retrieval_rank: int | None = None


class ConfigResult(BaseModel):
    config: str
    status: Status
    official: str | None = None
    reason: str


class Verdict(BaseModel):
    claim: Claim
    status: Status
    reason: str
    official: str | None = None
    method: Literal["numeric", "categorical", "feature", "nli", "none"] = "none"
    evidence: list[Evidence] = Field(default_factory=list)
    configs: list[ConfigResult] = Field(default_factory=list)
    config_note: str | None = None


class Source(BaseModel):
    type: Literal["text", "web", "youtube", "reddit", "sample"] = "text"
    title: str = "Untitled review"
    url: str | None = None
    author: str | None = None


class Analysis(BaseModel):
    id: str
    created_at: str
    source: Source
    vehicle: Vehicle
    verdicts: list[Verdict]
    subjective: list[Claim]
    counts: dict[str, int]
    accuracy: float | None  # supported / verifiable factual claims
    summary: str
    extractor: str
    retrieval: str
    latency_ms: int
    text_chars: int


class AnalyzeRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    title: str | None = None
    author: str | None = None
    vehicle: Vehicle | None = None  # optional override for auto-detected configuration
    use_llm: bool | None = None
    save: bool = True
