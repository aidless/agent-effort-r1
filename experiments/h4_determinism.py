#!/usr/bin/env python3
r"""Is the new-card 8B control an independent replication, or greedy determinism
reproducing itself?

h4_read.py showed gain_fit and the iso curve identical to 4 decimals across two
physically different GPUs. Before that is written as "H4 replicates on a new
vehicle", it has to be established WHICH of the two it is, because they support
completely different sentences:

  - per-episode outcomes identical  -> decoding is deterministic (temperature=0), so a
    second vehicle cannot move the outcome distribution. The replication then carries
    almost no information about the gains, and the paper may only claim that the
    result is not an artifact of the first card's numerics.
  - some episodes differ            -> the vehicle is a real perturbation and the fit
    agreeing is evidence.

Compares the outcome-carrying fields of all 672 paired records, and separately checks
whether the *inputs* were declared identical (seed, model fingerprint, chat mode).
"""
import json
import os
import statistics

# repo-local artifacts (the cloud copies were byte-verified into results/ on 2026-09-24:
# 673703 B / 674243 B, sha256 a0643029750c7bae and c66e4801394265ef respectively)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD = os.path.join(ROOT, 'results', 'h4_real_llm_gx_qwen3_8b.json')
NEW = os.path.join(ROOT, 'results', 'h4_real_llm_gx_qwen3_8b_newcard.json')
OUTCOME = ('success', 'reason', 'steps_used', 'tool_calls_used', 'vision_probes_used',
           'parse_errors', 'reward', 'solved', 'final_state')

da, db = json.load(open(OLD, encoding='utf-8')), json.load(open(NEW, encoding='utf-8'))
ra, rb = da['records'], db['records']
print('records: old=%d new=%d' % (len(ra), len(rb)))


def key(r):
    b = r.get('budget')
    bt = json.dumps(b, sort_keys=True) if isinstance(b, dict) else str(b)
    return (r.get('arm'), bt, r.get('task_id'), r.get('episode', r.get('index')),
            r.get('repeat'), r.get('seed'))


ka, kb = [key(r) for r in ra], [key(r) for r in rb]
print('pairing keys unique on both sides: %s / %s' % (len(set(ka)) == len(ka), len(set(kb)) == len(kb)))
if len(set(ka)) != len(ka) or len(set(kb)) != len(kb):
    print('NOTE: keys collide -> falling back to positional pairing (order is fixed by the sweep)')
    ma = {i: r for i, r in enumerate(ra)}
    mb = {i: r for i, r in enumerate(rb)}
    pairs = [(ma[i], mb[i]) for i in range(min(len(ma), len(mb)))]
else:
    mb = dict(zip(kb, rb))
    pairs = [(a, mb[k]) for k, a in zip(ka, ra) if k in mb]
print('paired records: %d' % len(pairs))

fields = sorted({k for r in ra for k in r} & {k for r in rb for k in r} & set(OUTCOME))
print('outcome fields compared: %s' % fields)
n_diff = {f: 0 for f in fields}
worst = []
for a, b in pairs:
    d = [f for f in fields if a.get(f) != b.get(f)]
    for f in d:
        n_diff[f] += 1
    if d and len(worst) < 3:
        worst.append(({f: (a.get(f), b.get(f)) for f in d}, a.get('arm'), a.get('budget')))

print('\nper-field disagreement counts (out of %d):' % len(pairs))
for f in fields:
    print('  %-20s %d' % (f, n_diff[f]))
tot = sum(1 for a, b in pairs if any(a.get(f) != b.get(f) for f in fields))
print('  records with ANY outcome difference: %d / %d (%.1f%%)'
      % (tot, len(pairs), 100.0 * tot / max(1, len(pairs))))
for w in worst:
    print('  example: %s' % (w,))

print('\n== declared inputs (were these held fixed on purpose?) ==')
for k in ('seed', 'chat_mode_requested', 'chat_mode_effective', 'backend', 'repeats',
          'min_free_mib', 'lock_mode'):
    print('  %-22s old=%r new=%r %s' % (k, da.get(k), db.get(k),
                                        'same' if da.get(k) == db.get(k) else 'DIFFERENT'))
