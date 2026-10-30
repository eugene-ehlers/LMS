# Settlement re-advance

`POST /v1/settlement-readvances`

Header `Idempotency-Key` is required. Amounts are integer cents. `recognised_at` must carry a timezone. The recognition date is 00:00 Africa/Johannesburg on that calendar day, including a UTC timestamp that is already the next day in Johannesburg.

The command settles one disbursed agreement and books the loan the decision engine has already priced. It does not reprice.

## Request

`organisation_id`, `agreement_id`, `actor_id`, `recognised_at`, `receipt_cents`, `interest_cap_present`, and `settings` are required. `vat_rate` is a decimal string and is required when a service fee is levied. `product_elections` is optional. A product value that is present wins over the organisation value. The campaign fall-away choice and its trigger move together: when the product sets the choice, the trigger is the product's trigger.

`settings` and, where supplied, `product_elections` must name every election this path freezes. An unset value fails closed. An omitted residual write-off threshold is left null. `resolve_residual_threshold_cents` then fills the platform default of R100 (10 000 cents). Zero is a stored choice. An unset in-duplum trigger fails closed at booking. `interest_cap_present` must be a boolean. `false` fails when a posting needs a cap row.

`new_loan` is required:

- `product_code`: `micro_short_term` or `unsecured_personal`
- `application_number`: a new application. Reusing an application fails. The LMS issues the next loan number from the shared 12-digit series.
- `rate`: a decimal string in the unit the ledger already stores. A short-term rate is a monthly fraction. An unsecured rate is the annual margin fraction. No conversion is applied. A float is rejected.
- `short_term_rate_flag`: `five_percent` or `three_percent` on a short-term loan, and absent on an unsecured loan. The rate may not exceed 5% or 3% for that flag. The LMS does not count other short-term loans and does not flip the flag.
- `term_count`, `frequency`, `instalment_cents`, `cash_advanced_cents`, and `schedule`. The schedule is principal slices. The line count must equal `term_count`. The slices must sum to the cash advanced. The contractual instalment is stored as supplied.
- `initiation_fee_cents` defaults to 0 and is not capitalised.
- `repos`: required for `unsecured_personal`. Each row is `effective_from` and a decimal `annual_rate`. No repo rate is assumed.

The new loan is the same organisation and the same person as the settled agreement. Name, identity number, and service address are frozen from Enigma at booking. The staff check uses the mandate string `lms.settlement.readvance`. That string follows the Decision 19 naming style. It is not a locked role name. Enigma still decides access. The consumer check uses `agreement.book`.

An NCR registration number must already be stored for the organisation. A missing row or a blank number fails closed for both Day-1 products. Enigma is not asked for the number.

## What the command does

1. Reject a missing actor, agreement, election, NCR number, or new loan before any ledger post. A missing `new_loan` names early settlement and restructure. Neither is performed.
2. Capitalise through the recognition date, and not past the contractual end. Interest is accrued on each day in that window and billed on the recognition date. The opening month keeps the locked service-fee fraction. Every later month through the settlement month is a full monthly fee, including a settlement month whose instalment date is still later. A month already levied is left as it is.
3. Read the balance. A short receipt is not allocated. A receipt above the balance with no Laybye child is not allocated. The failure includes `required_cents`.
4. Allocate an exact receipt in section 126 order. `settle` pays the remaining principal. No early-termination charge is added. Excess above the balance is credited to the Laybye when a child exists.
5. Mark the agreement settled only when the balance is 0 cents. Otherwise the new loan is not booked.
6. Store the supplied rate, term, instalment, and short-term flag. Freeze the elections and the identity. Link the new loan to the settled agreement, loan id, and loan number when that number was already issued.
7. Append one `SETTLEMENT_READVANCE` operational audit row for the first attempt, with the actor, the recognition timestamp, and the outcome. The receipt amount stays on the payment audit. A replay of the same key and body returns the stored response and does not write a second row.

## Response

Success is HTTP 200. `outcome` is `success`. `confirmation` names the new loan number and the settled loan number, or the settled agreement id when that loan was never numbered. `balance_cents` is 0.

Failure is HTTP 422, or 404 when the agreement is missing, or 409 when the idempotency key was already used for a different body. `outcome` is `failure`. `code` and `message` say which check failed. A request with no `organisation_id` is returned as `organisation-unset` and is not audited, because the audit log has no organisation to attach it to.

If the receipt is posted and booking the new loan then fails, the settled agreement stays settled. The message says so. There is no automatic reversal.
