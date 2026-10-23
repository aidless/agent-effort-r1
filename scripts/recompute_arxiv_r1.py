#!/usr/bin/env python3
"""Read retained records; regenerate descriptive tables, without model/network calls.

Uses the standard library. Repeated executions and two menus are nested within
eight authored tasks. No population p-values or confidence intervals are emitted.
E2 is independently recalculated from its declared algebra, not an agent run.
"""
from pathlib import Path
from collections import Counter, defaultdict
from itertools import product
from statistics import mean, stdev
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/arxiv_r1_descriptive.json'
INPUTS = ['e1_tool_latency.json', 'e1b_agent_primitives.json',
          'e2_allocation.json', 'e3_agent_loop.json',
          'h4_real_llm_gx_qwen3_8b_persist.json',
          'h4_real_llm_gx_qwen3_14b_persist.json']
LEVELS = ['L0_minimal', 'L1_low', 'L2_mid', 'L3_high', 'L4_max']
BUDGETS = [(2, 1, 200, 0), (4, 3, 600, 1), (8, 6, 1500, 2),
           (16, 12, 4000, 4), (32, 24, 12000, 8)]
FIELDS = ['max_steps', 'max_tool_calls', 'max_context_chars', 'max_vision_probes']
MENUS = ['read_then_write', 'probe_heavy']
TASKS = ['t01_csv_group_sum', 't02_json_roundtrip', 't03_dedupe_stable',
         't04_binary_search', 't05_word_freq', 't06_matrix_transpose',
         't07_interval_merge', 't08_topk']

def close(x, y):
    assert math.isclose(x, y, rel_tol=1e-10, abs_tol=1e-9), (x, y)

def load(name):
    return json.loads((ROOT / 'results' / name).read_text())

def cells(rows, field='level', menu='menu'):
    out = {}
    for level in sorted({r[field] for r in rows}):
        rr = [r for r in rows if r[field] == level]
        task_values = {t: mean(int(r['success']) for r in rr if r['task'] == t)
                       for t in TASKS}
        out[level] = dict(n=len(rr), n_success=sum(r['success'] for r in rr),
                          rate=mean(task_values.values()), task_rates=task_values,
                          menu_rates={m: mean(int(r['success']) for r in rr if r[menu] == m)
                                      for m in sorted({r[menu] for r in rr})},
                          mean_elapsed_ms=mean(r['elapsed_ms'] for r in rr),
                          failure_reasons=dict(Counter(r['reason'] for r in rr if not r['success'])))
    return out

def latency(d):
    out = {}
    for name, raw in d['raw'].items():
        xs, ok = raw['samples_ms'], raw['ok']
        assert len(xs) == len(ok) and len(xs) >= 30
        assert all(type(x) is bool for x in ok)
        assert all(math.isfinite(x) and x >= 0 for x in xs)
        a = d['aggregates'][name]
        assert len(xs) == a['n'] and sum(ok) == a['n_ok']
        close(mean(xs), a['mean_ms'])
        close(1 - mean(ok), a['failure_rate'])
        ys = [x for x, b in zip(xs, ok) if b]
        if ys:
            close(mean(ys), a['mean_ok_ms'])
        out[name] = dict(n=len(xs), n_ok=sum(ok), mean_ms=mean(xs),
                         sd_ms=stdev(xs), mean_ok_ms=mean(ys) if ys else None)
    return out

