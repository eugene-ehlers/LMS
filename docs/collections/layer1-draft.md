# Collections and arrears

Layer 1. This note describes the behaviour that is implemented. Each behaviour cites `docs/LOCKED_DECISIONS.md`. The earlier single-definition draft does not match the current lock and is not the rule this code follows.

Statements, Laybye claim logic, and regulatory extracts are out of scope. In-duplum clipping stays off (decision 7).

## Two defaults

Decision 6 keeps two concepts.

A contractual breach is recorded when a schedule due date has passed and the receipts whose value date is that due date are below the full-payment threshold. Decision 1 makes the whole of day X 00:00 Johannesburg time, so the day has not passed until the next calendar day. A receipt on day X is not a breach. A later receipt does not clear the breach. The only removal is `correct_system_error`, which decision 6 reserves for a system error corrected as if the breach never occurred.

A collections default is the account outside its limit. The limit used here is the decision 6 threshold test: `is_in_default` on each schedule due date, with leniency counted in calendar days and with every receipt attributed to that due date up to the check date. Paying the arrears makes `is_in_default` false, so the collections default is cured.

The threshold instalment is the original principal slice plus levied charges that share that due date. Unbilled interest stays out until it is debited. Both tests call `is_full_payment` and `_threshold_instalment`. Unset `leniency_days` or `full_payment_threshold_percent` still fail closed in configuration. This layer does not hard-code 4, 5, or 95.

The default flag is for in-duplum, reporting, and collections. Decision 6 says it does not stop fees or interest, and payments continue normally. `observe` does not accrue and does not allocate. `accrue_day` and `Servicing.accept_payment` still run. Reporting reads `contractual_breaches`, `collections_default`, and the open episode. Servicing status `in_arrears` remains the Layer 0 marker for an open episode.

## In-duplum trigger

Decision 6 and decision 19 store the trigger at organisation level with an optional product override. The two values are `contractual_breach` and `collections_default`. An unset trigger fails closed. There is no platform default.

`contractual_breach` opens one episode when the first breach is recorded and no episode is open. Decision 7 fixes the ceiling at the unpaid principal then, including pre-default capitalised initiation, through `duplum_base_cents`. A later payment does not close the episode and does not reset the counter. A later breach does not start a second episode.

`collections_default` opens an episode when the account is in collections default and none is open. A cure closes that episode. The next collections default opens a new episode with a new ceiling. Decision 7 says this is not a lifetime ceiling when this trigger is selected.

Decision 3 keeps the campaign discount through the leniency window and removes it on the default flag date. It does not return on cure. A contractual-breach episode can open inside the window. The discount falls away only once the check date is on or after that breach date plus leniency. A collections-default episode opens on or after the flag date, so the discount falls away as the episode opens. Closing an episode does not restore it. A system-error correction does not restore it either.

The clip stays off. This layer does not call `clip_in_duplum`.

## Residual write-off

Decision 8: if the contractual instalment is paid exactly, a small residual may be written off after the last instalment. The threshold is client-configurable. Decision 19 sets the platform default at R100 (10 000 cents). It is not automatic.

`propose_residual_write_off` is the command. It posts only when all of these hold:

- The value date is after the last schedule date (decision 8).
- `contractual_end` equals that last schedule date (decision 8 and decision 13). If they differ, the command fails closed.
- No in-duplum episode is open. This gate is the implementation request. Decision 8 does not state it. See the gaps.
- Every current schedule line was received in exact cents. Decision 8 reserves the small residual for an exact contractual instalment. A shortfall is arrears and uses the mandated write-off.
- The outstanding position is greater than zero and less than or equal to the threshold. Equal to R100 is inside the platform default. A stored zero is a client choice. A negative amount is refused.

Decision 19 fills an unset residual with R100. Other unset elections fail closed. `resolve_residual_threshold_cents` applies 10 000 cents when both the organisation and the product are null. A product value, including zero, overrides the organisation. The SQL column has no default, so a null row is not silently 10 000 in the database. The resolver applies it.

The post is the write-off journal: debit `write_off_expense`, credit each outstanding bucket, clear the remaining slices and charges.

## Provision and larger write-off

Decision 8: provision and write-off are per client, manual or formula-based. The factors named there include arrears, recency, months on book, promise-to-pay adherence, and contactability. There is no platform score.

`record_provision` stores a manual non-negative amount, or calls a formula the client supplies. Promise-to-pay and contactability are not on the ledger. A formula without them fails closed. An unset mode fails closed.

`write_off` is the larger write-off. The amount must be the full outstanding position. Decision 8 does not order a partial write-off across buckets, so any other amount fails closed before authority is asked.

