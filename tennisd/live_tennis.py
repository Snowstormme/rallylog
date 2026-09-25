"""Import the free current top-tier slate from Live Tennis API."""

import os
from datetime import datetime, timedelta, timezone

import requests

from . import db
from .models import LiveMatch


API_ROOT = "https://api.livetennisapi.com/api/public/v1"
GRAND_SLAMS = {
    "australian open": "Australian Open",
    "french open": "Roland Garros",
    "roland garros": "Roland Garros",
    "wimbledon": "Wimbledon",
    "us open": "US Open",
    "u.s. open": "US Open",
}
FEATURED_TIERS = (
    "grand_slam",
    "atp_1000",
    "atp_500",
    "wta_1000",
    "wta_500",
)


def parse_instant(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def slam_name(raw_name):
    lowered = (raw_name or "").lower()
    for marker, canonical in GRAND_SLAMS.items():
        if marker in lowered:
            return canonical
    return None


def display_score(score):
    if not isinstance(score, dict):
        return ""
    games = score.get("games")
    if not isinstance(games, list) or len(games) != 2:
        return ""
    first, second = games
    if not isinstance(first, list) or not isinstance(second, list):
        return ""
    sets = []
    for left, right in zip(first, second):
        if isinstance(left, int) and isinstance(right, int):
            sets.append(f"{left}–{right}")
    points = score.get("points")
    if isinstance(points, list) and len(points) == 2 and any(str(point) not in ("0", "") for point in points):
        sets.append(f"({points[0]}–{points[1]})")
    return " ".join(sets)


def normalize_match(item, now=None):
    now = now or datetime.now(timezone.utc)
    tier = str(item.get("tier") or "").lower()
    tournament = slam_name(item.get("tournament")) or str(item.get("tournament") or "").strip()
    tour = str(item.get("tour") or "").upper()
    if not tournament or len(tournament) > 160 or tier not in FEATURED_TIERS or tour not in ("ATP", "WTA"):
        return None
    if (tier.startswith("atp_") and tour != "ATP") or (tier.startswith("wta_") and tour != "WTA"):
        return None
    if item.get("draw") != "singles" or item.get("is_doubles") is True:
        return None
    status = item.get("status")
    if status not in ("live", "upcoming"):
        return None
    starts_at = parse_instant(item.get("scheduled_time"))
    if status == "upcoming" and (not starts_at or starts_at < now - timedelta(hours=6) or starts_at > now + timedelta(days=7)):
        return None
    players = item.get("players") or {}
    p1, p2 = players.get("p1") or {}, players.get("p2") or {}
    if not p1.get("name") or not p2.get("name"):
        return None
    surface = str(item.get("surface") or "hard").title()
    return {
        "provider_id": str(item["id"]),
        "status": status,
        "tour": tour,
        "tournament": tournament,
        "tournament_id": str(item.get("tournament_id") or "") or None,
        "surface": surface if surface in ("Hard", "Clay", "Grass") else "Hard",
        "round": item.get("round_code") or item.get("round") or None,
        "starts_at": starts_at,
        "player1_name": p1["name"],
        "player2_name": p2["name"],
        "player1_provider_id": str(p1.get("id") or "") or None,
        "player2_provider_id": str(p2.get("id") or "") or None,
        "score": display_score(item.get("score")),
        "server": (item.get("score") or {}).get("server"),
        "provider_updated_at": parse_instant((item.get("score") or {}).get("timestamp")),
        "synced_at": now,
    }


def fetch_matches(status, session=requests):
    key = os.environ.get("LIVETENNISAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("LIVETENNISAPI_KEY is not configured.")
    matches = []
    offset = 0
    while offset < 1000:
        response = session.get(
            f"{API_ROOT}/matches",
            params={
                "status": status,
                "tier": ",".join(FEATURED_TIERS),
                "draw": "singles",
                "limit": 100,
                "offset": offset,
            },
            headers={"X-API-Key": key, "User-Agent": "Tennisd/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        page = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(page, list):
            break
        matches.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    return matches


def sync_matches(status, session=requests, now=None):
    if status not in ("live", "upcoming"):
        raise ValueError("status must be live or upcoming")
    now = now or datetime.now(timezone.utc)
    rows = [normalize_match(item, now) for item in fetch_matches(status, session)]
    rows = [row for row in rows if row]
    current_ids = {row["provider_id"] for row in rows}
    for row in rows:
        match = db.session.get(LiveMatch, row["provider_id"])
        if match is None:
            match = LiveMatch(provider_id=row["provider_id"])
            db.session.add(match)
        for field, value in row.items():
            setattr(match, field, value)
    stale = LiveMatch.query.filter_by(status=status).all()
    for match in stale:
        if match.provider_id not in current_ids:
            db.session.delete(match)
    if status == "upcoming":
        LiveMatch.query.filter(LiveMatch.starts_at > now + timedelta(days=7)).delete(synchronize_session=False)
    db.session.commit()
    return len(rows)
