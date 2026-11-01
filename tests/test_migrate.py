"""Migration listing and the deploy configuration check. No database."""

from __future__ import annotations

import pytest

from lms.migrate import migration_paths, require_deploy_config


def test_migrations_run_before_the_reference_seed() -> None:
    paths = migration_paths()
    names = [path.name for path in paths]
    assert names[0] == "0001_lms_owned.sql"
    assert names[-1] == "001_reference.sql"
    assert names[-2] == "0011_in_duplum_ceiling.sql"
    assert names == sorted(names[:-1]) + [names[-1]]


def test_a_missing_bucket_or_database_setting_fails_closed(monkeypatch) -> None:
    for name in (
        "LMS_DB_HOST",
        "LMS_DB_NAME",
        "LMS_DB_USER",
        "LMS_DB_PASSWORD",
        "LMS_S3_BUCKET",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LMS_DB_HOST", "db.example")
    monkeypatch.setenv("LMS_DB_NAME", "lms")
    monkeypatch.setenv("LMS_DB_USER", "lms_admin")
    monkeypatch.setenv("LMS_DB_PASSWORD", "secret")
    with pytest.raises(SystemExit) as raised:
        require_deploy_config()
    assert "LMS_S3_BUCKET" in str(raised.value)
