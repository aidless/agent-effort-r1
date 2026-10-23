#!/usr/bin/env python3
r"""Does the 14B run's flatter curve mean "the effect vanished" or "the benchmark ran out
of headroom"?

The 14B derived stats say: iso curve 0.0 / 0.8125 / 1.0 / 0.875 / 0.875, McNemar L1->L4
p=0.607 (6 worse, 9 better), and -- unlike 8B -- a quadratic that survives excluding the
structurally floored level (p=0.0352). Read naively that says the scale leg contradicts
the paper's headline. But two of those facts are also exactly what a SATURATED task set
looks like: L2 reaches 1.0000, so nothing above it can improve, and a decline can only
show up as a drop from a ceiling.

So separate the three claims that are currently being conflated:
  (i)  MECHANISM  -- does verification still get deferred as budget grows
                    (writes up, tests down)? Scale-independent behaviour, no ceiling issue.
  (ii) SHAPE      -- is there a monotone decline, or an interior optimum? Ceiling-sensitive.
  (iii)POWER       -- can these n=48 cells detect a decline of the size 8B showed?
Saturating affects (ii); it does not affect (i); (iii) is arithmetic.
"""
import json
import math
import os
import sys

# the paper root, not experiments/ -- a RES of experiments/results silently
# made every lookup miss and the whole script printed 'missing'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, 'results')
RUNS = {'8B old card  ': 'h4_real_llm_gx_qwen3_8b.json',
        '8B new card  ': 'h4_real_llm_gx_qwen3_8b_newcard.json',
        '8B persist   ': 'h4_real_llm_gx_qwen3_8b_persist.json',
        '14B persist  ': 'h4_real_llm_gx_qwen3_14b_persist.json'}
DERIVED = {'8B old card  ': 'h4_derived_stats.json',
           '8B new card  ': 'h4_derived_stats_newcard.json',
           '8B persist   ': 'h4_derived_stats_8b_persist.json',
           '14B persist  ': 'h4_derived_stats_14b.json'}
LEVELS = ['L0_minimal', 'L1_low', 'L2_mid', 'L3_high', 'L4_max']


def load(p):
    f = os.path.join(RES, p)
    return json.load(open(f, encoding='utf-8')) if os.path.isfile(f) else None


print('=== (ii) SHAPE, and the ceiling evidence next to it ===')
print('%-14s %-42s %-28s %s' % ('run', 'iso curve L0..L4', 'saturated cells (=1.0)', 'mcnemar L1->L4'))
for tag, f in RUNS.items():
    d = load(DERIVED[tag]); raw = load(f)
    if not d:
        print('%-14s  (derived stats missing)' % tag); continue
    ic = d['iso_curve']
    curve = ' '.join('%.4f' % ic[l]['success'] for l in LEVELS)
    sat = [l for l in LEVELS if ic[l]['success'] >= 0.999]
    mc = d['mcnemar_pairs']['L1_low_to_L4_max']
    print('%-14s %-42s %-28s %d/%d/%d p=%.4f' % (
        tag, curve, ','.join(sat) or 'none',
        mc['worsened'], mc['improved'], mc['ties'], mc['exact_p_two_sided']))
    lr = d['logistic_lr_excluding_structurally_floored_level']
    print('   %-13s excl-floor quadratic: chi2=%.4f p=%.4f coef=%+.4f -> %s' % (
        '', lr['lr_chi2'], lr['p_value'], lr['quadratic_coef_std_log2_budget'],
        'significant (concave, interior optimum)' if lr['p_value'] < 0.05
        and lr['quadratic_coef_std_log2_budget'] < 0 else 'not significant'))

print('\n=== (i) MECHANISM: writes vs tests per episode, low -> max budget ===')
print('   (this is what C39 claims; a ceiling on success cannot fake it)')
for tag in RUNS:
    d = load(DERIVED[tag])
    if not d or 'actions_per_episode' not in d:
        print('%-14s  no actions_per_episode' % tag); continue
    a = d['actions_per_episode']
    try:
        w1, w4 = a['L1_low']['write'], a['L4_max']['write']
        t1, t4 = a['L1_low']['test'], a['L4_max']['test']
        print('%-14s write %.2f -> %.2f (x%.2f)   test %.2f -> %.2f (%+.1f%%)  %s' % (
            tag, w1, w4, w4 / max(w1, 1e-9), t1, t4, 100 * (t4 - t1) / max(t1, 1e-9),
            'DEFERS verification' if (w4 > w1 and t4 <= t1) else 'pattern NOT reproduced'))
    except KeyError as e:
        print('%-14s  missing key %s' % (tag, e))

print('\n=== failure reason at the top budget (is it still step exhaustion?) ===')
for tag in RUNS:
    d = load(DERIVED[tag])
    if not d:
        continue
    fr = d['iso_curve'].get('L4_max', {}).get('failure_reasons')
    print('  %-14s L4_max: %s' % (tag, fr))

print("\n=== (iii) POWER and an independent check of the producer p-value ===")
# McNemar only counts DISCORDANT pairs, so "not significant" must be distinguished from
# "underpowered". Report both tails, and recompute the two-sided exact p from the same
# (worsened, improved) counts the producer used: if my arithmetic and the registered
# producer disagree, that is a bug in one of them and it must surface here rather than in
# a quoted p-value in the paper.
TOL = 1e-9


