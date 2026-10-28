# LMS Locked Decisions

Single source of truth for all decisions that have been researched and locked.
All future agents, chats and developers must follow these rules.
Do not re-open a locked decision without an explicit change request.

Last updated: 2026-10-28

## Standing instruction for all agents

Before proposing or implementing any calculation, ledger, servicing or configuration behaviour:
1. Read this document and follow all locked decisions.
2. If you find a gap, conflict, or uncertainty between this document and the Act, regulations, case law, or another design, raise it explicitly.
3. Do not invent a default or silently choose a reading. Flag the point so the locked decisions can be updated and all agents can see the change.

## 1. Value date and day boundary

- System recognition date is the value date for all allocation and reversals.
- Start of the day is treated as 00:00.
- A loan, settlement or deposit concluded at any time on a calendar day is treated as having occurred at 00:00 on that day.
- Reversals use the same value date the system originally recognised.
- A payment received on a flag date is treated as 00:00 on that day and is visible to the morning default check.
- When two events are both recognised at 00:00 on the same calendar day, process them in the order they were recognised by the system (stable sort by receipt sequence).
- On any calendar day, capitalisation of accrued interest and fees and allocation of payments recognised that day are treated as simultaneous at 00:00. The order is: accrue and capitalise the day's due amounts first, then allocate payments recognised that day.

## 2. Initiation fee treatment

- If capitalised → part of the principal debt.
- If not capitalised → treated as a due fee/charge under section 126.
- Same logic applies to related fee points.
- A capitalised initiation fee that was capitalised before the default date sits inside the in-duplum ceiling.
- Day-1: only products where section 102 explicitly allows capitalisation may capitalise the initiation fee. Short-term and unsecured default to non-capitalised.

## 3. Zero rates, zero fees and campaigns

- Must be fully supported.
- A campaign that sets interest to 0 % or fees to R0 is treated as the real rate less discount = 0 %.
- Calculations must not fail when rates or fees are zero for the full term or any portion of the term.
- Campaign pricing must be stored and displayed as base rate (x %) with a campaign discount (y %) deducted.
- Discount stays in place through the leniency window.
- Discount falls away on the default flag date; the rate becomes the base rate.
- Discount does not return on a later cure.
- Penalty interest may not exceed the contractual interest rate.

## 4. Laybye linked to a loan (parent/child)

- Parent/child relationship required. Contracts must treat the pair as one loan (not as security that would make the loan secured).
- Payments can be allocated across both the loan and the linked Laybye.
- Interest is calculated on the net balance (loan principal minus Laybye hold). The hold reduces only the interest base; principal remains gross for in-duplum and settlement.
- Only one monthly service fee (levied on the parent).
- Client can consolidate or settle when Laybye ≥ settlement balance.
- Credit life pays the loan first; Laybye covers any shortfall; surplus goes to the estate if treated as a cash deposit. If structured as insurance, treatment follows whether a beneficiary was named.
- Funeral benefit is paid to the named beneficiary and leaves the loan and Laybye as they are.
- Death may not apply the Laybye without a section 124 authority signed in life; otherwise the Laybye stays with the estate.
- Structured as a deposit-insurance style arrangement (client pays for a period, then loan is disbursed). Not deposit-taking under the Banks Act for Day-1 purposes.

## 5. Day count and accrual

- Both actual/actual and standard 30/360 must be available. Credit provider chooses.
- Recommendation for new products: default to actual/actual; keep 30/360 as a selectable option.
- Accrual frequency is daily.
- A 360-day year is not required for Day-1.
- Interest and fee accrual must use the same day-count and base method that was used to calculate the contractual instalment. Do not use a different method for accrual than was used for the instalment quote.

## 6. Default definition (aligned for in-duplum and collections)

- Single definition used for both in-duplum and collections/reporting.
- Leniency period is configurable per customer and counts calendar days (including weekends and public holidays).
- Unset leniency_days or full_payment_threshold_percent fails closed. Do not hard-code example values as defaults.
- Default is only automatically flagged on the contractual payment date + leniency days if the amount received for that due date is below the threshold.
- The instalment used for the threshold test is the original principal slice plus levied charges that share that due date (including monthly service fee, non-capitalised initiation fee, and credit life). Unbilled interest is excluded until it is debited.
- Credit life instalment must be included in the loan instalment for affordability calculations under the Act.
- Prefer keeping the contractual instalment the same during the loan term.
- Interest continues to be calculated daily on the outstanding balance. Leniency does not pause or reduce interest.
- A payment received on the flag date is treated as 00:00 on that day and is seen by the morning check.

## 7. In-duplum base and episodes

- Ceiling = unpaid principal (including any pre-default capitalised initiation fee) as at the date of first default in that episode.
- Post-default accruals count as charges even if displayed as capitalised on statements.
- Charges that cause the default do not count toward the cap; only charges that accrue during the default episode.
- A payment during the default reduces what is owed but does not reset the counter for that episode.
- A cure (account brought out of default) closes the episode.
- A new default starts a fresh episode with a new ceiling based on the unpaid principal at the start of the new default.
- Three section 103(5) edges not decided by Nedbank remain unnamed and unsigned; the clip stays off until counsel lists and confirms them. No implementation assumption is made.
- This is not an absolute single-lifetime ceiling; the law provides for the rule to halt and start anew on a subsequent default.
- Aligned with section 103(5) and Nedbank v NCR [2011] ZASCA 35, subject to the fresh-episode rule above.

