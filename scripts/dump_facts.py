"""Print the specification facts parsed from documents: python scripts/dump_facts.py file.pdf|file.html ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from autotruth.specs import parse_html, parse_pdf  # noqa: E402

for name in sys.argv[1:]:
    path = Path(name)
    doc, chunks, facts = parse_html(path) if path.suffix == ".html" else parse_pdf(path)
    print(f"== {doc.title} | {len(chunks)} chunks, {len(facts)} facts | trims {doc.trims} | variants {doc.variants[:12]}")
    for f in facts:
        value = [(q.value, q.unit) for q in f.quantities] or f.count or f.value_text
        print(f"  p{f.page} {f.heading[:22]:22} {f.attribute:16} {str(value)[:46]:46} {'R' if f.is_range else ' '} "
              f"{f.variant or '':8} {f.trim or ''} {' / '.join(f.qualifiers)}")
