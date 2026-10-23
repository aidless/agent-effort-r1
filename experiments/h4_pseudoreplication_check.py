#!/usr/bin/env python3
r"""Are the H4 'repeats' independent observations, or the same run three/twelve times?

Trigger, twice over. First, A9 (protocol: replicate the axis arms 3 -> 12 so the gain CIs
tighten) produced a gain_fit numerically identical to the repeats=3 fit -- same point
estimates to 1e-13, same r-squared to all 17 digits. Second, checking why found that at
temperature 0 a per-request seed does not move the policy: in the A9 artifact, 144 of 144
(task, level) groups carry the SAME action sequence in all 12 repeats, and in the registered
repeats=3 artifact 0 of 80 (level, task, menu) units change success across their 3 repeats.

That makes the quoted McNemar a test on pseudo-replicates: n_pairs=48 is 16 independent
units written three times. So this script recomputes every registered comparison twice, with
the PRODUCER'S OWN functions both times (an earlier ad-hoc re-derivation of the pairing key
returned 24 pairs where the producer reports 48, so the key is not something to rebuild from
memory), and fails when a comparison is significant as-run but not on units.

--selftest covers both directions: a synthetic artifact whose repeats do vary must come back
clean, and a copy of the real structure must come back red.
"""
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORDER = ['L0_minimal', 'L1_low', 'L2_mid', 'L3_high', 'L4_max']
PAIRS = (('L0_minimal', 'L1_low'), ('L1_low', 'L4_max'),
         ('L2_mid', 'L3_high'), ('L3_high', 'L4_max'))
UNIT = ('level', 'task', 'menu')


