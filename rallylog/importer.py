"""Import match records from the non-commercial Sackmann dataset archive."""

import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path

import requests
from sqlalchemy import select

from . import db
from .models import Match, Player

ARCHIVE = "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main"
SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_matches.json"
SAMPLE_PLAYERS_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_players.json"


def number(value):
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def date(value):
    try:
        return datetime.strptime(value, "%Y%m%d").date() if value else None
    except ValueError:
        return None


def csv_from_url(url):
    response = requests.get(url, timeout=30, headers={"User-Agent": "Rallylog/0.1 (tennis diary)"})
    response.raise_for_status()
    return list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))


def player_from_row(tour, source_id, name, row, bio=None, cache=None):
    player_id = f"{tour.lower()}-{source_id}"
    player = cache.get(player_id) if cache is not None else None
    if player is None:
        player = db.session.get(Player, player_id)
    if player is None:
        player = Player(id=player_id, tour=tour, name=name)
        db.session.add(player)
    if cache is not None:
        cache[player_id] = player
    if name and not player.name:
        player.name = name
    player.country = player.country or row.get("ioc")
    player.hand = player.hand or row.get("hand")
    player.height_cm = player.height_cm or number(row.get("ht"))
    if bio:
        player.born_on = player.born_on or date(bio.get("dob"))
        player.wikidata_id = player.wikidata_id or bio.get("wikidata_id") or None
        player.height_cm = player.height_cm or number(bio.get("height"))
        player.hand = player.hand or bio.get("hand")
        player.country = player.country or bio.get("ioc")
    return player


def import_rows(tour, rows, bios=None):
    existing = set(db.session.scalars(select(Match.id)).all())
    added = 0
    bios = bios or {}
    players = {}
    for row in rows:
        winner_source_id = row.get("winner_id")
        loser_source_id = row.get("loser_id")
        week_start = date(row.get("tourney_date"))
        match_id = f"{tour.lower()}-{row.get('tourney_id')}-{row.get('match_num')}"
        if (
            not winner_source_id or not loser_source_id or not week_start
            or not row.get("match_num") or match_id in existing
            or row.get("score", "").strip().upper() in ("W/O", "WALKOVER", "DEF")
        ):
            continue

        winner = player_from_row(
            tour, winner_source_id, row.get("winner_name", ""),
            {"ioc": row.get("winner_ioc"), "hand": row.get("winner_hand"), "ht": row.get("winner_ht")},
            bios.get(winner_source_id),
            players,
        )
        loser = player_from_row(
            tour, loser_source_id, row.get("loser_name", ""),
            {"ioc": row.get("loser_ioc"), "hand": row.get("loser_hand"), "ht": row.get("loser_ht")},
            bios.get(loser_source_id),
            players,
        )
        match = Match(
            id=match_id,
            tour=tour,
            tournament="US Open" if row.get("tourney_name") == "Us Open" else row.get("tourney_name", "Unknown"),
            level=row.get("tourney_level") or "?",
            surface=row.get("surface") or "Unknown",
            week_start=week_start,
            round=row.get("round") or "?",
            winner=winner,
            loser=loser,
            score=row.get("score") or "Score unavailable",
            best_of=number(row.get("best_of")),
            minutes=number(row.get("minutes")),
            winner_rank=number(row.get("winner_rank")),
            loser_rank=number(row.get("loser_rank")),
            w_ace=number(row.get("w_ace")),
            l_ace=number(row.get("l_ace")),
            w_df=number(row.get("w_df")),
            l_df=number(row.get("l_df")),
            w_svpt=number(row.get("w_svpt")),
            l_svpt=number(row.get("l_svpt")),
            w_first_in=number(row.get("w_1stIn")),
            l_first_in=number(row.get("l_1stIn")),
            w_first_won=number(row.get("w_1stWon")),
            l_first_won=number(row.get("l_1stWon")),
            w_bp_saved=number(row.get("w_bpSaved")),
            l_bp_saved=number(row.get("l_bpSaved")),
            w_bp_faced=number(row.get("w_bpFaced")),
            l_bp_faced=number(row.get("l_bpFaced")),
        )
        db.session.add(match)
        existing.add(match_id)
        added += 1
    db.session.commit()
    return added


def seed_samples():
    if db.session.scalar(select(Match.id).limit(1)) is not None or not SAMPLE_FILE.exists():
        return
    samples = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    bios = json.loads(SAMPLE_PLAYERS_FILE.read_text(encoding="utf-8"))
    for tour in ("ATP", "WTA"):
        import_rows(tour, [row for row in samples if row["tour"] == tour], bios[tour])


def import_archive(from_year, to_year):
    total = 0
    for tour in ("ATP", "WTA"):
        slug = tour.lower()
        players = csv_from_url(f"{ARCHIVE}/{slug}/{slug}_players.csv")
        bios = {player["player_id"]: player for player in players}
        for year in range(from_year, to_year + 1):
            try:
                rows = csv_from_url(f"{ARCHIVE}/{slug}/{slug}_matches_{year}.csv")
            except requests.HTTPError as error:
                if error.response.status_code == 404:
                    continue
                raise
            total += import_rows(tour, rows, bios)
    return total
