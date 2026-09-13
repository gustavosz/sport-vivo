#!/usr/bin/env python3
"""
scripts/provision.py
--------------------
Script idempotente de aprovisionamiento para Dispatcharr en Sport-Vivo.
Configura o actualiza:
  1. Superusuario administrador (Web UI)
  2. Proveedor IPTV (Xtream Codes / M3U) con límite de conexiones (Pool protection)
  3. Usuario cliente (TiviMate / Jellyfin) con emulación Xtream Codes
  4. Grupo y canales deportivos curados con streams de failover
  5. Fuente EPG externa y vinculación a canales
"""

import os
import sys
import django

# Inicializar Django dentro del contenedor de Dispatcharr
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
django.setup()

from django.apps import apps
from django.contrib.auth import get_user_model

User = get_user_model()
M3UAccount = apps.get_model('m3u', 'M3UAccount')
EPGSource = apps.get_model('epg', 'EPGSource')
EPGData = apps.get_model('epg', 'EPGData')
Channel = apps.get_model('dispatcharr_channels', 'Channel')
ChannelGroup = apps.get_model('dispatcharr_channels', 'ChannelGroup')
ChannelStream = apps.get_model('dispatcharr_channels', 'ChannelStream')
Stream = apps.get_model('dispatcharr_channels', 'Stream')
Logo = apps.get_model('dispatcharr_channels', 'Logo')
from dispatcharr.redis_client import RedisClient

# Variables desde el entorno (con defaults)
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Futbol2026*')

CLIENT_USERNAME = os.environ.get('CLIENT_USERNAME', 'tv_living')
CLIENT_PASSWORD = os.environ.get('CLIENT_PASSWORD', 'Futbol2026*')

# Variables de Proveedores IPTV
PROVIDER_NAME = os.environ.get('PROVIDER_NAME', 'Eagle 4K - Deportes AR')
PROVIDER_SERVER_URL = os.environ.get('PROVIDER_SERVER_URL', 'http://178015641313.eg4k-pass.my:80')
PROVIDER_USERNAME = os.environ.get('PROVIDER_USERNAME', '5mk2559fl3')
PROVIDER_PASSWORD = os.environ.get('PROVIDER_PASSWORD', 'ljiktoy94a')
PROVIDER_MAX_STREAMS = int(os.environ.get('PROVIDER_MAX_STREAMS', '1'))

BACKUP_PROVIDER_NAME = os.environ.get('BACKUP_PROVIDER_NAME', 'Trex OTT - Deportes AR')
BACKUP_PROVIDER_SERVER_URL = os.environ.get('BACKUP_PROVIDER_SERVER_URL', 'http://pro.business-cdn-8k.com')
BACKUP_PROVIDER_USERNAME = os.environ.get('BACKUP_PROVIDER_USERNAME', '2b8f2ea7f112')
BACKUP_PROVIDER_PASSWORD = os.environ.get('BACKUP_PROVIDER_PASSWORD', 'daa71567cf')
BACKUP_PROVIDER_MAX_STREAMS = int(os.environ.get('BACKUP_PROVIDER_MAX_STREAMS', '1'))

EPG_NAME = os.environ.get('EPG_NAME', 'EPG Argentina')
EPG_URL = os.environ.get('EPG_URL', 'https://jarap.github.io/iptv-epg-argentina/epg.xml.gz')

print("=" * 60)
print("🚀 SPORT-VIVO: Aprovisionamiento y Sincronización")
print("=" * 60)

# Limpieza segura de contadores de conexión huérfanos en Redis (solo si no hay streams activos)
try:
    _r = RedisClient.get_client()
    if _r:
        _active = _r.keys("live:channel:*:clients:*")
        if not _active:
            for _k in _r.keys("profile_connections:*"):
                _r.set(_k, 0)
            print("🧹 Contadores de conexión Redis inicializados en 0 (sin streams activos).")
        else:
            print("ℹ️ Stream activo detectado en Redis. Omitiendo reseteo de contadores de conexión.")
except Exception as _e:
    pass

# -----------------------------------------------------------------------------
# 1. Superusuario Administrador
# -----------------------------------------------------------------------------
admin_user, created = User.objects.get_or_create(
    username=ADMIN_USERNAME,
    defaults={'is_superuser': True, 'is_staff': True, 'is_active': True}
)
admin_user.set_password(ADMIN_PASSWORD)
admin_user.is_superuser = True
admin_user.is_staff = True
admin_user.is_active = True
admin_user.save()
action_text = "Creado" if created else "Actualizado"
print(f"✅ Superusuario admin: {admin_user.username} ({action_text})")

