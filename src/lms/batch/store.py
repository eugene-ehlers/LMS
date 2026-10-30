"""SQLite store for daily calculation batch runs, failures, alerts, and audit."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Iterator

from lms.batch.errors import PersistenceError, StoreConflict
from lms.batch.records import (
    ACTION_DAILY_BATCH,
    STATUS_COMPLETED,
    STATUS_INCOMPLETE,
    STATUS_IN_PROGRESS,
    STATUS_SKIPPED,
    AccountFailure,
    AuditEntry,
    BatchAlert,
    BatchRun,
    BatchStatus,
    outcome_for,
)
from lms.batch.timekeeping import RECOGNITION_BOUNDARY, TIMEZONE_NAME

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_runs (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL,
    recognition_date TEXT NOT NULL,
    recognition_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    accounts_processed INTEGER NOT NULL,
    accounts_failed INTEGER NOT NULL,
    accounts_at_ceiling INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    batch_failure_reason TEXT,
    skipped_at TEXT,
    skipped_by TEXT,
    skip_reason TEXT,
    superseded_by_run_id TEXT,
    seq INTEGER NOT NULL UNIQUE,
    CHECK (status IN ('in_progress', 'completed', 'incomplete', 'skipped')),
    CHECK (accounts_processed >= 0),
    CHECK (accounts_failed >= 0),
    CHECK (accounts_failed <= accounts_processed),
    CHECK (accounts_at_ceiling >= 0),
    CHECK (accounts_at_ceiling <= accounts_processed),
    CHECK (
        (status = 'completed' AND finished_at IS NOT NULL)
        OR (status <> 'completed' AND finished_at IS NULL)
    ),
    CHECK (
        (
            status = 'skipped'
            AND skipped_at IS NOT NULL
            AND skipped_by IS NOT NULL
            AND skip_reason IS NOT NULL
        )
        OR (
            status <> 'skipped'
            AND skipped_at IS NULL
            AND skipped_by IS NULL
            AND skip_reason IS NULL
        )
    ),
    CHECK (
        status <> 'incomplete'
        OR (
            batch_failure_reason IS NOT NULL
            AND length(batch_failure_reason) > 0
        )
    )
);

CREATE INDEX IF NOT EXISTS batch_runs_by_organisation
ON batch_runs (organisation_id, seq);

CREATE UNIQUE INDEX IF NOT EXISTS one_in_progress_per_organisation
ON batch_runs (organisation_id)
WHERE status = 'in_progress';

CREATE UNIQUE INDEX IF NOT EXISTS one_finished_batch_per_recognition_date
ON batch_runs (organisation_id, recognition_date)
WHERE status = 'completed';

CREATE TABLE IF NOT EXISTS batch_account_failures (
    id TEXT PRIMARY KEY,
    batch_run_id TEXT NOT NULL REFERENCES batch_runs (id),
    account_id TEXT NOT NULL,
    step TEXT NOT NULL,
    reason TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    CHECK (step IN ('accrue', 'capitalise', 'default_check')),
    CHECK (length(reason) > 0),
    UNIQUE (batch_run_id, account_id)
);

CREATE TABLE IF NOT EXISTS batch_alerts (
    id TEXT PRIMARY KEY,
    batch_run_id TEXT NOT NULL UNIQUE REFERENCES batch_runs (id),
    organisation_id TEXT NOT NULL,
    recognition_date TEXT NOT NULL,
    raised_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    resolution TEXT,
    resolved_at TEXT,
    resolved_by TEXT,
    CHECK (resolution IS NULL OR resolution IN ('resolved', 'skipped')),
    CHECK (length(reason) > 0),
    CHECK (
        (
            resolution IS NULL
            AND resolved_at IS NULL
            AND resolved_by IS NULL
        )
        OR (
            resolution IS NOT NULL
            AND resolved_at IS NOT NULL
            AND resolved_by IS NOT NULL
        )
    )
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    organisation_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    batch_run_id TEXT,
    detail TEXT NOT NULL,
    CHECK (length(actor_id) > 0),
    CHECK (length(detail) > 0)
);

CREATE INDEX IF NOT EXISTS audit_log_by_organisation
ON audit_log (organisation_id, seq);
"""


