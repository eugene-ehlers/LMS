# Primary servicing flows

Design note for the post-origination LMS. Date of the sources checked: 26 October 2026 (Africa/Johannesburg).

This note specifies how servicing books an activated agreement, takes payments, allocates them, and produces statements. It also specifies the calls servicing makes into the Calculation Engine and the Ledger. It does not design those two components. It states the contracts they must honour so that servicing can enforce the National Credit Act 34 of 2005 (NCA) without re-implementing them.

Enigma (`eugene-ehlers/enigma`) was not readable from this workspace. The Enigma calls below are the consumer port servicing needs. They are not a claim about Enigma's current API.

No NCA rule is invented below. Where the Act, the regulations, a judgment, and an NCR circular do not settle a point, the point is marked **Ambiguity** and given options with worked numbers. A recommendation is an implementation default for the rule pack, not a statement of law. Counsel signs each election before the rule pack is activated. The agreement stores the election ids that were in force when it was booked.

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
| Lay-by held as security for a high-risk short-term loan | Two linked records: a zero-cost deposit, and a credit agreement classified on its own facts | Net the deposit into principal, or treat the deposit as a fee |

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

Section 102 lets a credit provider include an initiation fee in the principal only for an instalment agreement, a mortgage, a secured loan, or a lease, and only if the consumer was offered the chance to pay it separately and declined. Day-1 unsecured and short-term agreements are not in that list. A deferred initiation fee on those products stays in its own bucket. See Ambiguity E4.

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

Service fee: GN R.1080 sets the maximum monthly service fee at R60. Regulation 44(1) and (2) still limit an annual fee to the monthly maximum times the number of months, and limit transaction-based fees (credit facilities only, s 101(1)(c)) to that same monthly or annual ceiling. Regulation 44(4), added by GN R.1080: a service fee is charged for a calendar month in which it is due, and on a pro rata basis where the agreement was concluded during that calendar month. The retrieved text of 44(4) stops there. It does not define the pro rata fraction, and it does not mention the month in which the agreement ends. See Ambiguity E8.

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

The subsection says it applies despite the common law. Servicing does not also run the common-law in duplum rule (interest stops at the capital, and starts again after a payment) on an in-scope agreement. Charges that accrued before default are outside the aggregate. They remain payable. They do not fill the cap, and they do not raise it. See Ambiguity E13 for what "principal debt" includes once interest has been capitalised into the deferred amount.

### 3.4 Payments and early settlement

Section 126:

1. The consumer may prepay any amount at any time, without notice or penalty.
2. The provider must accept a payment when it is tendered, including before the due date.
3. The provider must credit each payment as of the date of receipt, first to due or unpaid interest, second to due or unpaid fees or charges, third to principal.

Section 112(2): a credit takes effect on the date the consumer makes the payment, or otherwise earns the credit. Section 112(3) allows a later adjustment so the account reflects the legal obligations. Section 112(2) and s 126(3) do not use the same date. See Ambiguity E1.

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

## 4. Ambiguities

Each election is stored on the agreement. The engine receives the election; it does not choose a different one per call.

### E1. Value date: s 112(2) versus s 126(3)

Section 112(2) credits the account on the date the consumer makes the payment. Section 126(3) credits it as of the date of receipt.

Worked example. The consumer pays R500 at a retailer on Friday 3 April. The credit provider's account is credited on Tuesday 7 April. The short-term balance that morning is R5 000 at 5% per month, and the agreement uses a 30-day month. One day's interest on R5 000 is `5000 × 0.05 / 30 = R8.333…`. Four days is about R33.33, before rounding.

| Option | Interest value date | Cash date | Effect in the example |
| --- | --- | --- | --- |
| A | 3 April, the day the consumer paid | 7 April | Consumer is not charged for the rail's float |
| B | 7 April, the day funds are received | 7 April | Literal "date of receipt"; consumer bears about R33 |
| C | 7 April, unless the agreement defines receipt as the collection agent | 7 April | Depends on a sentence in the agreement |

Recommendation: A. Store both civil dates on every intake. The engine accrues and allocates on `consumer_payment_date`. The ledger's bank leg uses `receipt_date`. The float stays with the provider. Counsel confirms this before the pack is activated, because it prefers s 112(2) where the two sections differ.

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

