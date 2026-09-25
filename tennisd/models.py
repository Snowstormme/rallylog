from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint
from werkzeug.security import check_password_hash

from . import db


def utcnow():
    return datetime.now(timezone.utc)


PASSWORD_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(24), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(60), nullable=False)
    bio = db.Column(db.String(280), default="", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reviews = db.relationship("Review", back_populates="user", cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="reporter", cascade="all, delete-orphan")
    auth_state = db.relationship("AuthState", back_populates="user", uselist=False, cascade="all, delete-orphan")
    auth_tokens = db.relationship("AuthToken", back_populates="user", cascade="all, delete-orphan")
    profile_image = db.relationship("ProfileImage", back_populates="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = PASSWORD_HASHER.hash(password)

    def check_password(self, password):
        if self.password_hash.startswith("$argon2id$"):
            try:
                return PASSWORD_HASHER.verify(self.password_hash, password)
            except (InvalidHashError, VerificationError):
                return False
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        version = self.auth_state.session_version if self.auth_state else 0
        return f"{self.id}:{version}"


class ProfileImage(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    mime_type = db.Column(db.String(32), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    user = db.relationship("User", back_populates="profile_image")


class AuthState(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    email_verified_at = db.Column(db.DateTime(timezone=True))
    session_version = db.Column(db.Integer, default=0, nullable=False)
    user = db.relationship("User", back_populates="auth_state")


class AuthToken(db.Model):
    digest = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    purpose = db.Column(db.String(16), nullable=False)
    expires_at = db.Column(db.BigInteger, nullable=False)
    user = db.relationship("User", back_populates="auth_tokens")


class RateLimitEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.BigInteger, nullable=False, index=True)


class Player(db.Model):
    id = db.Column(db.String(24), primary_key=True)
    tour = db.Column(db.String(3), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    country = db.Column(db.String(3))
    hand = db.Column(db.String(1))
    height_cm = db.Column(db.Integer)
    born_on = db.Column(db.Date)
    wikidata_id = db.Column(db.String(20))
    prize_money_usd = db.Column(db.BigInteger)
    prize_money_asof = db.Column(db.Date)
    prize_checked_at = db.Column(db.DateTime(timezone=True))
    won_matches = db.relationship("Match", foreign_keys="Match.winner_id", back_populates="winner")
    lost_matches = db.relationship("Match", foreign_keys="Match.loser_id", back_populates="loser")


class Match(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    tour = db.Column(db.String(3), nullable=False, index=True)
    tournament = db.Column(db.String(120), nullable=False, index=True)
    level = db.Column(db.String(12), nullable=False)
    surface = db.Column(db.String(12), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    round = db.Column(db.String(4), nullable=False)
    winner_id = db.Column(db.String(24), db.ForeignKey("player.id"), nullable=False, index=True)
    loser_id = db.Column(db.String(24), db.ForeignKey("player.id"), nullable=False, index=True)
    score = db.Column(db.String(120), nullable=False)
    best_of = db.Column(db.Integer)
    minutes = db.Column(db.Integer)
    winner_rank = db.Column(db.Integer)
    loser_rank = db.Column(db.Integer)
    w_ace = db.Column(db.Integer)
    l_ace = db.Column(db.Integer)
    w_df = db.Column(db.Integer)
    l_df = db.Column(db.Integer)
    w_svpt = db.Column(db.Integer)
    l_svpt = db.Column(db.Integer)
    w_first_in = db.Column(db.Integer)
    l_first_in = db.Column(db.Integer)
    w_first_won = db.Column(db.Integer)
    l_first_won = db.Column(db.Integer)
    w_bp_saved = db.Column(db.Integer)
    l_bp_saved = db.Column(db.Integer)
    w_bp_faced = db.Column(db.Integer)
    l_bp_faced = db.Column(db.Integer)
    winner = db.relationship("Player", foreign_keys=[winner_id], back_populates="won_matches")
    loser = db.relationship("Player", foreign_keys=[loser_id], back_populates="lost_matches")
    reviews = db.relationship("Review", back_populates="match", cascade="all, delete-orphan")


class LiveMatch(db.Model):
    """Current Grand Slam, 1000 or 500 fixture mirrored from the live provider."""

    provider_id = db.Column(db.String(64), primary_key=True)
    status = db.Column(db.String(12), nullable=False, index=True)
    tour = db.Column(db.String(3), nullable=False, index=True)
    tournament = db.Column(db.String(160), nullable=False)
    tournament_id = db.Column(db.String(80))
    surface = db.Column(db.String(12), nullable=False)
    round = db.Column(db.String(32))
    starts_at = db.Column(db.DateTime(timezone=True), index=True)
    player1_name = db.Column(db.String(120), nullable=False)
    player2_name = db.Column(db.String(120), nullable=False)
    player1_provider_id = db.Column(db.String(32))
    player2_provider_id = db.Column(db.String(32))
    score = db.Column(db.String(160), default="", nullable=False)
    server = db.Column(db.Integer)
    provider_updated_at = db.Column(db.DateTime(timezone=True))
    synced_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Review(db.Model):
    __table_args__ = (
        UniqueConstraint("user_id", "match_id", name="uq_user_match_review"),
        CheckConstraint("rating_half IS NULL OR rating_half BETWEEN 1 AND 10", name="valid_rating"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    match_id = db.Column(db.String(100), db.ForeignKey("match.id"), nullable=False, index=True)
    rating_half = db.Column(db.Integer)
    watched_on = db.Column(db.Date, nullable=False)
    body = db.Column(db.String(3000), default="", nullable=False)
    is_favorite = db.Column(db.Boolean, default=False, nullable=False)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    has_spoilers = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    user = db.relationship("User", back_populates="reviews")
    match = db.relationship("Match", back_populates="reviews")
    comments = db.relationship("Comment", back_populates="review", cascade="all, delete-orphan")
    reports = db.relationship("Report", back_populates="review", cascade="all, delete-orphan")


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("review.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    review = db.relationship("Review", back_populates="comments")
    user = db.relationship("User")
    reports = db.relationship("Report", back_populates="comment", cascade="all, delete-orphan")


class Report(db.Model):
    __table_args__ = (
        CheckConstraint("(review_id IS NULL) <> (comment_id IS NULL)", name="one_report_target"),
    )
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    review_id = db.Column(db.Integer, db.ForeignKey("review.id"), index=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), index=True)
    reason = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(12), default="open", nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reporter = db.relationship("User", back_populates="reports")
    review = db.relationship("Review", back_populates="reports")
    comment = db.relationship("Comment", back_populates="reports")


class FollowedPlayer(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "player_id", name="uq_user_player_follow"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    player_id = db.Column(db.String(24), db.ForeignKey("player.id"), nullable=False, index=True)
    player = db.relationship("Player")


class TournamentSubscription(db.Model):
    __table_args__ = (
        UniqueConstraint("user_id", "tour", "tournament", name="uq_user_tournament_subscription"),
        CheckConstraint("tour IN ('ATP', 'WTA')", name="valid_subscription_tour"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    tour = db.Column(db.String(3), nullable=False, index=True)
    tournament = db.Column(db.String(120), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class WatchlistItem(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "match_id", name="uq_user_match_watchlist"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    match_id = db.Column(db.String(100), db.ForeignKey("match.id"), nullable=False, index=True)
    added_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    match = db.relationship("Match")


class Friendship(db.Model):
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friend_request"),
        CheckConstraint("requester_id <> addressee_id", name="different_friend_users"),
        CheckConstraint("status IN ('pending', 'accepted')", name="valid_friend_status"),
    )
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    addressee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(12), default="pending", nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    requester = db.relationship("User", foreign_keys=[requester_id])
    addressee = db.relationship("User", foreign_keys=[addressee_id])
