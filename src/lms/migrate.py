"""Apply db/migrations and the reference seed once, in order.

The files are the ones already in the repository. This runner does not add
an election row. A missing reference row after the seed fails closed.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REQUIRED_ENV = (
    "LMS_DB_HOST",
    "LMS_DB_NAME",
    "LMS_DB_USER",
    "LMS_DB_PASSWORD",
    "LMS_S3_BUCKET",
)

_LOCK = 842016


class MigrateError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def migration_paths(root: Path | None = None) -> list[Path]:
    root = root or repo_root()
    files = sorted((root / "db" / "migrations").glob("*.sql"))
    seed = root / "db" / "seed" / "001_reference.sql"
    if not files or not seed.is_file():
        raise MigrateError("The migration directory or the reference seed is missing.")
    return [*files, seed]


def require_deploy_config() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit(
            "fail closed: missing configuration: " + ", ".join(missing)
        )


def connection_kwargs() -> dict:
    host = os.environ.get("LMS_DB_HOST", "").strip()
    name = os.environ.get("LMS_DB_NAME", "").strip()
    user = os.environ.get("LMS_DB_USER", "").strip()
    password = os.environ.get("LMS_DB_PASSWORD", "")
    if not host or not name or not user or not password:
        raise MigrateError("fail closed: database configuration is missing.")
    port = os.environ.get("LMS_DB_PORT", "5432").strip() or "5432"
    sslmode = os.environ.get("LMS_DB_SSL", "prefer").strip() or "prefer"
    return {
        "host": host,
        "port": port,
        "dbname": name,
        "user": user,
        "password": password,
        "sslmode": sslmode,
    }


def pg_env() -> dict:
    values = connection_kwargs()
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": values["host"],
            "PGPORT": values["port"],
            "PGDATABASE": values["dbname"],
            "PGUSER": values["user"],
            "PGPASSWORD": values["password"],
            "PGSSLMODE": values["sslmode"],
        }
    )
    return env


def apply_migrations(root: Path | None = None) -> list[str]:
    """Apply each pending file in its own transaction. Return the names applied."""

    import psycopg

    wait_for_database()
    paths = migration_paths(root)
    kwargs = connection_kwargs()
    applied: list[str] = []
    with psycopg.connect(**_connect_kwargs(kwargs), connect_timeout=10) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK,))
        conn.commit()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.lms_schema_migration (
                  filename text PRIMARY KEY,
                  applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            conn.commit()
            done = {
                row[0]
                for row in conn.execute("SELECT filename FROM public.lms_schema_migration")
            }
            pending = [path for path in paths if path.name not in done]
            for path in pending:
                _apply_file(path)
                applied.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK,))
            conn.commit()
    return applied


def wait_for_database() -> None:
    import psycopg

    kwargs = _connect_kwargs(connection_kwargs())
    last: Exception | None = None
    attempts = int(os.environ.get("LMS_DB_WAIT_ATTEMPTS", "36"))
    for _ in range(attempts):
        try:
            with psycopg.connect(**kwargs, connect_timeout=5) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:
            last = exc
            time.sleep(5)
    raise MigrateError(f"fail closed: database is not reachable. {last}")


def _connect_kwargs(values: dict) -> dict:
    port = values["port"]
    return {**values, "port": int(port)}


def reference_data_present() -> None:
    """Fail closed when the statutory reference seed did not land."""

    import psycopg

    with psycopg.connect(**_connect_kwargs(connection_kwargs()), connect_timeout=10) as conn:
        row = conn.execute("SELECT count(*) FROM lms.ref_credit_classification").fetchone()
    if row is None or int(row[0]) < 1:
        raise SystemExit(
            "fail closed: lms.ref_credit_classification has no rows. The reference seed is missing."
        )


def _apply_file(path: Path) -> None:
    # The filename comes from the repository listing, not from a request.
    script = "\n".join(
        [
            "\\set ON_ERROR_STOP on",
            "BEGIN;",
            f"\\ir {path}",
            "INSERT INTO public.lms_schema_migration (filename) VALUES ("
            f"'{path.name}');",
            "COMMIT;",
            "",
        ]
    )
    completed = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=script,
        text=True,
        env=pg_env(),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise MigrateError(f"{path.name} failed.\n{detail}")


def main() -> None:
    if os.environ.get("LMS_REQUIRE_DEPLOY_CONFIG") == "1":
        require_deploy_config()
    apply_migrations()
    reference_data_present()
    print("migrations applied", flush=True)


if __name__ == "__main__":
    main()
