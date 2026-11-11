"""Print the reconstructed rows of a PDF: python -I scripts/dump_pdf.py file.pdf [max_rows_per_page]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import pymupdf
from autotruth.specs import _rows
pdf = pymupdf.open(sys.argv[1])
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 40
print(f"== {Path(sys.argv[1]).name}: {len(pdf)} pages, page size {pdf[0].rect.width:.0f}x{pdf[0].rect.height:.0f}")
for n, page in enumerate(pdf, start=1):
    rows = _rows(page)
    print(f"-- page {n}: {len(rows)} rows")
    for r in rows[:limit]:
        print(f"  [{r['size']:.0f}{'b' if r['bold'] else ' '}] " + " | ".join(c[:38] for c in r["cells"]))
