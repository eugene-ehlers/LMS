# Implementation checklist

The 28 October lock closed several items this file left open. `docs/IMPLEMENTATION_NOTE.md` is the current storage note. Where this checklist disagrees with `docs/LOCKED_DECISIONS.md`, the lock wins. Opening-month days are the date subtraction in decision 9. Subsequent short-term loans restart each calendar year (decision 13). VAT, late disbursement, partial prepayment, initiation interest, and the repo-rate fall are organisation elections with a product override (decision 19). The lay-by hold reduces only the interest base (decision 4). The annual equivalent is periodic rate times periods per year (decision 17).

This file does not change `docs/LOCKED_DECISIONS.md` and it does not add a rule. The storage that followed is `db/migrations/0003_elections.sql` and `docs/IMPLEMENTATION_NOTE.md`.

Read `docs/LOCKED_DECISIONS.md` first. Then the implementation note. Then this list. Where they differ, the locked decisions win.

A block marked **DRAFT** is a Layer 1 sketch. It is not an approved signature, not a schema change, and not a locked decision.

## Invariants

These restate the lock. An implementation keeps them. It does not fill a blank from this list.

1. Value date is the system recognition date. The day starts at 00:00. A loan, settlement, or deposit concluded on a calendar day is 00:00 that day. A reversal uses the value date originally recognised. A payment on a flag date is 00:00 that day and is visible to the morning default check.
2. A capitalised initiation fee is principal. A fee that is not capitalised is a section 126 charge. The same split applies to related fee points, which are not named. Pre-default capitalised initiation is inside the in-duplum ceiling.
3. A zero rate and a zero fee calculate, for the whole term or any part of it. Stored price is base rate minus campaign discount, including a result of zero. The discount stays through leniency, falls away on the default flag date, and does not return on a later cure. Penalty interest does not exceed the contractual rate.
4. A linked lay-by is a child of the loan. The pair is one loan, not security that would make the loan secured. Payments may be allocated to either. Interest uses loan principal minus the lay-by hold. One monthly service fee, on the parent. Consolidate or settle when the lay-by is at least the settlement balance. Credit life pays the loan first; the lay-by covers a shortfall; surplus of a cash-deposit treatment goes to the estate; an insurance structure follows a named beneficiary. A funeral benefit goes to the named beneficiary and leaves the loan and the lay-by unchanged. Death does not apply the lay-by without a section 124 authority signed in life. Day-1 is a deposit-insurance style arrangement and is not deposit-taking under the Banks Act.
5. The provider can choose actual/actual or 30/360. New products are recommended to use actual/actual. Accrual is daily. A 360-day year is not required for Day-1.
6. In duplum and collections use one default test. Leniency is calendar days, including weekends and public holidays. Unset `leniency_days` or `full_payment_threshold_percent` fails closed. Example values 4, 5, and 95 are not defaults. Default flags on the contractual due date plus leniency only when the amount received for that due date is below the threshold. The threshold instalment is the original principal slice plus levied charges that share that due date, including the monthly service fee, a non-capitalised initiation fee, and credit life. Unbilled interest is excluded until it is debited. Interest during leniency is the ordinary daily charge on the outstanding balance.
7. Each default episode has its own ceiling: unpaid principal at the first default in that episode, including pre-default capitalised initiation. Post-default accruals stay charges. Charges that cause the default do not count. A payment does not reset that episode's counter. A cure closes the episode. The next default takes a new ceiling. It is not a lifetime ceiling. Three unnamed section 103(5) edges stay unsigned, and the clip stays off until counsel confirms.
8. Allocation order is due or unpaid interest, then due or unpaid fees or charges, then principal.
9. Service-fee pro-rata applies only in the opening month. The fraction is inclusive days in the month over the actual days in that month. Later months, including the settlement month, take the full monthly fee, subject to the R60 cap. R60, R165, and R1 050 are excluding VAT by default. The provider may elect inclusive.
10. Interest on a deferred initiation fee defaults to none. `permitted` is stored per organisation or per product.
11. When the repo rate falls, the stored choice is `contract_rate` or `lower_of_contract_and_cap`. Option B also issues the section 104 notice. There is no platform default. Unset fails closed.
12. One statement per client shows all of that client's loans.
13. The platform's own decision engine may be forced at first. The LMS must be able to accept an external engine. Late disbursement supports both an adjusted instalment and a kept instalment with early settlement or a small write-off at contractual end. The write-off is not required if the account is already in default. A partial prepayment is either a shorter term or a lower instalment, chosen by the provider. The contractual instalment is preferred to stay the same during the term. Extra fees, other than interest, initiation, the monthly service fee, and credit life, are a further monthly fee and are not capitalised into the schedule. Restructuring can set a new instalment, price, and term. A subsequent short-term loan is counted per credit-provider organisation.
14. Frequencies are weekly, fortnightly, monthly, quarterly, bi-annual, and annual.
15. Identity, organisation, membership, enrolment, role, and mandate stay in Enigma. The LMS stores opaque ids. Timeout or an ambiguous Enigma status fails closed.
16. Name, ID number, and service address freeze at booking.
17. Billing rounds half-up to the cent. The same rounding rule is used wherever rounding is required. The annual equivalent rate is disclosed. Rounding must not create a compliance breach, including an instalment rounded above the affordability figure already aligned with the client.
18. A default-administration or collection-cost posting fails closed until a tariff row exists. Allowable extra costs are preferred as an additional monthly fee.

