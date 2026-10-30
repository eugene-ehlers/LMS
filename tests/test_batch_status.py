"""Daily calculation batch status."""

from __future__ import annotations

import http.client
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lms.batch.api import build_app, serve
from lms.batch.calculation import AccountStepError
from lms.batch.errors import (
    BatchConflict,
    BatchDidNotComplete,
    BatchNotFound,
    BatchStartNotRecorded,
    CalculationNotConfigured,
    InvalidBatchRequest,
)
from lms.batch.service import BatchService
from lms.batch.store import BatchStore
from lms.batch.timekeeping import parse_recognition_date

STATUS_KEYS = {
    "organisation_id",
    "timezone",
    "recognition_boundary",
    "later_recognition_date_blocked",
    "block_reason",
    "open_recognition_date",
    "last_status",
    "last_successful_run",
    "last_failed_run",
    "open_alerts",
}

RUN_KEYS = {
    "id",
    "organisation_id",
    "recognition_date",
    "recognition_at",
    "started_at",
    "finished_at",
    "accounts_processed",
    "accounts_failed",
    "accounts_at_ceiling",
    "status",
    "outcome",
    "actor_id",
    "batch_failure_reason",
    "failures",
    "alert",
    "skipped_at",
    "skipped_by",
    "skip_reason",
    "superseded_by_run_id",
}


class AdvancingClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        value = self.current
        self.current = self.current + timedelta(seconds=1)
        return value


class ScriptedCalculation:
    def __init__(self, failures: dict[str, tuple[str, str]] | None = None) -> None:
        self.failures = failures or {}
        self.calls: list[tuple[str, str, datetime]] = []

    def accrue(self, *, organisation_id: str, account_id: str, recognition_at: datetime) -> None:
        self._call("accrue", organisation_id, account_id, recognition_at)

    def capitalise(
        self, *, organisation_id: str, account_id: str, recognition_at: datetime
    ) -> None:
        self._call("capitalise", organisation_id, account_id, recognition_at)

    def default_check(
        self, *, organisation_id: str, account_id: str, recognition_at: datetime
    ) -> None:
        self._call("default_check", organisation_id, account_id, recognition_at)

    def _call(
        self, step: str, organisation_id: str, account_id: str, recognition_at: datetime
    ) -> None:
        self.calls.append((step, account_id, recognition_at))
        spec = self.failures.get(account_id)
        if spec and spec[0] == step:
            if spec[1] == "":
                raise AccountStepError(step, "")
            raise AccountStepError(step, spec[1])


def assert_jhb(value: str) -> None:
    assert value.endswith("+02:00")
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(hours=2)


def service_for(
    path: Path,
    calculation: object | None,
    clock: object | None = None,
    faults: set[str] | None = None,
) -> tuple[BatchStore, BatchService]:
    store = BatchStore(str(path), faults=faults)
    clock = clock or AdvancingClock(datetime(2026, 10, 27, 22, 15, 1, tzinfo=timezone.utc))
    return store, BatchService(store, calculation, clock)


def run(
    service: BatchService,
    *,
    organisation_id: str = "org-1",
    actor_id: str = "person-1",
    recognition_date: str = "2026-10-28",
    account_ids: list[str] | None = None,
):
    return service.run_batch(
        organisation_id=organisation_id,
        actor_id=actor_id,
        recognition_date=recognition_date,
        account_ids=["acc-1"] if account_ids is None else account_ids,
    )


def test_recognition_date_is_midnight_johannesburg_in_summer_and_winter() -> None:
    for day in ("2026-01-15", "2026-06-15", "2026-10-28"):
        calendar, instant = parse_recognition_date(day)
        assert calendar == day
        assert instant == f"{day}T00:00:00.000000+02:00"
    calendar, instant = parse_recognition_date("2026-10-27T22:00:00+00:00")
    assert calendar == "2026-10-28"
    assert instant == "2026-10-28T00:00:00.000000+02:00"
    with pytest.raises(ValueError, match="00:00 Africa/Johannesburg"):
        parse_recognition_date("2026-10-28T00:00:00Z")
    with pytest.raises(ValueError, match="00:00 Africa/Johannesburg"):
        parse_recognition_date("2026-10-28T08:00:00+02:00")
    with pytest.raises(ValueError, match="00:00 Africa/Johannesburg"):
        parse_recognition_date("2026-02-31")


