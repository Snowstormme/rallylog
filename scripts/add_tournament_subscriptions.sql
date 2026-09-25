-- Run once as the Neon database owner for an existing Tennisd deployment.
CREATE TABLE IF NOT EXISTS tournament_subscription (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    tour VARCHAR(3) NOT NULL CHECK (tour IN ('ATP', 'WTA')),
    tournament VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_tournament_subscription UNIQUE (user_id, tour, tournament)
);

CREATE INDEX IF NOT EXISTS ix_tournament_subscription_user_id
    ON tournament_subscription (user_id);
CREATE INDEX IF NOT EXISTS ix_tournament_subscription_tour
    ON tournament_subscription (tour);
CREATE INDEX IF NOT EXISTS ix_tournament_subscription_tournament
    ON tournament_subscription (tournament);

REVOKE ALL PRIVILEGES ON TABLE tournament_subscription FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tournament_subscription TO rallylog_web;
GRANT USAGE, SELECT ON SEQUENCE tournament_subscription_id_seq TO rallylog_web;
