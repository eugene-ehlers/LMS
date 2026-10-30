"""Dated campaigns. An edit or an end does not touch a stored qualification.

Decision 3. The campaign stores the base rate and the discount. The net
shown on the record is ``net_rate``. Booked qualifications keep the copy
taken when the loan was generated.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

from lms.staff.rates import integer_cents, net_rate
from lms_config.exceptions import CalculationInputError
from lms_config.locked import TRIGGER_COLLECTIONS_DEFAULT, TRIGGER_CONTRACTUAL_BREACH


FALLS_AWAY_ON_DEFAULT = "falls_away_on_default"
DOES_NOT_FALL_AWAY = "does_not_fall_away"
FALL_AWAY_CHOICES = frozenset({FALLS_AWAY_ON_DEFAULT, DOES_NOT_FALL_AWAY})
FALL_AWAY_TRIGGERS = frozenset({TRIGGER_CONTRACTUAL_BREACH, TRIGGER_COLLECTIONS_DEFAULT})


@dataclass(frozen=True, slots=True)
class Campaign:
    campaign_id: str
    organisation_id: str
    product_id: str | None
    start_date: date
    end_date: date
    base_rate: Decimal
    discount_rate: Decimal
    net_rate: Decimal
    fall_away_choice: str
    fall_away_trigger: str | None
    initiation_fee_discount_cents: int
    service_fee_discount_cents: int
    version: int


def check_fall_away(choice: str | None, trigger: str | None) -> None:
    """Option A needs a trigger. Option B stores no trigger. Anything else fails closed."""
    if choice not in FALL_AWAY_CHOICES:
        raise CalculationInputError(
            "campaign fall-away choice is not falls_away_on_default or does_not_fall_away"
        )
    if choice == FALLS_AWAY_ON_DEFAULT:
        if trigger not in FALL_AWAY_TRIGGERS:
            raise CalculationInputError(
                "campaign fall-away trigger is not contractual_breach or collections_default"
            )
        return
    if trigger is not None:
        raise CalculationInputError(
            "a campaign that does not fall away has no fall-away trigger"
        )


def build_campaign(
    *,
    organisation_id: str,
    product_id: str | None,
    start_date: date,
    end_date: date,
    base_rate: Decimal,
    discount_rate: Decimal,
    fall_away_choice: str,
    fall_away_trigger: str | None,
    initiation_fee_discount_cents: int,
    service_fee_discount_cents: int,
    campaign_id: str | None = None,
    version: int = 1,
) -> Campaign:
    if not organisation_id or not organisation_id.strip():
        raise CalculationInputError("campaign organisation_id is blank")
    if product_id is not None and not product_id.strip():
        raise CalculationInputError("campaign product_id is blank")
    if end_date < start_date:
        raise CalculationInputError("campaign end date is before the start date")
    check_fall_away(fall_away_choice, fall_away_trigger)
    integer_cents(initiation_fee_discount_cents, "initiation fee discount")
    integer_cents(service_fee_discount_cents, "service fee discount")
    performing = net_rate(base_rate, discount_rate)
    return Campaign(
        campaign_id=campaign_id or str(uuid4()),
        organisation_id=organisation_id,
        product_id=product_id,
        start_date=start_date,
        end_date=end_date,
        base_rate=base_rate,
        discount_rate=discount_rate,
        net_rate=performing,
        fall_away_choice=fall_away_choice,
        fall_away_trigger=fall_away_trigger,
        initiation_fee_discount_cents=initiation_fee_discount_cents,
        service_fee_discount_cents=service_fee_discount_cents,
        version=version,
    )


class CampaignStore:
    """In-memory campaigns. Qualification copies the record; it does not keep a live reference."""

    def __init__(self) -> None:
        self._rows: dict[str, Campaign] = {}

    def add(self, campaign: Campaign) -> Campaign:
        if campaign.campaign_id in self._rows:
            raise CalculationInputError("campaign id already exists")
        self._rows[campaign.campaign_id] = campaign
        return campaign

    def replace(self, campaign: Campaign) -> Campaign:
        current = self.get(campaign.campaign_id)
        if current.organisation_id != campaign.organisation_id:
            raise CalculationInputError("a campaign cannot move to another organisation")
        self._rows[campaign.campaign_id] = campaign
        return campaign

    def get(self, campaign_id: str) -> Campaign:
        row = self._rows.get(campaign_id)
        if row is None:
            raise CalculationInputError(f"campaign {campaign_id} does not exist")
        return row

    def list(self, organisation_id: str) -> tuple[Campaign, ...]:
        rows = [row for row in self._rows.values() if row.organisation_id == organisation_id]
        return tuple(sorted(rows, key=lambda row: (row.start_date, row.campaign_id)))

    def covering(
        self,
        organisation_id: str,
        product_id: str | None,
        recognition_date: date,
    ) -> tuple[Campaign, ...]:
        """Campaigns whose inclusive period contains the loan's recognition date.

        An organisation campaign matches every product. A product campaign
        matches only that product. The loan term is not consulted: a term
        that runs past the end date still qualifies. More than one match is
        returned as-is. The caller fails closed. This function does not pick.
        """
        found: list[Campaign] = []
        for row in self.list(organisation_id):
            if row.product_id is not None and row.product_id != product_id:
                continue
            if row.start_date <= recognition_date <= row.end_date:
                found.append(row)
        return tuple(found)


def end_campaign(campaign: Campaign, recognition_date: date) -> Campaign:
    """Set the end date to the recognition date when that date is earlier.

    Already booked qualifications are not an argument of this function.
    Ending a campaign that has not started yet would put the end before
    the start, which is refused.
    """
    if recognition_date < campaign.start_date:
        raise CalculationInputError("campaign end date is before the start date")
    end_date = campaign.end_date if campaign.end_date <= recognition_date else recognition_date
    return replace(campaign, end_date=end_date, version=campaign.version + 1)
