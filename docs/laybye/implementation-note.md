# Laybye layer — implementation note

Layer 1. The behaviour and the lock citations are in [layer1-draft.md](layer1-draft.md). This note is the call surface and the test run.

## Stable signatures

```text
laybye_name(*, mirror_product_name: str | None) -> str
day1_treatment(*, mirror_product_name: str | None) -> str

prepare_pair(ledger, *, organisation_id, person_id, product, organisation,
             recognised_at, cash_advanced_cents, frequency, schedule,
             identity_name, identity_number, service_address,
             quoted_disbursement=None, initiation_fee_cents=0,
             contractual_end=None, opening_hold_cents=0) -> tuple[LoanAccount, LoanAccount]

grant_loan(ledger, *, organisation_id, parent_loan_id, recognised_at,
           schedule, initiation_fee_cents=0) -> LoanAccount

receive_pre_disbursement(ledger, *, organisation_id, parent_loan_id,
                         cents, recognised_at) -> Transaction

allocate_receipt(ledger, *, organisation_id, parent_loan_id, cents,
                 recognised_at, attributed_due_on=None) -> ReceiptAllocation

accrue_parent(ledger, *, organisation_id, parent_loan_id, recognised_at,
              interest_cap_present) -> Accrual

levy_parent_service_fee(ledger, *, organisation_id, loan_id, recognised_at,
                        monthly_cents, due_on, interest_cap_present, vat_rate,
                        vat_registered=True, opening=False, first_due=None) -> Transaction

raise_collections(*, automated, loan_instalment_cents,
                  credit_life_premium_cents) -> tuple[CollectionInstruction, ...]

apply_credit_life_proceeds(ledger, *, organisation_id, parent_loan_id, cents,
                           recognised_at, attributed_due_on) -> CreditLifeProceeds

apply_on_death(ledger, *, organisation_id, parent_loan_id, recognised_at,
               requested_cents, authority, attributed_due_on) -> DeathApplication

store_funeral_beneficiary(name) -> None   # always raises beneficiary-not-in-lms
top_up(ledger, *, organisation_id, parent_loan_id) -> None   # always raises top-up-undefined
```

`ReceiptAllocation` is `value_date`, `loan_cents`, `laybye_cents`, `loan_transaction_id`, `laybye_transaction_id`.

`CollectionInstruction` is `purpose` (`loan_instalment` or `credit_life_premium`) and `cents`.

`Section124Authority` is `mandate_id`, `authorised_cents`, `authorised_from`, `authorised_to`, `signed_in_life`.

`CreditLifeProceeds` is `value_date`, `loan_cents`, `unposted_cents`, `loan_transaction_id`.

`DeathApplication` is `value_date`, `applied_cents`, `hold_cents_after`, `loan_transaction_id`, `laybye_transaction_id`.

Ledger methods this layer added, used only as the posting path for the rules above:

```text
Ledger.prepare(...) -> LoanAccount          # no loan-out journal; disbursement date is None
Ledger.grant(...) -> LoanAccount            # loan-out journal; Ledger.book is prepare then grant
Ledger.credit_laybye(...) -> Transaction    # debit cash, credit laybye_hold
Ledger.debit_laybye(...) -> Transaction     # debit laybye_hold, credit cash
Ledger.section_126_cents(...) -> int        # allocate_payment, apply_prepayment=False
```

`credit_laybye` and the opening credit inside `open_laybye` are the same two lines. `section_126_cents` does not re-rank fees. The rank stays in `allocate_payment`.

## How the layer calls Layer 0

| Step | Call | Owner |
| --- | --- | --- |
| Elections at open | `resolve_customer_settings` inside `Ledger.prepare` | Configuration |
| Value date | `lms_config.calendar.value_date` | Configuration |
| Interest base | `Ledger.accrue_day` → `interest_bearing_cents` → `daily_interest_rands` | Ledger, configuration, engine |
| Service fee | `Ledger.levy_service_fee` → `service_fee_cents` and `opening_service_fraction` | Ledger and engine |
| Due portion of a receipt | `Ledger.section_126_cents` → `allocate_payment` | Ledger and engine |
| Loan posting | `Ledger.post_payment` | Ledger |
| Hold posting | `Ledger.credit_laybye` or `Ledger.debit_laybye` | Ledger |
| Section 124 amount | `lms.calc.laybye.guard_s124` | Engine |
| In-duplum ceiling | `Ledger.flag_default` (unchanged; hold is not an argument) | Ledger |