def test_successful_batch_records_johannesburg_times_counts_and_audit(tmp_path: Path) -> None:
    calculation = ScriptedCalculation()
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        finished = run(service, account_ids=["acc-1", "acc-2"])
        assert finished.status == "completed"
        assert finished.outcome == "success"
        assert finished.recognition_date == "2026-10-28"
        assert finished.recognition_at == "2026-10-28T00:00:00.000000+02:00"
        assert finished.started_at == "2026-10-28T00:15:01.000000+02:00"
        assert finished.finished_at == "2026-10-28T00:15:02.000000+02:00"
        assert finished.accounts_processed == 2
        assert finished.accounts_failed == 0
        assert finished.accounts_at_ceiling == 0
        assert finished.failures == ()
        assert finished.actor_id == "person-1"
        assert finished.alert is None
        assert_jhb(finished.started_at)
        assert_jhb(finished.finished_at or "")
        assert [call[:2] for call in calculation.calls] == [
            ("accrue", "acc-1"),
            ("capitalise", "acc-1"),
            ("default_check", "acc-1"),
            ("accrue", "acc-2"),
            ("capitalise", "acc-2"),
            ("default_check", "acc-2"),
        ]
        for _step, _account, seen in calculation.calls:
            assert seen.hour == 0 and seen.minute == 0 and seen.second == 0
            assert seen.utcoffset() == timedelta(hours=2)
        audit = service.audit_entries("org-1")
        assert [entry.outcome for entry in audit] == ["started", "success"]
        assert {entry.actor_id for entry in audit} == {"person-1"}
        assert {entry.action for entry in audit} == {"daily_calculation_batch"}
        assert all(entry.recorded_at.endswith("+02:00") for entry in audit)
        status = service.status("org-1")
        assert set(status.to_dict()) == STATUS_KEYS
        assert set(status.last_status.to_dict()) == RUN_KEYS  # type: ignore[union-attr]
        assert status.last_successful_run is not None
        assert status.last_successful_run.id == finished.id
        assert status.last_failed_run is None
        assert status.later_recognition_date_blocked is False
        assert status.open_alerts == ()
    finally:
        store.close()


def test_account_failure_is_recorded_and_does_not_stop_the_other_accounts(
    tmp_path: Path,
) -> None:
    calculation = ScriptedCalculation(
        {
            "acc-2": ("accrue", "missing day-count election"),
            "acc-3": ("capitalise", "capitalise: service fee cap missing"),
        }
    )
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        finished = run(service, account_ids=["acc-1", "acc-2", "acc-3", "acc-4"])
        assert finished.outcome == "failed"
        assert finished.status == "completed"
        assert finished.finished_at is not None
        assert finished.accounts_processed == 4
        assert finished.accounts_failed == 2
        assert [(item.account_id, item.step, item.reason) for item in finished.failures] == [
            ("acc-2", "accrue", "accrue: missing day-count election"),
            ("acc-3", "capitalise", "capitalise: service fee cap missing"),
        ]
        assert [call[:2] for call in calculation.calls] == [
            ("accrue", "acc-1"),
            ("capitalise", "acc-1"),
            ("default_check", "acc-1"),
            ("accrue", "acc-2"),
            ("accrue", "acc-3"),
            ("capitalise", "acc-3"),
            ("accrue", "acc-4"),
            ("capitalise", "acc-4"),
            ("default_check", "acc-4"),
        ]
        assert finished.alert is None
        status = service.status("org-1")
        assert status.last_failed_run is not None
        assert status.last_failed_run.id == finished.id
        assert status.last_successful_run is None
        assert status.later_recognition_date_blocked is False
        assert status.open_alerts == ()
        outcomes = [entry.outcome for entry in service.audit_entries("org-1")]
        assert outcomes == ["started", "failed"]
        assert "acc-2: accrue: missing day-count election" in service.audit_entries("org-1")[1].detail
        later = run(service, recognition_date="2026-10-30", account_ids=[])
        assert later.outcome == "success"
        status = service.status("org-1")
        assert status.last_successful_run is not None
        assert status.last_successful_run.id == later.id
        assert status.last_failed_run is not None
        assert status.last_failed_run.id == finished.id
        assert status.later_recognition_date_blocked is False
    finally:
        store.close()


def test_empty_reason_names_the_step(tmp_path: Path) -> None:
    calculation = ScriptedCalculation({"acc-1": ("default_check", "")})
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        finished = run(service)
        assert finished.failures[0].reason == "default_check: failed without a reason"
        assert [call[0] for call in calculation.calls] == [
            "accrue",
            "capitalise",
            "default_check",
        ]
    finally:
        store.close()


