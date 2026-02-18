#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/input /app/output /app/sam3_output /app/models

if [[ ! -f /app/models/sam3.pt ]] && [[ -n "${SAM3_CHECKPOINT_URL:-}" ]]; then
  echo "[bootstrap] downloading sam3.pt ..."
  curl -L "${SAM3_CHECKPOINT_URL}" -o /app/models/sam3.pt
fi

if [[ ! -f /app/models/bpe_simple_vocab_16e6.txt.gz ]] && [[ -n "${SAM3_BPE_URL:-}" ]]; then
  echo "[bootstrap] downloading bpe vocab ..."
  curl -L "${SAM3_BPE_URL}" -o /app/models/bpe_simple_vocab_16e6.txt.gz
fi

exec python /app/server_pa.py
