# Conflicts this layer does not close

`docs/LOCKED_DECISIONS.md` is the source of truth. The open points at the end of that file are undecided. This note records where the code already on the Layer 0 and Layer 1 tree disagrees with the current lock. This layer does not change those functions and does not pick a new rule.

## Discount above the base

Decision 3 allows a discount higher than the base and floors the net at 0 %. `lms_config.locked.campaign_rate` raises `CalculationInputError` when the discount is greater than the base. `lms.staff.rates.net_rate` calls `campaign_rate` for every other pair. For a discount above the base it calls `campaign_rate`, catches that refusal, and stores `0`. It does not accrue and it does not apply a statutory cap.

`lms.calc.interest.campaign_terms` already floors an agreement's effective rate at 0 %. Using it here would also run the short-term 5 % / 3 % cap inside agreement construction. Decision 13 puts that distinction in the decision engine. This layer does not call `campaign_terms` to price a campaign.

`lms.election_snapshot.discount_rate` still has `discount_rate <= base_rate`. The dated campaign table does not.

## Residual threshold

Closed. Decision 19 fills R100 (10 000 cents) when both the organisation and the product are null. A stored value, including zero, is kept. Staff resolve uses that fill. Booking fails closed when the in-duplum trigger is unset.

## Fall-away at accrual

`campaign_rate` returns the base once the caller passes `discount_fallen_away` or `in_default`. It does not read `falls_away_on_default` or `does_not_fall_away`. The ledger still decides when to pass that flag. This layer stores the choice on the campaign and on the election. It does not change accrual, so a stored `does_not_fall_away` is not yet read by the posting path.

Decision 19 stores the same choice in both places and does not say which one accrual should read when they differ. The intake copies the campaign's choice. It does not compare it with the election.

## Supplied rate and campaign net

The decision intake stores `supplied_rate` and `credit_life_premium_cents` unchanged. When one campaign covers the recognition date, the intake also copies that campaign's base, discount, and net. It does not replace the supplied rate with the net. The lock does not say which of those is the contractual rate.

## Statements

One statement per client per credit-provider organisation stays in Layer 1. Nothing under `src/lms/staff` imports `lms.statements`.
