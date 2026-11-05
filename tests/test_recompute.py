import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / "results" / "stats.json"
COUNT_LINE = re.compile(
    r"Counts checked by tests/test_recompute.py: "
    r"pytest=(\d+), analysis.py inputs=(\d+), "
    r"scripts/recompute_arxiv_r1.py inputs=(\d+)\. "
    r"CI runs `pytest -q tests`\."
)
DESCRIPTIVE_TARGETS = (
    "results/arxiv_r1_descriptive.json",
    "paper/tables/curves.tex",
    "paper/tables/tasks.tex",
    "paper/tables/allocation.tex",
    "paper/tables/latency.tex",
    "paper/tables/axis.tex",
)
AUTHOR_PATH_NEEDLES = (
    "/" + "home" + "/",
    "/" + "Users" + "/",
    "C:" + "\\Users",
    "C:" + "/Users",
    "F:" + "\\deepseek",
    "F:" + "/deepseek",
)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
SKIP_SUFFIXES = {".png", ".pdf", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".pyc"}


def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, float):
        return round(value, 12)
    return value


def _pytest_functions():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def _analysis_inputs():
    text = (ROOT / "analysis.py").read_text(encoding="utf-8")
    match = re.search(r"for f in \[(.*?)\]", text, re.S)
    assert match, "analysis.py input list not found"
    return re.findall(r'"([^"]+\.json)"', match.group(1))


def _descriptive_inputs():
    path = ROOT / "scripts" / "recompute_arxiv_r1.py"
    spec = importlib.util.spec_from_file_location("recompute_arxiv_r1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.INPUTS)


def test_canonical_recompute_matches_committed_stats():
    original = STATS.read_bytes()
    before = json.loads(original)
    try:
        result = subprocess.run(
            [sys.executable, "analysis.py", "."],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "recompute checks passed: True" in result.stdout
        payload = json.loads(STATS.read_text(encoding="utf-8"))
        assert normalize(payload) == normalize(before)
        assert payload["recompute_checks_passed"] is True
    finally:
        # SciPy's Clopper-Pearson tail digits are not bit-stable. The contract is
        # 12 decimal places, so the retained file is restored rather than replaced.
        STATS.write_bytes(original)


def test_headline_cost_ratio_matches_published_descriptive_result():
    descriptive = json.loads(
        (ROOT / "results" / "arxiv_r1_descriptive.json").read_text(encoding="utf-8")
    )
    ratio = descriptive["e2"]["baselines"]["B2_fixed_mid"]["cost_ratio"]
    assert round(ratio, 2) == 3.44


def test_six_file_descriptive_recompute_matches_committed():
    before = {rel: (ROOT / rel).read_bytes() for rel in DESCRIPTIVE_TARGETS}
    result = subprocess.run(
        [sys.executable, "scripts/recompute_arxiv_r1.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Validated six retained result files" in result.stdout
    for rel, blob in before.items():
        assert (ROOT / rel).read_bytes() == blob, rel


def test_documented_counts_match_code_and_ci():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = COUNT_LINE.search(readme)
    assert match, "README count line missing or drifted"
    n_pytest, n_analysis, n_desc = (int(group) for group in match.groups())
    assert len(_pytest_functions()) == n_pytest
    analysis_inputs = _analysis_inputs()
    descriptive_inputs = _descriptive_inputs()
    assert len(analysis_inputs) == n_analysis
    assert len(descriptive_inputs) == n_desc
    assert analysis_inputs == descriptive_inputs[:n_analysis]
    workflow = (ROOT / ".github/workflows/static-checks.yml").read_text(encoding="utf-8")
    run_steps = [line.strip() for line in workflow.splitlines() if line.strip() == "pytest -q tests"]
    assert run_steps == ["pytest -q tests"]
    assert "does not install third-party" not in workflow
    assert "numpy==2.2.6" in workflow and "scipy==1.15.3" in workflow
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "not needed to recompute" not in requirements
    assert "analysis.py imports numpy and scipy" in requirements


def test_readme_labels_hypothesis_measurement_and_gaps():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# ")
    body = lines[1:]
    while body and not body[0].strip():
        body = body[1:]
    problem = []
    for line in body:
        if not line.strip() or line.startswith("#"):
            break
        problem.append(line)
    assert 1 <= len(problem) <= 3
    text = "\n".join(lines)
    assert "## Hypothesis" in text
    assert "## Measurement" in text
    assert "3326b513fa891cbd99e8c1ffcd986bd27d9dac73fd75dc7a3a31c0993db3f9e8" in text
    assert "7e2d56e7195074ab7c856d18054f59bf8e8557e1e89f90d39be879667adec157" in text
    assert "written programs" in text
    assert "FAILURE_MODES.md" in text
    assert "scripts/recompute_arxiv_r1.py" in text
    assert "analysis.py" in text
    assert ("shields" + ".io") not in text
    assert ("[" + "![") not in text


def test_failure_modes_blocks_ratio_misreading():
    text = (ROOT / "FAILURE_MODES.md").read_text(encoding="utf-8")
    assert "FM-RATIO" in text
    assert "3.44" in text
    assert "3.4402002147712176" in text
    assert "not a measured" in text
    assert "deployment saving" in text
    assert "3326b513fa891cbd99e8c1ffcd986bd27d9dac73fd75dc7a3a31c0993db3f9e8" in text


def test_no_author_absolute_paths_or_fake_badges():
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in AUTHOR_PATH_NEEDLES:
            if needle in text:
                hits.append(f"{path.relative_to(ROOT)} contains an author path")
                break
        if ("shields" + ".io") in text or ("[" + "![") in text:
            hits.append(f"{path.relative_to(ROOT)} contains a status badge")
    assert hits == []
