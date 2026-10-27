# Day-1 calculation rules

Locked on 26 October 2026 (Africa/Johannesburg). Aligned again on 27 October 2026 with the Layer 0 text now in [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md).

[LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) is the source of truth. This document is the calculation contract: formulas, edge cases, and the worked examples. `tests/test_day1_examples.py` and `tests/test_locked_alignments.py` pin the calculator that exists today. This update does not change that calculator. Where a pin and a newly locked sentence differ, the locked sentence is the rule for the next implementation, and the difference is recorded in [implementation-checklist.md](implementation-checklist.md). No new reading is added here.

The pure functions in `src/lms/calc/` are the numerical authority for the formulas that match those locks. This is the reference calculator. It is not yet a persisted ledger or an HTTP service.

A **lock** is a behaviour the engine enforces. A **decision** is a reading the National Credit Act (NCA) or its regulations leave open, and which [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) has not closed. The engine still has a behaviour for each open decision, because a calculator cannot run on an unresolved branch. That behaviour is recorded here with the alternative and, where it changes the cents, the worked difference. It is not a new locked decision.

Nothing in this document is a new NCA rule. Prescribed numbers are quoted from the Act, the 2006 regulations as amended by Government Notice R.1080 in *Government Gazette* 39379 of 6 November 2015 (in force six months later), and the sources named with each rule. Where a later instrument might have moved a threshold and this workspace could not confirm the amendment, the item is marked as a decision rather than treated as settled.

## Scope

The engine prices and posts cost of credit, allocates payments, quotes and executes early settlement, applies the statutory in-duplum cap, and prices a zero-cost lay-by. It does not originate credit, assess affordability, register a credit provider, deliver statements, or calculate a credit-life premium.

Identity is not modelled here. `credit_provider_org_id`, `consumer_party_id`, and `product_enrolment_id` are opaque Enigma ids. A section 124 mandate id is the same kind of foreign key. The private Enigma repository was not readable from this environment, so the LMS does not guess Enigma's schema. It refuses to store a person, an organisation, a membership, or a role.

Callers pass **civil dates in Africa/Johannesburg**. A payment at 22:30 UTC is the next South African calendar date. The engine does not convert time zones and does not split a day into timestamps.

## Products

| Product | Legal character | Day-1 price |
| --- | --- | --- |
| `micro` | NCA short-term credit transaction, regulation 39(2) | 5% or 3% per month, plus capped initiation and service fees |
| `personal` | NCA unsecured credit transaction | Repo + a fixed margin of at most 21 percentage points per year |
| `laybye_bnpl` | Not an NCA credit agreement while it stays zero-cost. A goods lay-by is CPA section 62 | No interest, no initiation fee, no service fee |
| `laybye_security` | A hold of the consumer's money, applied to a micro loan only under a section 124 authorisation | The hold itself earns nothing. The application is a section 126 payment on the loan |

A micro agreement is rejected, and is **not** silently repriced as personal, unless all of these are true:

- cash advanced is at most R8,000 (regulation 39(2), which this workspace still shows at the 2006 figure);
- maturity is on or before the advance date plus six calendar months;
- the cash is disbursed to the consumer, not to a related person and not to someone else (regulation 39(2)(d)).

A personal agreement is rejected if the margin exceeds 21 percentage points, or if the cash advanced is at least R250,000. Day-1 personal loans stay below the large-agreement line so the section 125(2)(c) early-termination charge does not arise. That charge's day-count is not locked. See D-LARGE and D-THRESHOLD.

Agreement size, used only to confirm that early termination is zero, follows section 9 and Government Notice 713 of 1 June 2006 as still cited in current commentary:

- small: principal at or below R15,000;
- intermediate: above R15,000 and below R250,000;
- large: at or above R250,000, and every mortgage.

## Money, rounding, and the interest base

Amounts are integer cents. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §17 requires half-up rounding to cents on billing, the same rounding rule wherever a round is required, and disclosure of the annual equivalent rate. A round must not push an instalment above an affordability figure already aligned with the client. The annual-equivalent formula, and what the system does when a round would cross that figure, are not in the locked file. See the checklist.

A fee or a billed interest charge is rounded half-up, away from zero, to the nearest cent. Daily interest is kept at 10 decimal places of a rand and rounded only when it is debited. That is rounding on billing. It is the method the pins use.

Debit interest:

- at month-end;
- on the settlement date used in a quote or a binding settlement;
- when a payment has cleared the principal and the accrued interest must be collected before the agreement can close.

Regulation 40(3) says the month's rand amount is the sum of the days. Summing the 10-decimal days and rounding once keeps a full calendar month of a constant balance on the stated rate. Two identities are tested:

- R2,000 at 5% per month for January through June 2026 bills **R600.00** of interest, which is 6 × 5% × R2,000;
- R10,000 at 28.25% per year for every day of 2026 (not a leap year) bills **R2,825.00**, which is exactly 28.25% of R10,000.

Regulation 40(4) allows a method that is not the prescribed one to differ by up to 0.1% over a year. The day-1 method is the prescribed actual-day method, so that tolerance is not used as room to go over the cap.

