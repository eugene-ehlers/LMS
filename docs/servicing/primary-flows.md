# Primary servicing flows

Design note for the post-origination LMS. Date of the sources checked: 26 October 2026 (Africa/Johannesburg). The source of truth is `docs/LOCKED_DECISIONS.md`, last updated 28 October 2026. Where this note disagrees with that file, that file wins.

The orchestration that now runs these flows is `src/lms/servicing/`. What is stable, what it calls, and the gaps that are still open are in [implementation-note.md](implementation-note.md).

| Behaviour | Locked section |
| --- | --- |
| Value date is the system recognition date, at 00:00. A reversal uses that same date. Same-day events keep recognition order. | §1 |
| Capitalised initiation is principal. Otherwise it is a section 126 charge. Day-1 short-term and unsecured default to non-capitalised. | §2 |
| A campaign stores base rate and discount. The discount stays through leniency, falls away on the flag date, and does not return. Zero rates and zero fees are valid. | §3 |
| A linked lay-by is one loan with its parent. Interest uses principal minus the hold. One service fee, on the parent. | §4 |
| Day count is actual/actual or 30/360. Accrual is daily. | §5 |
| Default is the due date plus leniency. Unset leniency or threshold fails closed. | §6 |
| In-duplum ceiling is per episode. The clip stays off. | §7 |
| Allocate due interest, then the named fee order, then principal. Memo accruals are not allocated. | §8 |
| Opening service fee uses inclusive days from disbursement through the day before first due, over the days in the disbursement month. Rand caps exclude VAT unless the provider elects inclusive. | §9 |
| Interest on a deferred initiation fee defaults to none only when the provider has stored `none`. An unset value fails closed. | §10, §19 |
| Repo-fall choice has no platform default. | §11, §19 |
| One statement per client per credit-provider organisation. Each loan keeps its own opening and closing balance. | §12 |
| Late disbursement and partial prepayment are provider choices. A subsequent short-term loan is counted per organisation and per calendar year. | §13, §19 |
| Frequencies are weekly, fortnightly, monthly, quarterly, bi-annual, and annual. | §14 |
| Enigma timeout, ambiguous status, or a suspended enrolment fails closed. Only opaque ids are stored. | §15 |
| Name, identity number, and service address are frozen at booking. | §16 |
| Billing rounds half-up. The disclosed annual equivalent is the periodic rate times the periods per year. | §17 |
| A default-administration or collection charge needs a tariff row. | §18 |

This note specifies how servicing books an activated agreement, takes payments, allocates them, and produces statements. It also specifies the calls servicing makes into the Calculation Engine and the Ledger. It does not design those two components. It states the contracts they must honour so that servicing can enforce the National Credit Act 34 of 2005 (NCA) without re-implementing them.

Enigma (`eugene-ehlers/enigma`) was not readable from this workspace. The Enigma calls below are the consumer port servicing needs. They are not a claim about Enigma's current API.

No NCA rule is invented below. Five elections were locked on 27 October 2026 (Africa/Johannesburg). They are L1 to L5 in section 4. Each one has a worked example. The agreement stores the resolved values, and every Calculation Engine call receives them. Choices that are still open stay marked as such. The implementation contracts, state machine, and sequences are in [implementation-design.md](implementation-design.md).

## 1. Boundaries

Servicing is the system of record for the life of an agreement after the external decision engine has approved it and the consumer has accepted it. Affordability (s 81), the quotation (s 92), and the agreement form (s 93) stay in origination. Servicing re-checks the cost of credit because servicing is the component that will levy it. A failed check refuses the booking. Servicing does not silently reprice.

| In this design | Explicitly out of this design |
| --- | --- |
| Book, disburse-confirm, accrue-instruct, allocate, settle, statement, s 110 enquiry, s 111 dispute intake, s 113 settlement quote, s 104 variable-rate notice | Affordability, credit bureau decisioning, quotation, agreement signing |
| NCA classification gate at booking | s 129 / s 130 enforcement, debt review, payment distribution agents |
| Arrears status as an output of allocation | Repossession, s 127 surrender (no day-1 secured goods) |
| Prescribed-debt stop at allocation (s 126B) | Selling debt |

Day-1 products, and the NCA category they are allowed to land in:

| Product | What servicing will book | What it will not do |
| --- | --- | --- |
| Micro / short-term | A short-term credit transaction only when regulation 39(2) is met | Treat the marketing name "micro" as the legal category |
| Unsecured personal | An unsecured credit transaction | Book it as short-term because the term is short |
| BNPL / lay-by, zero cost | A non-NCA payment plan, unless a charge exists | Invent a fee so that the NCA "applies cleanly" |
| Lay-by linked to a high-risk short-term loan | Parent and child, treated as one loan. Interest on principal minus the hold. One service fee, on the parent | Book the hold as security, or levy a second service fee |

Identity, organisations, memberships, product enrolment, roles, and mandates stay in Enigma. Servicing stores Enigma ids. It does not store a person or organisation master.

## 2. Where the money maths lives

Servicing does not calculate a cent. If the Calculation Engine is unavailable, booking, accrual, allocation, settlement quotes, and new statements fail. They are retried. There is no local fallback formula.

| Component | Owns | Does not own |
| --- | --- | --- |
| Servicing | Workflow, idempotency, agreement state, the stored legal elections, statement documents, payment intake | Interest, caps, in duplum arithmetic, allocation arithmetic |
| Calculation Engine | Deterministic money results for a versioned rule pack, given a ledger position and the agreement elections | Posting, identity, payment-rail I/O |
| Ledger | Immutable, balanced, effective-dated journals; positions; memo versus due | Whether a charge is lawful |
| Enigma | Who the parties are, and whether this caller may do this action for this organisation and product | Loan balances |

Every engine response is stored with `rule_pack_version`, `engine_version`, and a hash of the request and the response. A statement figure must be reproducible from those.

Amounts in the API are integer cents, currency `ZAR`. Dates that drive interest are civil dates in Africa/Johannesburg. Timestamps are stored in UTC as well as the civil date.

## 3. Rules actually used

Sources: the dtic consolidation of the NCA updated to Government Gazette 42649 of 19 August 2019; National Credit Regulations, 2006, as amended by GN R.1080 in Gazette 39379 of 6 November 2015 (in force 6 May 2016; NCR Circular 8 of 2016); GeN 713 in Gazette 28893, with the s 42 threshold later substituted by GN 513 in Gazette 39981 of 11 May 2016; NCR Circular 15 of 2016; *Nedbank Ltd v National Credit Regulator* [2011] ZASCA 35; *Micro Finance South Africa v National Credit Regulator* [2020] ZAGPPHC 463, 2021 (1) SA 487 (GP). No Supreme Court of Appeal decision on the MFSA point was found while writing this note.

Caps are data in the rule pack, each row carrying its gazette and effective date. The figures below are the ones those sources state. They are not compiled into servicing code as constants. A later notice replaces a row without a servicing release. The NCR's September 2024 fee-review terms of reference still quoted the 2016 rand amounts; that is not a gazette, and it is not proof that no later notice exists. Legal confirms the pack against the gazettes in force before go-live.

### 3.1 Cost of credit

Section 101(1) allows only: principal debt (the amount deferred, plus s 102 items); an initiation fee; a service fee; interest; cost of credit insurance under s 106; default administration charges; collection costs. Section 100 makes a charge outside that list, or above the permitted amount, unlawful. There is no separate "late fee" on an NCA agreement.

Section 102 lets a credit provider include an initiation fee in the principal only for an instalment agreement, a mortgage, a secured loan, or a lease, and only if the consumer was offered the chance to pay it separately and declined. The locked decisions also say a capitalised initiation fee is part of principal and a fee that is not capitalised is a section 126 charge. Those two texts are gap G2. Interest on a deferred fee that is not capitalised is L2.

### 3.2 Caps in the rule pack

From GN R.1080 Table A, for the categories day-1 can actually produce:

| Category | Maximum interest |
| --- | --- |
| Short-term credit transaction | 5% per month on the first loan, and 3% per month on subsequent loans within a calendar year |
| Unsecured credit transaction | RR + 21% per year |
| Incidental credit agreement | 2% per month |
| Credit facility, if a BNPL product is later structured as one | RR + 14% per year |
| Other credit agreement, if classification falls through | RR + 17% per year |

