#!/usr/bin/env python3
"""
scripts/evaluate_provider.py
----------------------------
Herramienta de Auditoría de Calidad y Ranking de Proveedores IPTV para Sport-Vivo.

Evalúa objetivamente:
  1. Rendimiento en Vivo: TTFB (latencia de arranque), Bitrate (Mbps) y Jitter (pausas).
  2. Telemetría Histórica: Horas reales de visualización y tasa de cortes por hora desde EventDB.
  3. Score de Calidad (0 a 100) y Veredicto de Renovación (Renovar / Regular / Descartar).
  4. Ranking Histórico Comparativo de Proveedores guardado en /data/provider_quality.json.

Modos de ejecución (controlados por EVAL_MODE):
  - audit   (default): Ejecuta el test en vivo, analiza telemetría, actualiza historial y muestra ranking.
  - ranking : Muestra únicamente la tabla comparativa histórica y el top de proveedores.
"""

import os
import sys
import json
import time
import datetime
import urllib.request
from collections import defaultdict

# Inicializar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
import django
django.setup()

from django.apps import apps
from django.utils import timezone

SystemEvent = apps.get_model('core', 'SystemEvent')
Channel = apps.get_model('dispatcharr_channels', 'Channel')
M3UAccount = apps.get_model('m3u', 'M3UAccount')

DATA_FILE = "/data/provider_quality.json"
EVAL_MODE = os.environ.get("EVAL_MODE", "audit").lower()

CLIENT_USERNAME = os.environ.get('CLIENT_USERNAME', 'tv_living')
CLIENT_PASSWORD = os.environ.get('CLIENT_PASSWORD', 'Futbol2026*')
DISPATCHARR_PORT = os.environ.get('DISPATCHARR_PORT', '9191')
PROVIDER_NAME = os.environ.get('PROVIDER_NAME', '').strip()
PROVIDER_USERNAME = os.environ.get('PROVIDER_USERNAME', '').strip()
PROVIDER_SELLER = os.environ.get('PROVIDER_SELLER', '').strip()


