"""Laybye parent/child orchestration.

This module does not calculate interest, section 126 order, the service-fee
cap, or the section 124 amount check. Those calls go to the ledger, the
calculation engine, and configuration.

LOCKED_DECISIONS.md is the source of truth. A point it does not settle is
raised and is not given a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from lms.calc.laybye import guard_s124
from lms.calc.money import RuleError
from lms.laybye.errors import LaybyeError
from lms.ledger.errors import LedgerError
from lms.ledger.models import Accrual, LoanAccount, Transaction
from lms.ledger.service import Ledger
from lms_config.calendar import value_date
from lms_config.locked import OrganisationSettings
from lms_config.validate import ProductTerms

CREDIT_IMPROVEMENT_LOAN_CHILD = "credit-improvement loan child"


@dataclass(frozen=True)
class ReceiptAllocation:
    """One recognised receipt after the loan has been granted. LOCKED_DECISIONS §1 and §4."""

    value_date: date
    loan_cents: int
    laybye_cents: int
    loan_transaction_id: str | None
    laybye_transaction_id: str | None


@dataclass(frozen=True)
class CollectionInstruction:
    """A collection the LMS raises. Not a credit-life account. LOCKED_DECISIONS §4."""

    purpose: str
    cents: int


@dataclass(frozen=True)
class Section124Authority:
    """Facts the LMS holds. Enigma does not store this authority. LOCKED_DECISIONS §4 and §15."""

    mandate_id: str
    authorised_cents: int
    authorised_from: date
    authorised_to: date | None
    signed_in_life: bool


@dataclass(frozen=True)
class CreditLifeProceeds:
    """Insurer cash applied to the loan. The surplus is not posted. LOCKED_DECISIONS §4."""

    value_date: date
    loan_cents: int
    unposted_cents: int
    loan_transaction_id: str | None


@dataclass(frozen=True)
class DeathApplication:
    value_date: date
    applied_cents: int
    hold_cents_after: int
    loan_transaction_id: str | None
    laybye_transaction_id: str | None


def laybye_name(*, mirror_product_name: str | None) -> str:
    """LOCKED_DECISIONS §4. No mirror: credit-improvement loan child. A mirror uses its product name."""
    if mirror_product_name is None:
        return CREDIT_IMPROVEMENT_LOAN_CHILD
    name = mirror_product_name.strip()
    if not name:
        raise LaybyeError(
            "mirror-name-blank",
            "LOCKED_DECISIONS §4: a mirror insurance product is called by its product name. "
            "A blank name fails closed.",
        )
    return name


def day1_treatment(*, mirror_product_name: str | None) -> str:
    """Cash-deposit while no mirror product exists. LOCKED_DECISIONS §4.

    The lock does not say which treatment replaces cash-deposit once a mirror
    exists. That call fails closed.
    """
    if mirror_product_name is None:
        return "cash-deposit"
    laybye_name(mirror_product_name=mirror_product_name)
    raise LaybyeError(
        "mirror-treatment-unset",
        "LOCKED_DECISIONS §4: Day-1 treatment is cash-deposit until a mirror insurance "
        "product exists. It does not say what the treatment becomes after that, "
        "other than the Laybye being called by the product name.",
    )


def prepare_pair(
    ledger: Ledger,
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
    opening_hold_cents: int = 0,
) -> tuple[LoanAccount, LoanAccount]:
    """Parent without a loan-out, plus one Laybye child. LOCKED_DECISIONS §4."""
    if opening_hold_cents < 0:
        raise LaybyeError("laybye", "Lay-by hold cannot be negative.")
    parent = ledger.prepare(
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
        contractual_end=contractual_end,
    )
    child = ledger.open_laybye(
        organisation_id=organisation_id,
        parent_loan_id=parent.loan_id,
        recognised_at=recognised_at,
        amount_cents=opening_hold_cents,
        identity_name=parent.frozen_full_name,
        identity_number=parent.frozen_id_number,
        service_address=parent.frozen_service_address,
    )
    return parent, child


def grant_loan(
    ledger: Ledger,
    *,
    organisation_id: str,
    parent_loan_id: str,
    recognised_at: datetime,
    schedule: tuple[tuple[date, int], ...],
    initiation_fee_cents: int = 0,
) -> LoanAccount:
    """Grant the parent. The hold balance is not an input. LOCKED_DECISIONS §4."""
    before = _hold(ledger, organisation_id, parent_loan_id)
    parent = ledger.grant(
        organisation_id=organisation_id,
        loan_id=parent_loan_id,
        recognised_at=recognised_at,
        schedule=schedule,
        initiation_fee_cents=initiation_fee_cents,
    )
    if _hold(ledger, organisation_id, parent_loan_id) != before:
        raise LaybyeError("laybye-moved", "Granting the loan moved the Laybye hold.")
    return parent


def receive_pre_disbursement(
    ledger: Ledger,
    *,
    organisation_id: str,
    parent_loan_id: str,
    cents: int,
    recognised_at: datetime,
) -> Transaction:
    """Sit the receipt in the Laybye. Cash in, not loan out. LOCKED_DECISIONS §4 and §1."""
    parent = ledger.store.get(organisation_id, parent_loan_id)
    if parent.disbursement_value_date is not None:
        raise LaybyeError(
            "already-granted",
            "LOCKED_DECISIONS §4: once the loan is granted, payments go to the loan first.",
        )
    if not ledger._children(parent):
        raise LaybyeError(
            "laybye-missing",
            "LOCKED_DECISIONS §4: a pre-disbursement receipt sits in the Laybye only "
            "when a Laybye account exists. None exists, so the receipt is not posted.",
        )
    principal_before = ledger.bucket_balance(parent, "principal")
    transaction = ledger.credit_laybye(
        organisation_id=organisation_id,
        parent_loan_id=parent_loan_id,
        cents=cents,
        recognised_at=recognised_at,
    )
    if ledger.bucket_balance(parent, "principal") != principal_before:
        raise LaybyeError(
            "loan-out",
            "LOCKED_DECISIONS §4: a pre-disbursement receipt is cash in, not loan out.",
        )
    if transaction.value_date != value_date(recognised_at):
        raise LaybyeError(
            "value-date",
            "LOCKED_DECISIONS §1: the value date is the recognition date.",
        )
    return transaction


def allocate_receipt(
    ledger: Ledger,
    *,
    organisation_id: str,
    parent_loan_id: str,
    cents: int,
    recognised_at: datetime,
    attributed_due_on: date | None = None,
) -> ReceiptAllocation:
    """Loan first under section 126, then any excess to the Laybye. LOCKED_DECISIONS §4 and §8.

    Due amounts are whatever ``Ledger.section_126_cents`` reports from
    ``allocate_payment``. This does not apply the §13 partial-prepayment
    election to the remainder. That interaction is not stated.
    """
    if cents <= 0:
        raise LaybyeError("payment", "A receipt must be positive.")
    parent = ledger.store.get(organisation_id, parent_loan_id)
    if parent.disbursement_value_date is None:
        raise LaybyeError(
            "not-disbursed",
            "LOCKED_DECISIONS §4: loan-first allocation starts once the loan is granted.",
        )
    loan_cents = ledger.section_126_cents(
        organisation_id=organisation_id,
        loan_id=parent_loan_id,
        cents=cents,
        recognised_at=recognised_at,
    )
    laybye_cents = cents - loan_cents
    if laybye_cents and not ledger._children(parent):
        raise LaybyeError(
            "laybye-missing",
            "LOCKED_DECISIONS §4: excess goes to the Laybye account. None exists, "
            "so the receipt is not posted.",
        )
    if loan_cents and attributed_due_on is None:
        raise LaybyeError(
            "due-date-attribution-unset",
            "LOCKED_DECISIONS §6 compares the amount received for a due date. "
            "A loan portion without an attributed due date is not posted.",
        )
    loan_transaction_id = None
    laybye_transaction_id = None
    if loan_cents:
        payment = ledger.post_payment(
            organisation_id=organisation_id,
            loan_id=parent_loan_id,
            cents=loan_cents,
            recognised_at=recognised_at,
            attributed_due_on=attributed_due_on,
        )
        loan_transaction_id = payment.transaction_id
        if payment.value_date != value_date(recognised_at):
            raise LaybyeError(
                "value-date",
                "LOCKED_DECISIONS §1: the value date is the recognition date.",
            )
    if laybye_cents:
        deposit = ledger.credit_laybye(
            organisation_id=organisation_id,
            parent_loan_id=parent_loan_id,
            cents=laybye_cents,
            recognised_at=recognised_at,
        )
        laybye_transaction_id = deposit.transaction_id
    return ReceiptAllocation(
        value_date=value_date(recognised_at),
        loan_cents=loan_cents,
        laybye_cents=laybye_cents,
        loan_transaction_id=loan_transaction_id,
        laybye_transaction_id=laybye_transaction_id,
    )


def accrue_parent(
    ledger: Ledger,
    *,
    organisation_id: str,
    parent_loan_id: str,
    recognised_at: datetime,
    interest_cap_present: bool,
) -> Accrual:
    """Interest on the ledger's net base. The hold is not subtracted again. LOCKED_DECISIONS §4 and §5."""
    return ledger.accrue_day(
        organisation_id=organisation_id,
        loan_id=parent_loan_id,
        recognised_at=recognised_at,
        interest_cap_present=interest_cap_present,
    )


