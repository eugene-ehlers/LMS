# LMS Locked Decisions

Single source of truth for all decisions that have been researched and locked.
All future agents, chats and developers must follow these rules.
Do not re-open a locked decision without an explicit change request.

Last updated: 2026-10-27

## 1. Value date and day boundary

- System recognition date is the value date for all allocation and reversals.
- Start of the day is treated as 00:00.
- A loan, settlement or deposit concluded at any time on a calendar day is treated as having occurred at 00:00 on that day.
- Reversals use the same value date the system originally recognised.

## 2. Initiation fee treatment

- If capitalised → part of the principal debt.
- If not capitalised → treated as a due fee/charge under section 126.
- Same logic applies to related fee points.

## 3. Zero rates, zero fees and campaigns

- Must be fully supported.
- A campaign that sets interest to 0 % or fees to R0 is treated as the real rate less discount = 0 %.
- Calculations must not fail when rates or fees are zero for the full term or any portion of the term.
- Campaign pricing must be stored and displayed as base rate (x %) with a campaign discount (y %) deducted.
- If the discount falls away on non-payment, the penalty rate becomes the base rate (x %).
- Penalty interest may not exceed the contractual interest rate.

## 4. Laybye linked to a loan (parent/child)

- Parent/child relationship required.
- Payments can be allocated across both the loan and the linked Laybye.
- Interest is calculated on the net balance (loan principal minus Laybye hold).
- Only one monthly service fee.
- Client can consolidate or settle when Laybye ≥ settlement balance.
- Credit life / funeral treatment of the linked Laybye must be defined (estate vs direct to beneficiary, and effect on the outstanding loan that credit life is meant to settle).

## 5. Day count and accrual

- Both actual/actual and standard 30/360 must be available. Credit provider chooses.
- Recommendation for new products: default to actual/actual; keep 30/360 as a selectable option.
- Accrual frequency is daily.

## 6. Default definition (aligned for in-duplum and collections)

- Single definition used for both in-duplum and collections/reporting.
- Leniency period is configurable per customer (example: 4 or 5 days).
- Default is only automatically flagged on the contractual payment date + leniency days if the full payment is not received.
- “Full payment” threshold is configurable per customer (example: 95 % or more of the instalment received = not a default).
- Interest continues to be calculated daily on the outstanding balance. Leniency does not pause or reduce interest.

## 7. In-duplum base

- Unpaid principal (including any pre-default capitalised initiation fee) as at the date of first default.
- Post-default accruals count as charges even if displayed as capitalised on statements.
- A payment reduces what is owed but does not reset the counter.
- Aligned with section 103(5) and Nedbank v NCR [2011] ZASCA 35.

## 8. Payment allocation

- Section 126 order: due or unpaid interest, then due or unpaid fees or charges, then principal.

## 9. Service-fee pro-rata

- Pro-rata only in the opening month (disbursement to first payment due).
- Full monthly fee thereafter, including the settlement month, subject to the R60 cap.
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

## 12. Statements

- One statement per client showing all loans (not a separate statement per loan).

## 13. Decision engine and instalments

- Initially the platform’s own engine can be forced; long-term the LMS must accept loans from external decision engines.
- Two options must be supported when disbursement occurs later than the quote date:
  - (a) adjust the instalment based on actual disbursement date and remaining term, or
  - (b) keep the original instalment and either settle early or write off a small residual at contractual end
    (write-off not required if the account is already in default).

## 14. Payment frequencies

- Must support weekly, fortnightly, monthly, quarterly, bi-annual and annual.

## 15. Enigma boundary

- Enigma owns person identity, organisations, memberships, product enrolment, roles and mandates.
- LMS stores only opaque person_id and organisation_id.
- LMS does not re-implement person or organisation identity.
- Fail closed on Enigma timeout or ambiguous status.

## 16. Identity freeze on agreement

- Freeze name + ID number + service address at booking.
- Subsequent changes in Enigma do not rewrite the concluded agreement.

---

**Usage rule for agents**
Before proposing or implementing any calculation, ledger, servicing or configuration behaviour, read this document and follow the locked decisions. If a new decision is required, flag it explicitly and do not invent a default.
