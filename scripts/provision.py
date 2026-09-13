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
        'is_active': True
    }
)
if not p1_created:
    provider_primary.name = PROVIDER_NAME
    provider_primary.server_url = PROVIDER_SERVER_URL
    provider_primary.password = PROVIDER_PASSWORD
    provider_primary.max_streams = PROVIDER_MAX_STREAMS
    provider_primary.account_type = 'XC'
    if chrome_ua:
        provider_primary.user_agent = chrome_ua
    provider_primary.is_active = True
    provider_primary.save()
p1_action = "Registrado" if p1_created else "Actualizado"
print(f"✅ Proveedor Principal : {provider_primary.name} [{provider_primary.server_url}] (Límite: {provider_primary.max_streams} stream) ({p1_action})")

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
            'is_active': True
        }
    )
    if not p2_created:
        provider_backup.name = BACKUP_PROVIDER_NAME
        provider_backup.server_url = BACKUP_PROVIDER_SERVER_URL
        provider_backup.password = BACKUP_PROVIDER_PASSWORD
        provider_backup.max_streams = BACKUP_PROVIDER_MAX_STREAMS
        provider_backup.account_type = 'XC'
        if chrome_ua:
            provider_backup.user_agent = chrome_ua
        provider_backup.is_active = True
        provider_backup.save()
    p2_action = "Registrado" if p2_created else "Actualizado"
    print(f"✅ Proveedor Failover  : {provider_backup.name} [{provider_backup.server_url}] (Límite: {provider_backup.max_streams} stream) ({p2_action})")

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
# 5. Configuración de Canales Curados y Streams de Failover
# -----------------------------------------------------------------------------
channels_config = [
    {
        "number": 1,
        "name": "ESPN Premium",
        "primary_stream_ids": [84034, 87555],  # Eagle 4K: |ARG| FOX SPORTS PREMIUM ᴴᴰ, |LAM| Fox Sports Premium
        "backup_stream_ids": [49894],          # Trex OTT: ARG: ESPN PREMIUM RAW
        "primary_hints": ["FOX SPORTS PREMIUM", "ESPN PREMIUM"],
        "backup_hints": ["ESPN PREMIUM RAW"],
    },
    {
        "number": 2,
        "name": "TNT Sports",
        "primary_stream_ids": [84035, 87615],  # Eagle 4K: |ARG| TNT SPORT, |LAM| TNT Sports ᵁᴴᴰ
        "backup_stream_ids": [50006],          # Trex OTT: ARG: TNT SPORTS RAW
        "primary_hints": ["TNT SPORT"],
        "backup_hints": ["TNT SPORTS RAW"],
    },
    {
        "number": 3,
        "name": "TyC Sports",
        "primary_stream_ids": [84023, 84267, 84021],  # Eagle 4K: |ARG| TYC SPORTS, CHL TyC Sports HD
        "backup_stream_ids": [50009, 50021],          # Trex OTT: ARG: TYC SPORTS RAW
        "primary_hints": ["TYC SPORTS"],
        "backup_hints": ["TYC SPORTS RAW"],
    },
    {
        "number": 4,
        "name": "Fox Sports 1",
        "primary_stream_ids": [84031, 84032],  # Eagle 4K: |ARG| FOX SPORTS 1 ᴴᴰ, opc2
        "backup_stream_ids": [49908],          # Trex OTT: ARG: FOX SPORTS 1 RAW
        "primary_hints": ["FOX SPORTS 1 ᴴᴰ", "FOX SPORT 1"],
        "backup_hints": ["FOX SPORTS 1 RAW"],
    },
    {
        "number": 5,
        "name": "Fox Sports 2",
        "primary_stream_ids": [84033, 84029],  # Eagle 4K: |ARG| FOX SPORTS 2 ᴴᴰ, |ARG| FOX SPORT 2
        "backup_stream_ids": [49909],          # Trex OTT: ARG: FOX SPORTS 2 RAW
        "primary_hints": ["FOX SPORTS 2 ᴴᴰ", "FOX SPORT 2"],
        "backup_hints": ["FOX SPORTS 2 RAW"],
    },
    {
        "number": 6,
        "name": "Fox Sports 3",
        "primary_stream_ids": [84030, 87545],  # Eagle 4K: |ARG| FOX SPORT 3, |LAM| Fox Sports 3 ᵁᴴᴰ
        "backup_stream_ids": [49910],          # Trex OTT: ARG: FOX SPORTS 3 RAW
        "primary_hints": ["FOX SPORT 3", "FOX SPORTS 3"],
        "backup_hints": ["FOX SPORTS 3 RAW"],
    },
    {
        "number": 7,
        "name": "ESPN",
        "primary_stream_ids": [84024, 84020],  # Eagle 4K: |ARG| ESPN, |ARGENT ᴴᴰ - ESPN ARG ᴴᴰ-
        "backup_stream_ids": [49896],          # Trex OTT: ARG: ESPN RAW
        "primary_hints": ["|ARG| ESPN", "ESPN ARG"],
        "backup_hints": ["ESPN RAW"],
    },
    {
        "number": 8,
        "name": "ESPN 2",
        "primary_stream_ids": [84025, 87565],  # Eagle 4K: |ARG| ESPN 2, |LAM| ESPN 2 ᵁᴴᴰ
        "backup_stream_ids": [49886],          # Trex OTT: ARG: ESPN 2 RAW
        "primary_hints": ["|ARG| ESPN 2", "ESPN 2"],
        "backup_hints": ["ESPN 2 RAW"],
    },
    {
        "number": 9,
        "name": "ESPN 3",
        "primary_stream_ids": [83883, 87600],  # Eagle 4K: |PER| ESPN 3, |LAM| ESPN 3 ᵁᴴᴰ
        "backup_stream_ids": [49890],          # Trex OTT: ARG: ESPN 3 RAW
        "primary_hints": ["ESPN 3"],
        "backup_hints": ["ESPN 3 RAW"],
    },
    {
        "number": 10,
        "name": "ESPN Extra",
        "primary_stream_ids": [84026, 83886],  # Eagle 4K: |ARG| ESPN+, |PER| ESPN EXTRA
        "backup_stream_ids": [49893],          # Trex OTT: ARG: ESPN EXTRA RAW
        "primary_hints": ["|ARG| ESPN+", "ESPN EXTRA"],
        "backup_hints": ["ESPN EXTRA RAW"],
    },
    {
        "number": 11,
        "name": "DSports (DirecTV 1)",
        "primary_stream_ids": [84039, 83968],  # Eagle 4K: |ARG| DIRECT TV SPORTS, |UY| DIRECTV SPORTS ᴴᴰ
        "backup_stream_ids": [49871],          # Trex OTT: ARG: DTV RAW
        "primary_hints": ["DIRECT TV SPORTS", "DIRECTV SPORTS 1"],
        "backup_hints": ["DTV RAW", "DIRECTV SPORTS 1"],
    },
    {
        "number": 12,
        "name": "DSports 2",
        "primary_stream_ids": [84040, 86554],  # Eagle 4K: |ARG| DIRECT TV SPORTS 2, |CO| DIRECTV SPORTS 2
        "backup_stream_ids": [50405, 50368],  # Trex OTT: CO: DIRECTV SPORTS 2
        "primary_hints": ["DIRECT TV SPORTS 2", "DIRECTV SPORTS 2"],
        "backup_hints": ["DIRECTV SPORTS 2"],
    },
    {
        "number": 13,
        "name": "DSports+ / DTV",
        "primary_stream_ids": [84041],         # Eagle 4K: |ARG| DIRECT TV SPORTS PLUS
        "backup_stream_ids": [49871],          # Trex OTT: ARG: DTV RAW
        "primary_hints": ["DIRECT TV SPORTS PLUS"],
        "backup_hints": ["DTV RAW"],
    },
]

