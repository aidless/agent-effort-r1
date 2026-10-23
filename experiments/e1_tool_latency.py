#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E1 — Real tool-latency profile for an agent loop (CPU-only, zero API budget).

Measures wall-clock latency of the tool primitives a coding/research agent
actually invokes, on the machine that will host the agent loop:

  T1 shell_simple        `/bin/true`                      (process spawn floor)
  T2 shell_command       `/bin/sh -c "sed/grep on file"`  (typical shell tool)
  T3 python_exec         `python3 -c <tiny>`              (interpreter start-up)
  T4 file_read_small     read 4 KiB from local disk
  T5 file_read_medium    read 256 KiB from local disk
  T6 file_write          write 4 KiB + fsync + os.replace (atomic write)
  T7 glob_scan           os.scandir over a 200-file dir
  T8 net_reachable       HTTP GET of a small known-good URL
  T9 net_unreachable     HTTP GET / DNS of RFC-2606 reserved TLD (must fail)
  T10 cpu_kernel         numpy 512x512 matmul (a "compute" step)
  T11 process_spawn_tree spawn 4 workers via multiprocessing (parallel tool fan-out)

Design rules honoured here:
  * >= 30 repetitions per tool (SCHEDULE below), recorded individually.
  * No fabricated latency constants: every number reported downstream comes
    from raw_samples in the output JSON.
  * Failure is first-class: unreachable-network latency AND failure rate are
    reported, never silently dropped.
  * Per-sample records include index so bootstrap CIs are recomputable.

Output: results/e1_tool_latency.json  (raw samples + aggregates + provenance)

Run:  python3 e1_tool_latency.py --out results/e1_tool_latency.json
      python3 e1_tool_latency.py --quick --out /tmp/e1_smoke.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import random
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import numpy as np

SEED = 20260911

# repetitions per tool: >= 30 for every tool; more for the cheap ones
SCHEDULE = {
    "T1_shell_simple": 120,
    "T2_shell_command": 90,
    "T3_python_exec": 60,
    "T4_file_read_small": 200,
    "T5_file_read_medium": 60,
    "T6_file_write_atomic": 90,
    "T7_glob_scan_200": 120,
    "T8_net_reachable": 40,
    "T9_net_unreachable": 40,
    "T10_cpu_kernel": 60,
    "T11_process_spawn_tree": 45,
    "T12_shell_read_verify": 60,
}

NET_REACHABLE_URLS = [
    "https://example.com/",
    "https://www.iana.org/",
]
NET_UNREACHABLE_HOSTS = [
    "nonexistent-host-p2.invalid",
    "no-such-service-p2.test",
]
NET_TIMEOUT_S = 10.0


# --------------------------------------------------------------- helpers ----
def pctl(xs, q):
    return float(np.percentile(np.asarray(xs, dtype=float), q))


def summarize(samples_ms, ok_flags):
    ok = [s for s, f in zip(samples_ms, ok_flags) if f]
    arr = np.asarray(samples_ms, dtype=float)
    n = len(samples_ms)
    n_ok = len(ok)
    out = {
        "n": n,
        "n_ok": n_ok,
        "failure_rate": (n - n_ok) / n if n else None,
        "mean_ms": float(arr.mean()) if n else None,
        "sd_ms": float(arr.std(ddof=1)) if n > 1 else None,
        "var_ms2": float(arr.var(ddof=1)) if n > 1 else None,
        "min_ms": float(arr.min()) if n else None,
        "max_ms": float(arr.max()) if n else None,
        "cv": (float(arr.std(ddof=1)) / float(arr.mean())) if n > 1 and arr.mean() else None,
    }
    for q, name in [(5, "p05"), (25, "p25"), (50, "p50"), (75, "p75"), (90, "p90"), (95, "p95"), (99, "p99")]:
        out[name + "_ms"] = pctl(arr, q) if n else None
    if n_ok > 1:
        a = np.asarray(ok, dtype=float)
        out["mean_ok_ms"] = float(a.mean())
        out["sd_ok_ms"] = float(a.std(ddof=1))
        out["p50_ok_ms"] = pctl(ok, 50)
        out["p95_ok_ms"] = pctl(ok, 95)
    return out


