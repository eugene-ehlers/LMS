"""Seven-path smoke against the merged LMS. No production behaviour is added.

The decision engine, debit-order rail, and Enigma dummies are called for the
approval, the matched receipt, and the booking identity. Servicing still posts
through its own Enigma stub, because that is the check the ledger path calls.
Locked rules are not given a new reading. Numbers are the ledger's.
"""

from __future__ import annotations

import http.client
import socket
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from lms.collection_campaigns.models import ROLE
from lms.collection_campaigns.service import CollectionCampaigns, earliest_effective
from lms.collections.errors import CollectionsError
from lms.collections.service import Collections
from lms.dummies.debit_order_rail import DebitOrderRailDummy
from lms.dummies.decision_engine import DecisionEngineDummy
from lms.dummies.enigma import EnigmaDummy
from lms.payments.dummies import DebitOrderRailDummy as FileRailDummy
from lms.payments.dummies import DecisionEngineDummy as PremiumDummy
from lms.payments.flags import FeatureFlags
from lms.payments.rail import PaymentRail
from lms.ports.decision_engine import Application, Approval, ConsumerIdentity, PaymentFrequency
from lms.ports.debit_order_rail import CollectionInstruction, CollectionSuccess
from lms.recognition import to_recognition_instant
from lms.servicing.enigma import EnigmaStub
from lms.servicing.service import Servicing
from lms.statements.service import Documents
from lms_config.compliance import ComplianceStore, ProviderCompliance
from lms_config.locked import OrganisationSettings, resolve_residual_threshold_cents
from lms_config.statute import SERVICE_FEE_MONTHLY_CENTS
from lms_config.templates import micro_short_term

JOHANNESBURG = to_recognition_instant(date(2026, 1, 1)).tzinfo
ORG = "org-active"
NCR = "NCRCP0000000"
VAT = Decimal("0.15")
CASH = 200_000
RECEIPT = 21_900
RESIDUAL = 10_000
ROOT = Path(__file__).resolve().parents[1]


class CountingStub(EnigmaStub):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, str]] = []

    def check(self, organisation_id: str, person_id: str, mandate: str):
        self.calls.append((organisation_id, person_id, mandate))
        return super().check(organisation_id, person_id, mandate)


def _refuse_http(*_args, **_kwargs):
    raise AssertionError("merged smoke: an HTTP call was made")


def _block_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", _refuse_http)
    monkeypatch.setattr(http.client.HTTPConnection, "request", _refuse_http)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", _refuse_http)


