#!/usr/bin/env python3
r"""Exhaustive field-by-field diff of the two h4_derived_stats outputs, so the ledger
row can say "every citable field matches" only after having looked at all of them.

Fields are classified, not just enumerated:
  CITABLE  -- a number a claim may rest on; must be equal or the replication claim dies
  PROVENANCE -- expected to differ (which artifact, when, by what code); a difference
                here is correct and equality here would be suspicious
  TIMING   -- expected to differ and NOT citable, because both runs' load-time VRAM
              readings contradict their own adaptive-util readings (452 vs 48136 MiB on
              the old card, 4102 vs 32230 on the new), so neither is a clean
              single-tenant measurement
"""
import json
import sys

A = 'results/h4_derived_stats.json'
B = 'results/h4_derived_stats_newcard.json'
PROVENANCE = {'source_result', 'generated_by', 'script_sha256', 'timestamp', 'argv',
              # source_sha256 is the hash of the artifact the producer read. Two runs are
              # two files, so it MUST differ; calling it citable is what made the first
              # version report a broken replication on the one field that differs for
              # exactly the reason under test.
              'source_sha256'}


def walk(x, y, path=''):
    """Yield (path, a, b) leaf comparisons."""
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            yield from walk(x.get(k), y.get(k), path + '/' + str(k))
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            yield (path + '/__len__', len(x), len(y))
        for i, (u, v) in enumerate(zip(x, y)):
            yield from walk(u, v, '%s[%d]' % (path, i))
    else:
        yield (path, x, y)


da, db = json.load(open(A, encoding='utf-8')), json.load(open(B, encoding='utf-8'))
rows = list(walk(da, db))
same = [r for r in rows if r[1] == r[2]]
diff = [r for r in rows if r[1] != r[2]]


def cls(path):
    top = path.strip('/').split('/')[0].split('[')[0]
    if top.strip('/') in PROVENANCE:
        return 'PROVENANCE'
    if 'timing' in path or 'wall' in path or 'elapsed' in path or '_ms' in path:
        return 'TIMING'
    return 'CITABLE'


print('leaf fields compared: %d  equal: %d  differing: %d' % (len(rows), len(same), len(diff)))
bad = []
for p, a, b in diff:
    k = cls(p)
    print('  [%-11s] %-58s old=%r new=%r' % (k, p, a, b))
    if k == 'CITABLE':
        bad.append(p)

print('\nequal CITABLE fields (%d), the load-bearing ones:' % len([r for r in same if cls(r[0]) == 'CITABLE']))
KEEP = ('iso_curve', 'mcnemar', 'gain_identifiability', 'non_monotonicity_verdict',
        'logistic_lr', 'identifiability_max_ci_width', 'actions_per_episode')
for p, a, _ in same:
    if cls(p) == 'CITABLE' and any(k in p for k in KEEP) and p.count('/') <= 2:
        print('  %-58s %s' % (p, a))

print('\nREPLICATION on citable fields: %s'
      % ('HOLDS (all equal)' if not bad else 'BROKEN on %d: %s' % (len(bad), bad)))

# The comparator has to be shown able to see a break, or "117/119 equal" is decoration.
import copy
inj = copy.deepcopy(db)
inj['iso_curve']['L1_low']['success'] = round(inj['iso_curve']['L1_low']['success'] + 0.05, 4)
rep = [r for r in walk(da, inj) if cls(r[0]) == 'CITABLE' and r[1] != r[2]]
print('INJECTION CONTROL: perturbing iso_curve.L1_low.success by +0.05 is flagged on %d '
      'citable field(s) -> %s' % (len(rep), 'CAUGHT' if rep else 'MISSED (comparator is blind)'))

ok = (not bad) and bool(rep)
print('\n%s' % ('VERDICT: replication holds AND the comparator can see a break'
                if ok else 'VERDICT: NOT ESTABLISHED (see above)'))
sys.exit(0 if ok else 1)
