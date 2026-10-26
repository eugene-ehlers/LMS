"""Figures transcribed from the instruments named on each constant.

Nothing in this module is inferred from market practice. Where a regulation
states a formula, the numbers are here and the unresolved reading of that
formula lives in ``interpret.py``.
"""

from decimal import Decimal

# GN 1080 in GG 39379 of 6 November 2015, effective six months later
# (6 May 2016). Substitutes regulation 42 Tables A and B and sets the
# regulation 44 monthly service-fee maximum at R60.
CAPS_EFFECTIVE_FROM = "2016-05-06"

SERVICE_FEE_MONTHLY_CENTS = 6_000

# Table B, short-term / unsecured / other / credit facilities.
# "R165 per credit agreement, plus 10% of the amount in excess of R1 000,
# but never to exceed R1 050."
INITIATION_FLAT_CENTS = 16_500
INITIATION_THRESHOLD_CENTS = 100_000
INITIATION_MARGINAL = Decimal("0.10")
INITIATION_ABSOLUTE_CENTS = 105_000

# Regulation 43(3), original regulations: the initiation fee may never
# exceed 15% of the principal debt. GN 1080 did not repeal this.
INITIATION_PRINCIPAL_RATIO = Decimal("0.15")

# Table A item 5. Both rates are in the gazette. Which loans are
# "subsequent" is not defined there; see interpret.ShortTermOrdinal.
SHORT_TERM_FIRST_MONTHLY = Decimal("0.05")
SHORT_TERM_SUBSEQUENT_MONTHLY = Decimal("0.03")

# Regulation 39(2): deferred amount at inception not exceeding R8,000,
# whole amount repayable within 6 months.
SHORT_TERM_DEFERRED_CENTS = 800_000
SHORT_TERM_MAX_MONTHS = 6

# Table A item 3: RR + 21% per year. The margin is the regulated figure.
# RR itself is reference data, not a constant.
UNSECURED_REPO_MARGIN = Decimal("0.21")

# Table A item 7.
INCIDENTAL_MONTHLY = Decimal("0.02")

# Table A, GN 1080. Margins over the SARB repurchase rate, per year.
REPO_MARGIN_BY_CLASSIFICATION = {
    "mortgage": Decimal("0.12"),
    "credit_facility": Decimal("0.14"),
    "unsecured": Decimal("0.21"),
    "developmental_small_business": Decimal("0.27"),
    "developmental_low_income_housing": Decimal("0.27"),
    "other": Decimal("0.17"),
}

# GN 713 in GG 28893 of 1 June 2006, section 7(1)(b) thresholds.
# Still stated in the 11 May 2016 consolidation. No later amendment
# was found in this pass; confirm before go-live.
AGREEMENT_LOWER_CENTS = 1_500_000  # small at or below
AGREEMENT_HIGHER_CENTS = 25_000_000  # large at or above

# CPA regulation 34 (GN R293, GG 34180): a lay-by cancellation penalty
# may not exceed 1% of the full purchase price.
LAYBY_PENALTY_RATIO = Decimal("0.01")

# SARB MPC statement of 23 September 2026: 7.25% effective 25 September 2026.
# Seeded as reference data. Tests that need "the rate in force" inject it;
# they do not read a clock.
REPO_EFFECTIVE_FROM = "2026-09-25"
REPO_ANNUAL = Decimal("0.0725")

# Regulation 40(4): an alternative interest method may not differ by more
# than 0.1% over a year from the prescribed daily calculation.
INTEREST_ANNUAL_TOLERANCE = Decimal("0.001")

# Regulation 40(2): non-short-term divisor is 365 or the actual days in
# the year. Short-term divisor is 30 or the actual days in the month.
# The agreement must pick one. These are not interchangeable: a 30-day
# divisor across a real year differs from actual days by more than 0.1%.
DAY_COUNT_ACTUAL_MONTH = "short_term_actual_days"
DAY_COUNT_30 = "short_term_30_day"
DAY_COUNT_365 = "annual_365"
DAY_COUNT_ACTUAL_YEAR = "annual_actual"