**Interest base (lock).** Interest accrues on the unpaid cash principal only, minus any linked lay-by hold ([LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §4). It does not accrue on unpaid interest, service fees, VAT, insurance, default administration, or collection costs. A deferred initiation fee bears interest only when the provider has chosen that option. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §10 locks the unset choice as no interest. Example 12 shows the calculator's net-of-hold interest. §4 also says that net figure is evidence the hold is a payment against the loan, not a separate savings product. The locked file does not say whether that payment reduces principal before the ceiling is read. The calculator subtracts the hold from the interest base only. See the checklist.

The base for a day is the principal at the start of that civil day after the advance has been posted and before payments received that day. An advance on 15 March accrues interest on 15 March. A payment on 15 March does not reduce 15 March's interest. It reduces the base from 16 March. This is the agreement's "particular time in the day" for regulation 40(2)(c)(i): start of day, with same-day advances included and same-day receipts excluded.

There is no separate penalty rate above the contractual rate. Section 103(1) says default interest may not exceed the highest rate on the principal. A campaign is stored and displayed as base rate x% minus discount y% ([LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §3). The discount stays on through the leniency window. It falls away on the default flag date, and the rate from that date is the base rate. A later cure does not bring the discount back. A campaign that sets interest to 0% is the real rate less the discount, equal to 0%. The penalty rate is that base rate and must not exceed the contractual rate. Example 13 matches these three timing rules. The in-duplum freeze can still stop accrual. §3 does not say whether a fee discount falls away. The calculator leaves fee discounts in place.

Personal rates are repo plus a margin fixed in the agreement (section 103(4)), and the margin is at most 21 percentage points (regulation 42, Table A, item 3, as substituted in 2015). [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §11 then requires a provider choice, stored per organisation or per product, with no platform default: Option A keeps the contract rate after a repo fall; Option B accrues at the lower of the contract rate and the current statutory maximum and issues the section 104 notice. Until that choice is stored, the calculation fails closed. The calculator still accrues `repo(day) + margin` on every personal loan. That is not Option A or Option B, and it is not fail-closed. See the checklist.

Short-term rates are disclosed as a monthly rate (regulation 42). Personal rates are disclosed as an annual rate (section 101(1)(d)). §17 also requires disclosure of the annual equivalent rate. The locked file does not give that conversion. This document does not supply one.

## Interest formulas

For a short-term agreement, on civil day D:

```text
net(D)        = max(0, unpaid_principal(D) − laybye_hold(D))
base_rate     = 5% or 3% per month, or the lower agreed monthly rate
effective(D)  = max(0, base_rate − campaign_discount)   while the campaign is on
              = base_rate                               once that discount has fallen away
interest(D)   = net(D) × effective(D) / days_in_calendar_month(D)
```

`base_rate` is 5% if this is the consumer's first short-term loan with this credit-provider organisation in the calendar year of the advance, and 3% otherwise (regulation 42, Table A, item 5), unless the agreement states a lower rate. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §13 locks that count to the credit-provider organisation. The base rate is chosen once, at inception, and does not change on 1 January. Another loan with the same inception date counts as earlier, so the later same-day agreement is a subsequent loan. A loan advanced on 1 January is the first loan of the new year even if a December loan is still outstanding. The campaign discount is a separate stored number. It is not a rewrite of the base rate. While leniency is running the effective rate still uses the discount. From the flag date it uses the base rate, including after a cure (§3).

For an unsecured personal agreement the same net and the same campaign rule apply, with:

```text
base_rate    = repo(D) + margin
interest(D)  = net(D) × effective(D) / days_in_year(D)
```

`days_in_year` is 366 in a leap year and 365 otherwise when the agreement uses actual/actual. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §5 requires both actual/actual and standard 30/360, with the provider choosing, and recommends actual/actual for new products. The same section says a 360-day year is not required for Day-1. Those two sentences are both locked and they conflict, because standard 30/360 uses a 360-day year. This document does not pick one. The calculator's `actual` option is actual/actual. Its `fixed` option is a 30-day month and a 365-day year. That is the regulation 40 alternative in D-DAYCOUNT. It is not 30/360. Accrual is daily (§5).

## Initiation fee

For micro and personal cash loans the prescribed maximum, before VAT, is the lesser of:

1. Table B (regulation 42(2), GN R.1080): `R165 + 10% × max(0, cash_advanced − R1,000)`, and never more than R1,050;
2. 15% of the principal debt (regulation 43(3)).

The principal used for both tests is the cash advanced. It excludes the initiation fee, so the 15% test is not circular. Regulation 42 says the "amount of the agreement" is the amount deferred. For these two products that amount is the cash disbursed to the consumer.

The 15% limb binds at and below R1,300. Table B binds between R1,300 and R9,850. The R1,050 limb binds at and above R9,850. Each limb is rounded half-up to the cent before the lesser is taken.

| Cash advanced | Cap before VAT | Which limb binds |
| --- | ---: | --- |
| R150.00 | R22.50 | 15% |
| R800.00 | R120.00 | 15% |
| R1,000.00 | R150.00 | 15% (Table B would be R165.00) |
| R1,300.00 | R195.00 | 15% and Table B are equal |
| R1,301.00 | R195.10 | Table B |
| R4,000.00 | R465.00 | Table B: 165 + 10% × 3,000 |
| R9,850.00 | R1,050.00 | R1,050 rand cap |
| R10,000.00 | R1,050.00 | R1,050 rand cap |

VAT is then added if the credit provider is a VAT vendor and the provider has not elected an inclusive cap. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §9 locks the rand maxima (R60, R165, R1,050) as excluding VAT by default. The provider may elect inclusive. On R800.00 the exclusive charge is R120.00 + R18.00 = **R138.00**. The inclusive election charges R120.00. See Example 1.

The fee is levied on the advance date, which is not earlier than approval (regulation 41(1)). Regulation 43(4) allows it only when a new credit agreement is established, not on a transactional draw. Whether a refinance is a new agreement is a legal characterisation the caller supplies. The engine will not invent a second initiation fee on an existing agreement.

[LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §2: a capitalised initiation fee is part of the principal debt, and §7 includes a capitalised initiation fee that was capitalised before the default date in the in-duplum ceiling. An initiation fee that is not capitalised is a section 126 fee. §2 says the same split applies to related fee points. It does not name those fees. The calculator always posts initiation as a section 126 fee, so its ceiling does not contain a capitalised fee.

**Due date (not locked).** The Act and the locked file do not say when a deferred, non-capitalised initiation fee falls due. The calculator keeps it unpaid from the advance date, so section 126 can pay it before principal, and due on the first principal due date, so it does not by itself open a default the next morning. That due date is still D-INIT-DUE. It is not a new rule.

Section 102 is the statutory tension with §2 for an unsecured or short-term agreement. This update does not resolve it. See the checklist.

## Service fee

Regulation 44, as substituted in 2015, sets the maximum monthly service fee at **R60**. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §9 locks that maximum, and the Table B rand figures, as excluding VAT by default. A provider may elect inclusive. The NCR's January 2019 note is the source named in §9.

The fee is levied at the end of the month to which it relates (regulation 41(2)), or on the settlement date if the agreement ends first.

[LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §9 locks the shape of the fee:

- pro-rata only in the opening month, described as disbursement to first payment due;
- opening-month fraction = inclusive days in the month / actual days in that month;
- every later month, including the settlement month, is the full monthly fee, subject to the R60 cap.

```text
ex_VAT = round_half_up(R60 × inclusive_days_in_the_month / actual_days_in_that_month)
VAT    = round_half_up(ex_VAT × vat_rate_on_the_levy_date)
```

The calculator's inclusive days run from the advance date through the last day of the commencement month, or through the settlement date if the agreement starts and ends in that month. An advance on the 1st is 31/31 of a 31-day month. An advance on the last day is 1/N of the cap. §9's phrase "disbursement to first payment due" does not say what the numerator is when that due date falls in a later month. See the checklist.

The full fee after the opening month, including the settlement month, is the locked rule. The calculator can still be switched to pro-rata the final month. That switch is below the locked full fee. Example 5 keeps both totals so the difference stays visible. A loan that starts and ends in one month is pro-rata only, which is the opening-month rule rather than a second full fee.

A service fee above R60 before VAT is rejected at configuration. During an in-duplum freeze the calculator clips the fee. §7 says three unnamed edges stay unclipped until counsel confirms. This document does not decide that the service-fee clip is one of them.

A linked lay-by does not add a second monthly service fee. §4 levies the one fee on the parent. Example 12 pins a single R69.00 fee. A campaign may discount the parent's ex-VAT service fee, including to R0. §3 requires a R0 fee to calculate. It does not say that fee discount falls away on the flag date. The calculator leaves it in place.

## VAT

Interest is not taxed. The working assumption is that interest is an exempt financial service (Value-Added Tax Act, section 12(a) read with section 2(1)(f)). A fee is taxed at the rate in force on the **levy date**. A rate change during the month does not split the month's fee. The standard rate on 26 October 2026 remains 15%: the 0.5 point increase announced for 1 May 2025 was reversed, and this workspace found no later increase.

A provider who is not a VAT vendor is configured `vat_registered = false` and is charged no VAT. The exclusive cap is then the amount payable.

Worked VAT figures are in Examples 5 and 8. The inclusive-cap alternative is in Example 1.

## In duplum (section 103(5))

Section 103(5):

> Despite any provision of the common law or a credit agreement to the contrary, the amounts contemplated in section 101(1)(b) to (g) that accrue during the time that a consumer is in default under the credit agreement may not, in aggregate, exceed the unpaid balance of the principal debt under that credit agreement as at the time that the default occurs.

The amounts are initiation fees, service fees, interest, credit-insurance premiums, default administration charges, and collection costs.

*Nedbank v National Credit Regulator* 2011 (3) SA 581 (SCA) is the authority used here, in particular the declarator the SCA left standing:

- while the consumer is in default, those amounts may not exceed the unpaid principal at the moment default occurred;
- once they reach that balance, no further charges accrue;
- a payment during the **same** default does not restart accrual.

Common-law in duplum is a different rule. *Paulsen v Slip Knot Investments* 2015 (CC) confirms that, outside the NCA, unpaid interest stops at the unpaid capital and can run again after a payment, and that the rule's operation around judgment is its own question. Day-1 NCA agreements do not import that restart.

**Default (lock, [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §6).** The same test is used for in duplum and for collections. Leniency is configured per customer and counts calendar days, including weekends and public holidays. An unset `leniency_days` or `full_payment_threshold_percent` fails closed. Example values, including 4 or 5 days and 95%, must not be hard-coded as defaults. The flag date is the contractual due date plus the configured leniency. The agreement is flagged when the amount received for that due date is below the threshold. The instalment in that test is the original principal slice plus the levied charges that share the due date, including the monthly service fee, a non-capitalised initiation fee, and credit life. Unbilled interest is outside the test until it is debited. A payment on the flag date is valued at 00:00 that day and is visible to the morning check (§1 and §6). Interest continues every civil day on the outstanding balance. Leniency does not pause it or reduce it. The campaign discount stays on during that window and becomes the base rate on the flag date (§3).

The calculator does not yet match two of those sentences. `Policy` still constructs with `leniency_days = 1` and a 100% threshold, and the morning check still runs before payments dated on the flag date. Examples 11 and 13 are pins of that code. They are not a restatement of the fail-closed rule or of the morning check.

**Ceiling (lock, [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7).** The ceiling is the unpaid principal at the start of that episode, including any initiation fee that was capitalised before the default date. It does not fall if principal is paid during the episode. Paying a duplum charge reduces what is owed and does not reset the episode counter. The calculator's ceiling is unpaid cash principal only, because it does not capitalise initiation. Example 12's R1,000.00 ceiling is that cash figure. §4's treatment of the hold as a payment against the loan is not applied to the ceiling in the calculator.

**What counts (lock, §7).** Charges that cause the default do not count toward the cap. Only charges that accrue during the episode count. A fee levied before the episode, and still unpaid, is collectible and is outside the cap. Post-default accruals count as charges even when a statement shows them as capitalised.

**Unsigned clip (§7).** Three section 103(5) edges that Nedbank did not decide remain unsigned, and the clip stays off until counsel confirms. The locked file does not name the three edges. This document does not assign D-VAT-DUPLUM, or any other open item, to those edges. The calculator still clips in-duplum charges, VAT included. That clip is not turned off here.

**VAT in the cap (not locked).** D-VAT-DUPLUM is the calculator's current behaviour: the consumer-facing total, including VAT, consumes the ceiling, and a clipped fee is split so ex-VAT plus VAT equals the posted total. It is not a sentence in the locked file.

**Order on a day inside the cap.** Interest for the day is clipped first. A fee levied that day then takes what room remains.

**Release (lock, [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7).** A cure closes the episode. Cure is the same test as the default flag: no due-date bundle whose flag date has arrived is still short of the threshold. Unbilled interest is not itself a due amount until it is debited, but interest that accrued during the episode is committed to the episode's accrued total when the episode closes. The next day accrues normally, outside that episode. A later default opens a new episode. Its ceiling is the unpaid principal at the start of that new default, not the previous ceiling and not a lifetime remainder. Amounts that accrued in the earlier episode do not consume the new ceiling. Example 7 keeps a R150.00 ceiling only because the principal never changed. Example 10 reduces the principal from R200.00 to R50.00 and the second ceiling follows it.

The NCR's draft guideline in Government Notice 54 of *Government Gazette* 38419 (30 January 2015) would add every earlier episode's accruals to the new one. That notice asked for comment. This workspace did not find it enacted as a regulation. The engine can still run that reading so the cents stay visible. It contradicts §7 and is not the production rule.

Credit insurance, default administration, and collection costs are not priced by a formula in the locked file.

- [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §6 includes a levied credit-life charge in the instalment used for the threshold, and requires the credit-life instalment in the affordability calculation. §4 states the death order. Neither section gives a premium table. The calculator has an insurance bucket only.
- [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §18: default-administration and collection-cost charges fail closed until a tariff row exists. §13 and §18 prefer an additional monthly fee, fixed or variable, rather than capitalising those costs into the amortisation schedule. The calculator still accepts a caller-supplied total and can clip it. That is not a tariff row and it is not fail-closed.
- Regulation 46 and regulation 47 remain the statutory limits. Regulation 47 still cites the Supreme Court Act, 1959, which the Superior Courts Act 10 of 2013 repealed. No rand tariff is taken from that citation.

## Payment allocation (section 126)

Section 126(1) and (2): the consumer may prepay at any time, without notice or penalty, and the provider must accept the payment.

Section 126(3), credited on the date of receipt:

1. due or unpaid interest;
2. due or unpaid fees and charges;
3. the principal debt.

Within interest, the oldest due date is paid first, then the earlier posting.

Within fees the Act is silent. Day-1 pays the earliest due date first and, on the same due date, uses this rank: collection costs, default administration, credit insurance, service fee, initiation fee (D-ALLOC). A deferred initiation fee is unpaid, so it is paid before principal even though it is not yet due. A service fee that is already due is paid before that initiation fee, because a due charge outranks a later-due one. That sub-order is what lets a partial payment clear the charge that would otherwise start default tomorrow.

[LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §13: after a partial prepayment the provider chooses whether to shorten the term or drop the instalment. The same section, and §6, prefer keeping the contractual instalment the same during the term. Unlike the repo choice in §11, §13 does not say the prepayment choice fails closed when it is unset. The calculator reduces the earliest unpaid slice, which changes that slice's amount. Example 6 is that calculator behaviour. It is not the provider choice.

Anything left after the principal is zero is suspense, not a negative balance. It is applied to interest and to the terminal service fee if the payment is large enough to close the agreement. It is not a fee.

## Early settlement (sections 125 and 113)

Section 125(1): the consumer or guarantor may settle at any time, with or without notice.

Section 125(2), for a day-1 agreement, is:

```text
settlement = unpaid principal
           + unpaid interest accrued up to and including the settlement date
           + unpaid fees levied up to that date, including the service fee for that month
           + early-termination charge
```

The early-termination charge is **R0**. Micro loans are small. Personal loans are kept below R250,000, so they are small or intermediate. Section 125(2)(c) applies only to a large agreement. See D-LARGE.

The quote is as at the end of the requested civil date, so that date's interest is included. Section 113: deliver the statement within five business days of the request, at no charge; it binds for five business days after delivery. The engine treats the delivery date as a valid payment date and the fifth business day after delivery as the last. Weekends are not business days. Public holidays are a set the caller passes. The engine does not ship a holiday calendar.

**Inside the window**, a payment of at least the quoted total settles the agreement. Interest and fees that would have accrued after the quote date are waived. The quoted total does not grow. A payment one cent short is an ordinary section 126 payment: it does not settle, and the agreement stays open for the unpaid cent (Example 8).

**After the window**, the same rand amount is an ordinary payment against the balances as at the payment date. It does not get the waiver.

A payment that does clear principal, accrued interest, and the month's service fee settles even without a quote. That is the section 125 right. The service fee is levied before the agreement is marked settled, so an ordinary prepayment cannot skip the final month's fee by arriving before month-end.

## Lay-by

### Zero-cost BNPL or goods lay-by

While the plan charges no interest, no fee, and no higher price for paying later, it is not a credit agreement. Section 8 requires a fee, a charge, interest, or a two-price structure before a credit transaction or incidental credit agreement exists. A goods lay-by, where the supplier holds the goods until the price is paid, is CPA section 62.

Day-1 posts no interest and no NCA fee. Each receipt reduces the unpaid price only. The money remains the consumer's property until delivery (CPA section 62(1)(a) read with section 65). The engine does not pay the consumer interest on that hold. See D-HOLD-INTEREST.

Cancellation, CPA section 62(4) to (6) and regulation 34 of the CPA regulations (GN R.293 of 1 April 2011):

- penalty is zero if it was not disclosed, in fact and extent, before the agreement;
- penalty is zero if non-completion is because of death or hospitalisation;
- otherwise the penalty is the agreed rate, but never more than 1% of the **full purchase price**, and never more than the amount paid;
- refund = amount paid − penalty, in money, not store credit (the CPA refund is of the amount paid; this engine returns a refund figure and does not convert it to credit).

Adding any late fee or interest later would risk turning the plan into an incidental credit agreement, capped at 2% per month once the charge is raised (regulation 42, Table A, item 7, and section 5). That transition is not implemented. See D-BNPL.

### Lay-by linked to a loan

[LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §4 locks the pair as one loan. The contract must not treat the hold as security that would make the loan secured. The parent/child link is required. Interest is the net balance, and §4 treats that as evidence the hold is a payment against the loan rather than a separate savings product. One monthly service fee is levied on the parent. The client can consolidate or settle when the lay-by balance is at least the settlement balance. The arrangement is a deposit-insurance style: the client pays for a period, then the loan is disbursed. For Day-1 it is not deposit-taking under the Banks Act.

On death, credit life pays the loan first. The lay-by covers any shortfall. A surplus goes to the estate when the lay-by is a cash deposit. When it is structured as insurance, treatment follows whether a beneficiary was named. A funeral benefit is paid to the named beneficiary and leaves the loan and the lay-by as they are. Death does not apply the lay-by unless a section 124 authority was signed in life. Without that authority the lay-by stays with the estate.

Section 90(2)(n) still makes a blanket set-off clause unlawful except as a standing debt arrangement or as section 124 allows. Section 124 requires a written or recorded authorisation that names the account, the obligation, the amount or the method, and the dates. The calculator's `guard_s124` refuses an application when the Enigma mandate id is missing, the date is outside the authorised dates, or the requested cents exceed the authorised cents. It does not post credit life, a funeral benefit, a death application, or a consolidation. The posting of the hold as a section 126 payment, as against an interest-base offset only, is a technical gap in the checklist. Example 12 is the offset the calculator uses.

## Worked examples

All of these use a VAT vendor and the exclusive-cap basis unless the example says otherwise. Repo, where it matters, is 7.00% until 24 September 2026 and 7.25% from 25 September 2026. The 7.00% figure is the rate implied by the South African Reserve Bank's 25 basis-point increase to 7.25% effective 25 September 2026. It is an input to the example. The engine does not fetch the rate.

### 1. Initiation cap, and VAT on top

R800.00 cash, first micro loan. Table B is R165.00. Fifteen percent is R120.00. The cap is **R120.00** before VAT. VAT at 15% is R18.00. The consumer is charged **R138.00**.

If the same R120.00 cap were VAT-inclusive (D-VAT), the consumer would pay R120.00, not R138.00.

The rest of the cap table is in the initiation section above. R4,000.00 is used again in Example 8: its cap is R465.00 before VAT, R534.75 including VAT at 15%.

### 2. Partial month, and the 30-day divisor

R2,000.00 at 5% per month, constant principal, 20 January 2026 through 31 January 2026 inclusive. That is 12 days of a 31-day month.

| Divisor | Interest |
| --- | ---: |
| Actual days in January (lock) | R38.71 |
| Fixed 30-day month | R40.00 |

The R38.71 is `round(R2,000 × 0.05 × 12 / 31)`. A full January at the same balance is **R100.00** on the actual-day divisor, which is exactly 5%. The 30-day divisor bills **R103.33** for that January, because 31/30 × 5% is more than 5% in a 31-day month. §5 recommends actual/actual for new products. The fixed column in this example is the calculator's 30/365 divisor, not standard 30/360. See D-DAYCOUNT.

### 3. First loan at 5%, subsequent loan at 3%

R1,000.00 for every day of February 2026 (28 days). A full month is exactly the monthly rate.

| Classification | February interest |
| --- | ---: |
| First short-term loan of 2026 with this provider | R50.00 |
| A prior short-term loan already exists in 2026 | R30.00 |

A second agreement advanced on the same calendar day as the first is a subsequent loan (3%). An agreement advanced on 1 January 2027, with a prior loan on 1 December 2026, is the first loan of 2027 (5%). The December loan does not keep a 3% label into the new year, and the February loan's 5% does not fall to 3% on 1 January.

### 4. Personal loan across the September 2026 repo change

R10,000.00 unsecured, margin 21 percentage points, actual days, 2026 not a leap year (divisor 365).

| Dates | Rate | Interest if that slice is rounded alone |
| --- | --- | ---: |
| 20–24 September (5 days) | 7.00% + 21% = 28.00% | R38.36 |
| 25–30 September (6 days) | 7.25% + 21% = 28.25% | R46.44 |
| 20–30 September as one debit | both rates | **R84.79** |

R38.36 + R46.44 is R84.80. The ledger debits the month once, so the posted charge is **R84.79**. Do not add the rounded slices.

One day, 29 February 2028, same principal, repo still 7.25%, margin 21%:

| Divisor | One day's interest |
| --- | ---: |
| 366, the leap-year actual count (lock) | R7.72 |
| 365, the fixed year | R7.74 |

Using 365 in a leap year bills one extra day's worth of interest over the year, about 0.27% more than the stated annual rate. Regulation 40 allows that reading. Day-1 does not use it, for the same reason as the 30-day month: a constant balance over the year should equal the stated annual rate, and the tested 2026 year does.

### 5. Commencement pro-rata, a hypothetical mid-loan VAT change, and the final month

R4,000.00 micro loan advanced 15 March 2026. This example uses a **hypothetical** VAT increase from 15% to 16% on 1 April 2026. That increase did not happen. It is here because a levy-date rule has to be shown against two rates. The settlement example uses the real 15% rate.

March is the commencement month. Inclusive days from 15 March through 31 March are 17 of 31.

```text
R60 × 17 / 31 = R32.9032… → R32.90
VAT at 15% on R32.90     = R4.935 → R4.94
March service fee        = R37.84
```

The March fee is levied on 31 March, so it takes the March rate even though the hypothetical increase is announced for April. April's fee is levied in April and takes 16%.

| April policy | Ex-VAT | VAT at 16% | Total |
| --- | ---: | ---: | ---: |
| Full month (lock) | R60.00 | R9.60 | R69.60 |
| Pro-rata, 10 days of 30 (D-TERMINAL alternative) | R20.00 | R3.20 | R23.20 |

A quote to settle on 10 April under the hypothetical rates is **R4,818.54** with the full April fee and **R4,772.14** with the pro-rata April fee. The R46.40 gap is only the April fee (R69.60 − R23.20). Interest, initiation, the March fee, and principal are the same. Early termination is R0.

The fee is not split across 15% and 16% inside April. The levy date picks one rate.

### 6. Partial payments under section 126

R1,000.00 advanced 1 March 2026, first loan, deferred initiation due on 1 September 2026 (maturity). March has 31 days and the advance is on the 1st, so the service fee is the full month.

| Charge at 31 March | Amount |
| --- | ---: |
| Interest, exactly 5% | R50.00 |
| Initiation, R150.00 + R22.50 VAT | R172.50 |
| Service, R60.00 + R9.00 VAT | R69.00 |
| Principal | R1,000.00 |

A payment of **R200.00** on 31 March, after the interest and the service fee have been debited:

| Bucket | Applied | Left |
| --- | ---: | ---: |
| Interest | R50.00 | R0.00 |
| Service fee (due 31 March) | R69.00 | R0.00 |
| Initiation (due only on 1 September, but unpaid) | R81.00 | R91.50 |
| Principal | R0.00 | R1,000.00 |

Interest is cleared before any fee, even though the initiation fee was levied on 1 March and the interest was debited on 31 March. Within fees, the service fee is already due and the initiation fee is not, so the service fee is cleared first.

A further **R100.00** against that balance:

| Bucket | Applied | Left |
| --- | ---: | ---: |
| Initiation | R91.50 | R0.00 |
| Principal | R8.50 | R991.50 |

No interest is outstanding, so the whole R100.00 is fees and then principal.

On a two-instalment variant of the same loan (R400.00 due 1 April and R600.00 due 1 May), with the initiation fee paid upfront, a 31 March payment that clears the R50.00 interest and the R69.00 service fee and then pays an extra R10.00 reduces the 1 April slice from R400.00 to **R390.00** and leaves the 1 May slice at R600.00.

### 7. In duplum: freeze, a payment that does not restart accrual, release, and the next default

R150.00 bullet micro loan advanced 1 May 2026, principal due 31 October 2026. Monthly interest at 5% is R7.50. The service fee including 15% VAT is R69.00. Initiation is 15% × R150.00 = R22.50, plus VAT R3.38, total **R25.88**, due only on 31 October.

May is not a default. Its charges are collectible and they do **not** consume the cap:

| Pre-default charge | Amount | In the cap? |
| --- | ---: | --- |
| Initiation | R25.88 | No |
| May interest | R7.50 | No |
| May service | R69.00 | No |

May's interest and service are due on 31 May. They are unpaid, so default starts on **1 June 2026**. The ceiling is the unpaid principal at that moment: **R150.00**.

| Month inside the first default | Interest | Service fee | Running total | Room left |
| --- | ---: | ---: | ---: | ---: |
| June | R7.50 | R69.00 | R76.50 | R73.50 |
| July interest | R7.50 |  | R84.00 | R66.00 |
| July service |  | **R66.00** (clipped from R69.00) | R150.00 | R0.00 |
| August | R0.00 | R0.00 | R150.00 | R0.00 |

The clipped July fee is R66.00 inclusive, split back into R57.39 ex-VAT and R8.61 VAT. The R3.00 that was not charged is not owed.

A payment of **R10.00** on 15 August clears the pre-default May interest of R7.50 and R2.50 of the June interest. Interest still owing is R12.50. The episode total stays **R150.00** and August interest stays R0.00. The payment does not restart accrual. That is the SCA's point in *Nedbank*.

If VAT were left outside the ceiling (D-VAT-DUPLUM), June and July would bill R7.50 + R69.00 + R7.50 + R69.00 = **R153.00** against a R150.00 ceiling, and July's service fee would not be clipped. Day-1 counts the VAT so the consumer-facing accrual stops at R150.00.

**Release.** On 15 September the consumer pays **R226.50**, which is every amount that has fallen due:

```text
May interest R7.50 + June interest R7.50 + July interest R7.50
+ May service R69.00 + June service R69.00 + July service R66.00
= R226.50
```

The R25.88 initiation fee is still unpaid and is not part of that payment, because it is not due until 31 October. Section 126 would take it before principal if the payment were larger. Principal stays R150.00. Default ends on 15 September.

From 16 September the loan accrues ordinary interest again: 15 days of a 30-day month is 15/30 × R7.50 = **R3.75**, debited on 30 September, plus a September service fee of R69.00. Neither is inside the closed episode.

**Second default, 1 October**, because the September charges are unpaid. The new ceiling is still R150.00.

| Reset rule | October interest | October service | Second-episode accrual |
| --- | ---: | ---: | ---: |
| Fresh cap (lock) | R7.50 | R69.00 | R76.50 |
| Draft 2015 guideline: aggregate prior accruals | R0.00 | R0.00 | R0.00 |

Under the fresh cap, the book at 31 October still shows September's unpaid R3.75 and R69.00 as well, so remaining interest is R11.25 and remaining service is R138.00. Under the draft guideline the October charges are not raised at all, because the first episode's R150.00 already equals the new ceiling. The fresh cap is the locked rule ([LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7). The aggregate column is the rejected reading, kept so the cents stay reproducible. Example 10 is the case where the second ceiling is a different number.

### 8. Settlement quote, the five-business-day window, and a short payment

Same R4,000.00 loan as Example 5, advanced 15 March 2026, but VAT stays at 15% for the whole term. Quote date and delivery date: Friday 10 April 2026.

| Component | Amount |
| --- | ---: |
| Principal | R4,000.00 |
| Interest 15–31 March (17/31 × 5% × R4,000) | R109.68 |
| Interest 1–10 April (10/30 × 5%) | R66.67 |
| Interest total | R176.35 |
| Initiation R465.00 + VAT R69.75 | R534.75 |
| March service R32.90 + VAT R4.94 | R37.84 |
| April service, full month, R60.00 + VAT R9.00 | R69.00 |
| Early termination, small agreement | R0.00 |
| **Settlement total** | **R4,817.94** |

The quote binds through **Friday 17 April 2026**, the fifth business day after Friday 10 April.

Paying **R4,817.94 on 17 April** settles the loan. A fresh quote prepared on 17 April would have charged April interest of R113.33 (1–17 April) instead of R66.67. The difference, **R46.66**, is waived. The April service fee does not change, because both quotes use the full-month fee.

Paying **R4,817.93 on 10 April** (one cent short) does not settle. Principal is covered and **R0.01 of the April service fee** remains. The agreement stays open.

Paying **R4,817.94 on Saturday 18 April**, the day after the window, does not settle either. April interest through 18 April is exactly R120.00. After interest is paid first, **R53.33 of the April service fee** remains unpaid.

A quote delivered on Wednesday 22 April 2026 binds through Wednesday 29 April. If Monday 27 April 2026 (Freedom Day) is in the caller's holiday set, the same quote binds through Thursday 30 April. The engine does not know Freedom Day unless the caller supplies it.

### 9. Lay-by cancellation, and applying the hold on default

**Goods lay-by / zero-cost BNPL.** Purchase price R2,000.00. The consumer has paid R800.00.

| Cause | Penalty | Refund |
| --- | ---: | ---: |
| Consumer cancels, 1% penalty disclosed beforehand | R20.00 | R780.00 |
| Consumer cancels, penalty never disclosed | R0.00 | R800.00 |
| Hospitalisation, even though a penalty was disclosed | R0.00 | R800.00 |

R20.00 is 1% of the full price, not 1% of the amount paid.

**Security hold.** The March loan in Example 6, before any payment, has unpaid interest and fees of R50.00 + R172.50 + R69.00 = **R291.50**. The hold is R300.00. The Enigma mandate authorises an application of up to the unpaid cost of credit, on 31 March, against that loan.

The engine applies **R291.50**. Section 126 clears the interest and both fees. Principal stays **R1,000.00**. The hold still has **R8.50**. Because the amounts that were due on 31 March have been paid, 1 April is not a default day.

An application with no mandate id is refused (`s124-mandate-missing`). An application larger than the authorised cents, or on a date the mandate does not name, is refused the same way. The calculator does not read the mandate text.

### 10. Second default, fresh ceiling after the principal has fallen

R200.00 micro loan advanced 1 May 2026. R150.00 falls due on 31 May and R50.00 on 31 October. The initiation fee is paid upfront, so it is outside both ceilings. Monthly interest at 5% on R200.00 is R10.00. The service fee including 15% VAT is R69.00.

May's charges are unpaid, so the first default starts on **1 June**. The ceiling is the unpaid principal that morning: **R200.00**. June and July each add R10.00 interest and R69.00 service (R158.00). August adds R10.00 interest and then clips the service fee to the remaining **R32.00**. The episode total is R200.00. September accrues nothing while that episode is open.

On **15 September** the consumer pays every charge that has fallen due, plus the R150.00 slice. Principal left is **R50.00**. The first episode closes that day. 16 September is not a default day.

September's post-cure charges fall due on 30 September and are unpaid, so a second default starts on **1 October**. The new ceiling is the unpaid principal that morning: **R50.00**, not the old R200.00.

| | First episode | Second episode, fresh | Second episode, aggregate reading |
| --- | ---: | ---: | ---: |
| Ceiling | R200.00 | R50.00 | R50.00 |
| October interest |  | R2.50 | R0.00 |
| October service |  | R47.50 (clipped from R69.00) | R0.00 |
| Accrued in the episode | R200.00 | R50.00 | R0.00 |

October interest is 5% of the R50.00 still unpaid. The fresh episode then has R47.50 of room, so the service fee is clipped to that and the new ceiling is full. The aggregate reading subtracts the first episode's R200.00 from the new R50.00 ceiling and charges nothing. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7 selects the fresh column.

### 11. Leniency, the 95% threshold, and interest that does not pause

R1,000.00 advanced 1 March 2026, initiation paid upfront, the whole principal due on 31 March. At 31 March the bundle due that day is:

| Component | Amount |
| --- | ---: |
| March interest | R50.00 |
| March service, including VAT | R69.00 |
| Principal | R1,000.00 |
| **Bundle** | **R1,119.00** |

`leniency_days = 4` and a 100% threshold. The flag date is 4 April.

| Date | In default? | Interest so far in April |
| --- | --- | ---: |
| 1–3 April | No | R5.00 unbilled (3/30 × 5% × R1,000.00) |
| 4 April | Yes | that day's interest starts the duplum episode |
| 30 April | Yes | March R50.00 + April R50.00 = **R100.00** |

The same loan with `leniency_days = 1` also bills **R100.00** by 30 April. The four-day window does not delete 1–3 April. It only delays the flag. These two runs pass the leniency and the threshold in explicitly. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §6 now fails closed when either value is unset, and it does not adopt 1 or 100% as defaults. The pin also flags on 4 April without a payment on 4 April. A payment on the flag date must be visible to the morning check. This example does not contain that payment, so it does not demonstrate the new check.

With `leniency_days = 4` and a **95%** threshold, 95% of R1,119.00 is exactly **R1,063.05**. Paid on 31 March, that clears the R119.00 of interest and service and R944.05 of principal, and **4 April is not a default**. Principal still owing is **R55.95**. One cent less, R1,063.04, is a default on 4 April. The threshold is the whole bundle, not 95% of the principal alone.

### 12. Lay-by hold in the interest base, one service fee

R1,000.00 micro loan for March 2026, linked to lay-by `laybye-child` with a R400.00 hold from the advance date.

| | Interest | Service fees posted |
| --- | ---: | ---: |
| No hold | R50.00 | one, R69.00 |
| R400.00 hold, the whole month | **R30.00** (5% × R600.00) | one, R69.00 |
| R1,500.00 hold, above the principal | **R0.00** | one, R69.00 |
| R400.00 until 15 March, then R1,000.00 from 16 March | **R14.52** | one, R69.00 |

R14.52 is 15/31 × 5% × R600.00, with each day kept at 10 decimal rands and the month rounded once. The hold set on 16 March is the balance at 00:00 that day, so 16 March already uses a zero net base.

The R400.00 loan is unpaid, so the calculator starts default on 1 April and sets the ceiling to **R1,000.00** of cash principal. It does not subtract the R400.00 hold. §4 calls the hold a payment against the loan. §7's ceiling is unpaid principal, including pre-default capitalised initiation. The locked file does not say the hold is deducted from that ceiling. This pin is the calculator's cash ceiling only.

### 13. Zero rate, zero fees, and a campaign discount that falls away

R1,000.00 advanced 1 March 2026. The contractual base is 5% per month. The campaign discount is 5% per month. The initiation discount is the whole ex-VAT cap and the service-fee discount is the whole R60.00. A settlement quote on 15 March is **R1,000.00**: no interest and no fee, and the calculation does not fail. The same is true of an agreed monthly rate of exactly 0% with the monthly service fee configured at R0 and the initiation fee discounted to R0.

The principal falls due on 31 March and is not paid.

| Campaign | March interest | April interest | April service fee | In default on 30 April? |
| --- | ---: | ---: | ---: | --- |
| Discount falls away on default, leniency 1 day | R0.00 | **R50.00** | R0.00 | Yes |
| Same campaign, leniency 4 days | R0.00 | **R45.00** | R0.00 | Yes |
| Discount does not fall away | R0.00 | **R0.00** | R0.00 | Yes |

`campaign_terms` keeps reporting base 5.00% and discount 5.00% after the fall-away. The effective rate is 0% while the discount is on and 5% once it has fallen away. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §3 locks that timing: the discount stays through leniency, falls away on the flag date, and does not return on a later cure. The 4-day window is still at 0%, including R0.00 of unbilled interest on 3 April. From 4 April the base rate runs, so April is 27/30 × R50.00 = **R45.00**. The fee discounts in this example stay at R0. §3 does not say a fee discount falls away.

A second loan, R600.00 due 31 March and R400.00 due 30 June, uses the same 5% minus 5% campaign, set to fall away. The R600.00 is paid on 15 April, after the flag. April interest is R25.00 for 1–15 April on R1,000.00 plus R10.00 for 16–30 April on the remaining R400.00, **R35.00** in total. Both pieces use the base 5%. The cure leaves the discount off, which §3 now locks.

## Data structures and pure functions

This block is the calculator's current surface. It is not the draft Layer 1 sketch. That sketch is in [implementation-checklist.md](implementation-checklist.md). Every public function takes values and returns values. None of them reads a clock, a database, or Enigma. `State` is immutable. `run` folds civil days from the advance date through `until` and returns a new state.

```text
Agreement
  product                      micro | personal
  credit_provider_org_id      Enigma organisation id
  consumer_party_id            Enigma party id
  product_enrolment_id         Enigma enrolment id
  cash_advanced_cents
  advance_date, maturity_date
  margin_annual                personal, at most 0.21
  agreed_monthly_rate          micro, optional, at most the 5% / 3% cap
  prior_short_term_inceptions  other loans; do not include this one
  initiation_paid_upfront
  principal_instalments        (due_date, cents), or one slice on maturity
  cash_to_consumer             false cannot be classified as short-term
  linked_laybye_id             required when laybye_hold_cents is positive
  laybye_hold_cents            opening hold; later LaybyeHold events replace it
  campaign_interest_discount   same unit as the product rate; subtracted from the base
  campaign_initiation_discount_cents
  campaign_service_discount_cents
  campaign_falls_away_on_default

Policy
  fee_cap_basis                exclusive is the §9 default; inclusive is the provider election
  terminal_service_fee         full matches §9; pro_rata does not
  duplum_reset                 fresh matches §7; aggregate is the rejected reading
  day_count                    actual is actual/actual; fixed is 30/365, not 30/360
  interest_on_deferred_initiation   false matches the §10 unset value
  service_fee_monthly_cents    at most 6000
  vat_registered               true for a vendor
  count_vat_in_duplum          calculator behaviour; not a §7 sentence. See G-CLIP
  leniency_days                required per customer; unset fails closed (§6). The calculator still defaults to 1
  full_payment_threshold_percent    required per customer; unset fails closed (§6). The calculator still defaults to 100

State
  principal_slices             due date, original cents, remaining cents
  charges                      interest and each s 101(1)(b)–(g) bucket,
                               with ex-VAT, VAT, remaining, and duplum episode
  unbilled_ordinary            decimal rands, not yet due
  unbilled_duplum              decimal rands inside the open or just-closed episode
  episodes                     ceiling, accrued cents, started, closed
  in_default, status, suspense_cents, clips, waived_cents
  laybye_hold_cents            balance used in that day's interest base
  campaign_discount_active     false from the flag date when the campaign falls away; a cure does not set it back
```

| Function | What it returns |
| --- | --- |
| `initiation_cap_ex_vat_cents(principal)` | Table B and 15%, lesser, in cents |
| `initiation_fee(...)` / `service_fee_cents(...)` | `(ex_vat, vat, total)` |
| `micro_monthly_rate(advance_date, prior_inceptions)` | `0.05` or `0.03` |
| `personal_annual_rate(day, margin, repos)` | repo + margin, never above repo + 21 points |
| `daily_interest_rands(base_cents, rate, divisor)` | 10-decimal rands for one day |
| `campaign_terms(agreement, day, repos, discount_active)` | `(base_rate, stored_discount, effective_rate)` |
| `allocate_payment(state, cents)` | interest, fees, principal, suspense, new state |
| `run(agreement, events, until=..., policy=...)` | state after folding those days |
| `quote_settlement(...)` | section 125 total, components, and the section 113 `valid_until` |
| `execute_settlement(quote, payment, paid_on)` | settled state and `waived_cents`, or an ordinary payment |
| `binding_until(delivered_on, holidays)` | fifth business day after delivery |
| `cancel_laybye(...)` | penalty and refund |
| `guard_s124(...)` | the authorised cents, or a `RuleError` |
| `payoff_cents(state)` | principal + remaining charges + unbilled interest rounded |

Events are `Payment` (ordinary, or `initiation_upfront`, and optionally `source="laybye_security"`), `LaybyeHold` (the hold balance at 00:00 on that date), and `ManualCharge` (`default_admin`, `collection`, or `insurance`) with a caller-supplied total. A manual charge during default is clipped to the remaining ceiling.

`RuleError.code` is stable. The codes the product guards use include `short-term-amount`, `short-term-term`, `short-term-payee`, `short-term-rate`, `unsecured-margin`, `day1-large`, `service-fee-cap`, `s124-mandate-missing`, `s124-amount`, and `s124-date`.

## Servicing locks not built in the calculator

These sentences are locked. This update records them. It does not add code.

- §12: one statement per client, covering all loans.
- §13: the platform may force its own decision engine at first, and must accept loans from an external engine later. When disbursement is later than the quote date, the provider uses either an instalment adjusted for the actual disbursement date and the remaining term, or the original instalment with an early settle or a small residual write-off at contractual end. The write-off is not required when the account is already in default. A restructuring can add other costs during the term by creating a new instalment, pricing, and term. Additional costs outside interest, initiation, the monthly service fee, and credit life are a further monthly fee, fixed or variable, and are not capitalised into the schedule.
- §14: weekly, fortnightly, monthly, quarterly, bi-annual, and annual frequencies.
- §15: opaque `person_id` and `organisation_id` only. Fail closed on an Enigma timeout or an ambiguous status.
- §16: freeze name, ID number, and service address at booking. A later Enigma change does not rewrite the concluded agreement.
- §1: a reversal uses the value date the system originally recognised.

The checklist holds the technical gaps under these sentences. None of them is given an algorithm here.

## Decision log

Rows marked **closed** are now sentences in [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md). The other rows were not closed by the 27 October 2026 Layer 0 update. They are not restated as new questions. The calculator column is what the code does today, including where that code is behind a closed row.

| Id | Question | Day-1 default | Alternative, with the worked difference |
| --- | --- | --- | --- |
| D-DAYCOUNT | §5 locks actual/actual and standard 30/360, recommends actual/actual for new products, and also says a 360-day year is not required for Day-1. Those last two claims conflict. Regulation 40 also allows a 30-day month and a 365-day year | Calculator: actual days, or `fixed` as 30/365. Not 30/360 | Full January on R2,000 at 5% is R100.00 actual and **R103.33** on a 30-day divisor. 29 February 2028 on R10,000 at 28.25% is R7.72 actual and **R7.74** on a 365-day divisor |
| D-VAT | **Closed by §9.** Rand maxima are ex-VAT by default. The provider may elect inclusive | Exclusive. VAT is added for a vendor, half-up, on the rounded ex-VAT amount. Interest has no VAT | The inclusive election changes the R800 initiation fee from **R138.00 to R120.00** |
| D-VAT-TIME | Which VAT rate applies when the rate changes during a month | The rate on the levy date, for the whole fee | Splitting the month was not adopted. Example 5 shows March at 15% and a hypothetical April at 16%, with no split inside April |
| D-VAT-DUPLUM | Not named in the locked file. §7's three unsigned edges are also unnamed. This row is not one of those edges unless counsel says so | The calculator clips the consumer-facing total, VAT included | Leaving VAT outside the ceiling bills **R153.00** of June and July charges on the R150 loan against a R150 ceiling, and does not clip July's service fee |
| D-BASE | **Closed by §10.** Provider choice, stored per organisation or per product. The locked unset value is no interest on a deferred initiation fee | No interest, unless `interest_on_deferred_initiation` is set | On the R1,000 March 2026 loan, putting the unpaid R172.50 initiation fee into the base raises March interest from **R50.00 to R58.35** |
| D-TERMINAL | **Closed by §9.** Full monthly fee after the opening month, including the settlement month, subject to the R60 cap | The calculator's full setting matches. The pro-rata final-month switch does not | Pro-rata for the final month cuts the hypothetical 10 April quote from **R4,818.54 to R4,772.14** |
| D-DUP-RESET | Closed by [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7. A cure closes the episode. The next default has a fresh ceiling equal to unpaid principal at the new default. The 2015 NCR draft was not found as a regulation | Fresh episode. Example 10: the ceiling moves from **R200.00 to R50.00** | The aggregate switch remains only so the rejected reading stays reproducible. On the R150 loan it charges **R0** in October where the fresh cap charges **R7.50 interest and R69.00 service**. On the R200 loan it charges **R0** in October where the fresh cap charges **R2.50 interest and R47.50 service** |
| D-INIT-DUE | The Act does not say when a deferred initiation fee falls due | Unpaid from the advance date (so section 126 pays it before principal) but due on the first principal due date | Making it due on the advance date would put the R150 loan in default on 2 May, and May's R69.00 service fee would then count toward the R150 ceiling. The pinned Example 7 would no longer hold |
| D-ALLOC | Section 126 orders interest, then fees as a class, then principal. It does not order the fee class | Earliest due date, then collection, default administration, insurance, service, initiation | Any other order inside the fee class is still section 126-compliant. The pinned R200 payment in Example 6 clears the service fee before the initiation fee because the service fee is already due |
| D-PREPAY | **Superseded by §13.** The provider chooses shorten-the-term or drop-the-instalment. No platform default is stated | The calculator reduces the earliest unpaid slice. Example 6 takes R10.00 off the R400.00 slice due 1 April and leaves the R600.00 slice | The §13 choice is not implemented. The checklist does not pick a default |
| D-RATE-SCOPE | **Closed by §13.** A subsequent short-term loan is counted per credit-provider organisation | Prior inceptions are an input for that organisation. The rate is fixed at inception | A market-wide 3% count is not the locked rule |
| D-THRESHOLD | Section 7 says the Minister reviews the section 9 thresholds at least every five years. Commentary in 2026 still uses R15,000 and R250,000 from GN 713 of 2006. The short-term R8,000 figure is still the one printed in regulation 39(2) | Use R8,000, six months, R15,000, and R250,000, and reject a book that would cross them | A later unnoticed amendment would move the micro / personal boundary and the early-termination boundary. Confirm against the latest Gazette before go-live |
| D-LARGE | Section 125(2)(c) adds an early-termination charge on a **large** agreement. For a variable-rate large agreement it is "no more than" the interest for three months minus any notice given. The regulation does not say whether those are calendar months, 90 days, or interest on the current balance | Day-1 personal loans at or above R250,000 are rejected. The charge is R0 for every agreement the engine will quote. The three-month formula is not implemented | Inventing a 90-day or three-calendar-month formula would be a new rule. Do not do it until the product is allowed to be large |
| D-BNPL | A zero-cost plan is outside the NCA. The first late fee or interest can make it incidental credit | No NCA cost is ever posted. Cancellation uses CPA regulation 34 | The incidental-credit cap of 2% per month is not built. Do not add a late fee in this engine until that path is specified |
| D-HOLD-INTEREST | CPA section 62 requires interest under the Prescribed Rate of Interest Act only when the supplier cannot deliver goods for a reason beyond its control, and double the payments when the failure is the supplier's. It does not require the supplier to pay interest on a voluntary security hold | The hold earns R0. Inability-to-supply compensation is not calculated | Paying the consumer a deposit rate would be a product choice, not an NCA cap |
| D-SECURITY | How much of the hold is applied on default | Only the cents a section 124 mandate specifically authorises. The recommended figure is the unpaid interest and fees, applied through section 126 | Applying the hold to principal, or to the full settlement, needs those cents and that obligation written into the mandate. A clause that merely says "apply the deposit on default" is the section 90(2)(n) problem |
| D-TARIFF | **Closed by §18 as a fail-closed rule.** No charge until a tariff row exists. §13 and §18 prefer an additional monthly fee over capitalising the cost into the schedule | Caller-supplied, then clipped. There is no tariff row | A missing row must not become a rand amount. The calculator does not enforce that yet |

## Calculator divergence

The locked file has closed the points that used to sit in this section as open business readings: calendar-day leniency, the instalment contents, the flag-date payment, campaign timing through leniency and after cure, exclusive VAT with an inclusive election, the full settlement-month service fee, no interest on a deferred initiation fee unless the provider chooses otherwise, the per-organisation subsequent-loan count, and fail-closed tariffs. [implementation-checklist.md](implementation-checklist.md) lists what the calculator still does instead, and the technical gaps. This section does not choose a repair. The Layer 1 types in that file are marked draft.

## What was deliberately not invented

- A rand cap for a section 129 letter or a collection commission.
- A three-month early-termination formula for large agreements.
- A market-wide count of who has already had a short-term loan this year. §13 counts subsequent loans per credit-provider organisation.
- An annual-equivalent conversion. §17 requires the disclosure. It does not give the formula, and this document does not invent `monthly × 12`.
- A credit-life premium table, or a section 106 cover test.
- A public-holiday calendar. Leniency counts those days as calendar days without needing their names (§6).
- A numeric default for leniency or for the full-payment threshold. §6 fails closed when either is unset.
- Compound interest on unpaid fees, other than the explicit and switched-off option to accrue on a deferred initiation fee.
- Any Enigma entity, role, or mandate schema.

## Sources

- National Credit Act 34 of 2005, sections 9, 90(2)(n), 101, 102, 103, 104, 105, 106, 113, 124, 125, and 126. Consolidated text used: LawLibrary point-in-time 1 October 2018, checked against the section text on Acts Online.
- National Credit Regulations, 2006, regulations 39, 40, 41, 42, 43, 44, 46, and 47. Tables A and B and the R60 service fee are the substitution in Government Notice R.1080, *Government Gazette* 39379, 6 November 2015, effective six months after publication.
- Government Notice R.6510, *Government Gazette* 53154, 13 August 2025, is a four-page amendment. The text recovered from it amends regulations 18 and 23A (credit-bureau information and affordability). It was not read as a change to regulations 40 to 47. The PDF had no usable text layer; confirm the Gazette before go-live.
- NCR, "If you have to borrow, borrow wisely", January 2019: service fee "must not exceed R60 excluding VAT"; short-term rate described as 5% then 3%.
- NCR Circular 15 of 2016: initiation fee on unsecured and short-term loans not to be included in the deferred amount.
- NCR draft guideline on section 103(5), Government Notice 54, *Government Gazette* 38419, 30 January 2015. Draft only.
- *Nedbank Ltd v National Credit Regulator* 2011 (3) SA 581 (SCA).
- *Paulsen v Slip Knot Investments 777 (Pty) Ltd* 2015 (CC), distinguished because it is the common-law rule.
- *Micro Finance South Africa and BASA v NCR* (Gauteng High Court, Davis J, 14 August 2020), as reported by Moonstone on 10 September 2020. Read the order before relying on the "permitted" maximum.
- Consumer Protection Act 68 of 2008, section 62, and regulation 34 of the CPA regulations (GN R.293, 1 April 2011): lay-by penalty may not exceed 1% of the full purchase price.
- SARB Monetary Policy Committee statement, September 2026: policy rate 7.25% effective 25 September 2026. SARS material through April 2025: the announced VAT increase was reversed and the standard rate stayed 15%. Neither feed is called by the engine.