### E4. Interest on a deferred initiation fee

NCR Circular 15 of 2016 says that on an unsecured or short-term loan the deferred initiation fee is shown separately and does not bear interest. The circular says it is not a binding ruling. *MFSA v NCR* held that regulation 39(1) includes the initiation fee in the deferred amount and regulation 40 calculates interest on the deferred amount, so a deferred fee may bear interest, and that s 102 only stops the fee being folded into principal. The judgment is a single-judge Gauteng decision marked not reportable.

Worked example. Cash advanced R5 000. Initiation fee R565 (see E5 for the cap arithmetic). Monthly rate 5%, 30-day convention, fee unpaid for a full 30-day month.

| Option | Interest base for the month | Interest for the month | Principal bucket |
| --- | --- | --- | --- |
| A. Circular 15 | R5 000 | R250.00 | R5 000. Fee stays R565, no interest on it |
| B. MFSA | R5 565 | R278.25 | R5 000. Fee stays R565, and it is inside the deferred amount |

Recommendation: no platform default. `initiation_fee_treatment` is required when the fee is deferred: `deferred_separate_no_interest` or `deferred_separate_with_interest`. The provider's signed election is copied onto the agreement. Absent the field, booking returns 422. In both options the fee is not principal, so it is not the s 103(5) base and it is a fee for s 126.

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

### E6. VAT and the rand maxima

The regulations state rand maxima. They do not say "exclusive of VAT".

Worked example. Contractual service fee at the maximum, R60.

| Option | Consumer is debited | Provider's VAT position |
| --- | --- | --- |
| A | R60, of which the provider accounts for VAT if the fee is taxable | The cap is the amount the consumer pays |
| B | R60 plus VAT (R69 at 15%) | The cap is treated as ex-VAT |

Recommendation: A, until counsel says the cap is exclusive. Interest is a separate tax question and is not used to answer it. The engine rejects a fee which, as charged to the consumer, exceeds the prescribed rand amount.

### E7. Which earlier loan makes a short-term loan "subsequent"

Table A says "5% per month on the first loan and 3% per month on subsequent loans within a calendar year." It does not say with whom.

Worked example. Consumer takes R2 000 for one month from provider A on 10 January at 5%, and R2 000 from provider A on 10 March. The March cap is 3% per month if "subsequent" means the same provider. If the March loan is instead with provider B, provider B does not have A's agreement in this LMS.

| Option | March cap at provider A | What provider B can know |
| --- | --- | --- |
| A. Same credit provider, calendar year of the agreement date | 3% | Nothing about A; B may charge 5% if B has no earlier short-term for this person in that year |
| B. Any short-term in the market | 3% | Only whatever the decision engine's bureau evidence says, which is incomplete |

Recommendation: A for the check this LMS can actually perform. The engine counts short-term agreements on this platform for the same Enigma person and the same Enigma organisation whose agreement date falls in that calendar year, excluding agreements that never disbursed. The decision engine may send the ids it relied on; the engine recomputes from the ledger of bookings and ignores a higher rate. A 5% rate on a subsequent same-provider loan is a 422. Option B is not enforceable here without treating bureau data as fact. If counsel requires B, the payload must include the evidence, and the agreement stores it.

The rate is fixed at inception for a fixed-rate agreement. A loan booked in December at 5% does not become 3% in January.

### E8. Service fee in the inception month and the exit month

Regulation 44(4) requires pro rata for the calendar month in which the agreement is concluded. It does not, in the text retrieved, require pro rata for the month of settlement, and it does not define the fraction.

Worked example. Agreement concluded 15 January, settled 15 February. Contractual monthly service fee R60. January has 31 days.

| Month | Option | Amount |
| --- | --- | --- |
| January | Actual days from the 15th to the 31st, inclusive, 17/31 × R60 | R32.90 |
| January | Half month | R30.00 |
| February | Full fee, because 44(4) does not mention settlement | R60.00 |
| February | Same day-count method, 15/28 × R60, by analogy | R32.14 |

