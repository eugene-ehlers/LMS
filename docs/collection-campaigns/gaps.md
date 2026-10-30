# Gaps

These points are not settled by section 28 or by the other locked decisions. The implementation does not treat them as locked rules. Where a command would have to choose, it fails closed.

On this branch, sections 1 to 27 are the Layer 2 locked file. Section 28 is the collection-campaign text, appended because the merge otherwise dropped it. The collection-campaign branch's section 21 was not used: it omits the compulsory NCR number and the all-zeros test number that section 21 on this branch already locks.

## Decision 3 is a different campaign

On this branch, Decision 3 says the origination discount falls away on the default flag date and does not return. Section 28 says a collection campaign applies for the campaign period or the rest of the term, and that the original rate resumes when a dated campaign ends. It does not say the collection reduction falls away on default.

The collection reduction is not passed through the origination fall-away flag. If these two campaigns are meant to be one object, that is a conflict and this code does not resolve it.

## Open-ended, once an end date is set

Section 28 says the original rate and fees resume when the campaign ends, unless the campaign was open-ended. It also says a rate or fee change is for the campaign period or the rest of the term.

This code reads a null `end_date` as open-ended. Staff end that campaign by storing an end date. It is then dated, so a `campaign_period` reduction resumes on the next recognition date. `rest_of_term` continues through the contractual end either way. A payment holiday is the campaign period only.

The past tense "was open-ended" could mean a campaign that began with no end date never resumes, even after staff later set an end date. That reading is not used.

## `campaign_rate` refuses a reduction above the contractual rate

`lms_config.locked.campaign_rate` raises when the reduction exceeds the base. `lms.calc.interest.campaign_terms` floors the net at 0%. The ledger uses `campaign_rate`. A collection reduction above that day's contractual rate fails the apply, the edit, or the accrual (`rate-above-contract`). The net is not floored. Open issue C5 describes the same split for origination campaigns and is left to that work.

A fee reduction at or above the fee is floored at R0 by `apply_ex_vat_discount`. The two calculators do not treat an excessive reduction the same way. This module does not add a third rule.

Zeroing a rate means a reduction equal to that day's contractual rate. A stored reduction of zero leaves the rate or fee unchanged. It is not a way to zero it.

## End date is inclusive

Section 28 does not say whether the end date is the last day inside the campaign. This code treats it as included: a campaign-period override applies on `end_date` and the contractual rate resumes on the next recognition date. That inclusive reading is not a locked rule.

Two campaigns whose occupied dates touch overlap. A rest-of-term reduction occupies dates through the contractual end, so it overlaps a later campaign on that loan even when the campaign windows do not meet. No precedence is locked, so the second apply or the edit is refused.

## A skipped instalment has no new due date

The contractual line stays where it is. The skip tells the morning check and collections not to treat that date as a new breach. It does not move the date, extend the term, or change the instalment amount.

A skip is recorded only for a due date on or after the apply or edit recognition date and inside the campaign window. A due date that has already passed is not newly skipped and a skip already stored for a past date is not removed. Section 28 does not say how an edit applies to a date that has passed. A holiday is not extended to the rest of the term.

Section 126 still sees a contractual slice as due once its date has arrived, so a voluntary receipt can reduce it. Section 28 does not say whether allocation should ignore a skipped slice. Allocation is unchanged.

While that unpaid contractual line is the only remaining miss, an open in-duplum episode is not closed. The holiday itself does not call `close_in_duplum_episode`. Whether paying the other arrears must also clear the skipped line before a cure is not locked. This is the conservative reading of "a payment holiday does not reset in-duplum".

## Posted accruals are not restated

An edit or an end changes the rate used for a later accrual. An accrual already posted stays until a separate reversal. Section 28 does not say to restate history. The ledger is append-only.

The collection reduction is applied to that day's contractual periodic rate, not frozen as a net rate at apply time. The originals stored on the application are the disclosure copy.

## Loan numbers and product

Section 28 says an explicit list. Layer 0 identifies a loan by `loan_id`. There is no separate human loan number on the account. The list is those ids.

The ledger stores a classification, not a product code. Bulk apply by product uses the code supplied at registration. The selector is inside one organisation. A product across organisations is not supported.

Combining organisation, product, and a loan list in one request is refused.

## Notice calendar

Five business days uses `lms_config.calendar.add_business_days` and the statutory public holidays from that module. Presidential one-off holidays are data (`ref_public_holiday`), not part of that function. A caller can pass `extra_holidays` on the service. The HTTP route does not. Whether ending a campaign needs its own section 104(2) notice is not stated. Ending does not require a second notice date.

## Role name

Decision 19 requires a descriptive role and gives `lms.campaign.write` as an example for campaign edits. Section 28 does not name the collection-campaign action. The action used here is `lms.collection_campaign.write`. That name is not written back into the locked decisions.

## Unsecured origination discount

The ledger still refuses an unsecured loan whose origination discount is not zero (`unsecured-campaign-base-unset`). A collection reduction is not priced on top of that pair. The existing ledger error stands.