# -----------------------------------------------------------------------------
# 2. Proveedores IPTV (Principal: Eagle 4K | Backup: Trex OTT)
# -----------------------------------------------------------------------------
UserAgent = apps.get_model('core', 'UserAgent')
chrome_ua = UserAgent.objects.filter(name__icontains='Chrome').first()

# 2a. Proveedor Principal
provider_primary, p1_created = M3UAccount.objects.get_or_create(
    username=PROVIDER_USERNAME,
    defaults={
        'name': PROVIDER_NAME,
        'server_url': PROVIDER_SERVER_URL,
        'password': PROVIDER_PASSWORD,
        'max_streams': PROVIDER_MAX_STREAMS,
        'account_type': 'XC',
        'user_agent': chrome_ua,
        'custom_properties': {'enable_vod': False, 'auto_enable_new_groups_vod': True, 'auto_enable_new_groups_live': True, 'auto_enable_new_groups_series': True},
        'refresh_interval': 24,
        'is_active': True
    }
)
if not p1_created:
    provider_primary.name = PROVIDER_NAME
    provider_primary.server_url = PROVIDER_SERVER_URL
    provider_primary.password = PROVIDER_PASSWORD
    provider_primary.max_streams = PROVIDER_MAX_STREAMS
    provider_primary.account_type = 'XC'
    provider_primary.refresh_interval = 24
    if chrome_ua:
        provider_primary.user_agent = chrome_ua
    provider_primary.is_active = True
    provider_primary.save()
p1_action = "Registrado" if p1_created else "Actualizado"
print(f"✅ Proveedor Principal : {provider_primary.name} [{provider_primary.server_url}] (Límite: {provider_primary.max_streams} stream, Auto-refresh: 24h) ({p1_action})")

# 2b. Proveedor Backup / Failover
provider_backup = None
if BACKUP_PROVIDER_USERNAME and BACKUP_PROVIDER_SERVER_URL:
    provider_backup, p2_created = M3UAccount.objects.get_or_create(
        username=BACKUP_PROVIDER_USERNAME,
        defaults={
            'name': BACKUP_PROVIDER_NAME,
            'server_url': BACKUP_PROVIDER_SERVER_URL,
            'password': BACKUP_PROVIDER_PASSWORD,
            'max_streams': BACKUP_PROVIDER_MAX_STREAMS,
            'account_type': 'XC',
            'user_agent': chrome_ua,
            'custom_properties': {'enable_vod': False, 'auto_enable_new_groups_vod': True, 'auto_enable_new_groups_live': True, 'auto_enable_new_groups_series': True},
            'refresh_interval': 24,
            'is_active': True
        }
    )
    if not p2_created:
        provider_backup.name = BACKUP_PROVIDER_NAME
        provider_backup.server_url = BACKUP_PROVIDER_SERVER_URL
        provider_backup.password = BACKUP_PROVIDER_PASSWORD
        provider_backup.max_streams = BACKUP_PROVIDER_MAX_STREAMS
        provider_backup.account_type = 'XC'
        provider_backup.refresh_interval = 24
        if chrome_ua:
            provider_backup.user_agent = chrome_ua
        provider_backup.is_active = True
        provider_backup.save()
    p2_action = "Registrado" if p2_created else "Actualizado"
    print(f"✅ Proveedor Failover  : {provider_backup.name} [{provider_backup.server_url}] (Límite: {provider_backup.max_streams} stream, Auto-refresh: 24h) ({p2_action})")

# -----------------------------------------------------------------------------
# 3. Usuario Cliente IPTV (TiviMate, Smart TV, Jellyfin)
# -----------------------------------------------------------------------------
client_user, c_created = User.objects.get_or_create(
    username=CLIENT_USERNAME,
    defaults={'is_superuser': False, 'is_staff': False, 'is_active': True}
)
client_user.set_password(CLIENT_PASSWORD)
# custom_properties['xc_password'] es vital para la emulación Xtream Codes
props = client_user.custom_properties or {}
props['xc_password'] = CLIENT_PASSWORD
client_user.custom_properties = props
client_user.is_active = True
client_user.save()
c_action = "Creado" if c_created else "Actualizado"
print(f"✅ Usuario Cliente IPTV: {client_user.username} ({c_action})")

# -----------------------------------------------------------------------------
# 4. Grupo de Canales: Deportes Argentina
# -----------------------------------------------------------------------------
group, g_created = ChannelGroup.objects.get_or_create(name="Deportes Argentina")
print(f"✅ Grupo de Canales: '{group.name}' listo")