`RR` is the SARB repurchase rate (reg 42(1)(a)).

Short-term, regulation 39(2): a credit transaction whose deferred amount at inception does not exceed R8 000; the whole amount is repayable within six months; money is disbursed to the consumer to use at the consumer's sole discretion; it is not conditional on the credit provider paying a related person, or paying someone other than the consumer, unless the consumer introduced that condition. Pawn transactions are included. The definition does not say "unsecured".

Unsecured, regulation 39(3): the debt is not supported by any pledge or other right in property, or by suretyship or other personal security.

Initiation fee, GN R.1080 Table B, for a short-term or unsecured agreement: R165 plus 10% of the amount in excess of R1 000, never more than R1 050. Regulation 42 says the amount of the agreement for this table is the amount deferred. Regulation 43(3) still says the initiation fee may never exceed 15% of the principal debt. Both limits apply; the lower one binds. Regulation 43, as amended, also says an initiation fee is charged only when a new credit agreement is established, not on a transactional basis. Incidental credit: initiation fee nil.

Service fee: GN R.1080 sets the maximum monthly service fee at R60. Regulation 44(1) and (2) still limit an annual fee to the monthly maximum times the number of months, and limit transaction-based fees (credit facilities only, s 101(1)(c)) to that same monthly or annual ceiling. Regulation 44(4) requires pro rata where the agreement is concluded during the calendar month. *MFSA v NCR* order 2 holds that this pro rata applies to the opening month and that the fee is not required to be pro-rated in the month the agreement terminates. The operational rule is L4.

Interest maths is regulation 40, owned entirely by the Calculation Engine:

- Other than short-term: daily amount = deferred amount for the day × annual rate / days in the year. The year is 365 or the actual year, as the agreement states.
- Short-term: daily amount = deferred amount for the day × monthly rate / days in the month. The month is 30 or the actual month, as the agreement states.
- The deferred amount for the day is either the average for the day or the balance at a time of day the agreement states.
- Interest is added to the deferred amount at most once a month, not earlier than the contractual due date, except that the final month may be added on the final day (reg 40(1)).
- Section 103(3): a provider must not, before the end of a day to which an interest charge applies, require payment of that charge or debit it.
- Regulation 40(4) allows a different calculation method only if the result for a year differs by no more than 0.1% from the prescribed method. That tolerance is not permission to exceed the rate cap.
- Section 101(1)(d) requires interest to be expressed as an annual rate. Regulation 42(1)(b) requires the short-term rate to be disclosed as a monthly rate. The agreement stores both figures and the disclosure method the engine was told to use. The regulations do not state whether the annual figure is `monthly × 12` or a compounded effective rate. See Ambiguity E14.

Regulation 41: an initiation fee is not levied before approval of the application. A monthly service fee is levied at the end of the month to which it relates. It may be added to the deferred amount on the same day interest is added, not earlier.

### 3.3 In duplum

Section 103(5):

> Despite any provision of the common law or a credit agreement to the contrary, the amounts contemplated in section 101(1)(b) to (g) that accrue during the time that a consumer is in default under the credit agreement may not, in aggregate, exceed the unpaid balance of the principal debt under that credit agreement as at the time that the default occurs.

*Nedbank v NCR* order 11, which this design follows:

- the s 101(1)(b) to (g) amounts that accrue while the consumer is in default may not in aggregate exceed the unpaid principal at the time default occurred;
- once that total equals the unpaid principal, no further charges may be levied;
- a later payment during the same default does not restart those charges.

The subsection says it applies despite the common law. Servicing does not also run the common-law in duplum rule (interest stops at the capital, and starts again after a payment) on an in-scope agreement. Charges that accrued before default are outside the aggregate. They remain payable. They do not fill the cap, and they do not raise it. What counts as unpaid principal on the day default occurs is L3.

### 3.4 Payments and early settlement

Section 126:

1. The consumer may prepay any amount at any time, without notice or penalty.
2. The provider must accept a payment when it is tendered, including before the due date.
3. The provider must credit each payment as of the date of receipt, first to due or unpaid interest, second to due or unpaid fees or charges, third to principal.

Section 112(2) dates a credit on the day the consumer makes the payment. Section 112(3) allows a later adjustment. The locked value date for allocation is the system's recognition of receipt, which is the operational reading of s 126(3). See L1. A reversal uses s 112(3) to undo that allocation on the same recognition date.

Section 125(1): the consumer or a guarantor may settle at any time, with or without notice. Section 125(2): the settlement amount is the unpaid principal at that time, plus unpaid interest and all other fees and charges payable up to the settlement date, plus an early-termination charge only in the case of a large agreement. Day-1 principals are far below the large-agreement threshold, and none of the products is a mortgage, so s 125(2)(c) does not apply. Future instalments are not added. Unaccrued future interest is not added.

Section 126B: servicing must not continue collection of a debt extinguished by prescription under the Prescription Act 1969 where the consumer raises prescription, or would reasonably have raised it had they known of it. Allocation of a payment to a prescribed agreement stops for review. The payment is not applied and is not returned automatically. See the failure path in section 7.

### 3.5 Statements

Section 108(1): the provider must offer to deliver periodic statements. Section 108(2): the maximum gap is one month, except two months for an instalment agreement, a lease, or a secured loan, and six months for a mortgage. Section 108(3): the parties may agree to less frequent statements for (2)(a) or (2)(b), but not more than three months apart. A credit facility with no debit or credit in the period need not get a statement.

Section 109(1): the opening balance of a statement is the closing balance of the immediately preceding statement. Section 109(2): a small-agreement statement must be in the prescribed form. Regulation 35 prescribes Form 26 and the field list in section 8. Section 109(3): an intermediate or large agreement may use the prescribed form or a provider form that meets the prescribed requirements.

Section 110: on request, and without charge, a statement of the current balance, the movements in a requested period, the overdue amounts and when they became due, and the amounts currently payable and when they became due. Delivery is within 10 business days if the request covers a year or less, otherwise 20. Not required again if a written statement of that kind was given in the previous three months. Not required for information more than three years after the account was closed. The consumer chooses oral or written, and the channel, to the extent the provider is equipped.

Section 111: a written dispute of a debit or credit. The provider explains the entry or confirms the error and the revised entry. Enforcement on a default that arises from the disputed entry waits. Section 113: a settlement statement calculated under s 125, delivered within five business days, binding for five business days after delivery. For a credit facility the quote is not binding for later draws or charges (s 113(3)).

Section 107(2): sections 108 to 110 do not apply to an incidental credit agreement until interest is first charged.

Business days follow the Act: exclude the starting day, include the ending day, and skip Saturdays, Sundays, and public holidays. The holiday calendar is data, not a hardcoded year.

### 3.6 Size thresholds

Section 9, read with the s 7(1)(b) determination in GeN 713 (lower threshold R15 000, higher threshold R250 000):

- Small: principal debt at or below R15 000 (also a pawn, or a facility with a limit at or below R15 000).
- Intermediate: principal debt between those thresholds. A facility whose limit is above R15 000 is intermediate under s 9(3)(a). The subsection, as consolidated, does not add "and below the higher threshold" for a facility.
- Large: a mortgage, or any other credit transaction whose principal is at or above R250 000.

A short-term loan cannot exceed R8 000 and is therefore a small agreement. An unsecured personal loan at or below R15 000 is small. Above R15 000 and below R250 000 it is intermediate. Day-1 does not book large agreements. If a payload has a principal at or above R250 000, booking rejects it rather than applying the s 125(2)(c) charge, which day-1 has no signed method for.

### 3.7 Credit life

Section 106(8) allows the Minister to cap the cost of credit insurance. The cap was gazetted in Gazette 40606 of 9 February 2017, effective six months later. The NCR's February 2017 media release summarises the cap as R4.50 per R1 000 for unsecured credit and R2 per R1 000 for mortgages. The gazette table has further rows, including credit-facility utilisation and affordable housing. Public text extraction of the short-term row was garbled, so this note does not transcribe a short-term premium number. The rule pack is loaded from that gazette. Servicing sends the quoted premium to the engine and posts only a premium the engine accepts. Minimum statutory cover is an origination concern; servicing records the policy reference and the premium it was told to bill.

