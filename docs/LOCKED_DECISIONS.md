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
- Once a loan is granted, the default allocation is: all payments go to the loan first (section 126 order). Any excess then goes to the Laybye account.
- Interest is calculated on the net balance (loan principal minus Laybye hold). The hold reduces only the interest base; principal remains gross for in-duplum and settlement.
- Only one monthly service fee (levied on the parent).
- Client can consolidate or settle when Laybye ≥ settlement balance.
- Day-1 treatment is cash-deposit until the insurer develops an appropriate insurance product. If a mirror insurance product exists later, the Laybye is called by that product name. If no mirror exists, it is called a credit-improvement loan child.
- Pre-disbursement receipts sit in the Laybye if a Laybye account exists. Accounting on the loan account is the same as any other account except it is cash in, not loan out.
- A top-up of the loan is treated like any other loan top-up. The existence of a linked Laybye does not change the top-up treatment.
- Credit life pays the loan first; Laybye covers any shortfall; surplus goes to the estate (cash-deposit treatment).
- Funeral is an insurance product; the beneficiary sits with the insurer, not in the LMS.
- Death may not apply the Laybye without a section 124 authority signed in life; otherwise the Laybye stays with the estate.
- Structured as a deposit-insurance style arrangement (client pays for a period, then loan is disbursed). Not deposit-taking under the Banks Act for Day-1 purposes.
- Credit life statements and accounts sit in the insurer’s domain. The LMS does not keep them.
- If collections are automated from the LMS, the LMS must know the credit-life premium amount so it can raise one collection for the loan instalment and a separate collection for the credit-life premium.

## 5. Day count and accrual

- Both actual/actual and standard 30/360 must be available. Credit provider chooses.
- Recommendation for new products: default to actual/actual; keep 30/360 as a selectable option.
- Accrual frequency is daily.
- A 360-day year is not required for Day-1.
- Interest and fee accrual must use the same day-count and base method that was used to calculate the contractual instalment. Do not use a different method for accrual than was used for the instalment quote.

## 6. Default definition — contractual breach vs collections default

- Two distinct concepts:
  - Contractual breach: payment was due on day X and not received on day X. Once the day has passed this cannot be rectified (unless it was a system error, in which case it is corrected as if it never occurred).
  - Collections default: the account is outside its limit (in arrears). This can be cured by paying the arrears amounts.
- The default flag starts the in-duplum calculation (if not already in an episode) and is used for reporting and collections. It does not stop the charging of fees or interest. Payments continue to be treated normally.
- The client chooses which event kicks off in-duplum:
  - Contractual breach (ceiling is fixed at that date and cannot be restarted), or
  - Collections default (in-duplum can stop if the client cures, and a new episode starts on the next collections default).
- Leniency period is configurable per customer and counts calendar days (including weekends and public holidays).
- Unset leniency_days or full_payment_threshold_percent fails closed. Do not hard-code example values as defaults.
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
- A cure closes the episode only when the client has chosen collections-default as the in-duplum trigger. If the client has chosen contractual breach, the ceiling remains fixed.
- A new default starts a fresh episode with a new ceiling based on the unpaid principal at the start of the new default (when collections-default trigger is selected).
- Three section 103(5) edges not decided by Nedbank remain unnamed and unsigned; the clip stays off until counsel lists and confirms them. No implementation assumption is made.
- This is not an absolute single-lifetime ceiling when the collections-default trigger is selected.
- Aligned with section 103(5) and Nedbank v NCR [2011] ZASCA 35, subject to the client-selected trigger above.

## 8. Payment allocation and capitalisation

