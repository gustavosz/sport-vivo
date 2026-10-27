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
WATCHDOG_SCRIPT="$SCRIPT_DIR/daemon.sh"
WATCHDOG_CMD="*/5 * * * * /bin/bash $WATCHDOG_SCRIPT ensure >> $LOG_FILE 2>&1"

echo "⏰ Configurando Cron Jobs para Sport-Vivo..."

# Obtener crontab actual sin fallar si está vacío
CURRENT_CRON=$(crontab -l 2>/dev/null || true)
NEW_CRON="$CURRENT_CRON"

if echo "$CURRENT_CRON" | grep -Fq "$SYNC_SCRIPT"; then
    echo "✅ Sincronización diaria ya instalada."
else
    NEW_CRON=$(printf '%s\n%s\n%s' "$NEW_CRON" "# Sport-Vivo Auto Sync (12:00 y 18:00 hs)" "$CRON_CMD")
    echo "✅ Sincronización diaria agregada: $CRON_CMD"
fi

if echo "$CURRENT_CRON" | grep -Fq "$WATCHDOG_SCRIPT ensure"; then
    echo "✅ Watchdog del daemon ya instalado."
else
    NEW_CRON=$(printf '%s\n%s\n%s' "$NEW_CRON" "# Sport-Vivo Watchdog del Stream Daemon (cada 5 min)" "$WATCHDOG_CMD")
    echo "✅ Watchdog del daemon agregado: $WATCHDOG_CMD"
fi

if [ "$NEW_CRON" != "$CURRENT_CRON" ]; then
    echo "$NEW_CRON" | crontab -
fi

echo ""
echo "📌 Tareas programadas actuales en tu usuario:"
crontab -l