def levy_parent_service_fee(
    ledger: Ledger,
    *,
    organisation_id: str,
    loan_id: str,
    recognised_at: datetime,
    monthly_cents: int,
    due_on: date,
    interest_cap_present: bool,
    vat_rate: Decimal,
    vat_registered: bool = True,
    opening: bool = False,
    first_due: date | None = None,
) -> Transaction:
    """One monthly service fee, on the parent. LOCKED_DECISIONS §4 and §9."""
    return ledger.levy_service_fee(
        organisation_id=organisation_id,
        loan_id=loan_id,
        recognised_at=recognised_at,
        monthly_cents=monthly_cents,
        due_on=due_on,
        interest_cap_present=interest_cap_present,
        vat_rate=vat_rate,
        vat_registered=vat_registered,
        opening=opening,
        first_due=first_due,
    )


def raise_collections(
    *,
    automated: bool,
    loan_instalment_cents: int,
    credit_life_premium_cents: int | None,
) -> tuple[CollectionInstruction, ...]:
    """Two collections when automation is on. No credit-life account is opened. LOCKED_DECISIONS §4.

    When collections are not automated from the LMS, this returns no instructions.
    The lock does not describe that path.
    """
    if loan_instalment_cents < 0:
        raise LaybyeError("collection", "The loan instalment cannot be negative.")
    if not automated:
        return ()
    if credit_life_premium_cents is None:
        raise LaybyeError(
            "premium-unknown",
            "LOCKED_DECISIONS §4: automated collections need the credit-life premium amount.",
        )
    if credit_life_premium_cents < 0:
        raise LaybyeError("collection", "The credit-life premium cannot be negative.")
    return (
        CollectionInstruction("loan_instalment", loan_instalment_cents),
        CollectionInstruction("credit_life_premium", credit_life_premium_cents),
    )


