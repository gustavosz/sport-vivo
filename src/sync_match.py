#!/usr/bin/env python3
"""
src/sync_match.py
-----------------
Sincronización de partidos de River Plate y Boca Juniors en los canales de eventos
de Sport-Vivo / Dispatcharr:

  - Canal 17: AFA Play  → SOLO señales Fanatiz / AFA Play.
  - Canal 18: Internacional → cualquier otra señal del partido (ViX, ESPN+, etc.).

Los canales 01 (ESPN Premium) y 02 (TNT Sports) NUNCA se modifican desde aquí.

Es la única fuente de verdad de la lógica de partidos y se usa de dos formas:
  - CLI  (make match / river / boca, daily_sync.sh):
        python - --team auto|river|boca [--channel 0|17|18] [--dry-run]
  - Módulo: src/stream_daemon.py importa sync_event_channels() y los helpers.

Solo escribe en la base de datos cuando el stream o el nombre del canal cambian.
"""

import os
import sys
import re
import argparse
from datetime import date, datetime, timedelta, timezone

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

# Configuración de Django dentro de Dispatcharr
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
import django
django.setup()

from django.apps import apps
from django.db import transaction
from django.db.models import Q

Channel = apps.get_model('dispatcharr_channels', 'Channel')
ChannelGroup = apps.get_model('dispatcharr_channels', 'ChannelGroup')
ChannelStream = apps.get_model('dispatcharr_channels', 'ChannelStream')
Stream = apps.get_model('dispatcharr_channels', 'Stream')
M3UAccount = apps.get_model('m3u', 'M3UAccount')

# -----------------------------------------------------------------------------
# Configuración
# -----------------------------------------------------------------------------
# Argentina no usa horario de verano: UTC-3 fijo. El contenedor corre en UTC, así
# que sin esto "hoy" pasaba a ser "mañana" a partir de las 21:00 ART.
ART = timezone(timedelta(hours=-3), name="ART")

EVENT_GROUP_NAME = "Deportes Argentina"
AFA_CHANNEL = 17
INTL_CHANNEL = 18
EVENT_CHANNELS = {
    AFA_CHANNEL: {"label": "AFA Play", "standby_name": "AFA Play (Fanatiz / Liga Arg)"},
    INTL_CHANNEL: {"label": "Internacional", "standby_name": "ViX PPV / Internacional"},
}

# Falsos positivos, placeholders y deportes no relacionados a descartar
EXCLUDE_PATTERNS = [
    r'^end(ed)?\s*\|',         # Eventos ya finalizados
    r'\bended\b',
    r'no event streaming',     # Placeholders vacíos del proveedor
    r'hockey',                 # Hockey
    r'volleyball', r'voley',   # Vóley
    r'baseball', r'milb',      # Béisbol
    r'driver tracker', r'formula 1', r'\bf1\b', # Automovilismo
    r'ncaa',                   # Deportes universitarios de EE.UU.
    r'river monsters',         # Serie de TV
    r'uc riverside', r'riverside',
    r'riverhead',
    r'blind river', r'french river',
    r'riverton',
    r'river plate uruguay',    # Homónimos extranjeros
    r'river plate zambia',
    r'sestao river',           # Club español
    r'boca chica',             # República Dominicana
    r'a bocados',              # Programa de cocina
    r't\u00e9l\u00e9 bocal',   # Canal francés
    r'gem river',              # Canal persa
]

_MONTH_RE = (r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|'
             r'aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)')
_MONTHS = {m: i for i, m in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], start=1)}
_RE_YMD = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
_RE_DMY = re.compile(r'\b(\d{2})-(\d{2})-(\d{4})\b')
_RE_D_MON = re.compile(r'\b(\d{1,2})\s+' + _MONTH_RE + r'\b')
# El (?!:) evita leer la hora como día: "Oct 23:00" no es "23 de octubre".
_RE_MON_D = re.compile(r'\b' + _MONTH_RE + r'\.?\s+(\d{1,2})\b(?!:)')


def local_now():
    """Fecha y hora actual en Argentina."""
    return datetime.now(ART)


