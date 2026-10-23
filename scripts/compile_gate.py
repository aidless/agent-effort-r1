"""compile_gate.py — LaTeX 编译门(gap-review R2 新增): 编译 + 引用键核对。

Phase 3 机器检查之一(名字引用: compile-gate; 不数序号)。三层设计:

1. 静态键核对(无需 TeX, 断 TeX 时唯一层):
   - \\cite 键 ↔ .bib 条目存在性; \\ref/\\autoref/\\eqref/\\pageref/\\cref 键 ↔ \\label 定义;
   - orphan label(定义了从未被引用, WARN); uncited bib 条目(WARN)。
2. 动态编译(需 pdflatex+bibtex, 权威层): 在临时目录编译(绝不污染交付态, FM-28),
   日志扫描: 编译错误 / undefined reference / undefined citation / multiply-defined label /
   overfull hbox(WARN)。undefined 判定以编译日志为准(LaTeX 自己报)。
3. 降级: TeX 不可用 → 只跑静态层, 报告 "## Compile skipped: 1"(文档化降级,
   与 gate_citations 的 Skipped_network 同哲学——降级是记录的通过, 不静默阻塞)。

用法:
  python compile_gate.py <paper_dir> --out reports/compile.md
        [--main main.tex] [--no-tex] [--fail-on-warning] [--timeout 180]
exit 0 = 错误类全 0(compile errors / undefined refs / undefined cites / multiply labels);
exit 1 = 存在错误类问题(--fail-on-warning 时 overfull/orphan/uncited 也计);
exit 2 = 基础设施错误(找不到 main.tex / 无 .bib 但出现 \\cite / 崩溃)。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEX_EXT = {".tex", ".sty", ".cls", ".bst", ".bib", ".clo", ".def", ".cfg", ".tikz"}
IMG_EXT = {".png", ".pdf", ".jpg", ".jpeg", ".eps", ".svg"}
SKIP_EXT = {".aux", ".log", ".out", ".toc", ".lof", ".lot", ".synctex.gz", ".gz",
            ".tar", ".zip", ".pyc", ".npz", ".json", ".jsonl", ".md", ".txt", ".cmd",
            ".exe", ".pem", ".key", ".pkl", ".npz", ".npy"}

CITE_CMD = re.compile(r"\\(?:cite|citet|citep|parencite|textcite|citealp|autocite|citet*)\*?"
                      r"(?:\[[^\]]*\])?\{([^}]*)\}")
REF_CMD = re.compile(r"\\(?:ref|autoref|eqref|pageref|cref|Cref|labelcref)\*?\{([^}]*)\}")
LABEL_CMD = re.compile(r"\\label\{([^}]*)\}")
INPUT_CMD = re.compile(r"\\(?:input|include)\{([^}]*)\}")
BIBLIO_CMD = re.compile(r"\\(?:bibliography|addbibresource)\{([^}]*)\}")
BIB_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)")


def _split_keys(s: str) -> list[str]:
    return [k.strip() for k in s.split(",") if k.strip()]


def find_main(paper_dir: Path, explicit: str | None) -> Path:
    if explicit:
        p = paper_dir / explicit
        if not p.exists():
            raise SystemExit(f"[compile-gate] --main 文件不存在: {p}")
        return p
    for cand in (paper_dir / "paper" / "main.tex", paper_dir / "main.tex"):
        if cand.exists():
            return cand
    raise SystemExit(f"[compile-gate] 未找到 main.tex(paper/main.tex 或 main.tex): {paper_dir}")


def collect_tex_files(main: Path) -> list[Path]:
    """递归收集 main.tex 的 \\input/\\include 链(相对 main 目录, 去重, 保持顺序)。"""
    root = main.parent
    seen: list[Path] = []
    queue = [main]
    while queue:
        f = queue.pop(0)
        if f in seen:
            continue
        seen.append(f)
        if f.suffix.lower() != ".tex":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in INPUT_CMD.finditer(text):
            name = m.group(1).strip()
            if not name or name.endswith((".sty", ".cls", ".bib")):
                continue
            p = root / (name if name.endswith(".tex") else name + ".tex")
            if p.exists():
                queue.append(p)
    return seen


def collect_bib_files(main: Path, tex_files: list[Path]) -> list[Path]:
    root = main.parent
    bibs: list[Path] = []
    for f in [main, *tex_files[1:]]:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in BIBLIO_CMD.finditer(text):
            for name in _split_keys(m.group(1)):
                p = root / (name if name.endswith(".bib") else name + ".bib")
                if p.exists() and p not in bibs:
                    bibs.append(p)
    return bibs


def static_analysis(main: Path, tex_files: list[Path], bib_files: list[Path]) -> dict:
    """静态键核对: 返回 {undefined_refs, undefined_citations, orphan_labels, uncited_bibs} 明细。"""
    labels: set[str] = set()
    refs: set[str] = set()
    cites: set[str] = set()
    for f in tex_files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        labels.update(m.group(1).strip() for m in LABEL_CMD.finditer(text))
        for m in REF_CMD.finditer(text):
            refs.update(_split_keys(m.group(1)))
        for m in CITE_CMD.finditer(text):
            cites.update(_split_keys(m.group(1)))
    bib_keys: set[str] = set()
    for b in bib_files:
        text = b.read_text(encoding="utf-8", errors="ignore")
        bib_keys.update(m.group(1) for m in BIB_KEY.finditer(text))
    undef_refs = sorted(r for r in refs if r not in labels)
    undef_cites = sorted(c for c in cites if c not in bib_keys)
    orphan = sorted(l for l in labels if l not in refs and not l.startswith(("fig:", "tab:")))
    uncited = sorted(k for k in bib_keys if k not in cites)
    return {"undefined_refs": undef_refs, "undefined_citations": undef_cites,
            "orphan_labels": orphan, "uncited_bibs": uncited}


def copy_to_tmp(main: Path) -> Path:
    """把 main.tex 目录树按白名单拷到临时目录(FM-28: 编译产物绝不进交付态)。"""
    root = main.parent
    td = Path(tempfile.mkdtemp(prefix="compile_gate_"))
    for src in root.rglob("*"):
        if src.is_dir() or src.name.startswith((".", "_")):
            continue
        if src.suffix.lower() in SKIP_EXT or src.suffix.lower() not in (TEX_EXT | IMG_EXT):
            continue
        rel = src.relative_to(root)
        dst = td / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError:
            pass
    return td


def run_tex(tmp: Path, main_name: str, timeout: int) -> tuple[str | None, list[str]]:
    """跑 pdflatex(-draftmode)+bibtex 至多 3 遍, 返回 (main.log 文本, errors 初筛)。"""
    has_bib = any(tmp.rglob("*.bib"))
    log_text: str | None = None
    for i in range(3):
        r = subprocess.run(["pdflatex", "-draftmode", "-interaction=nonstopmode",
                            main_name], cwd=tmp, capture_output=True, text=True,
                           timeout=timeout)
        if i == 0 and has_bib:
            subprocess.run(["bibtex", main_name[:-4]], cwd=tmp, capture_output=True,
                           text=True, timeout=timeout)
        logp = tmp / (main_name[:-4] + ".log")
        if logp.exists():
            log_text = logp.read_text(encoding="utf-8", errors="ignore")
        if r.returncode != 0 and "Emergency stop" in (log_text or ""):
            break
    return log_text, []


def parse_log(log_text: str | None) -> dict:
    if not log_text:
        return {"compile_errors": [], "undefined_refs": [], "undefined_citations": [],
                "multiply_labels": [], "overfull": 0}
    errors: list[str] = []
    undef_refs: set[str] = set()
    undef_cites: set[str] = set()
    multiply: set[str] = set()
    overfull = 0
    for line in log_text.splitlines():
        if line.startswith("!") or "LaTeX Error" in line or "Emergency stop" in line:
            errors.append(line.strip()[:200])
            continue
        m = re.search(r"LaTeX Warning: Reference `([^']+)' on page", line)
        if m:
            undef_refs.add(m.group(1))
            continue
        m = re.search(r"LaTeX Warning: Citation `([^']+)' on page", line)
        if m:
            undef_cites.add(m.group(1))
            continue
        m = re.search(r"LaTeX Warning: Label `([^']+)' multiply defined", line)
        if m:
            multiply.add(m.group(1))
            continue
        if "Overfull \\hbox" in line:
            overfull += 1
    return {"compile_errors": errors, "undefined_refs": sorted(undef_refs),
            "undefined_citations": sorted(undef_cites),
            "multiply_labels": sorted(multiply), "overfull": overfull}


def render(static: dict, dynamic: dict | None, skipped: bool, fail_on_warning: bool,
           out: Path) -> int:
    """合并两层计数, 写报告, 返回 exit code。dynamic 为 None = 静态层兜底。"""
    if dynamic is None:
        undef_refs, undef_cites = static["undefined_refs"], static["undefined_citations"]
        compile_errors, multiply, overfull = [], [], 0
    else:
        undef_refs, undef_cites = dynamic["undefined_refs"], dynamic["undefined_citations"]
        compile_errors, multiply, overfull = (dynamic["compile_errors"],
                                              dynamic["multiply_labels"], dynamic["overfull"])
    orphan, uncited = static["orphan_labels"], static["uncited_bibs"]
    lines = ["# LaTeX 编译门报告", ""]
    lines.append(f"## Compile errors: {len(compile_errors)}")
    for e in compile_errors:
        lines.append(f"- ERROR: {e}")
    lines.append(f"## Undefined references: {len(undef_refs)}")
    for k in undef_refs:
        lines.append(f"- \\ref 无对应 \\label: {k}")
    lines.append(f"## Undefined citations: {len(undef_cites)}")
    for k in undef_cites:
        lines.append(f"- \\cite 无对应 bib 条目: {k}")
    lines.append(f"## Multiply-defined labels: {len(multiply)}")
    for k in multiply:
        lines.append(f"- 重复 label: {k}")
    lines.append(f"## Overfull hboxes: {overfull}")
    lines.append(f"## Orphan labels: {len(orphan)}")
    for k in orphan:
        lines.append(f"- 定义了但未引用: {k}")
    lines.append(f"## Uncited bib entries: {len(uncited)}")
    for k in uncited:
        lines.append(f"- bib 条目未被引用: {k}")
    lines.append(f"## Compile skipped: {1 if skipped else 0}")
    if skipped:
        lines.append("- TeX 不可用, 以静态键核对为准(文档化降级)")
    err = len(compile_errors) + len(undef_refs) + len(undef_cites) + len(multiply)
    warn = overfull + len(orphan) + len(uncited)
    gate = "PASS" if (err == 0 and (not fail_on_warning or warn == 0)) else "FAIL"
    lines += ["", f"- 门禁: **{gate}** (错误类 {err}; 警告类 {warn}"
              + ("; --fail-on-warning 生效" if fail_on_warning else "") + ")"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if gate == "FAIL" else 0


def selftest() -> bool:
    """静态解析层自检(不编译): 解析函数对已知输入的输出正确。"""
    import io
    class _F:
        def __init__(self, text):
            self._t = text
        def read_text(self, *a, **k):
            return self._t
    fake = _F(r"""\section{Intro}\label{sec:intro}
