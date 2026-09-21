import hmac
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased, joinedload

from . import db
from .models import Comment, FollowedPlayer, Match, Player, Review, User
from .prize_money import update_prize_money
from .stats import community_statistics, diary_statistics, percent, player_statistics

site = Blueprint("site", __name__)


@site.before_app_request
def check_csrf():
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(submitted, expected):
            abort(400, "Your form expired. Reload the page and try again.")


def safe_next(default="site.home"):
    target = request.args.get("next", "")
    parsed = urlsplit(target)
    return target if target.startswith("/") and not target.startswith("//") and not parsed.netloc else url_for(default)


@site.get("/")
def home():
    featured = db.session.scalar(
        select(Match).where(Match.level == "G", Match.round == "F")
        .order_by(Match.week_start.desc(), Match.tour).limit(1)
    )
    recent_matches = db.session.scalars(
        select(Match).where(Match.level == "G", Match.round == "F")
        .order_by(Match.week_start.desc(), Match.tour).limit(8)
    ).all()
    recent_reviews = db.session.scalars(
        select(Review).where(Review.is_public.is_(True))
        .options(joinedload(Review.user), joinedload(Review.match))
        .order_by(Review.created_at.desc()).limit(4)
    ).all()
    counts = {
        "matches": db.session.scalar(select(func.count(Match.id))),
        "players": db.session.scalar(select(func.count(Player.id))),
        "logs": db.session.scalar(select(func.count(Review.id))),
    }
    return render_template(
        "home.html", featured=featured, recent_matches=recent_matches,
        recent_reviews=recent_reviews, counts=counts,
    )


@site.get("/matches")
def matches():
    query = request.args.get("q", "").strip()[:80]
    tour = request.args.get("tour", "")
    surface = request.args.get("surface", "")
    year = request.args.get("year", "")
    level = request.args.get("level", "")
    order = request.args.get("order", "newest")
    statement = select(Match)
    if query:
        winner = aliased(Player)
        loser = aliased(Player)
        statement = statement.join(winner, Match.winner).join(loser, Match.loser).where(
            or_(
                Match.tournament.ilike(f"%{query}%"),
                winner.name.ilike(f"%{query}%"),
                loser.name.ilike(f"%{query}%"),
            )
        )
    if tour in ("ATP", "WTA"):
        statement = statement.where(Match.tour == tour)
    if surface in ("Hard", "Clay", "Grass", "Carpet"):
        statement = statement.where(Match.surface == surface)
    if level in ("G", "M", "A", "F"):
        statement = statement.where(Match.level == level)
    if year.isdigit() and 1968 <= int(year) <= 2026:
        statement = statement.where(func.extract("year", Match.week_start) == int(year))
    statement = statement.order_by(
        Match.week_start.asc() if order == "oldest" else Match.week_start.desc(),
        Match.tournament,
    )
    page = max(1, request.args.get("page", 1, type=int))
    pagination = db.paginate(statement, page=page, per_page=18, error_out=False)
    return render_template(
        "matches.html", pagination=pagination, query=query, tour=tour,
        surface=surface, year=year, level=level, order=order,
    )


@site.get("/matches/<path:match_id>")
def match_detail(match_id):
    match = db.get_or_404(Match, match_id)
    reviews = db.session.scalars(
        select(Review).where(Review.match_id == match_id, Review.is_public.is_(True))
        .options(joinedload(Review.user), joinedload(Review.comments).joinedload(Comment.user))
        .order_by(Review.created_at.desc())
    ).unique().all()
    own_review = None
    if current_user.is_authenticated:
        own_review = db.session.scalar(
            select(Review).where(Review.match_id == match_id, Review.user_id == current_user.id)
        )
    serve_stats = []
    if match.w_ace is not None and match.l_ace is not None:
        serve_stats.append(("Aces", match.w_ace, match.l_ace, None))
    if match.w_df is not None and match.l_df is not None:
        serve_stats.append(("Double faults", match.w_df, match.l_df, None))
    if match.w_svpt and match.l_svpt and match.w_first_in is not None and match.l_first_in is not None:
        serve_stats.append((
            "First serve in", percent(match.w_first_in, match.w_svpt),
            percent(match.l_first_in, match.l_svpt), "%",
        ))
    if match.w_first_in and match.l_first_in and match.w_first_won is not None and match.l_first_won is not None:
        serve_stats.append((
            "First serve points won", percent(match.w_first_won, match.w_first_in),
            percent(match.l_first_won, match.l_first_in), "%",
        ))
    return render_template(
        "match.html", match=match, reviews=reviews, own_review=own_review,
        community=community_statistics(match), serve_stats=serve_stats, today=date.today(),
    )


