"""Layer 1 integration smoke. No production behaviour is added here.

The path calls the implementations already on these branches:

- Layer 0 servicing, ledger, configuration, and the calculation engine
- Statements and documents (PR #13)
- Laybye and credit life (PR #16)
- Collections and arrears (PR #17)
- Regulatory extracts (PR #18)

Locked decisions are not given a new reading. A step the public methods
cannot perform is reported. It is not patched in production code.

Caller elections for this run, not platform defaults:

- leniency 3 calendar days
- full-payment threshold 100 percent
- in-duplum trigger ``collections_default``
- residual write-off threshold R50 (5 000 cents), set explicitly

The VAT rate 15% and ``interest_cap_present=True`` are statement inputs.
Neither is a stored election.

Contract: short-term cash R2 000, value date 2026-04-01, one instalment
due 2026-05-01, periodic rate 5% per month, campaign discount 0, day count
actual/actual, initiation fee R0. Frequency is ``monthly`` because locked
decision 14 has no 30-day frequency and servicing does not build a schedule.
"""

from __future__ import annotations

import http.client
import socket
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lms.calc.interest import daily_interest_rands
from lms.collections.errors import CollectionsError
from lms.collections.service import Collections
from lms.laybye.service import allocate_receipt, grant_loan, prepare_pair, receive_pre_disbursement
from lms.regulatory.audit import AuditExtract, AuditLog, AuditRecord
from lms.regulatory.errors import RegulatoryError
from lms.regulatory.ncr import read_ncr_number
from lms.regulatory.sacrra import build_sacrra_extract
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.statements.service import Documents
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
ORG = "org-smoke"
PERSON = "person-smoke"
NCR = "NCRCP999"
CASH_CENTS = 200_000
LAYBYE_CENTS = 20_000
RECEIPT_CENTS = 21_900
RESIDUAL_CENTS = 5_000
ADVANCE = date(2026, 4, 1)
DUE = date(2026, 5, 1)
APRIL_END = date(2026, 4, 30)
FLAG_ON = date(2026, 5, 4)
VAT_RATE = Decimal("0.15")
BOOKED_AT = datetime(2026, 4, 1, 8, 0, tzinfo=JOHANNESBURG)
LAYBYE_AT = datetime(2026, 4, 1, 9, 0, tzinfo=JOHANNESBURG)
DISBURSED_AT = datetime(2026, 4, 1, 11, 0, tzinfo=JOHANNESBURG)
PAID_AT = datetime(2026, 5, 1, 10, 0, tzinfo=JOHANNESBURG)
EARLY_AT = datetime(2026, 5, 2, 8, 0, tzinfo=JOHANNESBURG)
FLAG_AT = datetime(2026, 5, 4, 8, 0, tzinfo=JOHANNESBURG)
CURE_AT = datetime(2026, 5, 4, 11, 0, tzinfo=JOHANNESBURG)

# Net of the R200 hold, April has 30 days, and the monthly rate is 5%.
# 1 800 × 0.05 × 30/30 = R90.00. The opening service fee is a full R60 plus
# R9 VAT because the locked §9 fraction for 1 April to 1 May is 30/30.
NET_APRIL_INTEREST_CENTS = 9_000
SERVICE_FEE_CENTS = 6_900
PRINCIPAL_FROM_RECEIPT_CENTS = RECEIPT_CENTS - NET_APRIL_INTEREST_CENTS - SERVICE_FEE_CENTS


