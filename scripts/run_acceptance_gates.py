"""paper-writing-agent: reusable acceptance-gate runner.

Config-driven gate checks (JSON):
  {"checks": [
     {"type": "file_exists", "name": "...", "path": "main.tex"},
     {"type": "hash_matches", "name": "...", "path": "main.pdf", "sha256": "..."},
     {"type": "stale_marker_absent", "name": "...", "path": "main.tex", "markers": ["35.4", "0.218"]},
     {"type": "script_runs", "name": "...", "cmd": ["python", "verify.py"], "cwd": "."},
     {"type": "json_value_equals", "name": "...", "path": "results.json", "jsonpath": "a.b", "value": 0.5},
     {"type": "zip_entries_include", "name": "...", "path": "pkg.zip", "entries": ["scripts/x.py"]}
  ]}

Optional per-check semantics:
  "expected_fail": true, "expected_reason": "..."  — 设计性阻断标注(如 D3 证据未产出、
  D4 写作被阶段门阻断)。仅影响报告标注(FAIL(expected))、历史 expected 字段与
  gate_reflection 的卡死检测(忽略 expected 门);退出码语义不变: 任何 FAIL(含
  expected)仍 exit 1——禁止用 expected_fail 掩盖真实缺陷。

Usage: python run_acceptance_gates.py gates_config.json
Relative paths in the config (including script_runs "cwd") resolve against the
config's own directory, so the runner works from any cwd.
Exit 0 = all PASS; exit 1 = at least one FAIL.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys, time, zipfile
from pathlib import Path

def get_jp(obj, jp: str):
    for part in jp.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
                continue
            except (ValueError, IndexError, TypeError):
                return None
        obj = obj[part]
    return obj

def run_check(c, base: Path, expected: bool = False):
    t = c.get("type")
    name = c.get("name", t)
    def p(path: str) -> Path:
        pp = Path(path)
        return pp if pp.is_absolute() else base / pp
    try:
        if t == "file_exists":
            ok = p(c["path"]).exists()
        elif t == "hash_matches":
            pp = p(c["path"])
            ok = pp.exists() and hashlib.sha256(pp.read_bytes()).hexdigest().lower() == c["sha256"].lower()
        elif t == "stale_marker_absent":
            pp = p(c["path"])
            text = pp.read_text(encoding="utf-8", errors="ignore") if pp.exists() else ""
            ok = all(m not in text for m in c["markers"])
        elif t == "script_runs":
            r = subprocess.run(c["cmd"], cwd=p(c.get("cwd", ".")), capture_output=True, timeout=c.get("timeout", 300))
            ok = r.returncode == 0
        elif t == "json_value_equals":
            pp = p(c["path"])
            data = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else None
            ok = data is not None and get_jp(data, c["jsonpath"]) == c["value"]
        elif t == "zip_entries_include":
            with zipfile.ZipFile(p(c["path"])) as z:
                names = set(z.namelist())
            ok = all(e in names for e in c["entries"])
        else:
            ok, name = False, f"UNKNOWN({t})"
    except Exception as exc:
        ok, name = False, f"{name} :: {exc}"
    if ok:
        print(f"PASS {name}")
    elif expected:
        # expected_fail (L1-1/L2 语义化): 设计性阻断——外部输入缺失导致的 FAIL,
        # 仅影响标注与反思回路, 不影响退出码(防自游戏: 任何 FAIL 仍 exit 1)。
        print(f"FAIL(expected) {name} :: {c.get('expected_reason', 'expected failure')}")
    else:
        print(f"FAIL {name}")
    return ok

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", help="gates_config.json (--selftest ignores)")
    ap.add_argument("--report", default="", help="将运行报告(含配置哈希)写入 JSON 文件")
    ap.add_argument("--record", default="", help="追加一行到 gate 历史 JSONL(供 gate_reflection.py 检测连续失败)")
    ap.add_argument("--selftest", action="store_true", help="run selftest and exit")
    args = ap.parse_args()

    if args.selftest:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "x.txt").write_text("hello", encoding="utf-8")
            cfg = {"checks": [
                {"type": "file_exists", "name": "present", "path": "x.txt"},
                {"type": "file_exists", "name": "absent", "path": "nope.txt"},
            ]}
            cfg_path = base / "gates.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            from run_acceptance_gates import run_check as _rc
            ok1, ok2 = False, False
            try:
                # 直接调用核心检查
                c1 = cfg["checks"][0]
                ok1 = _rc(c1, base)
            except Exception:
                pass
            try:
                c2 = cfg["checks"][1]
                ok2 = _rc(c2, base)
            except Exception:
                ok2 = False  # 文件不存在 -> False
            ok = ok1 is True and ok2 is False
            print(f"selftest: file_exists present={ok1} absent={ok2}: "
                  f"{'PASS' if ok else 'FAIL'}")
            return 0 if ok else 1

    if not args.config:
        ap.error("config required (or use --selftest)")
    cfg_path = Path(args.config)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # 运行身份:配置哈希(契约纪律)——防"换了配置仍报旧 PASS"
    cfg_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()
    # Relative paths in the config resolve against the config's own directory,
    # so the runner works from any cwd.
    base = cfg_path.resolve().parent
    details = []
    for c in cfg["checks"]:
        name = c.get("name", c.get("type"))
        exp = bool(c.get("expected_fail", False))
        try:
            ok = run_check(c, base, expected=exp)
        except Exception as exc:  # noqa: BLE001
            ok, name = False, f"{name} :: {exc}"
        details.append({"name": name, "passed": bool(ok), "expected": exp,
                        "expected_reason": c.get("expected_reason") if exp else None})
    summary = {"config": str(cfg_path), "config_sha256": cfg_hash,
               "n_checks": len(details), "n_pass": sum(1 for d in details if d["passed"]),
               "n_expected_fail": sum(1 for d in details if d["expected"] and not d["passed"]),
               "all_pass": all(d["passed"] for d in details), "checks": details}
    total_pass = summary["n_pass"]
    print(f"\nTOTAL: {total_pass}/{summary['n_checks']} PASS  (config_sha256={cfg_hash[:12]}…)")
    if summary["n_expected_fail"]:
        print(f"(expected failures: {summary['n_expected_fail']} — 设计性阻断, 退出码语义不变)")
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"report -> {out}")
    if args.record:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "config_sha256": cfg_hash,
               "n_checks": summary["n_checks"], "n_pass": summary["n_pass"],
               "all_pass": summary["all_pass"], "checks": details}
        hist = Path(args.record)
        hist.parent.mkdir(parents=True, exist_ok=True)
        with hist.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"recorded -> {hist}")
    return 0 if summary["all_pass"] else 1

if __name__ == "__main__":
    sys.exit(main())