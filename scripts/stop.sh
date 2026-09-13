#!/usr/bin/env bash
# ==============================================================================
# SPORT-VIVO: Detener Stack de Streaming
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

echo "============================================================"
echo "🛑 Deteniendo Stack Sport-Vivo (Dispatcharr)"
echo "============================================================"

docker compose down

echo "✅ Servicios detenidos correctamente. Los datos persisten en ./data."
echo "============================================================"