def get_active_account():
    """Obtiene dinámicamente la cuenta del proveedor primario activo."""
    prov_user = os.environ.get('PROVIDER_USERNAME')
    if prov_user:
        acc = M3UAccount.objects.filter(username=prov_user, is_active=True).first()
        if acc:
            return acc
    return M3UAccount.objects.filter(is_active=True).exclude(name='custom').order_by('id').first()


def is_afa_stream(name):
    """True si el stream es una señal Fanatiz / AFA Play."""
    n = name.lower()
    return 'fanatiz' in n or 'afa play' in n


def channel_accepts(channel_num, stream_name):
    """Define qué señales puede recibir cada canal de eventos."""
    if channel_num == AFA_CHANNEL:
        return is_afa_stream(stream_name)
    if channel_num == INTL_CHANNEL:
        return not is_afa_stream(stream_name)
    return False


def _closest_year(month, day, today):
    """Para fechas sin año ('26 Oct'), elige el año más cercano a hoy (maneja dic/ene)."""
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def extract_event_date(name):
    """Devuelve la primera fecha explícita encontrada en el nombre del stream, o None."""
    n = name.lower()
    today = local_now().date()
    try:
        m = _RE_YMD.search(n)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _RE_DMY.search(n)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    m = _RE_D_MON.search(n)
    if m:
        return _closest_year(_MONTHS[m.group(2)[:3]], int(m.group(1)), today)
    m = _RE_MON_D.search(n)
    if m:
        return _closest_year(_MONTHS[m.group(1)[:3]], int(m.group(2)), today)
    return None


def date_relevance(name):
    """
    Devuelve (es_relevante, es_hoy).
    Se acepta hoy y mañana (hora AR): los listados en UTC/CET de un partido nocturno
    en Argentina muestran la fecha del día siguiente. Nunca se aceptan fechas pasadas.
    """
    d = extract_event_date(name)
    if d is None:
        return True, False
    today = local_now().date()
    return d in (today, today + timedelta(days=1)), d == today


def score_stream(stream, team_filter='auto'):
    """
    Evalúa un stream. Devuelve None si no aplica, o (puntaje, equipo, plataforma).
    Mayor puntaje = mejor opción en español y calidad.
    """
    name = stream.name.lower()

    # 1. Descartar falsos positivos, placeholders y partidos ya terminados
    for exc in EXCLUDE_PATTERNS:
        if re.search(exc, name):
            return None

    relevant, is_today = date_relevance(name)
    if not relevant:
        return None

    # 2. Verificar correspondencia con el equipo buscado
    matched_team = None
    if team_filter in ['river', 'auto']:
        if re.search(r'\briver\s+plate\b', name) or re.search(r'(?<!blind\s)(?<!french\s)\briver\s+vs\b', name) or re.search(r'\bvs\.?\s+river\b', name):
            matched_team = 'River Plate'
    if not matched_team and team_filter in ['boca', 'auto']:
        if re.search(r'\bboca\s+juniors\b', name) or re.search(r'\bboca\s+vs\b', name) or re.search(r'\bvs\.?\s+boca\b', name) or re.search(r'\bvasco\s+x\s+boca\b', name):
            matched_team = 'Boca Juniors'

    if not matched_team:
        return None

    score = 50  # Puntaje base

    # 3. Ponderación por plataforma e idioma
    if 'd+ br' in name or '|br|' in name or 'brasil' in name or 'br:' in name:
        score -= 40  # Portugués: penalizado frente a cualquier señal en español
        platform = "BR (PT)"
    elif is_afa_stream(name):
        score += 60  # AFA Play / Fanatiz (feed oficial de la Liga Profesional)
        platform = "AFA Play"
    elif 'arg: espn premium' in name or 'espn premium' in name:
        score += 75  # ESPN Premium oficial argentino (con Pollo Vignolo)
        platform = "ESPN Premium HD"
    elif 'arg: tnt sports' in name or 'tnt sports' in name:
        score += 70  # TNT Sports oficial argentino
        platform = "TNT Sports HD"
    elif name.startswith('arg:') or '|arg|' in name or 'argentina' in name:
        score += 65  # Señal nacional argentina
        platform = "Transmisión AR"
    elif 'vix' in name or 'tudn' in name:
        score += 60  # ViX / TUDN en español latino 1080p
        platform = "ViX HD"
    elif 'espn+' in name:
        score += 55  # ESPN+ (EE.UU., audio en español disponible)
        platform = "ESPN+"
    elif 'd+ ar' in name or 'disney+ ar' in name or 'espn' in name:
        score += 55  # Disney+ Argentina / ESPN
        platform = "Disney+ AR"
    elif 'us: soccer ppv' in name or 'soccer ppv' in name:
        score += 52  # Soccer PPV internacional
        platform = "Soccer PPV"
    elif 'd+ cl' in name or 'd+ sur' in name or 'd+ lam' in name:
        score += 50  # Disney+ Cono Sur
        platform = "Disney+ Sur"
    elif 'prime us' in name:
        score += 45  # Prime Video US (audio español)
        platform = "Prime Video"
    elif 'liga profesional' in name or 'paramount' in name:
        score += 40  # Feeds fijos LPF de Paramount+
        platform = "LPF Oficial"
    else:
        platform = "Feed Deportes"

    # 4. Bonificaciones: partido de hoy (hora AR) y transmisión en vivo
    if is_today:
        score += 30
    if name.startswith('live'):
        score += 25

    # 5. Bonificación si menciona torneos oficiales argentinos o Conmebol
    if any(t in name for t in ['liga profesional', 'torneo', 'clausura', 'apertura', 'copa argentina', 'libertadores', 'sudamericana', 'lpf']):
        score += 15

    return (score, matched_team, platform)