fa, fb = da.get('model_fingerprint') or {}, db.get('model_fingerprint') or {}
for k in sorted(set(fa) | set(fb)):
    same = fa.get(k) == fb.get(k)
    if not same:
        print('  fingerprint %-18s old=%r new=%r  DIFFERENT' % (k, fa.get(k), fb.get(k)))
print('  fingerprint identical overall: %s' % (fa == fb))
print('  declared_limits old=%s' % json.dumps(da.get('declared_limits'), ensure_ascii=False)[:220])
print('  (whether decoding is greedy is read from the harness source, not assumed here)')

print('\n== what the vehicle DID move: timing distribution ==')
def gen(d):
    return [r['generation_ms'] for r in d['records']
            if isinstance(r.get('generation_ms'), (int, float)) and r['generation_ms'] > 0]


def q(g, frac):
    s = sorted(g)
    return s[min(len(s) - 1, int(frac * len(s)))] if s else float('nan')


ga, gb = gen(da), gen(db)
for tag, g in (('old', ga), ('new', gb)):
    print('  %-4s n=%d mean=%8.1f p10=%8.1f p50=%8.1f p90=%8.1f p99=%8.1f max=%9.1f  sd=%8.1f'
          % (tag, len(g), statistics.mean(g), q(g, .10), statistics.median(g),
             q(g, .90), q(g, .99), max(g), statistics.pstdev(g)))
print('  mean ratio old/new = %.4f (1.0 = no change); median ratio = %.4f'
      % (statistics.mean(ga) / statistics.mean(gb), statistics.median(ga) / statistics.median(gb)))
d = [y - x for x, y in zip(sorted(ga), sorted(gb))]
print('  quantile-matched deltas (new-old, ms): min=%.0f p50=%.0f max=%.0f  (mixed sign = no clean speed-up)'
      % (min(d), statistics.median(d), max(d)))
FIT_FIELDS = ('success', 'n')          # what fit_gains actually consumes
print('\n== do the differences reach the fit? ==')
print('  fit_gains input cells (harness line ~1074): arm, budget, fail=1-success, n, success.')
print('  so only `success` can move the fitted gains; steps/tool-call differences enter')
print('  summary means only.')
fit_relevant = sum(1 for a, b in pairs if a.get('success') != b.get('success'))
per_cell_ident = True
sa = {}
sb = {}
for r in ra:
    sa.setdefault((r.get('arm'), json.dumps(r.get('budget'), sort_keys=True)), []).append(bool(r.get('success')))
for r in rb:
    sb.setdefault((r.get('arm'), json.dumps(r.get('budget'), sort_keys=True)), []).append(bool(r.get('success')))
for k in sorted(set(sa) | set(sb)):
    if sorted(sa.get(k, [])) != sorted(sb.get(k, [])):
        per_cell_ident = False
        print('  cell %s success multiset DIFFERS' % (k,))
print('  episodes with a different success: %d / %d' % (fit_relevant, len(pairs)))
print('  per-cell success multisets identical: %s (%d cells)' % (per_cell_ident, len(sa)))

print('\nVERDICT: %s' % (
    'success is identical in every cell, so gain_fit is bit-identical BY CONSTRUCTION and '
    'is NOT independent cross-vehicle evidence; the vehicle did perturb trajectories '
    '(%d/%d records changed steps_used/tool_calls_used, %d of them fit-relevant). '
    'What this control can support: outcome robustness + a latency-profile comparison. '
    'What it cannot support: "the fitted gains replicate on new hardware".'
    % (tot, len(pairs), fit_relevant) if per_cell_ident and tot > 0 else
    ('OUTCOMES IDENTICAL -> greedy determinism, no replication content' if tot == 0 else
     'FIT-RELEVANT DIFFERENCES EXIST -> genuine replication of the gains')))