def producer():
    spec = importlib.util.spec_from_file_location(
        'hds', os.path.join(HERE, 'h4_derived_stats.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def units(recs):
    g = collections.defaultdict(list)
    for r in recs:
        g[tuple(r.get(k) for k in UNIT)].append(r)
    return g


def dedup(recs):
    """One record per (level, task, menu) -- the lowest repeat, so the choice is fixed."""
    keep = {}
    for r in recs:
        k = tuple(r.get(x) for x in UNIT)
        if k not in keep or r.get('repeat', 0) < keep[k].get('repeat', 0):
            keep[k] = r
    return list(keep.values())


def analyse(path, ds, out=sys.stdout.write):
    d = json.load(open(path, encoding='utf-8'))
    iso = [r for r in d.get('records') or [] if r.get('arm') == 'iso']
    ax = [r for r in d.get('records') or [] if str(r.get('arm', '')).startswith('axis_')]
    g_iso, g_ax = units(iso), units(ax)
    vary_i = sum(1 for v in g_iso.values() if len({x.get('success') for x in v}) > 1)
    vary_a = sum(1 for v in g_ax.values() if len({x.get('success') for x in v}) > 1)
    out('%s\n' % os.path.basename(path))
    out('  sha256 %s   records %d (iso %d, axis %d)   repeats field %s\n' % (
        hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16],
        len(d.get('records') or []), len(iso), len(ax), d.get('repeats')))
    out('  units (level,task,menu): iso %d, of which success VARIES across repeats %d\n' % (
        len(g_iso), vary_i))
    out('  units (level,task,menu): axis %d, of which success VARIES across repeats %d\n' % (
        len(g_ax), vary_a))
    budget = {b['label']: b['max_steps']
              for b in (d.get('iso_with_e3') or {}).get('budget_levels', [])}
    bad = []
    if not g_iso:
        out('  no iso records in this artifact: comparisons cannot be recomputed here\n')
        return bad
    dd = dedup(iso)
    out('  %-18s %-28s %-28s %s\n' % ('comparison', 'as-run (records)', 'on units', 'verdict'))
    for a, b in PAIRS:
        r1, r2 = ds.mcnemar(iso, a, b), ds.mcnemar(dd, a, b)
        p1, p2 = r1.get('exact_p_two_sided'), r2.get('exact_p_two_sided')
        flip = (p1 is not None and p2 is not None and p1 < 0.05 <= p2)
        out('  %-18s n=%-3d w=%-2d i=%-2d p=%-9.5g n=%-3d w=%-2d i=%-2d p=%-9.5g %s\n' % (
            '%s->%s' % (a.replace('L', ''), b.replace('L', '')),
            r1.get('n_pairs'), r1.get('worsened'), r1.get('improved'), p1,
            r2.get('n_pairs'), r2.get('worsened'), r2.get('improved'), p2,
            'SIGNIFICANCE LOST ON UNITS' if flip else 'unchanged'))
        if flip:
            bad.append(('mcnemar', '%s->%s' % (a, b), p1, p2))
    for tag, lv in (('all levels', ORDER), ('excl. floored', ORDER[1:])):
        if not budget:
            continue
        l1, l2 = ds.logistic_lr(iso, lv, budget), ds.logistic_lr(dd, lv, budget)
        q1, q2 = l1.get('p_value'), l2.get('p_value')
        flip = (q1 is not None and q2 is not None and q1 < 0.05 <= q2)
        out('  %-18s chi2=%-8.3g p=%-9.4g      chi2=%-8.3g p=%-9.4g %s\n' % (
            'logistic LR ' + tag, l1.get('lr_chi2'), q1, l2.get('lr_chi2'), q2,
            'SIGNIFICANCE LOST ON UNITS' if flip else 'unchanged'))
        if flip:
            bad.append(('logistic_lr', tag, q1, q2))
    return bad


def selftest(ds, tmp):
    """The synthetic green case: repeats that really differ must NOT be flagged."""
    recs = []
    for li, L in enumerate(ORDER):
        for t in range(4):
            for rep in range(3):
                recs.append({'arm': 'iso', 'level': L, 'task': 't%d' % t, 'menu': 'm',
                             'repeat': rep, 'budget': 4 << li,
                             'success': ((li + t + rep) % 3) == 0,
                             'model_turns': [{'action': 'read'}]})
    p = os.path.join(tmp, 'synthetic_varies.json')
    json.dump({'records': recs, 'repeats': 3,
               'iso_with_e3': {'budget_levels': [{'label': L, 'max_steps': 4 << i}
                                                 for i, L in enumerate(ORDER)]}},
              open(p, 'w'))
    bad = analyse(p, ds, out=lambda s: None)
    print('  synthetic (repeats DO vary): flagged %d comparison(s) -> %s'
          % (len(bad), 'ok, no false positive' if not bad else 'FALSE POSITIVE'))
    # and the opposite shape: three identical copies of each unit
    recs2 = []
    for li, L in enumerate(ORDER):
        for t in range(4):
            for rep in range(3):
                recs2.append({'arm': 'iso', 'level': L, 'task': 't%d' % t, 'menu': 'm',
                              'repeat': rep, 'budget': 4 << li,
                              'success': t > li, 'model_turns': [{'action': 'read'}]})
    p2 = os.path.join(tmp, 'synthetic_identical.json')
    json.dump({'records': recs2, 'repeats': 3,
               'iso_with_e3': {'budget_levels': [{'label': L, 'max_steps': 4 << i}
                                                 for i, L in enumerate(ORDER)]}},
              open(p2, 'w'))
    bad2 = analyse(p2, ds, out=lambda s: None)
    print('  synthetic (repeats identical): flagged %d comparison(s) -> %s'
          % (len(bad2), 'ok, the check fires' if bad2 else 'DEAD CHECK'))
    return (1 if bad else 0) + (0 if bad2 else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('artifacts', nargs='*',
                    default=[os.path.join(ROOT, 'results',
                                          'h4_real_llm_gx_qwen3_8b_persist.json')])
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    ds = producer()
    if a.selftest:
        import tempfile
        return 1 if selftest(ds, tempfile.mkdtemp(prefix='psr_')) else 0
    n_bad = 0
    for p in a.artifacts:
        if not os.path.isfile(p):
            print('MISSING: %s' % p)
            n_bad += 1
            continue
        n_bad += len(analyse(p, ds))
    print('\nA flag means: significant when every record is counted, not significant when '
          'each (level, task, menu) unit is counted once. With temperature 0 and identical '
          'trajectories across repeats, the unit count is the one a reader can defend.')
    return 1 if n_bad else 0


if __name__ == '__main__':
    sys.exit(main())