def bootstrap_ci(xs, stat=np.mean, n_boot=4000, alpha=0.05, seed=SEED):
    rng = np.random.default_rng(seed)
    a = np.asarray(xs, dtype=float)
    if a.size < 2:
        return None
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    stats = stat(a[idx], axis=1)
    lo = float(np.percentile(stats, 100 * alpha / 2))
    hi = float(np.percentile(stats, 100 * (1 - alpha / 2)))
    return {"stat": float(stat(a)), "lo": lo, "hi": hi, "n_boot": n_boot, "alpha": alpha}


def timed(fn):
    t0 = time.perf_counter()
    try:
        fn()
        ok = True
    except Exception:
        ok = False
    return (time.perf_counter() - t0) * 1000.0, ok


# --------------------------------------------------------------- workers ----
def _spawn_worker(_):
    x = 0
    for i in range(200_000):
        x += i
    return x


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--quick", action="store_true", help="tiny schedule for smoke tests")
    args = ap.parse_args()
    if args.quick:
        for k in SCHEDULE:
            SCHEDULE[k] = 6

    random.seed(SEED)
    workdir = tempfile.mkdtemp(prefix="p2_e1_")
    small = os.path.join(workdir, "small.txt")
    medium = os.path.join(workdir, "medium.txt")
    globdir = os.path.join(workdir, "glob200")
    os.makedirs(globdir, exist_ok=True)
    with open(small, "w") as fh:
        fh.write("abcdefghij" * 400)  # 4 KiB
    with open(medium, "w") as fh:
        fh.write("0123456789" * 26215)  # ~256 KiB
    for i in range(200):
        with open(os.path.join(globdir, "f_%03d.dat" % i), "w") as fh:
            fh.write("x" * 100)

    results = {}
    raw = {}

    def record(name, sample_ms, ok):
        results.setdefault(name, {"samples_ms": [], "ok": []})
        results[name]["samples_ms"].append(round(sample_ms, 4))
        results[name]["ok"].append(bool(ok))

    # T1 shell_simple
    for _ in range(SCHEDULE["T1_shell_simple"]):
        ms, ok = timed(lambda: subprocess.run(["/bin/true"], check=True, capture_output=True))
        record("T1_shell_simple", ms, ok)

    # T2 shell_command: grep-ish read over the 200-file dir
    cmd = ["/bin/sh", "-c", "grep -rl 'xxxxxxxxxx' %s | wc -l" % globdir]
    for _ in range(SCHEDULE["T2_shell_command"]):
        ms, ok = timed(lambda: subprocess.run(cmd, check=True, capture_output=True))
        record("T2_shell_command", ms, ok)

    # T3 python_exec
    for _ in range(SCHEDULE["T3_python_exec"]):
        ms, ok = timed(
            lambda: subprocess.run(
                [sys.executable, "-c", "import json,sys; sys.stdout.write(json.dumps({'n':1}))"],
                check=True,
                capture_output=True,
            )
        )
        record("T3_python_exec", ms, ok)

    # T4 / T5 file reads
    def r_small():
        with open(small, "rb") as fh:
            fh.read()

    def r_medium():
        with open(medium, "rb") as fh:
            fh.read()

    for _ in range(SCHEDULE["T4_file_read_small"]):
        record("T4_file_read_small", *timed(r_small))
    for _ in range(SCHEDULE["T5_file_read_medium"]):
        record("T5_file_read_medium", *timed(r_medium))

    # T6 atomic write
    target = os.path.join(workdir, "atomic.txt")

    def w_atomic():
        tmp = target + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(b"y" * 4096)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

    for _ in range(SCHEDULE["T6_file_write_atomic"]):
        record("T6_file_write_atomic", *timed(w_atomic))

    # T7 glob scan
    def scan():
        n = 0
        with os.scandir(globdir) as it:
            for e in it:
                if e.is_file():
                    n += 1
        assert n == 200, n

    for _ in range(SCHEDULE["T7_glob_scan_200"]):
        record("T7_glob_scan_200", *timed(scan))

    # T8 / T9 network
    def get_ok():
        url = random.choice(NET_REACHABLE_URLS)
        req = urllib.request.Request(url, headers={"User-Agent": "p2-e1-latency-probe"})
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT_S) as resp:
            resp.read(2048)
            assert resp.status == 200

    def get_fail():
        host = random.choice(NET_UNREACHABLE_HOSTS)
        req = urllib.request.Request("https://%s/" % host, headers={"User-Agent": "p2-e1"})
        urllib.request.urlopen(req, timeout=NET_TIMEOUT_S)

    for _ in range(SCHEDULE["T8_net_reachable"]):
        record("T8_net_reachable", *timed(get_ok))
    for _ in range(SCHEDULE["T9_net_unreachable"]):
        record("T9_net_unreachable", *timed(get_fail))

    # T10 cpu kernel
    A = np.random.default_rng(SEED).standard_normal((512, 512))
    B = np.random.default_rng(SEED + 1).standard_normal((512, 512))
    for _ in range(SCHEDULE["T10_cpu_kernel"]):
        record("T10_cpu_kernel", *timed(lambda: A @ B))

    # T11 parallel fan-out
    for _ in range(SCHEDULE["T11_process_spawn_tree"]):
        def fan(n_workers=4):
            with mp.Pool(n_workers) as pool:
                pool.map(_spawn_worker, range(n_workers))

        record("T11_process_spawn_tree", *timed(fan))

    # T12 read-tool call WITH correctness verification: a tool call is only
    # "successful" if it returns the right answer, not merely if it exits 0.
    # Half the invocations ask a query with no match (correct answer = 0); if a
    # tool returns a wrong-but-non-empty result the call is a semantic failure.
    sentinel = "SENTINEL_%d" % random.randrange(10**6)

    def read_verify():
        want_match = random.random() < 0.5
        pattern = "xxxxxxxxxx" if want_match else sentinel
        # grep exits 1 when nothing matches -> that is an EXPECTED outcome, not
        # a tool failure; the correctness assertion below is what defines
        # success for a read tool.
        res = subprocess.run(
            ["/bin/sh", "-c", "grep -rl '%s' %s | wc -l" % (pattern, globdir)],
            capture_output=True,
            text=True,
        )
        got = int(res.stdout.strip())
        expected = 200 if want_match else 0
        assert got == expected, "want %d got %d" % (expected, got)

    for _ in range(SCHEDULE["T12_shell_read_verify"]):
        record("T12_shell_read_verify", *timed(read_verify))

    # aggregate
    n_cores = os.cpu_count()
    aggregates = {}
    for name, rec in results.items():
        s = summarize(rec["samples_ms"], rec["ok"])
        ok_samples = [x for x, f in zip(rec["samples_ms"], rec["ok"]) if f]
        s["bootstrap_mean_ci95"] = bootstrap_ci(ok_samples if len(ok_samples) >= 2 else rec["samples_ms"])
        aggregates[name] = s
        raw[name] = {
            "samples_ms": rec["samples_ms"],
            "ok": rec["ok"],
            "n_expected": SCHEDULE[name],
        }

    doc = {
        "experiment": "E1_tool_latency_profile",
        "seed": SEED,
        "generated_by": "experiments/e1_tool_latency.py",
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "n_cpu": n_cores,
            "numpy": np.__version__,
            "hostname": socket.gethostname(),
        },
        "schedule": SCHEDULE,
        "aggregates": aggregates,
        "raw": raw,
        "notes": [
            "latency in ms, wall clock, per-invocation",
            "failure_rate is reported for every tool; unreachable network is a first-class case",
            "all downstream cost models must read aggregates[*].mean_ok_ms or p50/p95 from this file",
        ],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print("host: %s cpus=%d python=%s" % (socket.gethostname(), n_cores, platform.python_version()))
    hdr = "%-24s %6s %8s %9s %9s %9s %8s" % ("tool", "n", "fail", "mean_ms", "p50_ms", "p95_ms", "cv")
    print(hdr)
    for name in SCHEDULE:
        a = aggregates[name]
        print(
            "%-24s %6d %8.3f %9.3f %9.3f %9.3f %8.3f"
            % (name, a["n"], a["failure_rate"], a["mean_ms"], a["p50_ms"], a["p95_ms"], a["cv"] or 0.0)
        )
    print("wrote", args.out)
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