class CountingStub(EnigmaStub):
    """Same success stub. Records each check. It does not open a socket."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, str]] = []

    def check(self, organisation_id: str, person_id: str, mandate: str):
        self.calls.append((organisation_id, person_id, mandate))
        return super().check(organisation_id, person_id, mandate)


def _refuse_http(*_args, **_kwargs):
    raise AssertionError("Layer 1 smoke: an HTTP call was made. Enigma must not be called over the network.")


def _block_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", _refuse_http)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _refuse_http)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _refuse_http)


def _rands(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    amount = abs(cents)
    return f"{sign}R{amount // 100}.{amount % 100:02d} ({amount} cents)"


def _settings() -> OrganisationSettings:
    return OrganisationSettings(
        leniency_days=3,
        full_payment_threshold_percent=Decimal("100"),
        interest_on_deferred_initiation="none",
        repo_rate_fall="contract_rate",
        day_count_code="actual_actual",
        base_rate=Decimal("0.05"),
        discount_rate=Decimal("0"),
        vat_on_rand_maxima="exclusive",
        late_disbursement="keep_instalment",
        partial_prepayment="shorten_term",
    )


def _compliance() -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=ORG,
        legal_name="North Credit (Pty) Ltd",
        ncr_registration_number=NCR,
        trading_name="North Credit",
        physical_address="1 Long Street, Cape Town",
        postal_address="PO Box 1, Cape Town",
        telephone="0210000000",
        bank_name="Example Bank",
        bank_account_number="123456789",
        branch_code="051001",
        payment_reference="loan-ref",
    )


def _expect(problems: list[str], condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


def _step(problems: list[str], label: str, fn):
    try:
        return fn()
    except Exception as exc:
        problems.append(f"{label}: {type(exc).__name__}: {exc}")
        return None


def _section(statement, loan_id: str):
    return next(item for item in statement.loans if item.loan_id == loan_id)


def _instalment_cents(account, due_on: date) -> int:
    principal = sum(item.amount_cents for item in account.slices if item.due_on == due_on)
    levied = sum(
        charge.ex_vat_cents + charge.vat_cents
        for charge in account.charges
        if charge.due_on == due_on and charge.bucket != "additional_monthly"
    )
    return principal + levied


def _received_until(ledger, loan_id: str, due_on: date, day: date) -> int:
    total = 0
    for item in ledger.store.transactions_for(ORG, loan_id):
        if item.kind == "payment" and item.attributed_due_on == due_on and item.value_date <= day:
            total += item.amount_cents or 0
    return total


def _credit_buckets(transaction) -> list[tuple[str, int]]:
    return [
        (entry.bucket, entry.credit_cents)
        for entry in transaction.entries
        if entry.bucket is not None and entry.credit_cents
    ]


def _integer_cents(problems: list[str], ledger, parent, child, *statements) -> None:
    for account in (parent, child):
        for bucket in (
            "principal",
            "interest",
            "service",
            "initiation",
            "laybye_hold",
        ):
            balance = ledger.bucket_balance(account, bucket)
            _expect(problems, type(balance) is int, f"{account.instrument_kind} {bucket} balance is {type(balance).__name__}")
        for transaction in ledger.store.transactions_for(ORG, account.loan_id):
            if transaction.amount_cents is not None:
                _expect(
                    problems,
                    type(transaction.amount_cents) is int,
                    f"{transaction.kind} amount is {type(transaction.amount_cents).__name__}",
                )
            for entry in transaction.entries:
                _expect(problems, type(entry.debit_cents) is int and type(entry.credit_cents) is int, transaction.kind)
    for statement in statements:
        if statement is None:
            continue
        for section in statement.loans:
            for side in ("opening", "closing"):
                for bucket, amount in getattr(section, side).items():
                    _expect(
                        problems,
                        type(amount) is int,
                        f"statement {side} {bucket} is {type(amount).__name__}",
                    )


def _report(numbers: list[str], problems: list[str], gaps: list[str]) -> str:
    lines = ["Layer 1 smoke numbers:"]
    lines.extend(f"  {line}" for line in numbers)
    lines.append("Behavior:")
    if problems:
        lines.extend(f"  - {item}" for item in problems)
    else:
        lines.append("  - the path assertions that ran matched the ledger")
    lines.append("Gaps (left as they are; locked rules were not changed):")
    if gaps:
        lines.extend(f"  - {item}" for item in gaps)
    else:
        lines.append("  - none recorded")
    return "\n".join(lines)


def test_layer1_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Book, hold, disburse, state, pay, flag, cure, then extract."""
    _block_http(monkeypatch)
    problems: list[str] = []
    gaps: list[str] = []
    numbers: list[str] = []
    try:
        _run(problems, gaps, numbers)
    except Exception as exc:
        problems.append(f"path stopped: {type(exc).__name__}: {exc}")
    report = _report(numbers, problems, gaps)
    print(report)
    if problems or gaps:
        pytest.fail(report)


