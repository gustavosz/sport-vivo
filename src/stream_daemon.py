#!/usr/bin/env python3
"""
src/stream_daemon.py
--------------------
SPORT-VIVO: Stream Watcher Daemon.

1. Vigilancia de pantalla negra / stream zombi (cero conexiones extra al proveedor):
   - Lee las métricas que Dispatcharr ya publica en Redis (live:channel:<uuid>:metadata).
   - Solo actúa si el canal está ACTIVE, lleva >= MIN_UPTIME_BEFORE_AUDIT_SEC al aire,
     acumula LOW_SAMPLES_REQUIRED lecturas bajas CONSECUTIVAS y está fuera del cooldown.
   - Canales 01/02 (ESPN Premium / TNT Sports): NUNCA cambian de contenido. Solo se
     usan variantes de la MISMA señal argentina; si no existen, se fuerza una reconexión.
   - Canales 17/18: siguiente candidato del mismo partido y la misma plataforma.
   - El cambio se hace en caliente con ChannelService.change_stream_url (el mismo
     mecanismo que el "switch stream" de la UI). No se toca la asignación en la base
     de datos, así que cuando el canal vuelve a arrancar usa su stream original.
2. Auto-sincronización de partidos (Canal 17 AFA Play / Canal 18 Internacional) cada
   MATCH_SYNC_INTERVAL_SEC, delegada en sync_match.sync_event_channels().
3. Instancia única garantizada con flock (sin PID files usados para matar procesos).
"""

import os
import sys
import re
import time
import fcntl
import signal
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

# -----------------------------------------------------------------------------
# Entorno Django / Dispatcharr
# -----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in ('/app', SCRIPT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
import django
django.setup()

from django.db import close_old_connections

# Lógica de partidos compartida (zona horaria AR, filtros, asignación de canales)
import sync_match as sm

from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.live_proxy.services.channel_service import ChannelService

import redis

# -----------------------------------------------------------------------------
# Logging (con rotación; sin duplicar líneas cuando stdout se redirige al mismo archivo)
# -----------------------------------------------------------------------------
LOG_DIR = os.environ.get("SPORT_VIVO_LOG_DIR") or ("/app/custom_logs" if os.path.isdir("/app/custom_logs") else "/tmp")
LOG_FILE = os.path.join(LOG_DIR, "stream_daemon.log")
LOCK_FILE = os.path.join(LOG_DIR, "stream_daemon.lock")
PID_FILE = os.path.join(LOG_DIR, "stream_daemon.pid")  # Solo informativo

logger = logging.getLogger("SportVivoDaemon")
logger.setLevel(logging.INFO)
logger.propagate = False
_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
# El contenedor corre en UTC: mostrar las horas del log en hora argentina.
_formatter.converter = lambda secs: datetime.fromtimestamp(secs, sm.ART).timetuple()
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
_fh.setFormatter(_formatter)
logger.addHandler(_fh)
if sys.stdout.isatty():
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_formatter)
    logger.addHandler(_sh)

# -----------------------------------------------------------------------------
# Constantes de operación
# -----------------------------------------------------------------------------
BITRATE_ZOMBIE_THRESHOLD_KBPS = 350.0  # El bucle negro del proveedor mide ~192 kbps; HD > 2500 kbps
MIN_UPTIME_BEFORE_AUDIT_SEC = 30       # ffmpeg reporta bitrates bajos mientras arranca
LOW_SAMPLES_REQUIRED = 4               # Lecturas bajas consecutivas (~32 s) antes de actuar
FAILOVER_COOLDOWN_SEC = 300            # Mínimo entre dos acciones sobre el mismo canal
CYCLE_INTERVAL_SEC = 8                 # Intervalo de chequeo de streams activos
MATCH_SYNC_INTERVAL_SEC = 300          # Auto-sincronización de partidos (5 min)
LIVE_LOG_INTERVAL_SEC = 300            # Frecuencia del log informativo por canal en vivo

# Canales con señal fija: solo se aceptan variantes argentinas de la misma señal.
FIXED_SIGNAL_CHANNELS = {
    1: 'espn premium',
    2: 'tnt sports',
}
_ARG_TOKEN = re.compile(r'(^|[^a-z])arg([^a-z]|$)', re.IGNORECASE)


