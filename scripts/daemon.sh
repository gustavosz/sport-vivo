#!/usr/bin/env bash
# ==============================================================================
# SPORT-VIVO: Control del Stream Watcher Daemon
#   Uso: scripts/daemon.sh {start|stop|restart|status|ensure}
#   - ensure: lo levanta solo si no está corriendo (pensado para cron / watchdog).
# ==============================================================================
set -uo pipefail

# PATH completo para entornos no interactivos (cron de macOS)
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTAINER="dispatcharr"
DAEMON_PATH="/app/custom_scripts/stream_daemon.py"
PATTERN='[s]tream_daemon.py'   # Los corchetes evitan que pgrep/pkill se encuentren a sí mismos
LOG_FILE="$ROOT_DIR/logs/stream_daemon.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"
}

daemon_pids() {
    docker exec "$CONTAINER" pgrep -f "$PATTERN" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//'
}

provider_username() {
    if [ -f "$ROOT_DIR/.env" ]; then
        grep -E '^PROVIDER_USERNAME=' "$ROOT_DIR/.env" | tail -n1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'
    fi
}

do_start() {
    mkdir -p "$ROOT_DIR/logs"
    if [ -n "$(daemon_pids)" ]; then
        echo "✅ El daemon ya está corriendo (PID: $(daemon_pids))."
        return 0
    fi
    # stdout/stderr van a /dev/null: el daemon escribe su propio log con rotación.
    docker exec -d -u dispatch -w /app \
        -e PROVIDER_USERNAME="$(provider_username)" \
        "$CONTAINER" sh -c "exec python3 $DAEMON_PATH >/dev/null 2>&1"
    sleep 3
    if [ -n "$(daemon_pids)" ]; then
        echo "✅ Stream Watcher Daemon activo (PID: $(daemon_pids))."
    else
        echo "❌ El daemon no pudo iniciar. Revisa $LOG_FILE"
        return 1
    fi
}

do_stop() {
    if [ -z "$(daemon_pids)" ]; then
        echo "ℹ️ El daemon no estaba corriendo."
        return 0
    fi
    docker exec "$CONTAINER" pkill -TERM -f "$PATTERN" 2>/dev/null || true
    for _ in $(seq 1 15); do
        [ -z "$(daemon_pids)" ] && { echo "🛑 Daemon detenido."; return 0; }
        sleep 1
    done
    echo "⚠️ El daemon no respondió a SIGTERM; forzando cierre."
    docker exec "$CONTAINER" pkill -KILL -f "$PATTERN" 2>/dev/null || true
}

do_status() {
    echo "🤖 Estado del Sport-Vivo Stream Watcher Daemon:"
    if ! container_running; then
        echo "  ❌ El contenedor Dispatcharr no está activo."
        return 0
    fi
    local pids
    pids="$(daemon_pids)"
    if [ -n "$pids" ]; then
        echo "  ✅ Proceso activo (PID: $pids)"
    else
        echo "  ❌ Daemon no está corriendo (usa: make daemon-restart)"
    fi
    echo ""
    echo "📋 Últimos registros:"
    tail -n 15 "$LOG_FILE" 2>/dev/null || echo "  Sin logs todavía."
}

case "${1:-}" in
    start)
        container_running || { echo "❌ El contenedor Dispatcharr no está activo."; exit 1; }
        do_start ;;
    stop)
        container_running || exit 0
        do_stop ;;
    restart)
        container_running || { echo "❌ El contenedor Dispatcharr no está activo."; exit 1; }
        do_stop; do_start ;;
    status)
        do_status ;;
    ensure)
        # Watchdog: silencioso si todo está bien; deja rastro solo si tuvo que actuar.
        container_running || exit 0
        if [ -z "$(daemon_pids)" ]; then
            echo "[$(ts)] ⚠️ Watchdog: daemon caído (¿reinicio del contenedor?). Relanzando..."
            do_start
        fi ;;
    *)
        echo "Uso: $0 {start|stop|restart|status|ensure}"
        exit 2 ;;
esac
