#!/usr/bin/env bash
# ==============================================================================
# SPORT-VIVO: Validación y Sincronización Automática de IP Local
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: No se encontró el archivo .env en $ROOT_DIR"
    exit 1
fi

# 1. Detectar interfaz de red por defecto y la IP asignada en macOS
DEFAULT_IFACE=$(route get default 2>/dev/null | awk '/interface:/ {print $2}')
DETECTED_IP=""

if [ -n "$DEFAULT_IFACE" ]; then
    DETECTED_IP=$(ipconfig getifaddr "$DEFAULT_IFACE" 2>/dev/null || true)
fi

# Fallback por si la ruta no devuelve interfaz directa
if [ -z "$DETECTED_IP" ]; then
    for iface in en0 en1 en2; do
        DETECTED_IP=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
        if [ -n "$DETECTED_IP" ]; then
            break
        fi
    done
fi

if [ -z "$DETECTED_IP" ]; then
    echo "⚠️ No se pudo detectar la IP de red local automáticamente. Manteniendo configuración existente."
    exit 0
fi

# 2. Leer HOST_IP configurada actualmente en .env
CURRENT_CONFIG_IP=$(grep -E '^HOST_IP=' "$ENV_FILE" | head -n 1 | cut -d '=' -f2 | tr -d '"' | tr -d "'" || true)

# 3. Detectar nombre de host local (mDNS)
LOCAL_HOSTNAME="$(scutil --get LocalHostName 2>/dev/null || hostname -s || echo 'MacBook-Pro')"
MDNS_URL="http://${LOCAL_HOSTNAME}.local:9191"

echo "🔍 Verificación de Red Sport-Vivo:"
echo "   → IP Local Detectada : $DETECTED_IP"
echo "   → IP en archivo .env : ${CURRENT_CONFIG_IP:-'(no configurada)'}"
echo "   → URL mDNS Permanente: $MDNS_URL"

# 4. Actualizar .env si la IP cambió
if [ "$DETECTED_IP" != "$CURRENT_CONFIG_IP" ]; then
    echo "⚠️ IP local cambió: '${CURRENT_CONFIG_IP}' -> '${DETECTED_IP}'"
    
    if grep -q '^HOST_IP=' "$ENV_FILE"; then
        # Reemplazar en macOS (sed -i '')
        sed -i '' "s/^HOST_IP=.*/HOST_IP=${DETECTED_IP}/" "$ENV_FILE"
    else
        echo "HOST_IP=${DETECTED_IP}" >> "$ENV_FILE"
    fi
    echo "✅ Archivo .env actualizado con HOST_IP=${DETECTED_IP}"
else
    echo "✅ IP local sincronizada correctamente en .env."
fi

echo ""
echo "📺 Configuración recomendada para TiviMate / Smart TV:"
echo "   • Opción 1 (mDNS - Inmune a cambios de IP): $MDNS_URL"
echo "   • Opción 2 (IP Numérica directa)          : http://${DETECTED_IP}:9191"
echo ""