def binom_tail_ge(n, k):
    return sum(math.comb(n, j) * 0.5 ** n for j in range(k, n + 1))


for tag in DERIVED:
    d = load(DERIVED[tag])
    if not d:
        print('  %-14s  (derived stats missing)' % tag)
        continue
    mc = d['mcnemar_pairs']['L1_low_to_L4_max']
    w, im, ties = mc['worsened'], mc['improved'], mc['ties']
    n = w + im
    if n == 0:
        print('  %-14s  no discordant pairs' % tag)
        continue
    p_worse = binom_tail_ge(n, w)
    p_better = binom_tail_ge(n, im)
    two_sided = min(1.0, 2.0 * min(p_worse, p_better))
    delta = abs(two_sided - mc['exact_p_two_sided'])
    agree = 'AGREES with producer (d=%.2e)' % delta if delta < 1e-9 else \
        'DISAGREES with producer: mine=%.6f theirs=%.6f' % (two_sided, mc['exact_p_two_sided'])
    print('  %-14s worsened=%-2d improved=%-2d ties=%-2d  P(>=%d worse)=%.5f  '
          'P(>=%d better)=%.5f  two-sided=%.6f  %s'
          % (tag, w, im, ties, w, p_worse, im, p_better, two_sided, agree))
    if delta > TOL:
        print('      ^^ this needs resolving before either p-value is quoted')

# Ceiling arithmetic: how much room was left to decline from, per run.
print('\n  headroom above the peak, which is what a "no decline" reading turns on:')
for tag in DERIVED:
    d = load(DERIVED[tag])
    if not d:
        continue
    ic = d['iso_curve']
    lv = ['L1_low', 'L2_mid', 'L3_high', 'L4_max']
    su = {k: ic[k]['success'] for k in lv if k in ic}
    if not su:
        continue
    peak = max(su.values())
    print('     %-14s peak=%.4f  drop peak->L4=%.4f  cells at 1.0: %s'
          % (tag, peak, peak - su.get('L4_max', float('nan')),
             [k for k, v in ic.items() if v['success'] >= 0.999] or 'none'))

print('\n=== identity caveats that must travel with any claim ===')
for tag, f in RUNS.items():
    raw = load(f)
    if not raw:
        continue
    env = raw.get('environment', {})
    print('  %-14s harness=%s  gpu=%s  n_records=%s  seed=%s  max_model_len=%s' % (
        tag, str(raw.get('script_sha256'))[:12], env.get('gpu'),
        raw.get('timing', {}).get('episodes'), raw.get('seed'),
        json.dumps(raw.get('axis_arms'))[:40]))
# Derive the pairing verdict from the artifacts themselves instead of asserting it in
# prose: the sentence below used to say "still running", which was true once and then
# quietly became false while the file kept printing it.
sha = {t: (load(f) or {}).get('script_sha256') for t, f in RUNS.items()}
gpu = {t: ((load(f) or {}).get('environment') or {}).get('gpu') for t, f in RUNS.items()}
pair = [t for t in sha if t.startswith('8B persist')]
KEY14 = '14B persist  '
KEY8P = '8B persist   '
A8, A14 = load(RUNS[KEY8P]), load(RUNS[KEY14])


def _cells(a):
    return sorted({(r.get('task'), r.get('menu'), r.get('level')) for r in a['records']})


def _seeds(a):
    return sorted({r.get('seed') for r in a['records']})


design = ''
if A8 and A14:
    same_cells = _cells(A8) == _cells(A14)
    same_seeds = _seeds(A8) == _seeds(A14)
    design = ('   design identity measured here: %d/%d records, %d/%d (task,menu,level) '
              'cells %s, %d/%d seeds %s' % (
                  len(A8['records']), len(A14['records']),
                  len(_cells(A8)), len(_cells(A14)), 'identical' if same_cells else 'DIFFER',
                  len(_seeds(A8)), len(_seeds(A14)), 'identical' if same_seeds else 'DIFFER'))
if pair and all(sha.get(t) == sha.get(KEY14) for t in pair):
    L = [
        '-> SAME-CODE PAIRING CLOSED.',
        '   Both *_persist arms record script_sha256 = %s' % str(sha.get(KEY8P)),
        '   and the same device (%s),' % gpu.get(KEY8P),
        '   so this contrast varies only the model: same seed list, same task set,',
        '   same two menus, same 672-episode plan.',
    ]
    if design:
        L.append(design)
    L += [
        '   The two d35f6d03 8B artifacts are the vehicle leg (old vs new card at one',
        '   code revision), NOT the scale-leg partner.',
        '   Caveat on the field itself: script_sha256 is computed at write time from the',
        '   disk file, so it can misreport which code ran; see',
        '   evidence/H4_SELFHASH_DEFECT.md. For these two arms the file did not change',
        '   mid-run, so the value is sound.',
    ]
    print('\n'.join('  ' + x for x in L))
else:
    print('  -> PAIRING NOT CLOSED: sha mismatch across %s' % sorted(sha))
