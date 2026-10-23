#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E1b — Measured cost primitives for the AGENT-specific effort axes (CPU-only).

E1 profiled generic shell/file/net primitives. E2 additionally needs honest
cost constants for three agent-specific actions whose latency the V4.1-Flash
report never publishes:

  P1 image_codec_png   encode+decode a 1280x720 RGB frame (vision axis unit)
  P2 screenshot_capture screen grab attempt; if the host is headless this is a
                       DOCUMENTED FAILURE, reported as such (never silently
                       replaced by a made-up constant)
  P3 test_run_small    run pytest on a 3-test toy repo in a subprocess
                       (verification-turn unit)
  P4 local_http_search loopback HTTP query against a stdlib http.server index
                       over 500 documents (search-tool unit, network-free)
  P5 patch_apply       apply a small unified diff to a file and fsync
  P6 json_tool_call    invoke a JSON-emitting CLI tool and parse stdout

>= 30 repetitions each, per-invocation wall clock, failure recorded.

Output: results/e1b_agent_primitives.json
Run:    python3 e1b_agent_primitives.py --out results/e1b_agent_primitives.json
"""

from __future__ import annotations

import argparse
import http.server
import io
import json
import os
import platform
import random
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import numpy as np

SEED = 20260911
SCHEDULE = {
    "P1_image_codec_png": 60,
    "P2_screenshot_capture": 30,
    "P3_test_run_small": 30,
    "P4_local_http_search": 60,
    "P5_patch_apply": 60,
    "P6_json_tool_call": 60,
}


def pctl(xs, q):
    return float(np.percentile(np.asarray(xs, dtype=float), q))


def summarize(samples_ms, ok_flags):
    ok = [s for s, f in zip(samples_ms, ok_flags) if f]
    arr = np.asarray(samples_ms, dtype=float)
    out = {
        "n": len(samples_ms),
        "n_ok": len(ok),
        "failure_rate": (len(samples_ms) - len(ok)) / len(samples_ms) if samples_ms else None,
        "mean_ms": float(arr.mean()),
        "sd_ms": float(arr.std(ddof=1)) if len(arr) > 1 else None,
        "var_ms2": float(arr.var(ddof=1)) if len(arr) > 1 else None,
        "min_ms": float(arr.min()),
        "max_ms": float(arr.max()),
        "cv": (float(arr.std(ddof=1)) / float(arr.mean())) if len(arr) > 1 and arr.mean() else None,
    }
    for q, name in [(5, "p05"), (25, "p25"), (50, "p50"), (75, "p75"), (90, "p90"), (95, "p95"), (99, "p99")]:
        out[name + "_ms"] = pctl(arr, q)
    if len(ok) > 1:
        a = np.asarray(ok, dtype=float)
        out["mean_ok_ms"] = float(a.mean())
        out["sd_ok_ms"] = float(a.std(ddof=1))
        out["p50_ok_ms"] = pctl(ok, 50)
        out["p95_ok_ms"] = pctl(ok, 95)
    return out


def bootstrap_ci(xs, n_boot=4000, alpha=0.05, seed=SEED):
    rng = np.random.default_rng(seed)
    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return None
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    stats = a[idx].mean(axis=1)
    return {
        "stat": float(a.mean()),
        "lo": float(np.percentile(stats, 100 * alpha / 2)),
        "hi": float(np.percentile(stats, 100 * (1 - alpha / 2))),
        "n_boot": n_boot,
        "alpha": alpha,
    }


def timed(fn):
    t0 = time.perf_counter()
    try:
        fn()
        ok = True
        err = None
    except Exception as e:  # failure is first-class evidence
        ok = False
        err = "%s: %s" % (type(e).__name__, e)
    return (time.perf_counter() - t0) * 1000.0, ok, err


class _IndexHandler(http.server.BaseHTTPRequestHandler):
    docs = []

    def do_GET(self):  # noqa: N802
        q = self.path.split("q=")[-1].replace("+", " ").lower()
        hits = [d for d in self.docs if q in d][:5]
        body = json.dumps({"n_hits": len(hits), "hits": hits}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    if args.quick:
        for k in SCHEDULE:
            SCHEDULE[k] = 5

    random.seed(SEED)
    work = tempfile.mkdtemp(prefix="p2_e1b_")
    results = {}

    def record(name, ms, ok, err=None):
        results.setdefault(name, {"samples_ms": [], "ok": [], "errors": []})
        results[name]["samples_ms"].append(round(ms, 4))
        results[name]["ok"].append(bool(ok))
        if err:
            results[name]["errors"].append(err[:200])

    # ---- P1 image codec --------------------------------------------------
    from PIL import Image

    rng = np.random.default_rng(SEED)
    frame = Image.fromarray(rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8))

    for _ in range(SCHEDULE["P1_image_codec_png"]):
        def codec():
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            buf.seek(0)
            im = Image.open(buf)
            im.load()

        ms, ok, err = timed(codec)
        record("P1_image_codec_png", ms, ok, err)

    # ---- P2 screenshot ---------------------------------------------------
    for _ in range(SCHEDULE["P2_screenshot_capture"]):
        def shot():
            try:
                import mss  # type: ignore

                with mss.mss() as sct:
                    sct.grab(sct.monitors[0])
                return
            except Exception:
                pass
            # fall back to a real X11/Wayland grab attempt if DISPLAY is set
            if os.environ.get("DISPLAY"):
                subprocess.run(["import", "-window", "root", os.path.join(work, "s.png")], check=True,
                               capture_output=True, timeout=20)
                return
            raise RuntimeError("headless host: no mss and no DISPLAY for a real screen grab")

        record("P2_screenshot_capture", *timed(shot))

    # ---- P3 small test run ----------------------------------------------
    # The runner is auto-selected: pytest when importable on the host, else
    # unittest. Both are real test runners; the choice is recorded in the
    # output so the constant is never misattributed to a runner that is absent.
    repo = os.path.join(work, "toy_repo")
    os.makedirs(repo, exist_ok=True)
    with open(os.path.join(repo, "mod.py"), "w") as fh:
        fh.write("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    have_pytest = subprocess.run(
        [sys.executable, "-c", "import pytest"], capture_output=True
    ).returncode == 0
    if have_pytest:
        with open(os.path.join(repo, "test_mod.py"), "w") as fh:
            fh.write(
                "from mod import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n"
                "def test_mul():\n    assert mul(2, 3) == 6\n\n"
                "def test_add_neg():\n    assert add(-1, 1) == 0\n"
            )
        test_cmd = [sys.executable, "-m", "pytest", "-q", "test_mod.py"]
    else:
        with open(os.path.join(repo, "test_mod.py"), "w") as fh:
            fh.write(
                "import unittest\nfrom mod import add, mul\n\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
                "    def test_mul(self):\n        self.assertEqual(mul(2, 3), 6)\n\n"
                "    def test_add_neg(self):\n        self.assertEqual(add(-1, 1), 0)\n\n\n"
                "if __name__ == '__main__':\n    unittest.main(verbosity=0)\n"
            )
        test_cmd = [sys.executable, "test_mod.py"]

    for _ in range(SCHEDULE["P3_test_run_small"]):
        def run_tests():
            r = subprocess.run(test_cmd, cwd=repo, capture_output=True, timeout=300)
            if r.returncode == 5:
                raise RuntimeError("no tests collected")
            assert r.returncode == 0, r.stdout.decode()[-300:]

        record("P3_test_run_small", *timed(run_tests))

    # ---- P4 loopback http search ----------------------------------------
    _IndexHandler.docs = ["doc%04d about topic %d" % (i, i % 37) for i in range(500)]
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _IndexHandler)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base = "http://127.0.0.1:%d/search?q=" % port
    for _ in range(SCHEDULE["P4_local_http_search"]):
        def search():
            q = "topic+%d" % random.randrange(37)
            with urllib.request.urlopen(base + q, timeout=10) as r:
                data = json.loads(r.read().decode())
            assert data["n_hits"] >= 1

        record("P4_local_http_search", *timed(search))

    # ---- P5 patch apply --------------------------------------------------
    src = os.path.join(work, "patchme.py")
    patch = os.path.join(work, "p.patch")
    with open(patch, "w") as fh:
        fh.write(
            "--- a/patchme.py\n+++ b/patchme.py\n@@ -1,2 +1,2 @@\n-def f(x):\n-    return x\n+def f(x):\n+    return x + 1\n"
        )
    for i in range(SCHEDULE["P5_patch_apply"]):
        with open(src, "w") as fh:
            fh.write("def f(x):\n    return x\n")

        def apply_patch():
            r = subprocess.run(["patch", "-p1", "-i", patch, "-o", src + ".out", src],
                               capture_output=True, timeout=60)
            assert r.returncode == 0, r.stderr.decode()[-200:]
            with open(src + ".out", "rb") as fh:
                fh.read()

        record("P5_patch_apply", *timed(apply_patch))

    # ---- P6 json tool call ----------------------------------------------
    tool = os.path.join(work, "tool.py")
    with open(tool, "w") as fh:
        fh.write("import json,sys;print(json.dumps({'ok':True,'n':len(sys.argv)-1}))\n")
    for _ in range(SCHEDULE["P6_json_tool_call"]):
        def call_tool():
            r = subprocess.run([sys.executable, tool, "a", "b"], capture_output=True, timeout=60)
            assert r.returncode == 0
            assert json.loads(r.stdout.decode())["ok"] is True

        record("P6_json_tool_call", *timed(call_tool))

    httpd.shutdown()

    aggregates, raw = {}, {}
    for name, rec in results.items():
        s = summarize(rec["samples_ms"], rec["ok"])
        s["n_errors"] = len(rec["errors"])
        s["sample_errors"] = rec["errors"][:3]
        ok_samples = [x for x, f in zip(rec["samples_ms"], rec["ok"]) if f]
        s["bootstrap_mean_ci95"] = bootstrap_ci(ok_samples if len(ok_samples) >= 2 else rec["samples_ms"])
        aggregates[name] = s
        raw[name] = {"samples_ms": rec["samples_ms"], "ok": rec["ok"]}

    doc = {
        "experiment": "E1b_agent_primitives",
        "seed": SEED,
        "generated_by": "experiments/e1b_agent_primitives.py",
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "hostname": socket.gethostname(),
            "display_set": bool(os.environ.get("DISPLAY")),
            "cpus": os.cpu_count(),
        },
        "schedule": SCHEDULE,
        "test_runner": "pytest" if have_pytest else "unittest",
        "aggregates": aggregates,
        "raw": raw,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("host=%s display=%s" % (socket.gethostname(), os.environ.get("DISPLAY")))
    print("%-24s %5s %6s %10s %10s %10s %8s" % ("tool", "n", "fail", "mean_ms", "p50_ms", "p95_ms", "cv"))
    for k in SCHEDULE:
        a = aggregates[k]
        print("%-24s %5d %6.3f %10.3f %10.3f %10.3f %8.3f"
              % (k, a["n"], a["failure_rate"], a["mean_ms"], a["p50_ms"], a["p95_ms"], a["cv"] or 0.0))
    for k, a in aggregates.items():
        if a["failure_rate"]:
            print("  [expected-failure evidence] %s: %s" % (k, a["sample_errors"][:1]))
    print("wrote", args.out)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
