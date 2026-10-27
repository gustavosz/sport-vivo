#!/usr/bin/env bash
# ==============================================================================
# SPORT-VIVO: Sincronización Diaria y Verificación de Estado
# ==============================================================================
set -e

# Asegurar PATH completo para entornos no interactivos (cron de macOS)
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
LOG_DIR="$ROOT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_sync.log"

mkdir -p "$LOG_DIR"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" | tee -a "$LOG_FILE"
}

log "================================================================="
log "⚽ INICIO DE SINCRONIZACIÓN DIARIA SPORT-VIVO"
log "================================================================="

# 1. Validar y sincronizar IP local
log "🔍 1. Validando configuración de Red e IP local..."
if [ -f "$SCRIPT_DIR/validate_ip.sh" ]; then
    bash "$SCRIPT_DIR/validate_ip.sh" >> "$LOG_FILE" 2>&1 || log "⚠️ Advertencia al validar IP."
fi

# Cargar variables de entorno actualizadas
if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
else
    log "❌ Error: Archivo .env no encontrado en $ROOT_DIR"
    exit 1
fi

# 2. Verificar estado de la cuenta IPTV en la API del proveedor
log "📡 2. Verificando estado de suscripción con el proveedor ($PROVIDER_NAME)..."
STATUS="Unknown"
EXP_DATE="Unknown"

if [ -n "$PROVIDER_SERVER_URL" ] && [ -n "$PROVIDER_USERNAME" ] && [ -n "$PROVIDER_PASSWORD" ]; then
    API_URL="${PROVIDER_SERVER_URL}/player_api.php?username=${PROVIDER_USERNAME}&password=${PROVIDER_PASSWORD}"
    RESPONSE=$(curl -s --connect-timeout 8 --max-time 15 "$API_URL" || true)
    
    if [ -n "$RESPONSE" ]; then
        STATUS=$(echo "$RESPONSE" | python3 -c "import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('user_info', {}).get('status', 'Unknown'))
except Exception:
    print('ParseError')
" 2>/dev/null || echo "ParseError")

        EXP_DATE=$(echo "$RESPONSE" | python3 -c "import sys, json, datetime
try:
    data = json.load(sys.stdin)
    ts = data.get('user_info', {}).get('exp_date')
    if ts:
        print(datetime.datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S'))
    else:
        print('N/A')
except Exception:
    print('N/A')
" 2>/dev/null || echo "N/A")
    fi
fi

log "   → Estado de Cuenta: $STATUS"
log "   → Fecha Expiración: $EXP_DATE"

if [ "$STATUS" != "Active" ]; then
    log "⚠️ AVISO: La cuenta del proveedor figura como '$STATUS'."
    log "   Si acabas de pagar una renovación, contacta al vendedor para que active la línea en su panel."
fi

# 3. Verificar que el contenedor de Dispatcharr esté en ejecución
if ! docker ps --format '{{.Names}}' | grep -q "^dispatcharr$"; then
    log "⚠️ Contenedor Dispatcharr no está activo. Iniciando stack..."
    "$ROOT_DIR/scripts/start.sh" >> "$LOG_FILE" 2>&1 || true
fi

# 4. Si la cuenta está activa, solicitar a Dispatcharr refrescar streams
if [ "$STATUS" = "Active" ]; then
    log "🔄 3. Actualizando lista M3U del proveedor en Dispatcharr..."
    docker exec -i \
        -e PROVIDER_USERNAME="$PROVIDER_USERNAME" \
        dispatcharr su dispatch -c "cd /app && python -c '
import os, django
os.environ.setdefault(\"DJANGO_SETTINGS_MODULE\", \"dispatcharr.settings\")
django.setup()
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import refresh_single_m3u_account
user = os.environ.get(\"PROVIDER_USERNAME\")
acc = M3UAccount.objects.filter(username=user, is_active=True).first()
if acc:
    print(f\"Iniciando refresh para: {acc.name} (ID: {acc.id})\")
    refresh_single_m3u_account(acc.id)
    print(\"Refresh de streams completado.\")
' " >> "$LOG_FILE" 2>&1 || log "⚠️ Advertencia al refrescar cuenta M3U."
else
    log "ℹ️ 3. Omitiendo descarga M3U porque la cuenta está en estado '$STATUS'."
fi

# 5. Sincronizar partidos de River o Boca en Canal 17 (AFA Play) y Canal 18 (Internacional)
log "⚽ 4. Buscando partidos de Boca Juniors o River Plate (Canal 17 AFA Play / Canal 18 Internacional)..."
docker exec -i \
    -e PROVIDER_USERNAME="$PROVIDER_USERNAME" \
    dispatcharr su dispatch -c "cd /app && python - --team auto" < "$ROOT_DIR/src/sync_match.py" >> "$LOG_FILE" 2>&1 || log "⚠️ Advertencia en sync_match."

# 6. Asegurar que el Stream Watcher Daemon esté corriendo
log "🤖 5. Verificando Stream Watcher Daemon..."
bash "$SCRIPT_DIR/daemon.sh" ensure >> "$LOG_FILE" 2>&1 || log "⚠️ Advertencia al verificar el daemon."

log "================================================================="
log "✅ Sincronización diaria completada con éxito."
log "================================================================="
