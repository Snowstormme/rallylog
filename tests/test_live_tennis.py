import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tennisd import create_app, db
from tennisd.live_tennis import display_score, normalize_match, sync_matches
from tennisd.models import LiveMatch


def fixture(status="live", starts_at=None):
    return {
        "id": 91234,
        "tournament": "Wimbledon",
        "tournament_id": "wimbledon-wta-singles",
        "tier": "grand_slam",
        "tour": "wta",
        "surface": "grass",
        "round": "Wimbledon - Quarter-finals",
        "round_code": "QF",
        "draw": "singles",
        "is_doubles": False,
        "status": status,
        "scheduled_time": (starts_at or datetime.now(timezone.utc)).isoformat(),
        "players": {
            "p1": {"id": 1, "name": "Iga Swiatek"},
            "p2": {"id": 2, "name": "Aryna Sabalenka"},
        },
        "score": {
            "games": [[6, 3, 2], [4, 6, 1]],
            "points": ["30", "15"], "server": 1,
            "timestamp": "2026-07-08T13:20:00Z",
        },
    }


class Response:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self.rows}


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.rows)


class LiveTennisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        database = Path(self.temporary.name) / "live.db"
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temporary.cleanup()

    def test_score_and_grand_slam_filtering(self):
        now = datetime(2026, 7, 8, 13, tzinfo=timezone.utc)
        row = fixture(starts_at=now)
        self.assertEqual(display_score(row["score"]), "6–4 3–6 2–1 (30–15)")
        normalized = normalize_match(row, now)
        self.assertEqual(normalized["tournament"], "Wimbledon")
        self.assertEqual(normalized["tour"], "WTA")
        row["tournament"] = "Berlin Open"
        self.assertIsNone(normalize_match(row, now))

    def test_upcoming_window_and_sync(self):
        now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        inside = fixture("upcoming", now + timedelta(days=3))
        outside = fixture("upcoming", now + timedelta(days=8))
        outside["id"] = 99999
        session = Session([inside, outside])
        with self.app.app_context(), patch.dict(os.environ, {"LIVETENNISAPI_KEY": "test-key"}):
            self.assertEqual(sync_matches("upcoming", session=session, now=now), 1)
            match = db.session.get(LiveMatch, "91234")
            self.assertEqual(match.player1_name, "Iga Swiatek")
            self.assertEqual(match.surface, "Grass")
        self.assertEqual(session.calls[0][1]["params"]["tier"], "grand_slam")
        self.assertEqual(session.calls[0][1]["params"]["draw"], "singles")

    def test_matches_page_and_internal_score_endpoint(self):
        with self.app.app_context():
            db.session.add(LiveMatch(
                provider_id="live-1", status="live", tour="ATP",
                tournament="US Open", surface="Hard", round="SF",
                starts_at=datetime.now(timezone.utc), player1_name="Carlos Alcaraz",
                player2_name="Jannik Sinner", score="6–4 2–3", server=2,
            ))
            db.session.commit()
        page = self.client.get("/matches")
        self.assertIn(b"Live on court", page.data)
        self.assertIn(b"surface-hard", page.data)
        self.assertIn(b"Carlos Alcaraz", page.data)
        payload = self.client.get("/api/live-matches").get_json()
        self.assertEqual(payload["matches"][0]["score"], "6\u20134 2\u20133")


if __name__ == "__main__":
    unittest.main()
