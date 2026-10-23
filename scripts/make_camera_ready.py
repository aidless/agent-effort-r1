r"""paper-writing-agent: camera-ready converter (N6).

Converts the anonymous TMLR manuscript to camera-ready:
  - \usepackage{tmlr}  ->  \usepackage[accepted]{tmlr}
  - inject author block (from a JSON spec) after \begin{document}
  - strip the double-blind placeholder author block
  - keep the anonymous version backed up as main_anon.tex

Author spec (authors.json):
  {"authors": [
     {"name": "Alice Zhang", "affiliation": "University X",
      "email": "alice@x.edu", "orcid": "0000-0001-2345-6789"},
     ...],
   "acknowledgements": "We thank ..."}

Usage:
  python make_camera_ready.py <paper_dir> --authors authors.json --out paper/main_cr.tex
  (default: writes paper/main.tex in place after backing up main_anon.tex)

Exit 0 = converted; exit 2 = inputs missing/unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir")
    ap.add_argument("--authors", required=True, help="authors.json spec")
    ap.add_argument("--out", default=None, help="output path (default: paper/main.tex in place)")
    args = ap.parse_args()

    root = Path(args.paper_dir).resolve()
    paper = root / "paper"
    main_tex = paper / "main.tex" if (paper / "main.tex").exists() else root / "main.tex"
    if not main_tex.exists():
        print(f"FAIL: no main.tex under {root}", file=sys.stderr)
        return 2
    auth_path = Path(args.authors)
    if not auth_path.exists():
        print(f"FAIL: authors spec not found: {auth_path}", file=sys.stderr)
        return 2
    spec = json.loads(auth_path.read_text(encoding="utf-8-sig"))

    text = main_tex.read_text(encoding="utf-8")

    # 1) template option: anonymous -> accepted
    new = re.sub(r"\\usepackage\{tmlr\}", r"\\usepackage[accepted]{tmlr}", text, count=1)
    if new == text:
        print("WARN: no \\usepackage{tmlr} found (template option unchanged)", file=sys.stderr)

    # 2) remove the anonymous author block (the template's sample block)
    #    pattern: \author{ ... } possibly spanning lines
    new = re.sub(r"\\author\s*\{[^}]*\}", "", new, count=1, flags=re.DOTALL)

    # 3) inject real authors after \begin{document}
    author_lines = ["\\author{"]
    for i, a in enumerate(spec.get("authors", [])):
        if i:
            author_lines.append("  \\and ")
        author_lines.append(f"  {a['name']}")
        if a.get("affiliation"):
            author_lines.append(f"  \\affiliation{{{a['affiliation']}}}")
        if a.get("email"):
            author_lines.append(f"  \\email{{{a['email']}}}")
        if a.get("orcid"):
            author_lines.append(f"  \\orcid{{{a['orcid']}}}")
    author_lines.append("}")
    author_block = "\n".join(author_lines)
    new = re.sub(r"(\\begin\{document\})",
                 lambda m: m.group(1) + "\n" + author_block + "\n", new, count=1)

    # 4) acknowledgements (if any)
    ack = (spec.get("acknowledgements") or "").strip()
    if ack:
        new = re.sub(r"(\\maketitle)",
                     lambda m: m.group(1) + f"\n\\begin{{acknowledgements}}\n{ack}\n\\end{{acknowledgements}}\n",
                     new, count=1)

    # 5) write: back up anonymous, write camera-ready
    out = Path(args.out) if args.out else main_tex
    anon_backup = main_tex.with_name("main_anon.tex")
    anon_backup.write_text(text, encoding="utf-8")
    out.write_text(new, encoding="utf-8")
    print(f"camera-ready written: {out}")
    print(f"anonymous backup: {anon_backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
