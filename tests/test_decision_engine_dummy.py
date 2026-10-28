from pathlib import Path

import pytest

from lms.dummies.decision_engine import DecisionEngineDummy
from lms.dummies.fixtures import (
    FIXED_CREDIT_LIFE_PREMIUM_CENTS,
    FIXED_INSTALMENT_CENTS,
    FIXED_PERIODIC_RATE_BPS,
)
from lms.errors import ContractError
from lms.ports.decision_engine import (
    Application,
    Approval,
    ConsumerIdentity,
    DecisionEngine,
    Decline,
    PaymentFrequency,
    ShortTermRateBand,
)
from tests.builders import application


def test_fixed_success_returns_the_canned_approval() -> None:
    engine = DecisionEngineDummy.fixed_success()

    approval = engine.decide(application())

    assert isinstance(engine, DecisionEngine)
    assert isinstance(approval, Approval)
    assert approval.kind == "approval"
    assert approval.application_number == "APP-00000001"
    assert approval.contractual_periodic_rate_bps == FIXED_PERIODIC_RATE_BPS
    assert approval.instalment_cents == FIXED_INSTALMENT_CENTS
    assert approval.credit_life_premium_cents == FIXED_CREDIT_LIFE_PREMIUM_CENTS
    assert approval.term_count == 6
    assert approval.payment_frequency is PaymentFrequency.MONTHLY
    assert approval.short_term_rate_band is ShortTermRateBand.FIVE_PERCENT


def test_short_term_flag_is_not_the_contractual_rate() -> None:
    engine = DecisionEngineDummy.fixed_success(
        short_term_rate_band=ShortTermRateBand.FIVE_PERCENT
    )

    approval = engine.decide(application())

    assert approval.short_term_rate_band is ShortTermRateBand.FIVE_PERCENT
    assert approval.contractual_periodic_rate_bps == 240
    assert approval.contractual_periodic_rate_bps not in (300, 500)


def test_three_percent_flag_and_absent_flag_are_fixed_by_the_scenario() -> None:
    three = DecisionEngineDummy.fixed_success(
        short_term_rate_band=ShortTermRateBand.THREE_PERCENT
    )
    absent = DecisionEngineDummy.fixed_success(short_term_rate_band=None)

    assert three.decide(application()).short_term_rate_band is ShortTermRateBand.THREE_PERCENT
    assert absent.decide(application(product_type="short_term")).short_term_rate_band is None


def test_product_type_does_not_change_the_fixed_result() -> None:
    engine = DecisionEngineDummy.fixed_success()

    short_term = engine.decide(application(product_type="short_term", requested_amount_cents=1))
    unsecured = engine.decide(
        application(product_type="unsecured_personal", requested_amount_cents=9_999_999)
    )
    other = engine.decide(application(product_type="laybye", requested_amount_cents=0))

    assert short_term.instalment_cents == unsecured.instalment_cents == other.instalment_cents
    assert short_term.contractual_periodic_rate_bps == unsecured.contractual_periodic_rate_bps
    assert {item.short_term_rate_band for item in (short_term, unsecured, other)} == {
        ShortTermRateBand.FIVE_PERCENT
    }
    assert [item.application_number for item in (short_term, unsecured, other)] == [
        "APP-00000001",
        "APP-00000002",
        "APP-00000003",
    ]


def test_term_is_echoed_and_the_instalment_is_not_recalculated() -> None:
    engine = DecisionEngineDummy.fixed_success()

    weekly = engine.decide(
        application(term_count=12, payment_frequency=PaymentFrequency.WEEKLY)
    )
    annual = engine.decide(
        application(term_count=3, payment_frequency="annual")
    )

    assert weekly.term_count == 12
    assert weekly.payment_frequency is PaymentFrequency.WEEKLY
    assert annual.term_count == 3
    assert annual.payment_frequency is PaymentFrequency.ANNUAL
    assert weekly.instalment_cents == annual.instalment_cents == FIXED_INSTALMENT_CENTS


def test_every_locked_frequency_is_accepted() -> None:
    engine = DecisionEngineDummy.fixed_success()

    for frequency in PaymentFrequency:
        approval = engine.decide(application(payment_frequency=frequency))
        assert approval.payment_frequency is frequency


def test_zero_rate_zero_instalment_and_zero_credit_life_are_returned_as_given() -> None:
    engine = DecisionEngineDummy.fixed_success(
        contractual_periodic_rate_bps=0,
        instalment_cents=0,
        credit_life_premium_cents=0,
    )

    approval = engine.decide(application())

    assert approval.contractual_periodic_rate_bps == 0
    assert approval.instalment_cents == 0
    assert approval.credit_life_premium_cents == 0


def test_a_configured_rate_is_not_clipped() -> None:
    engine = DecisionEngineDummy.fixed_success(contractual_periodic_rate_bps=99_999)

    assert engine.decide(application()).contractual_periodic_rate_bps == 99_999


def test_fixed_decline_has_an_application_number_and_no_pricing() -> None:
    engine = DecisionEngineDummy.fixed_decline()

    decline = engine.decide(application())

    assert isinstance(decline, Decline)
    assert decline.kind == "decline"
    assert decline.application_number == "APP-00000001"
    assert "instalment_cents" not in decline.__dataclass_fields__
    assert "short_term_rate_band" not in decline.__dataclass_fields__


def test_same_consumer_can_be_approved_twice_because_the_dummy_does_not_classify() -> None:
    engine = DecisionEngineDummy.fixed_success()

    first = engine.decide(application())
    second = engine.decide(application())

    assert isinstance(first, Approval)
    assert isinstance(second, Approval)


def test_amounts_must_be_integer_cents() -> None:
    with pytest.raises(ContractError):
        application(requested_amount_cents=1500.0)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        application(requested_amount_cents=True)  # type: ignore[arg-type]
    with pytest.raises(ContractError):
        application(requested_amount_cents=-1)


def test_invalid_term_frequency_and_identity_are_rejected() -> None:
    with pytest.raises(ContractError):
        application(term_count=0)
    with pytest.raises(ContractError):
        application(payment_frequency="daily")
    with pytest.raises(ContractError):
        application(product_type="  ")
    with pytest.raises(ContractError):
        ConsumerIdentity(person_id="", name="Test Consumer", id_number="0000000000000")


def test_call_site_accepts_another_implementation() -> None:
    class ScriptedEngine:
        def decide(self, application: Application) -> Decline:
            return Decline(application_number="APP-SCRIPTED")

    def request_decision(engine: DecisionEngine, payload: Application) -> Decline:
        result = engine.decide(payload)
        assert isinstance(result, Decline)
        return result

    scripted = request_decision(ScriptedEngine(), application())
    dummy = request_decision(DecisionEngineDummy.fixed_decline(), application())

    assert scripted.application_number == "APP-SCRIPTED"
    assert dummy.application_number == "APP-00000001"


def test_dummy_source_does_not_encode_concurrency_rules() -> None:
    source = Path("lms/dummies/decision_engine.py").read_text(encoding="utf-8").lower()

    for word in ("concurrent", "subsequent", "restructur", "settled-and-readvanced"):
        assert word not in source
