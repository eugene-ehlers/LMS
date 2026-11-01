"""Brand row for screen headers and footers.

The screen reads ``lms.cfg_brand``. The logo key and the statement footer
come from that row. Display name, telephone, and email are not the header
or the footer.

No row for the organisation: the header and the footer stay empty.
One row: that row's logo key and statement footer.
More than one brand code: nothing is chosen.
A read that does not succeed is not treated as a missing row.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import unquote, urlparse
from uuid import UUID


class BrandReadError(Exception):
    """``lms.cfg_brand`` was not read. This is not an empty result."""


@dataclass(frozen=True, slots=True)
class BrandChrome:
    """The logo and footer a screen may paint.

    ``status`` is ``none`` (no row), ``one`` (that row), ``many`` (more
    than one brand code; nothing is chosen), or ``unread`` (the table
    was not read).
    """

    status: str
    logo_object_key: str | None = None
    statement_footer: str | None = None


class BrandDirectory:
    """Reads ``lms.cfg_brand`` for one organisation.

    ``organisation_id`` on that table is a uuid. An organisation id that
    is not a uuid cannot be a row, so the chrome stays empty and the
    table is not queried. The session variable ``lms.organisation_id``
    is set before the select because row-level security uses it. The
    select also filters on ``organisation_id``.
    """

    def __init__(self, database_url: str | None = None) -> None:
        if database_url is None:
            database_url = os.environ.get("LMS_DATABASE_URL", "")
        self.database_url = database_url

    def presentation(self, organisation_id: str) -> BrandChrome:
        organisation_uuid = _organisation_uuid(organisation_id)
        if organisation_uuid is None:
            return BrandChrome("none")
        if not self.database_url.strip():
            raise BrandReadError("lms.cfg_brand was not read.")
        rows = self._rows(organisation_uuid)
        if len(rows) == 0:
            return BrandChrome("none")
        if len(rows) > 1:
            return BrandChrome("many")
        row = rows[0]
        logo = row.get("logo_object_key")
        logo_text = logo.strip() if isinstance(logo, str) else ""
        footer = row.get("statement_footer")
        footer_text = footer if isinstance(footer, str) else None
        return BrandChrome("one", logo_text or None, footer_text)

    def _rows(self, organisation_uuid: str) -> list[dict]:
        command, password = _psql(self.database_url, organisation_uuid)
        script = """
SELECT set_config('lms.organisation_id', :'org', false)
\\g /dev/null
SELECT COALESCE(json_agg(json_build_object(
  'brand_code', brand_code,
  'logo_object_key', logo_object_key,
  'statement_footer', statement_footer
) ORDER BY brand_code), '[]'::json)
FROM lms.cfg_brand
WHERE organisation_id = :'org'::uuid;
"""
        try:
            completed = subprocess.run(
                command,
                input=script,
                capture_output=True,
                text=True,
                env={**os.environ, "PGPASSWORD": password},
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BrandReadError("lms.cfg_brand was not read.") from exc
        if completed.returncode != 0:
            raise BrandReadError("lms.cfg_brand was not read.")
        try:
            parsed = json.loads(completed.stdout.strip() or "null")
        except json.JSONDecodeError as exc:
            raise BrandReadError("lms.cfg_brand was not read.") from exc
        if not isinstance(parsed, list):
            raise BrandReadError("lms.cfg_brand was not read.")
        return [row for row in parsed if isinstance(row, dict)]


def _organisation_uuid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _psql(database_url: str, organisation_uuid: str) -> tuple[list[str], str]:
    binary = shutil.which("psql")
    if binary is None:
        raise BrandReadError("lms.cfg_brand was not read.")
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise BrandReadError("lms.cfg_brand was not read.")
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    host = parsed.hostname or ""
    port = str(parsed.port or 5432)
    database = parsed.path.lstrip("/")
    if not user or not host or not database:
        raise BrandReadError("lms.cfg_brand was not read.")
    command = [
        binary,
        "-q",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-A",
        "-t",
        "-v",
        f"org={organisation_uuid}",
    ]
    return command, password
