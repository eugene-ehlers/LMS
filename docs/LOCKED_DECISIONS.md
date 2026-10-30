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
- The payment rail must capitalise due amounts before allocating.

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
- The discount rate may be higher than the base rate, but the net (base rate less discount) is floored at 0 %. It can never be negative.
- Fees also cannot be negative. A fee discount that would produce a negative fee is capped at R0.
- A discount affects the value used as the rate for calculations. It does not change the accrual method, day-count convention, or annualisation method.
- A discount can apply to any product (annual, weekly, etc.).
- Whether the discount falls away on default is a client choice, stored per campaign:
  - Option A: discount falls away on the chosen default event (contractual breach or collections default).
  - Option B: discount does not fall away.
- It must be clear which default event (contractual breach or collections default) triggers fall-away when Option A is selected.
- The base rate is the rate charged by the client. For unsecured personal this is normally the NCA maximum (repo rate + margin) fixed at the time of contract. The discount is applied against that contractual rate.
- If the client has opted for the rate to reduce when the repo rate falls, the contractual rate reduces and the discount is applied to the reduced rate. The effective rate is capped at 0 % and can never be negative.
- Every campaign has a start date and an end date. Staff must be able to set and change them (for example to correct errors).
- Any loan generated during the campaign period qualifies for the linked campaign, even if the loan term extends beyond the campaign end date.
- Treatment of variable rates, discounts, or opted-for reducing rates depends on the rules of that campaign.
- The system must be agile enough to support campaigns that match the client’s products and campaign rules.
- A campaign edit or end does not reprice agreements already booked.
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
- The decision engine supplies the credit-life premium amount each time.

## 5. Day count and accrual

- Both actual/actual and standard 30/360 must be available. Credit provider chooses.
- Recommendation for new products: default to actual/actual; keep 30/360 as a selectable option.
- Accrual frequency is daily.
- A 360-day year is not required for Day-1.
- Interest and fee accrual must use the same day-count and base method that was used to calculate the contractual instalment. Do not use a different method for accrual than was used for the instalment quote.
- Converting a rate between weekly, monthly, annual or daily must follow NCA prescriptions and well-supported mathematical benchmarks so the conversion is defensible.
- Weekly periods = actual days in the year / 7. This caters for leap years. A fixed 52 or a fixed 365 is not used.

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
- A system-error correction of a contractual breach restores the campaign discount and clears the in-duplum ceiling as if the breach never occurred.

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

## 8. Payment allocation, capitalisation and write-off

- Section 126 order: due or unpaid interest, then due or unpaid fees or charges, then principal.
- Only due or unpaid amounts are allocated.
- When multiple fee buckets are all already due, order is: collection costs, default administration, credit insurance, service fee, initiation fee (earliest due date first within each bucket).
- On any calendar day, accrued interest and fees that become due that day are capitalised at 00:00 before payments recognised that day are allocated.
- Capitalisation and payment allocation need not occur on the same calendar day. Capitalisation may be month-end; payment may be on the client's payday. Each is processed on its own recognition date.
- Fees and interest charged may never exceed NCA limits.
- If the client pays the contractual instalment exactly as per the contract, the loan will either be repaid earlier or a small residual may be written off after the last instalment.
- Small residual write-off threshold is client-configurable. Default value is R100. It is not automatic.
- If the client does not pay exactly the contractual instalment, the difference becomes part of arrears. Normal arrears, in-duplum and collections rules then apply. The client either continues paying until the loan is fully repaid, or the outstanding amount is written off.
- Write-off can be manual. If automated, the external formula is the mandate.
- A write-off can never be more or less than the outstanding balance. All receipts must be allocated before the write-off. If the balance does not reduce to R0 it is not a write-off.
- A balance can open again at a later date if a payment taken into consideration is returned unpaid. That must be flagged so approval can be obtained to write it off as well.
- A returned unpaid item after a write-off is flagged only. The balance is not reopened and no recovery is posted in the LMS.
- Any income received after a write-off is a recovery and is dealt with at the accounting level, not in the LMS.
- Provisioning formulas are run outside the LMS. The LMS only receives an instruction to write off or not, or the action is performed manually.
- Recency, months on book, promise-to-pay adherence and contactability are risk calculations performed on LMS data in reporting. They are not calculated inside the LMS.