class SportVivoDaemon:
    def __init__(self):
        self.running = True
        self.redis_client = redis.Redis(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            db=int(os.environ.get('REDIS_DB', 0)),
            decode_responses=True,
        )
        self.last_match_sync = 0.0
        self.channel_state = {}  # uuid -> {"stream_id", "low", "last_log"}
        self.last_action = {}    # uuid -> timestamp (persiste aunque el canal se detenga)
        self._lock_fd = None

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    # -------------------------------------------------------------------------
    # Ciclo de vida
    # -------------------------------------------------------------------------
    def _handle_signal(self, signum, frame):
        logger.info(f"Señal recibida ({signum}). Deteniendo Sport-Vivo Daemon limpiamente...")
        self.running = False

    def _acquire_lock(self):
        """Garantiza una sola instancia. El lock se libera solo si el proceso muere."""
        fd = open(LOCK_FILE, 'a+')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            return False
        self._lock_fd = fd
        try:
            with open(PID_FILE, 'w') as f:
                f.write(str(os.getpid()))
        except OSError:
            pass
        return True

    def _release_lock(self):
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except OSError:
            pass
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
            except OSError:
                pass

    # -------------------------------------------------------------------------
    # 1. Monitoreo de bitrate y detección de pantalla negra (zombi)
    # -------------------------------------------------------------------------
    def audit_active_channels(self):
        """Inspecciona en Redis los canales con clientes conectados."""
        seen = set()
        try:
            keys = list(self.redis_client.scan_iter(match="live:channel:*:metadata", count=100))
        except Exception as e:
            logger.error(f"Error consultando Redis: {e}")
            return

        for metadata_key in keys:
            channel_id = metadata_key.split(":")[2]
            seen.add(channel_id)
            try:
                self._audit_channel(channel_id, metadata_key)
            except Exception as ex:
                logger.error(f"Error auditando canal {channel_id}: {ex}", exc_info=True)

        # Olvidar contadores de canales que ya no existen (el cooldown se conserva)
        for cid in list(self.channel_state):
            if cid not in seen:
                del self.channel_state[cid]

    def _audit_channel(self, channel_id, metadata_key):
        client_count = self.redis_client.scard(RedisKeys.clients(channel_id)) or 0
        if client_count == 0:
            self.channel_state.pop(channel_id, None)  # Sin clientes: nada que vigilar
            return

        md = self.redis_client.hgetall(metadata_key)
        if not md or md.get(ChannelMetadataField.STATE) != ChannelState.ACTIVE:
            return

        channel_name = md.get(ChannelMetadataField.CHANNEL_NAME, "Desconocido")
        stream_id = md.get(ChannelMetadataField.STREAM_ID, "")
        stream_name = md.get(ChannelMetadataField.STREAM_NAME, "")
        try:
            init_time = float(md.get(ChannelMetadataField.INIT_TIME) or 0)
        except (TypeError, ValueError):
            init_time = 0.0

        st = self.channel_state.setdefault(channel_id, {"stream_id": stream_id, "low": 0, "last_log": 0.0})
        if st["stream_id"] != stream_id:
            st.update(stream_id=stream_id, low=0)  # Cambió el stream: empezar de cero

        now = time.time()
        uptime = now - init_time if init_time > 0 else 0
        if uptime < MIN_UPTIME_BEFORE_AUDIT_SEC:
            return

        bitrate_str = md.get(ChannelMetadataField.FFMPEG_OUTPUT_BITRATE) or md.get(ChannelMetadataField.FFMPEG_BITRATE)
        if not bitrate_str:
            return  # Sin métrica confiable no se juzga el stream
        try:
            bitrate = float(bitrate_str)
        except ValueError:
            return

        if now - st["last_log"] >= LIVE_LOG_INTERVAL_SEC:
            logger.info(
                f"📺 [En vivo] {channel_name} ({stream_name}) | Clientes: {client_count} | "
                f"Uptime: {uptime:.0f}s | Bitrate: {bitrate:.1f} kbps"
            )
            st["last_log"] = now

        if bitrate <= 0 or bitrate >= BITRATE_ZOMBIE_THRESHOLD_KBPS:
            if st["low"]:
                logger.info(f"✅ {channel_name}: bitrate normalizado ({bitrate:.1f} kbps).")
            st["low"] = 0
            return

        st["low"] += 1
        if st["low"] < LOW_SAMPLES_REQUIRED:
            logger.warning(f"⚠️ {channel_name}: bitrate bajo {bitrate:.1f} kbps ({st['low']}/{LOW_SAMPLES_REQUIRED})")
            return

        since_last = now - self.last_action.get(channel_id, 0)
        if since_last < FAILOVER_COOLDOWN_SEC:
            if st["low"] == LOW_SAMPLES_REQUIRED:
                logger.warning(
                    f"⏳ {channel_name}: sigue en bitrate bajo, en cooldown "
                    f"({FAILOVER_COOLDOWN_SEC - since_last:.0f}s restantes)."
                )
            return

        self.last_action[channel_id] = now
        st["low"] = 0
        logger.warning(
            f"🚨 PANTALLA NEGRA / STREAM ZOMBI CONFIRMADO 🚨 Canal: {channel_name} | "
            f"Stream: {stream_name} (ID: {stream_id}) | Bitrate: {bitrate:.1f} kbps "
            f"durante {LOW_SAMPLES_REQUIRED} lecturas seguidas"
        )
        self._handle_zombie(channel_id, stream_id)

    def _handle_zombie(self, channel_id, current_stream_id):
        channel = sm.Channel.objects.filter(uuid=channel_id).first()
        if not channel:
            logger.warning(f"No se encontró el canal con UUID {channel_id} en la base de datos.")
            return

        ch_num = int(channel.channel_number)
        cur = int(current_stream_id) if str(current_stream_id).isdigit() else None
        alt = self._find_alternate(ch_num, cur)

        if alt:
            logger.info(f"🔁 Canal {ch_num}: cambio en caliente a [{alt.id}] {alt.name}")
            result = ChannelService.change_stream_url(channel_id, target_stream_id=alt.id)
            status = result.get('status') if isinstance(result, dict) else None
            if status in ('success', 'recovered'):
                logger.info(f"✅ Canal {ch_num}: cambio aplicado. La asignación original en la base no se modificó.")
                return
            logger.warning(f"Canal {ch_num}: el cambio en caliente falló ({result}). Se fuerza reconexión.")
        else:
            logger.info(f"Canal {ch_num}: no hay variante de la misma señal disponible. Se fuerza reconexión.")

        result = ChannelService.stop_channel(channel_id)
        logger.info(f"🔄 Canal {ch_num}: reconexión solicitada ({result.get('status') if isinstance(result, dict) else result}). "
                    f"El reproductor debería reconectar solo.")

    @staticmethod
    def _last_known_bitrate(stream):
        """Último bitrate medido por Dispatcharr para el stream (Stream.stream_stats), o None."""
        stats = getattr(stream, 'stream_stats', None) or {}
        try:
            value = stats.get('ffmpeg_output_bitrate')
            return float(value) if value is not None else None
        except (AttributeError, TypeError, ValueError):
            return None

    def _pick_healthy(self, streams):
        """Descarta streams que ya se midieron como pantalla negra; prefiere los verificados."""
        verified, unknown = [], []
        for s in streams:
            last = self._last_known_bitrate(s)
            if last is None:
                unknown.append(s)
            elif last >= BITRATE_ZOMBIE_THRESHOLD_KBPS:
                verified.append(s)
            else:
                logger.info(f"   Descartada alternativa [{s.id}] {s.name}: último bitrate conocido {last:.0f} kbps.")
        return (verified + unknown)[0] if (verified or unknown) else None

    def _find_alternate(self, ch_num, current_stream_id):
        """Stream alternativo que NO cambia el contenido del canal, o None."""
        account = sm.get_active_account()
        if not account:
            return None

        if ch_num in FIXED_SIGNAL_CHANNELS:
            qs = sm.Stream.objects.filter(
                m3u_account=account, name__icontains=FIXED_SIGNAL_CHANNELS[ch_num]
            ).exclude(id=current_stream_id).order_by('id')
            return self._pick_healthy([s for s in qs if _ARG_TOKEN.search(s.name)])

        if ch_num in sm.EVENT_CHANNELS:
            pool = [c for c in sm.find_candidates(account) if sm.channel_accepts(ch_num, c[3].name)]
            team = next((c[1] for c in pool if c[3].id == current_stream_id), None)
            return self._pick_healthy([
                s for _, matched_team, _, s in pool
                if s.id != current_stream_id and (team is None or matched_team == team)
            ])

        return None  # Resto de los canales: solo reconexión

    # -------------------------------------------------------------------------
    # 2. Sincronización automática de partidos (Canal 17 y Canal 18)
    # -------------------------------------------------------------------------
    def auto_sync_matches(self):
        try:
            sm.sync_event_channels(log=logger.info)
        except Exception as e:
            logger.error(f"Error en auto-sincronización de partidos: {e}", exc_info=True)

    # -------------------------------------------------------------------------
    # Bucle principal
    # -------------------------------------------------------------------------
    def start(self):
        if not self._acquire_lock():
            logger.info("Ya hay una instancia del daemon en ejecución. Saliendo.")
            return

        logger.info("=" * 65)
        logger.info(f"🚀 SPORT-VIVO: STREAM WATCHER DAEMON INICIADO (PID {os.getpid()})")
        logger.info(f"   • Chequeo de bitrate : cada {CYCLE_INTERVAL_SEC}s, umbral < {BITRATE_ZOMBIE_THRESHOLD_KBPS} kbps, "
                    f"{LOW_SAMPLES_REQUIRED} lecturas seguidas, cooldown {FAILOVER_COOLDOWN_SEC}s")
        logger.info(f"   • Auto-sync partidos : cada {MATCH_SYNC_INTERVAL_SEC}s (hora AR: {sm.local_now():%Y-%m-%d %H:%M})")
        logger.info("=" * 65)

        try:
            while self.running:
                try:
                    close_old_connections()  # Evita conexiones a Postgres caducadas
                    self.audit_active_channels()
                    if (time.time() - self.last_match_sync) >= MATCH_SYNC_INTERVAL_SEC:
                        self.auto_sync_matches()
                        self.last_match_sync = time.time()
                except Exception as e:
                    logger.error(f"Error inesperado en ciclo del daemon: {e}", exc_info=True)

                for _ in range(CYCLE_INTERVAL_SEC):
                    if not self.running:
                        break
                    time.sleep(1)
        finally:
            self._release_lock()
            logger.info("🛑 Sport-Vivo Daemon finalizado correctamente.")


if __name__ == '__main__':
    SportVivoDaemon().start()
