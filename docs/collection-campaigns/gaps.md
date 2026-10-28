# Gaps

These points are not settled by `docs/LOCKED_DECISIONS.md` or by the collection-campaign brief. The implementation does not treat them as locked rules. Where a command would have to choose, it fails closed.

## Section 28 is not in the locked decisions

This branch's locked-decisions file ends at section 21. Commits `f75d1be` and `ecffee7` on `main` name a collection-campaign lock and then replace the file with a placeholder. There is no section 28 text to follow. The code follows the task brief and the decisions that are actually in this branch. The short note at the end of `docs/LOCKED_DECISIONS.md` records that. It does not add a rule.

## Decision 3 is a different campaign

On this branch, Decision 3 says the origination discount falls away on the default flag date and does not return. The brief says a collection campaign applies during its period and the original rate resumes when that period ends. It does not say the collection reduction falls away on default.

The collection reduction is not passed through the origination fall-away flag. If these two campaigns are meant to be one object, that is a conflict and this code does not resolve it.

The later text on `main` before the placeholder (commit `401b3c1`) says every campaign has an end date. The brief allows an open-ended collection campaign. This branch's Decision 3 does not say either. Open-ended is implemented because the brief asks for it.

## `campaign_rate` refuses a reduction above the contractual rate

`lms_config.locked.campaign_rate` raises when the reduction exceeds the base. `lms.calc.interest.campaign_terms` floors the net at 0%. The ledger uses `campaign_rate`. A collection reduction above that day's contractual rate fails the apply, the edit, or the accrual (`rate-above-contract`). The net is not floored. Open issue C5 describes the same split for origination campaigns and is left to that work.

A fee reduction at or above the fee is floored at R0 by `apply_ex_vat_discount`. The two calculators do not treat an excessive reduction the same way. This module does not add a third rule.

## End date is inclusive

The brief does not say whether the end date is the last day inside the campaign. This code treats it as included: the override applies on `end_date` and the contractual rate resumes on the next recognition date. That inclusive reading is not a locked rule.

Two campaigns that touch on the same date overlap. No precedence is locked, so the second apply or the edit is refused.

## A skipped instalment has no new due date

The contractual line stays where it is. The skip tells the morning check and collections not to treat that date as a new breach. It does not move the date, extend the term, or change the instalment amount.

A skip is recorded only for a due date on or after the apply or edit recognition date. A due date that has already passed is not newly skipped and a skip already stored for a past date is not removed. The brief does not say how an edit applies to a date that has passed.

Section 126 still sees a contractual slice as due once its date has arrived, so a voluntary receipt can reduce it. The brief does not say whether allocation should ignore a skipped slice. Allocation is unchanged.

While that unpaid contractual line is the only remaining miss, an open in-duplum episode is not closed. The holiday itself does not call `close_in_duplum_episode`. Whether paying the other arrears must also clear the skipped line before a cure is not locked. This is the conservative reading of "a payment holiday does not reset in-duplum".

## Posted accruals are not restated

An edit or an end changes the rate used for a later accrual. An accrual already posted stays until a separate reversal. The brief does not say to restate history. The ledger is append-only.

The collection reduction is applied to that day's contractual periodic rate, not frozen as a net rate at apply time. The originals stored on the application are the audit copy.

## Loan numbers and product

The brief says an explicit list of loan numbers. Layer 0 identifies a loan by `loan_id`. There is no separate human loan number on the account. The list is those ids.

The ledger stores a classification, not a product code. Bulk apply by product uses the code supplied at registration. The selector is inside one organisation. A product across organisations is not supported.

Combining organisation, product, and a loan list in one request is refused.

## Notice calendar

Five business days uses `lms_config.calendar.add_business_days` and the statutory public holidays from that module. Presidential one-off holidays are data (`ref_public_holiday`), not part of that function. A caller can pass `extra_holidays` on the service. The HTTP route does not. Whether ending a campaign needs its own section 104(2) notice is not stated. Ending does not require a second notice date.

## Role name

Decision 19 requires a descriptive role and gives `lms.campaign.write` as an example for campaign edits. It does not name the collection-campaign action. The action used here is `lms.collection_campaign.write`. That name is not written back into the locked decisions.

## Unsecured origination discount

The ledger still refuses an unsecured loan whose origination discount is not zero (`unsecured-campaign-base-unset`). A collection reduction is not priced on top of that pair. The existing ledger error stands.
