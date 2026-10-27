#!/usr/bin/env python3
"""
tests/test_provision_and_audit.py
---------------------------------
Tests unitarios para src/provision.py y src/evaluate_provider.py.
"""

import os
import sys
import unittest

os.environ.setdefault("SPORT_VIVO_LOG_DIR", "/tmp")

for _p in ("/app", "/app/src", os.path.join(os.path.dirname(__file__), "..", "src")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import provision
import evaluate_provider


class FakeRedisForClients:
    def __init__(self, key_counts=None):
        self.key_counts = key_counts or {}

    def keys(self, pattern):
        if pattern == "live:channel:*:clients":
            return list(self.key_counts.keys())
        return []

    def scard(self, key):
        return self.key_counts.get(key, 0)


class TestProvisionConfigAndHelpers(unittest.TestCase):
    def test_has_active_redis_clients_uses_set_cardinality(self):
        # Sin claves -> False
        r_empty = FakeRedisForClients({})
        self.assertFalse(provision.has_active_redis_clients(r_empty))

        # Clave presente pero con 0 clientes conectados -> False
        r_zero = FakeRedisForClients({"live:channel:abc-123:clients": 0})
        self.assertFalse(provision.has_active_redis_clients(r_zero))

        # Clave con 1 cliente activo -> True
        r_active = FakeRedisForClients({"live:channel:abc-123:clients": 1})
        self.assertTrue(provision.has_active_redis_clients(r_active))

    def test_channels_config_covers_all_18_channels_with_argentine_aliases_and_logos(self):
        numbers = [c["number"] for c in provision.CHANNELS_CONFIG]
        self.assertEqual(numbers, list(range(1, 19)))

        by_num = {c["number"]: c for c in provision.CHANNELS_CONFIG}
        # Canal 11 prioriza ARG: DTV sobre señales de Colombia
        self.assertEqual(by_num[11]["aliases"][0], "ARG: DTV")
        # Canal 13 incluye RC: DIRECTV SPORTS HD y ARG: DTV
        self.assertIn("RC: DIRECTV SPORTS HD", by_num[13]["aliases"])
        # Canal 15 incluye ARG: GOL TV como fallback cuando DeporTV no está
        self.assertIn("ARG: GOL TV", by_num[15]["aliases"])
        # Todos los 18 canales tienen logotipo asignado
        for ch_num in range(1, 19):
            self.assertIn(ch_num, provision.CHANNEL_LOGOS)


class TestEvaluateProvider(unittest.TestCase):
    def test_calculate_quality_score_handles_zero_and_none_ttfb(self):
        telemetry = {"is_new": True, "incidents_per_hour": 0.0, "viewing_hours": 0.5}
        benchmarks = [
            {"channel_num": 1, "status": "OK", "ttfb_ms": 0.0, "mbps": 8.5, "stalls": 0},
            {"channel_num": 2, "status": "OK", "ttfb_ms": 1200.0, "mbps": 9.5, "stalls": 0},
            {"channel_num": 3, "status": "OK", "ttfb_ms": None, "mbps": 9.0, "stalls": 0},
        ]
        res = evaluate_provider.calculate_quality_score(telemetry, benchmarks)
        # Promedio entre 0.0 y 1200.0 (ignorando None) = 600 ms
        self.assertEqual(res["avg_ttfb_ms"], 600.0)
        self.assertGreaterEqual(res["total_score"], 90)

    def test_has_active_viewers_detects_live_viewer(self):
        r_idle = FakeRedisForClients({"live:channel:uuid1:clients": 0})
        self.assertFalse(evaluate_provider.has_active_viewers(r_idle))

        r_busy = FakeRedisForClients({"live:channel:uuid1:clients": 1})
        self.assertTrue(evaluate_provider.has_active_viewers(r_busy))


if __name__ == "__main__":
    unittest.main()
