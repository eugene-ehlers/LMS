# Day-1 calculation rules

Locked on 26 October 2026 (Africa/Johannesburg), and aligned on 27 October 2026 with [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md).

[LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) is the source of truth for decisions that have already been locked. This document is the calculation contract: formulas, edge cases, and the worked examples. `tests/test_day1_examples.py` and `tests/test_locked_alignments.py` pin every figure. If the prose and the tests disagree, fix the prose. Where this document and the locked-decisions file disagree, the locked-decisions file wins, and the disagreement is listed under [Raised, not chosen](#raised-not-chosen) so that file can be updated. The calculator does not invent a third reading.

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

Amounts are integer cents. A fee or a billed interest charge is rounded half-up, away from zero, to the nearest cent. Daily interest is kept at 10 decimal places of a rand and rounded only when it is debited.

Debit interest:

- at month-end;
- on the settlement date used in a quote or a binding settlement;
- when a payment has cleared the principal and the accrued interest must be collected before the agreement can close.

Regulation 40(3) says the month's rand amount is the sum of the days. Summing the 10-decimal days and rounding once keeps a full calendar month of a constant balance on the stated rate. Two identities are tested:

- R2,000 at 5% per month for January through June 2026 bills **R600.00** of interest, which is 6 × 5% × R2,000;
- R10,000 at 28.25% per year for every day of 2026 (not a leap year) bills **R2,825.00**, which is exactly 28.25% of R10,000.

Regulation 40(4) allows a method that is not the prescribed one to differ by up to 0.1% over a year. The day-1 method is the prescribed actual-day method, so that tolerance is not used as room to go over the cap.

**Interest base (lock).** Interest accrues on the unpaid cash principal only, minus any linked lay-by hold ([LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §4). It does not accrue on unpaid interest, service fees, VAT, insurance, default administration, or collection costs. A deferred initiation fee does not join the base either. See D-BASE. A hold larger than the principal produces a zero base for that day. It does not create a credit. The hold does not reduce the in-duplum ceiling. See Example 12.

The base for a day is the principal at the start of that civil day after the advance has been posted and before payments received that day. An advance on 15 March accrues interest on 15 March. A payment on 15 March does not reduce 15 March's interest. It reduces the base from 16 March. This is the agreement's "particular time in the day" for regulation 40(2)(c)(i): start of day, with same-day advances included and same-day receipts excluded.

There is no separate penalty rate above the contractual rate. Section 103(1) says default interest may not exceed the highest rate on the principal. A campaign is stored as the contractual base rate minus a discount ([LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §3). While the campaign is on, the effective rate is that difference, floored at 0%. If the campaign is marked to fall away on default, the effective rate from the flag date is the contractual base, which is the penalty rate, and it is not higher than the base. See Example 13. The in-duplum freeze can still stop accrual.

Personal rates move only as repo plus a margin fixed in the agreement (section 103(4)). The margin is at most 21 percentage points (regulation 42, Table A, item 3, as substituted in 2015). The applied rate on a day is `repo(day) + margin`, using the repo whose effective date is on or before that day. Days before a change are not restated. Section 104(3) still requires written notice no later than 30 business days after the change. That notice is a servicing duty, not a term in the formula.

Short-term rates are disclosed as a monthly rate (regulation 42). Personal rates are disclosed as an annual rate (section 101(1)(d)). The engine does not publish `monthly × 12` as if it were a prescribed annual rate.

## Interest formulas

For a short-term agreement, on civil day D:

```text
net(D)        = max(0, unpaid_principal(D) − laybye_hold(D))
base_rate     = 5% or 3% per month, or the lower agreed monthly rate
effective(D)  = max(0, base_rate − campaign_discount)   while the campaign is on
              = base_rate                               once that discount has fallen away
interest(D)   = net(D) × effective(D) / days_in_calendar_month(D)
```

`base_rate` is 5% if this is the consumer's first short-term loan with this credit provider in the calendar year of the advance, and 3% otherwise (regulation 42, Table A, item 5), unless the agreement states a lower rate. The base rate is chosen once, at inception, and does not change on 1 January. Another loan with the same inception date counts as earlier, so the later same-day agreement is a subsequent loan. A loan advanced on 1 January is the first loan of the new year even if a December loan is still outstanding. The list of prior inceptions is an input. See D-RATE-SCOPE. The campaign discount is a separate stored number. It is not a rewrite of the base rate.

For an unsecured personal agreement the same net and the same campaign rule apply, with:

```text
base_rate    = repo(D) + margin
interest(D)  = net(D) × effective(D) / days_in_year(D)
```

`days_in_year` is 366 in a leap year and 365 otherwise. See D-DAYCOUNT for the 30-day and 365-day alternatives, both of which regulation 40(2)(c) permits. The day-1 wording uses actual days. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §5 also asks for 30/360. That divisor is not the pinned `fixed` option. See [Raised, not chosen](#raised-not-chosen).

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

VAT is then added if the credit provider is a VAT vendor. On R800.00 the day-1 charge is R120.00 + R18.00 = **R138.00**. See D-VAT.

The fee is levied on the advance date, which is not earlier than approval (regulation 41(1)). Regulation 43(4) allows it only when a new credit agreement is established, not on a transactional draw. Whether a refinance is a new agreement is a legal characterisation the caller supplies. The engine will not invent a second initiation fee on an existing agreement.

**Due date (lock, D-INIT-DUE).** If the consumer pays the fee upfront, it is due on the advance date and the upfront payment is applied to it before that day's interest is debited (section 103(3): that day's interest is not payable before the end of the day). If the fee is deferred, it is unpaid from the advance date, so section 126 allocates it before principal, but it falls due on the first principal due date. It does not, by itself, put the agreement in default the next morning.

Section 102 does not allow this fee to be folded into the principal of an unsecured or short-term agreement. It stays in its own bucket.

## Service fee

Regulation 44, as substituted in 2015, sets the maximum monthly service fee at **R60**. The National Credit Regulator's January 2019 public note says this maximum is R60 **excluding VAT**. Day-1 treats the prescribed rand caps as exclusive of VAT and adds VAT for a vendor. See D-VAT.

The fee is levied at the end of the month to which it relates (regulation 41(2)), or on the settlement date if the agreement ends first.

Regulation 44(4) requires a pro-rata fee when the agreement is concluded during the calendar month:

```text
ex_VAT = round_half_up(R60 × inclusive_days / days_in_that_month)
VAT    = round_half_up(ex_VAT × vat_rate_on_the_levy_date)
```

Inclusive days run from the advance date through the last day of that month, or through the settlement date if the agreement is concluded and ends in the same month. An advance on the 1st is 31/31 of a 31-day month, so the pro-rata formula charges the full R60. An advance on the last day is 1/N of the cap.

After the commencement month, the day-1 product charges the full monthly maximum for every later calendar month in which the agreement is open, including the month in which it ends. That is the maximum Davis J allowed in *Micro Finance South Africa and the Banking Association of South Africa v National Credit Regulator* (Gauteng Division, Pretoria, 14 August 2020), as reported by Moonstone on 10 September 2020. The signed order was not in this workspace. See D-TERMINAL. Charging the full final month is permitted by that judgment, not required. The engine can be switched to pro-rata the final month. It will not charge more than the full month, and it will not charge a full month on top of the commencement pro-rata when both happen in one month.

A service fee above R60 before VAT is rejected at configuration. During an in-duplum freeze the fee is clipped, not rejected. See below.

A linked lay-by does not add a second monthly service fee ([LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §4). The child lay-by is not posted as its own NCA agreement on this ledger, so it cannot raise one. Example 12 pins a single R69.00 fee on the loan. A campaign may discount the loan's ex-VAT service fee, including down to R0. That fee discount does not fall away when the interest discount does. See [Raised, not chosen](#raised-not-chosen).

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

**Default (lock, [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §6).** The same test is used for in duplum and for the default flag. Default is flagged on a contractual due date plus `leniency_days` calendar days, when the amount received toward that due date's bundle is below `full_payment_threshold_percent`. The bundle is the original cents of the principal slices and the levied charges that share that due date. Unbilled interest is not in the bundle. A payment on the due date is already in the state on the flag date. A payment on the flag date itself is applied later that day, which is the accepted calculator's order. See [Raised, not chosen](#raised-not-chosen).

With the preserved unset values, `leniency_days = 1` and the threshold is 100%. That flags on the calendar day after the due date if any cent of the bundle remains, which is the rule the accepted calculator already used. [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §6 gives 4 or 5 days, and 95%, as examples. It does not lock those numbers as the unset values. Interest accrues every civil day during the leniency window, on that day's net balance, at the rate that applies that day. Leniency does not pause it and does not move the campaign penalty rate forward. Example 11.

**Ceiling (lock, [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7).** The ceiling is the unpaid cash principal at the start of the first day of that episode, before that day's interest. It does not fall if principal is paid during the episode. It does not include the lay-by hold, unpaid fees, or uncapitalised initiation. Paying a duplum charge reduces what is owed. It does not give back cap room. A capitalised initiation fee would be part of this principal. The calculator does not capitalise initiation. See [Raised, not chosen](#raised-not-chosen).

**What counts (lock).** Only amounts that accrue on a day that is already inside the episode. A fee levied the day before default, and still unpaid, is collectible and is outside the cap. The levy date decides, not the month the fee "relates" to.

**VAT (lock, D-VAT-DUPLUM).** The consumer-facing total, including VAT, consumes the ceiling. On a freeze day the charge is clipped to the remaining cents and VAT is extracted from that clipped total so ex-VAT plus VAT equals the amount posted. The uncharged remainder is not a debt.

**Order on a day inside the cap.** Interest for the day is clipped first. A fee levied that day then takes what room remains.

**Release (lock, [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7).** A cure closes the episode. Cure is the same test as the default flag: no due-date bundle whose flag date has arrived is still short of the threshold. Unbilled interest is not itself a due amount until it is debited, but interest that accrued during the episode is committed to the episode's accrued total when the episode closes. The next day accrues normally, outside that episode. A later default opens a new episode. Its ceiling is the unpaid principal at the start of that new default, not the previous ceiling and not a lifetime remainder. Amounts that accrued in the earlier episode do not consume the new ceiling. Example 7 keeps a R150.00 ceiling only because the principal never changed. Example 10 reduces the principal from R200.00 to R50.00 and the second ceiling follows it.

The NCR's draft guideline in Government Notice 54 of *Government Gazette* 38419 (30 January 2015) would add every earlier episode's accruals to the new one. That notice asked for comment. This workspace did not find it enacted as a regulation. The engine can still run that reading so the cents stay visible. It contradicts §7 and is not the production rule.

Credit insurance, default administration, and collection costs are buckets, not calculators.

- A premium is an input. Section 106's "cover may not exceed the outstanding obligation" is not computed here.
- Regulation 46 limits a default administration charge to the amount payable for a registered letter of demand in an undefended magistrates' court action, plus reasonable necessary delivery expenses. No rand tariff is hardcoded.
- Regulation 47 limits collection costs to costs actually incurred, under whichever of the statutes it names applies to the enforcement. It still cites the Supreme Court Act, 1959, which the Superior Courts Act 10 of 2013 repealed. The engine does not turn that citation into a tariff.

Both are clipped by the same ceiling when they are levied during default.

## Payment allocation (section 126)

Section 126(1) and (2): the consumer may prepay at any time, without notice or penalty, and the provider must accept the payment.

Section 126(3), credited on the date of receipt:

1. due or unpaid interest;
2. due or unpaid fees and charges;
3. the principal debt.

Within interest, the oldest due date is paid first, then the earlier posting.

Within fees the Act is silent. Day-1 pays the earliest due date first and, on the same due date, uses this rank: collection costs, default administration, credit insurance, service fee, initiation fee (D-ALLOC). A deferred initiation fee is unpaid, so it is paid before principal even though it is not yet due. A service fee that is already due is paid before that initiation fee, because a due charge outranks a later-due one. That sub-order is what lets a partial payment clear the charge that would otherwise start default tomorrow.

Principal is reduced on the earliest unpaid instalment first, including a future instalment once arrears and fees are clear (D-PREPAY). A payment that clears the principal of a multi-instalment loan therefore shortens the next instalment rather than the last.

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

### Lay-by as security for a short-term loan

Section 90(2)(n) makes a blanket set-off clause unlawful except as a standing debt arrangement or as section 124 allows. Section 124 requires a written (or recorded) authorisation that names the account, the obligation, the amount or the method, and the dates. Regulation 38 requires notice in Form 27, or an electromagnetic record later transcribed, before the first charge.

The calculator does not decide that a mandate is valid. `guard_s124` refuses the application when the Enigma mandate id is missing, the date is outside the authorised dates, or the requested cents exceed the authorised cents. The recommended authorised amount is the unpaid interest and fees, not a forced settlement of principal that the mandate did not name. The application is then an ordinary section 126 payment sourced from the hold. The hold is reduced by the amount applied. It earns R0.

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

The R38.71 is `round(R2,000 × 0.05 × 12 / 31)`. A full January at the same balance is **R100.00** on the actual-day divisor, which is exactly 5%. The 30-day divisor bills **R103.33** for that January, because 31/30 × 5% is more than 5% in a 31-day month. Day-1 agreements state the actual-day divisor so a full calendar month cannot exceed the prescribed monthly rate. Regulation 40(2)(c)(iv) allows a 30-day agreement. It is not the day-1 wording. See D-DAYCOUNT.

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

The same loan with `leniency_days = 1` also bills **R100.00** by 30 April. The four-day window does not delete 1–3 April. It only delays the flag. `leniency_days = 0` would flag on 31 March itself. The preserved unset value is 1, which flags on the next calendar day. That unset value is raised below. It is not a number in the locked-decisions file.

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

The R400.00 loan is unpaid, so default starts on 1 April. The in-duplum ceiling that morning is **R1,000.00**, the gross unpaid principal. It is not the R600.00 net balance on which March interest was calculated.

### 13. Zero rate, zero fees, and a campaign discount that falls away

R1,000.00 advanced 1 March 2026. The contractual base is 5% per month. The campaign discount is 5% per month. The initiation discount is the whole ex-VAT cap and the service-fee discount is the whole R60.00. A settlement quote on 15 March is **R1,000.00**: no interest and no fee, and the calculation does not fail. The same is true of an agreed monthly rate of exactly 0% with the monthly service fee configured at R0 and the initiation fee discounted to R0.

The principal falls due on 31 March and is not paid.

| Campaign | March interest | April interest | April service fee | In default on 30 April? |
| --- | ---: | ---: | ---: | --- |
| Discount falls away on default, leniency 1 day | R0.00 | **R50.00** | R0.00 | Yes |
| Same campaign, leniency 4 days | R0.00 | **R45.00** | R0.00 | Yes |
| Discount does not fall away | R0.00 | **R0.00** | R0.00 | Yes |

`campaign_terms` keeps reporting base 5.00% and discount 5.00% after the fall-away. The effective rate is 0% while the discount is on and 5% once it has fallen away. The 4-day window is still at 0%, including R0.00 of unbilled interest on 3 April, because the penalty rate starts on the flag date and not on the missed due date. From 4 April the base rate runs, so April is 27/30 × R50.00 = **R45.00**. The fee discounts stay at R0. That split is raised below.

A second loan, R600.00 due 31 March and R400.00 due 30 June, uses the same 5% minus 5% campaign, set to fall away. The R600.00 is paid on 15 April, after the flag. April interest is R25.00 for 1–15 April on R1,000.00 plus R10.00 for 16–30 April on the remaining R400.00, **R35.00** in total. Both pieces use the base 5%. The cure does not turn the discount back on. That restoration is also raised below.

## Data structures and pure functions

Every public function takes values and returns values. None of them reads a clock, a database, or Enigma. `State` is immutable. `run` folds civil days from the advance date through `until` and returns a new state.

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
  fee_cap_basis                exclusive (lock) | inclusive
  terminal_service_fee         full (lock) | pro_rata
  duplum_reset                 fresh (locked by LOCKED_DECISIONS §7) | aggregate (rejected reading)
  day_count                    actual (lock) | fixed
  interest_on_deferred_initiation   false (lock)
  service_fee_monthly_cents    at most 6000
  vat_registered               true for a vendor
  count_vat_in_duplum          true (lock)
  leniency_days                1 preserves the accepted calculator; raised, not a locked number
  full_payment_threshold_percent    100 preserves the accepted calculator; raised, not a locked number

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

## Decision log

These are the readings that need a business, and in several cases a legal, confirmation. The "day-1 default" column is what the code does now.

| Id | Question | Day-1 default | Alternative, with the worked difference |
| --- | --- | --- | --- |
| D-DAYCOUNT | Regulation 40 lets the agreement use actual days or a 30-day month and a 365-day year | Actual days in the month, and 365 or 366 in the year | Full January on R2,000 at 5% is R100.00 actual and **R103.33** on a 30-day divisor. 29 February 2028 on R10,000 at 28.25% is R7.72 actual and **R7.74** on a 365-day divisor |
| D-VAT | The regulations state R60 and the Table B rands without saying "excluding VAT". The NCR's January 2019 note says the service fee "must not exceed R60 excluding VAT" | Prescribed caps are ex-VAT. VAT is added for a vendor, half-up, on the rounded ex-VAT amount. Interest has no VAT | Treating the cap as VAT-inclusive changes the R800 initiation fee from **R138.00 to R120.00** |
| D-VAT-TIME | Which VAT rate applies when the rate changes during a month | The rate on the levy date, for the whole fee | Splitting the month was not adopted. Example 5 shows March at 15% and a hypothetical April at 16%, with no split inside April |
| D-VAT-DUPLUM | Does VAT on a fee consume the section 103(5) ceiling | Yes. The consumer-facing total is clipped to the ceiling | Leaving VAT outside the ceiling bills **R153.00** of June and July charges on the R150 loan against a R150 ceiling, and does not clip July's service fee |
| D-BASE | Regulation 39(1) defines "deferred amount" to include section 101(1)(b) to (g), which would compound unpaid interest and fees. NCR Circular 15 of 2016 says a deferred initiation fee on an unsecured or short-term loan must stay separate and not bear interest. The 2020 High Court judgment, as reported, says interest on a deferred initiation fee is **permitted** | Interest accrues on unpaid cash principal only. The court permitted the extra interest. It did not require it. Charging less than the maximum is lawful. Regulation 39's wider base is not used | On the R1,000 March 2026 loan, putting the unpaid R172.50 initiation fee into the base raises March interest from **R50.00 to R58.35**. Compounding unpaid interest as well is a further step and is not offered as a switch |
| D-TERMINAL | Regulation 44(4) pro-rates the commencement month and is silent on the month the agreement ends. Davis J held that a full fee in the final month is allowed | Commencement month is pro-rata. Every later month, including the settlement month, is the full R60 before VAT. A loan that starts and ends in one month is pro-rata only | Pro-rata for the final month cuts the hypothetical 10 April quote from **R4,818.54 to R4,772.14** |
| D-DUP-RESET | Closed by [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §7. A cure closes the episode. The next default has a fresh ceiling equal to unpaid principal at the new default. The 2015 NCR draft was not found as a regulation | Fresh episode. Example 10: the ceiling moves from **R200.00 to R50.00** | The aggregate switch remains only so the rejected reading stays reproducible. On the R150 loan it charges **R0** in October where the fresh cap charges **R7.50 interest and R69.00 service**. On the R200 loan it charges **R0** in October where the fresh cap charges **R2.50 interest and R47.50 service** |
| D-INIT-DUE | The Act does not say when a deferred initiation fee falls due | Unpaid from the advance date (so section 126 pays it before principal) but due on the first principal due date | Making it due on the advance date would put the R150 loan in default on 2 May, and May's R69.00 service fee would then count toward the R150 ceiling. The pinned Example 7 would no longer hold |
| D-ALLOC | Section 126 orders interest, then fees as a class, then principal. It does not order the fee class | Earliest due date, then collection, default administration, insurance, service, initiation | Any other order inside the fee class is still section 126-compliant. The pinned R200 payment in Example 6 clears the service fee before the initiation fee because the service fee is already due |
| D-PREPAY | Which instalment a principal prepayment reduces | The earliest unpaid slice, so arrears clear before the tail shortens | Reducing the last instalment instead would leave the next instalment intact. Example 6's two-slice loan reduces the 1 April slice by the extra R10, from R400 to R390 |
| D-RATE-SCOPE | "First loan" and "subsequent loans within a calendar year" do not say whether the universe is one credit provider or the whole market | This credit provider only, because the LMS cannot see other providers. The caller can pass bureau dates later without a formula change. The rate is fixed at inception | A market-wide 3% rule needs data this product does not have on day 1 |
| D-THRESHOLD | Section 7 says the Minister reviews the section 9 thresholds at least every five years. Commentary in 2026 still uses R15,000 and R250,000 from GN 713 of 2006. The short-term R8,000 figure is still the one printed in regulation 39(2) | Use R8,000, six months, R15,000, and R250,000, and reject a book that would cross them | A later unnoticed amendment would move the micro / personal boundary and the early-termination boundary. Confirm against the latest Gazette before go-live |
| D-LARGE | Section 125(2)(c) adds an early-termination charge on a **large** agreement. For a variable-rate large agreement it is "no more than" the interest for three months minus any notice given. The regulation does not say whether those are calendar months, 90 days, or interest on the current balance | Day-1 personal loans at or above R250,000 are rejected. The charge is R0 for every agreement the engine will quote. The three-month formula is not implemented | Inventing a 90-day or three-calendar-month formula would be a new rule. Do not do it until the product is allowed to be large |
| D-BNPL | A zero-cost plan is outside the NCA. The first late fee or interest can make it incidental credit | No NCA cost is ever posted. Cancellation uses CPA regulation 34 | The incidental-credit cap of 2% per month is not built. Do not add a late fee in this engine until that path is specified |
| D-HOLD-INTEREST | CPA section 62 requires interest under the Prescribed Rate of Interest Act only when the supplier cannot deliver goods for a reason beyond its control, and double the payments when the failure is the supplier's. It does not require the supplier to pay interest on a voluntary security hold | The hold earns R0. Inability-to-supply compensation is not calculated | Paying the consumer a deposit rate would be a product choice, not an NCA cap |
| D-SECURITY | How much of the hold is applied on default | Only the cents a section 124 mandate specifically authorises. The recommended figure is the unpaid interest and fees, applied through section 126 | Applying the hold to principal, or to the full settlement, needs those cents and that obligation written into the mandate. A clause that merely says "apply the deposit on default" is the section 90(2)(n) problem |
| D-TARIFF | Default-administration and collection amounts | Caller-supplied, then clipped by section 103(5). No magistrates' court or debt-collector tariff is hardcoded | Hardcoding a rand letter fee would invent a number the regulation ties to a tariff |

## Raised, not chosen

These points are gaps or conflicts between [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md), the Act, and the accepted calculator. The calculator does not treat them as new locked decisions. Where a behaviour is named below, it is the behaviour required to keep the accepted formulas running, or the only arithmetic that avoids a negative amount. Update the locked-decisions file before treating any of them as closed.

| Point | What the locked file says | What the calculator does now | Why it is not closed |
| --- | --- | --- | --- |
| Unset leniency and threshold | §6: configurable, with examples of 4 or 5 days and 95% or more. No unset number | `leniency_days = 1` and `100%`. That is the accepted calculator: flag the next calendar day if any cent of the bundle remains | 4, 5, and 95 are examples, not a default. Choosing them as the unset values would move every existing pinned default |
| Which days leniency counts | §6 says "days" | Calendar days. Flag date = due date + `leniency_days` | Business days are not stated |
| What "the instalment" contains | §6: 95% or more of the instalment | Original cents of principal slices and levied charges that share that due date. Unbilled interest is outside the test until it is debited | A contractual instalment that includes unbilled interest is not defined |
| Payment on the flag date | §1: a payment on a calendar day is recognised at 00:00. §6: flag if the payment has not been received | The morning check runs before that day's payments, as the accepted calculator already does. A payment on the flag date can cure the episode later the same day. It does not stop the episode from opening | Applying §1 literally would let a same-day payment stop the flag, and would change the duplum day-count of a payment made on the first default day |
| When the campaign penalty rate starts | §3: the discount falls away on non-payment and the penalty rate is the base rate. §6: default is flagged after leniency | The discount stays on through the leniency window, including at 0%. The base rate starts on the flag date. Example 13: four days of leniency bill **R45.00** of April interest, not R50.00 and not R0.00 | "Non-payment" could instead mean the missed due date, with the penalty rate running during leniency while the flag waits |
| Does a cure restore the discount? | §3 does not say | It stays off, including after the cure. The split loan in Example 13 bills **R10.00** for 16–30 April on the remaining R400.00, not R0.00 | Restoring it on cure would also be a new rule |
| Do fee discounts fall away? | §3 describes the penalty as a rate | Only the interest discount falls away. Initiation and service discounts stay, including a discount to R0 | The file does not say a fee campaign ends on non-payment |
| Fee discount shape | Interest is base x% minus discount y% | Fee discounts are cents off the ex-VAT fee, floored at R0, then VAT is recalculated | A percentage fee discount is not stated |
| Discount larger than the base | "Real rate less discount = 0%" | The effective rate is floored at 0%. It is not a credit, and it is not an error | A negative rate would break regulation 40 |
| Lay-by and the duplum ceiling | §4: interest on principal minus hold. §7: ceiling is unpaid principal, including capitalised initiation | Interest uses the net balance. The ceiling uses gross unpaid principal. Example 12: March interest **R30.00**, ceiling **R1,000.00** | The file does not say the hold reduces the ceiling |
| Hold larger than principal | §4: net balance | Interest base is floored at R0. Example 12: a R1,500.00 hold on R1,000.00 bills **R0.00** interest and still one R69.00 service fee | A negative base is not an NCA result |
| Same-day hold | §1: value date 00:00. The interest convention in this document excludes same-day receipts from that day's base | A `LaybyeHold` on date D reduces interest on D. The hold is not a section 126 receipt | Treating it like a receipt would start the lower base on D+1 |
| Capitalised initiation | §2: if capitalised, it is part of the principal. §7: the ceiling includes pre-default capitalised initiation. This document: section 102 keeps the fee out of principal on a short-term or unsecured agreement | Initiation stays a section 126 fee. The ceiling is cash principal only | Capitalising it for these two products conflicts with the section 102 reading already in this document. No capitalisation rule was added |
| Service-fee pro-rata period | §9: pro-rata only from disbursement to the first payment due. Regulation 44(4): pro-rata when the agreement is concluded during the calendar month | Pro-rata for the commencement calendar month only. Later months, including the settlement month, are the full fee | "Until the first payment due" can cross a month boundary. Regulation 44(4) does not. The accepted formula was left in place |
| 30/360 | §5: actual/actual and standard 30/360 must both be available | `actual` is actual/actual. `fixed` is a 30-day month and a **365-day** year, which is the regulation 40 alternative already pinned. It is not 30/360 | Changing the personal divisor from 365 to 360 would move the pinned fixed-day figures. No 360-day divisor was added |
| Rate after a repo fall | §11: provider choice. Option A keeps the contract rate. Option B uses the lower of the contract rate and the current statutory maximum, with a section 104 notice | The engine always accrues `repo(day) + margin`. There is no frozen contract rate and no notice | Neither option is coded as a choice. The current formula matches Option B only when the margin is already at the 21-point cap |
| Lay-by payments, consolidation, credit life | §4: payments may be allocated across the loan and the lay-by; the client may settle when the lay-by covers the settlement balance; credit life on the linked lay-by must be defined | The hold reduces the interest base. Applying the hold still requires a section 124 amount and is a section 126 payment. No split allocation, no automatic consolidation, no credit-life posting | Those three behaviours are not specified far enough to calculate |
| Statements, external decision engines, payment frequencies, identity freeze | §§12–16 | Not in this calculator | They are servicing and origination rules. They do not change a cent in `src/lms/calc/` |

## What was deliberately not invented

- A rand cap for a section 129 letter or a collection commission.
- A three-month early-termination formula for large agreements.
- A market-wide view of who has already had a short-term loan this year.
- An annual percentage rate equal to the monthly short-term rate times 12.
- A credit-life premium table, or a section 106 cover test.
- A public-holiday calendar.
- A grace period other than the configurable leniency in [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) §6. The unset values are raised above. They are not a new statutory grace.
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
