"""Current value of an LMS feature flag.

``cfg_feature_flag`` in the schema is effective-dated. This store keeps the
current value only. A missing row is ``None``. Nothing here defaults a flag to on.
"""

from __future__ import annotations

from lms.payments.errors import PaymentRailError

# Seeded catalogue. db/seed/001_reference.sql. This layer reads one of them.
CATALOGUE = (
    "origination_enabled",
    "debit_orders_enabled",
    "statements_enabled",
    "bnpl_enabled",
    "layby_security_enabled",
)

DEBIT_ORDERS_ENABLED = "debit_orders_enabled"


class FeatureFlags:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], bool] = {}

    def put(self, organisation_id: str, flag_key: str, enabled: bool) -> None:
        if flag_key not in CATALOGUE:
            raise PaymentRailError(
                "flag-unknown",
                f"{flag_key} is not in the feature-flag catalogue.",
            )
        if not isinstance(enabled, bool):
            raise PaymentRailError("election-unset", "A feature flag is true or false. It is not assumed.")
        self._rows[(organisation_id, flag_key)] = enabled

    def get(self, organisation_id: str, flag_key: str) -> bool | None:
        if flag_key not in CATALOGUE:
            raise PaymentRailError("flag-unknown", f"{flag_key} is not in the feature-flag catalogue.")
        return self._rows.get((organisation_id, flag_key))
