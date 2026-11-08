"""Gera docs/relatorio.pdf a partir de docs/relatorio.md (mesmo padrão do repositório de visão).

    pip install -r requirements-docs.txt
    python scripts/build_report.py
"""
from __future__ import annotations

from pathlib import Path

import markdown
from weasyprint import HTML

DOCS = Path(__file__).resolve().parents[1] / "docs"
CSS = """
@page { size: A4; margin: 2cm 1.8cm; @bottom-center { content: counter(page); font-size: 9pt; color: #666; } }
@page paisagem { size: A4 landscape; margin: 1.2cm; }
body { font-family: 'DejaVu Sans', sans-serif; font-size: 10pt; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 19pt; margin: 0 0 6pt; color: #3a2a00; }
h2 { font-size: 13pt; margin: 16pt 0 6pt; color: #3a2a00; border-bottom: 1.5px solid #e2b93b; padding-bottom: 2pt; }
p, li { text-align: justify; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #d6d2c4; padding: 3pt 5pt; text-align: left; vertical-align: top; }
th { background: #faf3dc; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.4pt; background: #f4f4f1; padding: 0 2pt; }
pre { background: #f4f4f1; padding: 6pt 8pt; font-size: 7.8pt; white-space: pre-wrap; border-radius: 4px; }
pre code { background: none; padding: 0; }
img { max-width: 100%; display: block; margin: 6pt auto; border: 1px solid #ddd; }
.fig { page-break-inside: avoid; margin: 8pt 0; }
.fig img { max-height: 21cm; }
.paisagem { page: paisagem; page-break-before: always; page-break-after: always; }
.paisagem img { width: 100%; border: none; }
em.legenda { display: block; text-align: center; font-size: 8.5pt; color: #555; margin-top: 3pt; }
"""


def main() -> None:
    md = (DOCS / "relatorio.md").read_text(encoding="utf-8")
    html = markdown.markdown(md, extensions=["tables", "fenced_code", "md_in_html"])
    doc = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>"
    destino = DOCS / "relatorio.pdf"
    HTML(string=doc, base_url=str(DOCS) + "/").write_pdf(destino)
    print(f"{destino.relative_to(DOCS.parent)} gerado ({destino.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
