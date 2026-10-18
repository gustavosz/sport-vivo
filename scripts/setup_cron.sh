#!/usr/bin/env bash
# ==============================================================================
# SPORT-VIVO: Instalador de Cron Job Diario (macOS)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/daily_sync.sh"
LOG_FILE="$ROOT_DIR/logs/cron.log"

mkdir -p "$ROOT_DIR/logs"

CRON_CMD="0 12,18 * * * /bin/bash $SYNC_SCRIPT >> $LOG_FILE 2>&1"

echo "⏰ Configurando Cron Job diario para Sport-Vivo..."

# Obtener crontab actual sin fallar si está vacío
CURRENT_CRON=$(crontab -l 2>/dev/null || true)

if echo "$CURRENT_CRON" | grep -Fq "$SYNC_SCRIPT"; then
    echo "✅ El cron job ya está instalado en el sistema:"
    echo "$CURRENT_CRON" | grep -F "$SYNC_SCRIPT"
else
    # Agregar tarea al crontab
    (echo "$CURRENT_CRON"; echo "# Sport-Vivo Auto Sync (12:00 y 18:00 hs)"; echo "$CRON_CMD") | crontab -
    echo "✅ Cron job instalado con éxito en crontab:"
    echo "   $CRON_CMD"
fi

echo ""
echo "📌 Tareas programadas actuales en tu usuario:"
crontab -l