`Servicing.book_linked_laybye` books the agreement, prepares the pair, posts a pre-disbursement receipt as cash in, and grants when `grant_at` is set. `Servicing.disburse` grants a parent that was prepared earlier and still calls `Ledger.book` when no parent exists, so an ordinary loan without a Laybye is unchanged. `Ledger.post_payment` on a loan with a Laybye child takes due section 126 amounts and credits the remainder to the hold. `allocate_receipt` calls that method. A loan with no Laybye child still applies the partial-prepayment election and then raises `overpayment-unset`. §13 and §4 do not say whether prepayment runs before the Laybye; this path does not apply the election to the remainder.

Enigma is not called. §15 no longer gives Enigma the section 124 authority. The authority is the `Section124Authority` argument. A missing one fails closed.

## Remaining gaps

No value is filled in for these.

1. **§13 beside §4.** Excess after the due section 126 amount goes to the Laybye. The partial-prepayment election is not applied to that excess. The lock does not say a client can still choose to prepay future principal instead.
2. **Mirror treatment.** The name switches. The treatment that replaces cash-deposit is not stated. `day1_treatment` fails closed. There is no configuration field for the mirror product.
3. **Top-up.** There is no ordinary top-up posting to delegate to. `top_up` fails closed and does not move the hold.
4. **Estate surplus.** `unposted_cents` on credit-life proceeds is not paid. There is no estate account or payee.
5. **Shortfall that is not yet due, and consolidate versus settle.** `apply_on_death` posts only the due section 126 amount and fails closed above it (`shortfall-beyond-section-126`). The settlement comparison and the two verbs are not given postings.
6. **Credit life in the instalment.** §6 still counts a levied credit-life charge. §4 says the LMS does not keep those accounts. This layer does not levy the charge and does not add an affordability formula.
7. **Section 124 document.** Cents, dates, and "signed in life" are arguments. No schema for the signed instrument is given.
8. **Two interest bases.** The ledger and the pure engine do not adjust initiation the same way. This layer calls the ledger. Day-1 non-capitalised initiation matches max(0, principal − hold).
9. **In-duplum trigger.** §7 and §19 are not on the booking snapshot. This layer does not choose `contractual_breach` or `collections_default`.
10. **Same-day capitalisation in servicing.** The statement path can still accrue after a receipt recognised the same day. This allocator does not accrue. Statements are out of scope. The two smoke tests that record that gap still fail; they failed on the Layer 0 branch before this work.

## Test results

`python3 -m pytest tests/test_laybye.py` — 10 passed.

Pinned:

- Payments go to the loan first, excess to the Laybye, and future principal is not prepaid.
- Due principal is paid before the Laybye.
- A pre-disbursement receipt lands in the Laybye as cash in. Principal stays 0. No Laybye account fails closed.
- Net-balance interest is max(0, principal − hold). The in-duplum ceiling stays the gross principal.
- One service fee on the parent. The child and a second fee in the month are refused.
- Automated collections return a loan instalment and a separate credit-life premium. A zero premium is a real zero. An unknown premium fails closed. Nothing is posted. A funeral beneficiary is refused.
- Credit-life proceeds pay the due loan amount and do not increase the hold. The surplus is unposted.
- Death application with no authority, and with `signed_in_life=False`, fails closed. The hold and principal are unchanged.
- Top-up fails closed and does not change the hold.
- No mirror: the name is `credit-improvement loan child` and the treatment is `cash-deposit`. A mirror uses its name. A blank name fails closed. The replacement treatment fails closed.

`python3 -m pytest` — 127 passed, 2 failed, 2 skipped.

The two failures are `tests/test_layer0_smoke.py`:

- `test_same_day_capitalisation_is_not_applied_before_the_receipt` calls `pytest.fail` on purpose. The servicing statement still capitalises after the receipt.
- `test_rejected_statement_leaves_no_interest_bill` records that a statement rejected for a missing VAT rate has already billed interest.

Both are statement behaviour. This change does not implement statements.
