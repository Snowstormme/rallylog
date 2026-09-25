import hmac
import html
import io
import re
import unicodedata
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import requests
from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, func, inspect, or_, select
from sqlalchemy.orm import aliased, joinedload

from . import db
from .models import AuthState, AuthToken, Comment, FollowedPlayer, Friendship, LiveMatch, Match, Player, ProfileImage, Report, Review, User, WatchlistItem, utcnow
from .news_feed import NEWS_SOURCES, fetch_news_items
from .prize_money import update_prize_money
from .security import client_ip, limit_action, send_account_email, valid_token
from .stats import community_statistics, diary_statistics, percent, player_statistics

site = Blueprint("site", __name__)

TOURNAMENT_LOCATIONS = {
    "australian open": "Melbourne, Australia",
    "roland garros": "Paris, France",
    "wimbledon": "London, United Kingdom",
    "us open": "New York, United States",
}


def match_location(match):
    return TOURNAMENT_LOCATIONS.get(match.tournament.lower(), "Location unavailable")


def current_match_rows(status):
    """Return an empty slate while a new deployment is waiting for its migration."""
    if not inspect(db.engine).has_table(LiveMatch.__tablename__):
        return []
    statement = select(LiveMatch).where(LiveMatch.status == status)
    if status == "upcoming":
        statement = statement.where(
            LiveMatch.starts_at >= utcnow() - timedelta(hours=6),
            LiveMatch.starts_at <= utcnow() + timedelta(days=7),
        )
    return db.session.scalars(
        statement.order_by(LiveMatch.starts_at, LiveMatch.tournament, LiveMatch.provider_id)
    ).all()


@lru_cache(maxsize=512)
def wikimedia_player_photo(wikidata_id):
    if not wikidata_id or not re.fullmatch(r"Q[1-9][0-9]*", wikidata_id):
        return None
    try:
        response = requests.get(
            f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json",
            headers={"Accept": "application/json", "User-Agent": "Tennisd/1.0 (player portraits)"},
            timeout=4,
        )
        response.raise_for_status()
        claim = response.json()["entities"][wikidata_id]["claims"]["P18"][0]
        filename = claim["mainsnak"]["datavalue"]["value"]
        return f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{quote(filename, safe='')}?width=420"
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException):
        return None


