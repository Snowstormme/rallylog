-- Run as the database owner after creating a plain LOGIN role named rallylog_web.
-- The website role can use Rallylog tables but cannot alter or drop the schema.

ALTER ROLE rallylog_web NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM rallylog_web;
GRANT USAGE ON SCHEMA public TO rallylog_web;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM rallylog_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rallylog_web;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM rallylog_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rallylog_web;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rallylog_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO rallylog_web;