def load_history():
    """Carga el historial de evaluaciones desde el archivo persistente."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"evaluations": []}


def save_history(data):
    """Guarda el historial de evaluaciones en el archivo persistente."""
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  No se pudo persistir el historial: {e}")


def get_viewing_telemetry(days=30):
    """Extrae horas vistas y métricas de cortes desde core.SystemEvent."""
    since = timezone.now() - datetime.timedelta(days=days)
    events = SystemEvent.objects.filter(timestamp__gte=since)

    total_viewing_seconds = 0.0
    sessions_count = 0
    reconnect_count = 0
    error_count = 0
    buffering_count = 0

    for e in events:
        etype = e.event_type
        if etype == 'client_disconnect' and isinstance(e.details, dict):
            dur = float(e.details.get('duration', 0))
            total_viewing_seconds += dur
            sessions_count += 1
        elif etype == 'channel_reconnect':
            reconnect_count += 1
        elif etype == 'channel_error':
            error_count += 1
        elif etype == 'channel_buffering':
            buffering_count += 1

    total_viewing_hours = total_viewing_seconds / 3600.0
    total_incidents = reconnect_count + error_count
    
    # Calcular cortes por hora (si hay al menos 6 minutos de datos)
    if total_viewing_hours >= 0.1:
        incidents_per_hour = total_incidents / total_viewing_hours
    else:
        incidents_per_hour = 0.0

    return {
        "viewing_hours": round(total_viewing_hours, 2),
        "sessions": sessions_count,
        "reconnects": reconnect_count,
        "errors": error_count,
        "buffer_events": buffering_count,
        "incidents_per_hour": round(incidents_per_hour, 2)
    }


def benchmark_single_channel(ch_num, sample_seconds=5):
    """Prueba un canal a través del proxy local de Dispatcharr."""
    url = f"http://localhost:{DISPATCHARR_PORT}/live/{CLIENT_USERNAME}/{CLIENT_PASSWORD}/{int(ch_num)}.ts"
    headers = {"User-Agent": "TiviMate/5.1.6 (Android 12)"}
    req = urllib.request.Request(url, headers=headers)

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            ttfb = (time.time() - t0) * 1000
            t_read = time.time()
            bytes_read = 0
            stalls = 0
            last_chunk_time = t_read

            while time.time() - t_read < sample_seconds:
                chunk = resp.read(65536)
                now = time.time()
                if not chunk:
                    break
                bytes_read += len(chunk)
                if now - last_chunk_time > 1.8:
                    stalls += 1
                last_chunk_time = now

            duration = time.time() - t_read
            mbps = (bytes_read * 8) / (duration * 1_000_000) if duration > 0 else 0
            return {
                "channel_num": ch_num,
                "status": "OK",
                "ttfb_ms": round(ttfb, 0),
                "duration_s": round(duration, 1),
                "mbps": round(mbps, 2),
                "stalls": stalls
            }
    except Exception as e:
        return {
            "channel_num": ch_num,
            "status": f"FAIL ({str(e)[:30]})",
            "ttfb_ms": None,
            "duration_s": 0,
            "mbps": 0,
            "stalls": 1
        }


def calculate_quality_score(telemetry, benchmark_results):
    """
    Calcula el Score de Calidad (0 a 100) ponderado:
      - 35%: Estabilidad en vivo (Cortes por hora históricos)
      - 25%: Consistencia en benchmark (Ausencia de stalls/pausas)
      - 20%: Tasa de transferencia (Bitrate Mbps)
      - 20%: Latencia de arranque (TTFB ms)
    """
    # 1. Estabilidad histórica (35 pts)
    iph = telemetry["incidents_per_hour"]
    hours = telemetry["viewing_hours"]
    if hours < 0.1:
        score_stability = 30  # Sin historial suficiente, neutro
    elif iph <= 0.5:
        score_stability = 35
    elif iph <= 1.5:
        score_stability = 30
    elif iph <= 3.0:
        score_stability = 22
    elif iph <= 5.0:
        score_stability = 14
    else:
        score_stability = 5

    # 2. Consistencia en benchmark (25 pts)
    total_stalls = sum(r.get("stalls", 0) for r in benchmark_results)
    tested_count = len(benchmark_results) or 1
    stalls_per_test = total_stalls / tested_count
    if stalls_per_test == 0:
        score_stalls = 25
    elif stalls_per_test <= 0.5:
        score_stalls = 18
    elif stalls_per_test <= 1.0:
        score_stalls = 10
    else:
        score_stalls = 3

    # 3. Bitrate promedio (20 pts)
    ok_results = [r for r in benchmark_results if r.get("status") == "OK"]
    if ok_results:
        avg_mbps = sum(r["mbps"] for r in ok_results) / len(ok_results)
    else:
        avg_mbps = 0.0

    if avg_mbps >= 10.0:
        score_bitrate = 20
    elif avg_mbps >= 7.0:
        score_bitrate = 16
    elif avg_mbps >= 4.0:
        score_bitrate = 11
    elif avg_mbps > 0:
        score_bitrate = 6
    else:
        score_bitrate = 0

    # 4. Latencia de arranque / TTFB (20 pts)
    if ok_results:
        avg_ttfb = sum(r["ttfb_ms"] for r in ok_results if r.get("ttfb_ms")) / len(ok_results)
    else:
        avg_ttfb = 9999.0

    if avg_ttfb <= 2000:
        score_ttfb = 20
    elif avg_ttfb <= 3500:
        score_ttfb = 15
    elif avg_ttfb <= 5500:
        score_ttfb = 10
    else:
        score_ttfb = 4

    total_score = int(round(score_stability + score_stalls + score_bitrate + score_ttfb))
    total_score = max(0, min(100, total_score))

    # Determinar veredicto
    if total_score >= 80:
        verdict = "RECOMENDADO RENOVAR"
        badge = "🟢"
    elif total_score >= 60:
        verdict = "REGULAR (EVALUAR CON PRECAUCION)"
        badge = "🟡"
    else:
        verdict = "NO RENOVAR (ALTA INESTABILIDAD)"
        badge = "🔴"

    return {
        "total_score": total_score,
        "verdict": verdict,
        "badge": badge,
        "avg_mbps": round(avg_mbps, 2),
        "avg_ttfb_ms": round(avg_ttfb, 0),
        "score_breakdown": {
            "estabilidad_historica": score_stability,
            "consistencia_jitter": score_stalls,
            "bitrate_video": score_bitrate,
            "latencia_arranque": score_ttfb
        }
    }


def render_ranking_table(history):
    """Renderiza el Top Ranking de Proveedores Histórico."""
    evals = history.get("evaluations", [])
    if not evals:
        print("\nℹ️  Aún no hay evaluaciones guardadas en el historial.")
        return

    # Agrupar por proveedor + vendedor tomando la evaluación más reciente
    by_provider = {}
    for ev in evals:
        pname = ev.get("provider_name", "Desconocido")
        seller = ev.get("seller", "N/A")
        key = f"{pname}___{seller}"
        if key not in by_provider or ev.get("timestamp", "") > by_provider[key].get("timestamp", ""):
            by_provider[key] = ev

    # Ordenar por Score descendente
    ranked = sorted(by_provider.values(), key=lambda x: x.get("score", 0), reverse=True)

    print("\n" + "=" * 104)
    print("🏆  RANKING Y TOP DE PROVEEDORES IPTV (SPORT-VIVO)")
    print("=" * 104)
    print(f"{'Pos':<4} {'Proveedor':<26} {'Vendedor / Tienda':<24} {'Score':<8} {'Bitrate':<11} {'Cortes/h':<10} {'Veredicto'}")
    print("-" * 104)

    for idx, r in enumerate(ranked, start=1):
        badge = r.get("badge", "⚪")
        pname = r.get("provider_name", "Unknown")[:25]
        seller = r.get("seller", "N/A")[:23]
        score = f"{r.get('score', 0)}/100"
        mbps = f"{r.get('metrics', {}).get('avg_mbps', 0)} Mbps"
        cph = f"{r.get('metrics', {}).get('incidents_per_hour', 0)}/h"
        verdict = f"{badge} {r.get('verdict', 'N/A')}"
        print(f" #{idx:<3} {pname:<26} {seller:<24} {score:<8} {mbps:<11} {cph:<10} {verdict}")

    print("=" * 104 + "\n")


def run_audit():
    """Ejecuta la auditoría en vivo y el cálculo del score."""
    provider = None
    if PROVIDER_USERNAME:
        provider = M3UAccount.objects.filter(username=PROVIDER_USERNAME).first()
    elif PROVIDER_NAME:
        provider = M3UAccount.objects.filter(name=PROVIDER_NAME).first()
    if not provider:
        provider = M3UAccount.objects.filter(server_url__isnull=False).exclude(name="custom").order_by('-id').first() or M3UAccount.objects.first()

    provider_name = provider.name if provider else "Proveedor Desconocido"
    provider_server = provider.server_url if provider else "N/A"
    provider_seller = PROVIDER_SELLER or "N/A"

    print("\n" + "=" * 78)
    print("📡  SPORT-VIVO: AUDITORÍA DE CALIDAD DE PROVEEDOR")
    print("=" * 78)
    print(f"  Proveedor Activo : {provider_name}")
    print(f"  Vendedor / Tienda: {provider_seller}")
    print(f"  Servidor Base    : {provider_server}")
    print(f"  Fecha Auditoría  : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 78)

    # 1. Telemetría de uso real
    print("\n📊 1. Analizando Telemetría de Visualización Real (Últimos 30 días)...")
    telemetry = get_viewing_telemetry()
    print(f"  • Tiempo total visto    : {telemetry['viewing_hours']} horas ({telemetry['sessions']} sesiones)")
    print(f"  • Reconexiones / Pausas : {telemetry['reconnects']} eventos")
    print(f"  • Errores de señal      : {telemetry['errors']} eventos")
    print(f"  • Tasa de incidentes    : {telemetry['incidents_per_hour']} cortes por hora de partido")

    # 2. Benchmark de canales clave
    print("\n⚡ 2. Ejecutando Benchmark en Vivo de Canales Clave...")
    key_channels = [
        (1, "ESPN Premium"),
        (2, "TNT Sports"),
        (3, "TyC Sports"),
        (4, "Fox Sports 1"),
        (7, "ESPN")
    ]

    benchmark_results = []
    for ch_num, ch_name in key_channels:
        ch_obj = Channel.objects.filter(channel_number=ch_num).first()
        if not ch_obj:
            continue
        print(f"  [Ch {ch_num:02d}] Probando {ch_name:<16} ...", end="", flush=True)
        res = benchmark_single_channel(ch_num, sample_seconds=4)
        benchmark_results.append(res)
        if res["status"] == "OK":
            print(f" ✅ {res['mbps']} Mbps | TTFB: {int(res['ttfb_ms'])}ms | Pausas: {res['stalls']}")
        else:
            print(f" ❌ {res['status']}")
        time.sleep(1)

    # 3. Cálculo de Score
    eval_result = calculate_quality_score(telemetry, benchmark_results)

    print("\n" + "-" * 78)
    print(f"🎯 3. RESULTADO DE EVALUACIÓN Y CALIFICACIÓN: {eval_result['badge']} {eval_result['total_score']} / 100")
    print("-" * 78)
    print(f"  • Veredicto Final         : {eval_result['badge']} {eval_result['verdict']}")
    print(f"  • Bitrate Promedio        : {eval_result['avg_mbps']} Mbps (Recomendado >= 8 Mbps)")
    print(f"  • Latencia de Arranque    : {int(eval_result['avg_ttfb_ms'])} ms (TTFB)")
    print(f"  • Desglose de Puntos      : Estabilidad={eval_result['score_breakdown']['estabilidad_historica']}/35 | "
          f"Jitter={eval_result['score_breakdown']['consistencia_jitter']}/25 | "
          f"Bitrate={eval_result['score_breakdown']['bitrate_video']}/20 | "
          f"Latencia={eval_result['score_breakdown']['latencia_arranque']}/20")

    # 4. Guardar en Historial
    history = load_history()
    eval_record = {
        "timestamp": timezone.now().isoformat(),
        "provider_name": provider_name,
        "seller": provider_seller,
        "server_url": provider_server,
        "score": eval_result["total_score"],
        "verdict": eval_result["verdict"],
        "badge": eval_result["badge"],
        "metrics": {
            "viewing_hours": telemetry["viewing_hours"],
            "incidents_per_hour": telemetry["incidents_per_hour"],
            "avg_ttfb_ms": eval_result["avg_ttfb_ms"],
            "avg_mbps": eval_result["avg_mbps"],
            "tested_channels": len(benchmark_results)
        }
    }
    history["evaluations"].append(eval_record)
    save_history(history)

    # 5. Mostrar Ranking
    render_ranking_table(history)


def main():
    history = load_history()
    if EVAL_MODE == "ranking":
        render_ranking_table(history)
    else:
        run_audit()


if __name__ == "__main__":
    main()