## Data already stored

`db/migrations/0002_locked_decisions.sql` already has these. Their meaning follows the lock above. Null still means unset.

| Stored | Level | Lock |
| --- | --- | --- |
| `leniency_days` | Organisation, product override | Decision 6. Calendar days. Not 4 or 5. |
| `full_payment_threshold_percent` | Organisation, product override | Decision 6. A percent. Not 95. |
| `base_rate`, `discount_rate` | Product terms. Effective rate column must equal base minus discount | Decision 3. The fallen-away state is not a separate column. |
| `interest_on_deferred_initiation` | Organisation, default `none`. Product override | Decision 10 |
| `repo_rate_fall` | Organisation and product. Null allowed | Decision 11. Null fails closed |
| `actual_actual`, `thirty_360` | Day-count reference rows | Decision 5. Day-1 need not use 360 |
| `intraday = start_of_day` | Product terms | Decision 1 |
| `prorate_settlement_service_fee = false` | Product terms, forced | Decision 9 |

The agreement pin is specified in the design note and is not a table in this repository. It has to carry the resolved copies, plus the frozen name, ID number, and service address (decision 16). The NCR number copy already described in the design note is not one of those three fields.

## Data the lock requires, without a storage level

Do not add these columns until the storage level is locked. Decisions 10 and 11 say "per organisation or per product". The items below do not.

| Choice | What the lock requires | What it does not say |
| --- | --- | --- |
| VAT election | Exclusive is the default for R60, R165, and R1 050. Inclusive is allowed | Organisation, product, or agreement. Whether other rand caps follow |
| Late disbursement | Both option (a) and option (b) | Which store holds the provider's choice |
| Partial prepayment | Shorten the term, or drop the instalment | Which store holds the choice |
| External decision engine | Must be acceptable. The platform engine may be forced initially | The payload of an external quote |
| Frequency | The six names | Weekday, 14-day versus calendar fortnight, anchor date |
| Further monthly fee | Fixed or variable, outside the amortising schedule | The fee code list beyond the examples |
| Restructure | A new instalment, price, and term | New agreement versus amendment of the frozen pin |
| Statement | One per client, all loans | Whether "all" crosses organisations |
| Annual equivalent rate | Disclosed | The formula |
| Section 104 notice | Issued when option B is the stored choice | The notice contents |

Tariff rows stay empty on purpose. Decision 18 does not supply rand amounts.

## DRAFT — Layer 1 sketch

Not production code. Not a locked rule. Signatures only, so a later pass can see the shape the lock already forces. Names can change. Behaviour that the technical questions below leave open is not given a body.