Default administration charges (reg 46) and collection costs (reg 47) are not levied by these flows. They are posted later by collections, into the buckets the waterfall already has, and they count toward s 103(5) if they accrue during default. Regulation 46 limits default administration charges to letters necessarily written under Part C of Chapter 6, at the magistrates' court registered-letter tariff plus reasonable delivery cost. An ordinary missed instalment does not create one.

## 4. Elections

L1 to L5 are locked. L1, L3, and L4 are platform rules. L2 and L5 are chosen per organisation, with an optional per-product override. Booking freezes the resolved set onto the agreement. Later edits to the organisation or product do not change agreements already booked. Every engine call receives the frozen set. The engine does not substitute a different value.

The subsections marked E are not locked. A recommendation there is the earlier design position. It is not in the rule pack, and the engine must not apply it, until it is locked in the same way as L1 to L5.

### L1. Value date is the system recognition date

The value date for allocation is the Africa/Johannesburg civil date on which servicing recognises the payment. That is the date of the commit that first posts the payment to unallocated receipts, unless the intake carries an explicit `recognition_date` that is not in the future. The date the consumer tendered the money is stored as `tendered_on`. It is not the value date.

A reversal removes the allocation on that same recognition date. The day the reversal message arrives is `reversed_on`. It is not a second value date.

The value date has no time of day. A loan, settlement, deposit, or payment recognised on a calendar day is treated as 00:00 on that day. A payment whose recognition date is the default flag date is included in the morning default check. The clock time of that check is not stated in the locked decisions. See the checklist.

Worked example. Short-term balance R5 000 at 5% per month, 30-day month. One day of interest is `5000 × 0.05 / 30 = R8.333…`.

| Event | Civil date | Effect |
| --- | --- | --- |
| Consumer pays R500 at a retailer | Friday 3 April 2026 | Stored as `tendered_on`. No allocation |
| Servicing posts the receipt | Tuesday 7 April 2026 | Recognition date and allocation value date. Interest has run through 7 April. The R500 is allocated on 7 April |
| Rail reverses the receipt | Wednesday 15 April 2026 | Allocation is undone with value date 7 April. 15 April is `reversed_on` only |

The four days from 3 April to 6 April are not credited as an earlier receipt. A payment recognised on 7 April does not get a value date of 3 April.

### L2. Interest on a deferred initiation fee is a provider choice

Default, when neither the organisation nor the product has a row: no interest on a deferred initiation fee. The alternative, stored per organisation or overridden per product, permits interest. That alternative is the reading in *MFSA v NCR*: regulation 39 includes the fee in the deferred amount, and regulation 40 calculates interest on the deferred amount. The fee stays out of the principal bucket on a short-term or unsecured agreement, because s 102 does not list those agreements.

Worked example. Cash advanced R5 000. Initiation fee R565. Monthly rate 5%. The fee is unpaid for a 30-day month.

| Resolved choice | Interest base | Interest for the month | Principal bucket |
| --- | --- | --- | --- |
| `no_interest` (platform default) | R5 000 | R250.00 | R5 000. Fee stays R565 |
| `interest_permitted` | R5 565 | R278.25 | R5 000. Fee stays R565 and is inside the deferred amount |

Capitalised and not capitalised are both locked treatments. If the fee is capitalised, it is part of the principal debt. If it is not, it is a due fee or charge under section 126. The same split applies to related fees. A fee capitalised before the default date sits inside the in-duplum ceiling. `interest_permitted` does not by itself capitalise the fee.

Conflict, not a rule: section 102 allows an initiation fee inside principal only for an instalment agreement, a mortgage, a secured loan, or a lease, and only if the consumer declined to pay it separately. The locked decisions do not say which day-1 products may capitalise. This note does not ban it and does not authorise it. Booking of `initiation_fee_capitalised = true` on a short-term or unsecured subsector returns 422 `unresolved_conflict` until `LOCKED_DECISIONS.md` names the products.

### E2. "Due or unpaid" before the charge may be debited

Section 126(3) takes due or unpaid interest, then due or unpaid fees. Section 103(3) and regulation 40 forbid debiting interest before the end of the day it applies to. Regulation 41(2) levies the monthly service fee at the end of that month.

Worked example. Instalment due on the 25th. On the 10th the consumer pays R1 000. Interest has accrued for ten days (R80) and has not been debited. The service fee (R60) has not been levied. Nothing is overdue.

| Option | Where the R1 000 goes | Later interest |
| --- | --- | --- |
| A. Only amounts already due | R1 000 reduces principal | Calculated on the reduced principal from the value date, using the agreement's day convention |
| B. Accrued-but-not-debited interest is "unpaid" | R80 to interest, R920 to principal | The R80 is collected before the Act allows it to be debited |

Recommendation: A, for both interest and fees, so the waterfall uses the same meaning of "due". Accrued-but-not-due interest is a memo balance. It is visible on an internal enquiry. It is not a s 126 target until the engine posts the due-debit on the contractual date. The agreement's day-count convention still determines whether the value date itself is a due day.

### E3. Order among fees

Section 126(3)(b) does not rank initiation, service, credit life, default administration, and collection costs against each other.

Worked example. All of the following are already due: service fee R60 (due 31 March), unpaid initiation R150 (due on the disbursement date, 2 March), credit-life premium R40 (due 31 March). Payment R100.

| Option | Application of R100 |
| --- | --- |
| A. Oldest due date first | Initiation R100. Service and insurance remain |
| B. Pro rata across the R250 | Initiation R60.00, service R24.00, insurance R16.00 |
| C. A published order that is not in the Act | Whichever order was published; it is a convention |

Recommendation: A. Where two fee amounts share a due date, a stable order is disclosed on the agreement and in the rule pack: unpaid initiation, service fee, credit life, default administration, collection costs. That tie-break is a convention. It is not s 126. Changing it does not change the interest-then-fees-then-principal order.

### E5. Base used to calculate the initiation-fee maximum

Table B is applied to "the amount deferred". Regulation 39's deferred amount includes the initiation fee. Section 101(1)(b) caps the fee relative to the principal debt. Using the fee inside the base that calculates the fee is circular.

Worked example, short-term or unsecured, limits R165 + 10% above R1 000, ceiling R1 050, and 15% of principal (reg 43(3)).

| Cash advanced | Table B on the cash advanced | 15% of that cash | Binding cap under option A |
| --- | --- | --- | --- |
| R800 | R165 | R120 | R120 |
| R1 000 | R165 | R150 | R150 |
| R2 000 | R165 + R100 = R265 | R300 | R265 |
| R8 000 | R165 + R700 = R865 | R1 200 | R865 |
| R20 000 unsecured | R165 + R1 900 = R2 065, cut to R1 050 | R3 000 | R1 050 |

Option B iterates the fee on (cash + fee). For R8 000 that produces a fee of R961.11 instead of R865. The difference is material.

Recommendation: A. The base is the cash advanced, which is the principal, excluding the fee being calculated. This matches s 101(1)(b) and the MFSA holding that the fee is not principal. Option B is implemented only if counsel writes it into the pack.

### VAT on the rand maxima (locked)

The rand maxima R60, R165, and R1 050 are excluding VAT. That is the default. The provider may elect inclusive. An unset election means exclusive. No example rate of VAT is introduced here.

The locked text does not say whether that election is per organisation or per product. Product-level override is not built. An organisation-level election is the reading of "provider". A disclosed value that differs from it returns 422 `election_mismatch`.

### E7. Which earlier loan makes a short-term loan "subsequent"

Table A says "5% per month on the first loan and 3% per month on subsequent loans within a calendar year." It does not say with whom.

Worked example. Consumer takes R2 000 for one month from provider A on 10 January at 5%, and R2 000 from provider A on 10 March. The March cap is 3% per month if "subsequent" means the same provider. If the March loan is instead with provider B, provider B does not have A's agreement in this LMS.

| Option | March cap at provider A | What provider B can know |
| --- | --- | --- |
| A. Same credit provider, calendar year of the agreement date | 3% | Nothing about A; B may charge 5% if B has no earlier short-term for this person in that year |
| B. Any short-term in the market | 3% | Only whatever the decision engine's bureau evidence says, which is incomplete |