## 8. Payment allocation and capitalisation

- Section 126 order: due or unpaid interest, then due or unpaid fees or charges, then principal.
- Only due or unpaid amounts are allocated.
- When multiple fee buckets are all already due, order is: collection costs, default administration, credit insurance, service fee, initiation fee (earliest due date first within each bucket).
- On any calendar day, accrued interest and fees that become due that day are capitalised at 00:00 before payments recognised that day are allocated.
- Capitalisation and payment allocation need not occur on the same calendar day. Capitalisation may be month-end; payment may be on the client's payday. Each is processed on its own recognition date.
- Fees and interest charged may never exceed NCA limits.
- If the client pays the contractual instalment exactly as per the contract, the loan will either be repaid earlier or a small residual may be written off after the last instalment (write-off not required if the account is already in default).
- If the client does not pay exactly the contractual instalment, the difference becomes part of arrears. Normal arrears, in-duplum and collections rules then apply. The client either continues paying until the loan is fully repaid, or the outstanding amount is written off.

## 9. Service-fee pro-rata and VAT

- Pro-rata only in the opening month (disbursement to first payment due).
- Opening-month fraction = inclusive calendar days from the disbursement date to the day before the first due date, divided by the actual days in the disbursement month.
- Full monthly fee thereafter, including the settlement month, subject to the R60 cap.
- Rand maxima (R60, R165, R1 050) are excluding VAT by default (NCR January 2019 note). Provider may elect inclusive if required.
- Consistent with regulation 44(4) and the Micro Finance South Africa judgment.

## 10. Interest on deferred initiation fee

- Provider choice. Default = no interest on deferred initiation fee.
- Alternative = interest permitted (supported by Micro Finance South Africa v NCR [2020] ZAGPPHC 463).
- Choice stored per organisation or per product.

## 11. Rate after repo rate falls

- Provider choice:
  - Option A: continue at the contract rate.
  - Option B: accrue at the lower of contract rate and current statutory maximum, and issue the section 104 notice.
- Choice stored per organisation or per product.
- No platform default; fails closed until the provider chooses.

## 12. Statements

- One statement per client per credit-provider organisation, showing all of that client's loans with that organisation.
- Each loan retains its own opening and closing balance so section 109 still holds.

## 13. Decision engine, instalments and additional fees

- Initially the platform’s own engine can be forced; long-term the LMS must accept loans from external decision engines.
- Quote date and disbursement date may differ. The contractual instalment accepted by the client is binding.
- Two options must be supported when disbursement occurs later than the quote date:
  - (a) adjust the instalment based on actual disbursement date and remaining term, or
  - (b) keep the original instalment and either settle early or write off a small residual at contractual end
    (write-off not required if the account is already in default).
- After a partial prepayment the provider chooses whether to shorten the term or drop the instalment.
- Prefer keeping the contractual instalment the same during the loan term.
- Additional fees outside interest, initiation, monthly service fee and credit life (for example certain collection costs) should be added as a further monthly fee (fixed or variable), not capitalised into the amortisation schedule.
- A loan restructuring capability exists so that other costs can be added during the term by creating a new instalment, pricing and term when required.
- “Subsequent” short-term loan is counted per credit-provider organisation and per calendar year.
- Interest and fee accrual must use the same method that was used to calculate the contractual instalment.

## 14. Payment frequencies

- Must support weekly, fortnightly, monthly, quarterly, bi-annual and annual.

## 15. Enigma boundary

- Enigma owns person identity, organisations, memberships, product enrolment, roles and mandates.
- LMS stores only opaque person_id and organisation_id.
- LMS does not re-implement person or organisation identity.
- Fail closed on Enigma timeout, ambiguous status, or a clear suspended enrolment.

## 16. Identity freeze on agreement

- Freeze name + ID number + service address at booking.
- Subsequent changes in Enigma do not rewrite the concluded agreement.

## 17. Rounding and disclosure

- Round half-up to cents on billing.
- The same rounding rule must be applied everywhere rounding is required.
- Proviso: rounding must not create a compliance issue (example: an instalment rounded up above the affordability figure previously aligned with the client).
- Annual-equivalent rate for disclosure = periodic rate × number of periods per year (simple nominal, not effective). Disclose both the periodic rate and the nominal annual rate.

## 18. Default administration and collection-cost tariffs

- Fail closed until a tariff row exists.
- Prefer adding allowable extra costs as an additional monthly fee rather than capitalising them into the schedule.

## 19. Storage of elections

- The following elections are stored at organisation level with an optional product override (same pattern as leniency):
  - VAT-inclusive election for rand maxima
  - Late-disbursement instalment choice
  - Partial-prepayment choice (shorten term or drop instalment)
  - Interest on deferred initiation fee
  - Repo-rate fall choice
- Unset values fail closed.
