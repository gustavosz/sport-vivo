#!/usr/bin/env python3
"""
tests/test_sync_match.py
------------------------
Tests unitarios para la lógica de detección, filtrado, fechas y nombrado de partidos (src/sync_match.py).
"""

import os
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace

for _p in ("/app", "/app/src", os.path.join(os.path.dirname(__file__), "..", "src")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import sync_match as sm


def make_stream(name: str, stream_id: int = 1):
    return SimpleNamespace(id=stream_id, name=name)


class TestSyncMatchDates(unittest.TestCase):
    def setUp(self):
        self.today = sm.local_now().date()
        self.tomorrow = self.today + timedelta(days=1)
        self.yesterday = self.today - timedelta(days=1)
        self.far_future = self.today + timedelta(days=12)

    def test_today_d_mon_format_is_accepted(self):
        d_mon = f"{self.today.day} {self.today.strftime('%b')}"
        s = make_stream(f"NEXT | RIVER PLATE VS. RACING CLUB | Sun {d_mon} 23:00 CET (ES) | ES: VIX PPV 2")
        self.assertIsNotNone(sm.score_stream(s))

    def test_yesterday_is_rejected(self):
        d_mon = f"{self.yesterday.day} {self.yesterday.strftime('%b')}"
        s = make_stream(f"NEXT | RIVER PLATE VS. RACING CLUB | Sun {d_mon} 23:00 CET (ES) | ES: VIX PPV 2")
        self.assertIsNone(sm.score_stream(s))

    def test_tomorrow_utc_night_match_in_argentina_is_accepted(self):
        d_mon = f"{self.tomorrow.day} {self.tomorrow.strftime('%b')}"
        s = make_stream(f"NEXT | BOCA JUNIORS VS TIGRE | {d_mon} 00:30 UTC (ARG) | ARG: FANATIZ PPV 1")
        self.assertIsNotNone(sm.score_stream(s))

    def test_iso_date_today_is_accepted(self):
        mon_d = f"{self.today.strftime('%b')} {self.today.day}"
        s = make_stream(f"US (ESPN+ 029) | Boca Juniors vs. Lanús {mon_d} 2:55PM ET ({self.today.isoformat()} 14:55:00)")
        self.assertIsNotNone(sm.score_stream(s))

    def test_far_future_date_is_rejected(self):
        s = make_stream(f"(Fanatiz 090) | Aldosivi vs River Plate ({self.far_future.isoformat()} 19:00:45)")
        self.assertIsNone(sm.score_stream(s))

    def test_month_followed_by_time_is_not_parsed_as_day(self):
        self.assertIsNone(sm.extract_event_date("RIVER PLATE VS RACING | Oct 23:00 UTC"))


class TestSyncMatchFiltersAndScoring(unittest.TestCase):
    def test_excludes_placeholders_and_ended_events(self):
        invalid_names = [
            "- NO EVENT STREAMING - | 8K EXCLUSIVE | ARG: FANATIZ PPV 13",
            "END | RIVER PLATE VS. RACING",
            "ENDED | BOCA JUNIORS VS. TIGRE",
        ]
        for name in invalid_names:
            with self.subTest(name=name):
                self.assertIsNone(sm.score_stream(make_stream(name)))

    def test_excludes_foreign_homonyms_and_other_sports(self):
        invalid_names = [
            "UY: River Plate Uruguay vs Peñarol",
            "US (ESPN+ 100) | Soccer: Sestao River vs. Espanyol",
            "NCAA: UC Riverside vs UCLA",
            "Hockey: River Plate vs GEBA",
            "Baseball: Boca Chica vs Santo Domingo",
            "UY: Boston River vs Nacional | Campeonato Uruguayo",
            "NFHS | Toms River East vs Brick Memorial",
            "Campbell River Storm vs Victoria Cougars",
            "Langley Rivermen vs Alberni Valley",
            "River vs Tigers (High School Football)",
        ]
        for name in invalid_names:
            with self.subTest(name=name):
                self.assertIsNone(sm.score_stream(make_stream(name)))

    def test_excludes_u16_messi_cup_and_nordic_feeds(self):
        invalid_youth_and_nordic = [
            "TeliaPlay SE 44: River Plate U16 vs Ajax U16",
            "TeliaPlay SE 37: Boca Juniors U16 vs UE Cornella U16",
            "SE: DISNEY+ | Boca Juniors vs. Flamengo | Oct 26",
            "DK: DISNEY+ | River Plate vs. Inter Milan | Oct 27",
            "US (ESPN+ 118) | Soccer: River Plate vs. Inter Milan (River Plate vs. Inter Milan)",
            "US (ESPN+ 099) | Soccer: Boca Juniors vs. Flamengo (Boca Juniors vs. Flamengo) (2026-10-27 13:25:00)",
            "US (ESPN+ 015) | Soccer: Boca Juniors vs. UE Cornellà",
            "ARG: Sub-20 River Plate vs Racing",
            "Torneo Proyección Reserva: Boca Juniors vs Lanús",
        ]
        for name in invalid_youth_and_nordic:
            with self.subTest(name=name):
                self.assertIsNone(sm.score_stream(make_stream(name)))

    def test_accepts_short_river_or_boca_when_south_american_context_present(self):
        res_river = sm.score_stream(make_stream("ARG: FANATIZ PPV 1 | River vs Racing Club"))
        self.assertIsNotNone(res_river)
        self.assertEqual(res_river[1], "River Plate")

        res_boca = sm.score_stream(make_stream("ARG: FANATIZ PPV 2 | Boca vs Lanús"))
        self.assertIsNotNone(res_boca)
        self.assertEqual(res_boca[1], "Boca Juniors")

    def test_channel_split_afa_vs_international(self):
        self.assertTrue(sm.channel_accepts(17, "ARG: FANATIZ PPV 1 | Boca vs River"))
        self.assertTrue(sm.channel_accepts(17, "AFA Play | River Plate vs Racing"))
        self.assertFalse(sm.channel_accepts(17, "ES: VIX PPV 2 | River Plate vs Racing"))

        self.assertTrue(sm.channel_accepts(18, "ES: VIX PPV 2 | River Plate vs Racing"))
        self.assertTrue(sm.channel_accepts(18, "US: ESPN+ PPV 13 | Boca Juniors vs Lanús"))
        self.assertFalse(sm.channel_accepts(18, "(Fanatiz 087) | Boca Juniors vs Defensa"))

    def test_platform_detection(self):
        _, _, platform_afa = sm.score_stream(make_stream("LIVE | BOCA JUNIORS VS LANÚS | ARG: FANATIZ PPV 1"))
        self.assertEqual(platform_afa, "AFA Play")

        _, _, platform_vix = sm.score_stream(make_stream("LIVE | RIVER PLATE VS RACING | ES: VIX PPV 2"))
        self.assertEqual(platform_vix, "ViX HD")

        _, _, platform_espn_plus = sm.score_stream(make_stream("LIVE | RIVER PLATE VS RACING | US: ESPN+ PPV 13"))
        self.assertEqual(platform_espn_plus, "ESPN+")

    def test_clean_channel_name_formats_legibly(self):
        name1 = sm.clean_channel_name(
            "(Fanatiz 087) | Boca Juniors vs Defensa y Justicia (2026-11-07 19:00:30)",
            "Boca Juniors",
            "AFA Play",
        )
        self.assertEqual(name1, "⚽ Boca Juniors Vs Defensa Y Justicia (AFA Play)")

        name2 = sm.clean_channel_name(
            "LIVE | CLUB ATLÉTICO RIVER PLATE VS. RACING CLUB | Sun 25 Oct 23:00 CET | ES: VIX PPV 2",
            "River Plate",
            "ViX HD",
        )
        self.assertEqual(name2, "⚽ River Plate Vs. Racing Club (ViX HD)")

        name3 = sm.clean_channel_name(
            "US (ESPN+ 118) | Soccer: River Plate vs. Racing Club (River Plate vs. Racing Club) (2026-10-27 16:25:10)",
            "River Plate",
            "ESPN+",
        )
        self.assertEqual(name3, "⚽ River Plate Vs. Racing Club (ESPN+)")

    def test_standby_mode_assigns_standby_stream_instead_of_leaving_stale_event(self):
        from unittest.mock import patch

        fake_account = SimpleNamespace(id=4, name="World 8K")
        standby_17 = make_stream("- NO EVENT STREAMING - | ARG: FANATIZ PPV 1", stream_id=145679)
        standby_18 = make_stream("NO EVENT STREAMING | ES: VIX PPV 1", stream_id=108241)

        def fake_resolve(acc, ch):
            return standby_17 if ch == 17 else standby_18

        applied = []

        def fake_apply(ch, stream, name, dry_run=False, log=print):
            applied.append((ch, stream.id if stream else None, name))
            return True

        with patch.object(sm, "get_active_account", return_value=fake_account), \
             patch.object(sm, "find_candidates", return_value=[]), \
             patch.object(sm, "resolve_standby_stream", side_effect=fake_resolve), \
             patch.object(sm, "apply_channel", side_effect=fake_apply):
            sm.sync_event_channels(team="auto", channels=(17, 18), dry_run=True, log=lambda *_: None)

        self.assertEqual(applied, [
            (17, 145679, "AFA Play (Fanatiz / Liga Arg)"),
            (18, 108241, "ViX PPV / Internacional"),
        ])


if __name__ == "__main__":
    unittest.main()