def find_candidates(account=None, team='auto'):
    """
    Lista ordenada de (puntaje, equipo, plataforma, stream).
    El filtro grueso se hace en la base (no se recorren los ~150k streams en Python)
    y el desempate por id es determinístico para no reescribir canales sin motivo.
    """
    qs = Stream.objects.filter(Q(name__icontains='river') | Q(name__icontains='boca'))
    if account:
        qs = qs.filter(m3u_account=account)
    else:
        qs = qs.filter(m3u_account__is_active=True)

    candidates = []
    for s in qs.only('id', 'name'):
        result = score_stream(s, team)
        if result:
            score, matched_team, platform = result
            candidates.append((score, matched_team, platform, s))
    candidates.sort(key=lambda c: (c[0], c[3].id), reverse=True)
    return candidates


def clean_channel_name(stream_name, matched_team, platform):
    """Genera un nombre de canal legible a partir del nombre crudo del stream."""
    clean = re.sub(r'^(NEXT\s*\|\s*|LIVE\s*\|\s*|ENDED\s*\|\s*)', '', stream_name, flags=re.IGNORECASE).strip()
    match_part = clean.split('|')[0].strip()
    # Formato "(Fanatiz 087) | Boca vs ...": el partido está en el segundo segmento
    if re.match(r'^\(.*\)$', match_part) and '|' in clean:
        match_part = clean.split('|')[1].strip()
    match_part = re.sub(r'\(\d{4}-\d{2}-\d{2}[^)]*\)', '', match_part)
    match_part = re.sub(r'^(D\+\s*\w+\s*\d*\||PRIME\s*\w+\s*\d*\||US\s*\([^\)]+\)|ARG:\s*)', '', match_part, flags=re.IGNORECASE).strip()
    match_part = re.sub(r'\b(CLUB\s+ATL[EÉ]TICO|ATL[EÉ]TICO|CLUB)\s+', '', match_part, flags=re.IGNORECASE)
    match_part = re.sub(r'\b(CA|CR)\s+', '', match_part, flags=re.IGNORECASE)
    match_part = re.sub(r'\s+', ' ', match_part).strip()
    if 'vs' in match_part.lower() or ' x ' in match_part.lower():
        name = f"⚽ {match_part.title()} ({platform})"
    else:
        name = f"⚽ {matched_team} ({platform})"
    return name[:50]


