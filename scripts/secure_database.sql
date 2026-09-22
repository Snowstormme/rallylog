-- Run as the database owner after creating a LOGIN role named rallylog_app.
-- The website role can use Rallylog tables but cannot alter or drop the schema.

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO rallylog_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rallylog_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rallylog_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rallylog_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO rallylog_app;
