# H4 harness self-hash is computed at write time, not at load time

Found 2026-09-24 03:00 (+08) while trying to pair two artifacts by `script_sha256`.
Owner of the finding: this session (d0788aa9). No paper number is wrong; the
*provenance field* is, and a gate that reads it can be fooled.

## The defect

`<host>/scripts/h4_real_llm_gx.py`（云端路径；本地对应 `experiments/h4_real_llm_gx.py`）:

```
821: def script_sha256():
822:     """Hash of this file, so a result can be tied to the exact harness revision."""
824:     with open(os.path.abspath(__file__), "rb") as fh:      # reads the DISK file
1180:        "script_sha256": script_sha256(),                  # called at the END of main()
```

The hash is taken when the artifact is written, not when the module was loaded. If the
file on disk changes while a run is in flight, the artifact reports the sha of code that
never executed. That is the one situation the field exists to detect.

## Witness (why this is not hypothetical)

| fact | value | carrier |
|---|---|---|
| 8B new-card control arm started | 02:04:46 | `h4_8bctrl/logs/h4_qwen3_8b_newcard_d0788aa9_20260924_020446.log` |
| harness sha checked at launch | `d35f6d0392d7` (want == got) | `prio4.log`, `h4_arm.log` line "harness want=d35f6d0392d7 got=d35f6d0392d7" |
| persistence patch applied | 02:31:50 | `<host>/scripts/h4_real_llm_gx.py.bak_persist_20260924T023150` |
| control artifact written | 02:34 | `h4_8bctrl/results/h4_real_llm_gx_qwen3_8b_newcard_d0788aa9.json` |
| sha recorded *inside* that artifact | `3326b513fa89` | local copy `h4_artifacts/h4_8b_newcard.json` (sha256 of file c66e4801394265ef, byte-verified against remote) |

So the control's numbers were produced by `d35f6d03`, and the file labels itself
`3326b513`. The label is wrong; the rollouts are fine.

Direction of the error matters: it always reports the *newest* on-disk code, so an
unreviewed mid-run edit gets laundered into an identity that a same-code pairing gate
will happily accept. The old-card baseline (`d35f6d03`) and this control are in truth
the same code -- which is the pairing the paper wants -- but the field now claims they
differ, and in the other direction a real edit could be made to look approved.

## Why no number moves

`h4_inert_test.py` (carrier `h4_inert_proof.txt`, regenerated at every scale-leg launch)
compares patched vs pre-patch final artifacts at identical stub seeds over
`iso_success_curve / gain_fit / floor_cells_excluded_from_fit / stub_gain_recovery /
ref_sensitivity` plus per-record outcome fields: identical, and the comparator catches a
single-field injection. The patch is +54 lines with 0 lines removed, and both added
calls sit outside the numeric path (one before the rollout loop, one after it).

## Fix (prepared, deliberately NOT applied mid-run)

Hash the source once at import into a module constant, and have `script_sha256()`
return that. Applying it now would change the on-disk sha while the 14B/8B pair is in
flight and reproduce this exact bug in the very artifacts being produced, so it goes on
after that leg finishes.

## Handling of the existing artifact

`h4_8b_newcard.json` is not edited -- a measurement artifact must not be rewritten after
the fact. Its true executing code is `d35f6d03`, established by the four independent
carriers above. Any claim that pairs it with the old-card baseline must cite this note,
not the self-reported field.