Recommendation: the agreement states `actual_days_in_month` for the inception month, counting from the disbursement date to the end of that month, inclusive, over the actual number of days in that month. The same fraction method is used for the settlement month, as a consumer-protective policy, and the agreement says so. That exit-month pro rata is a policy. It is not a sentence in the retrieved regulation 44(4). A provider who wants the full exit month must send that election and have counsel sign it. Rounding of the pro rata amount is the engine's published rounding rule (E15).

### E9. A fixed contractual rate after RR moves

Section 101(1)(d)(ii) and s 100(1)(c) prohibit interest above the applicable maximum. Section 104(1) prohibits a unilateral increase except for a variable rate. NCR Circular 8 of 2016 says the 2016 fee review is not retrospective. A moving RR is not the same thing as that review.

Worked example. Unsecured agreement, fixed contractual rate 24% per year. Cap is RR + 21%. RR at booking is 7%, so the cap is 28%. The contractual rate is lawful at booking. RR later falls to 2%. The cap becomes 23%.

| Option | Rate accrued after the fall |
| --- | --- |
| A. Cap tested at inception only | 24%, which is then above the formula |
| B. Continuing ceiling | min(24%, 23%) = 23%, and a s 104 notice is sent because the amount the consumer pays changed |

Recommendation: B. The engine accrues at most the cap in force on that day. A fixed rate never increases. A reduction is notified under s 104(2) (at least five business days) when it is a change to a fixed contractual charge, and the variable-rate path in section 6.4 is used when the agreement itself is priced as RR plus a margin. Counsel confirms B, because Circular 8 shows that "not retrospective" is the Regulator's approach to a regulation change, and a falling RR is not that event.

### E10. In duplum headroom after a payment

This one is not ambiguous in the SCA order. It is stated here because the common-law rule is the opposite and must not leak into the engine.

Worked example. Unpaid principal when the missed instalment fell due: R300. Cap on costs accruing during this default: R300. No insurance. Rate 5% per month. Service fee R60. Interest for a full month on R300 is R15. The example uses the monthly sum so the cap is visible; the engine still computes the days under regulation 40.

| Month in default | New charges | Aggregate accrued during this default |
| --- | --- | --- |
| 1 | Interest R15 + service R60 | R75 |
| 2 | R75 | R150 |
| 3 | R75 | R225 |
| 4 | R75 | R300, then frozen |
| 5 | R0 | R300 |
| Payment of R100 during month 5 | Applied by s 126 to unpaid interest, then fees. No new charge | Stays frozen |
| 6, still in default | R0 | R300 |

The initiation fee levied at disbursement is not in the R300. It accrued before default. If the consumer later pays everything that is overdue, the default ends and the freeze ends. A later default takes a new base equal to the unpaid principal at that new default. The amounts that accrued during the first default are not refunded.

### E13. What the in-duplum base is made of

Section 103(5) uses "the unpaid balance of the principal debt … as at the time that the default occurs." Section 101(1)(a) defines principal as the amount deferred plus s 102 items. Regulation 39's deferred amount includes fees and interest once they are deferred. Regulation 40 adds interest to the deferred amount monthly. If "principal" for the cap follows that expanded deferred amount, capitalised interest enlarges the cap.

Worked example. Cash advanced R1 000. Before any default, one month's interest of R50 is added to the deferred amount for the next interest calculation. The consumer then misses a payment. Unpaid cash principal is R1 000. Unpaid interest is R50.

| Option | Cap for this default | What a payment does to the base |
| --- | --- | --- |
| A | R1 000 | Later principal reductions do not shrink the cap. The text fixes it at the time default occurs. Capitalised interest is not principal |
| B | R1 050 | The cap grows by the interest that was capitalised before default, and can grow again if interest capitalised during default is treated as principal |

Recommendation: A. The ledger never journals interest into the principal bucket. "Added to the deferred amount" is an input the engine uses when it calculates the next day's interest. It is not a reclassification. The duplum base is the principal bucket at the start of default, and it is stored as a memo that does not change until that default ends. Pre-default unpaid interest stays collectable and does not consume the cap.

### E11. Zero-cost BNPL or lay-by, and a later late fee

