-- Run once as the Neon database owner for an existing Tennisd deployment.
CREATE TABLE IF NOT EXISTS profile_image (
    user_id INTEGER PRIMARY KEY REFERENCES "user"(id) ON DELETE CASCADE,
    mime_type VARCHAR(32) NOT NULL,
    image_data BYTEA NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

REVOKE ALL PRIVILEGES ON TABLE profile_image FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE profile_image TO rallylog_web;
