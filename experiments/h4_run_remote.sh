#!/usr/bin/env bash
# h4_run_remote.sh — run the H4 measurement on the GPU host under the shared lock.
#
# Layout-agnostic: the harness dir is derived from this script's own location, so
# it works as experiments/ locally and as scripts/ on the GPU host.
#
# GPU discipline (queue rule):
#   * one host-wide lock ($LOCK), held with flock (NON-BLOCKING:
#     if the lock is held this is not our turn, and queueing silently would hide
#     the contention from the operator)
#   * priority P1 > P2(H4) > P7(H3) > P4; this is the P2 step
#   * ABORT (never bypass the lock) when free VRAM < FLOOR_MIB
#   * all outputs and ALL caches under $WORK -- the root partition can be small
#     and vLLM/torch will fill it if left to their defaults
#
# Usage:
#   bash <dir>/h4_run_remote.sh
#   MODEL=$MODEL_DIR/Qwen3-14B-AWQ LOCK=$H4_GPU_LOCK WORK=$H4_WORK TAG=qwen3_14b bash <dir>/h4_run_remote.sh
set -uo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAPER_ROOT="$(dirname "$HARNESS_DIR")"

MODEL="${MODEL:?set MODEL to the local AWQ checkpoint path}"
REPEATS="${REPEATS:-3}"
TAG="${TAG:-qwen3_8b}"
ARMS="${ARMS:-iso,axis_steps,axis_tools,axis_vision}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
MAX_TOKENS="${MAX_TOKENS:-1024}"
LOCK="${LOCK:?set LOCK to the shared host lock path}"
WORK="${WORK:?set WORK to a scratch dir with space for results}"
OUT="${OUT:-$WORK/results/h4_real_llm_gx_${TAG}.json}"
LOG="$WORK/logs/h4_${TAG}_$(date +%Y%m%d_%H%M%S).log"
FAIL_LOG="$WORK/logs/h4_${TAG}_failures.log"

# VRAM floor, model-size aware: the 14B AWQ weights (~9.4 GB) plus the KV cache
# for a long context need more headroom than the 8B (~5.7 GB).
case "$MODEL" in
  *14B*) FLOOR_MIB="${FLOOR_MIB:-30000}" ;;
  *)     FLOOR_MIB="${FLOOR_MIB:-25600}" ;;
esac

echo "== H4 real run =="
echo "harness dir  : $HARNESS_DIR"
echo "paper root   : $PAPER_ROOT"
echo "model        : $MODEL"
echo "out          : $OUT"
echo "log          : $LOG"
echo "floor (MiB)  : $FLOOR_MIB"
echo "repeats/cell : $REPEATS"
echo "arms         : $ARMS"

if [ ! -e "$MODEL" ]; then
  echo "ABORT: model path does not exist: $MODEL" >&2
  exit 2
fi
if [ ! -e "$LOCK" ]; then
  echo "ABORT: shared GPU lock is missing: $LOCK" >&2
  exit 2
fi

mkdir -p "$WORK/results" "$WORK/logs"

# Keep every cache off the ~1.1 GB root partition.
export TMPDIR="$WORK/tmp"
export VLLM_CACHE_ROOT="$WORK/cache/vllm"
export HF_HOME="$WORK/cache/hf"
export XDG_CACHE_HOME="$WORK/cache"
export TRITON_CACHE_DIR="$WORK/cache/triton"
# vLLM 0.27.1 defaults VLLM_USE_FLASHINFER_SAMPLER=1, but this image ships no
# `flashinfer` module, so the EngineCore dies at startup with
#   ModuleNotFoundError: No module named 'flashinfer'
# (measured 2026-09-11 23:25). The native sampler is used instead; the flag is
# recorded in the result JSON via the environment block.
export VLLM_USE_FLASHINFER_SAMPLER=0
mkdir -p "$TMPDIR" "$VLLM_CACHE_ROOT" "$HF_HOME" "$XDG_CACHE_HOME" "$TRITON_CACHE_DIR"

FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d ' ')
echo "free VRAM    : ${FREE} MiB"
if [ "$FREE" -lt "$FLOOR_MIB" ]; then
  echo "ABORT: free VRAM ${FREE} < ${FLOOR_MIB}; the lock is NOT bypassed." >&2
  echo "       another job holds the GPU (priority P1 > P2). Retry after it finishes." >&2
  exit 3
fi

{
  echo "--- start $(date -Is) ---"
  if ! flock -n "$LOCK" /bin/bash -c "
      set -uo pipefail
      cd '$PAPER_ROOT'
      # The lock is already held by this wrapper.  The harness must NOT take it
      # again: flock() treats two fds on the same file as independent, so a
      # nested acquire on the outer lock is DENIED and the run would abort.
      export H4_GPU_LOCK_HELD=1
      python3 '$HARNESS_DIR/h4_real_llm_gx.py' \
        --backend vllm \
        --external-lock \
        --gpu-lock '$LOCK' \
        --model '$MODEL' \
        --repeats '$REPEATS' \
        --arms '$ARMS' \
        --max-model-len '$MAX_MODEL_LEN' \
        --max-tokens '$MAX_TOKENS' \
        --out '$OUT' \
        --ref-sensitivity
  "; then
    echo "ABORT: could not take $LOCK (held by another job) or the run failed." >&2
    exit 4
  fi
  echo "--- done $(date -Is) ---"
} 2>&1 | tee "$LOG"

RC=${PIPESTATUS[0]}

# failure log: abort/OOM/timeout reasons, kept separable from the run log
grep -iE "ABORT|ERROR|Traceback|OOM|out of memory|timeout" "$LOG" > "$FAIL_LOG" 2>/dev/null || true

echo
echo "artifacts:"
echo "  $OUT"
echo "  $LOG"
echo "  $FAIL_LOG ($(wc -l < "$FAIL_LOG" 2>/dev/null || echo 0) lines)"
exit $RC
