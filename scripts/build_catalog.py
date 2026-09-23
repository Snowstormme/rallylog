"""Export only attributed tennis records, never user accounts, for offline seeding."""

import gzip
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from tennisd import create_app, db
from tennisd.models import Match, Player


OUTPUT = Path(__file__).resolve().parent.parent / "data" / "catalog_2023_2026.json.gz"
PLAYER_COLUMNS = (
    "id", "tour", "name", "country", "hand", "height_cm", "born_on", "wikidata_id",
)
MATCH_COLUMNS = tuple(column.name for column in Match.__table__.columns)


def serializable(record, columns):
    result = {name: getattr(record, name) for name in columns}
    for name, value in result.items():
        if isinstance(value, (date, datetime)):
            result[name] = value.isoformat()
    return result


def main():
    app = create_app()
    with app.app_context():
        players = db.session.scalars(select(Player).order_by(Player.id)).all()
        matches = db.session.scalars(select(Match).order_by(Match.id)).all()
        if len(matches) < 1000:
            raise RuntimeError("Import the historical catalog before building the bundle.")
        catalog = {
            "players": [serializable(player, PLAYER_COLUMNS) for player in players],
            "matches": [serializable(match, MATCH_COLUMNS) for match in matches],
        }
    with gzip.open(OUTPUT, "wt", encoding="utf-8", compresslevel=9) as target:
        json.dump(catalog, target, separators=(",", ":"), ensure_ascii=False)
    print(f"Wrote {len(matches)} matches and {len(players)} players to {OUTPUT}")


if __name__ == "__main__":
    main()
