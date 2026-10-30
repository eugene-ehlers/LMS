"""Batch, failure, alert, and audit records."""

from __future__ import annotations

from dataclasses import dataclass

ACTION_DAILY_BATCH = "daily_calculation_batch"

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_INCOMPLETE = "incomplete"
STATUS_SKIPPED = "skipped"

OUTCOME_STARTED = "started"
OUTCOME_SUCCESS = "success"
OUTCOME_FAILED = "failed"
OUTCOME_INCOMPLETE = "incomplete"
OUTCOME_SKIPPED = "skipped"
OUTCOME_START_REFUSED = "start_refused"

STEP_ACCRUE = "accrue"
STEP_CAPITALISE = "capitalise"
STEP_DEFAULT_CHECK = "default_check"
STEPS = (STEP_ACCRUE, STEP_CAPITALISE, STEP_DEFAULT_CHECK)

RESOLUTION_RESOLVED = "resolved"
RESOLUTION_SKIPPED = "skipped"


def outcome_for(status: str, accounts_failed: int) -> str:
    if status == STATUS_COMPLETED and accounts_failed == 0:
        return OUTCOME_SUCCESS
    if status == STATUS_COMPLETED:
        return OUTCOME_FAILED
    return status


@dataclass(frozen=True)
class AccountFailure:
    account_id: str
    step: str
    reason: str
    recorded_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "account_id": self.account_id,
            "step": self.step,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class BatchAlert:
    id: str
    batch_run_id: str
    organisation_id: str
    recognition_date: str
    raised_at: str
    reason: str
    resolution: str | None
    resolved_at: str | None
    resolved_by: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "batch_run_id": self.batch_run_id,
            "organisation_id": self.organisation_id,
            "recognition_date": self.recognition_date,
            "raised_at": self.raised_at,
            "reason": self.reason,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }


@dataclass(frozen=True)
class BatchRun:
    id: str
    organisation_id: str
    recognition_date: str
    recognition_at: str
    started_at: str
    finished_at: str | None
    accounts_processed: int
    accounts_failed: int
    status: str
    outcome: str
    actor_id: str
    batch_failure_reason: str | None
    failures: tuple[AccountFailure, ...]
    alert: BatchAlert | None
    skipped_at: str | None
    skipped_by: str | None
    skip_reason: str | None
    superseded_by_run_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "organisation_id": self.organisation_id,
            "recognition_date": self.recognition_date,
            "recognition_at": self.recognition_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "accounts_processed": self.accounts_processed,
            "accounts_failed": self.accounts_failed,
            "status": self.status,
            "outcome": self.outcome,
            "actor_id": self.actor_id,
            "batch_failure_reason": self.batch_failure_reason,
            "failures": [failure.to_dict() for failure in self.failures],
            "alert": None if self.alert is None else self.alert.to_dict(),
            "skipped_at": self.skipped_at,
            "skipped_by": self.skipped_by,
            "skip_reason": self.skip_reason,
            "superseded_by_run_id": self.superseded_by_run_id,
        }


@dataclass(frozen=True)
class BatchStatus:
    organisation_id: str
    timezone: str
    recognition_boundary: str
    later_recognition_date_blocked: bool
    block_reason: str | None
    open_recognition_date: str | None
    last_status: BatchRun | None
    last_successful_run: BatchRun | None
    last_failed_run: BatchRun | None
    open_alerts: tuple[BatchAlert, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "organisation_id": self.organisation_id,
            "timezone": self.timezone,
            "recognition_boundary": self.recognition_boundary,
            "later_recognition_date_blocked": self.later_recognition_date_blocked,
            "block_reason": self.block_reason,
            "open_recognition_date": self.open_recognition_date,
            "last_status": None if self.last_status is None else self.last_status.to_dict(),
            "last_successful_run": (
                None
                if self.last_successful_run is None
                else self.last_successful_run.to_dict()
            ),
            "last_failed_run": (
                None if self.last_failed_run is None else self.last_failed_run.to_dict()
            ),
            "open_alerts": [alert.to_dict() for alert in self.open_alerts],
        }


@dataclass(frozen=True)
class AuditEntry:
    id: str
    organisation_id: str
    actor_id: str
    recorded_at: str
    action: str
    outcome: str
    batch_run_id: str | None
    detail: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "organisation_id": self.organisation_id,
            "actor_id": self.actor_id,
            "recorded_at": self.recorded_at,
            "action": self.action,
            "outcome": self.outcome,
            "batch_run_id": self.batch_run_id,
            "detail": self.detail,
        }
