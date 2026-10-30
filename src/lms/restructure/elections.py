"""Decision 19 elections frozen onto a restructured agreement.

Unset values fail closed. The residual threshold is not filled. Decision 8
names R100 and Decision 19 says an unset election fails closed. This module
does not choose between those sentences (open issue C4).
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.restructure.money import require_cents


VAT = frozenset({"exclusive", "inclusive"})
LATE = frozenset({"adjust_instalment", "keep_instalment"})
PREPAY = frozenset({"shorten_term", "drop_instalment"})
INITIATION = frozenset({"none", "permitted"})
REPO = frozenset({"contract_rate", "lower_of_contract_and_cap"})
TRIGGERS = frozenset({"contractual_breach", "collections_default"})
FALL_AWAY = frozenset({"falls_away_on_default", "does_not_fall_away"})

# Order is the order Decision 19 names them. A missing row reports the first gap.
REQUIRED_FIELDS = (
    "vat_on_rand_maxima",
    "late_disbursement",
    "partial_prepayment",
    "interest_on_deferred_initiation",
    "repo_rate_fall",
    "in_duplum_trigger",
    "residual_write_off_threshold_cents",
    "campaign_fall_away_choice",
)

_CHOICES = {
    "vat_on_rand_maxima": VAT,
    "late_disbursement": LATE,
    "partial_prepayment": PREPAY,
    "interest_on_deferred_initiation": INITIATION,
    "repo_rate_fall": REPO,
    "in_duplum_trigger": TRIGGERS,
    "campaign_fall_away_choice": FALL_AWAY,
}


class ElectionError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class FrozenElections:
    vat_on_rand_maxima: str
    late_disbursement: str
    partial_prepayment: str
    interest_on_deferred_initiation: str
    repo_rate_fall: str
    in_duplum_trigger: str
    residual_write_off_threshold_cents: int
    campaign_fall_away_choice: str
    campaign_fall_away_trigger: str | None


def freeze_elections(raw: object) -> FrozenElections:
    """Copy a resolved election row. A missing or unknown value fails closed."""

    if not isinstance(raw, dict):
        raise ElectionError("missing election: vat_on_rand_maxima")
    values: dict[str, object] = {}
    for field in REQUIRED_FIELDS:
        if field not in raw or raw[field] is None:
            raise ElectionError(f"missing election: {field}")
        values[field] = raw[field]
    for field, allowed in _CHOICES.items():
        value = values[field]
        if not isinstance(value, str) or value not in allowed:
            choices = " or ".join(sorted(allowed))
            raise ElectionError(f"invalid election: {field}. Expected {choices}")
    try:
        residual = require_cents(
            values["residual_write_off_threshold_cents"],
            "residual_write_off_threshold_cents",
        )
    except ValueError as exc:
        raise ElectionError(str(exc)) from exc
    choice = values["campaign_fall_away_choice"]
    if "campaign_fall_away_trigger" not in raw or raw["campaign_fall_away_trigger"] is None:
        trigger: str | None = None
    else:
        trigger = raw["campaign_fall_away_trigger"]
    if choice == "falls_away_on_default":
        if trigger is None:
            raise ElectionError("missing election: campaign_fall_away_trigger")
        if not isinstance(trigger, str) or trigger not in TRIGGERS:
            raise ElectionError(
                "invalid election: campaign_fall_away_trigger. "
                "Expected collections_default or contractual_breach"
            )
    elif trigger is not None:
        raise ElectionError(
            "invalid election: campaign_fall_away_trigger. "
            "A choice of does_not_fall_away stores no trigger"
        )
    return FrozenElections(
        vat_on_rand_maxima=str(values["vat_on_rand_maxima"]),
        late_disbursement=str(values["late_disbursement"]),
        partial_prepayment=str(values["partial_prepayment"]),
        interest_on_deferred_initiation=str(values["interest_on_deferred_initiation"]),
        repo_rate_fall=str(values["repo_rate_fall"]),
        in_duplum_trigger=str(values["in_duplum_trigger"]),
        residual_write_off_threshold_cents=residual,
        campaign_fall_away_choice=str(choice),
        campaign_fall_away_trigger=trigger,
    )
