"""Day-1 product parameter templates.

These are commercial starting points a tenant may only lower, inside the
statutory ceiling. They are not themselves the statute. Enrolment of an
organisation onto a product is Enigma's decision; publishing these
parameters is the LMS's.
"""

from decimal import Decimal

from lms_config.statute import (
    DAY_COUNT_365,
    DAY_COUNT_ACTUAL_MONTH,
    SERVICE_FEE_MONTHLY_CENTS,
    SHORT_TERM_DEFERRED_CENTS,
    SHORT_TERM_FIRST_MONTHLY,
    SHORT_TERM_MAX_MONTHS,
    UNSECURED_REPO_MARGIN,
)
from lms_config.validate import (
    SHORT_TERM,
    UNSECURED,
    ZERO_COST,
    CPA_LAYBY,
    FeeTerms,
    InstrumentTerms,
    ProductTerms,
)

# Below the section 9 large-agreement line (R250 000). Chosen so the
# unsettled section 125(2)(c) early-termination charge is outside Day-1.
UNSECURED_DAY1_MAX_PRINCIPAL_CENTS = 24_999_999


def micro_short_term() -> ProductTerms:
    return ProductTerms(
        classification=SHORT_TERM,
        max_principal_cents=SHORT_TERM_DEFERRED_CENTS,
        instruments=(
            InstrumentTerms(
                code="loan",
                kind="credit",
                monthly_rate=SHORT_TERM_FIRST_MONTHLY,
                day_count=DAY_COUNT_ACTUAL_MONTH,
                max_term_months=SHORT_TERM_MAX_MONTHS,
                max_deferred_cents=SHORT_TERM_DEFERRED_CENTS,
                fees=(
                    FeeTerms("initiation", charge="statutory_formula"),
                    FeeTerms("service", amount_cents=SERVICE_FEE_MONTHLY_CENTS, charge="fixed"),
                    FeeTerms("default_admin", charge="tariff"),
                    FeeTerms("collection", charge="tariff"),
                ),
            ),
        ),
    )


def unsecured_personal() -> ProductTerms:
    return ProductTerms(
        classification=UNSECURED,
        max_principal_cents=UNSECURED_DAY1_MAX_PRINCIPAL_CENTS,
        instruments=(
            InstrumentTerms(
                code="loan",
                kind="credit",
                repo_margin=UNSECURED_REPO_MARGIN,
                day_count=DAY_COUNT_365,
                max_term_months=60,
                fees=(
                    FeeTerms("initiation", charge="statutory_formula"),
                    FeeTerms("service", amount_cents=SERVICE_FEE_MONTHLY_CENTS, charge="fixed"),
                    FeeTerms("default_admin", charge="tariff"),
                    FeeTerms("collection", charge="tariff"),
                ),
            ),
        ),
    )


def bnpl_zero() -> ProductTerms:
    """No interest, no fee, no late charge.

    The moment a charge is added this classification is wrong: the agreement
    has to be republished as incidental credit (2% per month, initiation nil)
    or as another NCA classification. The engine does not reclassify silently.
    """
    return ProductTerms(
        classification=ZERO_COST,
        instruments=(
            InstrumentTerms(code="plan", kind="credit", monthly_rate=Decimal(0), annual_rate=Decimal(0)),
        ),
    )


def layby_goods() -> ProductTerms:
    """CPA section 62 lay-by. Penalty ceiling is the statutory 1%.

    The penalty is still nil unless it was disclosed before the agreement
    and the consumer's failure is not death or hospitalisation.
    """
    return ProductTerms(
        classification=CPA_LAYBY,
        instruments=(
            InstrumentTerms(
                code="goods",
                kind="cpa_layby",
                monthly_rate=Decimal(0),
                fees=(FeeTerms("layby_penalty", charge="statutory_formula"),),
            ),
        ),
    )


def layby_security_short_term() -> ProductTerms:
    """High-risk short-term loan plus a zero-interest cash deposit.

    The deposit is not a CPA lay-by of goods, so the 1% cancellation penalty
    is not available. Set-off is refused unless the posting carries an
    Enigma mandate id (section 124 authorisation is checked by servicing,
    not invented here).
    """
    loan = micro_short_term().instruments[0]
    deposit = InstrumentTerms(
        code="deposit",
        kind="security_deposit",
        monthly_rate=Decimal(0),
        annual_rate=Decimal(0),
        setoff_requires_mandate=True,
        fees=(FeeTerms("layby_penalty", charge="zero"),),
    )
    return ProductTerms(
        classification=SHORT_TERM,
        max_principal_cents=SHORT_TERM_DEFERRED_CENTS,
        instruments=(loan, deposit),
    )