Locked: a subsequent short-term loan is counted per credit-provider organisation. Regulation 42 Table A also says "within a calendar year". Section 13 of the locked decisions does not restate the year. This note does not treat that silence as a repeal of the year limb, and it does not treat the year limb as newly locked. `validate_booking` receives the prior short-term agreements of this person at this organisation, each with its agreement date. How the year limb combines with that list is gap G7 in the checklist. A loan's contractual rate does not change on 1 January.

### L4. Service fee is pro-rated only in the opening period

Pro rata applies only to the opening period, from the disbursement date up to and not including the first payment due date. After that due date the engine levies the full contractual monthly fee, including in the month of settlement. The amount charged to the consumer on any one levy is not above the contractual monthly fee and not above R60.

The opening-month fraction is inclusive days in the month, divided by the actual number of days in that month. The opening month is the period from disbursement to the first payment due. After that, the full contractual monthly fee is levied, including in the settlement month, subject to the R60 cap. The cap is excluding VAT unless the provider has elected inclusive.

No rand example is given. "Inclusive days in the month" is not defined as a date pair, and a worked amount would choose a numerator the locked text does not state. See gap G4. Rounding of the fraction, when it is billed, is half-up to cents.

### L5. Rate after a repo fall is a provider choice

Stored per organisation, or overridden per product:

| Value | Accrual after RR falls | Notice |
| --- | --- | --- |
| `contract_rate_continues` | The contractual rate continues | No s 104 notice for this fall |
| `lower_of_contract_and_cap` | The lower of the contractual rate and the statutory maximum on that day | s 104(2) notice, at least five business days, because the amount the consumer pays changes |

There is no platform default. An RR-linked product (unsecured personal, cap RR + 21%) fails booking with `election_required` until the organisation or the product has a row. A short-term monthly rate is not an RR formula. Booking stores `not_applicable` for that field, and a later fall in RR does not change the contractual 5% or 3% per month.

A fixed contractual rate never increases because RR rises. Section 104(1) still forbids that unilateral increase. An agreement priced as a margin over RR uses the variable-rate path in section 6.4, and the same stored choice caps the result when the choice is `lower_of_contract_and_cap`.

Worked example. Unsecured agreement, fixed contractual rate 24% per year. RR at booking is 7%, so the cap is 28%. The contractual rate is lawful at booking. RR later falls to 2%. The cap becomes 23%.

| Resolved choice | Rate accrued after the fall |
| --- | --- |
| `contract_rate_continues` | 24% |
| `lower_of_contract_and_cap` | 23%, and the s 104(2) notice is issued |

### E10. In duplum headroom after a payment

This one is not ambiguous in the SCA order. It is stated here because the common-law rule is the opposite and must not leak into the engine.

Worked example. Unpaid principal when the missed instalment fell due: R300. Cap on costs accruing during this default: R300. No insurance. Rate 5% per month. Service fee R60. Interest for a full month on R300 is R15. The example uses the monthly sum so the cap is visible; the engine still computes the days under regulation 40.

| Month in default | New charges | Aggregate accrued during this default |
| --- | --- | --- |
| 1 | Interest R15 + service R60 | R75 |
| 2 | R75 | R150 |
| 3 | R75 | R225 |
| 4 | R75 would meet the ceiling | The aggregate is recorded. The charge is not clipped |
| 5 | Not suppressed. The clip is off | Aggregate is recorded and is not used to zero the charge |
| Payment of R100 during month 5 | Applied by s 126. The payment does not reset the counter for this episode | Ceiling unchanged |
| 6, still in this episode | Not suppressed | Ceiling unchanged |

If that R300 already includes an initiation fee capitalised into principal before the default, the fee is inside the ceiling. A fee that was never capitalised is outside the ceiling. Charges that caused the default do not count toward the cap. Only charges that accrue during the episode do. Post-default accruals count even when a statement shows them as capitalised. A payment during the episode reduces what is owed and does not reset the counter. Clearing the arrears closes the episode. The next default snapshots a new ceiling from unpaid principal at the start of that new default. Three section 103(5) edges not decided by *Nedbank* are not named in the locked decisions. The clip stays off until counsel confirms. Servicing stores the ceiling and the aggregate and does not suppress a charge.

### L3. In-duplum base is unpaid principal at the date of first default

The base is the unpaid principal on the date that default occurs, including any initiation fee that was capitalised into principal before that date. The date is the first day of that default episode. It is not a later day inside the episode, and it is not recomputed because a payment later reduces principal.

Post-default accruals of the s 101(1)(b) to (g) amounts are charges. They increment the in-duplum aggregate. A statement may display them as capitalised into a single balance. That display does not move them into the principal bucket and does not increase the base. *Nedbank v NCR* order 11(c) still applies: once the aggregate equals the base, a payment during that same default does not restart the charges.

When the arrears are cleared, the episode ends. Section 103(5) constrains amounts that accrue "during the time that a consumer is in default", and the SCA order limits the freeze to the period "while such default persists". A later default is a new occurrence and snapshots a new base on that later date.

On a day-1 short-term or unsecured agreement the initiation fee is not capitalised into principal (L2), so the base is the unpaid cash principal. The separate initiation fee stays collectable and does not enter the base or the aggregate.

Worked example. Cash advanced R1 000 on 1 March. The instalment due 31 March is unpaid at the end of that day. `default_occurred_on` is 31 March.

| Facts on 31 March | Duplum base | April interest R50 and service fee R60 |
| --- | --- | --- |
| Initiation fee R150 was capitalised into principal before 31 March. Unpaid principal R1 150 | R1 150 | Aggregate becomes R110. Base stays R1 150. The statement may show the R110 inside the balance. The R110 remains a charge |
| L2 default: fee R150 is a separate bucket and was not capitalised. Unpaid principal R1 000. Pre-default interest of R40 is also unpaid | R1 000 | The R40 stays collectable and does not consume the cap. The April R110 consumes it. Base stays R1 000 |

Interest that regulation 40 adds to the deferred amount for the next day's calculation is an engine input. It is not a journal from the interest bucket into principal. Post-default interest therefore cannot enlarge the base by being displayed as capitalised.

### E11. Zero-cost BNPL or lay-by, and a later late fee

Section 8(4)(f) brings "any other" deferral into the Act when a charge, fee, or interest is payable. A deferral with none of those is not a credit agreement under that paragraph. A credit facility under s 8(3) has its own elements, including a charge or a pre-approved limit that may be used from time to time. A closed four-instalment lay-by of a known purchase is not, without more, a facility. Consumer Protection Act s 62 lay-by is a different statute and is not implemented by these NCA flows.

Worked example. Goods priced at R1 200. Four payments of R300. No initiation fee, no service fee, no interest, no late fee.

| Event | Classification |
| --- | --- |
| Booked as priced | `non_nca_payment_plan`. No Form 26 duty. No s 126 waterfall, because there are no interest or fee buckets. A payment reduces the outstanding instalments in the order the contract states |
| Someone later adds a R50 late fee on this plan | Rejected. A late fee is not a permitted amendment of a non-NCA plan inside servicing |
| The product is re-offered with a late charge | New agreement. It may be incidental credit. Section 5 defers full application until 20 business days after the charge is raised. Incidental initiation fee is nil. Incidental interest maximum is 2% per month. Sections 108 to 110 apply only once interest is charged (s 107(2)) |

Recommendation: book the zero-cost product as `non_nca_payment_plan`. Do not emit NCA statements for it. Do not run s 103(5) on it. The contractual receipt is still allocated through the ledger so the two products share intake, idempotency, and reversals.

### Lay-by linked to a loan (locked)

The pair is a parent and a child, and the contracts treat it as one loan. It is not security, and it is not booked as a secured loan. The child is a deposit-insurance style arrangement: the client pays for a period, then the loan is disbursed. Day-1 does not treat that as deposit-taking under the Banks Act.

Interest is calculated on the net balance, loan principal minus the lay-by hold. The locked text says this is evidence that the hold is a payment against the loan rather than a separate savings product. One monthly service fee is levied, on the parent. The client can consolidate or settle when the lay-by hold is greater than or equal to the settlement balance. A non-refundable hold described as a fee is still a prohibited charge and is rejected.