def _rands(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    amount = abs(cents)
    return f"{sign}R{amount // 100}.{amount % 100:02d} ({amount} cents)"


def _settings(**overrides) -> OrganisationSettings:
    values = dict(
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
        in_duplum_trigger="collections_default",
        residual_write_off_threshold_cents=RESIDUAL,
    )
    values.update(overrides)
    return OrganisationSettings(**values)


def _compliance() -> ProviderCompliance:
    return ProviderCompliance(
        organisation_id=ORG,
        legal_name="North Credit (Pty) Ltd",
        ncr_registration_number=NCR,
        trading_name="North Credit",
        physical_address="1 Dummy Street, Johannesburg",
        postal_address="PO Box 1, Johannesburg",
        telephone="0110000000",
        bank_name="Example Bank",
        bank_account_number="123456789",
        branch_code="051001",
        payment_reference="loan-ref",
    )


def _section(statement, loan_id: str):
    return next(item for item in statement.loans if item.loan_id == loan_id)


def _nonzero(side: dict[str, int]) -> str:
    parts = [f"{bucket} {_rands(amount)}" for bucket, amount in sorted(side.items()) if amount]
    return ", ".join(parts) if parts else "(all zero)"


def _credits(transaction) -> list[tuple[str, int]]:
    return [
        (entry.bucket, entry.credit_cents)
        for entry in transaction.entries
        if entry.bucket is not None and entry.credit_cents
    ]


def _charges(account) -> list[tuple[str, date, int, int, int]]:
    rows = []
    for charge in account.charges:
        total = charge.ex_vat_cents + charge.vat_cents
        rows.append((charge.bucket, charge.levied_on, charge.ex_vat_cents, charge.vat_cents, total))
    return rows


def _memos(ledger, loan_id: str) -> list:
    return [
        item
        for item in ledger.store.transactions_for(ORG, loan_id)
        if item.kind == "interest_accrual" and item.memo_rands is not None
    ]


def _bills(ledger, loan_id: str) -> list:
    return [item for item in ledger.store.transactions_for(ORG, loan_id) if item.kind == "interest_bill"]


def _integer_cents(problems: list[str], ledger, *accounts) -> None:
    for account in accounts:
        for bucket in ("principal", "interest", "service", "initiation"):
            balance = ledger.bucket_balance(account, bucket)
            if type(balance) is not int:
                problems.append(f"{bucket} balance is {type(balance).__name__}")


class Smoke:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.gaps: list[str] = []
        self.failures: list[str] = []
        self.measured: dict[str, object] = {}

    def say(self, line: str) -> None:
        self.lines.append(line)

    def gap(self, line: str) -> None:
        self.gaps.append(line)

    def fail(self, line: str) -> None:
        self.failures.append(line)

    def text(self) -> str:
        parts = ["Merged smoke numbers:", *self.lines, "Gaps:"]
        parts.extend(f"- {item}" for item in self.gaps) if self.gaps else parts.append("- none")
        parts.append("Path failures:")
        parts.extend(f"- {item}" for item in self.failures) if self.failures else parts.append("- none")
        return "\n".join(parts)


def _book(servicing: Servicing, person: str, when: date, cash: int, frequency: str, schedule, key: str):
    return servicing.book(
        organisation_id=ORG,
        person_id=person,
        product=micro_short_term(),
        settings=_settings(),
        recognised_at=to_recognition_instant(when),
        cash_advanced_cents=cash,
        frequency=frequency,
        schedule=tuple(schedule),
        initiation_fee_cents=0,
        quoted_disbursement=when,
        idempotency_key=key,
    )


def _disburse(servicing: Servicing, agreement_id: str, when: date):
    return servicing.disburse(agreement_id, recognised_at=to_recognition_instant(when))


def _approve(engine: DecisionEngineDummy, identity, *, amount: int, term: int, frequency: PaymentFrequency, instalment: int) -> Approval:
    decision = engine.decide(
        Application(
            consumer=ConsumerIdentity(
                person_id=identity.person_id,
                name=identity.name,
                id_number=identity.id_number,
            ),
            requested_amount_cents=amount,
            product_type="micro_short_term",
            term_count=term,
            payment_frequency=frequency,
        )
    )
    if not isinstance(decision, Approval):
        raise AssertionError(f"decision engine declined {frequency}")
    return decision


def test_merged_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    _block_http(monkeypatch)
    smoke = Smoke()
    try:
        _run(smoke)
    except Exception as exc:
        smoke.fail(f"path stopped: {type(exc).__name__}: {exc}")
    print(smoke.text())
    assert not smoke.failures, smoke.text()


def _run(smoke: Smoke) -> None:
    enigma = EnigmaDummy()
    identity = enigma.identity_for_booking("person-active")
    context = enigma.organisation.context(ORG)
    session = enigma.session.introspect("session-active")
    campaign_role = enigma.lookup_mandate("person-active", ORG, ROLE)
    smoke.say(
        f"Enigma dummy: person {identity.person_id} {identity.name} id {identity.id_number}, "
        f"address {identity.service_address}; org {context.organisation_id} "
        f"{context.company_registration_number}; session {session.person_id}; "
        f"{ROLE} granted={campaign_role.granted}"
    )
    if campaign_role.granted:
        smoke.gap("EnigmaDummy granted the collection-campaign role to person-active")
    else:
        smoke.gap(
            "EnigmaDummy person-active does not hold lms.collection_campaign.write. "
            "CollectionCampaigns.create authorises through access.check. "
            "The campaign path below uses EnigmaStub, which returns a clear success for that role. "
            "Servicing.book also calls EnigmaStub.check, not EnigmaDummy."
        )
    stub = CountingStub()
    stub.full_name = identity.name
    stub.id_number = identity.id_number
    stub.service_address = identity.service_address
    servicing = Servicing(enigma=stub)
    compliance = ComplianceStore()
    compliance.put(_compliance())
    documents = Documents(servicing, compliance)
    collections = Collections(servicing)
    campaigns = CollectionCampaigns(servicing.ledger, EnigmaStub())
    payments = PaymentRail(
        servicing=servicing,
        rail=FileRailDummy(),
        decision_engine=PremiumDummy(),
        compliance=compliance,
        flags=FeatureFlags(),
    )
    engine = DecisionEngineDummy.fixed_success(
        contractual_periodic_rate_bps=500,
        instalment_cents=CASH,
    )
    rail = DebitOrderRailDummy.fixed_success()
    _migrations(smoke)
    _fail_closed(smoke, servicing, collections)
    _normal(smoke, servicing, documents, engine, rail, payments, identity)
    _open_period(smoke, servicing, documents, engine, identity)
    _weekly(smoke, servicing, payments, engine, identity)
    _settlement(smoke, servicing, documents, engine, identity)
    _collections_default(smoke, servicing, documents, collections, engine, rail, payments, identity)
    _write_off(smoke, servicing, documents, collections, engine, identity)
    _campaign(smoke, servicing, campaigns, engine, identity)
    _integer_cents(smoke.failures, servicing.ledger, *servicing.ledger.store.accounts_for(ORG))


def _migrations(smoke: Smoke) -> None:
    names = sorted(path.name for path in (ROOT / "db" / "migrations").glob("*.sql"))
    prefixes: dict[str, list[str]] = {}
    for name in names:
        prefixes.setdefault(name.split("_", 1)[0], []).append(name)
    duplicated = {prefix: files for prefix, files in prefixes.items() if len(files) > 1}
    smoke.say(f"migrations: {', '.join(names)}")
    if duplicated:
        smoke.gap(
            "Two migrations share a prefix, so apply order is not determined by the prefix alone: "
            + "; ".join(f"{prefix}={files}" for prefix, files in sorted(duplicated.items()))
        )


def _fail_closed(smoke: Smoke, servicing: Servicing, collections: Collections) -> None:
    try:
        servicing.book(
            organisation_id=ORG,
            person_id="person-unset",
            product=micro_short_term(),
            settings=OrganisationSettings(
                leniency_days=None,
                full_payment_threshold_percent=None,
                interest_on_deferred_initiation=None,
                repo_rate_fall=None,
                day_count_code=None,
                base_rate=None,
                discount_rate=None,
                vat_on_rand_maxima=None,
                late_disbursement=None,
                partial_prepayment=None,
                in_duplum_trigger=None,
                residual_write_off_threshold_cents=None,
            ),
            recognised_at=to_recognition_instant(date(2026, 4, 1)),
            cash_advanced_cents=CASH,
            frequency="monthly",
            schedule=((date(2026, 5, 1), CASH),),
            initiation_fee_cents=0,
            quoted_disbursement=date(2026, 4, 1),
            idempotency_key="book-unset",
        )
        smoke.fail("booking with every election unset succeeded")
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        smoke.say(f"fail closed, elections unset at book: {code}: {exc}")
    bare = _book(servicing, "person-trigger", date(2026, 4, 1), CASH, "monthly", ((date(2026, 5, 1), CASH),), "book-trigger")
    smoke.say(
        f"book with the elections set: trigger {bare.resolved.in_duplum_trigger!r}, "
        f"residual {bare.resolved.residual_write_off_threshold_cents}"
    )
    unset = servicing.book(
        organisation_id=ORG,
        person_id="person-trigger-unset",
        product=micro_short_term(),
        settings=_settings(in_duplum_trigger=None, residual_write_off_threshold_cents=None),
        recognised_at=to_recognition_instant(date(2026, 4, 1)),
        cash_advanced_cents=CASH,
        frequency="monthly",
        schedule=((date(2026, 5, 1), CASH),),
        initiation_fee_cents=0,
        quoted_disbursement=date(2026, 4, 1),
        idempotency_key="book-trigger-unset",
    )
    smoke.say(
        f"book with trigger and residual omitted: status {unset.status}, "
        f"stored trigger {unset.resolved.in_duplum_trigger!r}, "
        f"stored residual {unset.resolved.residual_write_off_threshold_cents}"
    )
    if unset.resolved.in_duplum_trigger is None:
        smoke.gap(
            "Decision 19 says an unset in-duplum trigger fails closed. "
            "Servicing.book stored None and returned the agreement. "
            "Event: book with in_duplum_trigger omitted."
        )
    if unset.resolved.residual_write_off_threshold_cents != RESIDUAL:
        smoke.gap(
            "Decision 8 and Decision 19 name a residual default of R100 and also say unset fails closed. "
            f"resolve stored {unset.resolved.residual_write_off_threshold_cents} cents when both levels were null. "
            "Event: book with residual_write_off_threshold_cents omitted. Already C4 and C6."
        )
    try:
        collections.bind(unset.agreement_id, in_duplum_trigger=None, residual_threshold_cents=RESIDUAL)
        smoke.fail("bind with an unset trigger succeeded")
    except CollectionsError as exc:
        smoke.say(f"fail closed, bind without trigger: {exc.code}")
        if exc.code != "trigger-unset":
            smoke.fail(f"bind without trigger raised {exc.code}")
    filled = resolve_residual_threshold_cents(None, None)
    smoke.say(f"resolve_residual_threshold_cents(None, None) = {filled}")
    try:
        documents_vat = Documents(servicing, ComplianceStore())
        documents_vat.compliance.put(_compliance())
        granted = _disburse(servicing, bare.agreement_id, date(2026, 4, 1))
        documents_vat.issue_statement(
            organisation_id=ORG,
            person_id=granted.person_id,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            interest_cap_present=True,
            vat_rate=None,
        )
        smoke.fail("April statement without a VAT rate succeeded")
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        smoke.say(f"fail closed, statement without VAT: {code}")


def _normal(smoke, servicing, documents, engine, rail, payments, identity) -> None:
    approval = _approve(
        engine,
        identity,
        amount=CASH,
        term=1,
        frequency=PaymentFrequency.MONTHLY,
        instalment=CASH,
    )
    smoke.say(
        f"normal approval {approval.application_number}: "
        f"{approval.contractual_periodic_rate_bps} bps, "
        f"term {approval.term_count} {approval.payment_frequency}, "
        f"instalment {_rands(approval.instalment_cents)}, "
        f"credit life {_rands(approval.credit_life_premium_cents)}"
    )
    advance = date(2026, 4, 1)
    due = date(2026, 5, 1)
    record = _book(servicing, "person-normal", advance, CASH, "monthly", ((due, CASH),), "book-normal")
    record = _disburse(servicing, record.agreement_id, advance)
    loan_number = payments.register_loan_number(
        organisation_id=ORG,
        agreement_id=record.agreement_id,
        application_number=approval.application_number,
        recognised_at=to_recognition_instant(advance),
        actor_id="staff-1",
    )
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    smoke.say(
        f"normal disbursed {record.disbursement_value_date} loan {loan_number} "
        f"principal {_rands(servicing.ledger.bucket_balance(account, 'principal'))} "
        f"rate {account.snapshot.base_rate} day count {account.snapshot.day_count_code} "
        f"frozen {account.frozen_full_name}"
    )
    april = documents.issue_statement(
        organisation_id=ORG,
        person_id="person-normal",
        period_start=advance,
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=VAT,
    )
    april_loan = _section(april, account.loan_id)
    smoke.say(f"normal April closing: {_nonzero(april_loan.closing)}")
    smoke.say(f"normal April interest memos: {len(_memos(servicing.ledger, account.loan_id))}")
    submitted = rail.submit_collection(
        CollectionInstruction(
            loan_number=loan_number,
            amount_cents=RECEIPT,
            due_date=due,
            recognition_at=due,
            id_number=identity.id_number,
        )
    )
    if not isinstance(submitted, CollectionSuccess):
        smoke.fail(f"debit-order dummy did not match the R219 receipt: {submitted}")
        return
    receipt = submitted.receipt
    smoke.say(
        f"debit-order dummy receipt {receipt.receipt_sequence} {receipt.loan_number} "
        f"{_rands(receipt.amount_cents)} at {receipt.recognition_at.isoformat()}"
    )
    if receipt.recognition_at != to_recognition_instant(due):
        smoke.fail(f"receipt recognition is {receipt.recognition_at}, not 00:00 Africa/Johannesburg")
    payment = servicing.accept_payment(
        organisation_id=ORG,
        person_id="person-normal",
        cents=receipt.amount_cents,
        recognised_at=receipt.recognition_at,
        idempotency_key="pay-normal",
        agreement_id=record.agreement_id,
        attributed_due_on=due,
    )
    loan_tx = servicing.ledger.store.get_transaction(ORG, payment.ledger_transaction_id)
    smoke.say(f"normal 1 May credits: {_credits(loan_tx)}")
    smoke.say(
        "normal after receipt: "
        f"principal {_rands(servicing.ledger.bucket_balance(account, 'principal'))}, "
        f"interest {_rands(servicing.ledger.bucket_balance(account, 'interest'))}, "
        f"service {_rands(servicing.ledger.bucket_balance(account, 'service'))}"
    )
    may = documents.issue_statement(
        organisation_id=ORG,
        person_id="person-normal",
        period_start=due,
        period_end=due,
        interest_cap_present=True,
        vat_rate=VAT,
    )
    may_loan = _section(may, account.loan_id)
    smoke.say(f"normal 1 May opening: {_nonzero(may_loan.opening)}")
    smoke.say(f"normal 1 May closing: {_nonzero(may_loan.closing)}")
    smoke.say(f"normal 1 May opening source: {may_loan.opening_source}")
    if may_loan.opening != april_loan.closing:
        smoke.fail(
            f"1 May opening {may_loan.opening} is not the April closing {april_loan.closing}"
        )
    may_memos = [item for item in _memos(servicing.ledger, account.loan_id) if item.value_date == due]
    smoke.say(
        "normal 1 May accrual memos: "
        + ", ".join(f"{item.memo_rands} rands" for item in may_memos)
    )
    smoke.measured["normal_april_closing"] = dict(april_loan.closing)
    smoke.measured["normal_april_interest"] = april_loan.closing["interest"]
    smoke.measured["normal_may_opening"] = dict(may_loan.opening)
    smoke.measured["normal_credits"] = _credits(loan_tx)
    smoke.measured["normal_may_memo"] = None if not may_memos else str(may_memos[0].memo_rands)
    if may_memos and str(may_memos[0].memo_rands) == "3.1451612903":
        smoke.gap(
            "The 1 May interest memo is 3.1451612903 rands, which is 5% of the R1 950 principal "
            "left after the R219 receipt, divided by 31. Locked sections 1 and 8 treat the day's "
            "events as 00:00 and capitalise before allocating. The receipt path posted the receipt "
            "before the statement accrued 1 May, so the day's interest uses the reduced balance. "
            "A memo on the R2 000 balance that existed at the start of 1 May would be 3.2258064516 rands. "
            "The memo was not billed. Event: R219 receipt on 1 May, then the 1 May statement."
        )
    smoke.gap(
        "Orchestration section 6 calls Notifications.push after Documents.issue_statement. "
        "This tree has no notifications module, and issue_statement does not push. "
        "Event: normal lifecycle April and 1 May statements."
    )


def _open_period(smoke, servicing, documents, engine, identity) -> None:
    approval = _approve(
        engine,
        identity,
        amount=CASH,
        term=2,
        frequency=PaymentFrequency.MONTHLY,
        instalment=100_000,
    )
    advance = date(2026, 4, 15)
    first = date(2026, 5, 1)
    final = date(2026, 6, 1)
    record = _book(
        servicing,
        "person-open",
        advance,
        CASH,
        "monthly",
        ((first, 100_000), (final, 100_000)),
        "book-open",
    )
    record = _disburse(servicing, record.agreement_id, advance)
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    april = documents.issue_statement(
        organisation_id=ORG,
        person_id="person-open",
        period_start=advance,
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=VAT,
    )
    may = documents.issue_statement(
        organisation_id=ORG,
        person_id="person-open",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        interest_cap_present=True,
        vat_rate=VAT,
    )
    fees = [row for row in _charges(account) if row[0] == "service"]
    smoke.say(
        f"open-period approval {approval.application_number}; "
        f"disbursed {advance.isoformat()} first due {first.isoformat()} final due {final.isoformat()}"
    )
    smoke.say("open-period service fees (bucket, levied_on, ex VAT, VAT, total): " + str(fees))
    smoke.say(f"open-period April closing: {_nonzero(_section(april, account.loan_id).closing)}")
    smoke.say(f"open-period May closing: {_nonzero(_section(may, account.loan_id).closing)}")
    smoke.measured["open_fees"] = fees
    if len(fees) < 2:
        smoke.gap(f"open-period levied {len(fees)} service fee(s); expected the opening month and the next month")
        return
    opening, following = fees[0], fees[1]
    full = 6_900
    if opening[4] >= full:
        smoke.gap(f"opening-month service fee is {_rands(opening[4])}, which is not a pro-rata of the R60 cap")
    if following[4] != full:
        smoke.gap(f"next-month service fee is {_rands(following[4])}, not the full {_rands(full)}")


def _weekly(smoke, servicing, payments, engine, identity) -> None:
    dues = (
        date(2026, 4, 8),
        date(2026, 4, 15),
        date(2026, 4, 22),
        date(2026, 4, 29),
        date(2026, 5, 6),
    )
    instalment = 40_000
    approval = _approve(
        engine,
        identity,
        amount=CASH,
        term=len(dues),
        frequency=PaymentFrequency.WEEKLY,
        instalment=instalment,
    )
    advance = date(2026, 4, 1)
    record = _book(
        servicing,
        "person-weekly",
        advance,
        CASH,
        "weekly",
        tuple((due, instalment) for due in dues),
        "book-weekly",
    )
    record = _disburse(servicing, record.agreement_id, advance)
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    before = documents_interest(servicing, account.loan_id)
    for due in dues:
        payments.capitalise_due_amounts(
            record,
            due,
            interest_cap_present=True,
            vat_rate=VAT,
        )
    fees = [row for row in _charges(account) if row[0] == "service"]
    bills = [(item.value_date.isoformat(), item.amount_cents) for item in _bills(servicing.ledger, account.loan_id)]
    memo_days = sorted({item.value_date for item in _memos(servicing.ledger, account.loan_id)})
    smoke.say(
        f"weekly approval {approval.application_number} frequency {approval.payment_frequency}; "
        f"dues {[due.isoformat() for due in dues]}"
    )
    smoke.say(f"weekly accrual days: {len(memo_days)} from {memo_days[0] if memo_days else None} to {memo_days[-1] if memo_days else None}")
    smoke.say(f"weekly interest bills (value date, cents): {bills}")
    smoke.say(f"weekly service fees: {fees}")
    smoke.say(f"weekly interest bucket before the rail capitalised: {before}")
    expected_days = (dues[-1] - advance).days + 1
    if len(memo_days) != expected_days:
        smoke.gap(f"weekly accrual covered {len(memo_days)} days; the term has {expected_days}")
    if len(fees) != 2:
        smoke.gap(f"weekly service fee was levied {len(fees)} times across {len(dues)} due dates")
    if [item[0] for item in bills] != [due.isoformat() for due in dues]:
        smoke.gap(f"interest was not capitalised on each weekly due date: {bills}")
    smoke.measured["weekly_fees"] = fees
    smoke.measured["weekly_bills"] = bills
    smoke.measured["weekly_days"] = len(memo_days)


def documents_interest(servicing, loan_id: str) -> int:
    account = servicing.ledger.store.get(ORG, loan_id)
    return servicing.ledger.bucket_balance(account, "interest")


def _settlement(smoke, servicing, documents, engine, identity) -> None:
    approval = _approve(
        engine,
        identity,
        amount=CASH,
        term=1,
        frequency=PaymentFrequency.MONTHLY,
        instalment=CASH,
    )
    advance = date(2026, 4, 1)
    final = date(2026, 6, 1)
    record = _book(servicing, "person-settle", advance, CASH, "monthly", ((final, CASH),), "book-settle")
    record = _disburse(servicing, record.agreement_id, advance)
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    before = {
        bucket: servicing.ledger.bucket_balance(account, bucket)
        for bucket in ("principal", "interest", "service")
    }
    as_of = date(2026, 5, 15)
    quote = documents.settlement_quote(
        agreement_id=record.agreement_id,
        as_of=as_of,
        delivered_on=as_of,
        request_on=as_of,
        holidays=frozenset(),
        vat_rate=VAT,
    )
    after = {
        bucket: servicing.ledger.bucket_balance(account, bucket)
        for bucket in ("principal", "interest", "service")
    }
    smoke.say(
        f"settlement approval {approval.application_number}; "
        f"as of {quote.as_of.isoformat()} delivered {quote.delivered_on.isoformat()} "
        f"valid until {quote.valid_until.isoformat()}"
    )
    smoke.say(
        f"settlement quote principal {_rands(quote.principal_cents)} "
        f"interest {_rands(quote.interest_cents)} fees {_rands(quote.fee_cents)} "
        f"early termination {_rands(quote.early_termination_cents)} "
        f"total {_rands(quote.total_cents)} components {quote.components}"
    )
    if quote.early_termination_cents != 0:
        smoke.fail(f"early termination is {_rands(quote.early_termination_cents)}")
    if before != after:
        smoke.fail(f"settlement quote posted: before {before} after {after}")
    if quote.fee_cents < 6_900:
        smoke.gap(f"settlement fees are {_rands(quote.fee_cents)}, below one full monthly service fee")
    service = sum(amount for kind, amount in quote.components if kind == "service")
    initiation = sum(amount for kind, amount in quote.components if kind == "initiation")
    if service != 13_800:
        smoke.gap(
            f"settlement service component is {_rands(service)}. "
            f"A full fee in April and in the May settlement month is {_rands(13_800)}."
        )
    if initiation:
        smoke.gap(
            "The agreement was booked with an initiation fee of 0 cents. "
            f"The settlement quote includes initiation {_rands(initiation)}. "
            "Documents.settlement_quote builds an engine agreement without the booked initiation amount, "
            "and the engine prices the statutory initiation formula. The quote did not post that fee. "
            "Event: settlement requested on 15 May 2026."
        )
    smoke.measured["quote"] = (
        quote.principal_cents,
        quote.interest_cents,
        quote.fee_cents,
        quote.early_termination_cents,
        quote.total_cents,
        quote.valid_until.isoformat(),
        quote.components,
    )
    if not hasattr(servicing.ledger, "quote_settlement"):
        smoke.gap(
            "Orchestration section 7 calls Ledger.quote_settlement, then Documents.settlement_quote. "
            "Ledger has no quote_settlement. Documents.settlement_quote called the calculation engine "
            "and did not post. Event: settlement requested on 15 May 2026."
        )


def _collections_default(smoke, servicing, documents, collections, engine, rail, payments, identity) -> None:
    approval = _approve(
        engine,
        identity,
        amount=CASH,
        term=1,
        frequency=PaymentFrequency.MONTHLY,
        instalment=CASH,
    )
    advance = date(2026, 4, 1)
    due = date(2026, 5, 1)
    record = _book(servicing, "person-default", advance, CASH, "monthly", ((due, CASH),), "book-default")
    collections.bind(
        record.agreement_id,
        in_duplum_trigger="collections_default",
        residual_threshold_cents=RESIDUAL,
    )
    record = _disburse(servicing, record.agreement_id, advance)
    documents.issue_statement(
        organisation_id=ORG,
        person_id="person-default",
        period_start=advance,
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=VAT,
    )
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    on_due = collections.observe(record.agreement_id, recognised_at=to_recognition_instant(due))
    flag_on = due + timedelta(days=3)
    flagged = collections.observe(record.agreement_id, recognised_at=to_recognition_instant(flag_on))
    ceiling = flagged.open_episode_ceiling
    principal_at_flag = servicing.ledger.bucket_balance(account, "principal")
    smoke.say(
        f"collections approval {approval.application_number}; "
        f"observe {due.isoformat()}: default={on_due.collections_default} ceiling={on_due.open_episode_ceiling} "
        f"episodes={on_due.episode_count}"
    )
    smoke.say(
        f"collections observe {flag_on.isoformat()}: default={flagged.collections_default} "
        f"ceiling={ceiling} episodes={flagged.episode_count} "
        f"principal {_rands(principal_at_flag)} breaches={flagged.contractual_breaches}"
    )
    if not flagged.collections_default or flagged.episode_count != 1:
        smoke.gap("collections default did not open an episode on the flag date")
    if ceiling != principal_at_flag:
        smoke.gap(f"ceiling {ceiling} is not the unpaid principal {principal_at_flag}")
    loan_number = payments.register_loan_number(
        organisation_id=ORG,
        agreement_id=record.agreement_id,
        application_number=approval.application_number,
        recognised_at=to_recognition_instant(flag_on),
        actor_id="staff-1",
    )
    pay_on = date(2026, 5, 5)
    submitted = rail.submit_collection(
        CollectionInstruction(
            loan_number=loan_number,
            amount_cents=20_000,
            due_date=due,
            recognition_at=pay_on,
            id_number=identity.id_number,
        )
    )
    if not isinstance(submitted, CollectionSuccess):
        smoke.fail(f"collections receipt was not matched: {submitted}")
        return
    servicing.accept_payment(
        organisation_id=ORG,
        person_id="person-default",
        cents=submitted.receipt.amount_cents,
        recognised_at=submitted.receipt.recognition_at,
        idempotency_key="pay-default",
        agreement_id=record.agreement_id,
        attributed_due_on=due,
    )
    later = collections.observe(record.agreement_id, recognised_at=to_recognition_instant(pay_on))
    principal_after = servicing.ledger.bucket_balance(account, "principal")
    interest_after = servicing.ledger.bucket_balance(account, "interest")
    service_after = servicing.ledger.bucket_balance(account, "service")
    smoke.say(
        f"collections after {_rands(20_000)} on {pay_on.isoformat()}: "
        f"default={later.collections_default} ceiling={later.open_episode_ceiling} "
        f"episodes={later.episode_count} "
        f"principal {_rands(principal_after)} interest {_rands(interest_after)} service {_rands(service_after)}"
    )
    if later.open_episode_ceiling != ceiling:
        smoke.gap(f"payment changed the ceiling from {ceiling} to {later.open_episode_ceiling}")
    if later.episode_count != 1 or not later.collections_default:
        smoke.gap("payment reset the collections-default episode")
    outstanding_before = principal_at_flag + 10_000 + 6_900
    outstanding_after = principal_after + interest_after + service_after
    smoke.say(
        f"collections outstanding before the R200 receipt {_rands(outstanding_before)}, "
        f"after {_rands(outstanding_after)}"
    )
    if outstanding_after >= outstanding_before:
        smoke.gap("the receipt during the episode did not reduce the balance")
    smoke.measured["collections"] = (
        ceiling,
        principal_at_flag,
        principal_after,
        interest_after,
        service_after,
        later.collections_default,
        outstanding_after,
    )


def _write_off(smoke, servicing, documents, collections, engine, identity) -> None:
    cash = 10_000
    approval = _approve(
        DecisionEngineDummy.fixed_success(contractual_periodic_rate_bps=500, instalment_cents=cash),
        identity,
        amount=cash,
        term=1,
        frequency=PaymentFrequency.MONTHLY,
        instalment=cash,
    )
    advance = date(2026, 4, 1)
    due = date(2026, 5, 1)
    record = _book(servicing, "person-writeoff", advance, cash, "monthly", ((due, cash),), "book-writeoff")
    collections.bind(
        record.agreement_id,
        in_duplum_trigger="collections_default",
        residual_threshold_cents=RESIDUAL,
    )
    record = _disburse(servicing, record.agreement_id, advance)
    documents.issue_statement(
        organisation_id=ORG,
        person_id="person-writeoff",
        period_start=advance,
        period_end=date(2026, 4, 30),
        interest_cap_present=True,
        vat_rate=VAT,
    )
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    servicing.accept_payment(
        organisation_id=ORG,
        person_id="person-writeoff",
        cents=cash,
        recognised_at=to_recognition_instant(due),
        idempotency_key="pay-writeoff",
        agreement_id=record.agreement_id,
        attributed_due_on=due,
    )
    before = {
        bucket: servicing.ledger.bucket_balance(account, bucket)
        for bucket in ("principal", "interest", "service", "initiation")
    }
    outstanding = sum(before.values())
    smoke.say(
        f"write-off approval {approval.application_number}; "
        f"after the exact {_rands(cash)} instalment and before any staff instruction: "
        + ", ".join(f"{bucket} {_rands(amount)}" for bucket, amount in before.items())
        + f"; outstanding {_rands(outstanding)}; status {record.status}"
    )
    if outstanding == 0:
        smoke.gap("the residual was already R0 before a staff instruction")
    if record.status == "written_off":
        smoke.gap("the loan was written off without a staff instruction")
    staff_on = date(2026, 5, 2)
    try:
        view = collections.propose_residual_write_off(
            record.agreement_id,
            recognised_at=to_recognition_instant(staff_on),
        )
    except CollectionsError as exc:
        smoke.say(f"write-off staff instruction refused: {exc.code}: {exc}")
        smoke.gap(
            f"propose_residual_write_off refused {exc.code} with outstanding {_rands(outstanding)}. "
            "Event: residual after the final instalment."
        )
        smoke.measured["write_off"] = ("refused", exc.code, outstanding)
        return
    after = {
        bucket: servicing.ledger.bucket_balance(account, bucket)
        for bucket in ("principal", "interest", "service", "initiation")
    }
    smoke.say(
        f"write-off after staff instruction on {staff_on.isoformat()}: "
        + ", ".join(f"{bucket} {_rands(amount)}" for bucket, amount in after.items())
        + f"; written_off={view.written_off} status {record.status}"
    )
    if sum(after.values()) != 0 or not view.written_off:
        smoke.gap(f"staff write-off left {after}")
    smoke.measured["write_off"] = ("posted", outstanding, after, view.written_off)


def _campaign(smoke, servicing, campaigns, engine, identity) -> None:
    approval = _approve(
        engine,
        identity,
        amount=CASH,
        term=1,
        frequency=PaymentFrequency.MONTHLY,
        instalment=CASH,
    )
    advance = date(2026, 4, 1)
    final = date(2026, 6, 1)
    record = _book(servicing, "person-campaign", advance, CASH, "monthly", ((final, CASH),), "book-campaign")
    record = _disburse(servicing, record.agreement_id, advance)
    account = servicing.ledger.store.get(ORG, record.ledger_loan_id)
    campaigns.register_account(
        organisation_id=ORG,
        loan_id=account.loan_id,
        product_code="micro_short_term",
        contractual_fees_cents={"service": SERVICE_FEE_MONTHLY_CENTS},
        actor_id="staff-1",
    )
    notice = date(2026, 4, 24)
    start = earliest_effective(notice)
    end = start + timedelta(days=6)
    before_lines = tuple(account.schedule_versions[-1].lines)
    before_end = account.contractual_end
    before_rate = account.snapshot.base_rate
    campaign = campaigns.create(
        organisation_id=ORG,
        actor_id="staff-1",
        recognised_at=to_recognition_instant(notice),
        start_date=start,
        end_date=end,
        rate_reduction=Decimal("0.02"),
        rate_scope="campaign_period",
        fee_reductions={},
        fee_scope=None,
        payment_holiday=False,
        notice_date=notice,
    )
    campaigns.apply(
        campaign.campaign_id,
        organisation_id=ORG,
        actor_id="staff-1",
        recognised_at=to_recognition_instant(start),
        selector="loans",
        loan_ids=(account.loan_id,),
    )
    inside = campaigns.accrue(
        organisation_id=ORG,
        loan_id=account.loan_id,
        recognised_at=to_recognition_instant(start),
        interest_cap_present=True,
    )
    after = end + timedelta(days=1)
    resumed = campaigns.accrue(
        organisation_id=ORG,
        loan_id=account.loan_id,
        recognised_at=to_recognition_instant(after),
        interest_cap_present=True,
    )
    smoke.say(
        f"campaign approval {approval.application_number}; notice {notice.isoformat()} "
        f"start {start.isoformat()} end {end.isoformat()} reduction 0.02"
    )
    smoke.say(
        f"campaign inside {inside.value_date.isoformat()} rate {inside.periodic_rate} "
        f"memo {inside.day_rands} rands on base {_rands(inside.base_cents)}"
    )
    smoke.say(
        f"campaign after {resumed.value_date.isoformat()} rate {resumed.periodic_rate} "
        f"memo {resumed.day_rands} rands on base {_rands(resumed.base_cents)}"
    )
    smoke.say(
        f"campaign term unchanged={account.schedule_versions[-1].lines == before_lines} "
        f"end {before_end.isoformat()} still {account.contractual_end.isoformat()} "
        f"stored rate {before_rate} still {account.snapshot.base_rate}"
    )
    if inside.periodic_rate != Decimal("0.03"):
        smoke.gap(f"campaign accrual rate was {inside.periodic_rate}, not 0.03")
    if resumed.periodic_rate != before_rate:
        smoke.gap(f"rate after the campaign was {resumed.periodic_rate}, not {before_rate}")
    if account.schedule_versions[-1].lines != before_lines or account.contractual_end != before_end:
        smoke.gap("the campaign changed the contractual term or instalments")
    if account.snapshot.base_rate != before_rate:
        smoke.gap("the campaign overwrote the stored contractual rate")
    smoke.measured["campaign"] = (
        start.isoformat(),
        end.isoformat(),
        str(inside.periodic_rate),
        str(inside.day_rands),
        str(resumed.periodic_rate),
        str(resumed.day_rands),
    )
    _pin(smoke)


def _pin(smoke: Smoke) -> None:
    """The cents this run produced. A later change has to show up here."""
    expected = {
        "normal_april_interest": 10_000,
        "normal_credits": [("interest", 10_000), ("service", 6_900), ("principal", 5_000)],
        "normal_may_memo": "3.1451612903",
        "open_fees": [
            ("service", date(2026, 4, 30), 3_200, 480, 3_680),
            ("service", date(2026, 5, 31), 6_000, 900, 6_900),
        ],
        "weekly_days": 36,
        "weekly_bills": [
            ("2026-04-08", 2_667),
            ("2026-04-15", 2_333),
            ("2026-04-22", 2_333),
            ("2026-04-29", 2_334),
            ("2026-05-06", 2_268),
        ],
        "weekly_fees": [
            ("service", date(2026, 4, 1), 1_400, 210, 1_610),
            ("service", date(2026, 5, 6), 6_000, 900, 6_900),
        ],
        "quote": (
            200_000,
            14_839,
            44_275,
            0,
            259_114,
            "2026-05-22",
            (("initiation", 30_475), ("interest", 14_839), ("principal", 200_000), ("service", 13_800)),
        ),
        "collections": (200_000, 200_000, 196_900, 0, 0, True, 196_900),
        "write_off": (
            "posted",
            7_400,
            {"principal": 0, "interest": 0, "service": 0, "initiation": 0},
            True,
        ),
        "campaign": ("2026-05-04", "2026-05-10", "0.03", "1.9354838710", "0.05", "3.2258064516"),
    }
    for key, value in expected.items():
        if smoke.measured.get(key) != value:
            smoke.fail(f"{key}: measured {smoke.measured.get(key)!r}, pinned {value!r}")
    opening = smoke.measured.get("normal_may_opening")
    closing = smoke.measured.get("normal_april_closing")
    if opening != closing:
        smoke.fail(f"1 May opening {opening} is not the April closing {closing}")
