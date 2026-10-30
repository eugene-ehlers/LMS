"""Ledger and account model.

Interest, allocation, day count, rounding, elections, and the Johannesburg
value date are called from the calculation engine and the configuration
layer. This module posts the results. It does not keep a second formula.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from lms.calc.allocation import allocate_payment
from lms.calc.fees import opening_service_fraction, service_fee_cents
from lms.calc.interest import (
    accrual_weight,
    daily_interest_rands,
    divisor_days,
    personal_annual_rate,
)
from lms.calc.models import (
    Charge,
    DayCount,
    FeeCapBasis,
    PrepaymentChoice,
    PrincipalSlice,
    Product,
    RepoFallChoice,
    RepoRate,
    State,
    VatRate,
)
from lms.calc.money import to_cents
from lms.ledger.errors import LedgerError
from lms.ledger.models import (
    FREQUENCIES,
    Accrual,
    DueCharge,
    Effect,
    ElectionSnapshot,
    Entry,
    Episode,
    LoanAccount,
    ScheduleVersion,
    Slice,
    Statement,
    StatementLine,
    Transaction,
)
from lms.ledger.store import LedgerStore
from lms_config.calendar import value_date
from lms_config.context import require_reference_for_posting
from lms_config.locked import (
    IN_DUPLUM_CLIP_POSTS,
    OrganisationSettings,
    campaign_rate,
    duplum_base_cents,
    interest_bearing_cents,
    is_in_default_at_morning_check,
    nominal_annual_rate,
    order_recognised_events,
)
from lms_config.locked import RecognisedReceipt
from lms_config.statute import DAY_COUNT_30_360, DAY_COUNT_ACTUAL_ACTUAL
from lms_config.validate import CPA_LAYBY, SHORT_TERM, UNSECURED, ZERO_COST, ProductTerms

_MONTHS = {"monthly": 1, "quarterly": 3, "bi_annual": 6, "annual": 12}
_DAYS = {"weekly": 7, "fortnightly": 14}
_COST_BUCKETS = (
    "interest",
    "initiation",
    "service",
    "credit_insurance",
    "default_administration",
    "collection_costs",
    "additional_monthly",
)
_CALC_KIND = {
    "interest": "interest",
    "initiation": "initiation",
    "service": "service",
    "credit_insurance": "insurance",
    "default_administration": "default_admin",
    "collection_costs": "collection",
}
_REVERSIBLE = {
    "booking",
    "laybye_deposit",
    "laybye_application",
    "payment",
    "interest_accrual",
    "interest_bill",
    "charge",
    "service_fee",
}
_ZERO_PRICE = {ZERO_COST, CPA_LAYBY}


def next_due_date(day: date, frequency: str) -> date:
    """Step one contractual period.

    Weekly and fortnightly are a fixed number of calendar days. A monthly
    step that would land on a day the target month does not have is refused.
    LOCKED_DECISIONS §14 does not say how that day moves.
    """
    if frequency not in FREQUENCIES:
        raise LedgerError("frequency-unsupported", f"{frequency} is not a locked payment frequency.")
    if frequency in _DAYS:
        return day + timedelta(days=_DAYS[frequency])
    month_index = day.month - 1 + _MONTHS[frequency]
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    if day.day > last:
        raise LedgerError(
            "due-date-unspecified",
            "LOCKED_DECISIONS §14 does not say how a due date moves when that "
            "day does not exist in the target month. The ledger will not clamp it.",
        )
    return date(year, month, day.day)


def nominal_annual(periodic_rate: Decimal, periods_per_year: int) -> Decimal:
    """LOCKED_DECISIONS §17. The caller supplies the number of periods."""
    return nominal_annual_rate(periodic_rate, periods_per_year)


class Ledger:
    def __init__(self, store: LedgerStore | None = None) -> None:
        self.store = store or LedgerStore()
        self._loan_portion_only = False
        self._last_laybye_transaction_id: str | None = None

    def book(
        self,
        *,
        organisation_id: str,
        person_id: str,
        product: ProductTerms,
        organisation: OrganisationSettings,
        recognised_at: datetime,
        cash_advanced_cents: int,
        frequency: str,
        schedule: tuple[tuple[date, int], ...],
        identity_name: str,
        identity_number: str,
        service_address: str,
        quoted_disbursement: date | None = None,
        initiation_fee_cents: int = 0,
        contractual_end: date | None = None,
    ) -> LoanAccount:
        if product.classification not in {SHORT_TERM, UNSECURED, ZERO_COST, CPA_LAYBY}:
            raise LedgerError(
                "classification-unsupported",
                f"{product.classification} is not a Day-1 classification in this ledger.",
            )
        resolved = resolve_customer_settings_for_booking(organisation, product)
        self._require_identity(identity_name, identity_number, service_address)
        if frequency not in FREQUENCIES:
            raise LedgerError("frequency-unsupported", f"{frequency} is not a locked payment frequency.")
        if cash_advanced_cents <= 0:
            raise LedgerError("principal", "Cash advanced must be positive.")
        if initiation_fee_cents < 0:
            raise LedgerError("initiation", "Initiation fee cannot be negative.")
        owed = cash_advanced_cents + (initiation_fee_cents if product.initiation_capitalised else 0)
        if sum(amount for _, amount in schedule) != owed:
            raise LedgerError(
                "schedule",
                "Schedule lines must sum to the principal. A capitalised initiation "
                "fee is included in that principal. LOCKED_DECISIONS §2.",
            )
        booked = value_date(recognised_at)
        end = contractual_end or max(due for due, _ in schedule)
        if end < booked:
            raise LedgerError("term", "Contractual end cannot precede the disbursement value date.")
        for due, amount in schedule:
            if amount <= 0:
                raise LedgerError("schedule", "Each principal line must be positive.")
            if due < booked or due > end:
                raise LedgerError("schedule", "A principal due date is outside the agreement.")
        self._reject_unset_late_disbursement(resolved, booked, quoted_disbursement)
        account = self.prepare(
            organisation_id=organisation_id,
            person_id=person_id,
            product=product,
            organisation=organisation,
            recognised_at=recognised_at,
            cash_advanced_cents=cash_advanced_cents,
            frequency=frequency,
            schedule=schedule,
            identity_name=identity_name,
            identity_number=identity_number,
            service_address=service_address,
            quoted_disbursement=quoted_disbursement,
            initiation_fee_cents=initiation_fee_cents,
            contractual_end=end,
        )
        return self.grant(
            organisation_id=account.organisation_id,
            loan_id=account.loan_id,
            recognised_at=recognised_at,
            schedule=schedule,
            initiation_fee_cents=initiation_fee_cents,
        )

    def prepare(
        self,
        *,
        organisation_id: str,
        person_id: str,
        product: ProductTerms,
        organisation: OrganisationSettings,
        recognised_at: datetime,
        cash_advanced_cents: int,
        frequency: str,
        schedule: tuple[tuple[date, int], ...],
        identity_name: str,
        identity_number: str,
        service_address: str,
        quoted_disbursement: date | None = None,
        initiation_fee_cents: int = 0,
        contractual_end: date | None = None,
    ) -> LoanAccount:
        """Open the parent before the loan-out journal. LOCKED_DECISIONS §4.

        Pre-disbursement receipts need a parent row so the Laybye child can
        exist. This posts no principal and no cash credit. The disbursement
        value date stays empty until ``grant``.
        """
        if product.classification not in {SHORT_TERM, UNSECURED, ZERO_COST, CPA_LAYBY}:
            raise LedgerError(
                "classification-unsupported",
                f"{product.classification} is not a Day-1 classification in this ledger.",
            )
        resolved = resolve_customer_settings_for_booking(organisation, product)
        self._require_identity(identity_name, identity_number, service_address)
        if frequency not in FREQUENCIES:
            raise LedgerError("frequency-unsupported", f"{frequency} is not a locked payment frequency.")
        if cash_advanced_cents <= 0:
            raise LedgerError("principal", "Cash advanced must be positive.")
        if initiation_fee_cents < 0:
            raise LedgerError("initiation", "Initiation fee cannot be negative.")
        if not schedule:
            raise LedgerError("schedule", "A prepared loan needs its contractual schedule.")
        owed = cash_advanced_cents + (initiation_fee_cents if product.initiation_capitalised else 0)
        if sum(amount for _, amount in schedule) != owed:
            raise LedgerError(
                "schedule",
                "Schedule lines must sum to the principal. A capitalised initiation "
                "fee is included in that principal. LOCKED_DECISIONS §2.",
            )
        end = contractual_end or max(due for due, _ in schedule)
        for due, amount in schedule:
            if amount <= 0:
                raise LedgerError("schedule", "Each principal line must be positive.")
            if due > end:
                raise LedgerError("schedule", "A principal due date is outside the agreement.")
        snapshot = ElectionSnapshot.from_resolved(
            resolved,
            initiation_capitalised=product.initiation_capitalised,
            payment_frequency=frequency,
            classification=product.classification,
        )
        account = LoanAccount(
            organisation_id=organisation_id,
            loan_id=str(uuid4()),
            person_id=person_id,
            parent_loan_id=None,
            instrument_kind="loan",
            frozen_full_name=identity_name.strip(),
            frozen_id_number=identity_number.strip(),
            frozen_service_address=service_address.strip(),
            snapshot=snapshot,
            payment_frequency=frequency,
            disbursement_value_date=None,
            quoted_disbursement=quoted_disbursement,
            contractual_end=end,
            cash_advanced_cents=cash_advanced_cents,
        )
        self.store.add(account)
        return account

    def grant(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        schedule: tuple[tuple[date, int], ...],
        initiation_fee_cents: int = 0,
    ) -> LoanAccount:
        """Post the loan-out journal. The linked hold is not moved. LOCKED_DECISIONS §4."""
        account = self.store.get(organisation_id, loan_id)
        if account.instrument_kind != "loan":
            raise LedgerError("laybye-parent", "Only the parent loan is granted.")
        if account.disbursement_value_date is not None or self._has_kind(account, "booking"):
            raise LedgerError("already-granted", "This loan has already been granted.")
        if initiation_fee_cents < 0:
            raise LedgerError("initiation", "Initiation fee cannot be negative.")
        capitalised = account.snapshot.initiation_capitalised
        owed = account.cash_advanced_cents + (initiation_fee_cents if capitalised else 0)
        if sum(amount for _, amount in schedule) != owed:
            raise LedgerError(
                "schedule",
                "Schedule lines must sum to the principal. A capitalised initiation "
                "fee is included in that principal. LOCKED_DECISIONS §2.",
            )
        booked = value_date(recognised_at)
        if account.contractual_end < booked:
            raise LedgerError("term", "Contractual end cannot precede the disbursement value date.")
        for due, amount in schedule:
            if amount <= 0:
                raise LedgerError("schedule", "Each principal line must be positive.")
            if due < booked or due > account.contractual_end:
                raise LedgerError("schedule", "A principal due date is outside the agreement.")
        self._reject_unset_late_disbursement(
            account.snapshot, booked, account.quoted_disbursement
        )
        late_choice: str | None = None
        reason = "booking"
        if account.quoted_disbursement is not None and booked > account.quoted_disbursement:
            late_choice = account.snapshot.late_disbursement
            reason = "late_disbursement"
        account.disbursement_value_date = booked
        effects: list[Effect] = []
        for sequence, (due, amount) in enumerate(schedule, start=1):
            effects.append(Effect("create_slice", cents=amount, due_on=due, sequence=sequence))
        entries = [
            Entry("principal", "principal", account.cash_advanced_cents, 0),
            Entry("cash", None, 0, account.cash_advanced_cents),
        ]
        if initiation_fee_cents and capitalised:
            entries.extend(
                (
                    Entry("principal", "principal", initiation_fee_cents, 0),
                    Entry("initiation_income", None, 0, initiation_fee_cents),
                )
            )
            effects.append(Effect("increase_capitalised", cents=initiation_fee_cents))
        elif initiation_fee_cents:
            entries.extend(
                (
                    Entry("initiation_receivable", "initiation", initiation_fee_cents, 0),
                    Entry("initiation_income", None, 0, initiation_fee_cents),
                )
            )
            effects.append(
                Effect(
                    "increase_charge",
                    cents=initiation_fee_cents,
                    charge_id=str(uuid4()),
                    bucket="initiation",
                    due_on=booked,
                    sequence=1,
                    levied_on=booked,
                    ex_vat_cents=initiation_fee_cents,
                )
            )
            account.next_charge_sequence = 2
        account.schedule_versions.append(
            ScheduleVersion(1, booked, reason, late_choice, tuple(schedule))
        )
        self._post(
            account,
            kind="booking",
            recognised_at=recognised_at,
            entries=tuple(entries),
            effects=tuple(effects),
        )
        self._assert_consistent(account)
        return account

    def open_laybye(
        self,
        *,
        organisation_id: str,
        parent_loan_id: str,
        recognised_at: datetime,
        amount_cents: int,
        identity_name: str,
        identity_number: str,
        service_address: str,
    ) -> LoanAccount:
        parent = self.store.get(organisation_id, parent_loan_id)
        if parent.instrument_kind != "loan":
            raise LedgerError("laybye-parent", "A lay-by hold is a child of a loan, not of another hold.")
        if self._children(parent):
            raise LedgerError(
                "laybye-already-linked",
                "LOCKED_DECISIONS §4 treats the loan and its lay-by as one pair.",
            )
        if amount_cents < 0:
            raise LedgerError("laybye", "Lay-by hold cannot be negative.")
        self._require_identity(identity_name, identity_number, service_address)
        booked = value_date(recognised_at)
        child = LoanAccount(
            organisation_id=organisation_id,
            loan_id=str(uuid4()),
            person_id=parent.person_id,
            parent_loan_id=parent.loan_id,
            instrument_kind="laybye_hold",
            frozen_full_name=identity_name.strip(),
            frozen_id_number=identity_number.strip(),
            frozen_service_address=service_address.strip(),
            snapshot=parent.snapshot,
            payment_frequency=parent.payment_frequency,
            disbursement_value_date=booked,
            quoted_disbursement=None,
            contractual_end=parent.contractual_end,
            cash_advanced_cents=parent.cash_advanced_cents,
        )
        self.store.add(child)
        if amount_cents:
            self._post(
                child,
                kind="laybye_deposit",
                recognised_at=recognised_at,
                entries=(
                    Entry("cash", None, amount_cents, 0),
                    Entry("laybye_hold", "laybye_hold", 0, amount_cents),
                ),
                effects=(),
                amount_cents=amount_cents,
            )
        return child

    def credit_laybye(
        self,
        *,
        organisation_id: str,
        parent_loan_id: str,
        cents: int,
        recognised_at: datetime,
    ) -> Transaction:
        """Cash in on the hold. Not a loan-out. LOCKED_DECISIONS §4."""
        child = self._laybye_child(organisation_id, parent_loan_id)
        if cents <= 0:
            raise LedgerError("laybye", "A Laybye receipt must be positive.")
        return self._post(
            child,
            kind="laybye_deposit",
            recognised_at=recognised_at,
            entries=(
                Entry("cash", None, cents, 0),
                Entry("laybye_hold", "laybye_hold", 0, cents),
            ),
            effects=(),
            amount_cents=cents,
        )

    def debit_laybye(
        self,
        *,
        organisation_id: str,
        parent_loan_id: str,
        cents: int,
        recognised_at: datetime,
    ) -> Transaction:
        """Reduce the hold. Paired with a loan receipt when the hold is applied."""
        child = self._laybye_child(organisation_id, parent_loan_id)
        if cents <= 0:
            raise LedgerError("laybye", "A Laybye application must be positive.")
        if self.bucket_balance(child, "laybye_hold") < cents:
            raise LedgerError("laybye", "The Laybye hold is smaller than the application.")
        return self._post(
            child,
            kind="laybye_application",
            recognised_at=recognised_at,
            entries=(
                Entry("laybye_hold", "laybye_hold", cents, 0),
                Entry("cash", None, 0, cents),
            ),
            effects=(),
            amount_cents=cents,
        )

    def section_126_cents(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        cents: int,
        recognised_at: datetime,
    ) -> int:
        """Due amount ``allocate_payment`` will take. Future principal is not included.

        LOCKED_DECISIONS §8. The partial-prepayment election is not applied here.
        """
        account = self._loan(organisation_id, loan_id)
        if cents < 0:
            raise LedgerError("payment", "A receipt cannot be negative.")
        if cents == 0:
            return 0
        day = value_date(recognised_at)
        due_charges = [charge for charge in account.charges if charge.remaining_cents > 0]
        additional = [charge for charge in due_charges if charge.bucket == "additional_monthly"]
        named = [charge for charge in due_charges if charge.bucket != "additional_monthly"]
        interest_due = sum(charge.remaining_cents for charge in named if charge.bucket == "interest")
        named_fees = sum(charge.remaining_cents for charge in named if charge.bucket != "interest")
        additional_due = sum(charge.remaining_cents for charge in additional)
        if (
            additional_due
            and named_fees
            and cents > interest_due
            and cents < interest_due + named_fees + additional_due
        ):
            raise LedgerError(
                "additional-fee-order-unset",
                "LOCKED_DECISIONS §8 orders the named fee buckets. It does not place "
                "the further monthly fee among them, so a short payment that would "
                "have to choose fails closed.",
            )
        state = self._state(account, named, day)
        first_amount = min(cents, interest_due + named_fees) if additional_due else cents
        first = allocate_payment(
            state,
            first_amount,
            as_of=day,
            prepayment=None,
            apply_prepayment=False,
        )
        taken = first.interest_cents + first.fee_cents + first.principal_cents
        leftover = cents - taken
        additional_taken = 0
        for charge in sorted(additional, key=lambda item: (item.due_on, item.sequence)):
            if leftover == 0:
                break
            take = min(charge.remaining_cents, leftover)
            additional_taken += take
            leftover -= take
        return taken + additional_taken

    def accrue_day(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        interest_cap_present: bool,
        repos: tuple[RepoRate, ...] = (),
        repo_annual: Decimal | None = None,
    ) -> Accrual:
        account = self._loan(organisation_id, loan_id)
        day = value_date(recognised_at)
        if day < account.disbursement_value_date or day > account.contractual_end:
            raise LedgerError(
                "outside-term",
                "Interest is not accrued outside the disbursement date and the contractual end.",
            )
        if any(tx.kind == "interest_accrual" and tx.value_date == day for tx in self._tx_for(account)):
            raise LedgerError("already-accrued", "This value date already has an accrual.")
        classification = account.snapshot.classification
        if classification not in _ZERO_PRICE:
            require_reference_for_posting(
                interest_cap_present=interest_cap_present,
                repo_annual=repo_annual,
                repo_required=classification == UNSECURED,
                tariff_cents=None,
                tariff_required=False,
            )
        base, principal, hold = self._interest_base(account)
        rate, weight, divisor = self._rate_and_divisor(account, day, repos)
        if classification in _ZERO_PRICE:
            day_rands = daily_interest_rands(0, Decimal(0), 1, weight=1)
            weight = 1
        else:
            day_rands = daily_interest_rands(base, rate, divisor, weight=weight)
        transaction = self._post(
            account,
            kind="interest_accrual",
            recognised_at=recognised_at,
            entries=(),
            effects=(),
            memo_rands=day_rands,
        )
        return Accrual(
            account.loan_id,
            day,
            base,
            principal,
            hold,
            weight,
            rate,
            day_rands,
            transaction.transaction_id,
        )

    def bill_interest(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
    ) -> Transaction | None:
        account = self._loan(organisation_id, loan_id)
        net = Decimal(0)
        for transaction in self._tx_for(account):
            if transaction.memo_rands is not None and self._root_kind(transaction) == "interest_accrual":
                net += transaction.memo_rands
        if net < 0:
            raise LedgerError(
                "bill-below-booked",
                "Billed interest would exceed the accrued memo. Reverse the bill rather than posting a negative one.",
            )
        target = to_cents(net)
        already = self._billed_accrual_cents(account)
        delta = target - already
        if delta < 0:
            raise LedgerError(
                "bill-below-booked",
                "Billed interest would exceed the accrued memo. Reverse the bill rather than posting a negative one.",
            )
        if delta == 0:
            return None
        day = value_date(recognised_at)
        return self._charge(
            account,
            bucket="interest",
            cents=delta,
            due_on=day,
            recognised_at=recognised_at,
            kind="interest_bill",
            ex_vat_cents=delta,
            vat_cents=0,
        )

    def levy_charge(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        bucket: str,
        cents: int,
        due_on: date,
        recognised_at: datetime,
        interest_cap_present: bool,
        tariff_cents: int | None = None,
        repo_annual: Decimal | None = None,
    ) -> Transaction:
        account = self._loan(organisation_id, loan_id)
        if bucket not in _COST_BUCKETS or bucket == "service":
            raise LedgerError("bucket", "Use the service-fee method for the monthly service fee.")
        if cents < 0:
            raise LedgerError("charge", "A charge cannot be negative.")
        if account.snapshot.classification in _ZERO_PRICE and cents:
            raise LedgerError("zero-cost-charge", "A zero-cost booking cannot carry an NCA charge.")
        self._require_tariff_or_cap(
            account,
            bucket,
            interest_cap_present=interest_cap_present,
            tariff_cents=tariff_cents,
            repo_annual=repo_annual,
        )
        if bucket == "additional_monthly":
            # Not capitalised into principal. LOCKED_DECISIONS §13 and §18.
            pass
        return self._charge(
            account,
            bucket=bucket,
            cents=cents,
            due_on=due_on,
            recognised_at=recognised_at,
            kind="charge",
            ex_vat_cents=cents,
            vat_cents=0,
        )

    def levy_service_fee(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        monthly_cents: int,
        due_on: date,
        interest_cap_present: bool,
        vat_rate: Decimal | None = None,
        vat_registered: bool = True,
        opening: bool = False,
        first_due: date | None = None,
    ) -> Transaction:
        account = self.store.get(organisation_id, loan_id)
        if account.instrument_kind != "loan":
            raise LedgerError(
                "service-fee-parent",
                "LOCKED_DECISIONS §4: one monthly service fee, levied on the parent.",
            )
        if account.disbursement_value_date is None:
            raise LedgerError(
                "not-disbursed",
                "The loan has not been granted. LOCKED_DECISIONS §4.",
            )
        if monthly_cents < 0:
            raise LedgerError("service-fee", "Service fee cannot be negative.")
        if account.snapshot.classification in _ZERO_PRICE and monthly_cents:
            raise LedgerError("zero-cost-charge", "A zero-cost booking cannot carry a service fee.")
        day = value_date(recognised_at)
        period = (day.year, day.month)
        if period in account.service_months:
            raise LedgerError(
                "service-fee-once",
                "LOCKED_DECISIONS §4: the linked pair carries one monthly service fee.",
            )
        ex_vat = vat = total = 0
        if monthly_cents:
            if vat_rate is None:
                raise LedgerError(
                    "vat-rate-unset",
                    "The VAT rate is not stored on the election. The ledger does not assume one.",
                )
            require_reference_for_posting(
                interest_cap_present=interest_cap_present,
                repo_annual=None,
                repo_required=False,
                tariff_cents=None,
                tariff_required=False,
            )
            basis = (
                FeeCapBasis.EXCLUSIVE
                if account.snapshot.vat_on_rand_maxima == "exclusive"
                else FeeCapBasis.INCLUSIVE
            )
            fraction = None
            full_month = True
            if opening:
                if first_due is None:
                    raise LedgerError("service-fee", "The opening month needs the first due date.")
                fraction = opening_service_fraction(account.disbursement_value_date, first_due)
                full_month = False
            ex_vat, vat, total = service_fee_cents(
                on=day,
                period_start=day,
                period_end=day,
                monthly_cap_cents=monthly_cents,
                full_month=full_month,
                fraction=fraction,
                vat_rates=(VatRate(date(day.year, 1, 1), vat_rate),),
                basis=basis,
                vat_registered=vat_registered,
            )
        return self._charge(
            account,
            bucket="service",
            cents=total,
            due_on=due_on,
            recognised_at=recognised_at,
            kind="service_fee",
            ex_vat_cents=ex_vat,
            vat_cents=vat,
            extra_effects=(Effect("mark_service_month", year=period[0], month=period[1]),),
        )

    def settlement_balance_cents(self, organisation_id: str, loan_id: str) -> int:
        """Remaining charges plus remaining principal, in cents.

        Unbilled interest is not included. Capitalise it first. A mismatch
        between the principal bucket and the slices fails closed.
        """
        account = self._loan(organisation_id, loan_id)
        unbilled = self._unbilled_interest_cents(account)
        if unbilled != 0:
            raise LedgerError(
                "unbilled-interest",
                "Accrued interest is still unbilled. Capitalise it before the settlement receipt is allocated.",
            )
        return self._owed_cents(account)

    def post_payment(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        cents: int,
        recognised_at: datetime,
        attributed_due_on: date | None = None,
        settle: bool = False,
    ) -> Transaction:
        """Allocate a receipt.

        A loan with a Laybye child takes due section 126 amounts first and
        credits any remainder to the Laybye. LOCKED_DECISIONS §4 and §8.
        The §13 partial-prepayment election is not applied to that remainder.
        The lock does not say whether prepayment runs before the Laybye.
        A loan with no Laybye child keeps the prepayment election, then
        ``overpayment-unset`` when a remainder has no home.

        ``settle=True`` pays every remaining principal slice. That is section
        125, in section 126 order, and it is not the section 13 prepayment
        choice. An early-termination charge is not added.
        """
        account = self._loan(organisation_id, loan_id)
        if cents < 0:
            raise LedgerError("payment", "A receipt cannot be negative.")
        if not self._loan_portion_only:
            self._last_laybye_transaction_id = None
            if settle:
                return self._post_settlement(
                    account,
                    cents=cents,
                    recognised_at=recognised_at,
                    attributed_due_on=attributed_due_on,
                )
            if self._children(account):
                return self._post_loan_then_laybye(
                    account,
                    cents=cents,
                    recognised_at=recognised_at,
                    attributed_due_on=attributed_due_on,
                )
        day = value_date(recognised_at)
        due_charges = [charge for charge in account.charges if charge.remaining_cents > 0]
        additional = [charge for charge in due_charges if charge.bucket == "additional_monthly"]
        named = [charge for charge in due_charges if charge.bucket != "additional_monthly"]
        interest_due = sum(charge.remaining_cents for charge in named if charge.bucket == "interest")
        named_fees = sum(charge.remaining_cents for charge in named if charge.bucket != "interest")
        additional_due = sum(charge.remaining_cents for charge in additional)
        if (
            additional_due
            and named_fees
            and cents > interest_due
            and cents < interest_due + named_fees + additional_due
        ):
            raise LedgerError(
                "additional-fee-order-unset",
                "LOCKED_DECISIONS §8 orders the named fee buckets. It does not place "
                "the further monthly fee among them, so a short payment that would "
                "have to choose fails closed.",
            )
        choice = _prepayment(account.snapshot.partial_prepayment)
        state = self._state(account, named, day)
        first_amount = cents
        if additional_due:
            first_amount = min(cents, interest_due + named_fees)
        first = allocate_payment(
            state,
            first_amount,
            as_of=day,
            prepayment=choice,
            apply_prepayment=not additional_due,
            settle=settle,
        )
        if additional_due and first.suspense_cents:
            raise LedgerError("unbalanced", "The fee portion of the receipt was not applied.")
        leftover = cents - first.interest_cents - first.fee_cents - first.principal_cents
        additional_taken: list[tuple[DueCharge, int]] = []
        for charge in sorted(additional, key=lambda item: (item.due_on, item.sequence)):
            if leftover == 0 or additional_due == 0:
                break
            take = min(charge.remaining_cents, leftover)
            if take:
                additional_taken.append((charge, take))
                leftover -= take
        second = None
        if additional_due and leftover:
            second = allocate_payment(
                first.state,
                leftover,
                as_of=day,
                prepayment=choice,
                apply_prepayment=True,
                settle=settle,
            )
            if second.suspense_cents:
                raise LedgerError(
                    "overpayment-unset",
                    "A receipt above the due and chosen prepayment amounts has no locked home.",
                )
        elif first.suspense_cents:
            raise LedgerError(
                "overpayment-unset",
                "A receipt above the due and chosen prepayment amounts has no locked home.",
            )
        principal_taken = first.principal_cents + (second.principal_cents if second else 0)
        self._guard_capitalised_reduction(account, principal_taken)
        effects: list[Effect] = []
        credits: dict[str, int] = {}
        final_charges = (second or first).state.charges
        original = {charge.charge_id: charge.remaining_cents for charge in self._charges_of(named)}
        for charge in final_charges:
            taken = original.get(charge.charge_id, 0) - charge.remaining_cents
            if taken:
                bucket = next(item.bucket for item in named if item.charge_id == charge.charge_id)
                credits[bucket] = credits.get(bucket, 0) + taken
                effects.append(Effect("decrease_charge", cents=taken, charge_id=charge.charge_id))
        for charge, taken in additional_taken:
            credits[charge.bucket] = credits.get(charge.bucket, 0) + taken
            effects.append(Effect("decrease_charge", cents=taken, charge_id=charge.charge_id))
        final_slices = (second or first).state.principal_slices
        original_slices = {slice_.sequence: slice_.remaining_cents for slice_ in account.slices}
        for slice_ in final_slices:
            taken = original_slices.get(slice_.sequence, 0) - slice_.remaining_cents
            if taken:
                credits["principal"] = credits.get("principal", 0) + taken
                effects.append(Effect("decrease_slice", cents=taken, sequence=slice_.sequence))
        if sum(credits.values()) != cents:
            raise LedgerError("unbalanced", "The receipt was not fully posted to a bucket.")
        entries = [Entry("cash", None, cents, 0)]
        for bucket, amount in credits.items():
            code = "principal" if bucket == "principal" else f"{bucket}_receivable"
            entries.append(Entry(code, bucket, 0, amount))
        transaction = self._post(
            account,
            kind="payment",
            recognised_at=recognised_at,
            entries=tuple(entries),
            effects=tuple(effects),
            amount_cents=cents,
            attributed_due_on=attributed_due_on,
        )
        self._assert_consistent(account)
        return transaction

    def _post_settlement(
        self,
        account: LoanAccount,
        *,
        cents: int,
        recognised_at: datetime,
        attributed_due_on: date | None,
    ) -> Transaction:
        """Pay the settlement balance in section 126 order, then any Laybye excess.

        The receipt is not posted when it is short of the balance, or when it
        exceeds the balance and no Laybye child exists. LOCKED_DECISIONS §4 and §8.
        """
        total = self._owed_cents(account)
        unbilled = self._unbilled_interest_cents(account)
        if unbilled != 0:
            raise LedgerError(
                "unbilled-interest",
                "Accrued interest is still unbilled. Capitalise it before the settlement receipt is allocated.",
            )
        if cents < total:
            raise LedgerError(
                "settlement-short",
                f"The settlement receipt is {cents} cents. The balance is {total} cents. "
                "The agreement is not settled.",
            )
        if cents > total and not self._children(account):
            raise LedgerError(
                "overpayment-unset",
                "The settlement receipt exceeds the balance and no Laybye is linked. "
                "LOCKED_DECISIONS §4 and §8 give that excess no home. The agreement is not settled.",
            )
        if total and attributed_due_on is None:
            raise LedgerError(
                "due-date-attribution-unset",
                "LOCKED_DECISIONS §6 compares the amount received for a due date. "
                "A settlement receipt without an attributed due date is not posted.",
            )
        excess = cents - total
        loan_tx = None
        if total:
            self._loan_portion_only = True
            try:
                loan_tx = self.post_payment(
                    organisation_id=account.organisation_id,
                    loan_id=account.loan_id,
                    cents=total,
                    recognised_at=recognised_at,
                    attributed_due_on=attributed_due_on,
                    settle=True,
                )
            finally:
                self._loan_portion_only = False
        if excess:
            laybye_tx = self.credit_laybye(
                organisation_id=account.organisation_id,
                parent_loan_id=account.loan_id,
                cents=excess,
                recognised_at=recognised_at,
            )
            self._last_laybye_transaction_id = laybye_tx.transaction_id
        if loan_tx is not None:
            return loan_tx
        raise LedgerError(
            "settlement-short",
            "The settlement balance is 0 cents. There is nothing to allocate, so the receipt is not a settlement.",
        )

    def _owed_cents(self, account: LoanAccount) -> int:
        charges = sum(charge.remaining_cents for charge in account.charges)
        principal = sum(slice_.remaining_cents for slice_ in account.slices)
        bucket = self.bucket_balance(account, "principal")
        if bucket != principal:
            raise LedgerError(
                "unbalanced",
                "Principal slices do not match the principal bucket. The agreement is not settled.",
            )
        return charges + principal

    def _unbilled_interest_cents(self, account: LoanAccount) -> int:
        net = Decimal(0)
        for transaction in self._tx_for(account):
            if transaction.memo_rands is not None and self._root_kind(transaction) == "interest_accrual":
                net += transaction.memo_rands
        if net < 0:
            raise LedgerError(
                "bill-below-booked",
                "Billed interest would exceed the accrued memo. Reverse the bill rather than posting a negative one.",
            )
        return to_cents(net) - self._billed_accrual_cents(account)

    def _post_loan_then_laybye(
        self,
        account: LoanAccount,
        *,
        cents: int,
        recognised_at: datetime,
        attributed_due_on: date | None,
    ) -> Transaction:
        """Due section 126 amounts on the loan, then the remainder on the Laybye."""
        if cents <= 0:
            raise LedgerError("payment", "A receipt must be positive.")
        loan_cents = self.section_126_cents(
            organisation_id=account.organisation_id,
            loan_id=account.loan_id,
            cents=cents,
            recognised_at=recognised_at,
        )
        excess = cents - loan_cents
        if excess and not self._children(account):
            raise LedgerError(
                "laybye-missing",
                "LOCKED_DECISIONS §4: excess goes to the Laybye account. None exists, "
                "so the receipt is not posted.",
            )
        if loan_cents and attributed_due_on is None:
            raise LedgerError(
                "due-date-attribution-unset",
                "LOCKED_DECISIONS §6 compares the amount received for a due date. "
                "A loan portion without an attributed due date is not posted.",
            )
        loan_tx = None
        if loan_cents:
            self._loan_portion_only = True
            try:
                loan_tx = self.post_payment(
                    organisation_id=account.organisation_id,
                    loan_id=account.loan_id,
                    cents=loan_cents,
                    recognised_at=recognised_at,
                    attributed_due_on=attributed_due_on,
                )
            finally:
                self._loan_portion_only = False
        laybye_tx = None
        if excess:
            laybye_tx = self.credit_laybye(
                organisation_id=account.organisation_id,
                parent_loan_id=account.loan_id,
                cents=excess,
                recognised_at=recognised_at,
            )
            self._last_laybye_transaction_id = laybye_tx.transaction_id
        if loan_tx is not None:
            return loan_tx
        if laybye_tx is not None:
            return laybye_tx
        raise LedgerError("payment", "A receipt must be positive.")

    def reverse(
        self,
        *,
        organisation_id: str,
        transaction_id: str,
        recognised_at: datetime,
    ) -> Transaction:
        original = self.store.get_transaction(organisation_id, transaction_id)
        if original.kind not in _REVERSIBLE:
            raise LedgerError(
                "reversal-undefined",
                f"A reversal of {original.kind} is not defined. LOCKED_DECISIONS §1 covers the value date of a reversal that is posted.",
            )
        existing = self.store.transactions_for(organisation_id, original.loan_id)
        if any(item.reverses_transaction_id == original.transaction_id for item in existing):
            raise LedgerError("already-reversed", "This transaction already has a reversal.")
        if any(item.recognition_sequence > original.recognition_sequence for item in existing):
            raise LedgerError("reversal-order", "Reverse the later transaction on this loan first.")
        account = self.store.get(organisation_id, original.loan_id)
        swapped = tuple(
            Entry(entry.account_code, entry.bucket, entry.credit_cents, entry.debit_cents)
            for entry in original.entries
        )
        memo = None if original.memo_rands is None else -original.memo_rands
        transaction = self._post(
            account,
            kind="reversal",
            recognised_at=recognised_at,
            value_date_override=original.value_date,
            entries=swapped,
            effects=(),
            memo_rands=memo,
            reverses_transaction_id=original.transaction_id,
            amount_cents=original.amount_cents,
            attributed_due_on=original.attributed_due_on,
        )
        self._undo(account, original.effects)
        self._assert_consistent(account)
        return transaction

    def flag_default(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        check_on: date,
        due_on: date,
        instalment_cents: int,
        recognised_at: datetime,
    ) -> bool:
        """Run the configuration layer's morning check.

        ``instalment_cents`` is supplied by the caller. The ledger does not
        assemble the threshold instalment: whether debited interest joins it
        is not locked.
        """
        account = self._loan(organisation_id, loan_id)
        payments = [
            transaction
            for transaction in self.store.transactions_for(organisation_id, loan_id)
            if transaction.kind == "payment"
            and not any(
                other.reverses_transaction_id == transaction.transaction_id
                for other in self.store.transactions_for(organisation_id, loan_id)
            )
        ]
        if any(transaction.attributed_due_on is None for transaction in payments):
            raise LedgerError(
                "due-date-attribution-unset",
                "LOCKED_DECISIONS §6 compares the amount received for a due date. "
                "Section 126 does not attribute a receipt to a due date, so an "
                "unattributed receipt fails closed.",
            )
        receipts = tuple(
            RecognisedReceipt(
                transaction.recognised_at,
                transaction.recognition_sequence,
                transaction.amount_cents or 0,
                transaction.attributed_due_on,
            )
            for transaction in payments
            if transaction.attributed_due_on is not None
        )
        flagged = is_in_default_at_morning_check(
            due_on=due_on,
            check_on=check_on,
            leniency_days=account.snapshot.leniency_days,
            receipts=receipts,
            instalment_cents=instalment_cents,
            threshold_percent=account.snapshot.full_payment_threshold_percent,
        )
        open_episode = self._open_episode(account)
        effects: list[Effect] = []
        if flagged and open_episode is None:
            effects.append(self._open_episode_effect(account, check_on))
            effects.append(Effect("fall_away"))
        elif not flagged and open_episode is not None:
            effects.append(
                Effect("close_episode", episode_no=open_episode.episode_no, levied_on=check_on)
            )
        self._post(
            account,
            kind="default_flag",
            recognised_at=recognised_at,
            entries=(),
            effects=tuple(effects),
        )
        return flagged

    def open_in_duplum_episode(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        fall_away: bool,
    ) -> Episode:
        """Open one episode at the principal now on the loan.

        Collections decides which §6 event this is. This method does not
        run the morning check and does not close an episode. A second open
        while one is already open is refused: §7 does not restart a ceiling.
        """
        account = self._loan(organisation_id, loan_id)
        if self._open_episode(account) is not None:
            raise LedgerError(
                "episode-open",
                "LOCKED_DECISIONS §7: an open in-duplum episode is not restarted.",
            )
        day = value_date(recognised_at)
        effects: list[Effect] = [self._open_episode_effect(account, day)]
        if fall_away and not account.discount_fallen_away:
            effects.append(Effect("fall_away"))
        self._post(
            account,
            kind="default_flag",
            recognised_at=recognised_at,
            entries=(),
            effects=tuple(effects),
        )
        opened = self._open_episode(account)
        if opened is None:
            raise LedgerError("episode", "The in-duplum episode did not open.")
        return opened

    def close_in_duplum_episode(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
    ) -> Episode:
        """Close the open episode. The discount flag is left as it is (§3)."""
        account = self._loan(organisation_id, loan_id)
        episode = self._open_episode(account)
        if episode is None:
            raise LedgerError("episode-absent", "There is no open in-duplum episode to close.")
        self._post(
            account,
            kind="default_flag",
            recognised_at=recognised_at,
            entries=(),
            effects=(
                Effect("close_episode", episode_no=episode.episode_no, levied_on=value_date(recognised_at)),
            ),
        )
        return episode

    def mark_discount_fallen_away(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
    ) -> None:
        """§3. Once the flag date has removed the discount, it stays off."""
        account = self._loan(organisation_id, loan_id)
        if account.discount_fallen_away:
            return
        self._post(
            account,
            kind="default_flag",
            recognised_at=recognised_at,
            entries=(),
            effects=(Effect("fall_away"),),
        )

    def write_off_outstanding(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        amount_cents: int | None = None,
    ) -> Transaction:
        """Write off the full outstanding position in one balanced journal.

        §8 does not rank a partial write-off across buckets. An amount other
        than the full position is refused. Principal slices and charges are
        cleared together so the ledger invariant holds.
        """
        account = self._loan(organisation_id, loan_id)
        effects: list[Effect] = []
        credits: dict[str, int] = {}
        for slice_ in account.slices:
            if slice_.remaining_cents:
                effects.append(
                    Effect("decrease_slice", cents=slice_.remaining_cents, sequence=slice_.sequence)
                )
                credits["principal"] = credits.get("principal", 0) + slice_.remaining_cents
        for charge in account.charges:
            if charge.remaining_cents:
                effects.append(
                    Effect(
                        "decrease_charge",
                        cents=charge.remaining_cents,
                        charge_id=charge.charge_id,
                    )
                )
                credits[charge.bucket] = credits.get(charge.bucket, 0) + charge.remaining_cents
        total = sum(credits.values())
        if total == 0:
            raise LedgerError("write-off-zero", "There is no outstanding balance to write off.")
        if amount_cents is not None and amount_cents != total:
            raise LedgerError(
                "write-off-partial-unset",
                "LOCKED_DECISIONS §8 does not order a partial write-off across buckets. "
                "The journal writes off the full outstanding position, or it does not post.",
            )
        entries = [Entry("write_off_expense", None, total, 0)]
        for bucket, amount in credits.items():
            code = "principal" if bucket == "principal" else f"{bucket}_receivable"
            entries.append(Entry(code, bucket, 0, amount))
        transaction = self._post(
            account,
            kind="write_off",
            recognised_at=recognised_at,
            entries=tuple(entries),
            effects=tuple(effects),
            amount_cents=total,
        )
        self._assert_consistent(account)
        return transaction

    def issue_statement(
        self,
        *,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
    ) -> Statement:
        if period_end < period_start:
            raise LedgerError("statement-period", "The statement period ends before it starts.")
        for start, end in self.store.statement_keys(organisation_id, person_id):
            if start <= period_end and period_start <= end:
                raise LedgerError(
                    "statement-exists",
                    "LOCKED_DECISIONS §12: one statement per client per credit-provider organisation. "
                    "The period bounds themselves are not locked; an overlapping period is refused.",
                )
        self.store.remember_statement((organisation_id, person_id, period_start, period_end))
        return self._statement(organisation_id, person_id, period_start, period_end)

    def statement(
        self,
        *,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
    ) -> Statement:
        return self._statement(organisation_id, person_id, period_start, period_end)

    def clip_in_duplum(self) -> None:
        if not IN_DUPLUM_CLIP_POSTS:
            raise LedgerError(
                "in-duplum-clip-off",
                "LOCKED_DECISIONS §7: the clip stays off. Three section 103(5) edges are unnamed.",
            )

    def bucket_balance(self, account: LoanAccount, bucket: str, *, as_of: date | None = None) -> int:
        total = 0
        for transaction in self._tx_for(account):
            if as_of is not None and transaction.value_date > as_of:
                continue
            for entry in transaction.entries:
                if entry.bucket != bucket:
                    continue
                if bucket == "laybye_hold":
                    total += entry.credit_cents - entry.debit_cents
                else:
                    total += entry.debit_cents - entry.credit_cents
        return total

    def ordered_receipts(self, organisation_id: str, loan_id: str) -> tuple[RecognisedReceipt, ...]:
        receipts = [
            RecognisedReceipt(
                transaction.recognised_at,
                transaction.recognition_sequence,
                transaction.amount_cents or 0,
                transaction.attributed_due_on,
            )
            for transaction in self.store.transactions_for(organisation_id, loan_id)
            if transaction.kind == "payment" and transaction.attributed_due_on is not None
        ]
        return order_recognised_events(receipts)

    def _statement(
        self,
        organisation_id: str,
        person_id: str,
        period_start: date,
        period_end: date,
    ) -> Statement:
        loans = tuple(
            account
            for account in self.store.accounts_for(organisation_id)
            if account.person_id == person_id
        )
        lines = []
        for account in loans:
            opening = {
                bucket: self.bucket_balance(account, bucket, as_of=period_start - timedelta(days=1))
                for bucket in ("principal", "interest", "laybye_hold")
            }
            closing = {
                bucket: self.bucket_balance(account, bucket, as_of=period_end)
                for bucket in ("principal", "interest", "laybye_hold")
            }
            lines.append(StatementLine(account.loan_id, opening, closing))
        return Statement(organisation_id, person_id, period_start, period_end, tuple(lines))

    def _loan(self, organisation_id: str, loan_id: str) -> LoanAccount:
        account = self.store.get(organisation_id, loan_id)
        if account.instrument_kind != "loan":
            raise LedgerError(
                "laybye-no-interest",
                "LOCKED_DECISIONS §4: the lay-by hold is not an interest-bearing account.",
            )
        if account.disbursement_value_date is None:
            raise LedgerError(
                "not-disbursed",
                "The loan has not been granted. LOCKED_DECISIONS §4.",
            )
        return account

    def _laybye_child(self, organisation_id: str, parent_loan_id: str) -> LoanAccount:
        parent = self.store.get(organisation_id, parent_loan_id)
        if parent.instrument_kind != "loan":
            raise LedgerError("laybye-parent", "A lay-by hold is a child of a loan, not of another hold.")
        children = self._children(parent)
        if not children:
            raise LedgerError(
                "laybye-missing",
                "LOCKED_DECISIONS §4: there is no Laybye account on this loan.",
            )
        return children[0]

    def _has_kind(self, account: LoanAccount, kind: str) -> bool:
        return any(transaction.kind == kind for transaction in self._tx_for(account))

    def _reject_unset_late_disbursement(self, settings: object, booked: date, quoted: date | None) -> None:
        if quoted is None or booked <= quoted:
            return
        choice = getattr(settings, "late_disbursement", None)
        if choice not in {"adjust_instalment", "keep_instalment"}:
            raise LedgerError(
                "election-unset",
                "Late disbursement is unset. LOCKED_DECISIONS §13 and §19 fail closed.",
            )

    def _children(self, account: LoanAccount) -> tuple[LoanAccount, ...]:
        return tuple(
            other
            for other in self.store.accounts_for(account.organisation_id)
            if other.parent_loan_id == account.loan_id
        )

    def _tx_for(self, account: LoanAccount) -> tuple[Transaction, ...]:
        return self.store.transactions_for(account.organisation_id, account.loan_id)

    def _interest_base(self, account: LoanAccount) -> tuple[int, int, int]:
        principal = self.bucket_balance(account, "principal")
        hold = sum(self.bucket_balance(child, "laybye_hold") for child in self._children(account))
        base = interest_bearing_cents(
            principal_cents=principal,
            capitalised_initiation_cents=account.capitalised_initiation_cents,
            deposit_hold_cents=hold,
            charge_interest_on_initiation=account.snapshot.interest_on_deferred_initiation == "permitted",
        )
        return base, principal, hold

    def _rate_and_divisor(
        self,
        account: LoanAccount,
        day: date,
        repos: tuple[RepoRate, ...],
    ) -> tuple[Decimal, int, int]:
        snapshot = account.snapshot
        if snapshot.classification in _ZERO_PRICE:
            return Decimal(0), 1, 1
        if snapshot.day_count_code is None:
            raise LedgerError(
                "election-unset",
                "Day count is unset. LOCKED_DECISIONS §5 fails closed for a credit product.",
            )
        day_count = _day_count(snapshot.day_count_code)
        weight = accrual_weight(day, day_count)
        fallen = account.discount_fallen_away
        if snapshot.classification == UNSECURED:
            if snapshot.discount_rate != 0:
                raise LedgerError(
                    "unsecured-campaign-base-unset",
                    "LOCKED_DECISIONS §3 stores a base rate minus a discount. It does not "
                    "say whether that discount is taken off the repo margin or off the "
                    "repo-plus-margin contract rate.",
                )
            full = personal_annual_rate(
                day,
                snapshot.base_rate,
                repos,
                advance_date=account.disbursement_value_date,
                repo_fall=_repo_fall(snapshot.repo_rate_fall),
            )
            rate = campaign_rate(full, snapshot.discount_rate, discount_fallen_away=fallen)
            return rate, weight, divisor_days(day, Product.PERSONAL, day_count)
        rate = campaign_rate(
            snapshot.base_rate,
            snapshot.discount_rate,
            discount_fallen_away=fallen,
        )
        return rate, weight, divisor_days(day, Product.MICRO, day_count)

    def _charge(
        self,
        account: LoanAccount,
        *,
        bucket: str,
        cents: int,
        due_on: date,
        recognised_at: datetime,
        kind: str,
        ex_vat_cents: int,
        vat_cents: int,
        extra_effects: tuple[Effect, ...] = (),
    ) -> Transaction:
        sequence = account.next_charge_sequence
        account.next_charge_sequence += 1
        charge_id = str(uuid4())
        effects = [
            Effect(
                "increase_charge",
                cents=cents,
                charge_id=charge_id,
                bucket=bucket,
                due_on=due_on,
                sequence=sequence,
                levied_on=value_date(recognised_at),
                ex_vat_cents=ex_vat_cents,
                vat_cents=vat_cents,
            ),
            *extra_effects,
        ]
        episode = self._open_episode(account)
        if episode is not None and cents:
            effects.append(Effect("increase_accrued", cents=cents, episode_no=episode.episode_no))
        entries: tuple[Entry, ...] = ()
        if cents:
            entries = (
                Entry(f"{bucket}_receivable", bucket, cents, 0),
                Entry(f"{bucket}_income", None, 0, cents),
            )
        transaction = self._post(
            account,
            kind=kind,
            recognised_at=recognised_at,
            entries=entries,
            effects=tuple(effects),
            amount_cents=cents,
        )
        self._assert_consistent(account)
        return transaction

    def _state(self, account: LoanAccount, charges: list[DueCharge], day: date) -> State:
        calc_charges = tuple(
            Charge(
                charge.charge_id,
                _CALC_KIND[charge.bucket],
                charge.levied_on,
                charge.due_on,
                charge.ex_vat_cents,
                charge.vat_cents,
                charge.remaining_cents,
                charge.remaining_cents,
                None,
                charge.sequence,
            )
            for charge in charges
        )
        slices = tuple(
            PrincipalSlice(slice_.due_on, slice_.amount_cents, slice_.remaining_cents, slice_.sequence)
            for slice_ in account.slices
        )
        return State(
            day,
            "open",
            slices,
            calc_charges,
            Decimal(0),
            Decimal(0),
            None,
            0,
            (),
            self._open_episode(account) is not None,
            account.next_charge_sequence,
            (account.episodes[-1].episode_no + 1) if account.episodes else 1,
            0,
            (),
            False,
            0,
            (),
            0,
            None,
            0,
            not account.discount_fallen_away,
        )

    def _charges_of(self, charges: list[DueCharge]) -> list[Charge]:
        return [
            Charge(
                charge.charge_id,
                _CALC_KIND[charge.bucket],
                charge.levied_on,
                charge.due_on,
                charge.ex_vat_cents,
                charge.vat_cents,
                charge.remaining_cents,
                charge.remaining_cents,
                None,
                charge.sequence,
            )
            for charge in charges
        ]

    def _guard_capitalised_reduction(self, account: LoanAccount, principal_cents: int) -> None:
        if principal_cents <= 0 or account.capitalised_initiation_cents <= 0:
            return
        cash_portion = self.bucket_balance(account, "principal") - account.capitalised_initiation_cents
        if account.snapshot.interest_on_deferred_initiation != "permitted" and cash_portion > 0:
            raise LedgerError(
                "capitalised-principal-reduction-unset",
                "LOCKED_DECISIONS §10 does not say whether a principal payment reduces "
                "the capitalised initiation fee or the cash principal first. While the "
                "fee is excluded from the interest base, that choice changes the base, "
                "so the ledger fails closed.",
            )

    def _post(
        self,
        account: LoanAccount,
        *,
        kind: str,
        recognised_at: datetime,
        entries: tuple[Entry, ...],
        effects: tuple[Effect, ...],
        memo_rands: Decimal | None = None,
        value_date_override: date | None = None,
        reverses_transaction_id: str | None = None,
        amount_cents: int | None = None,
        attributed_due_on: date | None = None,
    ) -> Transaction:
        debit = sum(entry.debit_cents for entry in entries)
        credit = sum(entry.credit_cents for entry in entries)
        if debit != credit:
            raise LedgerError("unbalanced", "A ledger transaction must balance.")
        for entry in entries:
            if entry.debit_cents < 0 or entry.credit_cents < 0:
                raise LedgerError("unbalanced", "An entry cannot be negative.")
            if entry.debit_cents and entry.credit_cents:
                raise LedgerError("unbalanced", "An entry is a debit or a credit.")
        transaction = Transaction(
            transaction_id=str(uuid4()),
            organisation_id=account.organisation_id,
            loan_id=account.loan_id,
            kind=kind,
            value_date=value_date_override or value_date(recognised_at),
            recognised_at=recognised_at,
            recognition_sequence=self.store.next_sequence(account.organisation_id),
            reverses_transaction_id=reverses_transaction_id,
            entries=entries,
            effects=effects,
            memo_rands=memo_rands,
            amount_cents=amount_cents,
            attributed_due_on=attributed_due_on,
        )
        self.store.append(transaction)
        self._apply(account, effects)
        return transaction

    def _apply(self, account: LoanAccount, effects: tuple[Effect, ...]) -> None:
        for effect in effects:
            if effect.op == "create_slice":
                account.slices.append(
                    Slice(effect.due_on, effect.cents, effect.cents, effect.sequence or 0)
                )
            elif effect.op == "increase_charge":
                account.charges.append(
                    DueCharge(
                        effect.charge_id or "",
                        effect.bucket or "",
                        effect.due_on or effect.levied_on or account.disbursement_value_date,
                        effect.cents,
                        effect.sequence or 0,
                        effect.levied_on or account.disbursement_value_date,
                        effect.ex_vat_cents,
                        effect.vat_cents,
                    )
                )
            elif effect.op == "decrease_charge":
                charge = self._charge_by_id(account, effect.charge_id or "")
                charge.remaining_cents -= effect.cents
            elif effect.op == "decrease_slice":
                slice_ = self._slice_by_sequence(account, effect.sequence or 0)
                slice_.remaining_cents -= effect.cents
            elif effect.op == "increase_capitalised":
                account.capitalised_initiation_cents += effect.cents
            elif effect.op == "mark_service_month":
                account.service_months.add((effect.year or 0, effect.month or 0))
            elif effect.op == "increase_accrued":
                episode = self._episode(account, effect.episode_no or 0)
                episode.accrued_cents += effect.cents
            elif effect.op == "open_episode":
                account.episodes.append(
                    Episode(effect.episode_no or 0, effect.levied_on or account.disbursement_value_date, effect.cents)
                )
            elif effect.op == "close_episode":
                episode = self._episode(account, effect.episode_no or 0)
                episode.closed_on = effect.levied_on
            elif effect.op == "fall_away":
                account.discount_fallen_away = True
            else:
                raise LedgerError("effect", f"Unknown ledger effect {effect.op}.")

    def _undo(self, account: LoanAccount, effects: tuple[Effect, ...]) -> None:
        for effect in reversed(effects):
            if effect.op == "create_slice":
                slice_ = self._slice_by_sequence(account, effect.sequence or 0)
                if slice_.remaining_cents != effect.cents:
                    raise LedgerError("reversal-undefined", "The slice changed after it was created.")
                account.slices.remove(slice_)
            elif effect.op == "increase_charge":
                charge = self._charge_by_id(account, effect.charge_id or "")
                charge.remaining_cents -= effect.cents
                if charge.remaining_cents == 0:
                    account.charges.remove(charge)
                elif charge.remaining_cents < 0:
                    raise LedgerError("reversal-undefined", "The charge changed after it was levied.")
            elif effect.op == "decrease_charge":
                self._charge_by_id(account, effect.charge_id or "").remaining_cents += effect.cents
            elif effect.op == "decrease_slice":
                self._slice_by_sequence(account, effect.sequence or 0).remaining_cents += effect.cents
            elif effect.op == "increase_capitalised":
                account.capitalised_initiation_cents -= effect.cents
            elif effect.op == "mark_service_month":
                account.service_months.discard((effect.year or 0, effect.month or 0))
            elif effect.op == "increase_accrued":
                self._episode(account, effect.episode_no or 0).accrued_cents -= effect.cents
            else:
                raise LedgerError("reversal-undefined", f"A reversal does not undo {effect.op}.")

    def _assert_consistent(self, account: LoanAccount) -> None:
        if account.instrument_kind != "loan":
            return
        principal = self.bucket_balance(account, "principal")
        if sum(slice_.remaining_cents for slice_ in account.slices) != principal:
            raise LedgerError("invariant", "Principal slices do not match the ledger.")
        if account.capitalised_initiation_cents > principal:
            raise LedgerError("invariant", "Capitalised initiation exceeds principal.")
        for bucket in _COST_BUCKETS:
            charged = sum(charge.remaining_cents for charge in account.charges if charge.bucket == bucket)
            if charged != self.bucket_balance(account, bucket):
                raise LedgerError("invariant", f"{bucket} charges do not match the ledger.")

    def _billed_accrual_cents(self, account: LoanAccount) -> int:
        total = 0
        for transaction in self._tx_for(account):
            if self._root_kind(transaction) != "interest_bill":
                continue
            for entry in transaction.entries:
                if entry.bucket == "interest":
                    total += entry.debit_cents - entry.credit_cents
        return total

    def _root_kind(self, transaction: Transaction) -> str:
        seen: set[str] = set()
        while transaction.reverses_transaction_id is not None and transaction.transaction_id not in seen:
            seen.add(transaction.transaction_id)
            transaction = self.store.get_transaction(
                transaction.organisation_id,
                transaction.reverses_transaction_id,
            )
        return transaction.kind

    def _open_episode(self, account: LoanAccount) -> Episode | None:
        for episode in account.episodes:
            if episode.closed_on is None:
                return episode
        return None

    def _open_episode_effect(self, account: LoanAccount, day: date) -> Effect:
        principal = self.bucket_balance(account, "principal")
        capitalised = account.capitalised_initiation_cents
        ceiling = duplum_base_cents(
            cash_balance_cents=principal - capitalised,
            capitalised_initiation_cents=capitalised,
        )
        episode_no = (account.episodes[-1].episode_no + 1) if account.episodes else 1
        return Effect("open_episode", cents=ceiling, episode_no=episode_no, levied_on=day)

    def _episode(self, account: LoanAccount, episode_no: int) -> Episode:
        for episode in account.episodes:
            if episode.episode_no == episode_no:
                return episode
        raise LedgerError("episode", "The in-duplum episode is not on this loan.")

    def _charge_by_id(self, account: LoanAccount, charge_id: str) -> DueCharge:
        for charge in account.charges:
            if charge.charge_id == charge_id:
                return charge
        raise LedgerError("charge", "The charge is not on this loan.")

    def _slice_by_sequence(self, account: LoanAccount, sequence: int) -> Slice:
        for slice_ in account.slices:
            if slice_.sequence == sequence:
                return slice_
        raise LedgerError("schedule", "The principal slice is not on this loan.")

    def _require_identity(self, name: str, number: str, address: str) -> None:
        if not name.strip() or not number.strip() or not address.strip():
            raise LedgerError(
                "identity-missing",
                "LOCKED_DECISIONS §16 freezes the name, identity number, and service "
                "address at booking. It does not say a blank field can be frozen, so "
                "the ledger refuses the booking.",
            )

    def _require_tariff_or_cap(
        self,
        account: LoanAccount,
        bucket: str,
        *,
        interest_cap_present: bool,
        tariff_cents: int | None,
        repo_annual: Decimal | None,
    ) -> None:
        tariff_required = bucket in {"default_administration", "collection_costs"}
        require_reference_for_posting(
            interest_cap_present=interest_cap_present,
            repo_annual=repo_annual,
            repo_required=account.snapshot.classification == UNSECURED and bucket == "interest",
            tariff_cents=tariff_cents,
            tariff_required=tariff_required,
        )


def resolve_customer_settings_for_booking(organisation: OrganisationSettings, product: ProductTerms):
    """The configuration layer's resolver. Imported lazily is unnecessary; called directly."""
    from lms_config.locked import resolve_customer_settings

    return resolve_customer_settings(organisation, product)


def _day_count(code: str) -> DayCount:
    if code == DAY_COUNT_ACTUAL_ACTUAL:
        return DayCount.ACTUAL
    if code == DAY_COUNT_30_360:
        return DayCount.THIRTY_360
    raise LedgerError(
        "election-unset",
        "Day count must be actual/actual or 30/360. LOCKED_DECISIONS §5.",
    )


def _repo_fall(code: str) -> RepoFallChoice:
    if code == "contract_rate":
        return RepoFallChoice.CONTRACT_RATE_CONTINUES
    if code == "lower_of_contract_and_cap":
        return RepoFallChoice.LOWER_OF_CONTRACT_AND_CAP
    raise LedgerError("election-unset", "Repo-rate fall is unset. LOCKED_DECISIONS §11 and §19.")


def _prepayment(code: str) -> PrepaymentChoice:
    if code == "shorten_term":
        return PrepaymentChoice.SHORTEN_TERM
    if code == "drop_instalment":
        return PrepaymentChoice.DROP_INSTALMENT
    raise LedgerError(
        "election-unset",
        "Partial prepayment is unset. LOCKED_DECISIONS §13 and §19 fail closed.",
    )