- Section 126 order: due or unpaid interest, then due or unpaid fees or charges, then principal.
- Only due or unpaid amounts are allocated.
- When multiple fee buckets are all already due, order is: collection costs, default administration, credit insurance, service fee, initiation fee (earliest due date first within each bucket).
- On any calendar day, accrued interest and fees that become due that day are capitalised at 00:00 before payments recognised that day are allocated.
- Capitalisation and payment allocation need not occur on the same calendar day. Capitalisation may be month-end; payment may be on the client's payday. Each is processed on its own recognition date.
- Fees and interest charged may never exceed NCA limits.
- If the client pays the contractual instalment exactly as per the contract, the loan will either be repaid earlier or a small residual may be written off after the last instalment.
- Small residual write-off threshold is client-configurable. Default value is R100. It is not automatic.
- If the client does not pay exactly the contractual instalment, the difference becomes part of arrears. Normal arrears, in-duplum and collections rules then apply. The client either continues paying until the loan is fully repaid, or the outstanding amount is written off.
- Provision and write-off are per client requirement and can be manual or formula-based (arrears, recency, months on book, promise-to-pay adherence, contactability, etc.).

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
  - (b) keep the original instalment and either settle early or write off a small residual at contractual end.
- After a partial prepayment the provider chooses whether to shorten the term or drop the instalment.
- Prefer keeping the contractual instalment the same during the loan term.
- Additional fees outside interest, initiation, monthly service fee and credit life (for example certain collection costs) should be added as a further monthly fee (fixed or variable), not capitalised into the amortisation schedule.
- A loan restructuring capability exists so that other costs can be added during the term by creating a new instalment, pricing and term when required.
- “Subsequent” short-term loan is counted per credit-provider organisation and per calendar year.
- Interest and fee accrual must use the same method that was used to calculate the contractual instalment.

## 14. Payment frequencies

- Must support weekly, fortnightly, monthly, quarterly, bi-annual and annual.

## 15. Enigma boundary

- Enigma is limited to identity and access management:
  - Individual registration, login, logout and password administration.
  - Linking individuals to companies and roles.
  - Granting access to applications based on the company and role after the individual has been verified and signed in.
  - Uses ID number and company registration for this purpose.
- LMS stores only opaque person_id and organisation_id.
- LMS does not re-implement person or organisation identity.
- Fail closed on Enigma timeout, ambiguous status, or a clear suspended enrolment.
- Everything else is an LMS responsibility, including:
  - Stores and brands linked to a company.
  - NCR registration numbers.
  - All data required for statements so that the correct details appear.
  - All data required for regulatory and compliance reporting.
- Enigma does not hold or return the NCR registration number, trading names, addresses, telephone numbers, payment-account details, or brand assets.

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
  - In-duplum trigger (contractual_breach / collections_default). Booking fails closed if the in-duplum trigger is unset.
  - Residual write-off threshold. The residual write-off threshold has a platform default of R100. An unset organisation or product value fills R100.
- Unset values fail closed. The residual write-off threshold is the exception: an unset organisation or product value fills R100.

## 20. Prescription (section 126B)

- Prescription handling is per client requirement.
- It can be manual or formula-based.
- Different clients may use different formulas based on arrears, recency, months on book, promise-to-pay adherence, contactability, and other factors.
- No platform default is imposed.

## 21. NCR registration number and compliance data

- The NCR registration number is stored as an LMS tenant attribute (organisation level).
- Enigma does not hold or return it.
- It is required on NCA communications and regulatory extracts for micro and unsecured personal loans.
- It is not required for pure hosting or for Laybye/BNPL.
- A blank NCR number blocks those communications and extracts. It does not block booking.
- Trading name, addresses, telephone numbers, payment-account details and brand assets are also LMS-owned and are not supplied by Enigma.

## 22. Non-campaign rate or fee change

- A non-campaign rate or fee change also requires a written notice of at least five business days before it takes effect (section 104(2)).
- A temporary reduction is stored as a concession or discount that goes to zero when the period ends.
- The original contractual rate and fees remain effective and are not changed.
- Resuming the original rate does not require a second notice.
- An interest-rate change does not automatically reduce the contractual instalment. The instalment remains stable unless a reduced-payment process is followed.
