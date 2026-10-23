#!/usr/bin/env python3
r"""Decide whether the persistence patch changed any measured number, by comparing
the FINAL artifacts of two identical stub sweeps: patched harness vs the pre-patch
backup.

Why not compare raw dumps: only the patched harness writes a raw dump (that is the
patch), so requiring one from the backup tests nothing -- it just fails. The final
artifact is what both produce.

The comparison is an ALLOW-LIST of the fields the paper consumes, not a deny-list of
"stuff that might differ". An allow-list is only trustworthy if it is not vacuous,
so CASE 3 perturbs one outcome field in one copy and requires the comparator to
notice. A comparator that reports INERT for everything, perturbed or not, is
decoration.
"""
import json
import os
import subprocess
import sys

H = '/root/autodl-tmp/p2_agent_effort/scripts/h4_real_llm_gx.py'
D = os.path.dirname(H)
BAKS = sorted(f for f in os.listdir(D) if f.startswith('h4_real_llm_gx.py.bak_persist_'))
if not BAKS:
    print('RED: no pre-patch backup on disk'); sys.exit(1)
BAK = os.path.join(D, BAKS[-1])
PY = '/root/autodl-tmp/venv_h4/bin/python'
W = '/root/autodl-tmp/cont_d0788aa9/inert_' + str(os.getpid())
os.makedirs(W, exist_ok=True)
ARGV = ['--backend', 'stub', '--repeats', '2', '--arms', 'iso,axis_steps,axis_tools,axis_vision',
        '--n-boot', '60']

DOC_KEYS = ('iso_success_curve', 'gain_fit', 'floor_cells_excluded_from_fit',
            'stub_gain_recovery', 'ref_sensitivity')
REC_KEYS = ('task_id', 'arm', 'budget', 'success', 'reason', 'steps_used',
            'tool_calls_used', 'vision_probes_used', 'parse_errors', 'steps_remaining')


def run(script, tag):
    out = os.path.join(W, tag + '.json')
    p = subprocess.run([PY, script] + ARGV + ['--out', out], capture_output=True,
                       text=True, timeout=2400, cwd=D)
    blob = (p.stdout or '') + (p.stderr or '')
    if not os.path.exists(out):
        print('RED: %s wrote nothing (rc=%d)\n%s' % (tag, p.returncode, blob[-400:]))
        sys.exit(1)
    print('%-9s rc=%d bytes=%d' % (tag, p.returncode, os.path.getsize(out)))
    return json.load(open(out)), blob


def project(doc):
    """Reduce an artifact to the fields this test claims to compare."""
    recs = [{k: r.get(k) for k in REC_KEYS if k in r} for r in doc.get('records', [])]
    return {'doc': {k: doc.get(k) for k in DOC_KEYS}, 'n_rec': len(recs), 'recs': recs}


def compare(a, b, label):
    bad = []
    if a['doc'] != b['doc']:
        for k in DOC_KEYS:
            if a['doc'].get(k) != b['doc'].get(k):
                bad.append('block %s differs' % k)
    if a['n_rec'] != b['n_rec']:
        bad.append('record count %d vs %d' % (a['n_rec'], b['n_rec']))
    else:
        for i, (x, y) in enumerate(zip(a['recs'], b['recs'])):
            if x != y:
                bad.append('record %d differs: %s' % (i, {k: (x.get(k), y.get(k))
                                                          for k in set(x) | set(y)
                                                          if x.get(k) != y.get(k)}))
    print('  %-52s %s' % (label, 'IDENTICAL' if not bad else 'DIFFERS'))
    for m in bad[:4]:
        print('      ' + m)
    return not bad


pa, blob_a = run(H, 'patched')
pb, blob_b = run(BAK, 'prepatch')
print('\ncompared keys: doc=%s + per-record %s' % (list(DOC_KEYS), list(REC_KEYS)))
print('not compared (wall clock by construction): mean/elapsed_ms, generation_ms,')
print('  run_seconds, gpu/VRAM details, paths, and the raw-dump side effects.\n')

ok = compare(project(pa), project(pb), 'CASE 1 patched vs pre-patch, same seed')

print('CASE 2 the fit actually ran in both (not an empty-equality pass):')
f_a, f_b = pa.get('gain_fit') or {}, pb.get('gain_fit') or {}
ran = bool(f_a.get('fitted')) and bool(f_b.get('fitted'))
print('  both gain_fit.fitted == True : %s (params=%s)' % (ran, bool(f_a.get('params'))))
ok = ran and ok

print('CASE 3 injection: perturb one outcome field, comparator must go red:')
import copy
pc = copy.deepcopy(pb)
if pc['records']:
    pc['records'][0]['success'] = 1 - pc['records'][0]['success']
    pc['records'][0]['steps_used'] = 999
inj = compare(project(pa), project(pc), 'injected single-field change')
caught = not inj
print('  injection caught  : %s' % caught)

ok = ok and caught
print('\n%s' % ('INERT: no paper-facing number moved, and the comparator can see a move'
                if ok else 'NOT ESTABLISHED'))
print('sha patched = %s' % subprocess.run(['sha256sum', H], capture_output=True,
                                          text=True).stdout.split()[0])
sys.exit(0 if ok else 1)
