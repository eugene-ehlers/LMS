"""What the decision-engine dummy supplied, plus the campaign that qualified.

Decision 13: the LMS stores the rate and the credit-life premium it is
given. It does not decide whether the rate is the 5 % rate or the 3 % rate.

The open point in LOCKED_DECISIONS is which figure is the contractual rate
when a campaign also qualifies. This record keeps both. It does not copy
one over the other, and a later campaign edit does not rewrite it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from lms.staff.campaigns import Campaign
from lms.staff.errors import StaffError
from lms_config.exceptions import CalculationInputError
from lms.staff.rates import integer_cents


@dataclass(frozen=True, slots=True)
class DecisionIntake:
    intake_id: str
    organisation_id: str
    product_id: str | None
    application_number: str
    recognition_date: date
    supplied_rate: Decimal
    credit_life_premium_cents: int
    campaign_id: str | None
    campaign_base_rate: Decimal | None
    campaign_discount_rate: Decimal | None
    campaign_net_rate: Decimal | None
    campaign_fall_away_choice: str | None
    campaign_fall_away_trigger: str | None
    maturity_date: date | None


class IntakeStore:
    def __init__(self) -> None:
        self._rows: dict[str, DecisionIntake] = {}

    def add(self, row: DecisionIntake) -> DecisionIntake:
        self._rows[row.intake_id] = row
        return row

    def get(self, intake_id: str) -> DecisionIntake:
        row = self._rows.get(intake_id)
        if row is None:
            raise CalculationInputError(f"decision intake {intake_id} does not exist")
        return row

    def list(self, organisation_id: str) -> tuple[DecisionIntake, ...]:
        rows = [row for row in self._rows.values() if row.organisation_id == organisation_id]
        return tuple(sorted(rows, key=lambda row: (row.recognition_date, row.intake_id)))


def record_intake(
    *,
    organisation_id: str,
    product_id: str | None,
    application_number: str,
    recognition_date: date,
    supplied_rate: Decimal,
    credit_life_premium_cents: int,
    matches: tuple[Campaign, ...],
    maturity_date: date | None,
) -> DecisionIntake:
    if not application_number or not application_number.strip():
        raise CalculationInputError("application number is blank")
    if supplied_rate < 0:
        raise CalculationInputError("supplied rate cannot be negative")
    integer_cents(credit_life_premium_cents, "credit-life premium")
    if len(matches) > 1:
        raise StaffError(
            "campaign-ambiguous",
            "More than one campaign covers this recognition date. "
            "LOCKED_DECISIONS does not say which one qualifies, so the intake is not stored.",
        )
    campaign = matches[0] if matches else None
    return DecisionIntake(
        intake_id=str(uuid4()),
        organisation_id=organisation_id,
        product_id=product_id,
        application_number=application_number,
        recognition_date=recognition_date,
        supplied_rate=supplied_rate,
        credit_life_premium_cents=credit_life_premium_cents,
        campaign_id=None if campaign is None else campaign.campaign_id,
        campaign_base_rate=None if campaign is None else campaign.base_rate,
        campaign_discount_rate=None if campaign is None else campaign.discount_rate,
        campaign_net_rate=None if campaign is None else campaign.net_rate,
        campaign_fall_away_choice=None if campaign is None else campaign.fall_away_choice,
        campaign_fall_away_trigger=None if campaign is None else campaign.fall_away_trigger,
        maturity_date=maturity_date,
    )