# -----------------------------------------------------------------------------
# 4b. Perfil de Streaming con Failover Rápido (Timeout y Buffering optimizados)
# -----------------------------------------------------------------------------
StreamProfile = apps.get_model('core', 'StreamProfile')
CoreSettings = apps.get_model('core', 'CoreSettings')
from core.models import PROXY_SETTINGS_KEY, STREAM_SETTINGS_KEY

stream_profile_fast, _ = StreamProfile.objects.get_or_create(
    name="ffmpeg-fast-failover",
    defaults={
        "command": "ffmpeg",
        "parameters": "-user_agent {userAgent} -rw_timeout 15000000 -i {streamUrl} -c copy -f mpegts pipe:1",
        "locked": False,
        "is_active": True,
        "user_agent_id": 1,
    }
)
stream_profile_fast.command = "ffmpeg"
stream_profile_fast.parameters = "-user_agent {userAgent} -rw_timeout 15000000 -i {streamUrl} -c copy -f mpegts pipe:1"
stream_profile_fast.save()

# Establecer buffering_timeout a 15s (valor óptimo para absorber jitter y reconexiones)
p_settings = CoreSettings.get_proxy_settings()
p_settings['buffering_timeout'] = 15
p_settings['buffering_speed'] = 1.0
CoreSettings._update_group(PROXY_SETTINGS_KEY, "Proxy Settings", p_settings)
CoreSettings.invalidate_group_cache(PROXY_SETTINGS_KEY)

# Establecer como perfil por defecto
s_settings = CoreSettings.get_stream_settings()
s_settings['default_stream_profile'] = stream_profile_fast.id
CoreSettings._update_group(STREAM_SETTINGS_KEY, "Stream Settings", s_settings)
CoreSettings.invalidate_group_cache(STREAM_SETTINGS_KEY)
print(f"✅ Perfil de Streaming Estable activo: {stream_profile_fast.name} (buffering_timeout: 15s, rw_timeout: 15s)")

# -----------------------------------------------------------------------------
# 5. Configuración de Canales Curados (Sin Failover - 1 Señal Argentina Única)
# -----------------------------------------------------------------------------
channels_config = [
    {
        "number": 1,
        "name": "ESPN Premium",
        "stream_id": 84034,  # Eagle 4K: |ARG| FOX SPORTS PREMIUM ᴴᴰ (Pack Fútbol)
        "hint": "FOX SPORTS PREMIUM",
        "epg_tvg_id": "espn.premium.argentina.latam",
        "epg_source_type": "latam",
    },
    {
        "number": 2,
        "name": "TNT Sports",
        "stream_id": 84035,  # Eagle 4K: |ARG| TNT SPORT
        "hint": "TNT SPORT",
        "epg_tvg_id": "tntsports.ar",
        "epg_source_type": "trex",
    },
    {
        "number": 3,
        "name": "TyC Sports",
        "stream_id": 84023,  # Eagle 4K: |ARG| TYC SPORTS
        "hint": "TYC SPORTS",
        "epg_tvg_id": "tyc.sports.argentina.latam",
        "epg_source_type": "latam",
    },
    {
        "number": 4,
        "name": "Fox Sports 1",
        "stream_id": 84031,  # Eagle 4K: |ARG| FOX SPORTS 1 ᴴᴰ (Transmite Fórmula 1 en directo en Argentina)
        "hint": "FOX SPORTS 1 ᴴᴰ",
        "epg_tvg_id": "foxsports.ar",
        "epg_source_type": "trex",
    },
    {
        "number": 5,
        "name": "Fox Sports 2",
        "stream_id": 84033,  # Eagle 4K: |ARG| FOX SPORTS 2 ᴴᴰ
        "hint": "FOX SPORTS 2 ᴴᴰ",
        "epg_tvg_id": "foxsports2.ar",
        "epg_source_type": "trex",
    },
    {
        "number": 6,
        "name": "Fox Sports 3",
        "stream_id": 84030,  # Eagle 4K: |ARG| FOX SPORT 3
        "hint": "FOX SPORT 3",
        "epg_tvg_id": "foxsports3.ar",
        "epg_source_type": "trex",
    },
    {
        "number": 7,
        "name": "ESPN",
        "stream_id": 84024,  # Eagle 4K: |ARG| ESPN
        "hint": "|ARG| ESPN",
        "epg_tvg_id": "espn.sur.latam",
        "epg_source_type": "latam",
    },
    {
        "number": 8,
        "name": "ESPN 2",
        "stream_id": 87565,  # Eagle 4K: |LAM| ESPN 2 ᵁᴴᴰ (720p 60fps fluido sin artefactos)
        "hint": "ESPN 2",
        "epg_tvg_id": "espn.2.sur.latam",
        "epg_source_type": "latam",
    },
    {
        "number": 9,
        "name": "ESPN 3",
        "stream_id": 87600,  # Eagle 4K: |LAM| ESPN 3 ᵁᴴᴰ (720p 30fps)
        "hint": "ESPN 3",
        "epg_tvg_id": "espn.3.sur.latam",
        "epg_source_type": "latam",
    },
    {
        "number": 10,
        "name": "ESPN Extra",
        "stream_id": 84026,  # Eagle 4K: |ARG| ESPN+
        "hint": "ESPN+",
        "epg_tvg_id": "espn.4.sur.latam",
        "epg_source_type": "latam",
    },
    {
        "number": 11,
        "name": "DSports (DirecTV 1)",
        "stream_id": 84039,  # Eagle 4K: |ARG| DIRECT TV SPORTS
        "hint": "DIRECT TV SPORTS",
        "epg_tvg_id": "DSPORTS | AR",
        "epg_source_type": "latam",
    },
    {
        "number": 12,
        "name": "DSports 2",
        "stream_id": 84040,  # Eagle 4K: |ARG| DIRECT TV SPORTS 2
        "hint": "DIRECT TV SPORTS 2",
        "epg_tvg_id": "DSPORTS 2 | ARGENTINA",
        "epg_source_type": "latam",
    },
    {
        "number": 13,
        "name": "DSports+ / DTV",
        "stream_id": 84041,  # Eagle 4K: |ARG| DIRECT TV SPORTS PLUS
        "hint": "DIRECT TV SPORTS PLUS",
        "epg_tvg_id": "dsports.plus.latam",
        "epg_source_type": "latam",
    },
]

