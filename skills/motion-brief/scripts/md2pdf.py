#!/usr/bin/env python3
"""评赛：Markdown → PDF（pandoc + weasyprint，中文排版）。

用法:
  md2pdf.py <输入.md> <输出.pdf>
"""

import sys
import os
import subprocess
import tempfile

CSS = """
@page { size: A4; margin: 2.2cm 2cm; }
body { font-family: "Noto Sans CJK SC", sans-serif; font-size: 10.5pt; line-height: 1.65; color: #1a1a1a; }
h1 { font-size: 20pt; text-align: center; margin: 0 0 6pt; }
h2 { font-size: 14pt; margin: 14pt 0 6pt; padding-bottom: 3pt; border-bottom: 2px solid #333333; }
h3 { font-size: 12pt; margin: 10pt 0 4pt; }
p { margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.5pt; }
th { background: #333333; color: #ffffff; font-weight: bold; padding: 4pt 6pt; border: 1px solid #cccccc; text-align: left; }
td { padding: 4pt 6pt; border: 1px solid #dddddd; vertical-align: top; }
tr:nth-child(even) td { background: #f9f9f9; }
a { color: #0563c1; text-decoration: underline; }
blockquote { margin: 6pt 0; padding: 4pt 10pt; border-left: 3px solid #cccccc; color: #555555; background: #fafafa; }
code { background: #f2f2f2; padding: 0 3pt; }
hr { border: none; border-top: 1px solid #cccccc; margin: 10pt 0; }
"""


def md_to_pdf(md_path, pdf_path, title="辩题速览"):
    with tempfile.TemporaryDirectory() as td:
        css_path = os.path.join(td, "style.css")
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(CSS)
        html_path = os.path.join(td, "report.html")
        subprocess.run(
            ["pandoc", "-s", md_path, "-o", html_path,
             "--metadata", f"title={title}", "-c", css_path],
            check=True,
        )
        subprocess.run(["weasyprint", html_path, pdf_path], check=True)
    print(f"PDF:  {pdf_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    md_to_pdf(sys.argv[1], sys.argv[2])