Decision 15: Enigma is identity and access. A timeout, an ambiguous status, or a suspended enrolment fails closed and posts nothing. The access check runs before the ceiling. A denied mandate posts nothing. The operational ceiling is the platform ceiling, or the lower of the platform and company ceilings when the company ceiling is set. An amount equal to the limit is inside. A missing platform ceiling fails closed. The journal is the same `write_off` transaction as the residual path.

## Prescription

Decision 20: prescription handling is per client, manual or formula-based. Different clients may use different formulas. No platform default is imposed. An unset mode fails closed. A formula that returns false does not open review.

When review is open, `receive` stores the receipt as `unapplied`. It does not call `Ledger.post_payment`. It does not post a refund. Opening review does not reverse a receipt that was already posted and does not close an open episode.

Section 126B of the National Credit Act prohibits selling a debt extinguished by the Prescription Act, and prohibits continued collection where the debt is extinguished and the consumer raises, or would reasonably have raised, the defence. The lock does not adopt a clock and does not adopt a refund.

## Calls this layer does not make

`Ledger.flag_default` and `Servicing.morning_check` still implement the previous single morning check and can close an episode from one due date. Collections does not call them. It calls `open_in_duplum_episode`, `close_in_duplum_episode`, and `mark_discount_fallen_away`.

`Servicing.accept_payment` is used for receipts that are not in prescription review. It allocates under decision 8 and refreshes servicing status. A direct call while the agreement status is `prescription_review` does not hold the receipt. See the gaps.

## Gaps

These are raised. This layer does not invent a locked answer for them.

1. Decision 6 does not say that leniency applies only to collections default, or that "not received on day X" means below the full-payment threshold rather than zero. This code uses the threshold for both tests and applies leniency only to collections default and to the discount fall-away date.
2. Decision 6 says "outside its limit (in arrears)". This code reads that limit as the threshold test, not as a separate arrears-balance cap. With a threshold below 100 percent, collections default can cure while a remainder still exists. Decision 8 still calls that remainder arrears.
3. Decision 3 keeps the discount through leniency. A contractual breach can be flagged inside that window. Withholding `fall_away` until the flag date is a reading of the two sentences together. It is not written as one rule.
4. Decision 7 fixes the ceiling at the unpaid principal on the date of first default. The ceiling is the principal when `open_in_duplum_episode` runs. A receipt posted after the breach date and before the first `observe` reduces that principal. The lock does not say what a late check does.
5. Decision 6 says a system error is corrected as if it never occurred, and also says a contractual-breach ceiling cannot be restarted. This code removes the breach. It closes the episode only when that breach opened it and no breach remains. It does not rebuild a ceiling for a breach that remains. It does not restore the discount, because decision 3 says the discount does not return.
6. Decision 8 does not condition the residual write-off on "no open episode". The implementation request does. The command refuses with `residual-episode-open`. Under `contractual_breach` an episode does not close on cure, so the residual path stays unavailable after that episode has opened.
7. Closed by Decision 19. An unset residual write-off threshold fills R100. Booking fails closed if the in-duplum trigger is unset.
8. The ledger election snapshot and `ProductTerms` do not store the trigger or the residual threshold. `Collections.bind` copies them. Migration `0005` and the configuration read expose the columns. There is no runtime SQL session in this layer. A second bind is refused so a later call does not rewrite the copy.
9. Decision 8 names formula factors and does not give weights. Months on book is the difference in calendar months from disbursement. That definition is not locked. Promise-to-pay and contactability have no ledger columns.
10. Decision 8 does not order a partial write-off. The journal refuses one. Slice order for a partial principal write-off is not invented.
11. Decision 15 does not name the action `lms.account.write_off` or the operational-ceiling rows. The comparison follows the Enigma port rule `enforce_amount`. The `lms.enigma` package is not on this branch. A missing platform ceiling fails closed. No rand ceiling is hard-coded.
12. Decision 20 does not define a prescription period or an exit from `prescription_review`. No clock is run. No refund method exists. Write-off during review is not specified; this code allows it.
13. `Servicing.accept_payment` does not know prescription review. `Collections.receive` is the path that holds the receipt. Once the agreement status is `prescription_review`, a direct `accept_payment` raises instead of storing an unapplied receipt, because allocation only accepts `active` and `in_arrears`.
14. `Ledger.flag_default` and `is_in_default_at_morning_check` still drop receipts after the flag date and can close an episode without reading the trigger. Servicing `morning_check` still calls them. Collections does not.
15. Two Layer 0 smoke tests already fail on `cursor/layer0-smoke-4153`: same-day capitalisation versus recognition order (decisions 1 and 8), and a rejected statement that still posts interest (decision 9). This layer does not change that behaviour.