print("\n--- Sincronizando Canales (1 Canal = 1 Stream Argentino Único, SIN Failover) ---")
for cfg in channels_config:
    channel, ch_created = Channel.objects.get_or_create(
        channel_number=cfg["number"],
        defaults={
            "name": cfg["name"],
            "channel_group": group,
            "stream_profile": stream_profile_fast,
            "hidden_from_output": False
        }
    )
    if not ch_created:
        channel.name = cfg["name"]
        channel.channel_group = group
        channel.stream_profile = stream_profile_fast
        channel.hidden_from_output = False
        channel.save()

    # Resolver stream único por ID o por Hint
    resolved_stream = None
    if cfg.get("stream_id"):
        resolved_stream = Stream.objects.filter(id=cfg["stream_id"]).first()
    if not resolved_stream and cfg.get("hint"):
        resolved_stream = Stream.objects.filter(name__icontains=cfg["hint"]).first()

    # Asignar estrictamente 1 único stream (orden=1), eliminando cualquier fallback
    ChannelStream.objects.filter(channel=channel).delete()
    if resolved_stream:
        ChannelStream.objects.create(
            channel=channel,
            stream=resolved_stream,
            order=1
        )
        acc_name = resolved_stream.m3u_account.name[:10] if resolved_stream.m3u_account else "Unknown"
        print(f"  [Ch {int(channel.channel_number):02d}] {channel.name:<18} : [Stream 1] [{acc_name}] {resolved_stream.name}")
    else:
        print(f"  [Ch {int(channel.channel_number):02d}] {channel.name:<18} : ⚠️ Sin stream disponible")