def test_start_is_not_recorded_when_the_store_cannot_write(tmp_path: Path) -> None:
    calculation = ScriptedCalculation()
    store, service = service_for(
        tmp_path / "batch.sqlite", calculation, faults={"fail_start"}
    )
    try:
        with pytest.raises(BatchStartNotRecorded, match="batch start could not be recorded"):
            run(service)
        assert calculation.calls == []
        assert service.status("org-1").last_status is None
        assert service.audit_entries("org-1") == ()
    finally:
        store.close()


def test_naive_clock_does_not_start_the_batch(tmp_path: Path) -> None:
    class NaiveClock:
        def now(self) -> datetime:
            return datetime(2026, 10, 28, 8, 0, 0)

    calculation = ScriptedCalculation()
    store, service = service_for(tmp_path / "batch.sqlite", calculation, clock=NaiveClock())
    try:
        with pytest.raises(BatchStartNotRecorded, match="naive timestamp"):
            run(service)
        assert calculation.calls == []
        assert service.status("org-1").last_status is None
    finally:
        store.close()


def test_unconfigured_steps_refuse_before_start(tmp_path: Path) -> None:
    store, service = service_for(tmp_path / "batch.sqlite", None)
    try:
        with pytest.raises(CalculationNotConfigured, match="not configured"):
            run(service)
        assert service.status("org-1").last_status is None
        audit = service.audit_entries("org-1")
        assert len(audit) == 1
        assert audit[0].outcome == "start_refused"
        assert audit[0].actor_id == "person-1"
        assert "not configured" in audit[0].detail
    finally:
        store.close()


def test_missing_actor_is_refused_without_an_audit_row(tmp_path: Path) -> None:
    calculation = ScriptedCalculation()
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        with pytest.raises(InvalidBatchRequest, match="actor_id is required"):
            run(service, actor_id=" ")
        assert calculation.calls == []
        assert service.audit_entries("org-1") == ()
    finally:
        store.close()


def test_duplicate_account_is_refused_before_start(tmp_path: Path) -> None:
    calculation = ScriptedCalculation()
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        with pytest.raises(InvalidBatchRequest, match="duplicate account identifier acc-1"):
            run(service, account_ids=["acc-1", "acc-1"])
        assert calculation.calls == []
        assert service.status("org-1").last_status is None
        assert service.audit_entries("org-1")[0].outcome == "start_refused"
    finally:
        store.close()


def test_incomplete_batch_alerts_and_blocks_the_next_day_until_retry_or_skip(
    tmp_path: Path,
) -> None:
    calculation = ScriptedCalculation()
    path = tmp_path / "batch.sqlite"
    store, service = service_for(path, calculation, faults={"fail_progress"})
    try:
        with pytest.raises(BatchDidNotComplete, match="could not record batch progress") as caught:
            run(service, account_ids=["acc-1", "acc-2"])
        failed = caught.value.run
        assert failed is not None
        assert failed.status == "incomplete"
        assert failed.finished_at is None
        assert failed.accounts_processed == 0
        assert failed.alert is not None
        assert failed.alert.resolution is None
        assert "acc-1" in failed.batch_failure_reason  # type: ignore[operator]
        assert [call[:2] for call in calculation.calls] == [
            ("accrue", "acc-1"),
            ("capitalise", "acc-1"),
            ("default_check", "acc-1"),
        ]
        status = service.status("org-1")
        assert status.later_recognition_date_blocked is True
        assert status.open_recognition_date == "2026-10-28"
        assert status.block_reason == failed.batch_failure_reason
        assert status.last_failed_run is not None
        assert status.last_failed_run.id == failed.id
        assert status.last_successful_run is None
        assert len(status.open_alerts) == 1
        assert status.open_alerts[0].batch_run_id == failed.id
        with pytest.raises(BatchConflict, match="did not complete|could not record"):
            run(service, recognition_date="2026-10-29", account_ids=[])
        assert len(calculation.calls) == 3
    finally:
        store.close()

    retry_calc = ScriptedCalculation()
    store, service = service_for(path, retry_calc)
    try:
        retried = run(service, account_ids=["acc-1"])
        assert retried.outcome == "success"
        assert retried.superseded_by_run_id is None
        status = service.status("org-1")
        assert status.later_recognition_date_blocked is False
        assert status.open_alerts == ()
        assert status.last_successful_run is not None
        assert status.last_successful_run.id == retried.id
        previous = store.get_run(failed.id)  # type: ignore[name-defined]
        assert previous is not None
        assert previous.status == "incomplete"
        assert previous.superseded_by_run_id == retried.id
        assert previous.alert is not None
        assert previous.alert.resolution == "resolved"
        assert previous.alert.resolved_by == "person-1"
        assert [call[0] for call in retry_calc.calls] == [
            "accrue",
            "capitalise",
            "default_check",
        ]
    finally:
        store.close()


