#!/usr/bin/env python3
r"""Re-derive, from the two artifacts alone, every number asserted in the
"Is the finding an artefact of the machine" paragraphs of paper/main.tex, and check
each against the string that actually appears in the manuscript.

This exists because prose numbers drift: the paper is the artefact a reviewer reads,
so a digit in it must be reproducible from results/*.json without consulting a
conversation. The script fails if a claimed number is absent from the tex (we edited
the tex, so the check is bidirectional) or if the artifact disagrees.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX = os.path.join(ROOT, 'paper', 'main.tex')
A = json.load(open(os.path.join(ROOT, 'results', 'h4_real_llm_gx_qwen3_8b.json'), encoding='utf-8'))
B = json.load(open(os.path.join(ROOT, 'results', 'h4_real_llm_gx_qwen3_8b_newcard.json'), encoding='utf-8'))
tex = open(TEX, encoding='utf-8').read()
seg_start = tex.find('Is the finding an artefact')
if seg_start < 0:
    print('RED: the paragraph is not in the manuscript'); sys.exit(1)
seg = tex[seg_start - 60:tex.find('\\section{Discussion}')]


def cells(d):
    o = {}
    for r in d['records']:
        o.setdefault((r.get('arm'), json.dumps(r.get('budget'), sort_keys=True)), []).append(bool(r.get('success')))
    return o


ca, cb = cells(A), cells(B)
n_flip = sum(1 for x, y in zip(A['records'], B['records']) if bool(x['success']) != bool(y['success']))
n_steps = sum(1 for x, y in zip(A['records'], B['records']) if x.get('steps_used') != y.get('steps_used'))
n_tools = sum(1 for x, y in zip(A['records'], B['records']) if x.get('tool_calls_used') != y.get('tool_calls_used'))
ident_cells = sum(1 for k in ca if sorted(ca[k]) == sorted(cb.get(k, [])))
fa, fb = A['model_fingerprint'], B['model_fingerprint']

checks = [
    ('$672$-episode', lambda: A['timing']['episodes'] == 672 and B['timing']['episodes'] == 672,
     'episodes old/new = %s/%s' % (A['timing']['episodes'], B['timing']['episodes'])),
    ('20260911', lambda: A['seed'] == B['seed'] == 20260911, 'seed %s == %s' % (A['seed'], B['seed'])),
    ('RTX 3090, 49152~MiB', lambda: A['environment']['gpu'] == 'NVIDIA GeForce RTX 3090, 49152 MiB',
     'old env.gpu = %r' % A['environment']['gpu']),
    ('vLLM 0.27.1', lambda: A['environment']['vllm'] == '0.27.1', 'old vllm = %r' % A['environment']['vllm']),
    ('RTX 4080, 32760~MiB', lambda: B['environment']['gpu'] == 'NVIDIA GeForce RTX 4080, 32760 MiB',
     'new env.gpu = %r' % B['environment']['gpu']),
    ('vLLM 0.30.0', lambda: B['environment']['vllm'] == '0.30.0', 'new vllm = %r' % B['environment']['vllm']),
    ('13 files', lambda: fa['n_files'] == fb['n_files'] == 13, 'n_files %s/%s' % (fa['n_files'], fb['n_files'])),
    ('$6{,}114{,}568{,}840$', lambda: fa['total_bytes'] == fb['total_bytes'] == 6114568840,
     'total_bytes %s/%s' % (fa['total_bytes'], fb['total_bytes'])),
    ('identical per-file digests', lambda: fa['files'] == fb['files'] and fa['path'] != fb['path'],
     'files equal=%s, paths differ=%s' % (fa['files'] == fb['files'], fa['path'] != fb['path'])),
    ('$0/672$', lambda: n_flip == 0, 'episodes changing success = %d' % n_flip),
    ('$23$ (arm, budget) cells', lambda: len(ca) == 23 and ident_cells == 23,
     'cells=%d, multisets identical=%d' % (len(ca), ident_cells)),
    ('$r^2{=}0.291377$', lambda: abs(A['gain_fit']['r_squared_on_cells'] - 0.29137722024820356) < 1e-9
     and A['gain_fit']['r_squared_on_cells'] == B['gain_fit']['r_squared_on_cells'],
     'r2 old=%r new=%r' % (A['gain_fit']['r_squared_on_cells'], B['gain_fit']['r_squared_on_cells'])),
    ('$0.30$ CI-width', lambda: '0.3' == ('%s' % json.load(open(os.path.join(
        ROOT, 'results', 'h4_derived_stats.json')))['identifiability_max_ci_width']),
     'threshold=%s' % json.load(open(os.path.join(ROOT, 'results', 'h4_derived_stats.json')))['identifiability_max_ci_width']),
    ('$7$ of $672$', lambda: n_steps == 7, 'episodes with different steps_used = %d' % n_steps),
    ('$3$ a different', lambda: n_tools == 3, 'episodes with different tool_calls_used = %d' % n_tools),
    ('$452$', lambda: A['gpu_state_at_load']['free_mib'] == 452
     and A['gpu_memory_utilization_detail']['free_mib'] == 48136,
     'old 452 vs 48136 -> %s vs %s' % (A['gpu_state_at_load']['free_mib'],
                                      A['gpu_memory_utilization_detail']['free_mib'])),
    ('$4{,}102$', lambda: B['gpu_state_at_load']['free_mib'] == 4102
     and B['gpu_memory_utilization_detail']['free_mib'] == 32230,
     'new 4102 vs 32230 -> %s vs %s' % (B['gpu_state_at_load']['free_mib'],
                                        B['gpu_memory_utilization_detail']['free_mib'])),
]

# the 117/119 claim comes from the diff carrier, not from these artifacts
diff_txt = open(os.path.join(ROOT, 'evidence', 'H4_NEWCARD_DIFF.txt'), encoding='utf-8').read()
m = re.search(r'leaf fields compared: (\d+)\s+equal: (\d+)\s+differing: (\d+)', diff_txt)
checks.append(('$119$ leaf fields', lambda: m and m.group(1) == '119' and m.group(2) == '117'
              and m.group(3) == '2', 'diff carrier says: %s' % (str(m.groups()) if m else 'no match')))
checks.append(('the two that differ are the input path and the input digest',
               lambda: 'source_result' in diff_txt and 'source_sha256' in diff_txt,
               'differing fields both provenance in carrier'))

bad = []
for needle, fn, detail in checks:
    present = needle in seg
    try:
        true_ = bool(fn())
    except Exception as e:
        true_ = False
        detail = 'EXC %s: %s' % (type(e).__name__, e)
    ok = present and true_
    print('  %-52s in-tex=%-5s from-data=%-5s  %s' % (needle[:52], present, true_, detail[:90]))
    if not ok:
        bad.append(needle)

print('\n%d/%d claims match both the manuscript and the artifacts' % (len(checks) - len(bad), len(checks)))
if bad:
    print('RED: %s' % bad)
sys.exit(1 if bad else 0)