Credit life pays the loan first. The lay-by covers any shortfall. Surplus goes to the estate when the hold is a cash deposit. When it is structured as insurance, treatment follows whether a beneficiary was named. A funeral benefit is paid to the named beneficiary and leaves the loan and the lay-by as they are. Death does not apply the lay-by unless a section 124 authority was signed in life. Otherwise the lay-by stays with the estate.

Payments can be allocated across the loan and the linked lay-by. The order of that cross-allocation is not stated beyond section 126 on the loan and the net-balance interest rule. See gap G12. No second service fee is created to fill that gap.

### E14. Annual-rate disclosure on a monthly short-term rate

Section 101(1)(d) requires an annual expression. Regulation 42(1)(b) requires monthly disclosure for short-term. Neither states the conversion.

Worked example. Monthly rate 5%.

| Method | Figure stored as the annual disclosure |
| --- | --- |
| Nominal, `0.05 × 12` | 60% |
| Effective, `(1.05^12) − 1` | 79.59% |

The annual equivalent rate is disclosed. The locked decisions do not define that equivalent as `monthly × 12` or as a compounded effective rate. This note does not check the payload against either formula. See gap G14.

### Rounding (locked)

On billing, round half-up to the cent. The same rule is used everywhere a figure is rounded. Rounding must not put an instalment above the affordability figure previously aligned with the client. Where that figure is carried on the booking is not stated. See gap G15. The scale of unbilled daily accruals, before the billed debit is rounded, is not stated. See gap G15. Regulation 40(4)'s 0.1% year tolerance is not permission to exceed a cap, and it is not a second rounding rule.

### Prepayment and a late disbursement (locked)

After a partial prepayment the provider chooses whether to shorten the term or drop the instalment. The preference in the locked decisions is to keep the contractual instalment the same during the term. That preference is not a runtime default. If the choice is absent, booking fails closed.

When disbursement is later than the quote date, both of these are supported, and the agreement names which one applies. If it names neither, booking fails closed.

- Adjust the instalment from the actual disbursement date and the remaining term.
- Keep the original instalment, and either settle early or write off a small residual at contractual end. The write-off is not required when the account is already in default.

What amount counts as a small residual is not stated. See gap G16. The historical schedule is kept. A restructure, when used, creates a new instalment, price, and term. Whether that restructure is a new credit agreement is not stated. See gap G16. Fees other than interest, initiation, the monthly service fee, and credit life are a further monthly fee, fixed or variable, and are not capitalised into the schedule. Default-administration and collection-cost amounts are not levied unless a tariff row exists.

## 5. Agreement state

The status is servicing's. The engine does not set it. An open in-duplum episode, a dispute, and prescription review are flags. The episode flag does not suppress charges.

`pending_disbursement` → `active` → (`in_arrears` ↔ `active`) → `settled`

Other terminals and side states: `booking_rejected` (nothing was persisted as an agreement), `disbursement_failed` (no consumer debit for interest or fees), `rescinded` (a s 121 instruction from origination, unwound by contra journals), `prescription_review` (allocation paused).

`in_arrears` is set by the morning check on the flag date. The flag date is the contractual due date plus `leniency_days`, counted in calendar days, including weekends and public holidays. The check flags default only when the amount received for that due date is below `full_payment_threshold_percent` of the threshold instalment. That instalment is the original principal slice plus levied charges that share the due date, including the monthly service fee, a non-capitalised initiation fee, and credit life. Unbilled interest is excluded until it is debited. This exclusion is for the threshold test. It is not a section 126 rule. Section 126 order is unchanged, and gap E2 stays open.

`leniency_days` and `full_payment_threshold_percent` are per customer. If either is unset, the check and the booking fail closed. No example count of days and no example percent is a default. Leniency does not pause or reduce interest. Interest continues daily on the outstanding balance. A campaign discount stays in place through the leniency window, falls away on the flag date, and becomes the base rate. The discount does not return on a later cure. Penalty interest may not exceed the contractual interest rate. Which of the base rate and the campaign net rate is "contractual" for that sentence is gap G3.

The same default definition is used for in duplum and for collections reporting. `default_occurred_on` for a new episode is the flag date on which this check first flags the account in that episode. A payment recognised on the flag date is 00:00 that day and is visible to the check. The account returns to `active` when it is brought out of default. That cure closes the episode.

Non-NCA payment plans use `pending_disbursement` or `active`, then `settled`. They do not use `in_arrears` as an NCA default, and they do not set the duplum flag. Their contract may still mark an instalment missed. That marker must not be fed to the in-duplum calculation.

## 6. Booking

Supported sequence: validate and create `pending_disbursement`, then disburse. The decision engine must not pay the consumer before it has a 201 from the first call. A single call that says the funds have already left is accepted only when validation passes. If validation fails, servicing returns 422 and opens an ops item `unbooked_disbursement`. It does not book an unlawful agreement in order to have somewhere to put the cash.

### 6.1 Enigma port

```
get_organisation(org_id) -> legal_name, trading_names, ncr_registration_number, status
get_person(person_id) -> display_name, contact_refs, status
check_mandate(actor_id, action, org_id, product_code) -> allow or deny
get_product_enrolment(org_id, product_code) -> status, effective interval
```

Servicing calls these on the booking path and on any staff action. A payment rail is not an Enigma actor. The collection account is mapped to the organisation inside servicing, and the rail signature is checked against that account. The payload's organisation id is not trusted on a rail webhook.

Name, identity number, and service address are read from Enigma at booking and frozen on the agreement. A later change in Enigma does not rewrite them. The statement prints the frozen values. If any of the three is missing, or Enigma times out, or the status is ambiguous, booking fails closed. Email and telephone are not in the freeze list. See gap G19.

### 6.2 `POST /v1/agreements`

Caller: the decision engine, with an Enigma mandate `agreement.book` for this organisation and product. Header `Idempotency-Key`. A repeat of the same key and the same body returns the original response. The same key with a different body returns 409.

```json
{
  "decision_reference": "dec_01J0",
  "credit_provider_org_id": "org_01J0",
  "consumer_person_id": "per_01J0",
  "brand_id": "brand_01J0",
  "product_code": "short_term_v1",
  "nca": {
    "form": "credit_transaction",
    "subsector": "short_term",
    "size": "small",
    "security": "none"
  },
  "money": {
    "currency": "ZAR",
    "principal_cents": 500000,
    "initiation_fee_cents": 56500
  },
  "disclosed": {
    "initiation_fee_interest": "no_interest",
    "rate_after_repo_fall": "not_applicable"
  },
  "interest": {
    "structure": "fixed_monthly",
    "monthly_rate": "0.050000",
    "annual_rate_disclosure": "0.600000",
    "day_count": "actual_actual"
  },
  "service_fee": {
    "basis": "monthly",
    "amount_cents": 6000
  },
  "credit_life": null,
  "term": {
    "agreement_date": "2026-10-26",
    "disbursement_due_date": "2026-10-26",
    "first_due_date": "2026-11-25",
    "maturity_date": "2026-11-25",
    "instalment_cents": 583150,
    "payment_frequency": "monthly"
  },
  "prepayment_application": "reduce_term",
  "quote_disbursement_rule": "adjust_instalment",
  "initiation_fee_capitalised": false,
  "statement_election": {
    "offered": true,
    "frequency": "monthly",
    "channel": "email"
  },
  "agreement_document": { "uri": "s3://agreements/dec_01J0.pdf", "sha256": "..." },
  "linked_deposit_id": null
}
```

The normative request and response schemas are in the implementation design. The R5 000 initiation-fee figure above is lawful only if it matches Table B and regulation 43(3): R165 + 10% × R4 000 = R565, and 15% × R5 000 = R750, so R565 binds. The engine recomputes it. The sample instalment is not a servicing calculation. L4, not the caller, decides service-fee pro rata. L2 and L5 are resolved from the organisation or product and then frozen; `disclosed` must match that resolution or the call returns 422.

`POST /v1/payment-plans` is the same shape with `nca.form = non_nca_payment_plan`, fees and interest required to be zero, and no duplum fields. A non-zero charge on that endpoint is 422 with `reclassify_required`.

