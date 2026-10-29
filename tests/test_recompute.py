import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / "results" / "stats.json"


def test_canonical_recompute_matches_committed_stats():
    before = json.loads(STATS.read_text(encoding="utf-8"))
    result = subprocess.run(
        [sys.executable, "analysis.py", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "recompute checks passed: True" in result.stdout
    payload = json.loads(STATS.read_text(encoding="utf-8"))
    assert payload == before
    assert payload["recompute_checks_passed"] is True


def test_headline_cost_ratio_matches_published_descriptive_result():
    descriptive = json.loads(
        (ROOT / "results" / "arxiv_r1_descriptive.json").read_text(encoding="utf-8")
    )
    ratio = descriptive["e2"]["baselines"]["B2_fixed_mid"]["cost_ratio"]
    assert round(ratio, 2) == 3.44