def normalized_person_name(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


@lru_cache(maxsize=2048)
def wikipedia_player_photo(name):
    """Find a public Wikipedia thumbnail when the catalog has no Wikidata link."""
    if not name or len(name) > 120:
        return None
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "generator": "search",
                "gsrsearch": f'intitle:"{name}" tennis', "gsrnamespace": 0,
                "gsrlimit": 5, "prop": "pageimages", "piprop": "thumbnail",
                "pithumbsize": 420, "format": "json",
            },
            headers={"User-Agent": "Tennisd/1.0 (player portraits)"}, timeout=4,
        )
        response.raise_for_status()
        target = normalized_person_name(name)
        pages = (response.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = re.sub(r"\s*\([^)]*\)\s*$", "", page.get("title", ""))
            if normalized_person_name(title) == target:
                source = (page.get("thumbnail") or {}).get("source")
                if source and source.startswith((
                    "https://upload.wikimedia.org/", "https://thumb.wikimedia.org/"
                )):
                    return source
    except (AttributeError, TypeError, ValueError, requests.RequestException):
        pass
    return None


def public_player_photo(player):
    return wikimedia_player_photo(player.wikidata_id) or wikipedia_player_photo(player.name)


def prepare_profile_image(upload):
    raw = upload.read(1_500_001)
    if not raw or len(raw) > 1_500_000:
        raise ValueError("Choose an image smaller than 1.5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width > 4096 or source.height > 4096:
                raise ValueError("The image dimensions are too large.")
            source.seek(0)
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, "WEBP", quality=84, method=6)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ValueError("Choose a valid JPG, PNG or WebP image.") from None
    data = output.getvalue()
    if len(data) > 500_000:
        raise ValueError("The processed image is still too large.")
    return data


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
    return (
        target if target.startswith("/") and not target.startswith("//")
        and "\\" not in target and not parsed.scheme and not parsed.netloc
        else url_for(default)
    )


@site.get("/")
def home():
    recent_matches = db.session.scalars(
        select(Match).where(Match.level.in_(("G", "M", "PM", "P", "A", "I")), Match.round == "F")
        .options(joinedload(Match.winner), joinedload(Match.loser))
        .order_by(Match.week_start.desc(), Match.tour).limit(8)
    ).all()
    recent_reviews = db.session.scalars(
        select(Review).where(Review.is_public.is_(True))
        .options(joinedload(Review.user), joinedload(Review.match))
        .order_by(Review.created_at.desc()).limit(4)
    ).all()
    return render_template(
        "home.html", featured_matches=recent_matches[:5], recent_matches=recent_matches,
        recent_reviews=recent_reviews, match_location=match_location,
    )


@site.get("/players/<player_id>/photo")
def player_photo(player_id):
    player = db.get_or_404(Player, player_id)
    photo_url = public_player_photo(player)
    if photo_url:
        response = redirect(photo_url)
        response.cache_control.public = True
        response.cache_control.max_age = 604800
        return response
    initials = html.escape("".join(part[0] for part in player.name.split()[:2]).upper())
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="420" height="560" viewBox="0 0 420 560"><defs><linearGradient id="g" x2="0" y2="1"><stop stop-color="#335b48"/><stop offset="1" stop-color="#13271f"/></linearGradient></defs><rect width="420" height="560" fill="url(#g)"/><circle cx="210" cy="190" r="82" fill="#9fb4a4" opacity=".38"/><path d="M70 560c8-150 65-226 140-226s132 76 140 226" fill="#9fb4a4" opacity=".38"/><text x="210" y="305" text-anchor="middle" fill="#d6ed80" font-family="Arial,sans-serif" font-size="64" font-weight="700">{initials}</text></svg>'''
    response = Response(svg, mimetype="image/svg+xml")
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    return response


@site.get("/u/<username>/avatar")
def profile_avatar(username):
    user = db.session.scalar(
        select(User).where(User.username == username).options(joinedload(User.profile_image))
    )
    if user is None or user.profile_image is None:
        abort(404)
    image = user.profile_image
    return send_file(
        io.BytesIO(image.image_data), mimetype=image.mime_type,
        etag=f"avatar-{user.id}-{int(image.updated_at.timestamp())}", max_age=86400,
    )


@site.get("/matches")
def matches():
    query = request.args.get("q", "").strip()[:80]
    tour = request.args.get("tour", "")
    surface = request.args.get("surface", "")
    year = request.args.get("year", "")
    level = request.args.get("level", "")
    order = request.args.get("order", "newest")
    statement = select(Match).options(joinedload(Match.winner), joinedload(Match.loser))
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
    if level in ("G", "M", "PM", "P", "A", "I", "F", "O", "D"):
        statement = statement.where(Match.level == level)
    if year.isdigit() and 1968 <= int(year) <= 2026:
        statement = statement.where(func.extract("year", Match.week_start) == int(year))
    statement = statement.order_by(
        Match.week_start.asc() if order == "oldest" else Match.week_start.desc(),
        Match.tournament,
    )
    page = max(1, request.args.get("page", 1, type=int))
    pagination = db.paginate(statement, page=page, per_page=18, error_out=False)
    live_matches = current_match_rows("live")
    upcoming_matches = current_match_rows("upcoming")
    return render_template(
        "matches.html", pagination=pagination, query=query, tour=tour,
        surface=surface, year=year, level=level, order=order, match_location=match_location,
        live_matches=live_matches, upcoming_matches=upcoming_matches,
    )


@site.get("/api/live-matches")
def live_matches_api():
    matches = current_match_rows("live")
    response = jsonify({
        "matches": [{
            "id": match.provider_id, "score": match.score,
            "server": match.server, "synced_at": match.synced_at.isoformat(),
        } for match in matches]
    })
    response.cache_control.no_store = True
    return response


@site.get("/matches/<path:match_id>")
def match_detail(match_id):
    match = db.get_or_404(Match, match_id)
    reviews = db.session.scalars(
        select(Review).where(Review.match_id == match_id, Review.is_public.is_(True))
        .options(joinedload(Review.user), joinedload(Review.comments).joinedload(Comment.user))
        .order_by(Review.created_at.desc())
    ).unique().all()
    own_review = None
    on_watchlist = False
    if current_user.is_authenticated:
        own_review = db.session.scalar(
            select(Review).where(Review.match_id == match_id, Review.user_id == current_user.id)
        )
        on_watchlist = db.session.scalar(
            select(WatchlistItem.id).where(
                WatchlistItem.match_id == match_id, WatchlistItem.user_id == current_user.id
            )
        ) is not None
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
        community=community_statistics(match), serve_stats=serve_stats,
        today=date.today(), on_watchlist=on_watchlist,
    )


@site.post("/matches/<path:match_id>/watchlist")
@login_required
def toggle_watchlist(match_id):
    db.get_or_404(Match, match_id)
    item = db.session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id, WatchlistItem.match_id == match_id
        )
    )
    if item:
        db.session.delete(item)
        flash("Removed from your watchlist.", "success")
    else:
        db.session.add(WatchlistItem(user_id=current_user.id, match_id=match_id))
        flash("Saved to your watchlist.", "success")
    db.session.commit()
    return redirect(url_for("site.match_detail", match_id=match_id))


@site.get("/players")
def players():
    query = request.args.get("q", "").strip()[:80]
    tour = request.args.get("tour", "")
    statement = select(Player)
    if query:
        statement = statement.where(Player.name.ilike(f"%{query}%"))
    if tour in ("ATP", "WTA"):
        statement = statement.where(Player.tour == tour)
    statement = statement.order_by(Player.wikidata_id.is_(None), Player.name)
    pagination = db.paginate(
        statement, page=max(1, request.args.get("page", 1, type=int)),
        per_page=24, error_out=False,
    )
    return render_template("players.html", pagination=pagination, query=query, tour=tour)


@site.get("/tournaments")
def tournaments():
    rows = db.session.execute(
        select(
            Match.tournament, Match.surface, Match.tour,
            func.count(Match.id).label("matches"),
            func.max(Match.week_start).label("latest"),
        ).group_by(Match.tournament, Match.surface, Match.tour)
        .order_by(func.max(Match.week_start).desc(), Match.tournament)
    ).all()
    return render_template("tournaments.html", tournaments=rows)


@site.get("/search")
def search():
    query = request.args.get("q", "").strip()[:80]
    players_found, matches_found, members = [], [], []
    if query:
        players_found = db.session.scalars(
            select(Player).where(Player.name.ilike(f"%{query}%")).order_by(Player.name).limit(8)
        ).all()
        winner, loser = aliased(Player), aliased(Player)
        matches_found = db.session.scalars(
            select(Match).join(winner, Match.winner).join(loser, Match.loser).where(or_(
                Match.tournament.ilike(f"%{query}%"), winner.name.ilike(f"%{query}%"),
                loser.name.ilike(f"%{query}%"),
            )).order_by(Match.week_start.desc()).limit(8)
        ).all()
        members = db.session.scalars(
            select(User).where(or_(User.username.ilike(f"%{query}%"), User.display_name.ilike(f"%{query}%")))
            .order_by(User.username).limit(8)
        ).all()
    return render_template("search.html", query=query, players=players_found, matches=matches_found, members=members)


@site.get("/news")
def news():
    source_keys = {source["key"] for source in NEWS_SOURCES}
    selected_source = request.args.get("source", "all").strip().lower()
    if selected_source not in source_keys:
        selected_source = "all"
    stories = [] if current_app.config["TESTING"] else fetch_news_items(selected_source)
    return render_template(
        "news.html", sources=NEWS_SOURCES, stories=stories, selected_source=selected_source,
    )


@site.get("/notifications")
@login_required
def notifications():
    requests_in = db.session.scalars(
        select(Friendship).where(Friendship.addressee_id == current_user.id, Friendship.status == "pending")
        .options(joinedload(Friendship.requester)).order_by(Friendship.created_at.desc())
    ).all()
    comments = db.session.scalars(
        select(Comment).join(Review).where(Review.user_id == current_user.id, Comment.user_id != current_user.id)
        .options(joinedload(Comment.user), joinedload(Comment.review).joinedload(Review.match))
        .order_by(Comment.created_at.desc()).limit(30)
    ).all()
    return render_template("notifications.html", requests_in=requests_in, comments=comments)


@site.post("/u/<username>/friend")
@login_required
def request_friend(username):
    other = db.session.scalar(select(User).where(User.username == username.lower()))
    if other is None:
        abort(404)
    if other.id == current_user.id:
        abort(400)
    existing = db.session.scalar(select(Friendship).where(or_(
        (Friendship.requester_id == current_user.id) & (Friendship.addressee_id == other.id),
        (Friendship.requester_id == other.id) & (Friendship.addressee_id == current_user.id),
    )))
    if existing is None:
        db.session.add(Friendship(requester_id=current_user.id, addressee_id=other.id))
        db.session.commit()
        flash("Friend request sent.", "success")
    return redirect(url_for("site.profile", username=other.username))


@site.post("/friend-requests/<int:request_id>/<action>")
@login_required
def answer_friend_request(request_id, action):
    item = db.get_or_404(Friendship, request_id)
    if item.addressee_id != current_user.id or item.status != "pending" or action not in {"accept", "decline"}:
        abort(403)
    if action == "accept":
        item.status = "accepted"
        flash("You are now friends.", "success")
    else:
        db.session.delete(item)
    db.session.commit()
    return redirect(url_for("site.notifications"))


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
    return render_template(
        "player.html", player=player, stats=stats, following=following,
        match_location=match_location,
    )


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
    if not current_app.config["REGISTRATION_ENABLED"]:
        abort(503)
    if current_user.is_authenticated:
        return redirect(url_for("site.my_profile"))
    if request.method == "POST":
        limit_action("register-ip", client_ip(), 5, 3600)
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
            user.auth_state = AuthState(
                email_verified_at=None if current_app.config["REQUIRE_EMAIL_VERIFICATION"] else utcnow()
            )
            db.session.add(user)
            db.session.commit()
            if current_app.config["REQUIRE_EMAIL_VERIFICATION"]:
                try:
                    send_account_email(user, "verify")
                    flash("Check your email to verify your account before logging in.", "success")
                except requests.RequestException:
                    current_app.logger.exception("Verification email delivery failed")
                    flash("We could not send your email. Use the resend link shortly.", "error")
                return redirect(url_for("site.check_email"))
            session.clear()
            login_user(user)
            flash("Welcome to Tennisd. Your diary is ready.", "success")
            return redirect(url_for("site.my_profile"))
    return render_template("auth.html", mode="register")


@site.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("site.my_profile"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        limit_action("login-ip", client_ip(), 20, 900)
        limit_action("login-identity", identity[:255], 8, 900)
        user = db.session.scalar(
            select(User).where(or_(User.username == identity, User.email == identity))
        )
        if user and len(password) <= 128 and user.check_password(password):
            if current_app.config["REQUIRE_EMAIL_VERIFICATION"] and (
                user.auth_state is None or user.auth_state.email_verified_at is None
            ):
                flash("Verify your email before logging in.", "error")
                return redirect(url_for("site.check_email"))
            if not user.password_hash.startswith("$argon2id$"):
                user.set_password(password)
                db.session.commit()
            session.clear()
            login_user(user)
            return redirect(safe_next("site.my_profile"))
        flash("Incorrect username, email or password.", "error")
    return render_template("auth.html", mode="login")


@site.get("/check-email")
def check_email():
    return render_template("auth_action.html", mode="check")


@site.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    if not (current_app.config["RESEND_API_KEY"] or current_app.config.get("MAIL_DELIVERY")):
        abort(503)
    if request.method == "POST":
        limit_action("resend-ip", client_ip(), 5, 3600)
        email = request.form.get("email", "").strip().lower()[:255]
        user = db.session.scalar(select(User).where(User.email == email))
        if user and (not user.auth_state or not user.auth_state.email_verified_at):
            try:
                send_account_email(user, "verify")
            except requests.RequestException:
                current_app.logger.exception("Verification email delivery failed")
        flash("If this address needs verification, a new link has been sent.", "success")
        return redirect(url_for("site.check_email"))
    return render_template("auth_action.html", mode="resend")


@site.route("/verify-email/<token>", methods=["GET", "POST"])
def verify_email(token):
    saved = valid_token(token, "verify")
    if saved is None:
        flash("This verification link has expired. Request a new one.", "error")
        return redirect(url_for("site.resend_verification"))
    if request.method == "POST":
        user = saved.user
        if user.auth_state is None:
            user.auth_state = AuthState(session_version=0)
        user.auth_state.email_verified_at = utcnow()
        db.session.delete(saved)
        db.session.commit()
        flash("Email verified. You can log in now.", "success")
        return redirect(url_for("site.login"))
    return render_template("auth_action.html", mode="verify", token=token)


@site.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if not (current_app.config["RESEND_API_KEY"] or current_app.config.get("MAIL_DELIVERY")):
        abort(503)
    if request.method == "POST":
        limit_action("reset-ip", client_ip(), 5, 3600)
        email = request.form.get("email", "").strip().lower()[:255]
        user = db.session.scalar(select(User).where(User.email == email))
        if user:
            try:
                send_account_email(user, "reset")
            except requests.RequestException:
                current_app.logger.exception("Password reset email delivery failed")
        flash("If an account uses this address, a reset link has been sent.", "success")
        return redirect(url_for("site.login"))
    return render_template("auth_action.html", mode="forgot")


@site.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    saved = valid_token(token, "reset")
    if saved is None:
        flash("This reset link has expired. Request a new one.", "error")
        return redirect(url_for("site.forgot_password"))
    if request.method == "POST":
        limit_action("reset-submit-ip", client_ip(), 10, 3600)
        password = request.form.get("password", "")
        if not 10 <= len(password) <= 128:
            flash("Use a password with 10–128 characters.", "error")
        else:
            user = saved.user
            user.set_password(password)
            if user.auth_state is None:
                user.auth_state = AuthState(session_version=0)
            user.auth_state.session_version += 1
            db.session.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
            db.session.commit()
            session.clear()
            flash("Password changed. Log in with your new password.", "success")
            return redirect(url_for("site.login"))
    return render_template("auth_action.html", mode="reset", token=token)


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
    available_tabs = {"profile", "diary", "likes"}
    if own:
        available_tabs.update({"watchlist", "friends"})
    active_tab = request.args.get("tab", "profile").lower()
    if active_tab not in available_tabs:
        active_tab = "profile"
    statement = select(Review).where(Review.user_id == user.id)
    if not own:
        statement = statement.where(Review.is_public.is_(True))
    reviews = db.session.scalars(
        statement.options(joinedload(Review.match).joinedload(Match.winner),
                          joinedload(Review.match).joinedload(Match.loser))
        .order_by(Review.watched_on.desc(), Review.id.desc())
    ).all()
    followed = []
    watchlist = []
    friends = []
    friend_state = None
    if own:
        followed = db.session.scalars(
            select(FollowedPlayer).where(FollowedPlayer.user_id == user.id)
            .options(joinedload(FollowedPlayer.player)).limit(12)
        ).all()
        watchlist = db.session.scalars(
            select(WatchlistItem).where(WatchlistItem.user_id == user.id)
            .options(joinedload(WatchlistItem.match))
            .order_by(WatchlistItem.added_at.desc())
        ).all()
        connections = db.session.scalars(select(Friendship).where(
            or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id),
            Friendship.status == "accepted",
        ).options(joinedload(Friendship.requester), joinedload(Friendship.addressee))).all()
        friends = [item.addressee if item.requester_id == user.id else item.requester for item in connections]
    elif current_user.is_authenticated:
        friend_state = db.session.scalar(select(Friendship.status).where(or_(
            (Friendship.requester_id == current_user.id) & (Friendship.addressee_id == user.id),
            (Friendship.requester_id == user.id) & (Friendship.addressee_id == current_user.id),
        )))
    favorites = [review for review in reviews if review.is_favorite]
    return render_template(
        "profile.html", user=user, reviews=reviews,
        stats=diary_statistics(reviews), own=own, followed=followed, watchlist=watchlist,
        favorites=favorites, active_tab=active_tab, friends=friends, friend_state=friend_state,
    )


@site.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        bio = request.form.get("bio", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        avatar_upload = request.files.get("avatar")
        avatar_data = None
        avatar_error = None
        if avatar_upload and avatar_upload.filename:
            limit_action("profile-image", str(current_user.id), 10, 3600)
            try:
                avatar_data = prepare_profile_image(avatar_upload)
            except ValueError as error:
                avatar_error = str(error)
        if new_password:
            limit_action("password-change", str(current_user.id), 5, 3600)
        if avatar_error:
            flash(avatar_error, "error")
        elif not 1 <= len(display_name) <= 60 or len(bio) > 280:
            flash("Display name or bio is too long.", "error")
        elif new_password and (
            not current_user.check_password(current_password) or not 10 <= len(new_password) <= 128
        ):
            flash("Check your current password; the new one needs 10–128 characters.", "error")
        else:
            current_user.display_name = display_name
            current_user.bio = bio
            if avatar_data is not None:
                if current_user.profile_image is None:
                    current_user.profile_image = ProfileImage(mime_type="image/webp", image_data=avatar_data)
                else:
                    current_user.profile_image.mime_type = "image/webp"
                    current_user.profile_image.image_data = avatar_data
                    current_user.profile_image.updated_at = utcnow()
            elif request.form.get("remove_avatar") == "on":
                current_user.profile_image = None
            if new_password:
                current_user.set_password(new_password)
                if current_user.auth_state is None:
                    current_user.auth_state = AuthState(session_version=0)
                current_user.auth_state.session_version += 1
            db.session.commit()
            if new_password:
                session.clear()
                login_user(current_user)
            flash("Settings saved.", "success")
            return redirect(url_for("site.settings"))
    return render_template("settings.html")


@site.get("/settings/export")
@login_required
def export_diary():
    reviews = db.session.scalars(
        select(Review).where(Review.user_id == current_user.id)
        .options(joinedload(Review.match)).order_by(Review.watched_on)
    ).all()
    follows = db.session.scalars(
        select(FollowedPlayer).where(FollowedPlayer.user_id == current_user.id)
        .options(joinedload(FollowedPlayer.player))
    ).all()
    watchlist = db.session.scalars(
        select(WatchlistItem).where(WatchlistItem.user_id == current_user.id)
    ).all()
    comments = db.session.scalars(
        select(Comment).where(Comment.user_id == current_user.id)
        .options(joinedload(Comment.review))
        .order_by(Comment.created_at)
    ).all()
    payload = {
        "username": current_user.username,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "bio": current_user.bio,
        "has_profile_photo": current_user.profile_image is not None,
        "joined_at": current_user.created_at.isoformat(),
        "diary": [
            {
                "match_id": review.match_id,
                "match": f"{review.match.winner.name} vs {review.match.loser.name}",
                "tournament": review.match.tournament,
                "watched_on": review.watched_on.isoformat(),
                "rating_out_of_five": review.rating_half / 2 if review.rating_half else None,
                "review": review.body,
                "favorite": review.is_favorite,
                "public": review.is_public,
                "spoilers": review.has_spoilers,
            }
            for review in reviews
        ],
        "followed_players": [item.player.name for item in follows],
        "watchlist_match_ids": [item.match_id for item in watchlist],
        "comments": [
            {
                "match_id": comment.review.match_id,
                "review_id": comment.review_id,
                "body": comment.body,
                "created_at": comment.created_at.isoformat(),
            }
            for comment in comments
        ],
    }
    response = jsonify(payload)
    response.headers["Content-Disposition"] = f'attachment; filename="tennisd-{current_user.username}.json"'
    response.cache_control.no_store = True
    return response


@site.post("/settings/delete-account")
@login_required
def delete_account():
    limit_action("account-delete", str(current_user.id), 5, 3600)
    if (
        request.form.get("username", "").strip().lower() != current_user.username
        or not current_user.check_password(request.form.get("password", ""))
    ):
        flash("Username or password was incorrect. Your account was not deleted.", "error")
        return redirect(url_for("site.settings"))
    user = db.session.get(User, current_user.id)
    db.session.execute(delete(Friendship).where(or_(
        Friendship.requester_id == user.id, Friendship.addressee_id == user.id,
    )))
    db.session.execute(delete(Comment).where(Comment.user_id == user.id))
    db.session.execute(delete(FollowedPlayer).where(FollowedPlayer.user_id == user.id))
    db.session.execute(delete(WatchlistItem).where(WatchlistItem.user_id == user.id))
    db.session.delete(user)
    db.session.commit()
    logout_user()
    session.clear()
    flash("Your account and diary have been deleted.", "success")
    return redirect(url_for("site.home"))


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
    watchlist_item = db.session.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id, WatchlistItem.match_id == match_id
        )
    )
    if watchlist_item:
        db.session.delete(watchlist_item)
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
    if comment.user_id != current_user.id and comment.review.user_id != current_user.id:
        abort(403)
    match_id = comment.review.match_id
    review_id = comment.review_id
    db.session.delete(comment)
    db.session.commit()
    return redirect(url_for("site.match_detail", match_id=match_id) + f"#review-{review_id}")


@site.post("/reports")
@login_required
def report_content():
    limit_action("report-user", str(current_user.id), 10, 86400)
    target = request.form.get("target", "")
    reason = request.form.get("reason", "")
    if reason not in {"spam", "harassment", "hate", "other"}:
        abort(400)
    if target == "review":
        review = db.get_or_404(Review, request.form.get("target_id", type=int))
        if not review.is_public:
            abort(404)
        match_id = review.match_id
        condition = (Report.reporter_id == current_user.id, Report.review_id == review.id)
        report = Report(reporter_id=current_user.id, review_id=review.id, reason=reason)
    elif target == "comment":
        comment = db.get_or_404(Comment, request.form.get("target_id", type=int))
        if not comment.review.is_public:
            abort(404)
        match_id = comment.review.match_id
        condition = (Report.reporter_id == current_user.id, Report.comment_id == comment.id)
        report = Report(reporter_id=current_user.id, comment_id=comment.id, reason=reason)
    else:
        abort(400)
    if db.session.scalar(select(Report.id).where(*condition, Report.status == "open")) is None:
        db.session.add(report)
        db.session.commit()
    flash("Thank you. This report is queued for review.", "success")
    return redirect(url_for("site.match_detail", match_id=match_id))


def require_moderator():
    state = current_user.auth_state if current_user.is_authenticated else None
    if (
        not current_user.is_authenticated
        or current_user.email != current_app.config["ADMIN_EMAIL"]
        or not state or not state.email_verified_at
    ):
        abort(403)


@site.get("/moderation")
@login_required
def moderation():
    require_moderator()
    reports = db.session.scalars(
        select(Report).where(Report.status == "open")
        .order_by(Report.created_at.asc()).limit(100)
    ).all()
    return render_template("moderation.html", reports=reports)


@site.post("/moderation/reports/<int:report_id>/<action>")
@login_required
def moderate_report(report_id, action):
    require_moderator()
    report = db.get_or_404(Report, report_id)
    if action == "dismiss":
        report.status = "dismissed"
    elif action == "remove":
        target = report.review or report.comment
        db.session.delete(target)
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("site.moderation"))


@site.get("/about")
def about():
    return render_template("about.html")


@site.get("/privacy")
def privacy():
    return render_template("privacy.html")