### 6.3 Happy path

1. Authenticate the caller. `check_mandate` and `get_product_enrolment`. Organisation and person must be active.
2. Insert the idempotency row. Lock it.
3. Check the product catalogue. `short_term_v1` may produce subsector `short_term` only. Servicing does not switch the loan to unsecured inside this product, because the organisation may not be enrolled for that product.
4. Resolve L2, L5, the VAT election, and the day-count convention, and call `CalculationEngine.validate_booking` with the frozen elections. The engine checks regulation 39, the initiation-fee caps, the service-fee cap, the resolved L5 choice, and the credit-life cap if a premium is present. Day count is `actual_actual` or `30_360`, chosen by the provider. Daily accrual is required. A 360-day year is not a separate Day-1 method beyond `30_360`. The recommendation for new products is `actual_actual`. An omitted convention fails closed, because the recommendation is not a runtime default. Zero interest and a zero fee are valid for a full term or part of a term. A campaign is stored as a base rate and a discount. The net rate is base minus discount, and it may be zero.
5. Persist the agreement as `pending_disbursement` with the rule-pack version, the frozen elections, and the engine's schedule. Do not post consumer charges yet.
6. Return 201 with `agreement_id` and `status`.

Disbursement, `POST /v1/agreements/{id}/disbursements`:

```json
{
  "mode": "confirm",
  "consumer_receipt_date": "2026-10-26",
  "provider_settlement_date": "2026-10-26",
  "amount_cents": 500000,
  "rail_reference": "eft_01J0",
  "destination_account_ref": "acct_01J0"
}
```

`mode = instruct` tells the payments service to pay the consumer and waits for a later `confirm`. On `confirm`:

1. Lock the agreement. It must be `pending_disbursement`, and the amount must equal `principal_cents`.
2. Ledger journals, in one transaction: principal receivable against disbursement clearing for the cash advanced. If the initiation fee is deferred, a separate initiation-fee receivable against the contra account the ledger chart maps (income or deferred income is a ledger policy, not an NCA rule). No service fee and no interest on the disbursement event itself.
3. Engine `on_disbursement` returns any memo that starts the next day's interest base. Servicing posts only that.
4. Status becomes `active`. The first statement period opens. Its opening balance is the principal plus any deferred initiation fee that has been levied, reported as separate lines, not as one blended principal. Section 109's "balance" on the Form 26 summary is the total outstanding. The transaction list shows the components.

### 6.4 Failure paths

| Condition | Result |
| --- | --- |
| Mandate denied, enrolment inactive, person or organisation unknown | 403 or 404. Nothing is booked |
| Idempotency key reused with a different body | 409 |
| Subsector does not match the product, amount above R8 000, term over six months, disbursement not to the consumer, second same-provider short-term loan priced at 5% | 422 `classification_rejected` or `cap_exceeded`, with the engine's rule id. No silent reclassification |
| Initiation fee above the lower of Table B and 15% | 422 `initiation_fee_cap` |
| Disclosed L2 or L5 value differs from the resolved organisation or product policy | 422 `election_mismatch` |
| RR-linked product and neither organisation nor product has an L5 row | 422 `election_required` |
| Size would be large | 422 `out_of_day1_scope` |
| Deposit linked as a non-refundable fee | 422 `prohibited_charge` |
| Engine timeout | 503. Idempotency row stays in progress so a retry does not double-book |
| `confirm` amount differs from principal | 422. Agreement stays `pending_disbursement` |
| Rail reports payment failed after `instruct` | Status `disbursement_failed`. Contra any journals. No interest |
| `confirm` arrives for an agreement that failed validation and was never created | 404, plus the ops item if the caller sets `funds_already_sent: true` |

Variable rate, when the agreement is `fixed_margin_over_rr` rather than fixed. A reference-rate feed supplies the new RR. The engine applies the frozen L5 choice and returns the new rate. Servicing stores it and, when the rate changes, sends the s 104(3) notice no later than 30 business days after the change takes effect, with the content regulation 36 requires: the effective date, and the rand interest if ascertainable. A fixed-rate agreement whose L5 choice is `lower_of_contract_and_cap` uses the five-business-day notice in s 104(2) when a fall in RR reduces the rate the consumer pays. `contract_rate_continues` leaves the fixed rate unchanged and sends no notice for that fall. Notice delivery is an outbox record. Failure to deliver retries. It does not roll back a rate the engine has already returned.

Section 121 rescission is an instruction from origination, `POST /v1/agreements/{id}/rescission`. Servicing does not decide if the section applies. If origination says it applies, servicing unwinds disbursement and fees with contra journals dated on the rescission value date and sets `rescinded`.

## 7. Payment ingestion and allocation

### 7.1 Intake

`POST /v1/payments`

Rails for day-1: DebiCheck collection result, EFT credit, PayShap, retail cash (Pay@ or an equivalent aggregator), and a staff capture under an Enigma mandate `payment.capture`. Staff capture is not a silent adjustment. It is an intake with an actor id.

```json
{
  "source": "debicheck",
  "source_event_id": "evt_01J0",
  "collection_account_ref": "cpacc_01J0",
  "amount_cents": 50000,
  "currency": "ZAR",
  "tendered_on": "2026-10-24",
  "recognition_date": "2026-10-26",
  "instrument": "debicheck_collection",
  "mandate_reference": "man_01J0",
  "agreement_id": "agr_01J0",
  "payer_reference": "AGR01J0"
}
```

Uniqueness is `(organisation, source, source_event_id)`. A duplicate success event returns the original allocation. A reversal is a different event type, never a negative amount on this endpoint.

The collection account resolves the organisation. A payload organisation id that disagrees is 422.

Provisional rail states (`submitted`, `tracking`) are stored and not allocated. Allocation starts on `success`. Every rail that can later dispute a success uses the reversal path. DebiCheck is not treated as irreversible.

### 7.2 Happy path

1. Verify the signature. Resolve the organisation from the collection account. Insert intake as `received`.
2. Post the suspense journal: bank (or clearing) against unallocated receipts. The value date is the recognition date from L1. If the ledger cannot post it, return 503 and let the rail retry. Do not acknowledge acceptance before the suspense journal exists. That commit is the recognition of receipt for s 126(2) and s 126(3).
3. Lock the agreement. If `agreement_id` is missing, match `payer_reference` or the DebiCheck mandate to one agreement. Zero matches or more than one match: leave the funds unallocated, set intake `unapplied`, emit `payment.unapplied`, return 202. Do not split across agreements. There is no statutory cross-agreement order to invent.
4. If the prescription flag is set, do not allocate. Intake stays `prescription_review`.
5. Engine `prepare(agreement, value_date = recognition_date, elections)`. It returns the due buckets after posting any charges that become due on that recognition date, the memo accruals, and the duplum flag. Servicing posts those due-debits first, in the same transaction as the allocation, so the waterfall sees them.
6. Engine `allocate(amount, due_buckets, elections)`. It returns lines that sum to the payment. Servicing checks the sum, checks that the order is interest, then fees, then principal, checks that no line exceeds the due bucket, and checks that principal is not driven negative. A surplus above the s 125 settlement amount is a separate surplus line, not principal and not future interest.
7. Ledger: debit unallocated, credit the buckets, value date = recognition date. One transaction, one idempotency key. `tendered_on` is stored on the intake row and is not a journal date.
8. Engine `position_after` returns arrears, duplum flag, and a revised schedule if principal was prepaid. Servicing updates status and stores the schedule version.
9. Return 200 with the lines. Emit `payment.allocated`.

Worked happy path, using E2 and E3 and a payment that arrives when amounts are already due. Position on the value date, before the payment:

| Bucket | Due |
| --- | --- |
| Interest | R200 |
| Service fee | R60 |
| Initiation fee | R0 |
| Principal | R5 000 |

Payment R500.

| Order | Bucket | Amount |
| --- | --- | --- |
| 1 | Interest | R200 |
| 2 | Service fee | R60 |
| 3 | Principal | R240 |

Principal becomes R4 760. A payment of R150 on the same position goes entirely to interest. Fees and principal are untouched, and the agreement stays in default.