def test_explicit_skip_uses_the_skipping_actor_and_unblocks_the_next_day(
    tmp_path: Path,
) -> None:
    path = tmp_path / "batch.sqlite"
    store, service = service_for(path, ScriptedCalculation(), faults={"fail_finish"})
    try:
        with pytest.raises(BatchDidNotComplete, match="batch finish could not be recorded") as caught:
            run(service, account_ids=["acc-1"])
        failed = caught.value.run
        assert failed is not None
        with pytest.raises(InvalidBatchRequest, match="skip reason is required"):
            service.skip_run(
                organisation_id="org-1",
                run_id=failed.id,
                actor_id="person-2",
                reason="  ",
            )
        skipped = service.skip_run(
            organisation_id="org-1",
            run_id=failed.id,
            actor_id="person-2",
            reason="ledger restored after the runner was killed",
        )
        assert skipped.status == "skipped"
        assert skipped.outcome == "skipped"
        assert skipped.finished_at is None
        assert skipped.skipped_by == "person-2"
        assert skipped.actor_id == "person-1"
        assert skipped.alert is not None
        assert skipped.alert.resolution == "skipped"
        assert skipped.alert.resolved_by == "person-2"
        skip_audit = [
            entry
            for entry in service.audit_entries("org-1")
            if entry.outcome == "skipped"
        ]
        assert len(skip_audit) == 1
        assert skip_audit[0].actor_id == "person-2"
        assert skip_audit[0].recorded_at.endswith("+02:00")
        assert "ledger restored" in skip_audit[0].detail
        status = service.status("org-1")
        assert status.later_recognition_date_blocked is False
        assert status.open_alerts == ()
        assert status.last_failed_run is not None
        assert status.last_failed_run.id == skipped.id
        with pytest.raises(BatchConflict, match="already skipped"):
            service.skip_run(
                organisation_id="org-1",
                run_id=failed.id,
                actor_id="person-2",
                reason="again",
            )
    finally:
        store.close()

    store, service = service_for(path, ScriptedCalculation())
    try:
        later = run(service, recognition_date="2026-10-29", account_ids=[])
        assert later.outcome == "success"
        with pytest.raises(BatchNotFound):
            service.skip_run(
                organisation_id="org-2",
                run_id=later.id,
                actor_id="person-9",
                reason="wrong organisation",
            )
        with pytest.raises(BatchConflict, match="cannot be skipped because it finished"):
            service.skip_run(
                organisation_id="org-1",
                run_id=later.id,
                actor_id="person-2",
                reason="too late",
            )
    finally:
        store.close()


def test_killed_run_stays_in_progress_until_the_next_start_raises_the_alert(
    tmp_path: Path,
) -> None:
    class KillFirst:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def accrue(self, *, organisation_id: str, account_id: str, recognition_at: datetime) -> None:
            self.calls.append(organisation_id)
            if organisation_id == "org-a":
                raise SystemExit(1)

        def capitalise(self, *, organisation_id: str, account_id: str, recognition_at: datetime) -> None:
            self.calls.append(f"capitalise:{organisation_id}")

        def default_check(
            self, *, organisation_id: str, account_id: str, recognition_at: datetime
        ) -> None:
            self.calls.append(f"default:{organisation_id}")

    calculation = KillFirst()
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        with pytest.raises(SystemExit):
            run(service, organisation_id="org-a")
        status = service.status("org-a")
        assert status.last_status is not None
        assert status.last_status.status == "in_progress"
        assert status.last_status.finished_at is None
        assert status.later_recognition_date_blocked is True
        assert status.open_recognition_date is None
        assert "has not completed" in (status.block_reason or "")
        assert status.open_alerts == ()
        assert status.last_failed_run is None
        other = run(service, organisation_id="org-b", account_ids=[])
        assert other.outcome == "success"
        assert service.status("org-b").later_recognition_date_blocked is False
        with pytest.raises(BatchConflict, match="still in progress") as caught:
            run(service, organisation_id="org-a", recognition_date="2026-10-29", account_ids=[])
        assert caught.value.run is not None
        assert caught.value.run.alert is not None
        assert caught.value.run.alert.resolution is None
        assert service.status("org-a").open_alerts[0].batch_run_id == status.last_status.id
        assert len([call for call in calculation.calls if call == "org-a"]) == 1
        skipped = service.skip_run(
            organisation_id="org-a",
            run_id=status.last_status.id,
            actor_id="person-2",
            reason="runner was killed after the start was recorded",
        )
        assert skipped.status == "skipped"
        assert skipped.alert is not None
        assert skipped.alert.resolution == "skipped"
        assert "did not complete" in skipped.alert.reason
        retried = run(service, organisation_id="org-a", account_ids=[])
        assert retried.outcome == "success"
        assert service.status("org-a").later_recognition_date_blocked is False
        assert service.status("org-a").open_alerts == ()
    finally:
        store.close()