def pick_for_channel(candidates, channel_num):
    """Mejor candidato permitido para el canal indicado, o None."""
    for cand in candidates:
        if channel_accepts(channel_num, cand[3].name):
            return cand
    return None


def apply_channel(channel_num, stream, name, dry_run=False, log=print):
    """
    Aplica stream + nombre al canal SOLO si algo cambió. Devuelve True si hubo cambios.
    Si stream es None (modo espera), conserva el stream actual y solo ajusta el nombre.
    """
    group, _ = ChannelGroup.objects.get_or_create(name=EVENT_GROUP_NAME)
    channel, _ = Channel.objects.get_or_create(
        channel_number=channel_num,
        defaults={"name": name, "channel_group": group, "hidden_from_output": False},
    )
    current_ids = list(
        ChannelStream.objects.filter(channel=channel).order_by('order').values_list('stream_id', flat=True)
    )
    stream_changed = stream is not None and current_ids != [stream.id]
    meta_changed = channel.name != name or channel.channel_group_id != group.id

    if not stream_changed and not meta_changed:
        return False
    if dry_run:
        log(f"  [DRY-RUN] Canal {channel_num} → '{name}'" + (f" (Stream {stream.id})" if stream else ""))
        return True

    with transaction.atomic():
        if meta_changed:
            channel.name = name
            channel.channel_group = group
            channel.save()
        if stream_changed:
            ChannelStream.objects.filter(channel=channel).delete()
            ChannelStream.objects.create(channel=channel, stream=stream, order=1)
    return True


def sync_event_channels(team='auto', channels=(AFA_CHANNEL, INTL_CHANNEL), dry_run=False, log=print, verbose=False):
    """
    Sincroniza los canales de eventos. Solo registra en el log los cambios reales
    (o todo si verbose=True). Devuelve {canal: (candidato|None, hubo_cambios)}.
    """
    account = get_active_account()
    candidates = find_candidates(account, team)
    results = {}

    for ch in channels:
        cfg = EVENT_CHANNELS[ch]
        pick = pick_for_channel(candidates, ch)
        if pick:
            score, matched_team, platform, stream = pick
            name = clean_channel_name(stream.name, matched_team, platform)
            changed = apply_channel(ch, stream, name, dry_run, log)
            if changed or verbose:
                state = "actualizado" if changed else "sin cambios"
                log(f"✅ Canal {ch} ({cfg['label']}) {state}: [{score} pts] [{platform}] {stream.name} (Stream {stream.id})")
        else:
            changed = apply_channel(ch, None, cfg['standby_name'], dry_run, log)
            if changed or verbose:
                log(f"ℹ️ Canal {ch} ({cfg['label']}) en espera: no hay partidos de River/Boca para hoy en esta plataforma.")
        results[ch] = (pick, changed)

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sincronizador inteligente de partidos para Sport-Vivo")
    parser.add_argument('--team', default='auto', choices=['auto', 'river', 'boca'], help="Equipo a buscar")
    parser.add_argument('--channel', type=int, default=0, choices=[0, AFA_CHANNEL, INTL_CHANNEL],
                        help="Canal a actualizar: 17 (AFA Play), 18 (Internacional) o 0 para ambos (default)")
    parser.add_argument('--dry-run', action='store_true', help="Solo mostrar el resultado sin modificar la base de datos")
    args = parser.parse_args()

    target = (AFA_CHANNEL, INTL_CHANNEL) if args.channel == 0 else (args.channel,)
    account = get_active_account()

    print("=" * 65)
    print(f"⚽ SPORT-VIVO: Sincronización de Partidos (Canales {', '.join(map(str, target))})")
    print("=" * 65)
    print(f"🔍 Búsqueda: {args.team.upper()} | Proveedor: {account.name if account else 'N/A'} | Hora AR: {local_now():%Y-%m-%d %H:%M}")

    if not args.dry_run:
        # Limpieza proactiva de grupos y canales legacy
        ChannelGroup.objects.filter(name="Eventos Fútbol / Disney+").delete()
        Channel.objects.filter(channel_number__gte=100).delete()

    sync_event_channels(team=args.team, channels=target, dry_run=args.dry_run, verbose=True)
    print("=" * 65)
