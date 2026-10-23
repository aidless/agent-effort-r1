#!/usr/bin/env bash
# queue rule: GPU use is serialised through /root/autodl-tmp/gpu.lock with flock,
# priority P1 > P4 > P2. This script never bypasses the lock and never steals it:
# with -n it fails fast instead of queueing, so a lower-priority job cannot starve
# a higher-priority one.
#
#   ./h4_queue_step.sh                 # try to run now, fail fast if not free
#   LOCK_WAIT=1800 ./h4_queue_step.sh  # queue up to 30 min for the lock
#
# Preconditions checked BEFORE touching the GPU:
#   free VRAM >= the model's footprint + 2 GiB headroom (model-size aware)
set -u
ROOT=/root/autodl-tmp/p2_agent_effort
LOCK=/root/autodl-tmp/gpu.lock
MODEL=${MODEL:-/root/autodl-tmp/models/Qwen3-8B-AWQ}
OUT=${OUT:-$ROOT/results/h4_gx_qwen.json}
REPEATS=${REPEATS:-3}
LOCK_WAIT=${LOCK_WAIT:-0}
EXPECTED_MIB=${EXPECTED_MIB:-0}

cd "$ROOT" || exit 9

free_mib() {
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' '
}

# model-size aware headroom (AWQ int4 weights ≈ params/2 bytes + activations + KV)
if [ "$EXPECTED_MIB" -eq 0 ]; then
  case "$MODEL" in
    *14B*) EXPECTED_MIB=20000 ;;
    *8B*)  EXPECTED_MIB=15000 ;;
    *)     EXPECTED_MIB=25000 ;;
  esac
fi
NEED=$((EXPECTED_MIB + 2048))

F=$(free_mib)
echo "[h4] model=$MODEL free=${F}MiB need>=${NEED}MiB"
if [ -z "$F" ] || [ "$F" -lt "$NEED" ]; then
  echo "[h4] ABORT: insufficient free VRAM (P1/P4 work in flight). Not touching the GPU."
  exit 3
fi

FLAGS="-n"
[ "$LOCK_WAIT" -gt 0 ] && FLAGS="-w $LOCK_WAIT"

echo "[h4] acquiring flock $LOCK $FLAGS"
if ! flock $FLAGS "$LOCK" /bin/bash -c '
  cd /root/autodl-tmp/p2_agent_effort
  F=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1 | tr -d " ")
  echo "[h4] lock acquired, free=${F}MiB"
  python3 scripts/h4_gx_measure.py \
    --model "'"$MODEL"'" \
    --out "'"$OUT"'" \
    --repeats "'"$REPEATS"'" \
    --min-free-mib "'"$EXPECTED_MIB"'" \
    --tasks all
'; then
  echo "[h4] could not acquire the lock in time (higher-priority job holds it). Exiting without GPU use."
  exit 4
fi

echo "[h4] done -> $OUT"
ls -la "$OUT" 2>/dev/null || true