def test_finished_recognition_date_cannot_be_run_again(tmp_path: Path) -> None:
    calculation = ScriptedCalculation()
    store, service = service_for(tmp_path / "batch.sqlite", calculation)
    try:
        run(service, account_ids=[])
        with pytest.raises(BatchConflict, match="already has a finished batch"):
            run(service, account_ids=["acc-1"])
        assert calculation.calls == []
    finally:
        store.close()


def test_could_not_record_account_failure_stops_the_batch(tmp_path: Path) -> None:
    calculation = ScriptedCalculation({"acc-1": ("accrue", "agreement has no rate")})
    store, service = service_for(
        tmp_path / "batch.sqlite", calculation, faults={"fail_failure_insert"}
    )
    try:
        with pytest.raises(BatchDidNotComplete, match="acc-1") as caught:
            run(service, account_ids=["acc-1", "acc-2"])
        assert "agreement has no rate" in str(caught.value)
        assert caught.value.run is not None
        assert caught.value.run.failures == ()
        assert [call[:2] for call in calculation.calls] == [("accrue", "acc-1")]
        assert service.status("org-1").open_alerts
    finally:
        store.close()


def test_organisations_do_not_share_status(tmp_path: Path) -> None:
    store, service = service_for(tmp_path / "batch.sqlite", ScriptedCalculation())
    try:
        run(service, organisation_id="org-1", account_ids=[])
        assert service.status("org-2").last_status is None
        assert service.audit_entries("org-2") == ()
    finally:
        store.close()


def test_schema_allows_one_in_progress_and_one_finished_run_per_date(tmp_path: Path) -> None:
    path = tmp_path / "batch.sqlite"
    store, service = service_for(path, ScriptedCalculation())
    try:
        finished = run(service, account_ids=[])
    finally:
        store.close()
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO batch_runs (
                    id, organisation_id, recognition_date, recognition_at, started_at,
                    finished_at, accounts_processed, accounts_failed, status, actor_id,
                    batch_failure_reason, skipped_at, skipped_by, skip_reason,
                    superseded_by_run_id, seq
                ) VALUES (
                    'second-finished', 'org-1', '2026-10-28', ?, ?,
                    ?, 0, 0, 'completed', 'person-1',
                    NULL, NULL, NULL, NULL, NULL, 99
                )
                """,
                (
                    finished.recognition_at,
                    finished.started_at,
                    finished.finished_at,
                ),
            )
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO batch_runs (
                    id, organisation_id, recognition_date, recognition_at, started_at,
                    finished_at, accounts_processed, accounts_failed, status, actor_id,
                    batch_failure_reason, skipped_at, skipped_by, skip_reason,
                    superseded_by_run_id, seq
                ) VALUES (
                    'progress-a', 'org-9', '2026-10-28', ?, ?,
                    NULL, 0, 0, 'in_progress', 'person-1',
                    NULL, NULL, NULL, NULL, NULL, 100
                )
                """,
                (finished.recognition_at, finished.started_at),
            )
            conn.execute(
                """
                INSERT INTO batch_runs (
                    id, organisation_id, recognition_date, recognition_at, started_at,
                    finished_at, accounts_processed, accounts_failed, status, actor_id,
                    batch_failure_reason, skipped_at, skipped_by, skip_reason,
                    superseded_by_run_id, seq
                ) VALUES (
                    'progress-b', 'org-9', '2026-10-29', ?, ?,
                    NULL, 0, 0, 'in_progress', 'person-1',
                    NULL, NULL, NULL, NULL, NULL, 101
                )
                """,
                (finished.recognition_at, finished.started_at),
            )
        conn.rollback()
    finally:
        conn.close()


