#!/usr/bin/env python3
r"""A9 decision rules, applied to the replication artifact when it lands.

Registered in evidence/protocol.md as A9 (2026-09-24 02:59Z), before the run. This script
is the mechanical half of that registration: it takes the axis-arm replication
(repeats=12, same model/tasks/menus/seed derivation), runs the SAME identifiability code the
paper already uses (experiments/h4_derived_stats.py, threshold 0.30 from
`identifiability_max_ci_width`), and then prints one line per pre-declared rule:

  rule 1  a gain becomes quotable when its CI width <= 0.30
  rule 2  if all three widths stay > 0.30 the answer is "not identifiable at this
          resolution" and sampling stops -- no third expansion
  rule 3  stability guard: a 12-repeat point estimate that moves more than the half-width of
          the 3-repeat arm's own interval is reported UNSTABLE and is not quotable even if
          rule 1 passes

rule 3 needs both artifacts, so it is skipped (loudly, with the reason) when the 3-repeat
file is missing rather than being quietly dropped. Nothing here re-fits with a different
estimator: both numbers come from the producer, so the comparison is same-source.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A9 = os.environ.get('A9_ARTIFACT') or os.path.join(
    ROOT, 'results', 'h4_real_llm_gx_qwen3_8b_a9_repl12.json')
BASE3 = os.path.join(ROOT, 'results', 'h4_real_llm_gx_qwen3_8b_persist.json')
PRODUCER = os.path.join(ROOT, 'experiments', 'h4_derived_stats.py')
AXES = ('steps', 'tools', 'vision')


def derive(path, out):
    r = subprocess.run([sys.executable, PRODUCER, path, '--out', out],
                       capture_output=True, text=True, timeout=1800)
    if not os.path.isfile(out):
        return None, (r.stdout + r.stderr)[-400:]
    return json.load(open(out, encoding='utf-8')), None


print('=== A9: gain identifiability at repeats=12 ===')
if os.environ.get('A9_ARTIFACT'):
    print('  WARNING: A9_ARTIFACT is overridden to %s' % os.environ['A9_ARTIFACT'])
    print('           This is NOT the replication arm: what this run writes is a smoke')
    print('           test of the script, named after the override so it cannot be')
    print('           mistaken for an A9 result.')
for p in (A9, PRODUCER):
    print('  %-60s %s' % (os.path.relpath(p, ROOT), 'present' if os.path.isfile(p) else 'MISSING'))
if not os.path.isfile(A9):
    print('\nA9 artifact not on disk yet -- nothing to judge. Re-run after the arm finishes.')
    sys.exit(2)

_ovr = os.environ.get('A9_ARTIFACT')
# the real arm's output belongs in results/; a smoke run's does not belong in the paper tree
# at all, because the next gate that walks results/ cannot tell the two apart
OUT9 = (os.path.join(ROOT, 'results', 'h4_derived_stats_a9_repl12.json') if not _ovr
        else os.path.join(__import__('tempfile').gettempdir(),
                          'h4_a9_SMOKE_from_%s.json'
                          % re.sub(r'[^A-Za-z0-9]+', '_', os.path.basename(A9))[:40]))
d9, err = derive(A9, OUT9)
if d9 is None:
    print('producer failed on the A9 artifact:\n' + (err or ''))
    sys.exit(3)
ident9 = d9.get('gain_identifiability') or {}
# the threshold is read from the producer's own source, never retyped here: the paper's
# rule is `withheld = width > 0.30` in experiments/h4_derived_stats.py, and a second copy
# of that constant is how a gate quietly drifts away from the thing it judges.
src = open(PRODUCER, encoding='utf-8').read()
import re as _re
# The key may hold a literal or, as it does now, a shared constant name. Either way the
# number is taken from the producer; a name that does not resolve is a red, not a default.
_m = _re.search(r'identifiability_max_ci_width["\']?\s*[:=]\s*([0-9.]+|[A-Za-z_]\w*)', src)
thr = thr_src = None
if _m:
    tok = _m.group(1)
    keyline = src[:_m.start()].count(chr(10)) + 1
    if _re.match(r'^[0-9.]+$', tok):
        thr, thr_src = float(tok), 'producer line %d (literal)' % keyline
    else:
        _d = _re.search(r'^%s\s*=\s*([0-9.]+)\s*$' % _re.escape(tok), src, _re.M)
        if _d:
            thr = float(_d.group(1))
            thr_src = 'producer line %d -> %s at line %d' % (
                keyline, tok, src[:_d.start()].count(chr(10)) + 1)
        else:
            thr_src = 'UNREADABLE: %s (line %d) does not resolve' % (tok, keyline)
print('  threshold = %s  (%s)' % (thr, thr_src))
if thr is None:
    print('  rule 1 cannot be judged without the producer threshold -- refusing to guess one')
    sys.exit(4)

d3 = None
if os.path.isfile(BASE3):
    # The baseline is READ here, never written into the tree. An earlier version passed the
    # registered path results/h4_derived_stats.json as --out, so running this judge -- even
    # with A9_ARTIFACT pointed at a smoke input -- regenerated a truth-source artifact and
    # moved its mtime. A read-only cross-check must not write anything it is checking.
    d3, _ = derive(BASE3, os.path.join(
        __import__('tempfile').gettempdir(), 'h4_a9_read_base3_%d.json' % os.getpid()))
    d3 = (d3 or {}).get('gain_identifiability') or {}

print('\n  axis      width(12)  <=thr?   point(12)     point(3)   half-width(3)  verdict')
quotable, unstable = [], []
for ax in AXES:
    v9 = ident9.get(ax) or {}
    w9 = v9.get('ci95_width')
    p9 = v9.get('point') or v9.get('point_estimate')
    v3 = (d3 or {}).get(ax) or {}
    w3 = v3.get('ci95_width')
    p3 = v3.get('point') or v3.get('point_estimate')
    if w9 is None:
        print('  %-9s  (A9 width not produced -- rule 1 cannot be judged)' % ax)
        continue
    # prefer the producer's own verdict over re-deriving it here
    wh = v9.get('withheld')
    r1 = (wh is False) if isinstance(wh, bool) else (w9 <= thr)
    note = 'QUOTABLE (rule 1)' if r1 else 'withheld (rule 2)'
    if r1 and w3 is not None and p9 is not None and p3 is not None:
        if abs(p9 - p3) > (w3 / 2.0):
            note = 'UNSTABLE (rule 3) -> not quotable'
            r1 = False
    if r1:
        quotable.append(ax)
    elif w9 > thr:
        unstable.append(ax)
    print('  %-9s  %8s  %-8s  %11s  %11s  %13s  %s' % (
        ax, ('%.3f' % w9) if w9 is not None else '-', r1,
        ('%.3f' % p9) if isinstance(p9, float) else p9,
        ('%.3f' % p3) if isinstance(p3, float) else p3,
        ('%.3f' % (w3 / 2.0)) if w3 is not None else 'no 3-repeat file', note))

print('\n  rule 1 (quotable axes): %s' % (quotable or 'none'))
print('  rule 2 applies (all widths > %.2f) : %s' % (thr, not quotable and all(
    (ident9.get(a) or {}).get('ci95_width', 0) > thr for a in AXES if (ident9.get(a) or {}))))
if d3 is None:
    print('  rule 3 NOT EVALUATED: the repeats=3 artifact is absent, so stability is unknown '
          '-- say so in the ledger rather than implying it passed')
print('\n  derived files: results/h4_derived_stats_a9_repl12.json'
      + ('' if d3 is None else ', results/h4_derived_stats.json'))
print('  this run wrote: %s' % os.path.relpath(OUT9, ROOT))
