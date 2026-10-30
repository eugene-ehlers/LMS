# Ledger implementation note

The account and ledger model is `src/lms/ledger/` and `db/migrations/0004_ledger_accounts.sql`. Behaviour is cited section by section in [account-balance-transaction-model.md](account-balance-transaction-model.md). [LOCKED_DECISIONS.md](LOCKED_DECISIONS.md) (28 October 2026) is the source of truth. This note does not change a locked rule.

The calculation engine (`src/lms/calc/`, PR #8) and the configuration layer (`src/lms_config/`, PR #4) are imported and called. Their formulas are not copied.

## Stable tables

`organisation_id` and `person_id` are opaque text. The configuration schema uses `uuid` for the organisation. That difference is unresolved.

| Table | Role |
| --- | --- |
| `lms.loan_account` | Loan or lay-by child. Frozen name, identity number, and service address. One lay-by child per parent. |
| `lms.election_snapshot` | Elections copied at booking. Append-only. |
| `lms.schedule_version`, `lms.schedule_line` | Principal schedule versions, including the late-disbursement choice. |
| `lms.ledger_transaction`, `lms.ledger_entry` | Append-only double entry. Sequence assigned by `lms.assign_recognition_sequence`. Reversal value date enforced by `lms.enforce_reversal_value_date`. |
| `lms.default_episode` | Ceiling fixed at the opening of the episode. |
| `lms.service_fee_levy` | One parent-loan service fee per calendar month. |
| `lms.client_statement`, `lms.client_statement_balance` | One statement per person per organisation per period, with each loan's own opening and closing amounts. |

`lms.loan_bucket_balance(organisation_id, loan_id, bucket, as_of)` returns the debit-normal sum, or the credit-normal sum for `laybye_hold`, of entries whose value date is on or before `as_of`.

Row level security uses `current_setting('lms.organisation_id')` with no uuid cast.

## Stable signatures

```text
Ledger.book(organisation_id, person_id, product, organisation, recognised_at,
            cash_advanced_cents, frequency, schedule, identity_name,
            identity_number, service_address, quoted_disbursement=None,
            initiation_fee_cents=0, contractual_end=None) -> LoanAccount
Ledger.open_laybye(organisation_id, parent_loan_id, recognised_at, amount_cents,
                   identity_name, identity_number, service_address) -> LoanAccount
Ledger.accrue_day(organisation_id, loan_id, recognised_at, interest_cap_present,
                  repos=(), repo_annual=None) -> Accrual
Ledger.bill_interest(organisation_id, loan_id, recognised_at) -> Transaction | None
Ledger.levy_charge(organisation_id, loan_id, bucket, cents, due_on, recognised_at,
                   interest_cap_present, tariff_cents=None, repo_annual=None) -> Transaction
Ledger.levy_service_fee(organisation_id, loan_id, recognised_at, monthly_cents, due_on,
                        interest_cap_present, vat_rate=None, vat_registered=True,
                        opening=False, first_due=None) -> Transaction
Ledger.post_payment(organisation_id, loan_id, cents, recognised_at,
                    attributed_due_on=None) -> Transaction
Ledger.reverse(organisation_id, transaction_id, recognised_at) -> Transaction
Ledger.flag_default(organisation_id, loan_id, check_on, due_on, instalment_cents,
                    recognised_at) -> bool
Ledger.issue_statement(organisation_id, person_id, period_start, period_end) -> Statement
Ledger.clip_in_duplum() -> None
next_due_date(day, frequency) -> date
nominal_annual(periodic_rate, periods_per_year) -> Decimal
```

`LoanAccount` will not accept a second write of the frozen identity fields. `LedgerError.code` is the stable failure name (`election-unset`, `identity-missing`, `identity-frozen`, `service-fee-parent`, `service-fee-once`, `in-duplum-clip-off`, `additional-fee-order-unset`, `due-date-attribution-unset`, `due-date-unspecified`, `not-found`, and the others raised in `service.py`).

## How the ledger calls the other two layers

| Step | Call |
| --- | --- |
| Booking elections | `lms_config.locked.resolve_customer_settings` |
| Value date | `lms_config.calendar.value_date` |
| Same-day receipt order | `lms_config.locked.order_recognised_events` |
| Morning default check | `lms_config.locked.is_in_default_at_morning_check` |
| Interest base | `lms_config.locked.interest_bearing_cents` |
| Charged campaign rate | `lms_config.locked.campaign_rate` |
| In-duplum ceiling | `lms_config.locked.duplum_base_cents` |
| Clip switch | `lms_config.locked.IN_DUPLUM_CLIP_POSTS` (false; the clip is not posted) |
| Missing cap, repo, or tariff | `lms_config.context.require_reference_for_posting` |
| Nominal annual rate | `lms_config.locked.nominal_annual_rate` |
| Day-count weight and divisor | `lms.calc.interest.accrual_weight`, `divisor_days` |
| Daily interest | `lms.calc.interest.daily_interest_rands` |
| Unsecured repo path | `lms.calc.interest.personal_annual_rate` |
| Section 126 and prepayment | `lms.calc.allocation.allocate_payment` |
| Opening service fee | `lms.calc.fees.opening_service_fraction`, `service_fee_cents` |
| Half-up to cents | `lms.calc.money.to_cents` |

`lms_config.allocation` and `lms_config.duplum.post_month` are not called. The first still splits a short payment in proportion. The second still clips. Section 8 and section 7 forbid both.

The in-memory store is what the behavioural tests drive. The migration is what PostgreSQL enforces: append-only entries, the original reversal value date, frozen identity, the assigned sequence, and tenant isolation. There is no repository between them. A request-scoped connection that sets `lms.organisation_id` is session middleware, which this change does not add. The Enigma client is not added.

## Raised, not solved

The design note lists these in full. The ones that block a posting, rather than a workflow that was left out, are:

- Section 6 "outstanding balance" is not the same phrase as section 4's principal minus the hold. The interest base is `interest_bearing_cents`.
- Section 3's contractual ceiling may mean the discounted rate. The charged rate after the flag date is the base rate.
- The 30/360 weight is the calculator's reading, not a sentence in section 5.
- The clip stays off. The calculator note says it stays on.
- Null elections fail closed, including VAT and interest on deferred initiation, even though sections 9 and 10 also name a substantive default.
- A receipt after the flag date is not counted by the morning-check function. No second cure rule was added.
- The threshold instalment is a caller argument. An unattributed receipt fails.
- A short payment that must rank the further monthly fee against the named fee buckets fails.
- A principal receipt that must choose cash principal or excluded capitalised initiation fails.
- An unsecured campaign discount fails. The lock does not say which figure y% is subtracted from.
- Late disbursement is recorded and the instalment amounts are not rewritten. No residual write-off is posted.
- A due date the target month does not contain is refused.
- A blank identity is refused.
- Half-up is not compared with an affordability figure. The calculator half-ups the opening service fee; the configuration helper floors it.
- The caller supplies the number of periods for the nominal annual rate.
- One receipt is not split across the loan and the lay-by. Consolidation, credit life, funeral, and death are not posted.
- Statement periods are caller-supplied. Overlap is refused. That refusal is not a locked calendar.
- Organisation ids are text here and uuid in the configuration tables.

## Tests

`python3 -m pytest` on 28 October 2026: **104 passed**.

The two PostgreSQL tests are included. They were skipped until PostgreSQL 16 was installed in this environment, then they passed: the configuration audit and tenant test, and the ledger test for an append-only entry, a reversal rejected on the wrong value date, a frozen name, a sequence of 1 assigned by the trigger, `loan_bucket_balance` of 100000 cents, and no rows visible to the other organisation.

Ledger pins in `tests/test_ledger_account.py`:

- Net-balance interest with a linked lay-by, principal left gross, and the in-duplum ceiling left gross.
- A second default opens a new ceiling. The first counter is not reset by the payment. A levy above the new ceiling is posted in full, and the clip raises.
- A receipt pays interest, then collection costs, default administration, credit insurance, service fee, and initiation, and does not reach principal while initiation is still unpaid.
- A reversal recognised on a later day keeps the original value date, and that later day has no ledger value date of its own.
- A missing partial-prepayment, late-disbursement, deferred-initiation, or repo-fall election fails closed and stores no loan.
- An account booked for one organisation is not returned to another.

Also covered: both day counts through the calculator's weight, a zero rate and a zero fee, the campaign discount falling away on the flag date and staying off after cure, one service fee on the parent, capitalised initiation as principal, the prepayment choice, half-up of the accrued total, an unbilled memo that a receipt cannot take, and a collection cost with no tariff row.
