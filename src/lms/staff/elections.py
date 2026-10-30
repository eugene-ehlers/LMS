"""Decision 19 elections. Organisation row, optional product override.

Unset values fail closed when a caller asks for the resolved row. A list
returns the stored nulls. The residual threshold is not filled: decision 8
names R100 and decision 19 says an unset election fails closed, and this
module does not choose between those two sentences.

``resolve_residual_threshold_cents`` is not called. It fills 5 000 cents.
``resolve_in_duplum_trigger`` is called. It already fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.staff.campaigns import check_fall_away
from lms_config.exceptions import CalculationInputError
from lms_config.locked import (
    INTEREST_ON_INITIATION_NONE,
    INTEREST_ON_INITIATION_PERMITTED,
    LATE_DISBURSEMENT_ADJUST,
    LATE_DISBURSEMENT_KEEP,
    PREPAY_DROP,
    PREPAY_SHORTEN,
    REPO_FALL_CONTRACT,
    REPO_FALL_LOWER,
    VAT_EXCLUSIVE,
    VAT_INCLUSIVE,
    resolve_in_duplum_trigger,
)
from lms.staff.rates import integer_cents


_VAT = frozenset({VAT_EXCLUSIVE, VAT_INCLUSIVE})
_LATE = frozenset({LATE_DISBURSEMENT_ADJUST, LATE_DISBURSEMENT_KEEP})
_PREPAY = frozenset({PREPAY_SHORTEN, PREPAY_DROP})
_INITIATION = frozenset({INTEREST_ON_INITIATION_NONE, INTEREST_ON_INITIATION_PERMITTED})
_REPO = frozenset({REPO_FALL_CONTRACT, REPO_FALL_LOWER})


@dataclass(frozen=True, slots=True)
class ElectionValues:
    vat_on_rand_maxima: str | None = None
    late_disbursement: str | None = None
    partial_prepayment: str | None = None
    interest_on_deferred_initiation: str | None = None
    repo_rate_fall: str | None = None
    in_duplum_trigger: str | None = None
    residual_write_off_threshold_cents: int | None = None
    campaign_fall_away_choice: str | None = None
    campaign_fall_away_trigger: str | None = None


def check_elections(values: ElectionValues) -> None:
    """Reject a value outside the locked vocabulary. Null is left for resolve."""
    _one(values.vat_on_rand_maxima, _VAT, "vat_on_rand_maxima")
    _one(values.late_disbursement, _LATE, "late_disbursement")
    _one(values.partial_prepayment, _PREPAY, "partial_prepayment")
    _one(values.interest_on_deferred_initiation, _INITIATION, "interest_on_deferred_initiation")
    _one(values.repo_rate_fall, _REPO, "repo_rate_fall")
    if values.in_duplum_trigger is not None:
        resolve_in_duplum_trigger(values.in_duplum_trigger)
    if values.residual_write_off_threshold_cents is not None:
        integer_cents(
            values.residual_write_off_threshold_cents,
            "residual write-off threshold",
        )
    if values.campaign_fall_away_choice is None:
        if values.campaign_fall_away_trigger is not None:
            raise CalculationInputError(
                "campaign fall-away trigger is set without a fall-away choice"
            )
        return
    check_fall_away(values.campaign_fall_away_choice, values.campaign_fall_away_trigger)


def resolve_elections(organisation: ElectionValues, product: ElectionValues | None) -> ElectionValues:
    """Product override wins. A null at both levels fails closed.

    The fall-away choice and trigger move together. A product that sets a
    choice does not keep the organisation trigger.
    """
    product = product or ElectionValues()
    check_elections(organisation)
    check_elections(product)
    if product.campaign_fall_away_choice is not None:
        choice = product.campaign_fall_away_choice
        trigger = product.campaign_fall_away_trigger
    else:
        choice = organisation.campaign_fall_away_choice
        trigger = organisation.campaign_fall_away_trigger
    resolved = ElectionValues(
        vat_on_rand_maxima=_pick(product.vat_on_rand_maxima, organisation.vat_on_rand_maxima),
        late_disbursement=_pick(product.late_disbursement, organisation.late_disbursement),
        partial_prepayment=_pick(product.partial_prepayment, organisation.partial_prepayment),
        interest_on_deferred_initiation=_pick(
            product.interest_on_deferred_initiation,
            organisation.interest_on_deferred_initiation,
        ),
        repo_rate_fall=_pick(product.repo_rate_fall, organisation.repo_rate_fall),
        in_duplum_trigger=resolve_in_duplum_trigger(
            organisation.in_duplum_trigger,
            product.in_duplum_trigger,
        ),
        residual_write_off_threshold_cents=_residual(
            organisation.residual_write_off_threshold_cents,
            product.residual_write_off_threshold_cents,
        ),
        campaign_fall_away_choice=choice,
        campaign_fall_away_trigger=trigger,
    )
    check_fall_away(resolved.campaign_fall_away_choice, resolved.campaign_fall_away_trigger)
    if resolved.vat_on_rand_maxima is None:
        raise CalculationInputError("vat_on_rand_maxima is not set on the product or the organisation")
    if resolved.late_disbursement is None:
        raise CalculationInputError("late_disbursement is not set on the product or the organisation")
    if resolved.partial_prepayment is None:
        raise CalculationInputError("partial_prepayment is not set on the product or the organisation")
    if resolved.interest_on_deferred_initiation is None:
        raise CalculationInputError(
            "interest_on_deferred_initiation is not set on the product or the organisation"
        )
    if resolved.repo_rate_fall is None:
        raise CalculationInputError("repo_rate_fall is not set on the product or the organisation")
    return resolved


class ElectionStore:
    def __init__(self) -> None:
        self._organisation: dict[str, ElectionValues] = {}
        self._product: dict[tuple[str, str], ElectionValues] = {}

    def put_organisation(self, organisation_id: str, values: ElectionValues) -> ElectionValues:
        _organisation_id(organisation_id)
        check_elections(values)
        self._organisation[organisation_id] = values
        return values

    def get_organisation(self, organisation_id: str) -> ElectionValues:
        _organisation_id(organisation_id)
        return self._organisation.get(organisation_id, ElectionValues())

    def put_product(self, organisation_id: str, product_id: str, values: ElectionValues) -> ElectionValues:
        _organisation_id(organisation_id)
        _product_id(product_id)
        check_elections(values)
        self._product[(organisation_id, product_id)] = values
        return values

    def get_product(self, organisation_id: str, product_id: str) -> ElectionValues:
        _organisation_id(organisation_id)
        _product_id(product_id)
        return self._product.get((organisation_id, product_id), ElectionValues())

    def list_products(self, organisation_id: str) -> tuple[tuple[str, ElectionValues], ...]:
        _organisation_id(organisation_id)
        rows = [
            (product_id, values)
            for (org, product_id), values in self._product.items()
            if org == organisation_id
        ]
        return tuple(sorted(rows, key=lambda item: item[0]))

    def require(self, organisation_id: str, product_id: str | None = None) -> ElectionValues:
        product = None if product_id is None else self.get_product(organisation_id, product_id)
        return resolve_elections(self.get_organisation(organisation_id), product)


def _pick(product_value, organisation_value):
    if product_value is not None:
        return product_value
    return organisation_value


def _residual(organisation: int | None, product: int | None) -> int:
    chosen = product if product is not None else organisation
    if chosen is None:
        raise CalculationInputError(
            "residual_write_off_threshold_cents is not set on the product or the organisation"
        )
    return integer_cents(chosen, "residual write-off threshold")


def _one(value: str | None, allowed: frozenset[str], label: str) -> None:
    if value is None:
        return
    if value not in allowed:
        raise CalculationInputError(f"{label} is not set on the product or the organisation")


def _organisation_id(organisation_id: str) -> None:
    if not organisation_id or not organisation_id.strip():
        raise CalculationInputError("organisation_id is blank")


def _product_id(product_id: str) -> None:
    if not product_id or not product_id.strip():
        raise CalculationInputError("product_id is blank")
