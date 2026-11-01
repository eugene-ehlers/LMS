# LMS Locked Decisions

Single source of truth for all decisions that have been researched and locked.
All future agents, chats and developers must follow these rules.
Do not re-open a locked decision without an explicit change request.

Last updated: 2026-11-01

## Standing instruction for all agents

Before proposing or implementing any calculation, ledger, servicing or configuration behaviour:
1. Read this document and follow all locked decisions.
2. If you find a gap, conflict, or uncertainty between this document and the Act, regulations, case law, or another design, raise it explicitly.
3. Do not invent a default or silently choose a reading. Flag the point so the locked decisions can be updated and all agents can see the change.

## 1. Value date and day boundary

- System recognition date is the value date for all allocation and reversals.
- Start of the day is treated as 00:00.
- The recognition date is 00:00 Africa/Johannesburg. An instant is accepted only when it is exactly 00:00 in that zone, and the stored offset is +02:00. Any other clock time is refused. A naive datetime has no Johannesburg day and is refused. It is not written to the audit log.
- A loan, settlement or deposit concluded at any time on a calendar day is treated as having occurred at 00:00 on that day.
- Reversals use the same value date the system originally recognised.
- A payment received on a flag date is treated as 00:00 on that day and is visible to the morning default check.
- When two events are both recognised at 00:00 on the same calendar day, process them in the order they were recognised by the system (stable sort by receipt sequence).
- On any calendar day, capitalisation of accrued interest and fees and allocation of payments recognised that day are treated as simultaneous at 00:00. The order is: accrue and capitalise the day's due amounts first, then allocate payments recognised that day, then run the morning default check.
- A receipt recognised on the flag date is visible to that morning default check.
- Interest that has accrued up to the due date is due on that date. It is capitalised before the receipt is allocated.
- The payment rail must capitalise due amounts before allocating.

## 2. Initiation fee treatment

- If capitalised → part of the principal debt.
- If not capitalised → treated as a due fee/charge under section 126.
- Same logic applies to related fee points.
- A capitalised initiation fee that was capitalised before the default date sits inside the in-duplum ceiling.
- Day-1: only products where section 102 explicitly allows capitalisation may capitalise the initiation fee. Short-term and unsecured default to non-capitalised.
- A settlement quote uses the booked initiation fee. It does not use the statutory formula.
- If the initiation fee is capitalised, it is already part of the loan value. It is not added again.
- If the initiation fee is not capitalised, the outstanding portion is not yet due. It is added to the settlement value.
- VAT is always included in the settlement value. The client remains accountable for the VAT portion.
- A settlement quote is binding for five business days (section 113, `binding_until`). The caller supplies the public holidays. No holiday calendar is assumed.
- Early-settlement interest runs to the quote as-of date. Days between that date and a later receipt date are not accrued on this path.
- An early-settlement receipt must equal the quoted total. A different amount is refused and is not allocated. That refusal is not the Laybye remainder in Decision 4.
- `Documents.settlement_quote` does not take repo rows. A non-empty repo list is refused on the quote and on execute. No repo rate is assumed.
- An audit record includes when the action was done. A naive recognition timestamp has no Johannesburg day, so no audit row is written and the failure is returned. An unknown agreement id has no organisation to attach, so no audit row is written and the failure is returned. No actor and no timestamp are invented to force a row.

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
- Every campaign has a start date and an end date. Staff must be able to set and change them (for example to correct errors). The end date in this section is the pricing campaign. An open-ended period is a collection campaign (Decision 28), not a pricing campaign.
- Any loan generated during the campaign period qualifies for the linked campaign, even if the loan term extends beyond the campaign end date.
- When a loan qualifies for a campaign, that campaign's fall-away choice and trigger apply. When it does not, the organisation election applies, and a product value overrides the organisation.
- When more than one campaign period contains the recognition date, intake fails closed and stores nothing.
- The contractual rate remains the rate the decision engine supplies. The campaign net is the rate used for calculations during the campaign. Both figures are stored. One is not copied over the other.
- Treatment of variable rates, discounts, or opted-for reducing rates depends on the rules of that campaign.
- The system must be agile enough to support campaigns that match the client’s products and campaign rules.
- A campaign edit or end does not reprice agreements already booked.
- Penalty interest may not exceed the contractual interest rate.

## 4. Laybye linked to a loan (parent/child)