@site.get("/players")
def players():
    query = request.args.get("q", "").strip()[:80]
    tour = request.args.get("tour", "")
    statement = select(Player)
    if query:
        statement = statement.where(Player.name.ilike(f"%{query}%"))
    if tour in ("ATP", "WTA"):
        statement = statement.where(Player.tour == tour)
    statement = statement.order_by(Player.name)
    pagination = db.paginate(
        statement, page=max(1, request.args.get("page", 1, type=int)),
        per_page=24, error_out=False,
    )
    return render_template("players.html", pagination=pagination, query=query, tour=tour)


@site.get("/players/<player_id>")
def player_detail(player_id):
    player = db.get_or_404(Player, player_id)
    update_prize_money(player)
    stats = player_statistics(player)
    following = False
    if current_user.is_authenticated:
        following = db.session.scalar(
            select(FollowedPlayer.id).where(
                FollowedPlayer.user_id == current_user.id,
                FollowedPlayer.player_id == player.id,
            )
        ) is not None
    return render_template("player.html", player=player, stats=stats, following=following)


@site.post("/players/<player_id>/follow")
@login_required
def follow_player(player_id):
    db.get_or_404(Player, player_id)
    follow = db.session.scalar(
        select(FollowedPlayer).where(
            FollowedPlayer.user_id == current_user.id,
            FollowedPlayer.player_id == player_id,
        )
    )
    if follow:
        db.session.delete(follow)
    else:
        db.session.add(FollowedPlayer(user_id=current_user.id, player_id=player_id))
    db.session.commit()
    return redirect(url_for("site.player_detail", player_id=player_id))


