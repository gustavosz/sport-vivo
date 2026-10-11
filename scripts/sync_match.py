#!/usr/bin/env python3
"""
scripts/sync_match.py
---------------------
Automatización inteligente para Sport-Vivo / Dispatcharr:
Detecta transmisiones activas de River Plate y Boca Juniors en el proveedor principal (Eagle 4K),
prioriza señales en español latino (ViX+ / TUDN, Disney+ AR, Prime US, Paramount+ LPF),
y actualiza el Canal 118 de forma completamente no disruptiva (sin tocar Redis ni streams activos).
"""

import os
import sys
import re
import argparse
from datetime import datetime

# Configuración de Django dentro de Dispatcharr
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
import django
django.setup()

from django.apps import apps

Channel = apps.get_model('dispatcharr_channels', 'Channel')
ChannelGroup = apps.get_model('dispatcharr_channels', 'ChannelGroup')
ChannelStream = apps.get_model('dispatcharr_channels', 'ChannelStream')
Stream = apps.get_model('dispatcharr_channels', 'Stream')

# Cuenta de Eagle 4K (Proveedor Principal)
EAGLE_ACCOUNT_ID = 3

# Falsos positivos y deportes no relacionados a descartar
EXCLUDE_PATTERNS = [
    r'^end\s*\|',              # Eventos ya finalizados
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
    r'boca chica',             # República Dominicana
    r'a bocados',              # Programa de cocina
    r't\u00e9l\u00e9 bocal',   # Canal francés
    r'gem river',              # Canal persa
]

def score_stream(stream, team_filter):
    """
    Evalúa y puntúa un stream en base a plataforma, idioma, fecha y relevancia.
    Mayor puntaje = mejor opción en español y calidad.
    """
    name = stream.name.lower()
    
    # 1. Descartar falsos positivos y partidos ya terminados
    for exc in EXCLUDE_PATTERNS:
        if re.search(exc, name):
            return -1

    # 2. Verificar correspondencia con el equipo buscado
    matched_team = None
    if team_filter in ['river', 'auto']:
        if re.search(r'\briver\s+plate\b', name) or re.search(r'(?<!blind\s)(?<!french\s)\briver\s+vs\b', name) or re.search(r'\bvs\.?\s+river\b', name):
            matched_team = 'River Plate'
    if not matched_team and team_filter in ['boca', 'auto']:
        if re.search(r'\bboca\s+juniors\b', name) or re.search(r'\bboca\s+vs\b', name) or re.search(r'\bvs\.?\s+boca\b', name):
            matched_team = 'Boca Juniors'
            
    if not matched_team:
        return -1

    score = 50  # Puntaje base

    # 3. Ponderación por plataforma e idioma
    if 'd+ br' in name or '|br|' in name or 'brasil' in name:
        score -= 40  # Portugués: penalizado severamente frente a cualquier señal en español
        platform = "Disney+ BR (PT)"
    elif 'vix' in name or 'tudn' in name:
        score += 60  # ViX / TUDN en español latino 1080p
        platform = "ViX HD"
    elif 'd+ ar' in name or 'disney+ ar' in name or 'espn' in name:
        score += 55  # Disney+ Argentina / ESPN
        platform = "Disney+ AR"
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

    # 4. Bonificación si coincide con la fecha de hoy
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    today_short = now.strftime('%b %d').lower()
    if today_str in name or today_short in name:
        score += 30

    # 5. Bonificación si menciona torneos oficiales argentinos
    if any(t in name for t in ['liga profesional', 'torneo', 'clausura', 'apertura', 'copa argentina', 'libertadores', 'sudamericana', 'lpf']):
        score += 15

    return (score, matched_team, platform)

