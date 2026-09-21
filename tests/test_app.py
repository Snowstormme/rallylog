import tempfile
import unittest
from pathlib import Path

from rallylog import create_app, db
from rallylog.models import Match, Review
from sqlalchemy import select


class RallylogFlows(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        database = Path(self.temporary.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            self.match_id = db.session.scalar(select(Match.id).limit(1))

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temporary.cleanup()

    def token(self):
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def register(self, name):
        self.client.get("/register")
        return self.client.post("/register", data={
            "csrf_token": self.token(), "username": name,
            "email": f"{name}@example.com", "password": "long-test-password",
        }, follow_redirects=True)

    def test_core_pages_and_search(self):
        for path in ("/", "/matches", "/players", "/about", f"/matches/{self.match_id}"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertIn(b"Jannik Sinner", self.client.get("/matches?q=Jannik+Sinner").data)
        self.assertEqual(self.client.get("/matches?tour=WTA").status_code, 200)

    def test_diary_comments_and_private_entries(self):
        self.assertEqual(self.register("alice").status_code, 200)
        response = self.client.post(f"/matches/{self.match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30",
            "rating": "9", "body": "A final worth revisiting.", "public": "on",
            "favorite": "on",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A final worth revisiting.", response.data)
        self.assertIn(b"4.5", self.client.get("/u/alice").data)
        with self.app.app_context():
            review_id = db.session.scalar(select(Review.id))

        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("bob")
        response = self.client.post(f"/reviews/{review_id}/comments", data={
            "csrf_token": self.token(), "body": "That final set was special.",
        }, follow_redirects=True)
        self.assertIn(b"That final set was special.", response.data)

        self.client.post("/logout", data={"csrf_token": self.token()})
        self.client.get("/login")
        self.client.post("/login", data={
            "csrf_token": self.token(), "identity": "alice", "password": "long-test-password",
        })
        self.client.get(f"/matches/{self.match_id}")
        self.client.post(f"/matches/{self.match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30",
            "rating": "9", "body": "A final worth revisiting.",
        })
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.assertNotIn(b"A final worth revisiting.", self.client.get("/u/alice").data)
        self.assertNotIn(b"A final worth revisiting.", self.client.get(f"/matches/{self.match_id}").data)

    def test_csrf_and_review_ownership(self):
        self.register("alice")
        self.assertEqual(self.client.post(f"/matches/{self.match_id}/log", data={}).status_code, 400)
        self.client.post(f"/matches/{self.match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30", "public": "on",
        })
        with self.app.app_context():
            review_id = db.session.scalar(select(Review.id))
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("bob")
        self.assertEqual(
            self.client.post(f"/reviews/{review_id}/delete", data={"csrf_token": self.token()}).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