Section 8(4)(f) brings "any other" deferral into the Act when a charge, fee, or interest is payable. A deferral with none of those is not a credit agreement under that paragraph. A credit facility under s 8(3) has its own elements, including a charge or a pre-approved limit that may be used from time to time. A closed four-instalment lay-by of a known purchase is not, without more, a facility. Consumer Protection Act s 62 lay-by is a different statute and is not implemented by these NCA flows.

Worked example. Goods priced at R1 200. Four payments of R300. No initiation fee, no service fee, no interest, no late fee.

| Event | Classification |
| --- | --- |
| Booked as priced | `non_nca_payment_plan`. No Form 26 duty. No s 126 waterfall, because there are no interest or fee buckets. A payment reduces the outstanding instalments in the order the contract states |
| Someone later adds a R50 late fee on this plan | Rejected. A late fee is not a permitted amendment of a non-NCA plan inside servicing |
| The product is re-offered with a late charge | New agreement. It may be incidental credit. Section 5 defers full application until 20 business days after the charge is raised. Incidental initiation fee is nil. Incidental interest maximum is 2% per month. Sections 108 to 110 apply only once interest is charged (s 107(2)) |

Recommendation: book the zero-cost product as `non_nca_payment_plan`. Do not emit NCA statements for it. Do not run s 103(5) on it. The contractual receipt is still allocated through the ledger so the two products share intake, idempotency, and reversals.

### E12. Lay-by used as security for a short-term loan

The deposit is the consumer's money. It is not a s 101 charge unless it is non-refundable, in which case booking rejects it as a prohibited charge. A pledge or cession of that balance can meet the s 1 definition of a secured loan. Regulation 39(3) would then stop the loan being an "unsecured credit transaction". Regulation 39(2) does not require the short-term loan to be unsecured. Section 108(2)(b) gives a secured loan a two-month statement maximum rather than one month.

Worked example. The consumer has paid R1 000 into a zero-interest lay-by. The provider disburses a R3 000 short-term loan to the consumer for one month, and the consumer cedes the lay-by as security.

| Question | Option A, recommended for day-1 | Option B |
| --- | --- | --- |
| Is the R1 000 principal, a prepayment, or a fee? | None of these. It is a deposit liability. It is not netted against the R3 000 | Treat R1 000 as a s 126 payment on day one. That is a different product (a R2 000 loan) and must be priced as that |
| Which interest row? | Short-term, if amount, term, and disbursement tests pass. The security does not by itself move it to RR+21% or RR+17% | If counsel decides the short-term row is unavailable once a pledge exists, the engine is given a different subsector and the lower of the available caps is a legal decision, not a servicing guess |
| How does the deposit get applied if the loan goes into default? | Only on the condition the cession states, and then as an internal payment with its own value date, through the same s 126 path | Set-off that bypasses s 126. Not recommended; the Act does not provide a special waterfall for set-off |

The opportunity cost of a compulsory zero-interest deposit is not modelled as interest. If counsel later treats it as an implicit cost of credit, the product has to be repriced in origination. Servicing will not impute it.

Section 91: the lay-by contract must not waive an NCA right on the loan. Servicing does not police the lay-by wording. It refuses to book the pair if the loan payload says the deposit is non-refundable or is a fee.

### E14. Annual-rate disclosure on a monthly short-term rate

Section 101(1)(d) requires an annual expression. Regulation 42(1)(b) requires monthly disclosure for short-term. Neither states the conversion.

Worked example. Monthly rate 5%.

| Method | Figure stored as the annual disclosure |
| --- | --- |
| Nominal, `0.05 × 12` | 60% |
| Effective, `(1.05^12) − 1` | 79.59% |

Recommendation: the payload carries `annual_disclosure_method`. Day-1 accepts `nominal_times_12` only, because that is the method origination must already have printed if it printed "60% per annum". The engine checks that `annual_rate_disclosure` equals the monthly rate times 12, to the disclosed precision. It does not certify that nominal times 12 is the method the Act calls "prescribed". The statement prints the monthly rate and the annual figure, each labelled with the method.

### E15. Rounding