def sync_match_channel(team='auto', channel_num=118, dry_run=False):
    print("=" * 65)
    print(f"⚽ SPORT-VIVO: Sincronización Inteligente de Partidos (Canal {channel_num})")
    print("=" * 65)
    print(f"🔍 Búsqueda activa para: {team.upper()} (Proveedor: Eagle 4K)")

    # Obtener o verificar el grupo 'Eventos Fútbol / Disney+'
    events_group, _ = ChannelGroup.objects.get_or_create(name="Eventos Fútbol / Disney+")
    
    # Obtener o crear el canal destino
    channel, ch_created = Channel.objects.get_or_create(
        channel_number=channel_num,
        defaults={
            "name": "⚽ Fútbol Argentino (En Espera)",
            "channel_group": events_group,
            "hidden_from_output": False
        }
    )

    # Buscar streams candidatos en Eagle 4K
    candidate_streams = Stream.objects.filter(m3u_account_id=EAGLE_ACCOUNT_ID)
    scored_candidates = []

    for s in candidate_streams:
        result = score_stream(s, team.lower())
        if result != -1 and isinstance(result, tuple):
            score, matched_team, platform = result
            scored_candidates.append((score, matched_team, platform, s))

    # Ordenar por puntaje descendente
    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    if scored_candidates:
        best_score, matched_team, platform, best_stream = scored_candidates[0]
        print(f"\n🎉 ¡Partido detectado! {len(scored_candidates)} señales evaluadas.")
        print(f"  → Mejor Señal : [{best_score} pts] [{platform}] {best_stream.name}")
        print(f"  → Stream ID   : {best_stream.id}")
        
        # Generar nombre limpio para el canal
        match_search = re.search(r'([A-Za-z0-9\s\.\#]+(?:vs\.?|vs)\s+[A-Za-z0-9\s\.\#]+)', best_stream.name, re.IGNORECASE)
        if match_search:
            clean_name = match_search.group(1).strip()
            clean_name = re.sub(r'^(D\+\s*\w+\s*\d*\||PRIME\s*\w+\s*\d*\||US\s*\([^\)]+\))', '', clean_name).strip()
            new_channel_name = f"⚽ {clean_name} ({platform})"
        else:
            new_channel_name = f"⚽ {matched_team} ({platform})"

        if dry_run:
            print(f"  [DRY-RUN] Canal {channel_num} se nombraría: '{new_channel_name}'")
            return

        channel.name = new_channel_name[:50]
        channel.channel_group = events_group
        channel.save()

        # Asignar stream único como orden 1
        ChannelStream.objects.filter(channel=channel).delete()
        ChannelStream.objects.create(channel=channel, stream=best_stream, order=1)
        print(f"✅ Canal {channel_num} actualizado con éxito: '{channel.name}' -> Stream ID {best_stream.id}")

    else:
        print("\nℹ️ No se detectaron partidos en vivo de River ni Boca en este momento.")
        standby_stream = Stream.objects.filter(
            m3u_account_id=EAGLE_ACCOUNT_ID,
            name__endswith="Futbol 1"
        ).first()

        new_channel_name = "⚽ Fútbol Argentino (En Espera)"
        if dry_run:
            print(f"  [DRY-RUN] Canal {channel_num} quedaría en espera: '{new_channel_name}'")
            return

        channel.name = new_channel_name
        channel.channel_group = events_group
        channel.save()

        if standby_stream:
            ChannelStream.objects.filter(channel=channel).delete()
            ChannelStream.objects.create(channel=channel, stream=standby_stream, order=1)
            print(f"✅ Canal {channel_num} en modo STANDBY con señal oficial: {standby_stream.name}")
        else:
            print(f"⚠️ Canal {channel_num} en modo STANDBY (sin señal fija)")

    print("=" * 65)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sincronizador inteligente de partidos para Sport-Vivo")
    parser.add_argument('--team', default='auto', choices=['auto', 'river', 'boca'], help="Equipo a buscar")
    parser.add_argument('--channel', type=int, default=118, help="Número de canal a actualizar (default 118)")
    parser.add_argument('--dry-run', action='store_true', help="Solo mostrar el resultado sin modificar la base de datos")
    args = parser.parse_args()

    sync_match_channel(team=args.team, channel_num=args.channel, dry_run=args.dry_run)
