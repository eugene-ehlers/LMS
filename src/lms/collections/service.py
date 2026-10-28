"""Collections, arrears, write-off, and prescription.

Layer 0 calculates, posts, and resolves elections. This module decides when
those calls run. It does not keep a second interest, allocation, or ceiling
formula.

LOCKED_DECISIONS.md (28 October 2026) is the source of truth. A conflict
with that file is named in docs/collections/implementation-note.md and is
not given a private rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import timedelta
from typing import Callable
from uuid import uuid4

from lms.collections.authority import RandCeiling, authorise_write_off
from lms.collections.errors import CollectionsError
from lms.ledger.errors import LedgerError
from lms.ledger.models import LoanAccount
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import PaymentRecord, Servicing, _fingerprint, _threshold_instalment
from lms_config.calendar import value_date
from lms_config.exceptions import CalculationInputError
from lms_config.locked import (
    TRIGGER_COLLECTIONS_DEFAULT,
    TRIGGER_CONTRACTUAL_BREACH,
    is_full_payment,
    is_in_default,
    resolve_in_duplum_trigger,
    resolve_residual_threshold_cents,
)

# The Enigma port sketch. Decision 15 does not name this action.
WRITE_OFF_ACTION = "lms.account.write_off"

ProvisionFormula = Callable[["ProvisionFacts"], int]
PrescriptionFormula = Callable[["ProvisionFacts"], bool]


@dataclass(frozen=True)
class ProvisionFacts:
    """Ledger-derived facts a caller-supplied formula may read.

    Promise-to-pay and contactability are not fields. The collections
    system owns them. This layer does not score the facts.
    """

    arrears_cents: int
    recency_days: int
    months_on_book: int
    as_of: date


@dataclass
class Case:
    agreement_id: str
    trigger: str
    residual_threshold_cents: int
    provision_mode: str | None = None
    prescription_mode: str | None = None
    breaches: set[date] = field(default_factory=set)
    episode_due_on: date | None = None
    prescription_review: bool = False
    provision_cents: int | None = None
    written_off: bool = False
    prescription_signals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CollectionsView:
    agreement_id: str
    trigger: str
    contractual_breaches: tuple[date, ...]
    collections_default: bool
    open_episode_ceiling: int | None
    episode_count: int
    discount_fallen_away: bool
    prescription_review: bool
    provision_cents: int | None
    written_off: bool
    residual_threshold_cents: int


class Collections:
    def __init__(self, servicing: Servicing) -> None:
        self.servicing = servicing
        self.cases: dict[str, Case] = {}

    def bind(
        self,
        agreement_id: str,
        *,
        in_duplum_trigger: str | None,
        product_in_duplum_trigger: str | None = None,
        residual_threshold_cents: int | None = None,
        product_residual_threshold_cents: int | None = None,
        provision_mode: str | None = None,
        prescription_mode: str | None = None,
    ) -> CollectionsView:
        """Copy the §19 elections onto the agreement. A second bind is refused.

        The ledger snapshot does not carry these two elections. Binding here
        is the collections copy. It does not post. The agreement may still
        be pending disbursement: the view then has no episode. A failed
        check does not store the case, so a later bind is not refused
        because an earlier attempt ran before disbursement. A second bind
        after a successful copy is still elections-frozen.
        """
        if agreement_id in self.cases:
            raise CollectionsError(
                "elections-frozen",
                "LOCKED_DECISIONS §19 copies elections onto the agreement. "
                "A later bind does not rewrite them.",
            )
        self.servicing._agreement(agreement_id)
        try:
            trigger = resolve_in_duplum_trigger(in_duplum_trigger, product_in_duplum_trigger)
        except CalculationInputError as exc:
            raise CollectionsError("trigger-unset", str(exc)) from exc
        try:
            threshold = resolve_residual_threshold_cents(
                residual_threshold_cents,
                product_residual_threshold_cents,
            )
        except CalculationInputError as exc:
            raise CollectionsError("residual-threshold-unset", str(exc)) from exc
        if provision_mode not in {None, "manual", "formula"}:
            raise CollectionsError(
                "provision-mode-unset",
                "LOCKED_DECISIONS §8: provision is manual or formula-based. "
                "Any other value fails closed.",
            )
        if prescription_mode not in {None, "manual", "formula"}:
            raise CollectionsError(
                "prescription-mode-unset",
                "LOCKED_DECISIONS §20: prescription is manual or formula-based. "
                "There is no platform default.",
            )
        self.cases[agreement_id] = Case(
            agreement_id=agreement_id,
            trigger=trigger,
            residual_threshold_cents=threshold,
            provision_mode=provision_mode,
            prescription_mode=prescription_mode,
        )
        return self.view(agreement_id)

    def observe(self, agreement_id: str, *, recognised_at: datetime) -> CollectionsView:
        """Record breach and collections default, then open or close in duplum.

        Call this after the day's receipts are posted. §1 capitalises first
        and allocates next; this method does not accrue and does not allocate.
        A contractual breach, once recorded, stays until a system-error correction.
        """
        case = self._case(agreement_id)
        if case.prescription_review or case.written_off:
            return self.view(agreement_id, recognised_at)
        record = self.servicing._agreement(agreement_id)
        if record.disbursement_value_date is None:
            raise CollectionsError("status", "The agreement has not been disbursed.")
        account = self._loan(record)
        check_on = value_date(recognised_at)
        self._record_breaches(case, account, check_on)
        defaulted = self._collections_default(account, check_on)
        self._apply_trigger(case, record, account, check_on, recognised_at, defaulted)
        return self.view(agreement_id, recognised_at)

    def correct_system_error(
        self,
        agreement_id: str,
        due_on: date,
        *,
        recognised_at: datetime,
    ) -> CollectionsView:
        """§6. A system error is removed as if the breach never occurred.

        A later payment does not call this. The discount is not put back (§3).
        """
        case = self._case(agreement_id)
        if due_on not in case.breaches:
            raise CollectionsError(
                "breach-absent",
                "There is no contractual breach on that due date to correct.",
            )
        case.breaches.remove(due_on)
        record = self.servicing._agreement(agreement_id)
        account = self._loan(record)
        if (
            case.trigger == TRIGGER_CONTRACTUAL_BREACH
            and case.episode_due_on == due_on
            and not case.breaches
            and _open(account) is not None
        ):
            self.servicing.ledger.close_in_duplum_episode(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=recognised_at,
            )
            case.episode_due_on = None
        return self.view(agreement_id, recognised_at)

    def receive(
        self,
        *,
        organisation_id: str,
        person_id: str,
        cents: int,
        recognised_at: datetime,
        idempotency_key: str,
        agreement_id: str,
        attributed_due_on: date | None,
    ) -> PaymentRecord:
        """A receipt in prescription review stays unapplied. No refund is posted.

        Any other agreement uses Servicing.accept_payment, which posts through
        the ledger. Interest and fees are not stopped by a default flag (§6).
        """
        case = self._case(agreement_id)
        if not case.prescription_review:
            return self.servicing.accept_payment(
                organisation_id=organisation_id,
                person_id=person_id,
                cents=cents,
                recognised_at=recognised_at,
                idempotency_key=idempotency_key,
                agreement_id=agreement_id,
                attributed_due_on=attributed_due_on,
            )
        fingerprint = _fingerprint(
            {
                "organisation_id": organisation_id,
                "person_id": person_id,
                "cents": cents,
                "recognised_at": recognised_at.isoformat(),
                "agreement_id": agreement_id,
                "attributed_due_on": attributed_due_on.isoformat() if attributed_due_on else None,
                "prescription_review": True,
            }
        )
        replay = self.servicing._replay("payment", organisation_id, idempotency_key, fingerprint)
        if replay is not None:
            return self.servicing.payments[replay]
        self.servicing.enigma.check(organisation_id, person_id, "payment.accept")
        if cents < 0:
            raise CollectionsError("payment", "A receipt cannot be negative.")
        payment = PaymentRecord(
            payment_id=str(uuid4()),
            organisation_id=organisation_id,
            person_id=person_id,
            cents=cents,
            recognised_at=recognised_at,
            value_date=value_date(recognised_at),
            status="unapplied",
            agreement_id=agreement_id,
            attributed_due_on=attributed_due_on,
        )
        self.servicing.payments[payment.payment_id] = payment
        self.servicing._remember("payment", organisation_id, idempotency_key, fingerprint, payment.payment_id)
        return payment

    def propose_residual_write_off(
        self,
        agreement_id: str,
        *,
        recognised_at: datetime,
    ) -> CollectionsView:
        """§8. Not automatic. The caller has to invoke this.

        Considered only after the last schedule date, only when the schedule
        was paid exactly, only when no episode is open, and only when the
        outstanding position is within the client's threshold (R50 when unset).
        """
        case = self._case(agreement_id)
        record = self.servicing._agreement(agreement_id)
        account = self._loan(record)
        check_on = value_date(recognised_at)
        last_due = _last_schedule_date(account)
        if account.contractual_end != last_due:
            raise CollectionsError(
                "contractual-end-unset",
                "LOCKED_DECISIONS §8 says after the last instalment and §13 says "
                "at contractual end. Those dates differ on this loan, so the "
                "residual is not posted.",
            )
        if check_on <= last_due:
            raise CollectionsError(
                "residual-not-due",
                "LOCKED_DECISIONS §8: a residual write-off is considered after the last instalment.",
            )
        if _open(account) is not None:
            raise CollectionsError(
                "residual-episode-open",
                "A residual write-off is considered only when no in-duplum episode is open.",
            )
        if not _schedule_paid_exactly(self, account):
            raise CollectionsError(
                "residual-not-exact",
                "LOCKED_DECISIONS §8 reserves the small residual for an exact "
                "contractual instalment. An arrears balance uses the mandated write-off.",
            )
        outstanding = _outstanding_cents(self.servicing.ledger, account)
        if outstanding == 0:
            raise CollectionsError("write-off-zero", "There is no residual to write off.")
        if outstanding > case.residual_threshold_cents:
            raise CollectionsError(
                "residual-above-threshold",
                "The outstanding position is above the residual write-off threshold.",
            )
        self._post_write_off(record, recognised_at, outstanding)
        case.written_off = True
        record.status = "written_off"
        return self.view(agreement_id, recognised_at)

    def write_off(
        self,
        agreement_id: str,
        *,
        recognised_at: datetime,
        actor_id: str,
        amount_cents: int,
        platform: RandCeiling | None,
        company: RandCeiling | None = None,
        mandate_allowed: bool,
        access: EnigmaStub | None = None,
        action: str = WRITE_OFF_ACTION,
    ) -> CollectionsView:
        """Larger write-off. Mandate and operational ceiling, then one journal.

        The access check runs before the journal. A timeout, an ambiguous
        status, a suspended enrolment, a denied mandate, or an amount over
        the ceiling posts nothing (§15, §8).
        """
        case = self._case(agreement_id)
        record = self.servicing._agreement(agreement_id)
        account = self._loan(record)
        outstanding = _outstanding_cents(self.servicing.ledger, account)
        if amount_cents != outstanding:
            raise CollectionsError(
                "write-off-partial-unset",
                "LOCKED_DECISIONS §8 does not order a partial write-off. "
                "The amount has to be the full outstanding position.",
            )
        authorise_write_off(
            access or self.servicing.enigma,
            organisation_id=record.organisation_id,
            actor_id=actor_id,
            action=action,
            amount_cents=amount_cents,
            platform=platform,
            company=company,
            mandate_allowed=mandate_allowed,
        )
        self._post_write_off(record, recognised_at, amount_cents)
        case.written_off = True
        record.status = "written_off"
        return self.view(agreement_id, recognised_at)

    def record_provision(
        self,
        agreement_id: str,
        *,
        recognised_at: datetime,
        amount_cents: int | None = None,
        formula: ProvisionFormula | None = None,
    ) -> CollectionsView:
        """§8. Manual amount, or a caller-supplied formula over ledger facts.

        The formula is not given a promise-to-pay or a contactability score.
        The collections system keeps those. This method stores the resulting
        provision cents only.
        """
        case = self._case(agreement_id)
        if case.provision_mode is None:
            raise CollectionsError(
                "provision-mode-unset",
                "LOCKED_DECISIONS §8: provision is per client. No mode is stored, so nothing is raised.",
            )
        if case.provision_mode == "manual":
            if amount_cents is None or amount_cents < 0:
                raise CollectionsError(
                    "provision-amount-unset",
                    "A manual provision needs a non-negative amount in cents.",
                )
            case.provision_cents = amount_cents
            return self.view(agreement_id, recognised_at)
        if formula is None:
            raise CollectionsError(
                "provision-formula-unset",
                "LOCKED_DECISIONS §8 allows a formula. This layer does not supply one.",
            )
        facts = self._facts(agreement_id, recognised_at)
        scored = formula(facts)
        if scored < 0:
            raise CollectionsError("provision-amount-unset", "A provision cannot be negative.")
        case.provision_cents = scored
        return self.view(agreement_id, recognised_at)

    def open_prescription_review(
        self,
        agreement_id: str,
        *,
        recognised_at: datetime,
        formula: PrescriptionFormula | None = None,
        signal: str = "manual",
    ) -> CollectionsView:
        """§20. Manual or a client formula. No platform prescription clock.

        Opening the review does not refund a receipt already posted and does
        not allocate anything new.
        """
        case = self._case(agreement_id)
        if case.prescription_mode is None:
            raise CollectionsError(
                "prescription-mode-unset",
                "LOCKED_DECISIONS §20: prescription is per client. No platform default is applied.",
            )
        if case.prescription_mode == "formula":
            if formula is None:
                raise CollectionsError(
                    "prescription-formula-unset",
                    "LOCKED_DECISIONS §20 allows a formula. This layer does not supply one.",
                )
            facts = self._facts(agreement_id, recognised_at)
            if not formula(facts):
                return self.view(agreement_id, recognised_at)
            signal = "formula"
        case.prescription_review = True
        case.prescription_signals.append(signal)
        self.servicing._agreement(agreement_id).status = "prescription_review"
        return self.view(agreement_id, recognised_at)

    def view(self, agreement_id: str, recognised_at: datetime | None = None) -> CollectionsView:
        case = self._case(agreement_id)
        record = self.servicing._agreement(agreement_id)
        if record.disbursement_value_date is None:
            return CollectionsView(
                agreement_id=agreement_id,
                trigger=case.trigger,
                contractual_breaches=tuple(sorted(case.breaches)),
                collections_default=False,
                open_episode_ceiling=None,
                episode_count=0,
                discount_fallen_away=False,
                prescription_review=case.prescription_review,
                provision_cents=case.provision_cents,
                written_off=case.written_off,
                residual_threshold_cents=case.residual_threshold_cents,
            )
        account = self._loan(record)
        check_on = value_date(recognised_at) if recognised_at is not None else None
        defaulted = self._collections_default(account, check_on) if check_on is not None else False
        opened = _open(account)
        return CollectionsView(
            agreement_id=agreement_id,
            trigger=case.trigger,
            contractual_breaches=tuple(sorted(case.breaches)),
            collections_default=defaulted,
            open_episode_ceiling=opened.ceiling_cents if opened is not None else None,
            episode_count=len(account.episodes),
            discount_fallen_away=account.discount_fallen_away,
            prescription_review=case.prescription_review,
            provision_cents=case.provision_cents,
            written_off=case.written_off,
            residual_threshold_cents=case.residual_threshold_cents,
        )

    def _record_breaches(self, case: Case, account: LoanAccount, check_on: date) -> None:
        threshold = account.snapshot.full_payment_threshold_percent
        for due_on, _schedule_cents in _schedule(account):
            if check_on <= due_on or due_on in case.breaches:
                continue
            received = _received_on(self._payments(account), due_on, due_on)
            instalment = _threshold_instalment(account, due_on)
            if not is_full_payment(received, instalment, threshold):
                case.breaches.add(due_on)

    def _collections_default(self, account: LoanAccount, check_on: date) -> bool:
        threshold = account.snapshot.full_payment_threshold_percent
        leniency = account.snapshot.leniency_days
        for due_on, _schedule_cents in _schedule(account):
            received = _received_until(self._payments(account), due_on, check_on)
            instalment = _threshold_instalment(account, due_on)
            if is_in_default(
                due_on=due_on,
                value_date=check_on,
                leniency_days=leniency,
                received_cents=received,
                instalment_cents=instalment,
                threshold_percent=threshold,
            ):
                return True
        return False

    def _apply_trigger(
        self,
        case: Case,
        record,
        account: LoanAccount,
        check_on: date,
        recognised_at: datetime,
        defaulted: bool,
    ) -> None:
        ledger = self.servicing.ledger
        if case.trigger == TRIGGER_CONTRACTUAL_BREACH:
            if case.breaches and _open(account) is None:
                opening = min(case.breaches)
                fall = check_on >= opening + _leniency(account)
                ledger.open_in_duplum_episode(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=recognised_at,
                    fall_away=fall,
                )
                case.episode_due_on = opening
                self._audit_episode(record, recognised_at, "opened")
            elif case.episode_due_on is not None and check_on >= case.episode_due_on + _leniency(account):
                ledger.mark_discount_fallen_away(
                    organisation_id=record.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=recognised_at,
                )
            return
        if case.trigger != TRIGGER_COLLECTIONS_DEFAULT:
            raise CollectionsError("trigger-unset", "The in-duplum trigger on this agreement is not a locked value.")
        if defaulted and _open(account) is None:
            ledger.open_in_duplum_episode(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=recognised_at,
                fall_away=True,
            )
            case.episode_due_on = check_on
            self._audit_episode(record, recognised_at, "opened")
            return
        if not defaulted and _open(account) is not None:
            ledger.close_in_duplum_episode(
                organisation_id=record.organisation_id,
                loan_id=account.loan_id,
                recognised_at=recognised_at,
            )
            self._audit_episode(record, recognised_at, "closed")

    def _facts(self, agreement_id: str, recognised_at: datetime) -> ProvisionFacts:
        record = self.servicing._agreement(agreement_id)
        account = self._loan(record)
        check_on = value_date(recognised_at)
        arrears = 0
        for due_on, schedule_cents in _schedule(account):
            if check_on < due_on:
                continue
            received = _received_until(self._payments(account), due_on, check_on)
            arrears += max(0, schedule_cents - received)
        last_paid = _last_payment_date(self._payments(account))
        anchor = last_paid or account.disbursement_value_date
        months = (check_on.year - account.disbursement_value_date.year) * 12 + (
            check_on.month - account.disbursement_value_date.month
        )
        return ProvisionFacts(
            arrears_cents=arrears,
            recency_days=(check_on - anchor).days,
            months_on_book=max(0, months),
            as_of=check_on,
        )

    def _post_write_off(self, record, recognised_at: datetime, amount_cents: int) -> None:
        if record.ledger_loan_id is None:
            raise CollectionsError("status", "The agreement has not been disbursed.")
        try:
            self.servicing.ledger.write_off_outstanding(
                organisation_id=record.organisation_id,
                loan_id=record.ledger_loan_id,
                recognised_at=recognised_at,
                amount_cents=amount_cents,
            )
        except LedgerError as exc:
            raise CollectionsError(exc.code, str(exc)) from exc

    def _payments(self, account: LoanAccount):
        rows = self.servicing.ledger.store.transactions_for(account.organisation_id, account.loan_id)
        reversed_ids = {item.reverses_transaction_id for item in rows if item.reverses_transaction_id}
        payments = [
            item
            for item in rows
            if item.kind == "payment" and item.transaction_id not in reversed_ids
        ]
        if any(item.attributed_due_on is None for item in payments):
            raise CollectionsError(
                "due-date-attribution-unset",
                "LOCKED_DECISIONS §6 compares the amount received for a due date. "
                "An unattributed receipt fails closed.",
            )
        return payments

    def _case(self, agreement_id: str) -> Case:
        case = self.cases.get(agreement_id)
        if case is None:
            raise CollectionsError(
                "trigger-unset",
                "LOCKED_DECISIONS §6 and §19: the in-duplum trigger is unset. "
                "The collections call fails closed.",
            )
        return case

    def _audit_episode(self, record, recognised_at: datetime, change: str) -> None:
        """Operational row. The caller that uses SQL inserts ``lms.audit_event``."""
        self.servicing.audit.append(
            organisation_id=record.organisation_id,
            occurred_at=recognised_at,
            event_type="AGREEMENT_STATUS_CHANGED",
            category="operational",
            agreement_id=record.agreement_id,
            enigma_person_id=record.person_id,
            payload={"in_duplum": change},
        )

    def _loan(self, record) -> LoanAccount:
        if record.ledger_loan_id is None:
            raise CollectionsError("status", "The agreement has not been disbursed.")
        return self.servicing.ledger.store.get(record.organisation_id, record.ledger_loan_id)


def _open(account: LoanAccount):
    for episode in account.episodes:
        if episode.closed_on is None:
            return episode
    return None


def _schedule(account: LoanAccount) -> tuple[tuple[date, int], ...]:
    if not account.schedule_versions:
        return ()
    return account.schedule_versions[-1].lines


def _last_schedule_date(account: LoanAccount) -> date:
    lines = _schedule(account)
    if not lines:
        raise CollectionsError("schedule", "The loan has no schedule.")
    return max(due for due, _amount in lines)


def _leniency(account: LoanAccount) -> timedelta:
    return timedelta(days=account.snapshot.leniency_days)


def _received_on(payments, due_on: date, day: date) -> int:
    return sum(
        item.amount_cents or 0
        for item in payments
        if item.attributed_due_on == due_on and item.value_date == day
    )


def _received_until(payments, due_on: date, day: date) -> int:
    return sum(
        item.amount_cents or 0
        for item in payments
        if item.attributed_due_on == due_on and item.value_date <= day
    )


def _last_payment_date(payments) -> date | None:
    dates = [item.value_date for item in payments]
    if not dates:
        return None
    return max(dates)


def _schedule_paid_exactly(collections: Collections, account: LoanAccount) -> bool:
    payments = collections._payments(account)
    for due_on, amount in _schedule(account):
        received = _received_until(payments, due_on, date.max)
        if received != amount:
            return False
    return True


def _outstanding_cents(ledger, account: LoanAccount) -> int:
    buckets = (
        "principal",
        "interest",
        "initiation",
        "service",
        "credit_insurance",
        "default_administration",
        "collection_costs",
        "additional_monthly",
    )
    return sum(ledger.bucket_balance(account, bucket) for bucket in buckets)
