"""Payment rails. Calls the ledger and the calculation engine. Does not re-implement them.

Capitalisation is ``Ledger.accrue_day``, ``Ledger.bill_interest`` and
``Ledger.levy_service_fee``. Allocation is ``Servicing.accept_payment``, which
posts through ``Ledger.post_payment`` and ``allocate_payment``. Section 126
order, fee rank, and cent rounding stay in those interfaces.

LOCKED_DECISIONS.md is the source of truth. A point it does not settle is
recorded as a gap and is not given a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from lms.laybye.errors import LaybyeError
from lms.laybye.service import raise_collections
from lms.ledger.errors import LedgerError
from lms.ledger.models import LoanAccount
from lms.payments.bankserv import BankservTransaction, render_collections_file, user_reference
from lms.payments.dummies import DebitOrderRailPort, DecisionEnginePort
from lms.payments.errors import PaymentRailError
from lms.payments.flags import DEBIT_ORDERS_ENABLED, FeatureFlags
from lms.payments.loan_numbers import LoanNumberSeries
from lms.payments.models import (
    CollectionInstructionRecord,
    CollectionMandate,
    DebitOrderFile,
    InboundReceipt,
    RailReceipt,
)
from lms.servicing.errors import ServicingError
from lms.servicing.service import AgreementRecord, Servicing
from lms_config.calendar import value_date, value_instant
from lms_config.compliance import ComplianceStore
from lms_config.exceptions import CalculationInputError
from lms_config.locked import RecognisedReceipt, order_recognised_events

_LOAN_PURPOSE = "loan_instalment"
_PREMIUM_PURPOSE = "credit_life_premium"
_PURPOSES = {_LOAN_PURPOSE, _PREMIUM_PURPOSE}
_SCHEMES = {"eft", "debicheck"}
_ALLOCATABLE = {"active", "in_arrears"}
_ROLE = "lms.payments.write"


@dataclass
class PaymentRail:
    """Debit-order files and receipt intake for one process."""

    servicing: Servicing
    rail: DebitOrderRailPort
    decision_engine: DecisionEnginePort
    compliance: ComplianceStore
    flags: FeatureFlags
    loan_numbers: LoanNumberSeries = field(default_factory=LoanNumberSeries)
    mandates: dict[str, CollectionMandate] = field(default_factory=dict)
    receipts: dict[str, RailReceipt] = field(default_factory=dict)
    files: dict[str, DebitOrderFile] = field(default_factory=dict)
    _sequence: int = 1
    _idempotency: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)

    def register_loan_number(
        self,
        *,
        organisation_id: str,
        agreement_id: str,
        application_number: str,
        recognised_at: datetime,
        actor_id: str,
        laybye: bool = False,
    ) -> str:
        """Issue the LMS loan number and link it to the application number. §25."""
        _aware(recognised_at)
        agreement = self._agreement(agreement_id, organisation_id)
        if agreement.ledger_loan_id is None:
            raise PaymentRailError("not-disbursed", "A loan number is issued after the loan is disbursed.")
        self._actor(organisation_id, actor_id)
        ledger_loan_id = agreement.laybye_loan_id if laybye else agreement.ledger_loan_id
        if laybye and not ledger_loan_id:
            raise PaymentRailError(
                "laybye-missing",
                "LOCKED_DECISIONS §25: the Laybye indicator needs the Laybye account.",
            )
        prior = self.loan_numbers.find_application(organisation_id, application_number)
        prior_indicator = None if prior is None else prior.laybye_indicator
        record = self.loan_numbers.issue(
            organisation_id=organisation_id,
            application_number=application_number,
            agreement_id=agreement.agreement_id,
            ledger_loan_id=ledger_loan_id or agreement.ledger_loan_id,
            laybye=laybye,
        )
        if prior is not None and not (laybye and prior_indicator is None):
            return record.loan_number
        self._audit(
            organisation_id=organisation_id,
            occurred_at=recognised_at,
            event_type="LOAN_NUMBER_ISSUED",
            category="operational",
            agreement_id=agreement.agreement_id,
            enigma_person_id=actor_id,
            payload={
                "loan_number": record.loan_number,
                "application_number": application_number,
                "laybye": laybye,
            },
        )
        return record.loan_number

    def put_mandate(self, agreement_id: str, mandate: CollectionMandate) -> None:
        """Store the collection account and scheme. Unset fields fail when a file is generated."""
        self.mandates[agreement_id] = mandate

    def generate_debit_order_file(
        self,
        *,
        organisation_id: str,
        due_on: date,
        recognised_at: datetime,
        actor_id: str,
        agreement_ids: tuple[str, ...],
        idempotency_key: str,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
    ) -> DebitOrderFile:
        """Build a Bankserv collections file and hand it to the debit-order rail."""
        _aware(recognised_at)
        if not agreement_ids:
            raise PaymentRailError("nothing-to-collect", "Name at least one agreement.")
        fingerprint = _fingerprint(
            {
                "organisation_id": organisation_id,
                "due_on": due_on.isoformat(),
                "recognised_at": recognised_at.isoformat(),
                "agreement_ids": list(agreement_ids),
                "interest_cap_present": interest_cap_present,
                "vat_rate": None if vat_rate is None else str(vat_rate),
            }
        )
        replay = self._replay("file", organisation_id, idempotency_key, fingerprint)
        if replay is not None:
            return self.files[replay]
        self._actor(organisation_id, actor_id)
        automated = self._automated(organisation_id)
        if not automated:
            raise PaymentRailError(
                "not-automated",
                "LOCKED_DECISIONS §4: the LMS raises collections when they are automated. "
                "debit_orders_enabled is false, so no file is submitted.",
            )
        recognition = value_date(recognised_at)
        provider = self.compliance.require(organisation_id)
        abbreviated = _abbreviated_name(provider.trading_name, provider.legal_name)
        instructions: list[CollectionInstructionRecord] = []
        transactions: list[BankservTransaction] = []
        for agreement_id in agreement_ids:
            agreement = self._agreement(agreement_id, organisation_id)
            if agreement.status not in _ALLOCATABLE or agreement.ledger_loan_id is None:
                raise PaymentRailError("status", f"No debit order for an agreement in {agreement.status}.")
            number = self.loan_numbers.find_by_agreement(organisation_id, agreement.agreement_id)
            if number is None:
                raise PaymentRailError(
                    "loan-number-unset",
                    "LOCKED_DECISIONS §25: the LMS loan number is not on this agreement.",
                )
            mandate = self.mandates.get(agreement.agreement_id)
            if mandate is None:
                raise PaymentRailError(
                    "mandate-unset",
                    "The debtor account and collection scheme are not stored. The file is not generated.",
                )
            self._validate_mandate(mandate)
            if recognition >= due_on:
                self.capitalise_due_amounts(
                    agreement,
                    recognition,
                    interest_cap_present=interest_cap_present,
                    vat_rate=vat_rate,
                )
            account = self.servicing.ledger.store.get(organisation_id, agreement.ledger_loan_id)
            instalment = instalment_outstanding_cents(account, due_on)
            premium = self.decision_engine.credit_life_premium_cents(
                organisation_id=organisation_id,
                application_number=number.application_number,
                loan_number=number.loan_number,
                due_on=due_on,
            )
            try:
                raised = raise_collections(
                    automated=True,
                    loan_instalment_cents=instalment,
                    credit_life_premium_cents=premium,
                )
            except LaybyeError as exc:
                raise _from_downstream(exc) from exc
            reference = mandate.mandate_reference if mandate.scheme == "debicheck" else number.loan_number
            if reference is None:
                raise PaymentRailError("mandate-unset", "A DebiCheck collection needs a mandate reference.")
            for item in raised:
                record = CollectionInstructionRecord(
                    loan_number=number.loan_number,
                    amount_cents=item.cents,
                    due_on=due_on,
                    recognition_date=recognition,
                    credit_life_premium_cents=premium if premium is not None else 0,
                    purpose=item.purpose,
                    scheme=mandate.scheme,
                    agreement_id=agreement.agreement_id,
                    application_number=number.application_number,
                    mandate_reference=mandate.mandate_reference,
                    tracking_indicator=mandate.tracking_indicator,
                )
                instructions.append(record)
                if item.cents <= 0:
                    continue
                transactions.append(
                    BankservTransaction(
                        user_branch=provider.branch_code,
                        user_account=provider.bank_account_number,
                        sequence=len(transactions) + 1,
                        homing_branch=mandate.debtor.branch_code,
                        homing_account=mandate.debtor.account_number,
                        account_type=mandate.debtor.account_type,
                        amount_cents=item.cents,
                        abbreviated_name=abbreviated,
                        user_reference=user_reference(
                            scheme=mandate.scheme,
                            purpose=item.purpose,
                            reference=reference,
                        ),
                        homing_name=mandate.debtor.account_name or agreement.frozen_full_name,
                    )
                )
        body = render_collections_file(tuple(transactions), action_date=due_on)
        produced = DebitOrderFile(
            organisation_id=organisation_id,
            recognition_date=recognition,
            due_on=due_on,
            instructions=tuple(instructions),
            body=body,
        )
        submission_id = self.rail.submit(produced)
        stored = DebitOrderFile(
            organisation_id=produced.organisation_id,
            recognition_date=produced.recognition_date,
            due_on=produced.due_on,
            instructions=produced.instructions,
            body=produced.body,
            submission_id=submission_id,
        )
        self.files[submission_id] = stored
        self._remember("file", organisation_id, idempotency_key, fingerprint, submission_id)
        self._audit(
            organisation_id=organisation_id,
            occurred_at=recognised_at,
            event_type="DEBIT_ORDER_SUBMITTED",
            category="operational",
            enigma_person_id=actor_id,
            payload={
                "submission_id": submission_id,
                "due_on": due_on.isoformat(),
                "recognition_date": recognition.isoformat(),
                "instruction_count": len(stored.instructions),
                "loan_numbers": [item.loan_number for item in stored.instructions],
            },
        )
        return stored

    def capitalise_due_amounts(
        self,
        agreement: AgreementRecord,
        recognition_date: date,
        *,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
    ) -> None:
        """Accrue through the recognition date, then capitalise amounts that are due.

        Interest is billed on the latest instalment due date on or before the
        recognition date, via ``Ledger.bill_interest``. A payment date that is
        not yet an instalment due date is accrued and not billed. Unbilled
        interest stays out of allocation. §6 and §8.

        Whether the accrual on the due date itself is due that day is not
        settled by the lock. ``bill_interest`` debits the whole unbilled memo,
        which includes that day's accrual because accrual runs first.
        """
        if interest_cap_present is None:
            raise PaymentRailError(
                "election-unset",
                "Interest capitalisation needs interest_cap_present. It is not assumed.",
            )
        if agreement.ledger_loan_id is None:
            raise PaymentRailError("not-disbursed", "The agreement has not been disbursed.")
        account = self.servicing.ledger.store.get(agreement.organisation_id, agreement.ledger_loan_id)
        self._accrue_through(agreement, account, recognition_date, interest_cap_present)
        due_dates = sorted(due for due, _amount in agreement.schedule if due <= recognition_date)
        if not due_dates:
            return
        try:
            self.servicing.ledger.bill_interest(
                organisation_id=agreement.organisation_id,
                loan_id=account.loan_id,
                recognised_at=value_instant(due_dates[-1]),
            )
        except LedgerError as exc:
            raise _from_downstream(exc) from exc
        except CalculationInputError as exc:
            raise PaymentRailError("election-unset", str(exc)) from exc
        self._levy_service_fees(
            agreement,
            account,
            recognition_date,
            vat_rate=vat_rate,
            interest_cap_present=interest_cap_present,
        )

    def accept_receipts(
        self,
        organisation_id: str,
        receipts: tuple[InboundReceipt, ...],
        *,
        actor_id: str,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
    ) -> tuple[RailReceipt, ...]:
        """Recognise a batch. Same-day receipts follow recognition sequence. §1.

        Capitalise the day's due amounts once the batch is in value-date order,
        then allocate each loan receipt.
        """
        self._actor(organisation_id, actor_id)
        prepared: list[tuple[int, InboundReceipt]] = []
        replayed: list[RailReceipt] = []
        for item in receipts:
            _aware(item.recognised_at)
            fingerprint = _receipt_fingerprint(organisation_id, item)
            replay = self._replay("receipt", organisation_id, item.idempotency_key, fingerprint)
            if replay is not None:
                replayed.append(self.receipts[replay])
                continue
            prepared.append((self._sequence, item))
            self._sequence += 1
        ordered = _order_inbound(prepared)
        accepted: list[RailReceipt] = []
        for sequence, item in ordered:
            accepted.append(
                self._accept_one(
                    organisation_id,
                    item,
                    sequence=sequence,
                    actor_id=actor_id,
                    interest_cap_present=interest_cap_present,
                    vat_rate=vat_rate,
                )
            )
        return tuple(replayed + accepted)

    def intake_from_rail(
        self,
        organisation_id: str,
        *,
        actor_id: str,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
    ) -> tuple[RailReceipt, ...]:
        """Take whatever the debit-order rail dummy (or a later rail) has queued."""
        return self.accept_receipts(
            organisation_id,
            self.rail.take_receipts(),
            actor_id=actor_id,
            interest_cap_present=interest_cap_present,
            vat_rate=vat_rate,
        )

    def match_receipt(
        self,
        receipt_id: str,
        *,
        actor_id: str,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
        loan_number: str | None = None,
        id_number: str | None = None,
        attributed_due_on: date | None = None,
    ) -> RailReceipt:
        """Match an unmatched receipt on loan number or ID number. §26.

        The value date stays the original recognition date. Zero matches or more
        than one match leave the receipt unapplied.
        """
        receipt = self._receipt(receipt_id)
        self._actor(receipt.organisation_id, actor_id)
        if receipt.status == "allocated":
            return receipt
        if receipt.status != "unapplied":
            raise PaymentRailError("payment", f"Cannot match a receipt in {receipt.status}.")
        if loan_number:
            receipt.loan_number = loan_number
        if id_number:
            receipt.id_number = id_number
        if attributed_due_on is not None:
            receipt.attributed_due_on = attributed_due_on
        agreement = self._resolve(receipt.organisation_id, receipt)
        if agreement is None:
            return receipt
        self._allocate_loan(receipt, agreement, interest_cap_present=interest_cap_present, vat_rate=vat_rate)
        return receipt

    def return_unpaid(
        self,
        receipt_id: str,
        *,
        recognised_at: datetime,
        actor_id: str,
    ) -> RailReceipt:
        """A returned unpaid item.

        After a write-off the item is flagged only. The balance is not reopened
        and no recovery is posted. §8 and §26. Before a write-off the original
        receipt is reversed through the ledger, and the reopened balance is flagged
        so a further write-off can be approved.
        """
        _aware(recognised_at)
        receipt = self._receipt(receipt_id)
        self._actor(receipt.organisation_id, actor_id)
        if receipt.status in {"returned_flagged", "reversed"} and receipt.flag:
            return receipt
        agreement = self.servicing.agreements.get(receipt.agreement_id) if receipt.agreement_id else None
        written_off = agreement is not None and _written_off(self.servicing, agreement)
        if written_off or receipt.status in {"not_posted", "insurer_accepted", "unapplied"}:
            if written_off:
                receipt.flag = "returned_unpaid_after_write_off"
                event = "RETURNED_UNPAID_FLAGGED"
            elif receipt.status == "unapplied":
                receipt.flag = "returned_unpaid"
                event = "RETURNED_UNPAID_FLAGGED"
            else:
                receipt.flag = "returned_unpaid"
                event = "RETURNED_UNPAID_FLAGGED"
            receipt.status = "returned_flagged"
            self._audit(
                organisation_id=receipt.organisation_id,
                occurred_at=recognised_at,
                event_type=event,
                category="operational",
                agreement_id=receipt.agreement_id,
                enigma_person_id=actor_id,
                payload={"receipt_id": receipt.receipt_id, "flag": receipt.flag},
            )
            return receipt
        if receipt.status != "allocated" or receipt.servicing_payment_id is None:
            raise PaymentRailError("payment", f"Cannot return a receipt in {receipt.status}.")
        try:
            self.servicing.reverse_payment(receipt.servicing_payment_id, recognised_at=recognised_at)
        except ServicingError as exc:
            raise _from_downstream(exc) from exc
        receipt.status = "reversed"
        receipt.flag = "write_off_approval_required"
        self._audit(
            organisation_id=receipt.organisation_id,
            occurred_at=recognised_at,
            event_type="RETURNED_UNPAID_FLAGGED",
            category="operational",
            agreement_id=receipt.agreement_id,
            enigma_person_id=actor_id,
            payload={"receipt_id": receipt.receipt_id, "flag": receipt.flag},
        )
        return receipt

    def _accept_one(
        self,
        organisation_id: str,
        item: InboundReceipt,
        *,
        sequence: int,
        actor_id: str,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
    ) -> RailReceipt:
        if type(item.amount_cents) is not int or item.amount_cents <= 0:
            raise PaymentRailError("payment", "A receipt amount must be a positive number of integer cents.")
        if item.purpose is not None and item.purpose not in _PURPOSES:
            raise PaymentRailError(
                "purpose-unset",
                "A receipt purpose is the loan instalment or the credit-life premium. It is not inferred.",
            )
        fingerprint = _receipt_fingerprint(organisation_id, item)
        replay = self._replay("receipt", organisation_id, item.idempotency_key, fingerprint)
        if replay is not None:
            return self.receipts[replay]
        receipt = RailReceipt(
            receipt_id=str(uuid4()),
            organisation_id=organisation_id,
            amount_cents=item.amount_cents,
            recognised_at=item.recognised_at,
            value_date=value_date(item.recognised_at),
            sequence=sequence,
            status="unapplied",
            purpose=item.purpose,
            loan_number=item.loan_number,
            id_number=item.id_number,
            agreement_id=item.agreement_id,
            attributed_due_on=item.attributed_due_on,
        )
        agreement = self._resolve(organisation_id, receipt)
        if agreement is not None and _written_off(self.servicing, agreement):
            receipt.agreement_id = agreement.agreement_id
            receipt.status = "not_posted"
            receipt.flag = "recovery_outside_lms"
            self._store_receipt(receipt, item.idempotency_key, fingerprint)
            self._audit(
                organisation_id=organisation_id,
                occurred_at=item.recognised_at,
                event_type="RECOVERY_NOT_POSTED",
                category="operational",
                agreement_id=agreement.agreement_id,
                enigma_person_id=actor_id,
                payload={"receipt_id": receipt.receipt_id, "flag": receipt.flag},
            )
            return receipt
        if item.purpose == _PREMIUM_PURPOSE:
            if agreement is not None:
                receipt.agreement_id = agreement.agreement_id
            receipt.status = "insurer_accepted"
            self._store_receipt(receipt, item.idempotency_key, fingerprint)
            self._audit(
                organisation_id=organisation_id,
                occurred_at=item.recognised_at,
                event_type="CREDIT_LIFE_PREMIUM_RECEIVED",
                category="operational",
                agreement_id=receipt.agreement_id,
                enigma_person_id=actor_id,
                payload={"receipt_id": receipt.receipt_id, "amount_cents": item.amount_cents},
            )
            return receipt
        if agreement is None:
            self._store_receipt(receipt, item.idempotency_key, fingerprint)
            self._audit(
                organisation_id=organisation_id,
                occurred_at=item.recognised_at,
                event_type="RECEIPT_HELD_UNAPPLIED",
                category="operational",
                enigma_person_id=actor_id,
                payload={"receipt_id": receipt.receipt_id, "amount_cents": item.amount_cents},
            )
            return receipt
        self._allocate_loan(
            receipt,
            agreement,
            interest_cap_present=interest_cap_present,
            vat_rate=vat_rate,
            idempotency_key=item.idempotency_key,
        )
        self._store_receipt(receipt, item.idempotency_key, fingerprint)
        return receipt

    def _allocate_loan(
        self,
        receipt: RailReceipt,
        agreement: AgreementRecord,
        *,
        interest_cap_present: bool | None,
        vat_rate: Decimal | None,
        idempotency_key: str = "",
    ) -> None:
        if receipt.attributed_due_on is None:
            raise PaymentRailError(
                "due-date-attribution-unset",
                "LOCKED_DECISIONS §6 compares the amount received for a due date. "
                "The receipt does not name one, so it is not allocated.",
            )
        if agreement.status not in _ALLOCATABLE:
            raise PaymentRailError("status", f"Cannot allocate to an agreement in {agreement.status}.")
        self.capitalise_due_amounts(
            agreement,
            receipt.value_date,
            interest_cap_present=interest_cap_present,
            vat_rate=vat_rate,
        )
        try:
            payment = self.servicing.accept_payment(
                organisation_id=receipt.organisation_id,
                person_id=agreement.person_id,
                cents=receipt.amount_cents,
                recognised_at=receipt.recognised_at,
                idempotency_key=idempotency_key or receipt.receipt_id,
                agreement_id=agreement.agreement_id,
                attributed_due_on=receipt.attributed_due_on,
            )
        except ServicingError as exc:
            raise _from_downstream(exc) from exc
        receipt.agreement_id = agreement.agreement_id
        receipt.servicing_payment_id = payment.payment_id
        receipt.ledger_transaction_id = payment.ledger_transaction_id
        receipt.allocations = payment.allocations
        receipt.status = payment.status
        if payment.value_date != receipt.value_date:
            raise PaymentRailError(
                "value-date",
                "LOCKED_DECISIONS §1: the recognition date is the Johannesburg calendar date.",
            )

    def _accrue_through(
        self,
        agreement: AgreementRecord,
        account: LoanAccount,
        recognition_date: date,
        interest_cap_present: bool,
    ) -> None:
        if account.disbursement_value_date is None:
            raise PaymentRailError("not-disbursed", "The loan has not been granted.")
        end = min(recognition_date, account.contractual_end)
        day = account.disbursement_value_date
        while day <= end:
            try:
                self.servicing.ledger.accrue_day(
                    organisation_id=agreement.organisation_id,
                    loan_id=account.loan_id,
                    recognised_at=value_instant(day),
                    interest_cap_present=interest_cap_present,
                )
            except LedgerError as exc:
                if exc.code not in {"already-accrued", "outside-term"}:
                    raise _from_downstream(exc) from exc
            except CalculationInputError as exc:
                raise PaymentRailError("election-unset", str(exc)) from exc
            day += timedelta(days=1)

    def _levy_service_fees(
        self,
        agreement: AgreementRecord,
        account: LoanAccount,
        recognition_date: date,
        *,
        vat_rate: Decimal | None,
        interest_cap_present: bool,
    ) -> None:
        monthly = _service_fee_cents(agreement)
        if monthly == 0 or account.disbursement_value_date is None:
            return
        if vat_rate is None:
            raise PaymentRailError(
                "vat-rate-unset",
                "LOCKED_DECISIONS §9: the LMS calculates VAT. No rate was supplied, and none is assumed.",
            )
        first_due = min(due for due, _amount in agreement.schedule)
        disbursement = account.disbursement_value_date
        if recognition_date >= first_due:
            self._levy_once(
                agreement,
                account,
                recognised_at=value_instant(disbursement),
                monthly_cents=monthly,
                due_on=first_due,
                interest_cap_present=interest_cap_present,
                vat_rate=vat_rate,
                opening=True,
                first_due=first_due,
            )
        seen_months: set[tuple[int, int]] = set()
        for due, _amount in sorted(agreement.schedule):
            if due > recognition_date:
                continue
            month = (due.year, due.month)
            if month == (disbursement.year, disbursement.month) or month in seen_months:
                continue
            seen_months.add(month)
            self._levy_once(
                agreement,
                account,
                recognised_at=value_instant(due),
                monthly_cents=monthly,
                due_on=due,
                interest_cap_present=interest_cap_present,
                vat_rate=vat_rate,
                opening=False,
                first_due=None,
            )

    def _levy_once(self, agreement, account, **kwargs) -> None:
        try:
            self.servicing.ledger.levy_service_fee(
                organisation_id=agreement.organisation_id,
                loan_id=account.loan_id,
                **kwargs,
            )
        except LedgerError as exc:
            if exc.code != "service-fee-once":
                raise _from_downstream(exc) from exc
        except CalculationInputError as exc:
            raise PaymentRailError("election-unset", str(exc)) from exc

    def _resolve(self, organisation_id: str, receipt: RailReceipt) -> AgreementRecord | None:
        """Exactly one agreement, or none. Loan number or ID number. §12 and §26."""
        found: dict[str, AgreementRecord] = {}
        if receipt.agreement_id:
            named = self.servicing.agreements.get(receipt.agreement_id)
            if named is None or named.organisation_id != organisation_id:
                return None
            found[named.agreement_id] = named
        if receipt.loan_number:
            record = self.loan_numbers.find(organisation_id, receipt.loan_number)
            if record is None:
                return None
            named = self.servicing.agreements.get(record.agreement_id)
            if named is None:
                return None
            found[named.agreement_id] = named
        if len(found) > 1:
            return None
        chosen = next(iter(found.values())) if found else None
        if not receipt.id_number:
            return chosen
        matches = [
            agreement
            for agreement in self.servicing.agreements.values()
            if agreement.organisation_id == organisation_id
            and agreement.frozen_id_number == receipt.id_number
            and agreement.ledger_loan_id is not None
        ]
        if chosen is not None:
            if chosen.frozen_id_number != receipt.id_number:
                return None
            return chosen
        if len(matches) == 1:
            return matches[0]
        return None

    def _automated(self, organisation_id: str) -> bool:
        flag = self.flags.get(organisation_id, DEBIT_ORDERS_ENABLED)
        if flag is None:
            raise PaymentRailError(
                "election-unset",
                "debit_orders_enabled is not set for this organisation. "
                "LOCKED_DECISIONS §19: an unset election fails closed. "
                "The lock does not say this catalogue flag is the section 4 automation switch.",
            )
        return flag

    def _validate_mandate(self, mandate: CollectionMandate) -> None:
        if mandate.scheme not in _SCHEMES:
            raise PaymentRailError(
                "scheme-unset",
                "The collection scheme is eft or debicheck. It is not assumed.",
            )
        debtor = mandate.debtor
        if not debtor.branch_code or not debtor.account_number or not debtor.account_type:
            raise PaymentRailError(
                "debtor-account-unset",
                "The consumer homing account is not an LMS field in the locked decisions. "
                "A missing account fails closed.",
            )
        if mandate.scheme == "debicheck":
            if not mandate.mandate_reference or not mandate.mandate_reference.strip():
                raise PaymentRailError(
                    "mandate-unset",
                    "A DebiCheck collection needs the mandate reference. None is assumed.",
                )
            if mandate.tracking_indicator is None:
                raise PaymentRailError(
                    "tracking-unset",
                    "A DebiCheck collection needs an explicit tracking indicator. None is assumed.",
                )
            if mandate.tracking_indicator < 0 or mandate.tracking_indicator > 10:
                raise PaymentRailError(
                    "tracking-unset",
                    "DebiCheck tracking days are 0 to 10. A value outside that range is not written.",
                )

    def _agreement(self, agreement_id: str, organisation_id: str) -> AgreementRecord:
        agreement = self.servicing.agreements.get(agreement_id)
        if agreement is None or agreement.organisation_id != organisation_id:
            raise PaymentRailError("not-found", "No agreement with that id for this organisation.", status=404)
        return agreement

    def _receipt(self, receipt_id: str) -> RailReceipt:
        receipt = self.receipts.get(receipt_id)
        if receipt is None:
            raise PaymentRailError("not-found", "No receipt with that id.", status=404)
        return receipt

    def _actor(self, organisation_id: str, actor_id: str) -> None:
        try:
            self.servicing.enigma.check(organisation_id, actor_id, _ROLE)
        except ServicingError as exc:
            raise _from_downstream(exc) from exc

    def _audit(self, **kwargs) -> None:
        self.servicing.audit.append(**kwargs)

    def _store_receipt(self, receipt: RailReceipt, key: str, fingerprint: str) -> None:
        self.receipts[receipt.receipt_id] = receipt
        if key:
            self._remember("receipt", receipt.organisation_id, key, fingerprint, receipt.receipt_id)

    def _replay(self, kind: str, organisation_id: str, key: str, fingerprint: str) -> str | None:
        if not key:
            raise PaymentRailError("idempotency-required", "This command needs an idempotency key.")
        stored = self._idempotency.get((kind, organisation_id, key))
        if stored is None:
            return None
        previous, resource_id = stored
        if previous != fingerprint:
            raise PaymentRailError(
                "idempotency-conflict",
                "This idempotency key was already used for a different request.",
                status=409,
            )
        return resource_id

    def _remember(self, kind: str, organisation_id: str, key: str, fingerprint: str, resource_id: str) -> None:
        self._idempotency[(kind, organisation_id, key)] = (fingerprint, resource_id)


def instalment_outstanding_cents(account: LoanAccount, due_on: date) -> int:
    """Section 6 instalment still outstanding on ``due_on``.

    Original principal slice remaining, plus levied charges that share that due
    date. Unbilled interest is not a charge, so it is absent. This does not
    allocate.
    """
    principal = sum(item.remaining_cents for item in account.slices if item.due_on == due_on)
    charges = sum(item.remaining_cents for item in account.charges if item.due_on == due_on)
    return principal + charges


def _order_inbound(
    prepared: list[tuple[int, InboundReceipt]],
) -> tuple[tuple[int, InboundReceipt], ...]:
    """``order_recognised_events``: value date, then recognition sequence. §1."""
    by_sequence = {sequence: item for sequence, item in prepared}
    ordered = order_recognised_events(
        tuple(
            RecognisedReceipt(
                item.recognised_at,
                sequence,
                item.amount_cents,
                item.attributed_due_on or value_date(item.recognised_at),
            )
            for sequence, item in prepared
        )
    )
    return tuple((item.sequence, by_sequence[item.sequence]) for item in ordered)


def _written_off(servicing: Servicing, agreement: AgreementRecord) -> bool:
    if agreement.status == "written_off":
        return True
    if agreement.ledger_loan_id is None:
        return False
    return any(
        transaction.kind == "write_off"
        for transaction in servicing.ledger.store.transactions_for(
            agreement.organisation_id, agreement.ledger_loan_id
        )
    )


def _service_fee_cents(agreement: AgreementRecord) -> int:
    for instrument in agreement.product.instruments:
        for fee in instrument.fees:
            if fee.code == "service":
                return fee.amount_cents
    return 0


def _abbreviated_name(trading_name: str, legal_name: str) -> str:
    source = trading_name.strip() or legal_name.strip()
    if not source or len(source) > 10:
        raise PaymentRailError(
            "abbreviated-name-unset",
            "The Bankserv abbreviated user name is 10 characters. Compliance does not store "
            "that name separately, and a longer legal or trading name is not truncated.",
        )
    return source.ljust(10)


def _aware(instant: datetime) -> None:
    if instant.tzinfo is None:
        raise PaymentRailError(
            "timestamp-naive",
            "LOCKED_DECISIONS §1: the recognition instant must be timezone-aware.",
        )


def _receipt_fingerprint(organisation_id: str, item: InboundReceipt) -> str:
    return _fingerprint(
        {
            "organisation_id": organisation_id,
            "amount_cents": item.amount_cents,
            "recognised_at": item.recognised_at.isoformat(),
            "purpose": item.purpose,
            "loan_number": item.loan_number,
            "id_number": item.id_number,
            "agreement_id": item.agreement_id,
            "attributed_due_on": None if item.attributed_due_on is None else item.attributed_due_on.isoformat(),
        }
    )


def _fingerprint(payload: dict) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _from_downstream(exc: Exception) -> PaymentRailError:
    code = getattr(exc, "code", None) or "rejected"
    status = getattr(exc, "status", 422)
    return PaymentRailError(code, str(exc), status=status)
