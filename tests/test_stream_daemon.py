#!/usr/bin/env python3
"""
tests/test_stream_daemon.py
---------------------------
Tests unitarios para la detección de stream zombi, histéresis, cooldown y filtrado de señales (src/stream_daemon.py).
"""

import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SPORT_VIVO_LOG_DIR", "/tmp")

for _p in ("/app", "/app/src", os.path.join(os.path.dirname(__file__), "..", "src")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import stream_daemon as sd
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState


class FakeRedis:
    def __init__(self, clients_count=1, metadata=None):
        self.clients_count = clients_count
        self.metadata = metadata or {}

    def scard(self, key):
        return self.clients_count

    def hgetall(self, key):
        return dict(self.metadata)


class TestStreamDaemonHelpers(unittest.TestCase):
    def setUp(self):
        self.daemon = sd.SportVivoDaemon()

    def test_arg_token_regex_matches_only_argentine_feeds(self):
        self.assertIsNotNone(sd._ARG_TOKEN.search("ARG: ESPN PREMIUM ᴿᴬᵂ"))
        self.assertIsNotNone(sd._ARG_TOKEN.search("VO: TNT SPORTS ARG ᴴᴰ"))
        self.assertIsNotNone(sd._ARG_TOKEN.search("|ARG| TNT SPORT"))
        self.assertIsNone(sd._ARG_TOKEN.search("UK: TNT SPORTS 1 HD"))
        self.assertIsNone(sd._ARG_TOKEN.search("US: TNT SPORTS BOX OFFICE"))
        self.assertIsNone(sd._ARG_TOKEN.search("CANAL LARGO HD"))

    def test_pick_healthy_skips_dead_streams_and_prefers_verified(self):
        dead = SimpleNamespace(id=10, name="VO: TNT SPORTS ARG", stream_stats={"ffmpeg_output_bitrate": 195.0})
        unknown = SimpleNamespace(id=20, name="ARG: TNT BACKUP", stream_stats={})
        healthy = SimpleNamespace(id=30, name="ARG: TNT SPORTS HD", stream_stats={"ffmpeg_output_bitrate": 2800.0})

        # Entre muerto, desconocido y sano -> elige el sano
        chosen = self.daemon._pick_healthy([dead, unknown, healthy])
        self.assertEqual(chosen.id, 30)

        # Entre muerto y desconocido -> descarta el muerto y elige el desconocido
        chosen2 = self.daemon._pick_healthy([dead, unknown])
        self.assertEqual(chosen2.id, 20)

        # Solo muerto -> devuelve None (para forzar reconexión limpia sin cambiar a stream muerto)
        self.assertIsNone(self.daemon._pick_healthy([dead]))


class TestStreamDaemonAuditHysteresis(unittest.TestCase):
    def setUp(self):
        self.daemon = sd.SportVivoDaemon()
        self.channel_uuid = "482f2d92-0a07-4d2c-9b45-06b3bb3018b5"
        self.meta_key = f"live:channel:{self.channel_uuid}:metadata"

    def _make_meta(self, bitrate="193.0", uptime_sec=60, state=ChannelState.ACTIVE, stream_id="145617"):
        return {
            ChannelMetadataField.STATE: state,
            ChannelMetadataField.CHANNEL_NAME: "TNT Sports",
            ChannelMetadataField.STREAM_ID: stream_id,
            ChannelMetadataField.STREAM_NAME: "ARG: TNT SPORTS ᴿᴬᵂ",
            ChannelMetadataField.INIT_TIME: str(time.time() - uptime_sec),
            ChannelMetadataField.FFMPEG_OUTPUT_BITRATE: str(bitrate),
        }

    def test_ignores_startup_grace_period(self):
        self.daemon.redis_client = FakeRedis(clients_count=1, metadata=self._make_meta(bitrate="193.0", uptime_sec=12))
        with patch.object(self.daemon, "_handle_zombie") as mock_failover:
            for _ in range(6):
                self.daemon._audit_channel(self.channel_uuid, self.meta_key)
            mock_failover.assert_not_called()

    def test_requires_consecutive_low_samples_and_respects_cooldown(self):
        self.daemon.redis_client = FakeRedis(clients_count=1, metadata=self._make_meta(bitrate="193.0", uptime_sec=60))
        with patch.object(self.daemon, "_handle_zombie") as mock_failover:
            # Lecturas 1, 2 y 3 bajas -> aún no dispara
            for _ in range(sd.LOW_SAMPLES_REQUIRED - 1):
                self.daemon._audit_channel(self.channel_uuid, self.meta_key)
            mock_failover.assert_not_called()

            # Lectura 4 baja consecutiva -> dispara failover exactamente 1 vez
            self.daemon._audit_channel(self.channel_uuid, self.meta_key)
            self.assertEqual(mock_failover.call_count, 1)

            # Siguientes 4 lecturas bajas dentro del cooldown de 300s -> NO vuelve a disparar
            for _ in range(sd.LOW_SAMPLES_REQUIRED + 2):
                self.daemon._audit_channel(self.channel_uuid, self.meta_key)
            self.assertEqual(mock_failover.call_count, 1)

    def test_counter_resets_if_bitrate_recovers(self):
        self.daemon.redis_client = FakeRedis(clients_count=1, metadata=self._make_meta(bitrate="193.0", uptime_sec=60))
        with patch.object(self.daemon, "_handle_zombie") as mock_failover:
            # 3 lecturas bajas
            for _ in range(sd.LOW_SAMPLES_REQUIRED - 1):
                self.daemon._audit_channel(self.channel_uuid, self.meta_key)

            # 1 lectura sana (2750 kbps) resetea el contador
            self.daemon.redis_client.metadata[ChannelMetadataField.FFMPEG_OUTPUT_BITRATE] = "2750.0"
            self.daemon._audit_channel(self.channel_uuid, self.meta_key)
            self.assertEqual(self.daemon.channel_state[self.channel_uuid]["low"], 0)

            # Otra lectura baja vuelve a empezar desde 1/4
            self.daemon.redis_client.metadata[ChannelMetadataField.FFMPEG_OUTPUT_BITRATE] = "193.0"
            self.daemon._audit_channel(self.channel_uuid, self.meta_key)
            self.assertEqual(self.daemon.channel_state[self.channel_uuid]["low"], 1)
            mock_failover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
