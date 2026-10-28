"""Apply a section 104 rate or fee change to selected accounts.

The notice document is not produced here. The contractual term and the
contractual instalment are not written. Original rate and fees stay on the
account and are copied here for disclosure. Accrual uses the new values
from the effective date through the end date, inclusive.

A collection campaign, a restructure, and an early settlement are refused.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from lms.calc.money import RuleError
from lms.ledger.errors import LedgerError
from lms.ledger.models import FREQUENCIES, LoanAccount
from lms.ledger.service import Ledger, next_due_date
from lms.rate_fee_change.authority import AccessPort, authorise
from lms.rate_fee_change.errors import RateFeeChangeError
from lms.rate_fee_change.models import (
    EVENT,
    FEE_TYPES,
    NOTICE_BUSINESS_DAYS,
    AccountRateFee,
    Outcome,
    RateFeeChange,
    StatusReport,
)
from lms.regulatory.audit import AuditLog
from lms.regulatory.errors import RegulatoryError
from lms_config.calendar import add_business_days, public_holidays, value_date, value_instant
from lms_config.exceptions import CalculationInputError
from lms_config.validate import CPA_LAYBY, ZERO_COST

_RATE_PLACES = Decimal("0.00000001")
_ZERO_COST = {ZERO_COST, CPA_LAYBY}
_DUE_WALK_LIMIT = 2000
_TIMESTAMP = (
    "Recognition time must carry a time zone. The recognition date is "
    "00:00 Africa/Johannesburg. The change was not applied."
)


def notice_holidays(notice: date, extra: frozenset[date] | set[date]) -> frozenset[date]:
    """Statutory holidays for the section 104(2) count, plus caller extras.

    Five business days always fall inside the notice year or the next one.
    Presidential one-off holidays are ``extra``. They are not in
    ``public_holidays``.
    """
    dates: list[date] = []
    for year in (notice.year, notice.year + 1):
        dates.extend(day for day, _name, _source in public_holidays(year))
    return frozenset(dates) | frozenset(extra)


def earliest_effective_date(notice: date, extra: frozenset[date] | set[date] = frozenset()) -> date:
    """First recognition date that is five business days after ``notice``.

    Section 2(5): the notice date is excluded and the returned day is included.
    """
    return add_business_days(notice, NOTICE_BUSINESS_DAYS, notice_holidays(notice, extra))


def _covers(change: RateFeeChange, day: date) -> bool:
    if day < change.effective_date:
        return False
    if change.end_date is not None and day > change.end_date:
        return False
    return True


def _overlaps(left: RateFeeChange, right: RateFeeChange) -> bool:
    left_end = left.end_date or date.max
    right_end = right.end_date or date.max
    return left.effective_date <= right_end and right.effective_date <= left_end


def _instalments(account: LoanAccount) -> tuple[tuple[date, int], ...]:
    ordered = sorted(account.slices, key=lambda item: item.sequence)
    return tuple((item.due_on, item.amount_cents) for item in ordered)


def _cents(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RateFeeChangeError(
            "fee-cents",
            f"{label} must be an integer number of cents. The change was not applied.",
        )
    if value < 0:
        raise RateFeeChangeError(
            "fee-negative",
            f"{label} cannot be negative ({value} cents). The change was not applied.",
        )
    return value


def _rate(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, float):
        raise RateFeeChangeError(
            "rate",
            "A periodic rate must be a decimal string or an exact integer, not a float. "
            "The change was not applied.",
        )
    if isinstance(value, bool):
        raise RateFeeChangeError(
            "rate",
            "A periodic rate must be a decimal string or an exact integer. The change was not applied.",
        )
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise RateFeeChangeError(
                "rate",
                "A periodic rate must be a decimal string. The change was not applied.",
            ) from exc
    else:
        raise RateFeeChangeError(
            "rate",
            "A periodic rate must be a decimal string or an exact integer. The change was not applied.",
        )
    if not parsed.is_finite():
        raise RateFeeChangeError(
            "rate",
            "A periodic rate must be a finite decimal. The change was not applied.",
        )
    if parsed < 0:
        raise RateFeeChangeError(
            "rate-negative",
            "A periodic rate cannot be negative. The change was not applied.",
        )
    if parsed != parsed.quantize(_RATE_PLACES):
        raise RateFeeChangeError(
            "rate-precision",
            f"A periodic rate is stored to 8 decimal places. {parsed} was not rounded. "
            "The change was not applied.",
        )
    return parsed


def _fees(value: object) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RateFeeChangeError(
            "fee",
            "Fees are a map of fee type to integer cents. The change was not applied.",
        )
    parsed: dict[str, int] = {}
    for key, amount in value.items():
        if key not in FEE_TYPES:
            raise RateFeeChangeError(
                "fee-type",
                f"{key} is not a fee type on the ledger. The change was not applied.",
            )
        parsed[str(key)] = _cents(amount, str(key))
    return parsed


class RateFeeChanges:
    def __init__(self, ledger: Ledger, access: AccessPort, audit: AuditLog | None = None) -> None:
        self.ledger = ledger
        self.access = access
        self.audit = audit if audit is not None else AuditLog()
        self._changes: dict[tuple[str, str], RateFeeChange] = {}
        self._accounts: dict[tuple[str, str, str], AccountRateFee] = {}
        self._pending_audit: dict[int, tuple[dict | None, dict | None]] = {}
        self._end_rollback: dict[int, tuple[RateFeeChange, date | None]] = {}

    def apply(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        notice_date: date | None,
        effective_date: date | None,
        end_date: date | None,
        periodic_rate: object,
        fees_cents: object,
        fee_payment_frequency: str | None,
        fee_payment_time: date | None,
        selector: str,
        loan_ids: tuple[str, ...] | list[str] | None = None,
        contractual_fees_cents: dict[str, dict[str, int]] | None = None,
        extra_holidays: frozenset[date] | set[date] = frozenset(),
        repos: tuple = (),
        notice_business_days: int | None = None,
    ) -> Outcome:
        requested = tuple(loan_ids or ())
        recognition = self._recognition(recognised_at)
        if recognition is None:
            return self._naive(requested)
        try:
            actor = authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
            outcome = self._apply(
                organisation_id=organisation_id,
                actor_id=actor,
                recognised_at=recognised_at,
                recognition=recognition,
                notice_date=notice_date,
                effective_date=effective_date,
                end_date=end_date,
                periodic_rate=periodic_rate,
                fees_cents=fees_cents,
                fee_payment_frequency=fee_payment_frequency,
                fee_payment_time=fee_payment_time,
                selector=selector,
                loan_ids=requested,
                contractual_fees_cents=contractual_fees_cents or {},
                extra_holidays=frozenset(extra_holidays),
                repos=repos,
                notice_business_days=notice_business_days,
            )
        except RateFeeChangeError as exc:
            ids = exc.loan_ids or requested
            self._audit_outcome(
                organisation_id=organisation_id,
                recognised_at=recognised_at,
                recognition=recognition,
                actor_id=actor_id,
                action="apply",
                ok=False,
                code=exc.code,
                message=str(exc),
                change_id=None,
                loan_ids=ids,
                notice_date=notice_date,
                effective_date=effective_date,
                end_date=end_date,
                before=None,
                after=None,
            )
            return Outcome(
                False,
                exc.code,
                str(exc),
                exc.status,
                loan_ids=ids,
                notice_date=notice_date,
                effective_date=effective_date,
                end_date=end_date,
                recognition_date=recognition,
            )
        if not self._seal(outcome, organisation_id, recognised_at, recognition, actor_id, "apply"):
            return self._audit_failed(outcome, organisation_id)
        return outcome

    def end(
        self,
        *,
        organisation_id: str,
        change_id: str,
        actor_id: str,
        recognised_at: datetime,
        end_date: date | None,
    ) -> Outcome:
        recognition = self._recognition(recognised_at)
        if recognition is None:
            return self._naive(())
        try:
            actor = authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
            outcome = self._end(
                organisation_id=organisation_id,
                change_id=change_id,
                actor_id=actor,
                recognised_at=recognised_at,
                end_date=end_date,
            )
        except RateFeeChangeError as exc:
            self._audit_outcome(
                organisation_id=organisation_id,
                recognised_at=recognised_at,
                recognition=recognition,
                actor_id=actor_id,
                action="end",
                ok=False,
                code=exc.code,
                message=str(exc),
                change_id=change_id,
                loan_ids=exc.loan_ids,
                notice_date=None,
                effective_date=None,
                end_date=end_date,
                before=None,
                after=None,
            )
            return Outcome(
                False,
                exc.code,
                str(exc),
                exc.status,
                change_id=change_id,
                loan_ids=exc.loan_ids,
                end_date=end_date,
                recognition_date=recognition,
            )
        if not self._seal(outcome, organisation_id, recognised_at, recognition, actor_id, "end"):
            return self._audit_failed(outcome, organisation_id)
        return outcome

    def record_failure(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime | None,
        code: str,
        message: str,
        action: str = "apply",
        loan_ids: tuple[str, ...] = (),
    ) -> None:
        """Audit a refusal that was raised before ``apply`` ran. A naive time is not sealed."""
        if recognised_at is None or not organisation_id:
            return
        recognition = self._recognition(recognised_at)
        if recognition is None:
            return
        self._audit_outcome(
            organisation_id=organisation_id,
            recognised_at=recognised_at,
            recognition=recognition,
            actor_id=actor_id,
            action=action,
            ok=False,
            code=code,
            message=message,
            change_id=None,
            loan_ids=loan_ids,
            notice_date=None,
            effective_date=None,
            end_date=None,
            before=None,
            after=None,
        )

    def last_status(
        self,
        *,
        organisation_id: str,
        on: date,
        loan_id: str | None = None,
    ) -> StatusReport:
        if not organisation_id:
            raise RateFeeChangeError(
                "organisation-unset",
                "A status query needs an organisation id.",
            )
        extract = self.audit.extract(
            organisation_id=organisation_id,
            from_date=date(1970, 1, 1),
            to_date=on,
        )
        rows = [row for row in extract.rows if row.event_type == EVENT]
        if loan_id is not None:
            rows = [row for row in rows if loan_id in list(row.payload.get("loan_ids", []))]
        if not rows:
            return StatusReport(
                False,
                "none",
                "none",
                "No rate or fee change has been recorded for this selection.",
            )
        row = max(rows, key=lambda item: item.recognition_sequence)
        payload = row.payload
        raw_ids = payload.get("loan_ids", [])
        ids = tuple(raw_ids) if isinstance(raw_ids, list) else ()
        recognition_text = payload.get("recognition_date")
        recognition = date.fromisoformat(recognition_text) if isinstance(recognition_text, str) else None
        return StatusReport(
            True,
            str(payload.get("outcome", "")),
            str(payload.get("reason") or payload.get("code") or ""),
            str(payload.get("message", "")),
            None if payload.get("change_id") in (None, "") else str(payload.get("change_id")),
            None if payload.get("action") is None else str(payload.get("action")),
            row.occurred_at,
            ids,
            recognition,
        )

    def get(self, organisation_id: str, change_id: str) -> RateFeeChange:
        change = self._changes.get((organisation_id, change_id))
        if change is None:
            raise RateFeeChangeError(
                "change-unknown",
                "No rate or fee change with that id is stored for this organisation.",
            )
        return change

    def list_changes(self, organisation_id: str) -> tuple[RateFeeChange, ...]:
        return tuple(
            change for (org, _change_id), change in self._changes.items() if org == organisation_id
        )

    def account_record(self, organisation_id: str, change_id: str, loan_id: str) -> AccountRateFee:
        record = self._accounts.get((organisation_id, change_id, loan_id))
        if record is None:
            raise RateFeeChangeError(
                "change-unknown",
                "That loan is not on this rate or fee change.",
            )
        return record

    def periodic_rate_override(
        self,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        repos: tuple = (),
    ) -> Decimal | None:
        """Rate for ``Ledger.accrue_day``, or None when no change covers the day."""
        try:
            day = value_date(recognised_at)
        except CalculationInputError as exc:
            raise RateFeeChangeError("timestamp-naive", _TIMESTAMP) from exc
        try:
            return self._override(organisation_id, loan_id, recognised_at, day, repos)
        except (RateFeeChangeError, LedgerError, RuleError) as exc:
            code = exc.code if isinstance(exc, RateFeeChangeError) else getattr(exc, "code", "accrual")
            message = str(exc)
            self._audit_outcome(
                organisation_id=organisation_id,
                recognised_at=recognised_at,
                recognition=day,
                actor_id="",
                action="accrue",
                ok=False,
                code=code,
                message=message,
                change_id=None,
                loan_ids=(loan_id,),
                notice_date=None,
                effective_date=None,
                end_date=None,
                before=None,
                after=None,
            )
            if isinstance(exc, RateFeeChangeError):
                exc.audited = True
                raise
            wrapped = RateFeeChangeError(code, message)
            wrapped.audited = True
            raise wrapped from exc

    def accrue(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        interest_cap_present: bool,
        repos: tuple = (),
        repo_annual: Decimal | None = None,
    ):
        override = self.periodic_rate_override(organisation_id, loan_id, recognised_at, repos)
        try:
            return self.ledger.accrue_day(
                organisation_id=organisation_id,
                loan_id=loan_id,
                recognised_at=recognised_at,
                interest_cap_present=interest_cap_present,
                repos=repos,
                repo_annual=repo_annual,
                periodic_rate_override=override,
            )
        except LedgerError as exc:
            day = value_date(recognised_at)
            self._audit_outcome(
                organisation_id=organisation_id,
                recognised_at=recognised_at,
                recognition=day,
                actor_id="",
                action="accrue",
                ok=False,
                code=exc.code,
                message=str(exc),
                change_id=None,
                loan_ids=(loan_id,),
                notice_date=None,
                effective_date=None,
                end_date=None,
                before=None,
                after=None,
            )
            wrapped = RateFeeChangeError(exc.code, str(exc))
            wrapped.audited = True
            raise wrapped from exc

    def service_fee_for_levy(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        monthly_cents: int,
    ) -> int:
        """Ex-VAT cents for ``Ledger.levy_service_fee``. VAT stays in the ledger."""
        return self._fee_amount(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            fee_type="service",
            contractual_cents=monthly_cents,
        )

    def fee_due_on(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        contractual_due_on: date,
    ) -> date:
        """Due date to levy. The loan schedule is not rewritten."""
        try:
            day = value_date(recognised_at)
        except CalculationInputError as exc:
            raise RateFeeChangeError("timestamp-naive", _TIMESTAMP) from exc
        try:
            change = self._covering(organisation_id, loan_id, day)
            if change is None or not _moves_payment(change):
                return contractual_due_on
            if self._due_allowed(change, contractual_due_on):
                return contractual_due_on
            raise RateFeeChangeError(
                "payment-time",
                f"The fee payment date {contractual_due_on.isoformat()} is not a date on the "
                f"section 104(2)(c) change for loan {loan_id}. The levy was not posted.",
                loan_ids=(loan_id,),
            )
        except RateFeeChangeError as exc:
            self._audit_use_failure(
                organisation_id, loan_id, recognised_at, day, "levy", exc.code, str(exc)
            )
            exc.audited = True
            raise

    def levy_service_fee(self, **kwargs):
        monthly = kwargs.pop("monthly_cents")
        due_on = kwargs.get("due_on")
        reduced = self.service_fee_for_levy(
            organisation_id=kwargs["organisation_id"],
            loan_id=kwargs["loan_id"],
            recognised_at=kwargs["recognised_at"],
            monthly_cents=monthly,
        )
        if isinstance(due_on, date):
            kwargs["due_on"] = self.fee_due_on(
                organisation_id=kwargs["organisation_id"],
                loan_id=kwargs["loan_id"],
                recognised_at=kwargs["recognised_at"],
                contractual_due_on=due_on,
            )
        return self.ledger.levy_service_fee(monthly_cents=reduced, **kwargs)

    def charge_cents_for_levy(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        bucket: str,
        cents: int,
    ) -> int:
        if bucket == "service":
            message = "The monthly service fee is levied with the service-fee method."
            try:
                day = value_date(recognised_at)
            except CalculationInputError as exc:
                raise RateFeeChangeError("timestamp-naive", _TIMESTAMP) from exc
            self._audit_use_failure(
                organisation_id, loan_id, recognised_at, day, "levy", "fee-type", message
            )
            wrapped = RateFeeChangeError("fee-type", message, loan_ids=(loan_id,))
            wrapped.audited = True
            raise wrapped
        return self._fee_amount(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            fee_type=bucket,
            contractual_cents=cents,
        )

    def levy_charge(self, **kwargs):
        cents = kwargs.pop("cents")
        bucket = kwargs["bucket"]
        due_on = kwargs.get("due_on")
        reduced = self.charge_cents_for_levy(
            organisation_id=kwargs["organisation_id"],
            loan_id=kwargs["loan_id"],
            recognised_at=kwargs["recognised_at"],
            bucket=bucket,
            cents=cents,
        )
        if isinstance(due_on, date):
            kwargs["due_on"] = self.fee_due_on(
                organisation_id=kwargs["organisation_id"],
                loan_id=kwargs["loan_id"],
                recognised_at=kwargs["recognised_at"],
                contractual_due_on=due_on,
            )
        return self.ledger.levy_charge(cents=reduced, **kwargs)

    def _apply(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        recognition: date,
        notice_date: date | None,
        effective_date: date | None,
        end_date: date | None,
        periodic_rate: object,
        fees_cents: object,
        fee_payment_frequency: str | None,
        fee_payment_time: date | None,
        selector: str,
        loan_ids: tuple[str, ...],
        contractual_fees_cents: dict[str, dict[str, int]],
        extra_holidays: frozenset[date],
        repos: tuple,
        notice_business_days: int | None,
    ) -> Outcome:
        if notice_business_days not in (None, NOTICE_BUSINESS_DAYS):
            raise RateFeeChangeError(
                "notice-days",
                "The five-business-day period is section 104(2). It is not a client election. "
                "The change was not applied.",
                loan_ids=loan_ids,
            )
        if notice_date is None:
            raise RateFeeChangeError(
                "notice-missing",
                "Section 104(2) needs the date of the written notice. "
                "No notice date was stored, so the change was not applied.",
                loan_ids=loan_ids,
            )
        if effective_date is None:
            raise RateFeeChangeError(
                "effective-missing",
                "The change needs the recognition date it takes effect. "
                "That date is 00:00 Africa/Johannesburg. Nothing was applied.",
                loan_ids=loan_ids,
            )
        if end_date is not None and end_date < effective_date:
            raise RateFeeChangeError(
                "end-before-effective",
                f"The end date {end_date.isoformat()} is before the effective date "
                f"{effective_date.isoformat()}. The change was not applied.",
                loan_ids=loan_ids,
            )
        earliest = earliest_effective_date(notice_date, extra_holidays)
        if effective_date < earliest:
            raise RateFeeChangeError(
                "notice-short",
                f"Section 104(2) needs at least five business days after {notice_date.isoformat()} "
                f"before the change takes effect. The earliest recognition date is "
                f"{earliest.isoformat()}. {effective_date.isoformat()} is too soon, "
                "so the change was not applied.",
                loan_ids=loan_ids,
            )
        rate = _rate(periodic_rate)
        fees = _fees(fees_cents)
        self._payment_fields(fee_payment_frequency, fee_payment_time, effective_date, end_date, loan_ids)
        if rate is None and not fees and fee_payment_frequency is None and fee_payment_time is None:
            raise RateFeeChangeError(
                "no-change",
                "The request does not reduce or zero a rate or fee and does not change "
                "the frequency or time of payment. Nothing was applied.",
                loan_ids=loan_ids,
            )
        accounts = self._select(organisation_id, selector, loan_ids)
        ids = tuple(account.loan_id for account in accounts)
        originals = self._original_fees(contractual_fees_cents, ids, fees)
        prepared: list[AccountRateFee] = []
        before: dict[str, dict] = {}
        after: dict[str, dict] = {}
        for account in accounts:
            self._account_can_change(account, effective_date, end_date, ids)
            contractual = self._contractual_rate(account, effective_date, repos, ids)
            self._rate_is_reduction(account.loan_id, contractual, rate, ids)
            self._fees_are_reductions(account.loan_id, originals.get(account.loan_id, {}), fees, ids)
            self._no_posted_conflict(account, effective_date, end_date, rate, fees, fee_payment_time, fee_payment_frequency, ids)
            self._no_overlap(organisation_id, account.loan_id, effective_date, end_date, ids)
            instalments = _instalments(account)
            record = AccountRateFee(
                change_id="",
                organisation_id=organisation_id,
                loan_id=account.loan_id,
                contractual_periodic_rate=contractual,
                contractual_base_rate=account.snapshot.base_rate,
                contractual_discount_rate=account.snapshot.discount_rate,
                contractual_fees_cents=dict(originals.get(account.loan_id, {})),
                contractual_end=account.contractual_end,
                contractual_instalments=instalments,
                payment_frequency=account.payment_frequency,
                applied_by=actor_id,
                applied_at=recognised_at,
            )
            prepared.append(record)
            before[account.loan_id] = _before_payload(account, contractual, record.contractual_fees_cents)
            after[account.loan_id] = _after_payload(
                contractual, record.contractual_fees_cents, rate, fees, fee_payment_frequency, fee_payment_time, account
            )
            if (
                account.contractual_end != record.contractual_end
                or account.payment_frequency != record.payment_frequency
                or _instalments(account) != instalments
            ):
                raise RateFeeChangeError(
                    "restructure",
                    "Changing the contractual term or the contractual instalment is a restructure. "
                    "This action does not change them.",
                    loan_ids=ids,
                )
        change_id = str(uuid4())
        change = RateFeeChange(
            change_id=change_id,
            organisation_id=organisation_id,
            notice_date=notice_date,
            effective_date=effective_date,
            end_date=end_date,
            periodic_rate=rate,
            fees_cents=dict(fees),
            fee_payment_frequency=fee_payment_frequency,
            fee_payment_time=fee_payment_time,
            notice_business_days=NOTICE_BUSINESS_DAYS,
            created_by=actor_id,
            created_at=recognised_at,
        )
        for record in prepared:
            record.change_id = change_id
        self._changes[(organisation_id, change_id)] = change
        for record in prepared:
            self._accounts[(organisation_id, change_id, record.loan_id)] = record
        message = _apply_confirmation(change, len(ids))
        outcome = Outcome(
            True,
            "applied",
            message,
            200,
            change_id,
            ids,
            notice_date,
            effective_date,
            end_date,
            recognition,
        )
        outcome_before_after = (before, after)
        self._pending_audit[id(outcome)] = outcome_before_after
        return outcome

    def _end(
        self,
        *,
        organisation_id: str,
        change_id: str,
        actor_id: str,
        recognised_at: datetime,
        end_date: date | None,
    ) -> Outcome:
        change = self._changes.get((organisation_id, change_id))
        if change is None:
            raise RateFeeChangeError(
                "change-unknown",
                "No rate or fee change with that id is stored for this organisation.",
            )
        ids = self._loan_ids(organisation_id, change_id)
        if end_date is None:
            raise RateFeeChangeError(
                "end-missing",
                "Ending a rate or fee change needs the last recognition date of the new values. "
                "Nothing was changed.",
                loan_ids=ids,
            )
        if end_date < change.effective_date:
            raise RateFeeChangeError(
                "end-before-effective",
                f"The end date {end_date.isoformat()} is before the effective date "
                f"{change.effective_date.isoformat()}. The end date was not stored.",
                loan_ids=ids,
            )
        if change.end_date is not None and end_date > change.end_date:
            raise RateFeeChangeError(
                "end-extends",
                "Moving the end date later extends the reduced rate or fee. That is a further "
                "change and this command does not carry a section 104(2) notice. "
                "The end date was not moved.",
                loan_ids=ids,
            )
        if change.end_date == end_date:
            raise RateFeeChangeError(
                "no-change",
                "The end date is already that recognition date. Nothing was changed.",
                loan_ids=ids,
            )
        removed_from = end_date + timedelta(days=1)
        for loan_id in ids:
            account = self.ledger.store.get(organisation_id, loan_id)
            if end_date > account.contractual_end:
                raise RateFeeChangeError(
                    "outside-term",
                    f"Loan {loan_id} ends on {account.contractual_end.isoformat()}. "
                    "The rate or fee change cannot run past the contractual end.",
                    loan_ids=ids,
                )
            self._no_posted_conflict(
                account,
                removed_from,
                change.end_date,
                change.periodic_rate,
                change.fees_cents,
                change.fee_payment_time,
                change.fee_payment_frequency,
                ids,
            )
        previous = change.end_date
        change.end_date = end_date
        change.ended_by = actor_id
        change.ended_at = recognised_at
        message = (
            f"Rate or fee change {change_id} ends on {end_date.isoformat()}. "
            "The new values apply on that date. The original rate and fees resume on the "
            f"next recognition date. Ended by {actor_id}."
        )
        outcome = Outcome(
            True,
            "ended",
            message,
            200,
            change_id,
            ids,
            change.notice_date,
            change.effective_date,
            end_date,
            value_date(recognised_at),
        )
        self._pending_audit[id(outcome)] = (
            {"end_date": None if previous is None else previous.isoformat()},
            {"end_date": end_date.isoformat()},
        )
        self._end_rollback[id(outcome)] = (change, previous)
        return outcome

    def _select(
        self,
        organisation_id: str,
        selector: str,
        loan_ids: tuple[str, ...],
    ) -> tuple[LoanAccount, ...]:
        if selector == "product":
            raise RateFeeChangeError(
                "product-unsupported",
                "The ledger does not store a product code, and no rule says which product set wins. "
                "Select the organisation or an explicit list of loans.",
                loan_ids=loan_ids,
            )
        if selector == "organisation":
            if loan_ids:
                raise RateFeeChangeError(
                    "selector",
                    "An organisation selection cannot also carry a loan list. "
                    "Send one selector. Nothing was applied.",
                    loan_ids=loan_ids,
                )
            accounts = tuple(
                account
                for account in self.ledger.store.accounts_for(organisation_id)
                if account.instrument_kind == "loan"
            )
            if not accounts:
                raise RateFeeChangeError(
                    "no-accounts",
                    "No granted loan is stored for this organisation. Nothing was applied.",
                )
            return accounts
        if selector != "loans":
            raise RateFeeChangeError(
                "selector",
                "The selector must be organisation or loans. Nothing was applied.",
                loan_ids=loan_ids,
            )
        if not loan_ids:
            raise RateFeeChangeError(
                "no-accounts",
                "A loan selection needs at least one loan id. Nothing was applied.",
            )
        if len(loan_ids) != len(set(loan_ids)):
            raise RateFeeChangeError(
                "loan-duplicate",
                "The loan list repeats an id. Nothing was applied.",
                loan_ids=loan_ids,
            )
        found: list[LoanAccount] = []
        for loan_id in loan_ids:
            try:
                account = self.ledger.store.get(organisation_id, loan_id)
            except LedgerError as exc:
                raise RateFeeChangeError(
                    "loan-unknown",
                    f"No loan {loan_id} is visible for this organisation. Nothing was applied.",
                    loan_ids=loan_ids,
                ) from exc
            if account.instrument_kind != "loan":
                raise RateFeeChangeError(
                    "not-a-loan",
                    f"{loan_id} is not a loan account. The change was not applied.",
                    loan_ids=loan_ids,
                )
            found.append(account)
        return tuple(found)

    def _account_can_change(
        self,
        account: LoanAccount,
        effective_date: date,
        end_date: date | None,
        loan_ids: tuple[str, ...],
    ) -> None:
        if account.snapshot.classification in _ZERO_COST:
            raise RateFeeChangeError(
                "zero-cost",
                f"Loan {account.loan_id} is zero-cost and cannot take a rate or fee. "
                "The change was not applied.",
                loan_ids=loan_ids,
            )
        if account.disbursement_value_date is None:
            raise RateFeeChangeError(
                "not-disbursed",
                f"Loan {account.loan_id} has not been granted, so it has no accrual date. "
                "The change was not applied.",
                loan_ids=loan_ids,
            )
        if effective_date < account.disbursement_value_date or effective_date > account.contractual_end:
            raise RateFeeChangeError(
                "outside-term",
                f"Loan {account.loan_id} accrues from {account.disbursement_value_date.isoformat()} "
                f"through {account.contractual_end.isoformat()}. "
                f"{effective_date.isoformat()} is outside that term. The change was not applied.",
                loan_ids=loan_ids,
            )
        if end_date is not None and end_date > account.contractual_end:
            raise RateFeeChangeError(
                "outside-term",
                f"Loan {account.loan_id} ends on {account.contractual_end.isoformat()}. "
                "The rate or fee change cannot run past the contractual end.",
                loan_ids=loan_ids,
            )

    def _contractual_rate(
        self,
        account: LoanAccount,
        effective_date: date,
        repos: tuple,
        loan_ids: tuple[str, ...],
    ) -> Decimal:
        try:
            return self.ledger.contractual_periodic_rate(
                organisation_id=account.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(effective_date),
                repos=repos,
            )
        except (LedgerError, RuleError) as exc:
            raise RateFeeChangeError(exc.code, str(exc), loan_ids=loan_ids) from exc

    def _rate_is_reduction(
        self,
        loan_id: str,
        contractual: Decimal,
        rate: Decimal | None,
        loan_ids: tuple[str, ...],
    ) -> None:
        if rate is None:
            return
        if rate > contractual:
            raise RateFeeChangeError(
                "rate-increase",
                f"Section 104(1) prohibits a unilateral increase of the interest rate. "
                f"The contractual periodic rate on {loan_id} is {contractual}. "
                f"{rate} is higher, so the change was not applied.",
                loan_ids=loan_ids,
            )
        if rate == contractual:
            raise RateFeeChangeError(
                "rate-not-reduced",
                f"A rate change has to reduce or zero the rate. {rate} is not below the "
                f"contractual periodic rate {contractual} on {loan_id}. The change was not applied.",
                loan_ids=loan_ids,
            )

    def _fees_are_reductions(
        self,
        loan_id: str,
        originals: dict[str, int],
        fees: dict[str, int],
        loan_ids: tuple[str, ...],
    ) -> None:
        for fee_type, new_cents in fees.items():
            if fee_type not in originals:
                raise RateFeeChangeError(
                    "fee-not-stored",
                    f"The contractual {fee_type} fee for {loan_id} was not supplied. "
                    "The ledger does not store it, so the original cannot be kept for disclosure. "
                    "The change was not applied.",
                    loan_ids=loan_ids,
                )
            original = originals[fee_type]
            if new_cents > original:
                raise RateFeeChangeError(
                    "fee-increase",
                    f"Section 104(1) prohibits a unilateral increase of the {fee_type} fee. "
                    f"The stored contractual amount on {loan_id} is {original} cents. "
                    f"{new_cents} cents is higher, so the change was not applied.",
                    loan_ids=loan_ids,
                )
            if new_cents == original:
                raise RateFeeChangeError(
                    "fee-not-reduced",
                    f"A fee change has to reduce or zero the {fee_type} fee. "
                    f"{new_cents} cents is not below the contractual {original} cents on {loan_id}. "
                    "The change was not applied.",
                    loan_ids=loan_ids,
                )

    def _no_overlap(
        self,
        organisation_id: str,
        loan_id: str,
        effective_date: date,
        end_date: date | None,
        loan_ids: tuple[str, ...],
    ) -> None:
        proposed = RateFeeChange(
            change_id="",
            organisation_id="",
            notice_date=effective_date,
            effective_date=effective_date,
            end_date=end_date,
            periodic_rate=None,
            fees_cents={},
            fee_payment_frequency=None,
            fee_payment_time=None,
            notice_business_days=NOTICE_BUSINESS_DAYS,
            created_by="",
            created_at=value_instant(effective_date),
        )
        for (org, _change_id, stored_loan), record in self._accounts.items():
            if org != organisation_id or stored_loan != loan_id:
                continue
            existing = self._changes.get((record.organisation_id, record.change_id))
            if existing is not None and _overlaps(existing, proposed):
                raise RateFeeChangeError(
                    "change-overlap",
                    f"Another rate or fee change already covers {loan_id} on an overlapping "
                    "recognition date. No precedence is locked, so nothing was applied.",
                    loan_ids=loan_ids,
                )

    def _no_posted_conflict(
        self,
        account: LoanAccount,
        start: date,
        end: date | None,
        rate: Decimal | None,
        fees: dict[str, int],
        fee_payment_time: date | None,
        fee_payment_frequency: str | None,
        loan_ids: tuple[str, ...],
    ) -> None:
        if rate is not None:
            for transaction in self.ledger.store.transactions_for(account.organisation_id, account.loan_id):
                if transaction.kind != "interest_accrual":
                    continue
                if _in_window(transaction.value_date, start, end):
                    raise RateFeeChangeError(
                        "accrual-already-posted",
                        f"Interest was already accrued on {account.loan_id} for "
                        f"{transaction.value_date.isoformat()}, which falls in this change. "
                        "Posted accruals are not restated. Nothing was stored.",
                        loan_ids=loan_ids,
                    )
        moves_payment = fee_payment_time is not None or fee_payment_frequency is not None
        if not fees and not moves_payment:
            return
        for charge in account.charges:
            if charge.bucket not in fees and not moves_payment:
                continue
            if _in_window(charge.levied_on, start, end):
                raise RateFeeChangeError(
                    "fee-already-levied",
                    f"A {charge.bucket} fee was already levied on {account.loan_id} for "
                    f"{charge.levied_on.isoformat()}. Posted fees are not restated. "
                    "Nothing was stored.",
                    loan_ids=loan_ids,
                )

    def _payment_fields(
        self,
        frequency: str | None,
        payment_time: date | None,
        effective_date: date,
        end_date: date | None,
        loan_ids: tuple[str, ...],
    ) -> None:
        if frequency is None and payment_time is None:
            return
        if frequency is not None and frequency not in FREQUENCIES:
            raise RateFeeChangeError(
                "frequency-unsupported",
                f"{frequency} is not a locked payment frequency. The change was not applied.",
                loan_ids=loan_ids,
            )
        if frequency is not None and payment_time is None:
            raise RateFeeChangeError(
                "payment-time-missing",
                "A change to the payment frequency needs fee_payment_time, the first "
                "Johannesburg date the fee is due. The lock does not name another anchor. "
                "The change was not applied.",
                loan_ids=loan_ids,
            )
        if payment_time is None:
            return
        if payment_time < effective_date or (end_date is not None and payment_time > end_date):
            raise RateFeeChangeError(
                "payment-time",
                "fee_payment_time must fall on or after the effective date and not after the end date. "
                "A clock time is not a recognition date. The change was not applied.",
                loan_ids=loan_ids,
            )

    def _original_fees(
        self,
        supplied: dict[str, dict[str, int]],
        loan_ids: tuple[str, ...],
        fees: dict[str, int],
    ) -> dict[str, dict[str, int]]:
        parsed: dict[str, dict[str, int]] = {}
        for loan_id, raw in supplied.items():
            parsed[loan_id] = _fees(raw)
        if fees:
            for loan_id in loan_ids:
                if loan_id not in parsed:
                    raise RateFeeChangeError(
                        "fee-not-stored",
                        f"The contractual fees for {loan_id} were not supplied. "
                        "The ledger does not store them. The change was not applied.",
                        loan_ids=loan_ids,
                    )
        return parsed

    def _override(
        self,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        day: date,
        repos: tuple,
    ) -> Decimal | None:
        change = self._covering(organisation_id, loan_id, day)
        if change is None or change.periodic_rate is None:
            return None
        contractual = self.ledger.contractual_periodic_rate(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            repos=repos,
        )
        if change.periodic_rate > contractual:
            raise RateFeeChangeError(
                "rate-increase",
                f"Section 104(1) prohibits a unilateral increase of the interest rate. "
                f"The contractual periodic rate on {day.isoformat()} is {contractual}. "
                f"The stored rate {change.periodic_rate} is higher, so interest was not accrued.",
                loan_ids=(loan_id,),
            )
        return change.periodic_rate

    def _fee_amount(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        fee_type: str,
        contractual_cents: int,
    ) -> int:
        try:
            day = value_date(recognised_at)
        except CalculationInputError as exc:
            raise RateFeeChangeError("timestamp-naive", _TIMESTAMP) from exc
        try:
            if fee_type not in FEE_TYPES:
                raise RateFeeChangeError(
                    "fee-type",
                    f"{fee_type} is not a fee type on the ledger. The levy was not posted.",
                )
            change = self._covering(organisation_id, loan_id, day)
            if change is None or fee_type not in change.fees_cents:
                return contractual_cents
            return self._reduced_fee(change, organisation_id, loan_id, fee_type, contractual_cents)
        except RateFeeChangeError as exc:
            self._audit_use_failure(
                organisation_id, loan_id, recognised_at, day, "levy", exc.code, str(exc)
            )
            exc.audited = True
            raise

    def _reduced_fee(
        self,
        change: RateFeeChange,
        organisation_id: str,
        loan_id: str,
        fee_type: str,
        contractual_cents: int,
    ) -> int:
        record = self._accounts.get((organisation_id, change.change_id, loan_id))
        stored = None if record is None else record.contractual_fees_cents.get(fee_type)
        if stored is None:
            raise RateFeeChangeError(
                "fee-not-stored",
                f"The contractual {fee_type} fee was not stored for loan {loan_id}. The levy was not posted.",
                loan_ids=(loan_id,),
            )
        if not isinstance(contractual_cents, int) or isinstance(contractual_cents, bool):
            raise RateFeeChangeError(
                "fee-cents",
                f"The {fee_type} levy must be an integer number of cents. The levy was not posted.",
                loan_ids=(loan_id,),
            )
        if contractual_cents != stored:
            raise RateFeeChangeError(
                "fee-mismatch",
                f"The levy amount is {contractual_cents} cents. The contractual {fee_type} fee "
                f"stored for loan {loan_id} is {stored} cents. The levy was not posted.",
                loan_ids=(loan_id,),
            )
        return change.fees_cents[fee_type]

    def _due_allowed(self, change: RateFeeChange, due_on: date) -> bool:
        if due_on < change.effective_date:
            return False
        if change.end_date is not None and due_on > change.end_date:
            return False
        if change.fee_payment_time is None:
            return True
        if change.fee_payment_frequency is None:
            return due_on == change.fee_payment_time
        cursor = change.fee_payment_time
        for _step in range(_DUE_WALK_LIMIT):
            if cursor == due_on:
                return True
            if cursor > due_on:
                return False
            try:
                cursor = next_due_date(cursor, change.fee_payment_frequency)
            except LedgerError as exc:
                raise RateFeeChangeError(exc.code, str(exc)) from exc
        raise RateFeeChangeError(
            "payment-time-unbounded",
            "The fee payment dates could not be walked to the levy date. The levy was not posted.",
        )

    def _covering(self, organisation_id: str, loan_id: str, day: date) -> RateFeeChange | None:
        found: list[RateFeeChange] = []
        for (org, change_id, stored_loan), _record in self._accounts.items():
            if org != organisation_id or stored_loan != loan_id:
                continue
            change = self._changes.get((org, change_id))
            if change is not None and _covers(change, day):
                found.append(change)
        if not found:
            return None
        if len(found) > 1:
            raise RateFeeChangeError(
                "change-overlap",
                f"More than one rate or fee change covers {loan_id} on {day.isoformat()}. "
                "No precedence is locked, so the value was not used.",
                loan_ids=(loan_id,),
            )
        return found[0]

    def _loan_ids(self, organisation_id: str, change_id: str) -> tuple[str, ...]:
        return tuple(
            loan_id
            for (org, stored_change, loan_id) in self._accounts
            if org == organisation_id and stored_change == change_id
        )

    def _recognition(self, recognised_at: datetime) -> date | None:
        try:
            return value_date(recognised_at)
        except CalculationInputError:
            return None

    def _naive(self, loan_ids: tuple[str, ...]) -> Outcome:
        return Outcome(False, "timestamp-naive", _TIMESTAMP, 422, loan_ids=loan_ids)

    def _seal(
        self,
        outcome: Outcome,
        organisation_id: str,
        recognised_at: datetime,
        recognition: date,
        actor_id: str,
        action: str,
    ) -> bool:
        before, after = self._pending_audit.pop(id(outcome), (None, None))
        try:
            self._audit_outcome(
                organisation_id=organisation_id,
                recognised_at=recognised_at,
                recognition=recognition,
                actor_id=actor_id,
                action=action,
                ok=True,
                code=outcome.code,
                message=outcome.message,
                change_id=outcome.change_id,
                loan_ids=outcome.loan_ids,
                notice_date=outcome.notice_date,
                effective_date=outcome.effective_date,
                end_date=outcome.end_date,
                before=before,
                after=after,
            )
        except RegulatoryError:
            self._rollback(outcome)
            return False
        else:
            self._end_rollback.pop(id(outcome), None)
            return True

    def _rollback(self, outcome: Outcome) -> None:
        if outcome.change_id is None:
            return
        ended = self._end_rollback.pop(id(outcome), None)
        if ended is not None:
            change, previous = ended
            change.end_date = previous
            change.ended_by = None
            change.ended_at = None
            return
        organisation_id = ""
        for (org, change_id) in list(self._changes):
            if change_id == outcome.change_id:
                organisation_id = org
                del self._changes[(org, change_id)]
        for key in list(self._accounts):
            if key[0] == organisation_id and key[1] == outcome.change_id:
                del self._accounts[key]

    def _audit_failed(self, outcome: Outcome, organisation_id: str) -> Outcome:
        return Outcome(
            False,
            "audit",
            "The audit log rejected the row. The change was not applied.",
            422,
            loan_ids=outcome.loan_ids,
            notice_date=outcome.notice_date,
            effective_date=outcome.effective_date,
            end_date=outcome.end_date,
            recognition_date=outcome.recognition_date,
        )

    def _audit_outcome(
        self,
        *,
        organisation_id: str,
        recognised_at: datetime,
        recognition: date,
        actor_id: str,
        action: str,
        ok: bool,
        code: str,
        message: str,
        change_id: str | None,
        loan_ids: tuple[str, ...],
        notice_date: date | None,
        effective_date: date | None,
        end_date: date | None,
        before: dict | None,
        after: dict | None,
    ) -> None:
        if not organisation_id or recognised_at.tzinfo is None:
            return
        self.audit.append(
            organisation_id=organisation_id,
            occurred_at=recognised_at,
            event_type=EVENT,
            category="operational",
            enigma_person_id=actor_id or None,
            payload={
                "outcome": "success" if ok else "failure",
                "action": action,
                "reason": None if ok else code,
                "code": code,
                "message": message,
                "change_id": change_id,
                "actor_id": actor_id,
                "recognition_date": recognition.isoformat(),
                "notice_date": None if notice_date is None else notice_date.isoformat(),
                "effective_date": None if effective_date is None else effective_date.isoformat(),
                "end_date": None if end_date is None else end_date.isoformat(),
                "notice_business_days": NOTICE_BUSINESS_DAYS,
                "loan_ids": list(loan_ids),
                "before": before,
                "after": after,
            },
        )

    def _audit_use_failure(
        self,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        recognition: date,
        action: str,
        code: str,
        message: str,
    ) -> None:
        self._audit_outcome(
            organisation_id=organisation_id,
            recognised_at=recognised_at,
            recognition=recognition,
            actor_id="",
            action=action,
            ok=False,
            code=code,
            message=message,
            change_id=None,
            loan_ids=(loan_id,),
            notice_date=None,
            effective_date=None,
            end_date=None,
            before=None,
            after=None,
        )


def _in_window(day: date, start: date, end: date | None) -> bool:
    if day < start:
        return False
    if end is not None and day > end:
        return False
    return True


def _moves_payment(change: RateFeeChange) -> bool:
    return change.fee_payment_frequency is not None or change.fee_payment_time is not None


def _before_payload(account: LoanAccount, contractual: Decimal, fees: dict[str, int]) -> dict:
    return {
        "periodic_rate": str(contractual),
        "base_rate": str(account.snapshot.base_rate),
        "discount_rate": str(account.snapshot.discount_rate),
        "fees_cents": dict(fees),
        "payment_frequency": account.payment_frequency,
        "contractual_end": account.contractual_end.isoformat(),
        "instalments": [
            {"due_on": due.isoformat(), "amount_cents": amount}
            for due, amount in _instalments(account)
        ],
    }


def _after_payload(
    contractual: Decimal,
    fees: dict[str, int],
    rate: Decimal | None,
    new_fees: dict[str, int],
    frequency: str | None,
    payment_time: date | None,
    account: LoanAccount,
) -> dict:
    used = dict(fees)
    used.update(new_fees)
    return {
        "periodic_rate": str(contractual if rate is None else rate),
        "fees_cents": used,
        "fee_payment_frequency": frequency,
        "fee_payment_time": None if payment_time is None else payment_time.isoformat(),
        "payment_frequency": account.payment_frequency,
        "contractual_end": account.contractual_end.isoformat(),
        "instalments": [
            {"due_on": due.isoformat(), "amount_cents": amount}
            for due, amount in _instalments(account)
        ],
    }


def _apply_confirmation(change: RateFeeChange, count: int) -> str:
    noun = "account" if count == 1 else "accounts"
    text = (
        f"Rate or fee change {change.change_id} applies to {count} {noun} from "
        f"{change.effective_date.isoformat()} at 00:00 Africa/Johannesburg. "
        f"Section 104(2) notice date {change.notice_date.isoformat()}. "
        f"Applied by {change.created_by}. "
        "The contractual term and instalment were not changed."
    )
    if change.end_date is None:
        return (
            text
            + " No end date is set, so the new rate and fees continue until an end date is stored."
        )
    return (
        text
        + f" The new values apply on {change.end_date.isoformat()} and the original rate and fees "
        "resume on the next recognition date."
    )
