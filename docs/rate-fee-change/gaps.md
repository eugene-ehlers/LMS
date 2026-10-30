# Gaps

These points are not settled by the locked decisions, or they conflict with a locked sentence or with the Act. The implementation does not treat them as new locked rules. Where a command would have to choose, it fails closed, except for the readings named below. Those readings are what the brief asked the code to do, and they are recorded in `docs/OPEN_ISSUES.md`.

## The locked-decisions file on this branch is not the section 28 text

`docs/LOCKED_DECISIONS.md` on this branch ends at section 21. On `main` the file is a placeholder pointing at `/tmp/locked_updated.md`, and that file is not on disk. The restored text through section 28 is commit `325acc6`. This change follows that text and the brief. It does not edit the locked-decisions file. See H1.

## Section 104(2) for a non-campaign change

Decision 22: a non-campaign rate or fee change also requires a written notice of at least five business days before it takes effect (section 104(2)). H2 is closed.

The count uses section 2(5): exclude the notice date, include the effective date, and skip Saturdays, Sundays, and statutory public holidays. Presidential one-off holidays are `extra_holidays` on the service. The HTTP route does not accept them. See H9.

## A temporary reduction is a concession

Decision 22: a temporary reduction is stored as a concession or discount that goes to zero when the period ends. The original contractual rate and fees remain effective and are not changed. Resuming the original rate does not require a second notice. An interest-rate change does not automatically reduce the contractual instalment. H3 is closed.

Ending does not extend the reduction. Moving the end date later is refused (`end-extends`) because that would need its own notice and this command does not carry one.

## Decision 11 and section 104(3) are not this path

Decision 11 option B says to accrue at the lower of the contract rate and the current statutory maximum and to issue the section 104 notice. It does not say subsection (2) or (3). Section 104(3) requires notice no later than 30 business days after a variable-rate change, not five business days before it.

This module does not apply a repo-rate fall and does not issue a section 104(3) notice. An unsecured rate read still needs the repo series the ledger already requires. The HTTP route does not send that series, so an unsecured apply fails closed until the service is called with `repos`. See H4.

## End date

The brief does not say whether the end date is inside the new values. This code includes it: the new values apply on `end_date`, and the contractual rate and fees resume on the next recognition date. See H5.

The same window is used for a fee payment frequency or payment time. The brief names the resume for rate and fees. It does not say the original frequency or payment time resumes. This code stops the whole overlay after the end date, because the change is one record. See H6.

## Frequency and time

Section 104(2)(c) is a change in the frequency or time for payment of a credit fee or charge. The brief says "frequency or time of payment" and also says the contractual term and contractual instalment amount stay as they are.

`fee_payment_time` is a Johannesburg calendar date. A clock time is refused because recognition is 00:00. `fee_payment_frequency` must be one of the locked frequencies and must name that first due date. The loan's `payment_frequency`, contractual end, and instalment lines are not written. A body that tries to set them is `restructure`.

Decision 14 does not say how a due date moves when the day does not exist in the target month. The existing ledger refusal (`due-date-unspecified`) is left as it is.

A statement levy does not invent a new schedule. If the statement's due date is not on the overlay, the levy fails closed (`payment-time`). See H10.

## Origination discount

Decision 3 is the discount stored at booking. Its fall-away flag is already inside the contractual rate the ledger returns. This overlay is not passed through that flag again. It ends on the end date only. See H12.

## Fees the ledger does not store

Contractual fee cents are supplied at apply and stored for disclosure. A product selector is refused. See H8.

A lower initiation fee does not restate a capitalised initiation already included in principal. The principal and the instalment lines stay as they were.

## Posted rows

An apply or an end that would cover a recognition date already accrued or levied fails closed. The ledger is not rewritten. See H11.

## Audit of a naive timestamp

Decision 1 needs a zone so the Johannesburg day is known. The audit log rejects a naive timestamp. That failure is returned and is not sealed. See H13.

## Role

Decision 19's examples include `lms.campaign.write`. They do not name this action. The action used here is `lms.rate_fee_change.write`. See H7.