- Parent/child relationship required. Contracts must treat the pair as one loan (not as security that would make the loan secured).
- Once a loan is granted, the default allocation is: all payments go to the loan first (section 126 order). Any excess then goes to the Laybye account.
- After due section 126 amounts, the remainder goes to the Laybye.
- The partial-prepayment election applies only to a remainder that is not sent to a linked Laybye.
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
- A receipt counts only toward the due date it is attributed to.
- If section 126 applies part of the receipt to an earlier due amount, that part does not count toward a later due date.
- A system-error correction of a contractual breach restores the campaign discount and clears the in-duplum ceiling as if the breach never occurred.

## 7. In-duplum base and episodes

- Ceiling = unpaid principal (including any pre-default capitalised initiation fee) as at the date of first default in that episode.
- Post-default accruals count as charges even if displayed as capitalised on statements.
- Charges that cause the default do not count toward the cap; only charges that accrue during the default episode.
- A payment during the default reduces what is owed but does not reset the counter for that episode.
- A cure closes the episode only when the client has chosen collections-default as the in-duplum trigger. If the client has chosen contractual breach, the ceiling remains fixed.
- A settlement closes any open in-duplum episode. The flag is cleared.
- A new default starts a fresh episode with a new ceiling based on the unpaid principal at the start of the new default (when collections-default trigger is selected).
- Three section 103(5) edges not decided by Nedbank remain unnamed and unsigned. No implementation assumption is made about those edges.
- The in-duplum clip is on for Day-1.
- When charges that accrue during a default episode equal the ceiling, the system raises a flag, records a warning, and stops levying further charges until the episode is closed.
- Payments during the episode reduce the balance but do not restart charges.
- A cure closes the episode (when the collections-default trigger is selected). A later default opens a new episode with a new ceiling.
- This reading follows Nedbank v NCR [2011] ZASCA 35 and NCR guidance. It will be adjusted if counsel names a different reading.
- This is not an absolute single-lifetime ceiling when the collections-default trigger is selected.
- Aligned with section 103(5) and Nedbank v NCR [2011] ZASCA 35, subject to the client-selected trigger above.

## 8. Payment allocation, capitalisation and write-off

- Section 126 order: due or unpaid interest, then due or unpaid fees or charges, then principal.
- Only due or unpaid amounts are allocated.
- When multiple fee buckets are all already due, order is: collection costs, default administration, credit insurance, service fee, initiation fee (earliest due date first within each bucket).
- On any calendar day, accrued interest and fees that become due that day are capitalised at 00:00 before payments recognised that day are allocated.
- Interest that has accrued up to the due date is due on that date. It is capitalised before the receipt is allocated.
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
- The LMS does not store promise-to-pay adherence or contactability, and it does not accept them as provisioning or prescription inputs.
- A full write-off journal can be posted. The Form 39 write-off cell stays empty. The journal is not mapped onto that cell.

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
- One month in this section is a calendar month. The statement path does not count thirty days. It refuses an overlapping period and a gap that would hide a ledger value date.
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
- The partial-prepayment election applies only to a remainder that is not sent to a linked Laybye.
- Prefer keeping the contractual instalment the same during the loan term.
- Additional fees outside interest, initiation, monthly service fee and credit life (for example certain collection costs) should be added as a further monthly fee (fixed or variable), not capitalised into the amortisation schedule.
- A loan restructuring capability exists so that other costs can be added during the term by creating a new instalment, pricing and term when required.
- The 5 % / 3 % short-term rate distinction is supplied by the decision engine. The LMS uses the rate it is given and checks that calculations stay within the Act for that rate. The LMS does not contain the rules that decide whether a loan is concurrent, subsequent, settled-and-readvanced, or restructured. Those rules sit in the decision engine.
- Day-1 test and dummy decision-engine values are an integer periodic rate in basis points, a term count plus a payment frequency, and an application number of APP- plus eight digits. One basis point is 0.01 percent. This is the Day-1 contract the LMS accepts. It is not a statutory wire format.
- A restructure keeps the original loan number. It copies the application number and does not allocate a second loan number.
- The restructure path runs the calculation engine's prescribed-rate check on the supplied periodic rate. It does not add a maximum of its own. The 5 percent and 3 percent distinction stays with the decision engine, so the check uses the engine's higher prescribed monthly rate.
- The restructure path records the roles presented to it. It does not invent a role name and it does not call a role check that would invent one.
- A payment-frequency change that does not change the contractual term or the contractual instalment is neither a restructure nor a collection campaign. The path fails closed and creates no agreement.
- A restructure moves the outstanding balance, in integer cents, from the original agreement record to the new agreement record. The original record's outstanding balance becomes zero. A ledger bucket balance remains the sum of its entries. These decisions do not name a restructure journal, so the path does not post one.
- The new agreement is stored as active. The original agreement is stored as restructured.
- When the caller does not supply a resolved election row, the restructure path reads the organisation election and the optional product override. A missing election fails closed. An unset residual write-off threshold still fills R100.
- A consented restructure requires client consent and a consent date. It does not add the collection-campaign notice of five business days.
- A naive recognised_at on a restructure is reported on the response and is not written to the audit log, because Decision 1 gives that clock no Johannesburg day.
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
- Organisation context returns the organisation id and the company registration number. It does not return a service address. The booking identity read returns the service address that is frozen.
- The consumer-registration check returns whether the consumer is registered. It does not return email or mobile.
- A consumer who wants to see their statements or settlement quotes must register via Enigma and sign in. The LMS does not store the consumer’s contact number or email for this purpose.
- LMS registration and sign-on pages direct the consumer to Enigma. The LMS does not implement registration or sign-on functionality.

