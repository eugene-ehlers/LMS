"""Run, skip, and query the daily calculation batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lms.batch.calculation import AccountStepError, DailyCalculation
from lms.batch.errors import (
    BatchConflict,
    BatchDidNotComplete,
    BatchError,
    BatchNoLongerInProgress,
    BatchNotFound,
    BatchStartNotRecorded,
    CalculationNotConfigured,
    InvalidBatchRequest,
    PersistenceError,
    StoreConflict,
)
from lms.batch.records import (
    STATUS_SKIPPED,
    STEPS,
    AccountFailure,
    BatchRun,
    BatchStatus,
)
from lms.batch.store import BatchStore
from lms.batch.timekeeping import JOHANNESBURG, format_jhb, parse_recognition_date


@dataclass
class _Progress:
    processed: int = 0
    failed: int = 0


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(JOHANNESBURG)


class BatchService:
    def __init__(
        self,
        store: BatchStore,
        calculation: DailyCalculation | None,
        clock: object | None = None,
    ) -> None:
        self._store = store
        self._calculation = calculation
        self._clock = clock if clock is not None else SystemClock()

    def run_batch(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognition_date: object,
        account_ids: object,
    ) -> BatchRun:
        started_at = self._timestamp()
        try:
            organisation_id = _require_token(organisation_id, "organisation_id")
            actor_id = _require_token(actor_id, "actor_id")
            recognition_day, recognition_at = parse_recognition_date(recognition_date)
            accounts = _require_accounts(account_ids)
        except ValueError as exc:
            self._refuse_if_possible(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recorded_at=started_at,
                detail=str(exc),
            )
            raise InvalidBatchRequest(str(exc)) from exc

        if self._calculation is None:
            self._refuse_if_possible(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recorded_at=started_at,
                detail="daily calculation steps are not configured",
            )
            raise CalculationNotConfigured("daily calculation steps are not configured")

        try:
            run = self._store.start_run(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recognition_date=recognition_day,
                recognition_at=recognition_at,
                started_at=started_at,
            )
        except PersistenceError as exc:
            raise BatchStartNotRecorded("batch start could not be recorded") from exc
        except StoreConflict as exc:
            raise self._conflict(exc) from exc

        progress = _Progress()
        try:
            return self._process(
                run,
                accounts,
                recognition_at_text=recognition_at,
                progress=progress,
            )
        except BatchNoLongerInProgress:
            raise self._skipped_while_running(run.id) from None
        except BatchStartNotRecorded:
            raise
        except Exception as exc:
            self._fail_incomplete(run, exc, progress)

    def skip_run(
        self,
        *,
        organisation_id: str,
        run_id: str,
        actor_id: str,
        reason: str,
    ) -> BatchRun:
        skipped_at = self._timestamp()
        try:
            organisation_id = _require_token(organisation_id, "organisation_id")
            run_id = _require_token(run_id, "batch run id")
            actor_id = _require_token(actor_id, "actor_id")
            reason = _require_reason(reason)
        except ValueError as exc:
            raise InvalidBatchRequest(str(exc)) from exc
        try:
            return self._store.skip_run(
                organisation_id=organisation_id,
                run_id=run_id,
                actor_id=actor_id,
                reason=reason,
                skipped_at=skipped_at,
            )
        except StoreConflict as exc:
            if exc.run_id is None:
                raise BatchNotFound(
                    f"batch run {run_id} was not found for this organisation"
                ) from exc
            raise self._conflict(exc) from exc
        except PersistenceError as exc:
            raise BatchStartNotRecorded("batch skip could not be recorded") from exc

    def status(self, organisation_id: str) -> BatchStatus:
        try:
            organisation_id = _require_token(organisation_id, "organisation_id")
        except ValueError as exc:
            raise InvalidBatchRequest(str(exc)) from exc
        return self._store.status(organisation_id)

    def audit_entries(self, organisation_id: str):
        organisation_id = _require_token(organisation_id, "organisation_id")
        return self._store.audit_entries(organisation_id)

    def _process(
        self,
        run: BatchRun,
        account_ids: list[str],
        *,
        recognition_at_text: str,
        progress: _Progress,
    ) -> BatchRun:
        recognition_at = datetime.fromisoformat(recognition_at_text)
        calculation = self._calculation
        if calculation is None:
            raise CalculationNotConfigured("daily calculation steps are not configured")
        for account_id in account_ids:
            failure = None
            for step in STEPS:
                self._require_running(run.id)
                failure = _run_step(
                    calculation,
                    step=step,
                    organisation_id=run.organisation_id,
                    account_id=account_id,
                    recognition_at=recognition_at,
                )
                if failure is not None:
                    break
            if failure is not None:
                try:
                    recorded = self._store.record_account_failure(
                        run_id=run.id,
                        account_id=failure.account_id,
                        step=failure.step,
                        reason=failure.reason,
                        accounts_processed=progress.processed + 1,
                        accounts_failed=progress.failed + 1,
                        recorded_at=self._timestamp(),
                    )
                except PersistenceError as exc:
                    raise BatchError(
                        "could not record failure for account "
                        f"{failure.account_id}: {failure.reason}"
                    ) from exc
                if not recorded:
                    raise BatchNoLongerInProgress()
                progress.processed += 1
                progress.failed += 1
            else:
                try:
                    updated = self._store.record_progress(
                        run.id, progress.processed + 1, progress.failed
                    )
                except PersistenceError as exc:
                    raise BatchError(
                        f"could not record batch progress after account {account_id}"
                    ) from exc
                if not updated:
                    raise BatchNoLongerInProgress()
                progress.processed += 1
        self._require_running(run.id)
        try:
            finished = self._store.finish_run(
                run_id=run.id,
                accounts_processed=progress.processed,
                accounts_failed=progress.failed,
                finished_at=self._timestamp(),
                actor_id=run.actor_id,
            )
        except PersistenceError as exc:
            raise BatchError("batch finish could not be recorded") from exc
        if finished is None:
            raise BatchNoLongerInProgress()
        return finished

    def _fail_incomplete(
        self, run: BatchRun, exc: Exception, progress: _Progress
    ) -> None:
        if isinstance(exc, BatchError):
            reason = exc.reason
        else:
            reason = str(exc).strip() or "batch failed without a reason"
        try:
            recorded_at = self._timestamp()
        except BatchStartNotRecorded:
            raise
        try:
            failed_run = self._store.mark_incomplete(
                run_id=run.id,
                reason=reason,
                accounts_processed=progress.processed,
                accounts_failed=progress.failed,
                recorded_at=recorded_at,
                actor_id=run.actor_id,
            )
        except PersistenceError as persist:
            raise BatchStartNotRecorded(
                "batch did not complete and the failure could not be recorded"
            ) from persist
        if failed_run is None:
            raise self._skipped_while_running(run.id)
        raise BatchDidNotComplete(reason, failed_run)

    def _require_running(self, run_id: str) -> None:
        current = self._store.get_run(run_id)
        if current is None or current.status != "in_progress":
            raise BatchNoLongerInProgress()

    def _skipped_while_running(self, run_id: str) -> BatchConflict:
        current = self._store.get_run(run_id)
        if current is not None and current.status == STATUS_SKIPPED:
            return BatchConflict(
                f"batch run {run_id} was explicitly skipped while it was running",
                current,
            )
        return BatchConflict(
            f"batch run {run_id} is no longer in progress",
            current,
        )

    def _conflict(self, exc: StoreConflict) -> BatchConflict:
        run = self._store.get_run(exc.run_id) if exc.run_id else None
        return BatchConflict(exc.reason, run)

    def _refuse_if_possible(
        self,
        *,
        organisation_id: object,
        actor_id: object,
        recorded_at: str,
        detail: str,
    ) -> None:
        if not isinstance(organisation_id, str) or not isinstance(actor_id, str):
            return
        if organisation_id.strip() == "" or actor_id.strip() == "":
            return
        if organisation_id != organisation_id.strip() or actor_id != actor_id.strip():
            return
        try:
            self._store.record_audit(
                organisation_id=organisation_id,
                actor_id=actor_id,
                recorded_at=recorded_at,
                outcome="start_refused",
                detail=detail,
            )
        except PersistenceError:
            return

    def _timestamp(self) -> str:
        now = getattr(self._clock, "now", None)
        if now is None:
            raise BatchStartNotRecorded(
                "clock returned a timestamp that is not Africa/Johannesburg; "
                "batch start could not be recorded"
            )
        try:
            current = now()
        except Exception as exc:
            raise BatchStartNotRecorded(
                "clock returned a timestamp that is not Africa/Johannesburg; "
                "batch start could not be recorded"
            ) from exc
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise BatchStartNotRecorded(
                "clock returned a naive timestamp; batch start could not be recorded"
            )
        if current.tzinfo.utcoffset(current) is None:
            raise BatchStartNotRecorded(
                "clock returned a naive timestamp; batch start could not be recorded"
            )
        try:
            return format_jhb(current)
        except Exception as exc:
            raise BatchStartNotRecorded(
                "clock returned a timestamp that is not Africa/Johannesburg; "
                "batch start could not be recorded"
            ) from exc


def _run_step(
    calculation: DailyCalculation,
    *,
    step: str,
    organisation_id: str,
    account_id: str,
    recognition_at: datetime,
) -> AccountFailure | None:
    method = getattr(calculation, step)
    try:
        method(
            organisation_id=organisation_id,
            account_id=account_id,
            recognition_at=recognition_at,
        )
    except AccountStepError as exc:
        text = exc.reason.strip() if isinstance(exc.reason, str) else ""
        if text == "":
            text = "failed without a reason"
        return AccountFailure(
            account_id=account_id,
            step=step,
            reason=_with_step(step, text),
            recorded_at="",
        )
    except Exception as exc:
        text = str(exc).strip() or "failed without a reason"
        return AccountFailure(
            account_id=account_id,
            step=step,
            reason=_with_step(step, text),
            recorded_at="",
        )
    return None


def _with_step(step: str, reason: str) -> str:
    prefix = f"{step}: "
    if reason.startswith(prefix):
        return reason
    return prefix + reason


def _require_token(value: object, label: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{label} is required")
    if value != value.strip():
        raise ValueError(f"{label} must not have surrounding space")
    return value


def _require_reason(value: object) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError("skip reason is required")
    if value != value.strip():
        raise ValueError("skip reason must not have surrounding space")
    return value


def _require_accounts(value: object) -> list[str]:
    if isinstance(value, str) or not isinstance(value, list):
        raise ValueError("account_ids must be a list of account identifiers")
    seen: set[str] = set()
    accounts: list[str] = []
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise ValueError("account identifier is required")
        if item != item.strip():
            raise ValueError("account identifier must not have surrounding space")
        if item in seen:
            raise ValueError(f"duplicate account identifier {item}")
        seen.add(item)
        accounts.append(item)
    return accounts


__all__ = ["BatchService", "SystemClock"]
