import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image
from tennisd import create_app, db
from tennisd.models import Comment, FollowedPlayer, Match, Player, ProfileImage, Report, Review, User, WatchlistItem
from sqlalchemy import select


class TennisdFlows(unittest.TestCase):
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
        for path in ("/", "/matches", "/players", "/tournaments", "/search", "/news", "/about", "/privacy", f"/matches/{self.match_id}"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        home = self.client.get("/")
        self.assertNotIn(b"hero-counts", home.data)
        self.assertNotIn(b"Start your diary", home.data)
        self.assertNotIn(b"Make every watch count", home.data)
        self.assertIn(b"data-featured-carousel", home.data)
        self.assertIn(b"home-match-card", home.data)
        self.assertIn(b"court-badge", home.data)
        self.assertIn(b"/photo", home.data)
        self.assertNotIn(b"nav-discover", home.data)
        for item in (b"nav-matches", b"nav-players", b"nav-tournaments", b"nav-notifications", b"nav-news", b"nav-search"):
            self.assertIn(item, home.data)
        self.assertIn(b"mobile-notifications", home.data)
        self.assertIn(b"<em></em><strong></strong><i></i><b></b>", home.data)
        register = self.client.get("/register")
        self.assertIn(b'data-password-toggle', register.data)
        self.assertIn(b'aria-controls="auth-password"', register.data)
        with self.client.get("/static/app.js") as script:
            self.assertIn(b"data-password-toggle", script.data)
            self.assertNotIn(b"is-animating", script.data)
        self.assertIn(b"Jannik Sinner", self.client.get("/matches?q=Jannik+Sinner").data)
        self.assertEqual(self.client.get("/matches?tour=WTA").status_code, 200)
        matches = self.client.get("/matches")
        self.assertIn(b"archive-match-card", matches.data)
        self.assertIn(b"court-badge", matches.data)
        self.assertIn(b"match-portrait-left", matches.data)
        players = self.client.get("/players")
        self.assertIn(b"player-photo-card", players.data)
        self.assertIn(b"/photo", players.data)
        with self.app.app_context():
            player_id = db.session.scalar(select(Player.id).limit(1))
        profile = self.client.get(f"/players/{player_id}")
        self.assertIn(b"player-hero-photo", profile.data)
        self.assertIn(f"/players/{player_id}/photo".encode(), profile.data)

    def test_friend_requests_and_notifications(self):
        self.register("alice")
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("bob")
        self.client.post("/u/alice/friend", data={"csrf_token": self.token()})
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.client.get("/login")
        self.client.post("/login", data={
            "csrf_token": self.token(), "identity": "alice", "password": "long-test-password",
        })
        notifications = self.client.get("/notifications")
        self.assertIn(b"bob", notifications.data)
        with self.app.app_context():
            from tennisd.models import Friendship
            request_id = db.session.scalar(select(Friendship.id))
        self.client.post(f"/friend-requests/{request_id}/accept", data={"csrf_token": self.token()})
        self.assertIn(b"bob", self.client.get("/u/alice?tab=friends").data)

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

    def test_login_redirect_stays_on_site(self):
        self.register("alice")
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.client.get("/login?next=/%5Cexample.com")
        response = self.client.post("/login?next=/%5Cexample.com", data={
            "csrf_token": self.token(), "identity": "alice", "password": "long-test-password",
        })
        self.assertEqual(response.headers["Location"], "/me")

    def test_profile_settings_follow_and_html_escaping(self):
        self.register("alice")
        self.assertNotIn(b"Open your diary", self.client.get("/").data)
        with self.app.app_context():
            player_id = db.session.scalar(select(Player.id).limit(1))
        self.client.post(f"/players/{player_id}/follow", data={"csrf_token": self.token()})
        self.assertIn(b"Following", self.client.get(f"/players/{player_id}").data)
        self.client.post(f"/matches/{self.match_id}/watchlist", data={"csrf_token": self.token()})
        profile = self.client.get("/u/alice")
        for label in (b"Profile", b"Diary", b"Watchlist", b"Likes", b"Friends"):
            self.assertIn(label, profile.data)
        watchlist = self.client.get("/u/alice?tab=watchlist")
        self.assertIn(b"Your watchlist", watchlist.data)
        self.assertIn(b'aria-current="page">Watchlist', watchlist.data)
        response = self.client.post("/settings", data={
            "csrf_token": self.token(), "display_name": "Court Reader",
            "bio": "Grass-court fan",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Court Reader", self.client.get("/u/alice").data)
        portrait = BytesIO()
        Image.new("RGB", (48, 64), "#d6ed80").save(portrait, "PNG")
        portrait.seek(0)
        response = self.client.post("/settings", data={
            "csrf_token": self.token(), "display_name": "Court Reader",
            "bio": "Grass-court fan", "avatar": (portrait, "portrait.png"),
        }, content_type="multipart/form-data", follow_redirects=True)
        self.assertIn(b"Settings saved", response.data)
        with self.app.app_context():
            self.assertIsNotNone(db.session.scalar(select(ProfileImage)))
        avatar = self.client.get("/u/alice/avatar")
        self.assertEqual(avatar.status_code, 200)
        self.assertEqual(avatar.mimetype, "image/webp")
        self.assertIn(b'/u/alice/avatar', self.client.get("/u/alice").data)
        response = self.client.post(f"/matches/{self.match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30",
            "body": "<script>alert(1)</script>", "public": "on", "spoilers": "on",
        }, follow_redirects=True)
        self.assertIn(b"&lt;script&gt;", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)
        self.assertIn(b"Review contains spoilers", self.client.get("/u/alice?tab=diary").data)
        with self.app.app_context():
            self.assertIsNone(db.session.scalar(select(WatchlistItem.id)))

    def test_account_export_and_deletion(self):
        self.register("alice")
        with self.app.app_context():
            player_id = db.session.scalar(select(Player.id).limit(1))
            another_match_id = db.session.scalar(
                select(Match.id).where(Match.id != self.match_id).limit(1)
            )
        self.client.post(f"/players/{player_id}/follow", data={"csrf_token": self.token()})
        self.client.post(f"/matches/{another_match_id}/watchlist", data={"csrf_token": self.token()})
        self.client.post(f"/matches/{self.match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30",
            "rating": "9", "body": "Alice's private data", "public": "on",
        })
        with self.app.app_context():
            alice_review_id = db.session.scalar(select(Review.id))
        self.client.post("/logout", data={"csrf_token": self.token()})

        self.register("bob")
        self.client.post(f"/reviews/{alice_review_id}/comments", data={
            "csrf_token": self.token(), "body": "Bob's comment",
        })
        self.client.post(f"/matches/{another_match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30", "public": "on",
        })
        with self.app.app_context():
            bob_review_id = db.session.scalar(
                select(Review.id).where(Review.match_id == another_match_id)
            )
            bob_comment_id = db.session.scalar(
                select(Comment.id).where(Comment.review_id == alice_review_id)
            )
        self.client.post("/logout", data={"csrf_token": self.token()})

        self.client.get("/login")
        self.client.post("/login", data={
            "csrf_token": self.token(), "identity": "alice", "password": "long-test-password",
        })
        self.assertIn(
            f'action="/comments/{bob_comment_id}/delete"'.encode(),
            self.client.get(f"/matches/{self.match_id}").data,
        )
        self.client.post(f"/reviews/{bob_review_id}/comments", data={
            "csrf_token": self.token(), "body": "Alice's comment",
        })
        export = self.client.get("/settings/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn("no-store", export.headers["Cache-Control"])
        data = export.get_json()
        self.assertEqual(data["email"], "alice@example.com")
        self.assertEqual(data["diary"][0]["rating_out_of_five"], 4.5)
        self.assertEqual(data["comments"][0]["body"], "Alice's comment")
        self.assertEqual(data["watchlist_match_ids"], [another_match_id])
        self.assertEqual(len(data["followed_players"]), 1)
        self.assertNotIn("password_hash", export.get_data(as_text=True))

        self.client.post("/settings/delete-account", data={
            "csrf_token": self.token(), "username": "alice", "password": "wrong-password",
        })
        with self.app.app_context():
            self.assertIsNotNone(db.session.scalar(select(User.id).where(User.username == "alice")))
        self.assertEqual(self.client.post("/settings/delete-account", data={
            "csrf_token": self.token(), "username": "alice", "password": "long-test-password",
        }).status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.scalar(select(User.id).where(User.username == "alice")))
            self.assertIsNone(db.session.scalar(select(Review.id).where(Review.id == alice_review_id)))
            self.assertIsNotNone(db.session.scalar(select(Review.id).where(Review.id == bob_review_id)))
            self.assertIsNone(db.session.scalar(select(Comment.id)))
            self.assertIsNone(db.session.scalar(select(FollowedPlayer.id)))
            self.assertIsNone(db.session.scalar(select(WatchlistItem.id)))
        self.assertEqual(self.client.get("/settings/export").status_code, 302)

    def test_reports_are_moderated_by_verified_admin(self):
        self.app.config["ADMIN_EMAIL"] = "alice@example.com"
        self.register("alice")
        self.client.post(f"/matches/{self.match_id}/log", data={
            "csrf_token": self.token(), "watched_on": "2025-01-30",
            "body": "A public review", "public": "on",
        })
        with self.app.app_context():
            review_id = db.session.scalar(select(Review.id))
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.register("bob")
        self.assertIn(b"Report", self.client.get(f"/matches/{self.match_id}").data)
        response = self.client.post("/reports", data={
            "csrf_token": self.token(), "target": "review",
            "target_id": str(review_id), "reason": "spam",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/moderation").status_code, 403)
        with self.app.app_context():
            report_id = db.session.scalar(select(Report.id))
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.client.get("/login")
        self.client.post("/login", data={
            "csrf_token": self.token(), "identity": "alice", "password": "long-test-password",
        })
        self.assertIn(b"A public review", self.client.get("/moderation").data)
        self.client.post(f"/moderation/reports/{report_id}/remove", data={
            "csrf_token": self.token(),
        })
        with self.app.app_context():
            self.assertIsNone(db.session.scalar(select(Review.id)))
            self.assertIsNone(db.session.scalar(select(Report.id)))


if __name__ == "__main__":
    unittest.main()
