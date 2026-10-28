# Collection-process state removed from the LMS

The LMS produces the collection file and receives receipts and write-off instructions. Promise-to-pay and contactability stay in the collections system. `docs/COLLECTIONS_SPLIT.md` on `main` (`f058cdc`) is the standing split. Locked decisions are not changed by this note.

## Promise-to-pay

There was no LMS table and no migration for a promise-to-pay amount, date, or adherence.

`ProvisionFacts` had `promise_to_pay`. `Collections.record_provision` and `Collections.open_prescription_review` required that string before a caller-supplied formula would run, and failed closed with `provision-factor-unset` or `prescription-factor-unset` when it was missing. Those parameters and that field are removed. A formula now receives `arrears_cents`, `recency_days`, `months_on_book`, and `as_of`.

A manual provision still stores `provision_cents`. A write-off still enters through `Collections.write_off`. The LMS does not accept a promise-to-pay in either path.

`docs/collections/implementation-note.md` and `docs/collections/layer1-draft.md` still print the withdrawn parameters. Those descriptions are historical.

## Contactability

There was no LMS table for contact attempts, outcomes, or a contactability score.

`ProvisionFacts.contactability` and the matching arguments on `record_provision` and `open_prescription_review` are removed. The formula is not given a score.

The credit provider's telephone on `ProviderCompliance` remains. That is the provider number used on statements. It is not a consumer contact attempt. Decision 27 already says contact details for collection purposes are not stored in the LMS. Registered-user contact details stay in Enigma.

## Collection file

Unchanged. `raise_collections` returns two instructions when collections are automated: `loan_instalment` and `credit_life_premium`. `PaymentRail.generate_debit_order_file` writes those amounts and no other purpose. `user_reference` rejects `promise_to_pay` and `ad_hoc`.

The loan line is still the amount outstanding on that due date. The stored contractual instalment is the existing open point P2. This removal does not add an ad-hoc amount or a promise-to-pay amount to close that point.

## Receipt intake

Unchanged. `PaymentRail.accept_receipts` capitalises due amounts on the Johannesburg recognition date, then allocates through `Servicing.accept_payment` in recognition sequence. A receipt from the debit-order rail dummy uses that path. `docs/layer3/receipt-intake.md` and `docs/layer3/capitalise-then-allocate.md` describe it.

## What still runs inside collections

`record_provision` can still apply a caller-supplied formula and store the resulting cents. `open_prescription_review` can still apply a caller-supplied formula. `_facts` still derives recency and months on book from ledger dates. Decision 8 says provisioning formulas run outside the LMS, and that recency, months on book, promise-to-pay adherence, and contactability are not calculated inside the LMS. The two collection-process inputs are gone. The in-LMS formula and the two ledger-derived figures are the gap recorded in `docs/OPEN_ISSUES.md`. This note does not move the formula outside and does not invent a reporting feed.