## 9. Service-fee pro-rata and VAT

- Pro-rata only in the opening month (disbursement to first payment due).
- Opening-month fraction = inclusive calendar days from the disbursement date to the day before the first due date, divided by the actual days in the disbursement month.
- Full monthly fee thereafter, including the settlement month, subject to the R60 cap.
- Rand maxima (R60, R165, R1 050) are excluding VAT by default (NCR January 2019 note). Provider may elect inclusive if required.
- Consistent with regulation 44(4) and the Micro Finance South Africa judgment.
- VAT applies to all vatable pricing components. If the client selects no VAT, it applies to all vatable components.
- The LMS must always calculate VAT. If the client is exempt or has a lower effective rate because of input/output ratios, that is reflected in the rate (exempt = 0 % on a vatable component).
- Non-vatable components must show no VAT rate, so that “not legally vatable” is distinguishable from “client does not want to charge VAT”.

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

## 12. Statements and documents

- One statement per client per credit-provider organisation, showing all of that client's loans with that organisation.
- Each loan retains its own opening and closing balance so section 109 still holds.
- The maximum period between successive statements is one month for Day-1 products (short-term and unsecured personal). Section 108 allows longer periods for other agreement types; those are not Day-1 products.
- The LMS produces shortened statements, interim statements, regular statements, proof of balances and proof of payments.
- Origination and contracting documents are produced in the decision engine before the information is sent to the LMS.
- Logo and look-and-feel are client-specific. The platform provides basic templates. The client may supply their own look and feel for customisation.
- Documents must be developed so that look-and-feel and logos are easy to change. Use shared headers and footers and centralised look-and-feel so that one change flows through rather than requiring multiple edits.
- Unless specific Laybye or BNPL legislation requires otherwise, use the NCA. Be consistent where possible.
- Show values only where they are charged.
- Staff must be able to locate records by ID (or passport / ID equivalent) or by loan number.

## 13. Decision engine, instalments and additional fees

- Initially the platform’s own engine can be forced; long-term the LMS must accept loans from external decision engines.
- Quote date and disbursement date may differ. The contractual instalment accepted by the client is binding.
- The contractual instalment must be stored on the agreement.
- Any change to the contractual instalment made by the LMS requires client consent.
- A restructure changes the contract and therefore changes the instalment.
- Arrears are added to the amount due. The contractual instalment itself remains the same; the amount due is larger because it includes arrears.
- If an instalment is missed, the loan remains open even after the contractual term has passed.
- Two options must be supported when disbursement occurs later than the quote date:
  - (a) adjust the instalment based on actual disbursement date and remaining term, or
  - (b) keep the original instalment and either settle early or write off a small residual at contractual end.
- After a partial prepayment the provider chooses whether to shorten the term or drop the instalment.
- Prefer keeping the contractual instalment the same during the loan term.
- Additional fees outside interest, initiation, monthly service fee and credit life (for example certain collection costs) should be added as a further monthly fee (fixed or variable), not capitalised into the amortisation schedule.
- A loan restructuring capability exists so that other costs can be added during the term by creating a new instalment, pricing and term when required.
- The 5 % / 3 % short-term rate distinction is supplied by the decision engine. The LMS uses the rate it is given and checks that calculations stay within the Act for that rate. The LMS does not contain the rules that decide whether a loan is concurrent, subsequent, settled-and-readvanced, or restructured. Those rules sit in the decision engine.
- Interest and fee accrual must use the same method that was used to calculate the contractual instalment.
- To avoid loan splitting, a second quote or loan for the same application must be failed until the first has been declined and is no longer open.

## 14. Payment frequencies

- Must support weekly, fortnightly, monthly, quarterly, bi-annual and annual.

## 15. Enigma boundary

- Enigma is limited to identity and access management:
  - Individual registration, login, logout and password administration.
  - Linking individuals to companies and roles.
  - Granting access to applications based on the company and role after the individual has been verified and signed in.
  - Uses ID number and company registration for this purpose.
  - Holds contact number and email for registered users (for password reset and similar).