A payment large enough to clear every due bucket and the principal is a settlement. The engine's settlement figure for that value date must equal the sum of those buckets. Any cents above it post to customer surplus, which is a liability. Surplus is refunded by `POST /v1/agreements/{id}/refunds` under mandate `payment.refund`. It is not taken as a fee.

Applying a lay-by deposit is the same endpoint with `source = deposit_appropriation` and a value date. It is rejected unless the cession's condition is recorded as met. The deposit liability and the loan receivable move in one ledger transaction.

Non-NCA plans skip steps 5 and 6's waterfall. The engine returns a contractual instalment application. Surplus is still surplus.

### 7.3 Reversal and replay

`POST /v1/payments/{id}/reversals` with the rail's reversal event id.

1. Lock the agreement.
2. Engine `replay` from the original recognition date, without that payment, over every later event. The engine is pure. Given the same journals and the frozen elections it returns the same journals.
3. Ledger posts the reversal and the replacement journals atomically. The reversal's value date is the original recognition date (L1), with a link to the reversal event. `reversed_on` is the civil date the reversal was processed.
4. A statement already delivered is not edited. If the replay changes a figure inside a delivered period, the next statement opens with the old closing balance (s 109) and shows an adjustment line (s 112(3)). The statement row is flagged `affected_by_replay` for operations. A statement not yet delivered is regenerated.

An unpaid DebiCheck after a `success` uses this path. A `tracking` event that never succeeded has nothing to reverse.

Backdated intake: a payment whose recognition date is earlier than a payment already allocated to the same agreement does not allocate on top. It triggers the same replay from that earlier recognition date. The lock serialises allocations per agreement. Order of work is recognition date, then intake time.

### 7.4 Other failure paths

| Condition | Result |
| --- | --- |
| Unknown reference | 202, funds remain unallocated. A later `POST /v1/payments/{id}/apply` with an agreement id runs the happy path from step 3. Mandate `payment.apply` required for staff |
| Amount zero, wrong currency, or success event for a different organisation's account | 422, no journal |
| Engine allocate result fails the sum or order check | No allocation journal. Intake stays `suspense`. Alert `allocation_invariant`. The payment is not returned automatically |
| Ledger commit fails after suspense was posted | Intake `allocation_pending`. Retry the allocate transaction. Suspense is not posted twice |
| Consumer dispute on a prior fee (s 111) | Allocation of a new payment continues for undisputed due amounts. Enforcement that depends on the disputed entry is blocked. The dispute does not reorder s 126 |
| Payment during duplum freeze | Allocated normally. The engine's `prepare` levies nothing new while the freeze holds |
| Quote binding window | A settlement payment inside the five business days of a delivered s 113 quote is allocated to the quoted figure if the quote's value date and the payment's value date match the quote rules. A credit facility quote does not bind later draws (s 113(3)). Outside the window, the engine recalculates. Day-1 credit transactions are bound by the quote for those five business days |
| Prescription flag | 202 `prescription_review`. No allocation, no automatic refund |

Section 126(2) requires the provider to accept the payment even when the reference is unknown. Acceptance is the suspense journal. Acceptance is not application.

## 8. Statements

### 8.1 What is generated

| Document | Duty | When |
| --- | --- | --- |
| Periodic statement | s 108, s 109, reg 35 for a small agreement. One document per client, with a section per loan | Gap cannot exceed the s 108 maximum. No separate document per loan |
| Balance enquiry | s 110 | On request, free, inside the business-day limits |
| Settlement quote | s 113, calculated under s 125 | On request, free, within five business days, binding for five business days |
| Dispute outcome | s 111 | After a written dispute |

The periodic statement is the one with a PDF. An s 110 response can be oral or a shorter writing; if it is written it is stored, and it does not replace the periodic statement's opening and closing chain.

Booking rejects an NCA agreement with `statement_election.offered` false. The Act requires the offer. One statement is issued per client and shows all of that client's loans. It is not one document per loan. Section 109 still requires each loan's opening balance to equal that loan's previous closing balance, so the document carries a section per agreement. Whether "client" means the person inside one credit-provider organisation, or the person across organisations, is not stated. See the checklist. The lay-by pair is one loan, so it is one section, not a secured-loan statement interval.

Payment frequencies that must be supported are weekly, fortnightly, monthly, quarterly, bi-annual, and annual. The locked list has no `single` value. A one-instalment short-term loan has no frequency token in that list. See the checklist. A non-NCA plan uses a contractual receipt, not Form 26.

### 8.2 Generation

Scheduler, or `POST /v1/agreements/{id}/statements` for a forced run. One statement per agreement per period, idempotent on `(agreement_id, period_end)`.

1. Lock the agreement. Engine `accrue_to(period_end)` returns the due-debits that fall on or before the period end, including the month-end service fee and the interest debit regulation 40 allows on that date. Post them.
2. Read the previous statement's `closing_total_cents`. That is this statement's opening total. The first statement's opening total is the total outstanding immediately after disbursement confirmation.
3. Ledger `movements(period_start, period_end)` in value-date order.
4. Engine `statement_figures` returns the regulation 35 totals, the outstanding balance, arrears, the rate to print, the instalment, and a component breakdown. Servicing checks that opening plus signed movements equals closing, and that the totals equal the sum of the lines in each regulation 35 category. A mismatch stops publication and raises `statement_invariant`.
5. Render the PDF. Store it in the document store. Store the row: period, opening, closing, figures, engine hashes, PDF hash, delivery status.
6. Deliver on the elected channel. Record the attempt. A failed delivery retries. The statement row is not deleted. Section 108's timing is about issuing; the issue timestamp is the moment the statement is generated and offered, and the delivery attempts are kept so a dispute about non-receipt is answerable.

Delivered PDFs are immutable. Replay after delivery is handled by the next statement's adjustment line, as in section 7.3.

### 8.3 PDF outline

Small agreements use Form 26. This outline is the regulation 35 field list, in reading order. It is not a redraw of the gazette form. The graphic layout of Form 26 is taken from the gazette artwork before go-live, not from this note.

1. Credit provider. Legal name and NCR registration number come from Enigma, not from the brand skin. Then trading name, physical address, postal address, telephone, and the bank account the consumer should pay (bank name, account number, branch code, payment reference).
2. Consumer. Name, agreement reference, address as at the statement date.
3. Statement date. Period start and period end.
4. Agreement summary, repeated per loan inside the client document. Principal debt. The annual equivalent rate as stored, with no formula added by servicing. For short-term, the monthly rate as well. A campaign shows the base rate and the discount. Instalment amount and frequency. Balance outstanding. Whether the account is in arrears, and the arrears amount. Name, identity number, and service address are the frozen booking values.
5. Period totals, each a debit or a credit as regulation 35(f) lists them: payments received; fees levied; interest accrued; insurance costs levied; collection costs levied; default administration costs levied; legal fees incurred. Legal fees and collection costs are shown even when they are zero, so the form does not depend on whether collections has posted anything.
6. Transaction list. Opening balance, carried from the previous closing balance. Then each movement: date, description, amount, debit or credit, running total. Closing balance.
7. Component closing balances, so a reader can see principal, initiation, service, interest, insurance, and surplus separately. This is additional to Form 26. If counsel decides Form 26 must be the only content on a small-agreement statement, this block is moved to the s 110 extract and dropped from the Form 26 PDF. It is not dropped from the stored figures.
8. How to dispute an entry (s 111), and how to ask for a settlement amount (s 113), including the address or channel those notices use.

Intermediate agreements on day-1 use this same document. Section 109(3) allows a provider form. Using the small-agreement form as a superset is a choice, and legal confirms it meets the prescribed requirements for intermediate agreements. Brand colour and logo are the only white-label variation. The NCR number and the legal name do not vary by brand.

### 8.4 Enquiry, quote, dispute

`POST /v1/agreements/{id}/balance-enquiries` with the requested period and the channel the consumer directed. Response within 10 or 20 business days as s 110(2) states. If a written response of the same kind was sent within three months, the API returns that response's id and does not generate a second one, unless the new request asks for a period the previous one did not cover. Requests for a period ending more than three years after closure return 422 `retention_limit`.