```python
# DRAFT
def value_date(recognised_at: datetime) -> date:
    """Johannesburg calendar date of system recognition. Value time is 00:00."""

def reversal_value_date(originally_recognised: date) -> date:
    """Decision 1. The reversal does not take its own recognition date."""

def threshold_instalment_cents(
    principal_slice_cents: int,
    levied_on_due_date: tuple[LeviedCharge, ...],
) -> int:
    """Decision 6. Principal slice plus charges that share the due date.
    Unbilled interest is absent from levied_on_due_date until it is debited.
    """

def is_in_default(
    *,
    due_on: date,
    value_date: date,
    leniency_days: int,
    received_for_due_date_cents: int,
    threshold_instalment_cents: int,
    threshold_percent: Decimal,
) -> bool:
    """One test for in duplum and collections. Calendar days.
    A flag-date receipt is already included in received_for_due_date_cents.
    """

def campaign_rate(
    base_rate: Decimal,
    discount_rate: Decimal,
    *,
    discount_fallen_away: bool,
) -> Decimal:
    """Decision 3. fallen_away is sticky after the flag date. A cure does not clear it.
    Result may be zero. The result is never above base_rate.
    """

def interest_base_cents(
    *,
    principal_cents: int,
    capitalised_initiation_cents: int,
    layby_hold_cents: int,
    charge_interest_on_initiation: bool,
) -> int:
    """Decisions 4 and 10. Not below zero. Does not post the hold through section 126."""

def episode_ceiling_cents(
    *,
    unpaid_principal_cents: int,
    pre_default_capitalised_initiation_cents: int,
) -> int:
    """Decision 7. New ceiling at the start of each episode.
    Charges that caused the default are not part of this principal figure.
    """

@dataclass(frozen=True)
class LaybyPair:
    """DRAFT. Decision 4. One loan, parent plus child. Not a secured classification."""
    parent_agreement_id: UUID
    child_agreement_id: UUID

def layby_can_settle(layby_balance_cents: int, settlement_balance_cents: int) -> bool:
    """Decision 4. True when the lay-by is at least the settlement balance.
    Which settlement balance is the open question below.
    """
```

`opening_service_fee_cents` is intentionally not given a draft body. Decision 9 states the fraction and does not make the numerator a single integer in the cross-month case. See technical question 1. The cent those fractions post at is technical question 20.

## Divergence already in the repository

The code and the tests describe the previous pass. They are not updated here. Do not treat a passing test as the locked charge where this table says they differ.

| Topic | What the repository does now | What the lock says |
| --- | --- | --- |
| Opening service fee | `(first_due - disbursed).days / days in the disbursement month`. 20 March 2026 to 3 April 2026 floors to 2709 cents | Inclusive days in the month / actual days in that month. The integer is not unique yet |
| VAT | Interpretation `cap_is_consumer_maximum`. Gazetted rand is the consumer maximum | R60, R165, and R1 050 exclude VAT unless the provider elects inclusive |
| Campaign after cure | `in_default=False` applies the discount again | The discount does not return on cure |
| Threshold instalment | Caller passes one instalment amount and one received amount | Received for that due date, against principal slice plus levied charges sharing the due date, excluding unbilled interest |
| In-duplum clip | `duplum.py` applies a cumulative cap, and the worked example counts the service fee from month 1 | Charges that cause the default do not count. The clip stays off until three unnamed edges are confirmed |
| Lay-by | Child kind `security_deposit`. Credit life was undocumented | One loan, not secured. Credit life, funeral, and death are stated |
| Rounding of caps | Statutory caps floor to the cent | Half-up on billing, the same rule wherever rounding is required, and no compliance breach |
| Identity pin | NCR number copy. Name, ID number, and service address are not frozen fields in the pin table | Decision 16 freezes those three |
| Statement, frequency, restructure, prepayment, late disbursement, VAT election | Not stored | Required, storage level not stated for several of them |

## Technical open questions

Each item quotes the limit of the lock. None of these has a selected answer.

