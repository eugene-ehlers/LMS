"""Canned values for the external-system dummies.

These numbers are fixtures for tests. They are not statutory rates, NCA caps,
or decision-engine rules.
"""

from __future__ import annotations

from datetime import date

# 240 basis points = 2.40% per payment period. One basis point = 0.01%.
FIXED_PERIODIC_RATE_BPS = 240
FIXED_INSTALMENT_CENTS = 25_000
FIXED_CREDIT_LIFE_PREMIUM_CENTS = 199

FIXED_FAILURE_REASON = "fixed_failure"

FIXED_UNMATCHED_LOAN_NUMBER = "LN-FIXED-UNMATCHED"
FIXED_UNMATCHED_ID_NUMBER = "0000000000000"
FIXED_UNMATCHED_AMOUNT_CENTS = 12_345
FIXED_UNMATCHED_RECOGNITION_DATE = date(2026, 1, 15)

APPLICATION_NUMBER_PREFIX = "APP-"
RECEIPT_SEQUENCE_WIDTH = 8