print("\n--- Sincronizando Canales y Mapeo de Failover (P1: Eagle 4K, P2: Trex OTT) ---")
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

    # Resolver streams candidatos del proveedor principal (Eagle 4K)
    resolved_primary = []
    for s_id in cfg.get("primary_stream_ids", []):
        s = Stream.objects.filter(id=s_id).first()
        if s and s not in resolved_primary:
            resolved_primary.append(s)
    if not resolved_primary:
        for hint in cfg.get("primary_hints", []):
            matches = Stream.objects.filter(m3u_account=provider_primary, name__icontains=hint)
            for m in matches:
                if m not in resolved_primary:
                    resolved_primary.append(m)

    # Resolver streams candidatos del proveedor de respaldo (Trex OTT)
    resolved_backup = []
    for s_id in cfg.get("backup_stream_ids", []):
        s = Stream.objects.filter(id=s_id).first()
        if s and s not in resolved_backup:
            resolved_backup.append(s)
    if not resolved_backup and provider_backup:
        for hint in cfg.get("backup_hints", []):
            matches = Stream.objects.filter(m3u_account=provider_backup, name__icontains=hint)
            for m in matches:
                if m not in resolved_backup:
                    resolved_backup.append(m)

    # Ordenar estrictamente:
    # 1. Señal Principal (Eagle 4K)
    # 2. Señal Backup (Trex OTT)
    # 3+. Señales Alternativas
    resolved_streams = []
    if resolved_primary:
        resolved_streams.append(resolved_primary[0])
    if resolved_backup:
        resolved_streams.append(resolved_backup[0])
    for s in resolved_primary[1:] + resolved_backup[1:]:
        if s not in resolved_streams:
            resolved_streams.append(s)

    if resolved_streams:
        ChannelStream.objects.filter(channel=channel).delete()
        for idx, stream in enumerate(resolved_streams, start=1):
            ChannelStream.objects.create(
                channel=channel,
                stream=stream,
                order=idx
            )
        streams_summary = " -> ".join([f"P{idx}:[{stream.m3u_account.name[:8] if stream.m3u_account else '?'}] {stream.name[:18]}" for idx, stream in enumerate(resolved_streams, start=1)])
        print(f"  [Ch {int(channel.channel_number):02d}] {channel.name:<18} : {streams_summary}")
    else:
        print(f"  [Ch {int(channel.channel_number):02d}] {channel.name:<18} : Sin streams disponibles")