@site.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("site.my_profile"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not re.fullmatch(r"[a-z0-9_]{3,24}", username):
            flash("Username: 3–24 lowercase letters, numbers or underscores.", "error")
        elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 255:
            flash("Enter a valid email address.", "error")
        elif len(password) < 10 or len(password) > 128:
            flash("Use a password with 10–128 characters.", "error")
        elif db.session.scalar(select(User.id).where(or_(User.username == username, User.email == email))):
            flash("That username or email is already in use.", "error")
        else:
            user = User(username=username, email=email, display_name=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            session.clear()
            login_user(user)
            flash("Welcome to Rallylog. Your diary is ready.", "success")
            return redirect(url_for("site.my_profile"))
    return render_template("auth.html", mode="register")


@site.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("site.my_profile"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(
            select(User).where(or_(User.username == identity, User.email == identity))
        )
        if user and user.check_password(password):
            session.clear()
            login_user(user)
            return redirect(safe_next("site.my_profile"))
        flash("Incorrect username, email or password.", "error")
    return render_template("auth.html", mode="login")


@site.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("site.home"))


@site.get("/me")
@login_required
def my_profile():
    return redirect(url_for("site.profile", username=current_user.username))


@site.get("/u/<username>")
def profile(username):
    user = db.session.scalar(select(User).where(User.username == username.lower()))
    if user is None:
        abort(404)
    own = current_user.is_authenticated and current_user.id == user.id
    statement = select(Review).where(Review.user_id == user.id)
    if not own:
        statement = statement.where(Review.is_public.is_(True))
    reviews = db.session.scalars(
        statement.options(joinedload(Review.match).joinedload(Match.winner),
                          joinedload(Review.match).joinedload(Match.loser))
        .order_by(Review.watched_on.desc(), Review.id.desc())
    ).all()
    followed = []
    if own:
        followed = db.session.scalars(
            select(FollowedPlayer).where(FollowedPlayer.user_id == user.id)
            .options(joinedload(FollowedPlayer.player)).limit(12)
        ).all()
    return render_template(
        "profile.html", user=user, reviews=reviews,
        stats=diary_statistics(reviews), own=own, followed=followed,
    )


@site.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        bio = request.form.get("bio", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        if not 1 <= len(display_name) <= 60 or len(bio) > 280:
            flash("Display name or bio is too long.", "error")
        elif new_password and (not current_user.check_password(current_password) or len(new_password) < 10):
            flash("Check your current password; the new one needs at least 10 characters.", "error")
        else:
            current_user.display_name = display_name
            current_user.bio = bio
            if new_password:
                current_user.set_password(new_password)
            db.session.commit()
            flash("Settings saved.", "success")
            return redirect(url_for("site.settings"))
    return render_template("settings.html")


@site.post("/matches/<path:match_id>/log")
@login_required
def log_match(match_id):
    match = db.get_or_404(Match, match_id)
    try:
        watched_on = date.fromisoformat(request.form.get("watched_on", ""))
        if watched_on > date.today() or watched_on < match.week_start:
            raise ValueError
        rating_text = request.form.get("rating", "")
        rating = int(rating_text) if rating_text else None
        if rating is not None and not 1 <= rating <= 10:
            raise ValueError
    except ValueError:
        flash("Choose a valid viewing date and rating.", "error")
        return redirect(url_for("site.match_detail", match_id=match_id))

    body = request.form.get("body", "").strip()
    if len(body) > 3000:
        flash("Keep your review under 3,000 characters.", "error")
        return redirect(url_for("site.match_detail", match_id=match_id))
    review = db.session.scalar(
        select(Review).where(Review.user_id == current_user.id, Review.match_id == match_id)
    )
    if review is None:
        review = Review(user_id=current_user.id, match_id=match_id)
        db.session.add(review)
    review.watched_on = watched_on
    review.rating_half = rating
    review.body = body
    review.is_favorite = request.form.get("favorite") == "on"
    review.is_public = request.form.get("public") == "on"
    review.has_spoilers = request.form.get("spoilers") == "on"
    db.session.commit()
    flash("Your match diary entry was saved.", "success")
    return redirect(url_for("site.match_detail", match_id=match_id))


@site.post("/reviews/<int:review_id>/delete")
@login_required
def delete_review(review_id):
    review = db.get_or_404(Review, review_id)
    if review.user_id != current_user.id:
        abort(403)
    match_id = review.match_id
    db.session.delete(review)
    db.session.commit()
    flash("Diary entry deleted.", "success")
    return redirect(url_for("site.match_detail", match_id=match_id))


@site.post("/reviews/<int:review_id>/comments")
@login_required
def add_comment(review_id):
    review = db.get_or_404(Review, review_id)
    if not review.is_public:
        abort(404)
    body = request.form.get("body", "").strip()
    if not 1 <= len(body) <= 500:
        flash("Comments must be 1–500 characters.", "error")
    else:
        recent = db.session.scalar(
            select(Comment).where(
                Comment.user_id == current_user.id,
                Comment.created_at > datetime.now(timezone.utc) - timedelta(seconds=15),
            ).limit(1)
        )
        if recent:
            flash("Please wait a moment before commenting again.", "error")
        else:
            db.session.add(Comment(review_id=review.id, user_id=current_user.id, body=body))
            db.session.commit()
            flash("Comment added.", "success")
    return redirect(url_for("site.match_detail", match_id=review.match_id) + f"#review-{review.id}")


@site.post("/comments/<int:comment_id>/delete")
@login_required
def delete_comment(comment_id):
    comment = db.get_or_404(Comment, comment_id)
    if comment.user_id != current_user.id:
        abort(403)
    match_id = comment.review.match_id
    review_id = comment.review_id
    db.session.delete(comment)
    db.session.commit()
    return redirect(url_for("site.match_detail", match_id=match_id) + f"#review-{review_id}")


@site.get("/about")
def about():
    return render_template("about.html")