## 16. Identity freeze on agreement

- Freeze name + ID number + service address at booking.
- The frozen name, ID number, and service address are the Enigma booking read. A differing application value is not frozen.
- Subsequent changes in Enigma do not rewrite the concluded agreement.

## 17. Rounding and disclosure

- Round half-up to cents on billing.
- The same rounding rule must be applied everywhere rounding is required.
- The calculation engine rounds each interest bill half-up and clears the unbilled remainder. The ledger rounds the cumulative memo half-up. A one-cent difference between those totals is a refusal. No balancing journal is posted.
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
  - In-duplum trigger (contractual_breach / collections_default). Booking fails closed when this trigger is unset on both the organisation and the product.
  - Residual write-off threshold. The platform default is R100. An unset organisation value and an unset product value fill R100. A stored value, including zero, is kept. A product value overrides the organisation.
  - Campaign discount fall-away choice (falls_away_on_default / does_not_fall_away)
  - Campaign fall-away trigger (contractual_breach / collections_default)
  - Debit orders enabled. This is the automated-collections switch. It does not change allocation. An unset value fails closed. A false value submits no debit-order file.
- Unset values fail closed. The residual write-off threshold is the exception: an unset value fills R100.
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
- The ledger classifications `short_term` and `unsecured` are the micro and unsecured personal loans that require the number. `zero_cost` and `cpa_layby` are Laybye/BNPL and do not. Pure hosting is not a column. The extract reads the agreement classification. The caller supplies pure hosting. When it is omitted and a classification would require the number, the extract fails closed. A statement covers more than one loan, so it is not given a second classification column.
- A blank NCR number is refused. A non-blank value, including a test number of all zeros, is accepted.
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
- Promise-to-pay and contact are named above as changes that need a signed-in person. The LMS does not store those facts and does not accept them as provisioning or prescription inputs.
- An operator who holds only `lms.collection_campaign.write` cannot open the batch screen. No batch-status role is named.
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
- The Day-1 loan number is a 12-digit sequence starting at 1. No company prefix is added until one is supplied. The sequence is not skipped.
- The debit-order loan line reads the amount still outstanding on that due date. The contractual instalment stays stored on the agreement and is not replaced by that line.

## 26. Payment rails and debit orders

- The payment rail must capitalise due amounts before allocating.
- A returned unpaid item after a write-off is flagged only. The balance is not reopened and no recovery is posted in the LMS.
- The decision engine supplies the credit-life premium amount each time.
- Debit-order file layout uses a standard South African format and must also cater for DebiCheck.
- The Day-1 file writes record 50 for both EFT and DebiCheck and hashes homing account numbers modulo 10**12. A missing homing account or abbreviated name fails closed. A credit-life premium receipt is stored as accepted by the insurer and is not posted to an insurer. No other DebiCheck record type and no other hash algorithm are named.
- An unmatched receipt may be matched on loan number or ID number.

## 27. Consumer access and notifications

