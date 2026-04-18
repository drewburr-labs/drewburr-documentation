#!/usr/bin/env bash
# Run Phase 1 benchmarks for all 13 coding model candidates.
# Each model is started fresh on the remote host, benchmarked, then stopped.
#
# Usage:
#   ./run_all_benchmarks.sh [extra args passed to benchmark.py]
#
# Examples:
#   ./run_all_benchmarks.sh
#   ./run_all_benchmarks.sh --tracks perf,track1
#   ./run_all_benchmarks.sh --restart-prod   # restart prod services after last model
#
# Notes:
#   --evalplus (HumanEval+ basic tests) is always included by default.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH="${SCRIPT_DIR}/benchmark.py"

SSH_HOST="drewburr@airunner01.drewburr.com"
API_URL="http://192.168.4.56:8001"

# Models ordered small → large to fail fast on any env issues before committing
# hours of compute to the 70B models.
MODELS=(
    "qwen2.5-coder-7b"
    "deepseek-coder-v2-lite"
    "phi-4"
    "codestral-22b"
    # "gemma4-26b"  # BLOCKED: bitsandbytes quant times out loading in vLLM (needs AWQ)
    "qwen3-30b"
    "qwen2.5-coder-32b"
    "deepseek-r1-qwen-32b"
    "gemma4-31b"
    "qwq-32b"
    # "qwen3-coder-80b"  # BLOCKED: bullpoint/Qwen3-Coder-Next-AWQ-4bit quant broken; need alt source
    "llama3.3-70b"
    "deepseek-r1-llama-70b"
)

TOTAL=${#MODELS[@]}
PASSED=0
FAILED=()
START_TIME=$(date +%s)

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Starting benchmark run: ${TOTAL} models"
log "SSH host: ${SSH_HOST}"
log "API URL:  ${API_URL}"
log ""

for i in "${!MODELS[@]}"; do
    MODEL="${MODELS[$i]}"
    NUM=$((i + 1))

    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "Model ${NUM}/${TOTAL}: ${MODEL}"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    MODEL_START=$(date +%s)

    if stdbuf -oL -eL python3 -u "${BENCH}" "${MODEL}" \
        --api-url "${API_URL}" \
        --ssh-host "${SSH_HOST}" \
        --evalplus \
        "$@" 2>&1; then
        MODEL_END=$(date +%s)
        ELAPSED=$(( MODEL_END - MODEL_START ))
        log "DONE: ${MODEL} in ${ELAPSED}s"
        PASSED=$(( PASSED + 1 ))
    else
        MODEL_END=$(date +%s)
        ELAPSED=$(( MODEL_END - MODEL_START ))
        log "FAILED: ${MODEL} after ${ELAPSED}s — continuing with next model"
        FAILED+=("${MODEL}")
    fi

    log ""
done

END_TIME=$(date +%s)
TOTAL_ELAPSED=$(( END_TIME - START_TIME ))
TOTAL_MIN=$(( TOTAL_ELAPSED / 60 ))

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Run complete: ${PASSED}/${TOTAL} succeeded in ${TOTAL_MIN}m"

if [ ${#FAILED[@]} -gt 0 ]; then
    log "Failed models:"
    for m in "${FAILED[@]}"; do
        log "  - ${m}"
    done
    exit 1
fi