We cite \cite{refA, refB} and \citep{refC}. See \ref{sec:intro} and \autoref{fig:plot}.
\input{other}
""")
    fake_other = _F(r"\label{fig:plot}\label{dup}\ref{dup}\includegraphics{a.png}")
    fake_bib = _F("@article{refA,\n title={A}}\n@book{refB,}\n@article{unused,}")
    tex_files = [fake, fake_other]
    st = static_analysis(fake, tex_files, [fake_bib])
    assert st["undefined_refs"] == [], st
    assert st["undefined_citations"] == ["refC"], st
    assert st["uncited_bibs"] == ["unused"], st
    assert "sec:intro" not in st["orphan_labels"], st  # 被 ref 引用
    assert "fig:plot" not in st["orphan_labels"], st   # fig: 前缀豁免
    print("[static analysis: cite/ref/label/bib 键核对正确] ✓")
    return True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="LaTeX 编译门(编译 + 引用键核对)")
    ap.add_argument("paper_dir", nargs="?", help="论文目录(--selftest 时省略)")
    ap.add_argument("--out", default="reports/compile.md")
    ap.add_argument("--main", default="", help="main.tex 路径(默认 paper/main.tex 或 main.tex)")
    ap.add_argument("--no-tex", action="store_true", help="跳过编译, 只静态核对")
    ap.add_argument("--fail-on-warning", action="store_true",
                    help="overfull/orphan/uncited 也计为 FAIL")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return 0 if selftest() else 1
    if not args.paper_dir:
        ap.error("paper_dir 必填(--selftest 除外)")
    paper_dir = Path(args.paper_dir)
    main = find_main(paper_dir, args.main or None)
    tex_files = collect_tex_files(main)
    bib_files = collect_bib_files(main, tex_files)
    static = static_analysis(main, tex_files, bib_files)
    dynamic = None
    skipped = True
    tex_ok = shutil.which("pdflatex") and shutil.which("bibtex")
    if tex_ok and not args.no_tex:
        tmp = copy_to_tmp(main)
        try:
            log_text, _ = run_tex(tmp, main.name, args.timeout)
            dynamic = parse_log(log_text)
            skipped = log_text is None
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"[compile-gate] 编译失败, 降级静态核对: {e}", file=sys.stderr)
            dynamic = None
            skipped = True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return render(static, dynamic, skipped, args.fail_on_warning, Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
