"""Failures the daily calculation batch reports to its caller."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lms.batch.records import BatchRun


class BatchError(Exception):
    """A batch operation failed with a specific reason."""

    status_code = 400

    def __init__(self, reason: str, run: BatchRun | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.run = run


class InvalidBatchRequest(BatchError):
    status_code = 400


class BatchConflict(BatchError):
    status_code = 409


class BatchNotFound(BatchError):
    status_code = 404


class BatchStartNotRecorded(BatchError):
    """The start could not be recorded. No account is processed."""

    status_code = 503


class CalculationNotConfigured(BatchError):
    status_code = 503


class BatchDidNotComplete(BatchError):
    status_code = 500


class PersistenceError(Exception):
    """The batch record store could not write what the batch must record."""


class StoreConflict(Exception):
    """A write was refused because an existing run blocks it."""

    def __init__(self, reason: str, run_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.run_id = run_id


class BatchNoLongerInProgress(Exception):
    """The run left in_progress while accounts were being processed."""
