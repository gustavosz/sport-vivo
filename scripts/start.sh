#!/usr/bin/env bash
# ==============================================================================
# SPORT-VIVO: Iniciar Stack de Streaming
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

echo "============================================================"
echo "⚽ Iniciando Stack Sport-Vivo (Dispatcharr)"
echo "============================================================"

# 1. Validar existencia de .env
if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "❌ Error: No se encontró el archivo .env en $ROOT_DIR"
    echo "💡 Copia la plantilla y completa tus credenciales:"
    echo "   cp .env.example .env"
    exit 1
fi

# Exportar variables del .env
set -a
source "$ROOT_DIR/.env"
set +a

DISPATCHARR_PORT="${DISPATCHARR_PORT:-9191}"
HOST_IP="${HOST_IP:-127.0.0.1}"
DOCKER_NETWORK="${DOCKER_NETWORK:-media-net}"

# 2. Asegurar que la red externa de Docker exista (para compartir con Jellyfin)
if ! docker network inspect "$DOCKER_NETWORK" >/dev/null 2>&1; then
    echo "🌐 Creando red externa de Docker: $DOCKER_NETWORK..."
    docker network create "$DOCKER_NETWORK"
else
    echo "🌐 Red Docker '$DOCKER_NETWORK' verificada."
fi

# 3. Levantar contenedor con Docker Compose
echo "🚀 Levantando servicios con Docker Compose..."
docker compose up -d

# 4. Esperar que Dispatcharr esté listo
echo "⏳ Esperando que Dispatcharr responda en http://localhost:${DISPATCHARR_PORT}..."
MAX_RETRIES=30
RETRY_COUNT=0
HEALTHY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${DISPATCHARR_PORT}/" || true)
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
        HEALTHY=true
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 2
done

if [ "$HEALTHY" = false ]; then
    echo "⚠️ Advertencia: Dispatcharr tardó más de lo esperado en responder. Verificando logs..."
    docker compose logs --tail=20 dispatcharr
else
    echo "✅ Dispatcharr en línea y saludable (HTTP $HTTP_CODE)."
fi

# 5. Ejecutar aprovisionamiento / sincronización automática
echo "🔄 Sincronizando configuración, canales y EPG..."
docker exec -i \
    -e ADMIN_USERNAME="$ADMIN_USERNAME" \
    -e ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    -e CLIENT_USERNAME="$CLIENT_USERNAME" \
    -e CLIENT_PASSWORD="$CLIENT_PASSWORD" \
    -e PROVIDER_NAME="$PROVIDER_NAME" \
    -e PROVIDER_SERVER_URL="$PROVIDER_SERVER_URL" \
    -e PROVIDER_USERNAME="$PROVIDER_USERNAME" \
    -e PROVIDER_PASSWORD="$PROVIDER_PASSWORD" \
    -e PROVIDER_MAX_STREAMS="$PROVIDER_MAX_STREAMS" \
    -e EPG_NAME="$EPG_NAME" \
    -e EPG_URL="$EPG_URL" \
    dispatcharr su - dispatch -c "cd /app && python -" < "$SCRIPT_DIR/provision.py"

# 6. Banner informativo final
echo ""
echo "============================================================"
echo "🎉 STACK SPORT-VIVO ACTIVO Y LISTO PARA USAR"
echo "============================================================"
echo "🖥️  Panel Web UI:         http://localhost:${DISPATCHARR_PORT}"
echo "    Usuario Admin:        ${ADMIN_USERNAME}"
echo "    Contraseña:           ${ADMIN_PASSWORD}"
echo ""
echo "📺 Conexión TiviMate / Smart TV (Xtream Codes API):"
echo "    Server / URL:         http://${HOST_IP}:${DISPATCHARR_PORT}"
echo "    Username:             ${CLIENT_USERNAME}"
echo "    Password:             ${CLIENT_PASSWORD}"
echo ""
echo "🔗 URLs Directas M3U / EPG (LAN):"
echo "    M3U Playlist:         http://${HOST_IP}:${DISPATCHARR_PORT}/output/m3u?username=${CLIENT_USERNAME}&password=${CLIENT_PASSWORD}"
echo "    EPG Guía XMLTV:       http://${HOST_IP}:${DISPATCHARR_PORT}/output/epg?username=${CLIENT_USERNAME}&password=${CLIENT_PASSWORD}"
echo ""
echo "🍿 Integración Jellyfin (Red interna Docker):"
echo "    M3U Tuner:            http://dispatcharr:${DISPATCHARR_PORT}/output/m3u?username=${CLIENT_USERNAME}&password=${CLIENT_PASSWORD}"
echo "    XMLTV Guide:          http://dispatcharr:${DISPATCHARR_PORT}/output/epg?username=${CLIENT_USERNAME}&password=${CLIENT_PASSWORD}"
echo "============================================================"