def apply_credit_life_proceeds(
    ledger: Ledger,
    *,
    organisation_id: str,
    parent_loan_id: str,
    cents: int,
    recognised_at: datetime,
    attributed_due_on: date | None,
) -> CreditLifeProceeds:
    """Pay the loan first. Do not open a credit-life account and do not fund the Laybye.

    LOCKED_DECISIONS §4. Surplus goes to the estate under the cash-deposit
    treatment. No estate account or payee exists, so the surplus is not posted.
    """
    if cents <= 0:
        raise LaybyeError("payment", "Credit-life proceeds must be positive.")
    hold_before = _hold(ledger, organisation_id, parent_loan_id)
    loan_cents = ledger.section_126_cents(
        organisation_id=organisation_id,
        loan_id=parent_loan_id,
        cents=cents,
        recognised_at=recognised_at,
    )
    if loan_cents and attributed_due_on is None:
        raise LaybyeError(
            "due-date-attribution-unset",
            "LOCKED_DECISIONS §6 compares the amount received for a due date.",
        )
    loan_transaction_id = None
    if loan_cents:
        payment = ledger.post_payment(
            organisation_id=organisation_id,
            loan_id=parent_loan_id,
            cents=loan_cents,
            recognised_at=recognised_at,
            attributed_due_on=attributed_due_on,
        )
        loan_transaction_id = payment.transaction_id
    if _hold(ledger, organisation_id, parent_loan_id) != hold_before:
        raise LaybyeError("laybye-moved", "Credit-life proceeds moved the Laybye hold.")
    return CreditLifeProceeds(
        value_date=value_date(recognised_at),
        loan_cents=loan_cents,
        unposted_cents=cents - loan_cents,
        loan_transaction_id=loan_transaction_id,
    )