def h4(d):
    assert d['is_real_llm'] is True and d['dry_run'] is False
    assert d['backend'] == 'vllm' and d['repeats'] == 3
    assert d['chat_mode_effective'] == 'think_off'
    fp = d['model_fingerprint']
    assert fp['full_hash'] is True and len(fp['files']) == fp['n_files'] == 13
    assert all(len(x['sha256']) == 64 for x in fp['files'])
    rs = d['records']
    assert len(rs) == d['n_records'] == 672
    assert set(r['task'] for r in rs) == set(TASKS)
    spec = [('iso', l, m, dict(zip(FIELDS, b))) for l, b in zip(LEVELS, BUDGETS) for m in MENUS]
    defaults = dict(zip(FIELDS, (8, 4, 1500, 2)))
    for arm, field, vals in [('axis_steps', 'max_steps', [2, 4, 8, 16, 32]),
                              ('axis_tools', 'max_tool_calls', [0, 1, 2, 4, 8, 16, 24]),
                              ('axis_vision', 'max_vision_probes', [0, 1, 2, 4, 8, 16])]:
        for v in vals:
            spec.append((arm, f'{field}={v}', 'probe_heavy', {**defaults, field: v}))
    expected = {(a, l, m, t, rep): b for a, l, m, b in spec for t in TASKS for rep in range(3)}
    seen = set()
    repeat_groups = defaultdict(list)
    for r in rs:
        key = (r['arm'], r['level'], r['menu'], r['task'], r['repeat'])
        assert key in expected and key not in seen, key
        seen.add(key)
        assert r['budget'] == expected[key]
        assert type(r['success']) is bool
        assert len(r['model_turns']) == r['n_history']
        assert r['tool_calls_used'] <= r['budget']['max_tool_calls']
        assert r['vision_probes_used'] <= r['budget']['max_vision_probes']
        if r['success']:
            assert r['reason'] == 'tests_passed'
            assert any(t['action'] == 'test' and t['rc'] == 0 for t in r['model_turns'])
        repeat_groups[key[:-1]].append(r)
    assert seen == set(expected)
    same_success = all(len({r['success'] for r in rr}) == 1 for rr in repeat_groups.values())
    same_actions = all(len({json.dumps(r['model_turns'], sort_keys=True) for r in rr}) == 1
                       for rr in repeat_groups.values())
    assert same_success and same_actions
    curves = cells([r for r in rs if r['arm'] == 'iso'])
    for l in LEVELS:
        close(curves[l]['rate'], d['iso_success_curve'][l]['success'])
        rr = [r for r in rs if r['arm'] == 'iso' and r['level'] == l]
        curves[l]['tests_per_episode'] = mean(sum(t['action'] == 'test' for t in r['model_turns']) for r in rr)
    diffs = {t: curves['L4_max']['task_rates'][t] - curves['L1_low']['task_rates'][t] for t in TASKS}
    loo = {t: mean(v for k, v in diffs.items() if k != t) for t in TASKS}
    actions = [{k: r[k] for k in ['task', 'menu', 'success', 'reason', 'model_turns']}
               for r in rs if r['arm'] == 'iso' and r['level'] == 'L4_max' and r['repeat'] == 0 and not r['success']]
    return dict(n_records=len(rs), n_tasks=8, task_menu_conditions=16,
                repeats_outcomes_identical=same_success, repeats_action_summaries_identical=same_actions,
                iso=curves, axis={a: cells([r for r in rs if r['arm'] == a]) for a in ['axis_steps', 'axis_tools', 'axis_vision']},
                low_to_max=dict(task_differences=diffs, mean_difference=mean(diffs.values()),
                                n_improved=sum(x > 0 for x in diffs.values()),
                                n_worse=sum(x < 0 for x in diffs.values()),
                                n_tied=sum(x == 0 for x in diffs.values()),
                                leave_one_task_out=loo, loo_range=[min(loo.values()), max(loo.values())]),
                max_failure_action_examples=actions, model_fingerprint=fp,
                environment=d['environment'], stored_script_sha256=d['script_sha256'])

