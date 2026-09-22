"""Restrict the production web role and verify that it is not privileged."""

import os

import psycopg
from psycopg import sql


ROLE = "rallylog_app"


def main():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL owner connection.")

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            database = cursor.fetchone()[0]
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
            if cursor.fetchone() is None:
                raise RuntimeError(f"Create the {ROLE} role in Neon before hardening it.")

            cursor.execute(sql.SQL("REVOKE neon_superuser FROM {}").format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL(
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            ).format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            ))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            ))
            cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(
                sql.Identifier(ROLE)
            ))
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(ROLE)
            ))
            cursor.execute(sql.SQL(
                "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {}"
            ).format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL(
                "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {}"
            ).format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
            ).format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(sql.Identifier(ROLE)))
            cursor.execute(sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(sql.Identifier(ROLE)))

            cursor.execute(
                """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication,
                       pg_has_role(%s, 'neon_superuser', 'member'),
                       has_schema_privilege(%s, 'public', 'CREATE')
                FROM pg_roles WHERE rolname = %s
                """,
                (ROLE, ROLE, ROLE),
            )
            unsafe = cursor.fetchone()
            if unsafe is None or any(unsafe):
                raise RuntimeError(f"{ROLE} still has elevated database privileges: {unsafe}")

    print(f"Database role {ROLE} is restricted and verified.")


if __name__ == "__main__":
    main()
