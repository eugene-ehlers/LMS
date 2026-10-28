"""Fixed decision-engine dummy. It does not price, and it does not classify loans."""

from __future__ import annotations

from enum import StrEnum

from lms.dummies.fixtures import (
    APPLICATION_NUMBER_PREFIX,
    FIXED_CREDIT_LIFE_PREMIUM_CENTS,
    FIXED_INSTALMENT_CENTS,
    FIXED_PERIODIC_RATE_BPS,
)
from lms.errors import ContractError
from lms.ports.decision_engine import (
    Application,
    Approval,
    Decision,
    Decline,
    ShortTermRateBand,
    require_short_term_rate_band,
)
from lms.validation import require_cents, require_non_negative_int


class DecisionScenario(StrEnum):
    FIXED_SUCCESS = "fixed_success"
    FIXED_DECLINE = "fixed_decline"


class DecisionEngineDummy:
    """Return one canned approval, or one canned decline, for every valid application.

    The short-term flag is whatever this instance was given. Product type is
    accepted and is not used to choose the flag, the rate, or the instalment.
    """

    def __init__(
        self,
        *,
        scenario: DecisionScenario = DecisionScenario.FIXED_SUCCESS,
        short_term_rate_band: ShortTermRateBand | None = ShortTermRateBand.FIVE_PERCENT,
        contractual_periodic_rate_bps: int = FIXED_PERIODIC_RATE_BPS,
        instalment_cents: int = FIXED_INSTALMENT_CENTS,
        credit_life_premium_cents: int = FIXED_CREDIT_LIFE_PREMIUM_CENTS,
    ) -> None:
        if not isinstance(scenario, DecisionScenario):
            raise ContractError("scenario must be a DecisionScenario")
        self._scenario = scenario
        self._short_term_rate_band = require_short_term_rate_band(short_term_rate_band)
        self._contractual_periodic_rate_bps = require_non_negative_int(
            contractual_periodic_rate_bps, "contractual_periodic_rate_bps"
        )
        self._instalment_cents = require_cents(instalment_cents, "instalment_cents")
        self._credit_life_premium_cents = require_cents(
            credit_life_premium_cents, "credit_life_premium_cents"
        )
        self._issued = 0

    @classmethod
    def fixed_success(
        cls,
        *,
        short_term_rate_band: ShortTermRateBand | None = ShortTermRateBand.FIVE_PERCENT,
        contractual_periodic_rate_bps: int = FIXED_PERIODIC_RATE_BPS,
        instalment_cents: int = FIXED_INSTALMENT_CENTS,
        credit_life_premium_cents: int = FIXED_CREDIT_LIFE_PREMIUM_CENTS,
    ) -> DecisionEngineDummy:
        return cls(
            scenario=DecisionScenario.FIXED_SUCCESS,
            short_term_rate_band=short_term_rate_band,
            contractual_periodic_rate_bps=contractual_periodic_rate_bps,
            instalment_cents=instalment_cents,
            credit_life_premium_cents=credit_life_premium_cents,
        )

    @classmethod
    def fixed_decline(cls) -> DecisionEngineDummy:
        return cls(scenario=DecisionScenario.FIXED_DECLINE, short_term_rate_band=None)

    def decide(self, application: Application) -> Decision:
        if not isinstance(application, Application):
            raise ContractError("application must be an Application")
        self._issued += 1
        application_number = f"{APPLICATION_NUMBER_PREFIX}{self._issued:08d}"
        if self._scenario is DecisionScenario.FIXED_DECLINE:
            return Decline(application_number=application_number)
        return Approval(
            application_number=application_number,
            contractual_periodic_rate_bps=self._contractual_periodic_rate_bps,
            term_count=application.term_count,
            payment_frequency=application.payment_frequency,
            instalment_cents=self._instalment_cents,
            credit_life_premium_cents=self._credit_life_premium_cents,
            short_term_rate_band=self._short_term_rate_band,
        )