def allocation(d):
    """Independent algebraic recalculation; never import the original E2 implementation."""
    p, anchors = d['assumed_params'], d['source_anchors']
    s0, k = anchors['s0'], anchors['kappa']
    close(k, math.log(2.5) / 75)
    assert s0 == 5000
    def w(b):
        return (math.log1p((b - 1) / s0) - math.log1p(24 / s0)) / (math.log1p(99 / s0) - math.log1p(24 / s0))
    def value(a):
        b, steps, tools, search, vision = a
        acc = .671 + (.763 - .671) * w(b)
        remaining = math.prod(1 - p['gain_' + n] * (1 - math.exp(-v / p['ref_' + n]))
                              for n, v in zip(['steps', 'tools', 'search', 'vision'], [steps, tools, search, vision]))
        success = min(1., 1 - (1 - acc * (1 - remaining)) * (1 - p['base_success']))
        tokens = (steps * 1200 * math.exp(k * (b - 25)) + steps * p['tokens_per_step_overhead']
                  + (tools + search) * p['tokens_per_tool_call']
                  + search * p['tokens_per_search_call'] + vision * p['tokens_per_vision_op'])
        return success, tokens
    levels = d['grid']['levels']
    grid = [tuple(a) for a in product(*(levels[n] for n in d['axis_names']))]
    assert len(grid) == d['grid']['n_allocations'] == 8820
    values = [(a, *value(a)) for a in grid]
    checks = {}
    for name, baseline in d['baselines'].items():
        a = tuple(baseline['alloc'][n] for n in d['axis_names'])
        s, c = value(a)
        close(s, baseline['success']); close(c, baseline['cost_tokens'])
        best = min((v for v in values if v[1] >= s - 1e-12), key=lambda v: v[2])
        ratio = c / best[2]
        mk = {'B1_all_max':'vs_all_max', 'B2_fixed_mid':'vs_fixed_mid',
              'B3_reason_only_max':'vs_reason_only_max','B4_agent_only_max':'vs_agent_only_max'}[name]
        close(ratio, d['matched_comparisons'][mk]['cost_ratio_baseline_over_unified_at_matched_success'])
        checks[name] = dict(alloc=a, success=s, tokens=c, matched_min_tokens=best[2],
                            matched_achieved_success=best[1], matched_alloc=best[0], cost_ratio=ratio)
    frontier = []
    for row in d['unified_router']['budget_frontier_tokens']:
        eligible = [v for v in values if v[2] <= row['budget_tokens'] + 1e-9]
        best = max(eligible, key=lambda v: v[1])
        close(best[1], row['max_success']); close(best[2], row['cost_tokens'])
        assert list(best[0]) == row['alloc']
        frontier.append(dict(budget_tokens=row['budget_tokens'], success=best[1], alloc=best[0], tokens=best[2]))
    for row in d['unified_router']['target_frontier_tokens']:
        best = min((v for v in values if v[1] >= row['target_success'] - 1e-12), key=lambda v: v[2])
        close(best[2], row['min_cost_tokens'])
    close(w(80), anchors['frontload_fraction_achieved'])
    return dict(n_allocations=len(grid), baselines=checks, token_budget_frontier=frontier,
                frontload_target=anchors['frontload_target_fraction_at_b80'],
                frontload_achieved=w(80), frontload_target_residual=w(80)-anchors['frontload_target_fraction_at_b80'],
                assumed_params=p, source_anchors=anchors,
                warning='Conditional algebraic outputs, not measured LLM cost/success. Independent axes are not constrained to executable trajectories. Original sensitivity compares changed parameters to the unchanged baseline; it is not adopted as a matched robustness test.')