# -----------------------------------------------------------------------------
# 5b. Logotipos Oficiales Transparentes en Alta Definición
# -----------------------------------------------------------------------------
print("\n--- Sincronizando Logotipos Transparentes HD ---")
channel_logos = {
    1: ("ESPN Premium", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/espn-premium-ar.png"),
    2: ("TNT Sports", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/tnt-sports-ar.png"),
    3: ("TyC Sports", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/tyc-sports-ar.png"),
    4: ("Fox Sports 1", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/fox-sports-ar.png"),
    5: ("Fox Sports 2", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/fox-sports-2-ar.png"),
    6: ("Fox Sports 3", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/fox-sports-3-ar.png"),
    7: ("ESPN", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/espn-ar.png"),
    8: ("ESPN 2", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/espn-2-ar.png"),
    9: ("ESPN 3", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/espn-3-ar.png"),
    10: ("ESPN Extra", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/argentina/espn-extra-ar.png"),
    11: ("DSports", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/world-latin-america/dsports-lam.png"),
    12: ("DSports 2", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/world-latin-america/dsports2-lam.png"),
    13: ("DSports+", "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/world-latin-america/dsports-plus-lam.png"),
}

for ch_num, (logo_title, logo_url) in channel_logos.items():
    channel = Channel.objects.filter(channel_number=ch_num).first()
    if channel:
        logo_obj, _ = Logo.objects.get_or_create(
            url=logo_url,
            defaults={"name": f"{logo_title} (HD Transparent)"}
        )
        if logo_obj.name != f"{logo_title} (HD Transparent)":
            logo_obj.name = f"{logo_title} (HD Transparent)"
            logo_obj.save()
        channel.logo = logo_obj
        channel.save()
        print(f"  [Ch {int(ch_num):02d}] Logo asignado: {logo_obj.name}")

# -----------------------------------------------------------------------------
# 6. Fuentes EPG Múltiples (Latam Sports + Trex XMLTV) y Mapeo Exacto
# -----------------------------------------------------------------------------
print("\n--- Sincronizando Fuentes EPG y Guía de Programación ---")
from apps.epg.tasks import fetch_xmltv, parse_channels_only, parse_programs_for_source

# 6a. Fuente 1: Latam Sports EPG (ESPN Premium, ESPN Sur, TyC, DSports)
epg_latam, _ = EPGSource.objects.get_or_create(
    url="https://raw.githubusercontent.com/siulemorales-arch/latam-sports-epg/main/epg.xml",
    defaults={"name": "EPG Latam Sports", "source_type": "url", "is_active": True, "refresh_interval": 12}
)
epg_latam.name = "EPG Latam Sports"
epg_latam.refresh_interval = 12
epg_latam.is_active = True
epg_latam.save()
print(f"✅ Fuente EPG 1: {epg_latam.name} [{epg_latam.url}] (Auto-refresh: 12h)")

# 6b. Fuente 2: Trex XMLTV (TNT Sports, Fox Sports 1, 2, 3)
epg_trex, _ = EPGSource.objects.get_or_create(
    url=f"{BACKUP_PROVIDER_SERVER_URL}/xmltv.php?username={BACKUP_PROVIDER_USERNAME}&password={BACKUP_PROVIDER_PASSWORD}",
    defaults={"name": "EPG Trex OTT", "source_type": "url", "is_active": True, "refresh_interval": 12}
)
epg_trex.name = "EPG Trex OTT"
epg_trex.refresh_interval = 12
epg_trex.is_active = True
epg_trex.save()
print(f"✅ Fuente EPG 2: {epg_trex.name} [{epg_trex.url}] (Auto-refresh: 12h)")

# Asegurar que los canales de ambas fuentes estén indexados en EPGData
for src in [epg_latam, epg_trex]:
    if EPGData.objects.filter(epg_source=src).count() == 0:
        print(f"  Descargando e indexando canales para {src.name}...")
        if fetch_xmltv(src):
            parse_channels_only(src)

# Vincular cada canal con su EPGData correspondiente
sources_map = {
    "latam": epg_latam,
    "trex": epg_trex,
}

for cfg in channels_config:
    ch_num = cfg["number"]
    tvg_id = cfg.get("epg_tvg_id")
    src = sources_map.get(cfg.get("epg_source_type"))
    if not tvg_id or not src:
        continue

    channel = Channel.objects.filter(channel_number=ch_num).first()
    epg_data = EPGData.objects.filter(epg_source=src, tvg_id=tvg_id).first()
    if channel and epg_data:
        channel.epg_data = epg_data
        channel.tvg_id = epg_data.tvg_id
        channel.save()
        print(f"  [Ch {int(ch_num):02d}] EPG vinculada: {epg_data.name} (tvg-id: {epg_data.tvg_id})")
    else:
        print(f"  [Ch {int(ch_num):02d}] ⚠️ No se encontró entrada EPG para tvg-id: {tvg_id}")

# Parsear los programas de las fuentes para los canales mapeados
ProgramData = apps.get_model('epg', 'ProgramData')
for src in [epg_latam, epg_trex]:
    try:
        print(f"\n  Sincronizando programas para {src.name}...")
        parse_programs_for_source(src)
    except Exception as e:
        print(f"  [Aviso] Error parseando programas de {src.name}: {e}")

prog_count = ProgramData.objects.count()
print(f"\n✅ Guía EPG actualizada con éxito: {prog_count} programas sincronizados en total.")

print("\n" + "=" * 60)
print("🎉 ¡Aprovisionamiento completado con éxito! (1 Stream por Canal - Cero Failover)")
print("=" * 60)