def _run(problems: list[str], gaps: list[str], numbers: list[str]) -> None:
    stub = CountingStub()
    servicing = Servicing(enigma=stub)
    product = micro_short_term()
    settings = _settings()
    record = servicing.book(
        organisation_id=ORG,
        person_id=PERSON,
        product=product,
        settings=settings,
        recognised_at=BOOKED_AT,
        cash_advanced_cents=CASH_CENTS,
        frequency="monthly",
        schedule=((DUE, CASH_CENTS),),
        initiation_fee_cents=0,
        quoted_disbursement=ADVANCE,
        idempotency_key="book-layer1",
    )
    _expect(problems, record.status == "pending_disbursement", f"booking status is {record.status}")
    _expect(problems, record.ledger_loan_id is None, "booking already had a ledger loan")
    _expect(problems, servicing.ledger.store.accounts_for(ORG) == (), "booking posted a ledger account")
    _expect(problems, record.frozen_full_name == "Ada Borrower", "identity was not frozen at booking")
    numbers.append(
        f"booked {record.agreement_id} status {record.status}, "
        f"leniency {record.resolved.leniency_days} days, "
        f"threshold {record.resolved.full_payment_threshold_percent}%"
    )
    collections = Collections(servicing)
    try:
        early_bind = collections.bind(
            record.agreement_id,
            in_duplum_trigger="collections_default",
            residual_threshold_cents=RESIDUAL_CENTS,
        )
    except CollectionsError as exc:
        early_bind = None
        numbers.append(f"bind before disbursement: {exc.code}: {exc}")
        gaps.append(
            "Collections.bind before disbursement raises "
            f"{exc.code}: {exc} "
            "The case is still stored: a second bind is refused as elections-frozen, "
            "and the later view reads collections_default and R50. "
            "Servicing.book cannot carry in_duplum_trigger or the residual threshold. "
            "OrganisationSettings has neither field. "
            "Locked §19 stores both at organisation level, with a product override. "
            "db/migrations/0005_collections_elections.sql is not read by this path."
        )
    else:
        numbers.append(
            f"elections bound before disbursement: in-duplum {early_bind.trigger}, "
            f"residual {_rands(early_bind.residual_threshold_cents)}"
        )

    stub.full_name = "Changed After Booking"
    stub.id_number = "0000000000000"
    stub.service_address = "9 Other Road, Johannesburg"
    prepared = _step(
        problems,
        "prepare laybye pair",
        lambda: prepare_pair(
            servicing.ledger,
            organisation_id=ORG,
            person_id=PERSON,
            product=product,
            organisation=settings,
            recognised_at=BOOKED_AT,
            cash_advanced_cents=CASH_CENTS,
            frequency="monthly",
            schedule=((DUE, CASH_CENTS),),
            identity_name=record.frozen_full_name,
            identity_number=record.frozen_id_number,
            service_address=record.frozen_service_address,
            quoted_disbursement=ADVANCE,
            initiation_fee_cents=0,
            contractual_end=DUE,
        ),
    )
    if prepared is None:
        gaps.append(
            "No servicing method books a linked Laybye before disbursement. "
            "Servicing.disburse calls Ledger.book, which prepares and grants in one call, "
            "so a pre-disbursement receipt cannot be inserted. prepare_pair failed as well."
        )
        return
    parent, child = prepared
    _expect(problems, parent.disbursement_value_date is None, "the parent was granted during prepare")
    _expect(problems, servicing.ledger.bucket_balance(parent, "principal") == 0, "prepare posted principal")
    _expect(problems, parent.frozen_full_name == "Ada Borrower", "prepare rewrote the frozen name")
    _expect(problems, child.instrument_kind == "laybye_hold", f"child kind is {child.instrument_kind}")

    receipt = _step(
        problems,
        "pre-disbursement receipt",
        lambda: receive_pre_disbursement(
            servicing.ledger,
            organisation_id=ORG,
            parent_loan_id=parent.loan_id,
            cents=LAYBYE_CENTS,
            recognised_at=LAYBYE_AT,
        ),
    )
    if receipt is not None:
        hold = servicing.ledger.bucket_balance(child, "laybye_hold")
        numbers.append(f"pre-disbursement Laybye hold: {_rands(hold)} on {receipt.value_date.isoformat()}")
        _expect(problems, hold == LAYBYE_CENTS, f"Laybye hold is {_rands(hold)}, expected {_rands(LAYBYE_CENTS)}")
        _expect(problems, receipt.kind == "laybye_deposit", f"pre-disbursement kind is {receipt.kind}")
        _expect(
            problems,
            servicing.ledger.bucket_balance(parent, "principal") == 0,
            "the pre-disbursement receipt changed parent principal",
        )
        _expect(
            problems,
            servicing.ledger.store.transactions_for(ORG, parent.loan_id) == (),
            "the pre-disbursement receipt posted on the parent loan",
        )
        _expect(problems, receipt.value_date == ADVANCE, f"receipt value date is {receipt.value_date}")
    else:
        return

    granted = _step(
        problems,
        "confirm disbursement",
        lambda: grant_loan(
            servicing.ledger,
            organisation_id=ORG,
            parent_loan_id=parent.loan_id,
            recognised_at=DISBURSED_AT,
            schedule=((DUE, CASH_CENTS),),
            initiation_fee_cents=0,
        ),
    )
    if granted is None:
        return
    numbers.append(
        f"disbursement {granted.disbursement_value_date}: "
        f"principal {_rands(servicing.ledger.bucket_balance(parent, 'principal'))}, "
        f"Laybye hold {_rands(servicing.ledger.bucket_balance(child, 'laybye_hold'))}"
    )
    _expect(
        problems,
        servicing.ledger.bucket_balance(parent, "principal") == CASH_CENTS,
        f"principal after grant is {_rands(servicing.ledger.bucket_balance(parent, 'principal'))}",
    )
    _expect(
        problems,
        servicing.ledger.bucket_balance(child, "laybye_hold") == LAYBYE_CENTS,
        "grant moved the Laybye hold",
    )
    _expect(problems, granted.frozen_full_name == "Ada Borrower", "grant rewrote the frozen name")
    _expect(problems, granted.frozen_id_number == "8001015800085", "grant rewrote the frozen identity number")
    mandates = [call[2] for call in stub.calls]
    _expect(problems, "disbursement.confirm" not in mandates, f"grant_loan called Enigma: {mandates}")
    gaps.append(
        "Confirming disbursement went through laybye.grant_loan, not Servicing.disburse. "
        "Servicing.disburse calls Ledger.book, which grants immediately and does not link a Laybye. "
        "The pending agreement was then pointed at the granted parent so statements and collections "
        "could see it. grant_loan does not call the Enigma stub (no disbursement.confirm). "
        "No production method performs book, pre-disbursement receipt, and grant as one agreement."
    )
    record.ledger_loan_id = parent.loan_id
    record.disbursement_value_date = granted.disbursement_value_date
    record.status = "active"
    try:
        collections.bind(
            record.agreement_id,
            in_duplum_trigger="collections_default",
            residual_threshold_cents=RESIDUAL_CENTS,
        )
        numbers.append("second bind was accepted")
    except CollectionsError as exc:
        numbers.append(f"second bind refused: {exc.code}")
        _expect(
            problems,
            exc.code == "elections-frozen",
            f"second bind failed with {exc.code}: {exc}",
        )
    bound = _step(problems, "read collections elections", lambda: collections.view(record.agreement_id))
    if bound is not None:
        numbers.append(
            f"elections on the case: in-duplum {bound.trigger}, residual {_rands(bound.residual_threshold_cents)}"
        )
        _expect(problems, bound.trigger == "collections_default", f"trigger is {bound.trigger}")
        _expect(
            problems,
            bound.residual_threshold_cents == RESIDUAL_CENTS,
            f"residual threshold is {_rands(bound.residual_threshold_cents)}",
        )

    compliance = ComplianceStore()
    compliance.put(_compliance())
    documents = Documents(servicing, compliance)
    april = _step(
        problems,
        "April statement",
        lambda: documents.issue_statement(
            organisation_id=ORG,
            person_id=PERSON,
            period_start=ADVANCE,
            period_end=APRIL_END,
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        ),
    )
    if april is None:
        return
    parent_april = _section(april, parent.loan_id)
    child_april = _section(april, child.loan_id)
    numbers.append(
        "April statement parent closing: "
        + ", ".join(f"{bucket} {_rands(amount)}" for bucket, amount in sorted(parent_april.closing.items()) if amount)
    )
    numbers.append(
        "April statement Laybye closing: "
        + ", ".join(f"{bucket} {_rands(amount)}" for bucket, amount in sorted(child_april.closing.items()) if amount)
    )
    _expect(
        problems,
        parent_april.closing.get("interest") == NET_APRIL_INTEREST_CENTS,
        "April interest on the net base (principal R2 000 minus Laybye R200) should bill at "
        f"{_rands(NET_APRIL_INTEREST_CENTS)}. The statement closed interest at "
        f"{_rands(parent_april.closing.get('interest', 0))}.",
    )
    _expect(
        problems,
        parent_april.closing.get("service") == SERVICE_FEE_CENTS,
        f"April service fee closed at {_rands(parent_april.closing.get('service', 0))}, "
        f"expected {_rands(SERVICE_FEE_CENTS)}",
    )
    _expect(
        problems,
        parent_april.closing.get("principal") == CASH_CENTS,
        f"April principal closed at {_rands(parent_april.closing.get('principal', 0))}",
    )
    _expect(
        problems,
        parent_april.closing.get("laybye_hold") == 0,
        "the parent statement folded the Laybye hold into the loan section",
    )
    _expect(
        problems,
        child_april.closing.get("laybye_hold") == LAYBYE_CENTS,
        f"April Laybye section closed at {_rands(child_april.closing.get('laybye_hold', 0))}",
    )
    _expect(problems, april.ncr_registration_number == NCR, f"April statement NCR is {april.ncr_registration_number}")
    interest_memos = [
        transaction.memo_rands
        for transaction in servicing.ledger.store.transactions_for(ORG, parent.loan_id)
        if transaction.kind == "interest_accrual" and transaction.memo_rands is not None and transaction.value_date <= APRIL_END
    ]
    numbers.append(f"April interest memos: {len(interest_memos)} days")

    payment = _step(
        problems,
        "1 May receipt",
        lambda: allocate_receipt(
            servicing.ledger,
            organisation_id=ORG,
            parent_loan_id=parent.loan_id,
            cents=RECEIPT_CENTS,
            recognised_at=PAID_AT,
            attributed_due_on=DUE,
        ),
    )
    if payment is None:
        return
    loan_tx = servicing.ledger.store.get_transaction(ORG, payment.loan_transaction_id)
    credited = _credit_buckets(loan_tx)
    numbers.append(
        f"1 May receipt {_rands(RECEIPT_CENTS)}: loan {_rands(payment.loan_cents)}, "
        f"Laybye {_rands(payment.laybye_cents)}, credits {credited}"
    )
    _expect(
        problems,
        credited == [
            ("interest", NET_APRIL_INTEREST_CENTS),
            ("service", SERVICE_FEE_CENTS),
            ("principal", PRINCIPAL_FROM_RECEIPT_CENTS),
        ],
        "the R219 receipt should pay due interest, then the service fee, then principal. "
        f"Credits were {credited}.",
    )
    _expect(
        problems,
        payment.laybye_cents == 0 and servicing.ledger.bucket_balance(child, "laybye_hold") == LAYBYE_CENTS,
        f"Laybye moved on a receipt that was still inside the loan's due amounts: laybye_cents={payment.laybye_cents}",
    )
    _expect(
        problems,
        payment.loan_cents == RECEIPT_CENTS,
        f"loan took {_rands(payment.loan_cents)} of {_rands(RECEIPT_CENTS)}",
    )
    numbers.append(
        "after the receipt: "
        f"principal {_rands(servicing.ledger.bucket_balance(parent, 'principal'))}, "
        f"interest {_rands(servicing.ledger.bucket_balance(parent, 'interest'))}, "
        f"service {_rands(servicing.ledger.bucket_balance(parent, 'service'))}, "
        f"Laybye {_rands(servicing.ledger.bucket_balance(child, 'laybye_hold'))}"
    )
    gaps.append(
        "The R219 receipt was posted with laybye.allocate_receipt. "
        "Servicing.accept_payment and Documents.issue_statement post the whole receipt through "
        "Ledger.post_payment. That method raises overpayment-unset once due amounts and the "
        "prepayment election are exhausted. It does not credit the Laybye. "
        "This receipt had no excess, so that leg was not exercised: "
        f"loan {_rands(payment.loan_cents)}, Laybye {_rands(payment.laybye_cents)}."
    )

    may = _step(
        problems,
        "1 May statement",
        lambda: documents.issue_statement(
            organisation_id=ORG,
            person_id=PERSON,
            period_start=DUE,
            period_end=DUE,
            interest_cap_present=True,
            vat_rate=VAT_RATE,
        ),
    )
    if may is not None:
        parent_may = _section(may, parent.loan_id)
        child_may = _section(may, child.loan_id)
        numbers.append(
            "1 May statement parent opening: "
            + ", ".join(f"{bucket} {_rands(amount)}" for bucket, amount in sorted(parent_may.opening.items()) if amount)
        )
        numbers.append(
            "1 May statement parent closing: "
            + ", ".join(
                f"{bucket} {_rands(amount)}"
                for bucket, amount in sorted(parent_may.closing.items())
                if amount or bucket in {"principal", "interest", "service", "laybye_hold"}
            )
        )
        numbers.append(
            "1 May statement Laybye opening/closing hold: "
            f"{_rands(child_may.opening.get('laybye_hold', 0))} / "
            f"{_rands(child_may.closing.get('laybye_hold', 0))}"
        )
        _expect(
            problems,
            parent_may.opening == parent_april.closing,
            f"parent opening {parent_may.opening} is not the April closing {parent_april.closing}",
        )
        _expect(
            problems,
            child_may.opening == child_april.closing,
            f"Laybye opening {child_may.opening} is not the April closing {child_april.closing}",
        )
        _expect(problems, parent_may.opening_source == "previous-closing", parent_may.opening_source)
        may_memos = [
            transaction
            for transaction in servicing.ledger.store.transactions_for(ORG, parent.loan_id)
            if transaction.kind == "interest_accrual" and transaction.value_date == DUE
        ]
        memo = sum((item.memo_rands or Decimal(0)) for item in may_memos)
        reduced = daily_interest_rands(
            CASH_CENTS - PRINCIPAL_FROM_RECEIPT_CENTS - LAYBYE_CENTS,
            Decimal("0.05"),
            31,
        )
        gross_net = daily_interest_rands(CASH_CENTS - LAYBYE_CENTS, Decimal("0.05"), 31)
        numbers.append(
            f"1 May interest memo {memo} rands; "
            f"on the balance after the receipt {reduced}; "
            f"on the morning balance before the receipt {gross_net}"
        )
        if may_memos and loan_tx is not None and may_memos[0].recognition_sequence > loan_tx.recognition_sequence:
            gaps.append(
                "1 May interest was accrued after the 1 May receipt, on the reduced principal. "
                f"The memo is {memo} rands. Accruing the morning balance of R1 800 first would be {gross_net} rands. "
                "Locked §1 and §8 say that on a calendar day the day's due amounts are accrued and capitalised "
                "at 00:00 and then receipts are allocated. The same sections also allow capitalisation at "
                "month-end and a payment on another day, and the statements layer only bills interest at "
                "month-end. The 1 May statement, issued after the receipt, does not move that day's accrual "
                "ahead of the receipt. This smoke does not choose which bullet wins."
            )

    early = _step(
        problems,
        "observe inside leniency",
        lambda: collections.observe(record.agreement_id, recognised_at=EARLY_AT),
    )
    if early is not None:
        numbers.append(
            f"2 May observe: collections_default={early.collections_default}, "
            f"breaches={early.contractual_breaches}, ceiling={early.open_episode_ceiling}"
        )
        _expect(problems, early.collections_default is False, "collections default flagged inside the 3-day leniency")
        _expect(problems, early.open_episode_ceiling is None, "an in-duplum episode opened inside leniency")
        _expect(
            problems,
            early.contractual_breaches == (DUE,),
            f"contractual breaches on 2 May are {early.contractual_breaches}",
        )

    flagged = _step(
        problems,
        "flag collections default",
        lambda: collections.observe(record.agreement_id, recognised_at=FLAG_AT),
    )
    if flagged is None:
        return
    principal_at_flag = servicing.ledger.bucket_balance(parent, "principal")
    numbers.append(
        f"4 May flag: collections_default={flagged.collections_default}, "
        f"ceiling={None if flagged.open_episode_ceiling is None else _rands(flagged.open_episode_ceiling)}, "
        f"principal {_rands(principal_at_flag)}, "
        f"Laybye {_rands(servicing.ledger.bucket_balance(child, 'laybye_hold'))}, "
        f"episodes={flagged.episode_count}"
    )
    _expect(problems, flagged.collections_default is True, "collections default did not flag on 4 May")
    _expect(
        problems,
        flagged.open_episode_ceiling == principal_at_flag,
        "the in-duplum ceiling should be the unpaid principal, gross of the Laybye hold. "
        f"Ceiling {flagged.open_episode_ceiling}, principal {principal_at_flag}, "
        f"principal minus hold {principal_at_flag - LAYBYE_CENTS}.",
    )
    _expect(problems, flagged.episode_count == 1, f"episode count is {flagged.episode_count}")

    instalment = _instalment_cents(parent, DUE)
    received = _received_until(servicing.ledger, parent.loan_id, DUE, FLAG_ON)
    shortfall = instalment - received
    numbers.append(
        f"1 May instalment {_rands(instalment)}, received by the flag date {_rands(received)}, "
        f"shortfall {_rands(shortfall)}"
    )
    _expect(problems, shortfall > 0, "the R219 receipt already cleared the 1 May instalment")
    cure_payment = _step(
        problems,
        "cure payment",
        lambda: allocate_receipt(
            servicing.ledger,
            organisation_id=ORG,
            parent_loan_id=parent.loan_id,
            cents=shortfall,
            recognised_at=CURE_AT,
            attributed_due_on=DUE,
        ),
    )
    if cure_payment is None:
        return
    numbers.append(
        f"cure receipt {_rands(shortfall)}: loan {_rands(cure_payment.loan_cents)}, "
        f"Laybye {_rands(cure_payment.laybye_cents)}"
    )
    cured = _step(
        problems,
        "observe after cure",
        lambda: collections.observe(record.agreement_id, recognised_at=CURE_AT),
    )
    if cured is None:
        return
    closed = parent.episodes[0].closed_on if parent.episodes else None
    numbers.append(
        f"after cure: collections_default={cured.collections_default}, "
        f"ceiling={cured.open_episode_ceiling}, episodes={cured.episode_count}, "
        f"closed_on={closed}, breaches={cured.contractual_breaches}, "
        f"principal {_rands(servicing.ledger.bucket_balance(parent, 'principal'))}"
    )
    _expect(problems, cured.collections_default is False, "the collections default stayed open after the arrears were paid")
    _expect(problems, cured.open_episode_ceiling is None, "the in-duplum episode stayed open after the cure")
    _expect(problems, closed == FLAG_ON, f"episode closed_on is {closed}")
    _expect(
        problems,
        cured.contractual_breaches == (DUE,),
        "the contractual breach of 1 May was removed by the later payment. "
        f"Breaches are {cured.contractual_breaches}. Locked §6 says that breach cannot be rectified.",
    )
    remaining_principal = servicing.ledger.bucket_balance(parent, "principal")
    if cured.collections_default is False and remaining_principal == NET_APRIL_INTEREST_CENTS:
        gaps.append(
            "The collections default closed while principal of "
            f"{_rands(remaining_principal)} was still unpaid. "
            "The 1 May instalment used here is the R2 000 principal slice plus the R69 service fee "
            f"({_rands(instalment)}). April interest of {_rands(NET_APRIL_INTEREST_CENTS)} was billed on "
            "30 April, so it is not part of that instalment. "
            "The R219 receipt is stored as one amount attributed to 1 May, and collections counts that "
            "whole amount, including the R90 section 126 applied to the 30 April interest. "
            "The cure receipt is the instalment minus that R219, which is R1 850, and it pays principal only. "
            "R90 of principal remains, equal to the April interest. "
            "Locked §6 does not say whether a receipt that section 126 splits across due dates counts in full "
            "toward the single attributed due date. This smoke does not choose a split."
        )
    write_offs = [
        item.kind for item in servicing.ledger.store.transactions_for(ORG, parent.loan_id) if item.kind == "write_off"
    ]
    _expect(problems, write_offs == [], f"a write-off was posted: {write_offs}")

    sacrra = _step(
        problems,
        "SACRRA extract",
        lambda: build_sacrra_extract(
            servicing.ledger,
            compliance,
            organisation_id=ORG,
            as_of=FLAG_ON,
            pure_hosting=False,
        ),
    )
    if sacrra is not None:
        _expect(problems, len(sacrra.rows) == 1, f"SACRRA row count is {len(sacrra.rows)}")
        _expect(problems, sacrra.ncr_registration_number == read_ncr_number(compliance, ORG) == NCR, sacrra.ncr_registration_number)
        if sacrra.rows:
            row = sacrra.rows[0]
            numbers.append(
                "SACRRA "
                f"{row.frozen_full_name} / {row.frozen_id_number}: "
                f"principal {_rands(row.principal_cents)}, "
                f"Laybye {_rands(row.laybye_hold_cents)}, "
                f"interest {_rands(row.bucket_cents['interest'])}, "
                f"service {_rands(row.bucket_cents['service'])}, "
                f"NCR {sacrra.ncr_registration_number}"
            )
            _expect(problems, row.loan_id == parent.loan_id, "SACRRA did not use the parent loan")
            _expect(problems, row.frozen_full_name == parent.frozen_full_name == "Ada Borrower", row.frozen_full_name)
            _expect(problems, row.frozen_id_number == parent.frozen_id_number == "8001015800085", row.frozen_id_number)
            _expect(
                problems,
                row.frozen_service_address == parent.frozen_service_address == "1 Main Road, Cape Town",
                row.frozen_service_address,
            )
            _expect(problems, row.frozen_full_name != stub.full_name, "SACRRA followed the Enigma stub after booking")
            for bucket, amount in row.bucket_cents.items():
                _expect(problems, type(amount) is int, f"SACRRA {bucket} is {type(amount).__name__}")
                if bucket == "laybye_hold":
                    actual = servicing.ledger.bucket_balance(child, "laybye_hold", as_of=FLAG_ON)
                else:
                    actual = servicing.ledger.bucket_balance(parent, bucket, as_of=FLAG_ON)
                _expect(
                    problems,
                    amount == actual,
                    f"SACRRA {bucket} {_rands(amount)} is not the ledger balance {_rands(actual)}",
                )
            _expect(
                problems,
                row.principal_cents == servicing.ledger.bucket_balance(parent, "principal", as_of=FLAG_ON),
                "SACRRA principal was not the ledger principal",
            )
            _expect(problems, row.laybye_hold_cents == LAYBYE_CENTS, f"SACRRA hold is {row.laybye_hold_cents}")
        _expect(problems, sacrra.file_bytes is None, "SACRRA emitted a submission file")

    try:
        missing = build_sacrra_extract(
            servicing.ledger,
            ComplianceStore(),
            organisation_id=ORG,
            as_of=FLAG_ON,
            pure_hosting=False,
        )
    except RegulatoryError as exc:
        missing = None
        numbers.append(f"SACRRA with no LMS compliance row failed closed: {exc.code}")
        _expect(problems, exc.code == "ncr-number-unset", f"missing NCR failed with {exc.code}")
    if missing is not None:
        problems.append(
            "SACRRA with no LMS compliance row returned an extract. "
            f"NCR on that extract: {missing.ncr_registration_number}."
        )
    _expect(problems, read_ncr_number(ComplianceStore(), ORG) is None, "a missing compliance row still returned an NCR number")
    _expect(problems, not hasattr(stub, "ncr_registration_number"), "the Enigma stub carries an NCR number")

    audit = AuditLog().extract(organisation_id=ORG, from_date=ADVANCE, to_date=FLAG_ON)
    field_names = tuple(AuditExtract.__dataclass_fields__)
    row_fields = tuple(AuditRecord.__dataclass_fields__)
    numbers.append(
        f"audit extract rows={len(audit.rows)}, verified={audit.verified}, "
        f"hashes_ok={audit.hashes_ok}, links_ok={audit.links_ok}, "
        f"chain_head_last_sequence={audit.chain_head_last_sequence}"
    )
    _expect(
        problems,
        {"predecessor_row_hash", "predecessor_recognition_sequence", "links_ok", "hashes_ok", "verified", "chain_head_last_hash", "chain_head_last_sequence"}
        <= set(field_names),
        f"audit extract fields are {field_names}",
    )
    _expect(
        problems,
        {"previous_hash", "row_hash", "recognition_sequence"} <= set(row_fields),
        f"audit row fields are {row_fields}",
    )
    if not audit.rows:
        gaps.append(
            "The audit extract for this organisation has no rows. "
            "Booking, the Laybye receipt, disbursement, the statements, the two receipts, "
            "and the in-duplum episode were not appended to AuditLog. "
            "The extract object has the hash-chain fields "
            "(previous_hash and row_hash on a row, predecessor_row_hash, links_ok, hashes_ok, "
            "verified, chain_head_last_hash) but none were filled from this path. "
            "The regulatory note already records that nothing in src/lms inserts lms.audit_event."
        )

    migration_dir = Path(__file__).resolve().parents[1] / "db" / "migrations"
    prefixed = sorted(path.name for path in migration_dir.glob("0005_*.sql"))
    if len(prefixed) > 1:
        gaps.append(
            "Three migrations share the 0005 prefix after the branches are combined: "
            + ", ".join(prefixed)
            + ". They were left numbered as each branch wrote them."
        )

    _integer_cents(problems, servicing.ledger, parent, child, april, may)
    _expect(problems, "lms.enigma.client" not in sys.modules and "lms.enigma" not in sys.modules, "an Enigma HTTP client was imported")
    mandates = [call[2] for call in stub.calls]
    numbers.append(f"Enigma stub mandates: {mandates}")
    numbers.append(
        "no HTTP call was attempted; socket.create_connection and http.client request were blocked"
    )
    if "payment.accept" not in mandates:
        gaps.append(
            "laybye.allocate_receipt did not call the Enigma stub. "
            "Servicing.accept_payment would have checked payment.accept. "
            f"Mandates seen: {mandates}."
        )
