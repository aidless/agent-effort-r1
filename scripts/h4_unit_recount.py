#!/usr/bin/env python3
"""Unit-level (independent-(task,menu)) recount of the H4 paired contrasts.

Why this exists: the manuscript's pseudo-replication rule (Table 4 caption; Sec. 5.4) says a
contrast must be reported on the 16 independent (task, menu) units, because each level's 48
records are those 16 units times three deterministic repeats. The released
`h4_derived_stats*.json` files carry unit-level recounts for the 8B artifacts only, so the
14B arm was being quoted in its record-level form. This script recounts both arms from their
raw artifacts and writes one JSON so the claim has a carrier.

Post-hoc for the 2026-10-10 revision: nothing here was preregistered, and no new episode was
run. Input = the released records; output = counts and an exact two-sided sign test.
Usage: python3 scripts/h4_unit_recount.py [--out results/h4_unit_recount.json]
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from math import comb
from pathlib import Path

LEGS = {
    "8B":  ("results/h4_real_llm_gx_qwen3_8b_persist.json",  "iso"),
    "14B": ("results/h4_real_llm_gx_qwen3_14b_persist.json", "iso"),
}
CONTRASTS = [("L1_low", "L4_max"), ("L2_mid", "L3_high"), ("L2_mid", "L4_max")]


def exact_sign_p(worse: int, better: int) -> float:
    """Two-sided exact binomial (McNemar) on discordant pairs."""
    n = worse + better
    if n == 0:
        return 1.0
    return min(1.0, sum(comb(n, i) for i in range(0, min(worse, better) + 1)) * 2 / 2 ** n)


def records_of(path: Path, arm: str) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in data["records"] if r.get("arm") == arm]


def curve(recs: list[dict], level: str) -> dict:
    return {(r["task"], r["menu"]): bool(r["success"]) for r in recs if r["level"] == level}


def record_pairs(recs: list[dict], level: str) -> dict:
    return {(r["task"], r["menu"], r.get("repeat")): bool(r["success"])
            for r in recs if r["level"] == level}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/h4_unit_recount.json")
    a = ap.parse_args()
    root = Path.cwd()
    out = {"generated_by": "scripts/h4_unit_recount.py",
           "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "kind": "post-hoc unit-level recount for the 2026-10-10 revision; no new episodes",
           "unit_definition": "one (task, menu) pair; 48 records per level = 16 units x 3 repeats",
           "statistic": "exact two-sided binomial (sign test) on discordant units",
           "legs": {}}
    for tag, (rel, arm) in LEGS.items():
        # H4_ARM exists so the negative control (a filter that selects nothing) can be run
        # against this script without editing it; it must fail, never print zeros.
        arm = os.environ.get("H4_ARM", arm)
        p = root / rel
        if not p.is_file():
            print(f"FAIL missing leg: {rel}", file=sys.stderr)
            return 1
        recs = records_of(p, arm)
        # Fail closed on an empty or mis-shaped selection: a wrong filter here would print a
        # clean-looking 0w/0b instead of an error.
        if not recs:
            all_arms = sorted({str(r.get("arm")) for r in
                               json.loads(p.read_text(encoding="utf-8"))["records"]})
            print(f"FAIL no records for {rel} arm={arm!r}; arms present: {all_arms}",
                  file=sys.stderr)
            return 1
        leg = {"source_result": rel,
               "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
               "n_records_arm": len(recs), "contrasts": []}
        for lo, hi in CONTRASTS:
            ulo, uhi = curve(recs, lo), curve(recs, hi)
            rlo, rhi = record_pairs(recs, lo), record_pairs(recs, hi)
            units = sorted(set(ulo) & set(uhi))
            if len(units) != 16:
                print(f"FAIL {tag} {lo}->{hi}: expected 16 independent (task, menu) units, "
                      f"got {len(units)} -- denominator of the claim is wrong", file=sys.stderr)
                return 1
            w = sum(1 for k in units if ulo[k] and not uhi[k])
            b = sum(1 for k in units if uhi[k] and not ulo[k])
            rp = sorted(set(rlo) & set(rhi))
            rw = sum(1 for k in rp if rlo[k] and not rhi[k])
            rb = sum(1 for k in rp if rhi[k] and not rlo[k])
            varying = sum(1 for k in units
                          if len({rlo.get((k[0], k[1], rep)) for rep in
                                  {t[2] for t in rp if (t[0], t[1]) == k}} - {None}) > 1)
            leg["contrasts"].append({
                "from": lo, "to": hi, "units": len(units),
                "units_worse": w, "units_better": b, "units_tie": len(units) - w - b,
                "p_units": exact_sign_p(w, b),
                "records": len(rp), "records_worse": rw, "records_better": rb,
                "records_tie": len(rp) - rw - rb, "p_records": exact_sign_p(rw, rb),
                "units_varying_across_repeats": varying})
        out["legs"][tag] = leg
    # Flat block so a claim row can bind to leaf field names (the ledger binder resolves
    # `file -> a.b[0].c`; deep list indices are easy to mistype, flat leaves are not).
    flat = {}
    for tag, leg in out["legs"].items():
        key = tag.replace("B", "b")  # 8B -> 8b, 14B -> 14b
        for c in leg["contrasts"]:
            pair = f"{c['from'].split('_')[0]}_{c['to'].split('_')[0]}"
            for stat, val in (("w", c["units_worse"]), ("b", c["units_better"]),
                              ("p", round(c["p_units"], 4)),
                              ("n_units", c["units"]),
                              ("rw", c["records_worse"]), ("rb", c["records_better"]),
                              ("rp", round(c["p_records"], 4))):
                flat[f"u{key}_{pair}_{stat}"] = val
        flat[f"u{key}_varying_units"] = max(c["units_varying_across_repeats"]
                                           for c in leg["contrasts"])
    out["flat"] = flat
    dest = root / a.out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for tag, leg in out["legs"].items():
        for c in leg["contrasts"]:
            print(f"{tag} {c['from']}->{c['to']}: units {c['units_worse']}w/{c['units_better']}b "
                  f"p={c['p_units']:.4f} | records {c['records_worse']}w/{c['records_better']}b "
                  f"p={c['p_records']:.4f} | units_varying {c['units_varying_across_repeats']}")
    print(f"written {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