- A consumer who wants information on their accounts must register via Enigma and sign in. Without registration they cannot access statements, settlement quotes or other account information.
- The LMS does not send collection notices. Collection notices are the responsibility of the collections software.
- Contact details for collection purposes are obtained from the client database via the application number (linked to the loan number and ID number). The LMS does not store them for this purpose.
- Staff with the appropriate role can access account information and provide it to a consumer who phones a call centre.
- The NCR registration number must be displayed on all NCA communications.
- The LMS sends a regular push when the monthly statement for the month is ready. The push tells the consumer the statement is available. It does not contain collection content.
- The NCR character pattern, the call-centre role name, the Enigma page URLs, and the push-provider machine action stay unset. The LMS does not store them.

## 28. Collection campaigns

- A collection campaign is a bulk change applied to existing accounts. It does not create a new credit agreement (section 95).
- Staff define a collection campaign with a start date, an end date (or open-ended), and one or more of the following changes. A null end date on this path is open-ended. Decision 3's end date is the pricing campaign:
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

- `debit_orders_enabled` is the Decision 19 automated-collections switch. It does not change allocation. An unset value fails closed. A false value submits no file. The earlier note that the lock did not name that flag is superseded.
- The Day-1 loan number is the 12-digit sequence in Decision 25, starting at 1, with no company prefix until one is supplied. The debit-order loan line reads the amount still outstanding on that due date. The contractual instalment stays stored. The earlier note that the character pattern was unset is superseded.
- The Day-1 Bankserv file writes record 50 for both EFT and DebiCheck and hashes homing account numbers modulo 10**12. A missing homing account or abbreviated name fails closed. A credit-life premium receipt is stored as accepted by the insurer and is not posted to an insurer. The earlier note that the layout named nothing else is superseded by that Day-1 reading.
- Interest that has accrued up to the due date is due on that date and is capitalised before the receipt is allocated. Sections 1 and 8. The earlier note that this was unsettled is superseded.
- Decision 19 fills an unset residual write-off threshold with R100. A stored value, including zero, is kept. The earlier payment-rail note that the resolver returned 5 000 cents, and that the two readings were unsettled, is superseded.
- Settlement re-advance has no module order in the orchestration note. The route, the settlement-month fee, and the points this command does not decide are recorded in `docs/settlement-readvance/`. That note is not a rule.

## Open points raised while implementing Layer 2

Points 1 to 4 are answered by the sentences in Decisions 3, 13, and 19. Nothing in those points chooses a different reading.

1. Decision 3 answers this. When a loan qualifies for a campaign, that campaign's fall-away choice and trigger apply. When it does not, the organisation election applies, and a product value overrides the organisation.
2. Decision 3 answers this. When more than one campaign period contains the recognition date, intake fails closed and stores nothing.
3. Decisions 3 and 13 answer this. The contractual rate remains the rate the decision engine supplies. The campaign net is the rate used for calculations during the campaign. Both figures are stored. One is not copied over the other.
4. Decision 19 answers this. An unset residual write-off threshold fills R100. A stored value, including zero, is kept. A product value overrides the organisation.

## 30. Daily calculation batch

- The batch steps are accrue, capitalise, then `default_check`. `default_check` is this batch's morning check. The batch does not call `Collections.observe`. `Collections.observe` is the call when a collections default is flagged.
- The batch does not take receipts. It checks receipts already posted, including a receipt recognised on the flag date.
- A finished batch with account failures does not block the next recognition date. An unfinished run blocks a later date until that same date is finished or explicitly skipped.
- A retry of an incomplete or skipped run walks every account through accrue, capitalise, and `default_check` again.
- The batch does not call Enigma. A missing `actor_id` fails closed and is not audited. A supplied person id is stored on the run and on the audit row. No role name is invented for running or skipping the batch.
- A calendar day that was never started does not block a later date.
- A recognition date whose batch has finished cannot be started again, including when accounts failed.
- The alert is a row returned by the status query. A hard stop leaves the run in progress. The alert row is written when a later start is refused or the run is skipped. No timeout is applied.
- Operators can query batch status by organisation and by account. The account query returns the stored failures for that account. UI-action status for a restructure is the last status recorded for that agreement, and the last recorded action for the organisation when no agreement is named.

## 29. Non-campaign rate or fee change

- A non-campaign rate or fee change requires a written notice of at least five business days before it takes effect (section 104(2)).
- A temporary reduction is stored as a concession or discount that goes to zero when the period ends.
- The original contractual rate and fees remain effective and are not changed.
- Resuming the original rate does not require a second notice.
- An interest-rate change does not automatically reduce the contractual instalment. The instalment remains stable unless a reduced-payment process is followed.