# -----------------------------------------------------------------------------
# 5b. Logotipos Oficiales Transparentes en Alta Definición (Sin fondos blancos)
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
# 6. Fuente EPG Externa y Vinculación
# -----------------------------------------------------------------------------
print("\n--- Sincronizando Guía de Programación (EPG) ---")
epg_source, e_created = EPGSource.objects.get_or_create(
    url=EPG_URL,
    defaults={
        'name': EPG_NAME,
        'source_type': 'url',
        'is_active': True
    }
)
if not e_created:
    epg_source.name = EPG_NAME
    epg_source.is_active = True
    epg_source.save()
print(f"✅ Fuente EPG: {epg_source.name} [{epg_source.url}]")

# Mapeo de canales a EPG
epg_mapping = {
    1: 171,  # ESPN Premium -> ESPN Premium HD (a1ty)
    2: 155,  # TNT Sports -> TNT Sports HD (a1sm)
    3: 153,  # TyC Sports -> TyC Sports HD (a1sk)
    4: 170,  # Fox Sports 1 -> Fox Sports HD (a1tx)
    5: 129,  # Fox Sports 2 -> Fox Sports 2 HD (a1r3)
    6: 154,  # Fox Sports 3 -> Fox Sports 3 HD (a1sl)
    7: 100,  # ESPN -> ESPN HD (a1jl)
    8: 96,   # ESPN 2 -> ESPN 2 HD (a1jc)
    9: 113,  # ESPN 3 -> ESPN 3 HD (a1kf)
    10: 93,  # ESPN Extra -> ESPN 4HD (a1j1)
}

epg_ids_to_refresh = []
for ch_num, epg_id in epg_mapping.items():
    try:
        channel = Channel.objects.filter(channel_number=ch_num).first()
        epg_data = EPGData.objects.filter(id=epg_id).first()
        if channel and epg_data:
            channel.epg_data = epg_data
            channel.tvg_id = epg_data.tvg_id
            channel.save()
            epg_ids_to_refresh.append(epg_data.id)
            print(f"  [Ch {int(ch_num):02d}] EPG asignada: {epg_data.name} (tvg-id: {epg_data.tvg_id})")
    except Exception as e:
        print(f"  [Aviso] No se pudo mapear EPG para canal {ch_num}: {e}")

try:
    from apps.epg.tasks import fetch_xmltv, parse_programs_for_source
    ProgramData = apps.get_model('epg', 'ProgramData')
    print("\n  Descargando y parseando programas de la guía...")
    if fetch_xmltv(epg_source):
        parse_programs_for_source(epg_source)
        prog_count = ProgramData.objects.count()
        print(f"✅ Guía actualizada: {prog_count} programas sincronizados para canales activos.")
except Exception as e:
    print(f"  [Aviso] Error sincronizando programas EPG: {e}")

print("\n" + "=" * 60)
print("🎉 ¡Aprovisionamiento completado con éxito!")
print("=" * 60)
