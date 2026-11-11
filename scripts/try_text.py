"""Run a piece of text through the pipeline and print the verdicts: python scripts/try_text.py "text" """
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from autotruth.models import Source  # noqa: E402
from autotruth.pipeline import Engine  # noqa: E402

engine = Engine(retrieval_mode="bm25", nli=False)
for text in sys.argv[1:]:
    a = engine.analyze(text, Source(title="test"), use_llm=False)
    print(f"\n== {a.vehicle.label()} | {a.counts}")
    for v in a.verdicts:
        print(f"  {v.status:13} {v.claim.text} [{v.claim.vehicle.trim or '-'}]\n{'':16}{v.reason[:230]}")
        if v.config_note:
            print(f"{'':16}note: {v.config_note}")
    for c in a.subjective:
        print(f"  subjective    {c.quote}")