- LMS stores only opaque person_id and organisation_id.
- LMS does not re-implement person or organisation identity.
- Fail closed on Enigma timeout, ambiguous status, or a clear suspended enrolment.
- Everything else is an LMS responsibility, including:
  - Stores and brands linked to a company.
  - NCR registration numbers.
  - Operational rand ceilings.
  - Campaign configuration.
  - All data required for statements so that the correct details appear.
  - All data required for regulatory and compliance reporting.
- Enigma does not hold or return the NCR registration number, trading names, addresses, telephone numbers for unregistered consumers, payment-account details, brand assets, operational ceilings, or campaign data.
- A consumer who wants to see their statements or settlement quotes must register via Enigma and sign in. The LMS does not store the consumer’s contact number or email for this purpose.
- LMS registration and sign-on pages direct the consumer to Enigma. The LMS does not implement registration or sign-on functionality.

## 16. Identity freeze on agreement

- Freeze name + ID number + service address at booking.
- Subsequent changes in Enigma do not rewrite the concluded agreement.

## 17. Rounding and disclosure

- Round half-up to cents on billing.
- The same rounding rule must be applied everywhere rounding is required.
- Proviso: rounding must not create a compliance issue (example: an instalment rounded up above the affordability figure previously aligned with the client).
- Annual-equivalent rate for disclosure = periodic rate × number of periods per year (simple nominal, not effective). Disclose both the periodic rate and the nominal annual rate.
- A discount affects the rate value used in the calculation. It does not change the annualisation method.
- Weekly periods for annualisation = actual days in the year / 7.

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
  - In-duplum trigger (contractual_breach / collections_default)
  - Residual write-off threshold (default R100)
  - Campaign discount fall-away choice (falls_away_on_default / does_not_fall_away)
  - Campaign fall-away trigger (contractual_breach / collections_default)
- Unset values fail closed.
- Campaign fall-away choice and trigger are stored per campaign.
- Role names for edits must be descriptive and follow best practice (for example lms.elections.write, lms.campaign.write).

## 20. Prescription (section 126B)

- Prescription is a collections action (or the decision not to collect). Whether it runs does not sit in the LMS.
- The result can be a write-off or the loan can continue to run as normal under the existing rules.
- Formulas that decide prescription are run outside the LMS. The LMS only receives the instruction or the action is performed manually.
- No platform default is imposed.

## 21. NCR registration number and compliance data

- The NCR registration number is stored as an LMS tenant attribute (organisation level).
- Enigma does not hold or return it.
- It is compulsory. For testing a test number in the same format with all zeros may be used.
- It is required on NCA communications and regulatory extracts for micro and unsecured personal loans.
- It is not required for pure hosting or for Laybye/BNPL.
- Trading name, addresses, telephone numbers, payment-account details and brand assets are also LMS-owned and are not supplied by Enigma.
- Compliance details (NCR number, trading name, addresses, telephone, payment-account details) are required for reporting, control and audits and must be captured up front.

## 22. Operational rand ceilings

- Operational rand ceilings are LMS data.
- Solution-wide ceilings are adjustable by TSDG (platform owner) via an interface.
- Company-specific ceilings are adjustable by a company admin via an interface restricted to certain roles.
- LMS applies the tighter of the two.
- A missing platform ceiling stops the command.
- These are authorization limits. Statutory NCA maxima stay in the calculation engine.

## 23. Audit trail

- All actions on the LMS, whether system changes or changes to accounts, must produce an audit record.
- The audit record includes who did it (staff identity from Enigma), when it was done, and what was done.
- A system-error correction is an audited action and must record the staff identity.
- For any change (compliance, elections, brand, ceiling, campaign, promise-to-pay, contact, system-error), a person must sign in with the correct role so the sign-in details can be stored in the audit record.
- The audit must be sufficient to identify who did things and whether they had the mandate to do so.
- Role-based access and audit records are required to pass POPIA and other audits.

## 24. Pricing

- There is one price mechanism: R100 per month.
- R100 per month drives the annual fee and any discount offered to entice annual payments.
- Any reference to R50 must be replaced with R100.

## 25. Loan numbers