def store_funeral_beneficiary(name: str) -> None:
    """The beneficiary sits with the insurer. LOCKED_DECISIONS §4."""
    del name
    raise LaybyeError(
        "beneficiary-not-in-lms",
        "LOCKED_DECISIONS §4: the funeral beneficiary sits with the insurer, not in the LMS.",
    )


def apply_on_death(
    ledger: Ledger,
    *,
    organisation_id: str,
    parent_loan_id: str,
    recognised_at: datetime,
    requested_cents: int,
    authority: Section124Authority | None,
    attributed_due_on: date | None,
) -> DeathApplication:
    """Apply the hold on death only with a section 124 authority signed in life. LOCKED_DECISIONS §4.

    Credit-life proceeds are not posted here and are not stored as an LMS account.
    The amount applied is capped by ``guard_s124`` and by the due amount the
    ledger will take under section 126. A shortfall above that due amount is
    not posted: the ledger has no settlement posting for undue principal.
    """
    on = value_date(recognised_at)
    hold_before = _hold(ledger, organisation_id, parent_loan_id)
    if authority is None or not authority.signed_in_life or not authority.mandate_id.strip():
        raise LaybyeError(
            "s124-missing",
            "LOCKED_DECISIONS §4: death may not apply the Laybye without a section 124 "
            "authority signed in life. The hold stays with the estate.",
        )
    if requested_cents <= 0:
        raise LaybyeError("s124-amount", "A death application must be positive.")
    try:
        allowed = guard_s124(
            mandate_id=authority.mandate_id,
            authorised_cents=authority.authorised_cents,
            requested_cents=requested_cents,
            on=on,
            authorised_from=authority.authorised_from,
            authorised_to=authority.authorised_to,
        )
    except RuleError as exc:
        raise LaybyeError(exc.code, str(exc)) from exc
    if allowed > hold_before:
        raise LaybyeError("laybye", "The Laybye hold is smaller than the application.")
    loan_cents = ledger.section_126_cents(
        organisation_id=organisation_id,
        loan_id=parent_loan_id,
        cents=allowed,
        recognised_at=recognised_at,
    )
    if loan_cents != allowed:
        raise LaybyeError(
            "shortfall-beyond-section-126",
            "LOCKED_DECISIONS §4 says the Laybye covers any shortfall. The ledger can "
            "post only the due section 126 amount. The remainder is not given a posting.",
        )
    if attributed_due_on is None:
        raise LaybyeError(
            "due-date-attribution-unset",
            "LOCKED_DECISIONS §6 compares the amount received for a due date.",
        )
    laybye_tx = ledger.debit_laybye(
        organisation_id=organisation_id,
        parent_loan_id=parent_loan_id,
        cents=loan_cents,
        recognised_at=recognised_at,
    )
    try:
        loan_tx = ledger.post_payment(
            organisation_id=organisation_id,
            loan_id=parent_loan_id,
            cents=loan_cents,
            recognised_at=recognised_at,
            attributed_due_on=attributed_due_on,
        )
    except LedgerError:
        ledger.reverse(
            organisation_id=organisation_id,
            transaction_id=laybye_tx.transaction_id,
            recognised_at=recognised_at,
        )
        raise
    return DeathApplication(
        value_date=on,
        applied_cents=loan_cents,
        hold_cents_after=_hold(ledger, organisation_id, parent_loan_id),
        loan_transaction_id=loan_tx.transaction_id,
        laybye_transaction_id=laybye_tx.transaction_id,
    )


def top_up(ledger: Ledger, *, organisation_id: str, parent_loan_id: str) -> None:
    """A top-up uses the ordinary loan path. There is no such path. LOCKED_DECISIONS §4 and §13.

    The hold is not read and not written.
    """
    del ledger, organisation_id, parent_loan_id
    raise LaybyeError(
        "top-up-undefined",
        "LOCKED_DECISIONS §4: a loan top-up is treated like any other loan top-up, "
        "and the linked Laybye does not change that treatment. Layer 0 has no "
        "top-up posting. This layer does not invent the price, schedule, or journal.",
    )


def _hold(ledger: Ledger, organisation_id: str, parent_loan_id: str) -> int:
    parent = ledger.store.get(organisation_id, parent_loan_id)
    return sum(ledger.bucket_balance(child, "laybye_hold") for child in ledger._children(parent))