def test_second_connection_sees_the_in_progress_gate(tmp_path: Path) -> None:
    class Stop:
        def accrue(self, **kwargs: object) -> None:
            raise SystemExit(1)

        def capitalise(self, **kwargs: object) -> None:
            return None

        def default_check(self, **kwargs: object) -> None:
            return None

    path = tmp_path / "batch.sqlite"
    store_a, service_a = service_for(path, Stop())
    try:
        with pytest.raises(SystemExit):
            run(service_a)
    finally:
        store_a.close()
    store_b, service_b = service_for(path, ScriptedCalculation())
    try:
        with pytest.raises(BatchConflict, match="still in progress"):
            run(service_b, recognition_date="2026-10-29", account_ids=[])
        assert service_b.status("org-1").open_alerts
    finally:
        store_b.close()


def test_query_route(tmp_path: Path) -> None:
    calculation = ScriptedCalculation({"acc-2": ("default_check", "outside limit, threshold unset")})
    app = build_app(
        str(tmp_path / "batch.sqlite"),
        calculation,
        AdvancingClock(datetime(2026, 10, 27, 22, 15, 1, tzinfo=timezone.utc)),
    )
    empty_status, empty_body = app.handle("GET", "/organisations/org-1/batch-status")
    assert empty_status == 200
    assert empty_body["last_status"] is None
    assert empty_body["timezone"] == "Africa/Johannesburg"
    assert empty_body["recognition_boundary"] == "00:00"

    refused, refused_body = app.handle(
        "POST",
        "/organisations/org-1/batch-runs",
        json.dumps(
            {
                "actor_id": "person-1",
                "recognition_date": "2026-10-28T10:00:00+02:00",
                "account_ids": ["acc-1"],
            }
        ).encode(),
    )
    assert refused == 400
    assert refused_body["error"] == "recognition date must be 00:00 Africa/Johannesburg"
    assert calculation.calls == []

    created, created_body = app.handle(
        "POST",
        "/organisations/org-1/batch-runs",
        json.dumps(
            {
                "actor_id": "person-1",
                "recognition_date": "2026-10-28",
                "account_ids": ["acc-1", "acc-2"],
            }
        ).encode(),
    )
    assert created == 200
    assert created_body["outcome"] == "failed"
    assert created_body["accounts_processed"] == 2
    assert created_body["accounts_failed"] == 1
    assert created_body["failures"][0]["account_id"] == "acc-2"
    assert created_body["failures"][0]["reason"] == "default_check: outside limit, threshold unset"

    status_code, body = app.handle("GET", "/organisations/org-1/batch-status")
    assert status_code == 200
    assert set(body) == STATUS_KEYS
    assert body["last_failed_run"]["id"] == created_body["id"]
    assert body["last_successful_run"] is None
    assert body["later_recognition_date_blocked"] is False

    success_code, success_body = app.handle(
        "POST",
        "/organisations/org-1/batch-runs",
        json.dumps(
            {
                "actor_id": "person-1",
                "recognition_date": "2026-10-29",
                "account_ids": [],
                "organisation_id": "org-1",
            }
        ).encode(),
    )
    assert success_code == 201
    assert success_body["outcome"] == "success"

    mismatch, mismatch_body = app.handle(
        "POST",
        "/organisations/org-1/batch-runs",
        json.dumps({"organisation_id": "org-2", "actor_id": "person-1"}).encode(),
    )
    assert mismatch == 400
    assert "does not match" in mismatch_body["error"]

    query, query_body = app.handle("GET", "/organisations/org-1/batch-status?all=1")
    assert query == 400
    assert query_body["error"] == "this route does not accept a query string"
    missing, missing_body = app.handle("GET", "/batch-status")
    assert missing == 404
    assert missing_body["error"] == "route not found"
    method, method_body = app.handle("POST", "/organisations/org-1/batch-status")
    assert method == 405

    server = serve(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/organisations/org-1/batch-status")
        response = connection.getresponse()
        payload = json.loads(response.read().decode())
        assert response.status == 200
        assert payload["last_successful_run"]["recognition_date"] == "2026-10-29"
        assert payload["last_failed_run"]["recognition_date"] == "2026-10-28"
        assert payload["last_status"]["outcome"] == "success"
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