`POST /v1/agreements/{id}/settlement-quotes` with `settlement_date`. The engine returns the s 125 breakdown: unpaid principal, unpaid interest to that date, each unpaid fee to that date, early-termination charge (always zero on day-1, and rejected if the agreement is large), and the total. No future instalments. The response records `delivered_at` and `binding_until` (five business days after delivery, skipped over weekends and holidays).

Worked quote. Settlement date 15 April. Not a large agreement.

| Component | Amount |
| --- | --- |
| Unpaid principal | R12 000 |
| Unpaid interest to 15 April | R180 |
| Unpaid service fee already due | R60 |
| Unpaid initiation fee | R200 |
| Early-termination charge | R0 |
| Settlement amount | R12 440 |

A payment of R13 000 on that value date, inside the binding window, allocates R12 440 to those buckets and R560 to surplus.

`POST /v1/agreements/{id}/disputes` with the statement id, the line id, and the consumer's notice. Status `open`. Enforcement jobs read this flag. The explanation or the correction is a staff action under mandate `statement.dispute_resolve`, and it is either a narrative linked to the line or a ledger adjustment from the engine. Closing the dispute stores the written outcome s 111(2) requires.

## 9. Call sequence

The three calls are always in this order inside one agreement lock: engine prepares the figures, servicing checks the invariants, ledger commits. The engine never posts. The ledger never recalculates.

```
Decision engine          Servicing                 Enigma        Calculation Engine     Ledger
      |  POST /agreements     |                      |                  |                  |
      |---------------------->| check_mandate        |                  |                  |
      |                       |--------------------->|                  |                  |
      |                       | validate_booking     |                  |                  |
      |                       |---------------------------------------->|                  |
      |                       |  cap result + schedule                   |                  |
      |                       |<----------------------------------------|                  |
      |  201 pending          |                      |                  |                  |
      |<----------------------|                      |                  |                  |
      |  POST .../disbursements confirm              |                  |                  |
      |---------------------->| on_disbursement      |                  |                  |
      |                       |---------------------------------------->|                  |
      |                       | post principal + initiation fee         |                  |
      |                       |---------------------------------------------------------->|
      |  200 active           |                      |                  |                  |
      |<----------------------|                      |                  |                  |

Rail  POST /payments
      |---------------------->| suspense journal     |                  |                  |
      |                       |---------------------------------------------------------->|
      |                       | prepare(value date)  |                  |                  |
      |                       |---------------------------------------->|                  |
      |                       | allocate             |                  |                  |
      |                       |---------------------------------------->|                  |
      |                       | check sum and order  |                  |                  |
      |                       | post allocation      |                  |                  |
      |                       |---------------------------------------------------------->|
      |  200 lines            |                      |                  |                  |
      |<----------------------|                      |                  |                  |

Scheduler
      |  accrue_to(period_end)|                      |                  |                  |
      |---------------------->|---------------------------------------->|                  |
      |                       | post due debits + read movements        |                  |
      |                       |---------------------------------------------------------->|
      |                       | statement_figures    |                  |                  |
      |                       |---------------------------------------->|                  |
      |                       | PDF + s 109 chain    |                  |                  |
```

Engine operations servicing will call:

| Operation | Inputs | Output servicing relies on |
| --- | --- | --- |
| `validate_booking` | Payload, elections, prior same-provider short-term ids, rule pack | Accept or reject with rule ids; schedule; classified subsector and size |
| `on_disbursement` | Agreement, disbursement civil date | Journals to levy the deferred initiation fee, if any; interest base for the next day |
| `prepare` | Agreement, ledger position, recognition date, frozen elections | Due-debits that fall on that date; memo accrual; duplum flag; duplum base if this date is the first day of default |
| `allocate` | Amount, due buckets, elections, settlement total | Lines in s 126 order, plus surplus; lines sum to the amount |
| `settlement_quote` | Agreement, position, settlement date | s 125 components and total |
| `statement_figures` | Agreement, movements, previous closing | Regulation 35 totals, arrears, rates to print, component closings |
| `replay` | Agreement, events from a value date, elections | Replacement journal set for that suffix |
| `on_rate_change` | Agreement, frozen L5 choice, new RR, date | New rate and the consumer debit difference. No change when L5 is `contract_rate_continues` on a fixed rate, or when the cap is not RR-linked |

Ledger operations:

| Operation | What it guarantees |
| --- | --- |
| `post` | Balanced journals, idempotency key, value date and cash date both stored, memo versus due is a property of the account |
| `position` | Balances by bucket as at a value date, after all committed journals with that value date |
| `movements` | The statement lines for a period, in value-date order |
| `reverse_and_replace` | Atomic contra plus new journals for a replay, linked to the cause |

Buckets the chart must provide, and which servicing will refuse to merge:

`principal`, `initiation_fee`, `service_fee`, `interest_due`, `interest_accrued_memo`, `credit_life`, `default_admin`, `collection_cost`, `customer_surplus`, `unallocated_receipts`, `duplum_base` (memo, set once per default), `duplum_accrued` (memo). Bank and disbursement clearing are ledger accounts servicing names on the instruction. A non-NCA plan uses `instalment_receivable`, `customer_surplus`, and `unallocated_receipts` only.

Invariants the ledger may enforce because they are structural, not a second calculation: journals balance; a `post` is idempotent; principal, fee, and interest accounts are distinct. Invariants servicing checks because they are statutory: allocation order; no charge posted that the engine did not emit; duplum memo does not exceed duplum base; statement opening equals the previous closing.

## 10. Dependencies

Calculation Engine:

- Versioned rule pack with gazette and effective date. L1, L3, and L4 are platform rules in that pack. L2 defaults to `no_interest` only when the agreement snapshot says so. L5 has no engine-side default: a missing value on an RR-linked agreement is a reject.
- Daily accrual, `actual_actual` or `30_360` as frozen on the agreement, and half-up to cents on billing. Unbilled scale is gap G15. The opening-month service-fee numerator is gap G4 and is not given a fixture amount.
- Short-term versus unsecured classification from regulation 39, not from the product name.
- In duplum exactly as *Nedbank v NCR* order 11, with the base defined by L3.
- Settlement as s 125(2), with a zero early-termination charge unless the agreement is large, which day-1 rejects at booking.
- Deterministic `replay`.
- Credit-life cap from Gazette 40606, transcribed from the gazette rather than from the media release.

Ledger:

- Effective-dated, immutable journals and atomic replay.
- Memo balances that are not "due" for the waterfall, distinct from due balances. Without that split, E2 cannot be implemented.
- The buckets in section 9 kept separate. Post-default interest and fees stay out of `principal`, so a statement line that displays them as capitalised cannot inflate `duplum_base`. A pre-default initiation fee enters `principal` only when the frozen election capitalises it.
- A position read that is repeatable inside the agreement lock (snapshot isolation or the equivalent).

Enigma, to be confirmed against the private repository:

- Stable ids for organisation, person, membership, product enrolment, and mandate checks.
- NCR registration number and legal name as facts servicing may print.
- A way to resolve the decision-engine service principal to a mandate on a specific organisation and product.

Platform:

- Aurora PostgreSQL, one transactional write for the intake row plus the ledger journals that belong to it. Row-level security by organisation id.
- Outbox for statement delivery, s 104 notices, and `payment.unapplied`.
- South African public-holiday calendar.
- SARB repo-rate feed, dated, so a past accrual uses the RR that was in force on that day.
- Document store for PDFs and the signed agreement, content-addressed.

Origination, which this design consumes and does not build:

- A concluded agreement document and a statement-delivery offer.
- Disclosure of the L2 and L5 choices that the organisation or product has stored, where the agreement must show them.
- A guarantee that money is not disbursed before `POST /v1/agreements` returns 201.

## 11. What remains unsigned

The 28 October 2026 lock closed the earlier open points on memo allocation (§8), fee-bucket order (§8), the opening-month numerator (§9), the calendar-year limb of a subsequent short-term loan (§13), the annual-equivalent formula (§17), Day-1 non-capitalisation (§2), and the statement key (§12: one statement per client per credit-provider organisation, with each loan's own balance chain).

Gaps that are still open are listed in [implementation-note.md](implementation-note.md). They are not given a servicing default. The in-duplum clip stays off (§7).