def main():
    docs = {f: load(f) for f in INPUTS}
    e1 = latency(docs[INPUTS[0]]); e1b = latency(docs[INPUTS[1]])
    e3 = docs['e3_agent_loop.json']; er = e3['records']
    assert len(er) == 240
    # E3 did not retain repeat IDs; validate multiplicity, without inventing IDs.
    keys = Counter((r['task'], r['budget_label'], r['schedule']) for r in er)
    assert set(keys) == set(product(TASKS, LEVELS, MENUS))
    assert set(keys.values()) == {3}
    assert all(len({r['success'] for r in er if (r['task'],r['budget_label'],r['schedule']) == key}) == 1 for key in keys)
    for r in er:
        assert r['budget'] == dict(zip(FIELDS, BUDGETS[LEVELS.index(r['budget_label'])]))
    output = dict(scope='Post hoc descriptive audit of retained records, 2026-10-13; no new model experiments.',
                  inputs={f: hashlib.sha256((ROOT/'results'/f).read_bytes()).hexdigest() for f in INPUTS},
                  latency={**e1, **e1b}, e2=allocation(docs['e2_allocation.json']),
                  e3=cells(er, 'budget_label', 'schedule'),
                  h4_8b=h4(docs[INPUTS[4]]), h4_14b=h4(docs[INPUTS[5]]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2, sort_keys=True)+'\n')
    tables = ROOT/'paper/tables'; tables.mkdir(parents=True, exist_ok=True)
    lines = [r'\begin{table}[t]', r'\centering\small',
             r'\caption{Coupled-budget outcomes. Each cell has 48 recorded executions but only eight authored tasks, each tested under two menus and three repeats. Repeats have identical success outcomes. Rates also equal the mean of the eight within-task rates; no independent-sample intervals are implied. E3 uses prescribed schedules and supplied correct code; H4 uses model-selected actions.}',
             r'\label{tab:curves}', r'\begin{tabular}{lrrrrrrr}', r'\toprule',
             r'Budget & Steps & Tools & Obs. chars & Probes & E3 & 8B & 14B \\', r'\midrule']
    for i, (l,b) in enumerate(zip(LEVELS,BUDGETS)):
        lines.append(f'L{i} & {b[0]} & {b[1]} & {b[2]:,} & {b[3]} & '+
                     ' & '.join(f'{output[k][l]["rate"]:.4f}' if k=='e3' else f'{output[k]["iso"][l]["rate"]:.4f}' for k in ['e3','h4_8b','h4_14b'])+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    (tables/'curves.tex').write_text('\n'.join(lines)+'\n')
    lines = [r'\begin{table}[t]',r'\centering\small',
             r'\caption{Within-task success fractions (two menus averaged; repeats do not add new outcomes). The last column gives the L4 minus L1 difference. These eight tasks are fixed authored examples, not a random sample of programming tasks.}',r'\label{tab:tasks}',
             r'\begin{tabular}{lrrrrrr}',r'\toprule',r'& \multicolumn{3}{c}{8B} & \multicolumn{3}{c}{14B} \\',r'Task & L1 & L4 & Difference & L1 & L4 & Difference \\',r'\midrule']
    for t in TASKS:
        vals=[]
        for k in ['h4_8b','h4_14b']:
            c=output[k]['iso']; vals.extend([c['L1_low']['task_rates'][t],c['L4_max']['task_rates'][t],output[k]['low_to_max']['task_differences'][t]])
        lines.append(t[:3]+r' & '+' & '.join(f'{v:.2f}' for v in vals)+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    (tables/'tasks.tex').write_text('\n'.join(lines)+'\n')
    lines=[r'\begin{table}[t]',r'\centering\small',
           r'\caption{Conditional allocation calculation. Modeled success and token costs are algebraic outputs. Minimum cost means the least grid cost attaining at least the baseline modeled success; discrete-grid overshoot is allowed. Ratios are baseline cost divided by that minimum, not measured deployment savings.}',r'\label{tab:allocation}',
           r'\begin{tabular}{lrrrr}',r'\toprule',r'Baseline & Modeled success & Modeled tokens & Minimum cost & Ratio \\',r'\midrule']
    for k,v in output['e2']['baselines'].items():
        name={'B1_all_max':'All maximum','B2_fixed_mid':'Fixed middle','B3_reason_only_max':'Reasoning maximum','B4_agent_only_max':'Agent axes maximum'}[k]
        lines.append(f'{name} & {v["success"]:.4f} & {v["tokens"]:,.0f} & {v["matched_min_tokens"]:,.0f} & {v["cost_ratio"]:.2f}'+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    (tables/'allocation.tex').write_text('\n'.join(lines)+'\n')
    lines=[r'\begin{table}[H]',r'\centering\small',
           r'\caption{All retained latency primitives. Means and standard deviations include failed attempts; counts of successful invocations are separate. Units are milliseconds. These are sequential samples on one host, without a portability or independent-sample interval claim.}',r'\label{tab:latency}',
           r'\begin{tabular}{lrrrr}',r'\toprule',r'Primitive ID & Attempts & Successful & Mean ms & SD ms \\',r'\midrule']
    for k,v in sorted(output['latency'].items(),key=lambda kv:(kv[0][0],int(kv[0].split('_')[0][1:]))):
        lines.append(k.replace('_',r'\_')+f' & {v["n"]} & {v["n_ok"]} & {v["mean_ms"]:.3f} & {v["sd_ms"]:.3f}'+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    (tables/'latency.tex').write_text('\n'.join(lines)+'\n')
    lines=[r'\begin{table}[H]',r'\centering\small',
           r'\caption{Single-axis sweep rates under the probe-enabled menu. Every cell has eight tasks and three repeats (24 executions); other caps remain fixed at steps=8, tools=4, observation characters=1500, probes=2. Those caps can bind. These rates do not isolate a universal marginal resource gain.}',r'\label{tab:axis}',
           r'\begin{tabular}{llrr}',r'\toprule',r'Swept cap & Value & 8B rate & 14B rate \\',r'\midrule']
    for arm in ['axis_steps','axis_tools','axis_vision']:
        keys=sorted(output['h4_8b']['axis'][arm],key=lambda x:int(x.split('=')[1]))
        for l in keys:
            label={'axis_steps':'Steps','axis_tools':'Tools','axis_vision':'Structural probes'}[arm]
            lines.append(f'{label} & {l.split("=")[1]} & {output["h4_8b"]["axis"][arm][l]["rate"]:.4f} & {output["h4_14b"]["axis"][arm][l]["rate"]:.4f}'+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}',r'\end{table}']
    (tables/'axis.tex').write_text('\n'.join(lines)+'\n')
    print('Validated six retained result files; wrote descriptive JSON and five tables.')
    for k in ['h4_8b','h4_14b']: print(k, json.dumps(output[k]['low_to_max']))

if __name__ == '__main__':
    main()