Regulation 40(3) sums the daily amounts. It does not say when to round to a cent. Regulation 40(4)'s 0.1% year tolerance does not authorise a rate above the cap.

Recommendation, owned by the engine and recorded in the pack: keep each daily amount at a fixed scale of six decimal places in rand, sum them, and round the consumer debit to the nearest cent, half away from zero, at the moment the charge becomes due. The engine must show, in its test pack, that a full year of this rounding stays within 0.1% of an unrounded prescribed calculation. Servicing posts the cents it is given.

### E16. Prepayment that does not settle the agreement

Section 126(1) allows the prepayment and forbids a penalty. It does not say whether the remaining term shortens or the instalment drops.

Recommendation: the agreement carries `prepayment_application` of `reduce_term` or `reduce_instalment`. If a multi-instalment agreement omits it, booking returns 422. A single-instalment short-term loan has nothing to reshape: the prepayment reduces principal after due interest and due fees, and interest runs on the reduced principal until the due date or an earlier settlement. The engine returns the revised schedule. Servicing stores it. The historical schedule is retained.

## 5. Agreement state

The status is servicing's. The engine does not set it. In duplum frozen, dispute open, and prescription flagged are flags, not statuses.

`pending_disbursement` → `active` → (`in_arrears` ↔ `active`) → `settled`

Other terminals and side states: `booking_rejected` (nothing was persisted as an agreement), `disbursement_failed` (no consumer debit for interest or fees), `rescinded` (a s 121 instruction from origination, unwound by contra journals), `prescription_review` (allocation paused).

An agreement is `in_arrears` when a due bucket is still unpaid at the end of its due date. It returns to `active` when those buckets are zero. Section 103(5) uses "in default" and does not define the moment default starts. Section 129(1) opens with "If the consumer is in default", so the pre-enforcement notice assumes default already exists; the notice is not the start of the s 103(5) clock. Day-1 treats default as starting at the end of the due date on which an amount remains unpaid, using the agreement's `end_of_day` convention. A later collections grace period does not move that timestamp. If counsel reads default as starting on the next civil day, that is a one-day change to this timestamp and must be an election in the rule pack before go-live.

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