- Loan numbers are generated by the LMS.
- The decision engine supplies an application number. The LMS links the loan number to the application number for audit purposes.
- There can be only one loan number for an application, except for a Laybye where the core loan number is the same and the Laybye is distinguished by another indicator.
- Loan numbers must be sequential and cannot be skipped.
- Loan numbers must be long enough so the system does not run out of numbers.
- Identifiers such as the first four letters of the company name and the month and year created may be included.

## 26. Payment rails and debit orders

- The payment rail must capitalise due amounts before allocating.
- A returned unpaid item after a write-off is flagged only. The balance is not reopened and no recovery is posted in the LMS.
- The decision engine supplies the credit-life premium amount each time.
- Debit-order file layout uses a standard South African format and must also cater for DebiCheck.
- An unmatched receipt may be matched on loan number or ID number.

## 27. Consumer access and notifications

- A consumer who wants information on their accounts must register via Enigma and sign in. Without registration they cannot access statements, settlement quotes or other account information.
- The LMS does not send collection notices. Collection notices are the responsibility of the collections software.
- Contact details for collection purposes are obtained from the client database via the application number (linked to the loan number and ID number). The LMS does not store them for this purpose.
- Staff with the appropriate role can access account information and provide it to a consumer who phones a call centre.
- The NCR registration number must be displayed on all NCA communications.
- The LMS sends a regular push when the monthly statement for the month is ready. The push tells the consumer the statement is available. It does not contain collection content.

## 28. Collection campaigns

- A collection campaign is a bulk change applied to existing accounts. It does not create a new credit agreement (section 95).
- Staff define a collection campaign with a start date, an end date (or open-ended), and one or more of the following changes:
  - Reduce or zero the interest rate for the campaign period or the rest of the term.
  - Reduce or zero one or more fees for the campaign period or the rest of the term.
  - Waive the contractual instalment for the campaign period (payment holiday).
- The campaign is applied to a selected set of accounts (by organisation, product, or an explicit list).
- During the campaign period the ledger applies the reduced rate or fee, or skips the instalment. The contractual term and the contractual instalment amount are not changed.
- When the campaign ends, the original rate and fees resume unless the campaign was open-ended.
- A payment holiday does not reset in-duplum. Interest continues to accrue on the outstanding balance unless the campaign also zeros the rate.
- A reduction in rate or fee is not an increase. Section 104(1) prohibits unilateral increases. A written notice of at least five business days is required before the change takes effect (section 104(2)).
- The original contractual rate, fees, and instalment remain stored for disclosure. The campaign values are stored separately and are used for accrual during the campaign period.
- Every collection-campaign change is audited. The audit record includes who applied it, when, the accounts affected, and the before and after values.
- A change that alters the contractual term or the contractual instalment amount is a restructure and is not a collection campaign.

Points section 28 does not settle are listed in `docs/collection-campaigns/gaps.md`.

## Gaps recorded (not rules)

The payment-rail layer found these points unset. Nothing in this section is a decision. The implementation fails closed or calls an existing interface. It does not fill a value in.

- Section 19 does not name an automated-collections election. The configuration catalogue already has `debit_orders_enabled` (“Submit debit orders”). A missing row fails closed. The lock does not say that flag is the section 4 automation switch.
- Section 25 does not fix the loan-number character pattern. The Bankserv user reference allows 14 characters for the mandate or agreement number. Section 13 requires the contractual instalment to be stored; the agreement stores a principal schedule. The debit-order loan line reads the section 6 amount still outstanding on that due date and does not invent unbilled interest.
- The published Bankserv collections layout does not define a DebiCheck record, and it does not state the hash-total algorithm beyond a 12-digit field. Consumer homing-account details and the bank’s 10-character abbreviated user name are not LMS fields in this document. A credit-life premium receipt has no insurer hand-off here.
- Whether interest that accrues on a payment date is itself due that day, or only on an instalment due date, is not settled beyond “capitalise due amounts, then allocate”.
- Section 8 and section 19 say the residual write-off threshold default is R100, and section 19 also says an unset election fails closed. `resolve_residual_threshold_cents` still returns 5 000 cents when both levels are null. This layer does not call that resolver and does not choose between those readings.
- Settlement re-advance has no module order in the orchestration note. The route, the settlement-month fee, and the points this command does not decide are recorded in `docs/settlement-readvance/`. That note is not a rule.