1. **Inclusive opening-month days.** Decision 9 says pro-rata only in the opening month (disbursement to first payment due) and "inclusive days in the month / actual days in that month." For a disbursement on 20 March 2026 and a first due date on 3 April 2026, a 31-day March, the words can be counted as 12 inclusive days in March, 14 days of date subtraction, or 15 days if both endpoints of the span count. At a R60 fee those fractions are 2322.58 cents, 2709.68 cents, and 2903.23 cents before a cent rounding. The code floors the middle figure to 2709 cents. The cent rounding is question 20. None of the three numerators is selected.

2. **The clip.** Decision 7 states an episode ceiling and also says three section 103(5) edges not decided by Nedbank remain unsigned and the clip stays off until counsel confirms. The three edges are not named. It is not stated whether the clip that stays off is only those edges or the episode ceiling in the same section.

3. **Charges that cause the default.** They do not count toward the cap. The lock does not say which posted rows are the cause, or whether a service fee that fell due on the contractual date is one of them. The cumulative table in the design note counts that fee from month 1 and is marked as not a posting instruction.

4. **Recognition date and the concluded day.** Decision 1 uses the system recognition date as the value date, and also treats a loan, settlement, or deposit concluded on a calendar day as 00:00 that day. It does not say which date wins when recognition happens on a later calendar day.

5. **Discount and the morning check.** The discount falls away on the flag date. A payment on that date is seen by the morning check. The lock does not say whether the discount is removed before that test or only if the test flags default.

6. **The lay-by hold as a payment.** Interest on the net balance is called evidence that the hold is a payment against the loan. Payments may also be allocated across the loan and the lay-by. The lock does not say the hold is posted through section 126.

7. **Lay-by against the settlement balance.** Settle when the lay-by is at least the settlement balance. The lock does not say whether that settlement balance is already net of the hold. Netting it twice would change the comparison.

8. **Credit-life branch on Day-1.** Surplus goes to the estate if the lay-by is a cash deposit, and follows a named beneficiary if it is insurance. Day-1 is also described as deposit-insurance style. The lock does not pick the branch.

9. **Calendar year and "subsequent".** Decision 13 counts per credit-provider organisation. Table A's "within a calendar year" is not mentioned. The repository counts across years. That scope matches the organisation. It is not a locked answer to January.

10. **Related fee points.** Decision 2 applies the capitalised-versus-section-126 split to them and does not name them.

11. **VAT beyond three maxima.** R60, R165, and R1 050 are excluding VAT by default. Other gazetted rand amounts are not listed. The election's storage level is not stated. Adding exclusive VAT to a short-term fee can push the deferred amount through R8 000. The lock does not say how origination behaves in that case.

12. **Annual equivalent rate.** Decision 17 requires disclosure and does not give the formula.

13. **Service address.** Decision 16 freezes it and does not say which lines or whether a later postal correction is a new freeze or a forbidden rewrite.

14. **One statement, many organisations.** Decision 12 says all loans for the client. Tenant isolation is per organisation. The lock does not say the statement crosses that boundary.

15. **Frequency anchors.** The six frequencies are required. The weekday, the fortnight length, and the anchor date are not.

16. **Restructure versus the freeze.** A new instalment, price, and term is required. Decision 16 stops Enigma identity edits from rewriting the concluded agreement. The lock does not say a restructure is a new agreement.

17. **Write-off of a residual.** Option (b) allows a small write-off at contractual end, and says it is not required if the account is already in default. The lock does not say which sub-ledger is written off.

18. **Section 104 notice.** Option B issues it. The lock does not say the contents or the trigger date beyond the fall in the repo rate.

19. **Affordability.** Credit life is included in the loan instalment for affordability. The lock does not restate the calculation.

20. **Half-up and a statutory maximum.** Decision 17 requires half-up everywhere and forbids a rounding that creates a compliance breach. A half-up that lands one cent above a gazetted maximum is the case the current floor was written to avoid. The lock does not say which sentence wins for that one cent. The repository still floors caps.