Statement delivery reads the contact from Enigma at send time. The PDF stores the name, address, and NCR number used on that statement, because the document is immutable even if Enigma later changes a detail.

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
    "initiation_fee_cents": 56500,
    "initiation_fee_treatment": "deferred_separate_with_interest"
  },
  "interest": {
    "structure": "fixed_monthly",
    "monthly_rate": "0.050000",
    "annual_rate_disclosure": "0.600000",
    "annual_disclosure_method": "nominal_times_12",
    "month_day_count": "30",
    "deferred_amount_convention": "end_of_day"
  },
  "service_fee": {
    "basis": "monthly",
    "amount_cents": 6000,
    "inception_proration": "actual_days_in_month",
    "settlement_proration": "actual_days_in_month"
  },
  "credit_life": null,
  "term": {
    "agreement_date": "2026-10-26",
    "disbursement_due_date": "2026-10-26",
    "first_due_date": "2026-11-25",
    "maturity_date": "2026-11-25",
    "instalment_cents": 583150,
    "frequency": "single"
  },
  "prepayment_application": "not_applicable",
  "statement_election": {
    "offered": true,
    "frequency": "monthly",
    "channel": "email"
  },
  "agreement_document": { "uri": "s3://agreements/dec_01J0.pdf", "sha256": "..." },
  "linked_deposit_id": null
}
```

The R5 000 initiation-fee figure in the sample is illustrative only if it matches Table B and regulation 43(3) for that principal: R165 + 10% × R4 000 = R565, and 15% × R5 000 = R750, so R565 binds. The engine recomputes it. The sample instalment is not a servicing calculation; the engine either accepts the schedule or returns the schedule it is prepared to maintain.

`POST /v1/payment-plans` is the same shape with `nca.form = non_nca_payment_plan`, fees and interest required to be zero, and no duplum fields. A non-zero charge on that endpoint is 422 with `reclassify_required`.

### 6.3 Happy path

1. Authenticate the caller. `check_mandate` and `get_product_enrolment`. Organisation and person must be active.
2. Insert the idempotency row. Lock it.
3. Check the product catalogue. `short_term_v1` may produce subsector `short_term` only. Servicing does not switch the loan to unsecured inside this product, because the organisation may not be enrolled for that product.
4. Call `CalculationEngine.validate_booking`. The engine checks regulation 39(2) or 39(3), both initiation-fee caps, the service-fee cap, the interest cap including E7 and E9, credit-life cap if a premium is present, the day-count elections against regulation 40, the schedule, the size thresholds, and the presence of every required election.
5. Persist the agreement as `pending_disbursement` with the rule-pack version, the elections, and the engine's schedule. Do not post consumer charges yet.
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
| Deferred initiation fee with no E4 election | 422 `election_required` |
| Size would be large | 422 `out_of_day1_scope` |
| Deposit linked as a non-refundable fee | 422 `prohibited_charge` |
| Engine timeout | 503. Idempotency row stays in progress so a retry does not double-book |
| `confirm` amount differs from principal | 422. Agreement stays `pending_disbursement` |
| Rail reports payment failed after `instruct` | Status `disbursement_failed`. Contra any journals. No interest |
| `confirm` arrives for an agreement that failed validation and was never created | 404, plus the ops item if the caller sets `funds_already_sent: true` |

Variable rate, when the agreement is `fixed_margin_over_rr` rather than fixed. A reference-rate feed supplies the new RR. The engine returns the new rate, capped by E9. Servicing stores it and sends the s 104(3) notice no later than 30 business days after the change takes effect, with the content regulation 36 requires: the effective date, and the rand interest if ascertainable. A change that reduces a fixed rate under E9 uses the five-business-day notice in s 104(2). Notice delivery is an outbox record. Failure to deliver retries. It does not roll back a rate the law already changed.

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
  "consumer_payment_date": "2026-10-24",
  "receipt_date": "2026-10-26",
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
2. Post the suspense journal: bank (or clearing) against unallocated receipts, cash date = `receipt_date`. This commit is the point at which the payment is "accepted" for s 126(2). If the ledger cannot post it, return 503 and let the rail retry. Do not acknowledge acceptance before the suspense journal exists.
3. Lock the agreement. If `agreement_id` is missing, match `payer_reference` or the DebiCheck mandate to one agreement. Zero matches or more than one match: leave the funds unallocated, set intake `unapplied`, emit `payment.unapplied`, return 202. Do not split across agreements. There is no statutory cross-agreement order to invent.
4. If the prescription flag is set, do not allocate. Intake stays `prescription_review`.
5. Engine `prepare(agreement, value_date = consumer_payment_date)`. It returns the due buckets after posting any charges that become due on that value date, the memo accruals, and the duplum flag. Servicing posts those due-debits first, in the same transaction as the allocation, so the waterfall sees them.
6. Engine `allocate(amount, due_buckets, elections)`. It returns lines that sum to the payment. Servicing checks the sum, checks that the order is interest, then fees, then principal, checks that no line exceeds the due bucket, and checks that principal is not driven negative. A surplus above the s 125 settlement amount is a separate surplus line, not principal and not future interest.
7. Ledger: debit unallocated, credit the buckets, value date = `consumer_payment_date`, cash date = `receipt_date`. One transaction, one idempotency key.
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
2. Engine `replay` from the reversed payment's value date, without that payment, over every later event. The engine is pure. Given the same journals and elections it returns the same journals.
3. Ledger posts the reversal and the replacement journals atomically, effective on their original value dates, with a link to the reversal event.
4. A statement already delivered is not edited. If the replay changes a figure inside a delivered period, the next statement opens with the old closing balance (s 109) and shows an adjustment line (s 112(3)). The statement row is flagged `affected_by_replay` for operations. A statement not yet delivered is regenerated.

An unpaid DebiCheck after a `success` uses this path. A `tracking` event that never succeeded has nothing to reverse.

Backdated intake: a payment with an earlier `consumer_payment_date` than a payment already allocated to the same agreement does not allocate on top. It triggers the same replay from the earlier value date. The lock serialises allocations per agreement. Order of work is value date, then intake time.

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
| Periodic statement | s 108, s 109, reg 35 for a small agreement | At the agreed frequency. Default monthly. Gap cannot exceed the s 108 maximum |
| Balance enquiry | s 110 | On request, free, inside the business-day limits |
| Settlement quote | s 113, calculated under s 125 | On request, free, within five business days, binding for five business days |
| Dispute outcome | s 111 | After a written dispute |

The periodic statement is the one with a PDF. An s 110 response can be oral or a shorter writing; if it is written it is stored, and it does not replace the periodic statement's opening and closing chain.

Booking rejects an NCA agreement with `statement_election.offered` false. The Act requires the offer. The consumer's election is captured in origination and copied here. Allowed frequencies: `monthly`, or `every_two_months` / `every_three_months` only where s 108(3) permits the reduction. A secured-loan classification, if counsel adopts it for the lay-by cession, allows a two-month maximum under s 108(2)(b). A non-NCA plan uses a contractual receipt, not Form 26.

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
4. Agreement summary. Principal debt (the principal bucket, labelled as principal, not as the all-in balance). Annual rate, with the method label. For short-term, the monthly rate as well. Instalment amount and frequency. Balance outstanding at the statement date (the all-in total). Whether the account is in arrears, and the arrears amount.
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
| `prepare` | Agreement, ledger position, value date | Due-debits that fall on that date; memo accrual; duplum flag; duplum base if default starts this date |
| `allocate` | Amount, due buckets, elections, settlement total | Lines in s 126 order, plus surplus; lines sum to the amount |
| `settlement_quote` | Agreement, position, settlement date | s 125 components and total |
| `statement_figures` | Agreement, movements, previous closing | Regulation 35 totals, arrears, rates to print, component closings |
| `replay` | Agreement, events from a value date, elections | Replacement journal set for that suffix |
| `on_rate_change` | Agreement, new RR, date | New rate and the consumer debit difference, for the s 104 notice |

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

- Versioned rule pack with gazette, effective date, and every election in section 4. No silent default for E4.
- Regulation 40 day maths, the 0.1% test, and E15 rounding, with fixtures that sum to the cent.
- Short-term versus unsecured classification from regulation 39, not from the product name.
- In duplum exactly as *Nedbank v NCR* order 11, with the base defined by E13 once counsel signs it.
- Settlement as s 125(2), with a zero early-termination charge unless the agreement is large, which day-1 rejects at booking.
- Deterministic `replay`.
- Credit-life cap from Gazette 40606, transcribed from the gazette rather than from the media release.

Ledger:

- Effective-dated, immutable journals and atomic replay.
- Memo balances that are not "due" for the waterfall, distinct from due balances. Without that split, E2 cannot be implemented.
- The buckets in section 9 kept separate, so a capitalised interest figure cannot inflate principal.
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
- The E4, E8, E14, and E16 elections, already disclosed where the agreement must disclose them.
- A guarantee that money is not disbursed before `POST /v1/agreements` returns 201.

## 11. What counsel signs before the rule pack is activated

The flows above are implementable only after these are signed. Until then the corresponding field has no default and booking fails closed.

| Id | Question |
| --- | --- |
| E1 | Credit interest on the date the consumer pays, while the bank date follows receipt |
| E2 | Exclude accrued-but-not-yet-debitable interest and fees from the s 126 waterfall |
| E3 | Oldest due fee first, with the disclosed same-day tie-break |
| E4 | Whether this provider's deferred initiation fee bears interest |
| E5 | Initiation-fee cap computed on cash advanced |
| E6 | Prescribed rand maxima are the most the consumer pays |
| E7 | "Subsequent" short-term loan means the same provider and the same calendar year |
| E8 | Pro rata method, and pro rata in the settlement month |
| E9 | Fixed rate is cut if the RR cap later falls below it |
| E13 | Duplum base is the principal bucket at the start of that default |
| E14 | Annual disclosure is nominal monthly times 12 |
| E11 / E12 | Zero-cost plan stays outside the NCA; the lay-by is a deposit, not principal |
| Form 26 | Gazette artwork, and whether the component block may sit on the small-agreement PDF |
| s 108 | That a secured-loan statement interval applies, or does not, to a lay-by cession |