class BatchStore:
    """One connection. Check-and-insert uses an immediate transaction."""

    def __init__(self, path: str, faults: set[str] | None = None) -> None:
        self.faults = faults if faults is not None else set()
        self._progress_writes = 0
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._conn.in_transaction:
                raise PersistenceError("batch store transaction already open")
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def start_run(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognition_date: str,
        recognition_at: str,
        started_at: str,
    ) -> BatchRun:
        if "fail_start" in self.faults:
            raise PersistenceError("batch start could not be recorded")
        blocked: tuple[str, str] | None = None
        created_id: str | None = None
        try:
            with self._transaction():
                in_progress = self._find_in_progress(organisation_id)
                if in_progress is not None:
                    reason = _in_progress_reason(in_progress)
                    self._ensure_alert(in_progress, started_at, reason)
                    self._insert_audit(
                        organisation_id=organisation_id,
                        actor_id=actor_id,
                        recorded_at=started_at,
                        outcome="start_refused",
                        batch_run_id=in_progress["id"],
                        detail=reason,
                    )
                    blocked = (reason, in_progress["id"])
                else:
                    unresolved = self._unresolved_incomplete(organisation_id)
                    other_dates = [
                        row
                        for row in unresolved
                        if row["recognition_date"] != recognition_date
                    ]
                    if other_dates:
                        blocking = other_dates[0]
                        reason = _incomplete_reason(blocking)
                        self._ensure_alert(blocking, started_at, reason)
                        self._insert_audit(
                            organisation_id=organisation_id,
                            actor_id=actor_id,
                            recorded_at=started_at,
                            outcome="start_refused",
                            batch_run_id=blocking["id"],
                            detail=reason,
                        )
                        blocked = (reason, blocking["id"])
                    else:
                        finished = self._completed_for(organisation_id, recognition_date)
                        if finished is not None:
                            reason = (
                                f"recognition date {recognition_date} already has a "
                                f"finished batch {finished['id']}"
                            )
                            self._insert_audit(
                                organisation_id=organisation_id,
                                actor_id=actor_id,
                                recorded_at=started_at,
                                outcome="start_refused",
                                batch_run_id=finished["id"],
                                detail=reason,
                            )
                            blocked = (reason, finished["id"])
                        else:
                            created_id = str(uuid.uuid4())
                            seq = self._next_seq()
                            self._conn.execute(
                                """
                                INSERT INTO batch_runs (
                                    id, organisation_id, recognition_date, recognition_at,
                                    started_at, finished_at, accounts_processed,
                                    accounts_failed, accounts_at_ceiling, status, actor_id,
                                    batch_failure_reason, skipped_at, skipped_by,
                                    skip_reason, superseded_by_run_id, seq
                                ) VALUES (?, ?, ?, ?, ?, NULL, 0, 0, 0, ?, ?, NULL, NULL, NULL, NULL, NULL, ?)
                                """,
                                (
                                    created_id,
                                    organisation_id,
                                    recognition_date,
                                    recognition_at,
                                    started_at,
                                    STATUS_IN_PROGRESS,
                                    actor_id,
                                    seq,
                                ),
                            )
                            self._insert_audit(
                                organisation_id=organisation_id,
                                actor_id=actor_id,
                                recorded_at=started_at,
                                outcome="started",
                                batch_run_id=created_id,
                                detail=(
                                    "daily calculation batch started for recognition "
                                    f"date {recognition_date} at 00:00 Africa/Johannesburg"
                                ),
                            )
        except sqlite3.IntegrityError as exc:
            conflict = self._record_integrity_conflict(
                organisation_id, actor_id, started_at
            )
            if conflict is not None:
                raise StoreConflict(conflict[0], conflict[1]) from exc
            raise PersistenceError("batch start could not be recorded") from exc
        if blocked is not None:
            raise StoreConflict(blocked[0], blocked[1])
        run = self.get_run(created_id or "")
        if run is None:
            raise PersistenceError("batch start could not be recorded")
        return run

    def _record_integrity_conflict(
        self, organisation_id: str, actor_id: str, started_at: str
    ) -> tuple[str, str] | None:
        with self._transaction():
            in_progress = self._find_in_progress(organisation_id)
            if in_progress is None:
                return None
            reason = _in_progress_reason(in_progress)
            self._ensure_alert(in_progress, started_at, reason)
            self._insert_audit(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recorded_at=started_at,
                outcome="start_refused",
                batch_run_id=in_progress["id"],
                detail=reason,
            )
            return reason, in_progress["id"]

    def record_progress(
        self,
        run_id: str,
        accounts_processed: int,
        accounts_failed: int,
        accounts_at_ceiling: int = 0,
    ) -> bool:
        self._progress_writes += 1
        if "fail_progress" in self.faults and self._progress_writes >= 1:
            raise PersistenceError("could not record batch progress")
        with self._transaction():
            cursor = self._conn.execute(
                """
                UPDATE batch_runs
                SET accounts_processed = ?, accounts_failed = ?, accounts_at_ceiling = ?
                WHERE id = ? AND status = ?
                """,
                (
                    accounts_processed,
                    accounts_failed,
                    accounts_at_ceiling,
                    run_id,
                    STATUS_IN_PROGRESS,
                ),
            )
            return cursor.rowcount == 1

    def record_account_failure(
        self,
        *,
        run_id: str,
        account_id: str,
        step: str,
        reason: str,
        accounts_processed: int,
        accounts_failed: int,
        recorded_at: str,
        accounts_at_ceiling: int = 0,
    ) -> bool:
        if "fail_failure_insert" in self.faults:
            raise PersistenceError("could not record account failure")
        with self._transaction():
            current = self._conn.execute(
                "SELECT status FROM batch_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if current is None or current["status"] != STATUS_IN_PROGRESS:
                return False
            self._conn.execute(
                """
                INSERT INTO batch_account_failures (
                    id, batch_run_id, account_id, step, reason, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), run_id, account_id, step, reason, recorded_at),
            )
            cursor = self._conn.execute(
                """
                UPDATE batch_runs
                SET accounts_processed = ?, accounts_failed = ?, accounts_at_ceiling = ?
                WHERE id = ? AND status = ?
                """,
                (
                    accounts_processed,
                    accounts_failed,
                    accounts_at_ceiling,
                    run_id,
                    STATUS_IN_PROGRESS,
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("could not record account failure")
            return True

    def finish_run(
        self,
        *,
        run_id: str,
        accounts_processed: int,
        accounts_failed: int,
        finished_at: str,
        actor_id: str,
        accounts_at_ceiling: int = 0,
    ) -> BatchRun | None:
        if "fail_finish" in self.faults:
            raise PersistenceError("batch finish could not be recorded")
        with self._transaction():
            failure_count = self._count_failures(run_id)
            if failure_count != accounts_failed:
                raise PersistenceError(
                    f"account failure count {failure_count} does not match "
                    f"accounts_failed {accounts_failed}"
                )
            current = self._conn.execute(
                "SELECT * FROM batch_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if current is None or current["status"] != STATUS_IN_PROGRESS:
                return None
            cursor = self._conn.execute(
                """
                UPDATE batch_runs
                SET status = ?, finished_at = ?, accounts_processed = ?,
                    accounts_failed = ?, accounts_at_ceiling = ?
                WHERE id = ? AND status = ?
                """,
                (
                    STATUS_COMPLETED,
                    finished_at,
                    accounts_processed,
                    accounts_failed,
                    accounts_at_ceiling,
                    run_id,
                    STATUS_IN_PROGRESS,
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._resolve_open_alert(
                run_id,
                resolution="resolved",
                resolved_at=finished_at,
                resolved_by=actor_id,
            )
            self._supersede_earlier_incomplete(
                organisation_id=current["organisation_id"],
                recognition_date=current["recognition_date"],
                seq=current["seq"],
                superseded_by=run_id,
                resolved_at=finished_at,
                resolved_by=actor_id,
            )
            outcome = outcome_for(STATUS_COMPLETED, accounts_failed)
            detail = self._finish_detail(
                run_id, accounts_processed, accounts_failed, accounts_at_ceiling
            )
            self._insert_audit(
                organisation_id=current["organisation_id"],
                actor_id=actor_id,
                recorded_at=finished_at,
                outcome=outcome,
                batch_run_id=run_id,
                detail=detail,
            )
            return self._load_run(run_id)

    def mark_incomplete(
        self,
        *,
        run_id: str,
        reason: str,
        accounts_processed: int,
        accounts_failed: int,
        recorded_at: str,
        actor_id: str,
        accounts_at_ceiling: int = 0,
    ) -> BatchRun | None:
        with self._transaction():
            current = self._conn.execute(
                "SELECT * FROM batch_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if current is None or current["status"] != STATUS_IN_PROGRESS:
                return None
            stored_failures = self._count_failures(run_id)
            if accounts_failed < stored_failures:
                accounts_failed = stored_failures
            if accounts_processed < accounts_failed:
                accounts_processed = accounts_failed
            cursor = self._conn.execute(
                """
                UPDATE batch_runs
                SET status = ?, batch_failure_reason = ?,
                    accounts_processed = ?, accounts_failed = ?, accounts_at_ceiling = ?
                WHERE id = ? AND status = ?
                """,
                (
                    STATUS_INCOMPLETE,
                    reason,
                    accounts_processed,
                    accounts_failed,
                    accounts_at_ceiling,
                    run_id,
                    STATUS_IN_PROGRESS,
                ),
            )
            if cursor.rowcount != 1:
                return None
            self._ensure_alert(current, recorded_at, reason)
            self._conn.execute(
                """
                UPDATE batch_alerts
                SET reason = ?
                WHERE batch_run_id = ? AND resolution IS NULL
                """,
                (reason, run_id),
            )
            self._insert_audit(
                organisation_id=current["organisation_id"],
                actor_id=actor_id,
                recorded_at=recorded_at,
                outcome="incomplete",
                batch_run_id=run_id,
                detail=reason,
            )
            return self._load_run(run_id)

    def skip_run(
        self,
        *,
        organisation_id: str,
        run_id: str,
        actor_id: str,
        reason: str,
        skipped_at: str,
    ) -> BatchRun:
        with self._transaction():
            current = self._conn.execute(
                "SELECT * FROM batch_runs WHERE id = ? AND organisation_id = ?",
                (run_id, organisation_id),
            ).fetchone()
            if current is None:
                raise StoreConflict("batch run was not found", None)
            if current["status"] == STATUS_SKIPPED:
                raise StoreConflict(
                    f"batch run {run_id} is already skipped",
                    run_id,
                )
            if current["status"] == STATUS_COMPLETED:
                raise StoreConflict(
                    f"batch run {run_id} cannot be skipped because it finished",
                    run_id,
                )
            if current["status"] not in (STATUS_IN_PROGRESS, STATUS_INCOMPLETE):
                raise StoreConflict(
                    f"batch run {run_id} cannot be skipped because it finished",
                    run_id,
                )
            cursor = self._conn.execute(
                """
                UPDATE batch_runs
                SET status = ?, skipped_at = ?, skipped_by = ?, skip_reason = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    STATUS_SKIPPED,
                    skipped_at,
                    actor_id,
                    reason,
                    run_id,
                    STATUS_IN_PROGRESS,
                    STATUS_INCOMPLETE,
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceError("batch skip could not be recorded")
            alert_reason = _incomplete_reason(current)
            self._ensure_alert(current, skipped_at, alert_reason)
            self._conn.execute(
                """
                UPDATE batch_alerts
                SET reason = ?
                WHERE batch_run_id = ? AND resolution IS NULL
                """,
                (alert_reason, run_id),
            )
            self._resolve_open_alert(
                run_id,
                resolution="skipped",
                resolved_at=skipped_at,
                resolved_by=actor_id,
            )
            self._insert_audit(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recorded_at=skipped_at,
                outcome="skipped",
                batch_run_id=run_id,
                detail=f"daily calculation batch explicitly skipped: {reason}",
            )
            loaded = self._load_run(run_id)
            if loaded is None:
                raise PersistenceError("batch skip could not be recorded")
            return loaded

    def record_audit(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recorded_at: str,
        outcome: str,
        detail: str,
        batch_run_id: str | None = None,
    ) -> None:
        with self._transaction():
            self._insert_audit(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recorded_at=recorded_at,
                outcome=outcome,
                batch_run_id=batch_run_id,
                detail=detail,
            )

    def get_run(self, run_id: str) -> BatchRun | None:
        with self._transaction():
            return self._load_run(run_id)

    def status(self, organisation_id: str) -> BatchStatus:
        with self._transaction():
            last = self._latest(
                """
                SELECT id FROM batch_runs
                WHERE organisation_id = ?
                ORDER BY seq DESC
                LIMIT 1
                """,
                (organisation_id,),
            )
            success = self._latest(
                """
                SELECT id FROM batch_runs
                WHERE organisation_id = ?
                  AND status = ?
                  AND accounts_failed = 0
                ORDER BY seq DESC
                LIMIT 1
                """,
                (organisation_id, STATUS_COMPLETED),
            )
            failed = self._latest(
                """
                SELECT id FROM batch_runs
                WHERE organisation_id = ?
                  AND (
                    status IN (?, ?)
                    OR (status = ? AND accounts_failed > 0)
                  )
                ORDER BY seq DESC
                LIMIT 1
                """,
                (
                    organisation_id,
                    STATUS_INCOMPLETE,
                    STATUS_SKIPPED,
                    STATUS_COMPLETED,
                ),
            )
            in_progress_rows = self._in_progress_rows(organisation_id)
            unresolved = self._unresolved_incomplete(organisation_id)
            block_reason, open_date = _block_fields(in_progress_rows, unresolved)
            alerts = tuple(
                self._alert_from_row(row)
                for row in self._conn.execute(
                    """
                    SELECT * FROM batch_alerts
                    WHERE organisation_id = ? AND resolution IS NULL
                    ORDER BY raised_at ASC, id ASC
                    """,
                    (organisation_id,),
                ).fetchall()
            )
            return BatchStatus(
                organisation_id=organisation_id,
                timezone=TIMEZONE_NAME,
                recognition_boundary=RECOGNITION_BOUNDARY,
                later_recognition_date_blocked=block_reason is not None,
                block_reason=block_reason,
                open_recognition_date=open_date,
                last_status=last,
                last_successful_run=success,
                last_failed_run=failed,
                open_alerts=alerts,
            )

    def audit_entries(self, organisation_id: str) -> tuple[AuditEntry, ...]:
        with self._transaction():
            rows = self._conn.execute(
                """
                SELECT * FROM audit_log
                WHERE organisation_id = ?
                ORDER BY seq ASC
                """,
                (organisation_id,),
            ).fetchall()
            return tuple(
                AuditEntry(
                    id=row["id"],
                    organisation_id=row["organisation_id"],
                    actor_id=row["actor_id"],
                    recorded_at=row["recorded_at"],
                    action=row["action"],
                    outcome=row["outcome"],
                    batch_run_id=row["batch_run_id"],
                    detail=row["detail"],
                )
                for row in rows
            )

    def _latest(self, sql: str, params: tuple[object, ...]) -> BatchRun | None:
        row = self._conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return self._load_run(row["id"])

    def _load_run(self, run_id: str) -> BatchRun | None:
        row = self._conn.execute(
            "SELECT * FROM batch_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        failures = tuple(
            AccountFailure(
                account_id=failure["account_id"],
                step=failure["step"],
                reason=failure["reason"],
                recorded_at=failure["recorded_at"],
            )
            for failure in self._conn.execute(
                """
                SELECT * FROM batch_account_failures
                WHERE batch_run_id = ?
                ORDER BY recorded_at ASC, id ASC
                """,
                (run_id,),
            ).fetchall()
        )
        alert_row = self._conn.execute(
            "SELECT * FROM batch_alerts WHERE batch_run_id = ?",
            (run_id,),
        ).fetchone()
        return BatchRun(
            id=row["id"],
            organisation_id=row["organisation_id"],
            recognition_date=row["recognition_date"],
            recognition_at=row["recognition_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            accounts_processed=row["accounts_processed"],
            accounts_failed=row["accounts_failed"],
            accounts_at_ceiling=row["accounts_at_ceiling"],
            status=row["status"],
            outcome=outcome_for(row["status"], row["accounts_failed"]),
            actor_id=row["actor_id"],
            batch_failure_reason=row["batch_failure_reason"],
            failures=failures,
            alert=None if alert_row is None else self._alert_from_row(alert_row),
            skipped_at=row["skipped_at"],
            skipped_by=row["skipped_by"],
            skip_reason=row["skip_reason"],
            superseded_by_run_id=row["superseded_by_run_id"],
        )

    def _alert_from_row(self, row: sqlite3.Row) -> BatchAlert:
        return BatchAlert(
            id=row["id"],
            batch_run_id=row["batch_run_id"],
            organisation_id=row["organisation_id"],
            recognition_date=row["recognition_date"],
            raised_at=row["raised_at"],
            reason=row["reason"],
            resolution=row["resolution"],
            resolved_at=row["resolved_at"],
            resolved_by=row["resolved_by"],
        )

    def _find_in_progress(self, organisation_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM batch_runs
            WHERE organisation_id = ? AND status = ?
            ORDER BY seq ASC
            LIMIT 1
            """,
            (organisation_id, STATUS_IN_PROGRESS),
        ).fetchone()

    def _in_progress_rows(self, organisation_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM batch_runs
            WHERE organisation_id = ? AND status = ?
            ORDER BY seq ASC
            """,
            (organisation_id, STATUS_IN_PROGRESS),
        ).fetchall()

    def _unresolved_incomplete(self, organisation_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM batch_runs AS run
            WHERE run.organisation_id = ?
              AND run.status = ?
              AND NOT EXISTS (
                SELECT 1 FROM batch_runs AS later
                WHERE later.organisation_id = run.organisation_id
                  AND later.recognition_date = run.recognition_date
                  AND later.status = ?
                  AND later.seq > run.seq
              )
            ORDER BY run.seq ASC
            """,
            (organisation_id, STATUS_INCOMPLETE, STATUS_COMPLETED),
        ).fetchall()

    def _completed_for(
        self, organisation_id: str, recognition_date: str
    ) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT * FROM batch_runs
            WHERE organisation_id = ? AND recognition_date = ? AND status = ?
            ORDER BY seq DESC
            LIMIT 1
            """,
            (organisation_id, recognition_date, STATUS_COMPLETED),
        ).fetchone()

    def _next_seq(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM batch_runs"
        ).fetchone()
        return int(row["seq"])

    def _count_failures(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM batch_account_failures WHERE batch_run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["n"])

    def _ensure_alert(self, run: sqlite3.Row, raised_at: str, reason: str) -> None:
        existing = self._conn.execute(
            "SELECT id FROM batch_alerts WHERE batch_run_id = ?",
            (run["id"],),
        ).fetchone()
        if existing is not None:
            return
        self._conn.execute(
            """
            INSERT INTO batch_alerts (
                id, batch_run_id, organisation_id, recognition_date,
                raised_at, reason, resolution, resolved_at, resolved_by
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
            """,
            (
                str(uuid.uuid4()),
                run["id"],
                run["organisation_id"],
                run["recognition_date"],
                raised_at,
                reason,
            ),
        )

    def _resolve_open_alert(
        self,
        run_id: str,
        *,
        resolution: str,
        resolved_at: str,
        resolved_by: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE batch_alerts
            SET resolution = ?, resolved_at = ?, resolved_by = ?
            WHERE batch_run_id = ? AND resolution IS NULL
            """,
            (resolution, resolved_at, resolved_by, run_id),
        )

    def _supersede_earlier_incomplete(
        self,
        *,
        organisation_id: str,
        recognition_date: str,
        seq: int,
        superseded_by: str,
        resolved_at: str,
        resolved_by: str,
    ) -> None:
        earlier = self._conn.execute(
            """
            SELECT id FROM batch_runs
            WHERE organisation_id = ?
              AND recognition_date = ?
              AND status = ?
              AND seq < ?
            """,
            (organisation_id, recognition_date, STATUS_INCOMPLETE, seq),
        ).fetchall()
        self._conn.execute(
            """
            UPDATE batch_runs
            SET superseded_by_run_id = ?
            WHERE organisation_id = ?
              AND recognition_date = ?
              AND status = ?
              AND seq < ?
              AND superseded_by_run_id IS NULL
            """,
            (superseded_by, organisation_id, recognition_date, STATUS_INCOMPLETE, seq),
        )
        for row in earlier:
            self._resolve_open_alert(
                row["id"],
                resolution="resolved",
                resolved_at=resolved_at,
                resolved_by=resolved_by,
            )

    def _finish_detail(
        self,
        run_id: str,
        accounts_processed: int,
        accounts_failed: int,
        accounts_at_ceiling: int,
    ) -> str:
        parts = [
            "daily calculation batch finished",
            f"accounts_processed={accounts_processed}",
            f"accounts_failed={accounts_failed}",
            f"accounts_at_ceiling={accounts_at_ceiling}",
        ]
        rows = self._conn.execute(
            """
            SELECT account_id, reason FROM batch_account_failures
            WHERE batch_run_id = ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        for row in rows:
            parts.append(f"{row['account_id']}: {row['reason']}")
        return "; ".join(parts)

    def _insert_audit(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recorded_at: str,
        outcome: str,
        detail: str,
        batch_run_id: str | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO audit_log (
                id, organisation_id, actor_id, recorded_at, action, outcome,
                batch_run_id, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                organisation_id,
                actor_id,
                recorded_at,
                ACTION_DAILY_BATCH,
                outcome,
                batch_run_id,
                detail,
            ),
        )


def _in_progress_reason(run: sqlite3.Row) -> str:
    return (
        f"batch run {run['id']} for recognition date {run['recognition_date']} "
        "is still in progress and has not completed"
    )


def _incomplete_reason(run: sqlite3.Row) -> str:
    stored = run["batch_failure_reason"] if "batch_failure_reason" in run.keys() else None
    if stored:
        return str(stored)
    return (
        f"batch run {run['id']} for recognition date {run['recognition_date']} "
        "did not complete"
    )


def _block_fields(
    in_progress: list[sqlite3.Row], unresolved: list[sqlite3.Row]
) -> tuple[str | None, str | None]:
    if in_progress:
        return _in_progress_reason(in_progress[0]), None
    if unresolved:
        return _incomplete_reason(unresolved[0]), unresolved[0]["recognition_date"]
    return None, None
